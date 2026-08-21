# llm/house_forecast.py — the participant puts a number down.
#
# ARCHITECTURE: for every question the Sunday Round opens, run one bounded
# tool loop and append the model's own probability to that question's
# `commitment_confidence` history as an actor='house' row. Nothing else: no
# card, no broadcast, no new table. The round's read path already knows how
# to render a house row (`api/rounds._round_state`) and how to score one.
#
# WHY: the participant argues about probability all week — node states,
# scenario weights, what the desk is mispricing — and has never once been on
# the hook for a number. That is a pundit. A pundit cannot be wrong, so its
# confidence carries no information and the two superforecasters in the room
# have no way to tell a good call from a fluent one. One row per question per
# week fixes that permanently: the same question, the same seal, the same
# clock, the same time-weighted Brier, and a public record of every time the
# machine was confidently wrong.
#
# TRADEOFF, and it is the one that decides the file's shape: a parse failure
# DROPS the question rather than guessing at the number. A missing house row
# reads as "the house sat this one out" and the read path already handles it
# (`house_committed: false`). A guessed one is a fabricated forecast on a
# scoreboard whose entire worth is that its numbers were really committed to.
# So the block is parsed strictly and a block that does not parse is lost.

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from models import Room
from scheduler import Job
from stakes.house import record_house_forecast

from .providers import LLMRequest, ProviderName
from .router import ModelRouter
from .tool_loop import ToolLoop
from .tools import build_registry

logger = logging.getLogger(__name__)

ENABLED_ENV = "HOUSE_FORECAST_ENABLED"
_ON_VALUES = ("1", "true", "yes", "on")

# Tighter than research's 15/300: this runs once per question per room per
# week, and a round of five questions across four rooms is twenty loops in
# one job tick. Enough iterations to check two or three live things and
# answer, not enough to go reading.
MAX_ITERATIONS = 6
LOOP_BUDGET_S = 90.0

# The outer bound. ToolLoop's own budget is checked BETWEEN iterations, so a
# single provider call that hangs is unbounded by it; this is what stops one
# stuck question from eating the whole round's tick.
QUESTION_BUDGET_S = 150.0

# Low, deliberately: the temperature that makes a turn in the room feel alive
# makes a probability jitter for no reason. The variance we want here comes
# from what the tools return, not from sampling.
TEMPERATURE = 0.3
MAX_TOKENS = 800

# The three fields of the answer block, in the order the shape teaches them.
_FIELDS = ("PROBABILITY", "BECAUSE", "WATCHING")

# WHY the shape is shown rather than described: an instruction written in
# capitals for emphasis comes back as a literal heading in the output (a
# clinical note once shipped with "First items of business:" as a bullet
# label, straight from the prompt's own emphasis). The labels below are
# capitalised because they are the literal tokens the parser reads, and the
# one worked example is the whole specification of the register.
HOUSE_SYSTEM = """You are a participant in this room and this is your own \
forecast — not advice, not a reading of what the humans think. It goes on the \
board beside theirs, under the same seal, scored on the same time-weighted \
Brier rule. You can be publicly and permanently wrong, which is the point.

Check before you commit. Your tools reach the room's live thesis state, market \
quotes, the desk's news and the room's own memory. Call the ones that would \
move your number and skip the rest. If a check fails, forecast without it and \
say nothing that implies you ran it.

Give a real number. Rounding to 0.5 to stay safe is the one answer that is \
always wrong, and 0.02 or 0.98 on a question written to be live says you did \
not read it.

Answer in exactly this shape, three lines, nothing before or after:

PROBABILITY: 0.34
BECAUSE: The Bank of Japan has moved at two of its last nine meetings and the \
statement language has not shifted since June.
WATCHING: The "patient" wording in the October statement."""


def house_forecast_enabled() -> bool:
    """Default OFF, read at call time.

    The inverse default of every other gate in `llm/` (which are opt-out) and
    for a reason: this one spends a tool loop per question per room per week
    and writes rows onto a scoreboard two people care about. It gets turned
    on deliberately, by name.
    """
    return os.getenv(ENABLED_ENV, "").strip().lower() in _ON_VALUES


def parse_house_block(raw: str) -> Optional[dict]:
    """The model's answer, or None if it did not answer in the shape.

    First occurrence of each label wins — a model that restates its number in
    a trailing aside ("PROBABILITY: see above") must not overwrite the one it
    committed to. Markdown emphasis around the label or the value is tolerated
    (`**PROBABILITY:** 0.72`) because it is a rendering artefact, not a
    different answer; anything else about the number is not tolerated at all.
    """
    fields: dict[str, str] = {}
    for line in (raw or "").splitlines():
        bare = line.strip().lstrip("*#-. ").strip()
        for key in _FIELDS:
            if key.lower() in fields:
                continue
            prefix = f"{key}:"
            if bare.upper().startswith(prefix):
                fields[key.lower()] = bare[len(prefix):].strip(" *")
                break

    try:
        probability = float(fields.get("probability", ""))
    except ValueError:
        return None
    # "72%", "0.72 (roughly)" and "somewhere near 0.7" all land here, and all
    # of them mean the model did not commit to a number we can score.
    if not 0.0 <= probability <= 1.0:
        return None
    because = fields.get("because") or ""
    if not because:
        return None
    return {
        "probability": probability,
        "because": because,
        "watching": fields.get("watching") or None,
    }


async def _as_room(conn, room) -> Room:
    """The full Room the tool registry needs, whatever the caller had.

    WHY: `question_round` carries rooms as a three-column asyncpg Record
    (id, name, trading_config) because that is all the drafter needed, while
    `build_registry` closes over `room.linked_book_id` and the router reads
    `room.primary_model`. Rather than widen that query — another agent's file
    — take either shape here and load what is missing.
    """
    if isinstance(room, Room):
        return room
    row = await conn.fetchrow("SELECT * FROM rooms WHERE id = $1", room["id"])
    if row is None:
        raise LookupError(f"room {room['id']} vanished mid-round")
    return Room(**dict(row))


def _question_prompt(room: Room, question: dict) -> str:
    lines = [
        f"Room: {room.name or 'this room'}. Today is "
        f"{datetime.now(timezone.utc).date().isoformat()}.",
        "",
        f"Question: {question['question']}",
        f"Resolves on: {question.get('source') or 'the named source'}, "
        f"read on {question.get('closes')}.",
    ]
    if question.get("base_rate"):
        lines.append(f"Base rate offered with the question: {question['base_rate']}.")
    lines += ["", "Your forecast."]
    return "\n".join(lines)


async def _forecast_one(conn, loop, room: Room, question: dict) -> Optional[dict]:
    # The budget bounds the MODEL, not the write: a timeout that fired
    # between the confidence row and its event would leave the history and
    # the event log disagreeing about what the house said.
    result = await asyncio.wait_for(loop.run(LLMRequest(
        messages=[{"role": "user", "content": _question_prompt(room, question)}],
        system=HOUSE_SYSTEM,
        model=room.primary_model,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )), QUESTION_BUDGET_S)
    routing = getattr(result, "routing", None)
    response = getattr(routing, "response", None)
    parsed = parse_house_block(getattr(response, "content", "") or "")
    if parsed is None:
        logger.info(
            "house forecast: unparseable block for %s — no row written",
            question.get("commitment_id"),
        )
        return None

    commitment_id = question["commitment_id"]
    if isinstance(commitment_id, str):
        commitment_id = UUID(commitment_id)
    # The question's OWN thread, not the room's first: the card is posted into
    # one thread and the confidence event has to land beside it.
    row = await conn.fetchrow(
        "SELECT room_id, thread_id FROM commitments WHERE id = $1", commitment_id,
    )
    if row is None:
        logger.warning("house forecast: commitment %s is gone", commitment_id)
        return None

    # WATCHING rides the same text column as BECAUSE rather than being
    # parsed and thrown away. `commitment_confidence` has one text field, and
    # `api/rounds._round_state` hands it to the card as `house.because` --
    # so this is the difference between the house saying what would change
    # its mind and the house saying it into a return value nobody reads.
    reasoning = parsed["because"]
    if parsed.get("watching"):
        reasoning = f"{reasoning} Watching: {parsed['watching']}"

    await record_house_forecast(
        conn,
        commitment_id=commitment_id,
        room_id=row["room_id"],
        thread_id=row["thread_id"],
        confidence=parsed["probability"],
        reasoning=reasoning,
    )
    return {
        "commitment_id": str(commitment_id),
        "probability": parsed["probability"],
        "because": parsed["because"],
        "watching": parsed["watching"],
        "reasoning": reasoning,
        "iterations": getattr(result, "iterations", 0),
        "degraded": getattr(result, "degraded", False),
        "tools": [t.get("name") for t in (getattr(result, "tool_trace", None) or [])],
    }


async def house_forecast(conn, room, questions: list[dict]) -> list[dict]:
    """One house forecast per freshly-opened round question.

    Returns one dict per question that actually landed a row. Never raises:
    a round that posted is a round that happened, and the house failing to
    forecast is a missing row, not a failed round.
    """
    if not house_forecast_enabled():
        return []
    live = [q for q in questions
            if q.get("commitment_id") and not q.get("binned")]
    if not live:
        return []

    try:
        room_model = await _as_room(conn, room)
        registry = build_registry(room_model, conn)
        router = ModelRouter(
            primary_provider=ProviderName(room_model.primary_provider),
            fallback_provider=ProviderName(room_model.fallback_provider),
            primary_model=room_model.primary_model,
            fallback_model=room_model.provoker_model,
        )
        loop = ToolLoop(
            router, registry,
            max_iterations=MAX_ITERATIONS, loop_budget_s=LOOP_BUDGET_S,
        )
    except Exception:  # noqa: BLE001
        # A forecast with no tools is a forecast from a stale training set on
        # a question about this week. Sit the round out rather than post one.
        # Everything the loop needs is built here so that a room whose
        # provider names or columns are not what this expects costs the round
        # a house forecast, never the round itself.
        logger.exception("house forecast: cannot build the loop for this room")
        return []

    recorded: list[dict] = []
    for question in live:
        try:
            landed = await _forecast_one(conn, loop, room_model, question)
        except Exception as e:  # noqa: BLE001 — one question the house could
            # not forecast must not cost the round its other four.
            logger.warning(
                "house forecast failed for %s: %s", question.get("commitment_id"), e,
            )
            continue
        if landed is not None:
            recorded.append(landed)
    return recorded


# ── the sweep ────────────────────────────────────────────────────────────
#
# WHY the house does NOT forecast inline inside `question_round`, which is
# where it obviously belongs and where the first draft of this put it:
# `scheduler._tick` runs jobs SERIALLY in a plain `for` loop, awaiting each
# one. A round of five questions across four rooms is twenty tool loops at up
# to QUESTION_BUDGET_S each — worst case fifty minutes during which the
# silence sweep, the heartbeat, the reconcile and every other job simply do
# not run. The round would have been posted correctly and the house would
# have taken the scheduler down with it.
#
# So it is a bounded sweep instead, and the thing that makes that acceptable
# rather than merely cheaper is the seal: the house's number is invisible
# until BOTH humans have committed. It does not need to be there when the
# card lands. It needs to be there before they finish arguing.
#
# The sweep is idempotent BY QUERY — a question with a house row is not
# selected — so a restart mid-drain costs nothing and there is no flag column
# to keep honest.
SWEEP_INTERVAL_S = 900
SWEEP_QUESTION_CAP = 2
SWEEP_BUDGET_S = 330.0
# A round question the house never got to inside a week is one the humans have
# been forecasting without it. Joining late would score it on a shorter,
# EASIER window than theirs (see api/rounds._score_question), so it sits out.
SWEEP_MAX_AGE = "7 days"


async def _unforecast(conn) -> list:
    return await conn.fetch(
        f"""SELECT c.id AS commitment_id, c.claim, c.resolution_criteria,
                   c.deadline, c.room_id, c.thread_id
              FROM commitments c
             WHERE c.category = 'round'
               AND c.status = 'active'
               AND c.deadline > now()
               AND c.created_at > now() - interval '{SWEEP_MAX_AGE}'
               AND NOT EXISTS (
                   SELECT 1 FROM commitment_confidence cc
                    WHERE cc.commitment_id = c.id AND cc.actor = 'house')
             ORDER BY c.created_at ASC, c.deadline ASC"""
    )


async def house_forecast_sweep(ctx) -> dict:
    """Give the house its number on round questions that do not have one yet."""
    if not house_forecast_enabled():
        return {"skipped": "disabled"}

    started = asyncio.get_running_loop().time()
    detail: dict = {"forecast": 0, "rooms": {}}
    async with ctx.pool.acquire() as conn:
        pending = await _unforecast(conn)
        if not pending:
            return {"skipped": "nothing_pending"}

        by_room: dict = {}
        for row in pending:
            by_room.setdefault(row["room_id"], []).append(row)

        for room_id, rows in by_room.items():
            if detail["forecast"] >= SWEEP_QUESTION_CAP:
                detail["rooms"][str(room_id)] = "cap_reached"
                continue
            if asyncio.get_running_loop().time() - started > SWEEP_BUDGET_S:
                detail["rooms"][str(room_id)] = "budget_spent"
                continue
            room = await conn.fetchrow(
                "SELECT * FROM rooms WHERE id = $1", room_id,
            )
            if room is None:
                continue
            take = rows[: SWEEP_QUESTION_CAP - detail["forecast"]]
            questions = [
                {
                    "commitment_id": str(r["commitment_id"]),
                    "question": r["claim"],
                    "source": r["resolution_criteria"],
                    "closes": r["deadline"].date().isoformat()
                    if r["deadline"] else None,
                }
                for r in take
            ]
            landed = await house_forecast(conn, room, questions)
            detail["forecast"] += len(landed)
            detail["rooms"][str(room_id)] = len(landed)
    detail["pending_after"] = max(0, len(pending) - detail["forecast"])
    return detail


def register_house_forecast_jobs(scheduler) -> None:
    scheduler.register(Job(
        "house_forecast_sweep", SWEEP_INTERVAL_S, house_forecast_sweep,
        enabled_env=ENABLED_ENV,
    ))
