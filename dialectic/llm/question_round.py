# llm/question_round.py — the Sunday Round.
#
# ARCHITECTURE: one scheduled job that mints a round of forecastable questions
# per active room, posts them as a single annotator card, and lets each human
# record — and revise — their own probability until the question closes.
#
# WHY this exists, and why it is shaped like this: the calibration spine
# (claims ledger, deterministic oracle, Brier/BSS, calibration bars, the paper
# book) shipped 2026-08-18 and by 2026-08-20 held five predictions, four of
# them the same duplicated gate-proof row. Nothing was wrong with the scoring;
# nothing was ever ASKED. Every path into the ledger depended on someone
# happening to say something falsifiable and someone else happening to tap
# Accept — and the accept card asked for neither a deadline nor a confidence,
# so even the two claims that were accepted could never be scored.
#
# The owners were IARPA/ACE Good Judgment Project superforecasters. The thing
# they said they missed was the arrival of a new round of questions. So the
# fix is not another extractor; it is a question source with a clock.
#
# THE GJP CONTRACT, and it is the whole quality bar:
#   - Binary. One event, one outcome. No compound clauses ("and"/"or" joining
#     two independently-resolvable events) — those are two questions.
#   - A NAMED resolution source, decided before anyone forecasts. A question
#     that resolves on "the consensus view" resolves on an argument.
#   - A hard close date. Ambiguity about WHEN is ambiguity about WHETHER.
#   - Forecasts are REVISABLE until close. This is not a nicety: GJP scored
#     the time-weighted average Brier across a question's life, so updating on
#     news is the skill being measured. `prediction_confidence` is already an
#     append-only per-actor history with recorded_at — the substrate was
#     always there, nothing ever wrote a second row to it.
#
# TRADEOFF: questions are drafted by the model against the room's live thesis
# and the week's readings, then posted WITHOUT human review. A bad question is
# visible and skippable — nobody is forced to forecast it — and the cost of a
# review gate is that the round stops arriving, which is the one failure this
# job exists to prevent. Resolution stays human-tapped, as everywhere else.

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from models import EventType, MessageType, SpeakerType
from scheduler import Job, SchedulerContext
from stakes.manager import CommitmentManager
from transport.websocket import MessageTypes, OutboundMessage
from llm.providers import LLMRequest, ProviderName, get_provider

logger = logging.getLogger(__name__)

# Sunday. `date.weekday()` is Monday=0, so Sunday is 6.
ROUND_WEEKDAY = 6

def questions_per_round() -> int:
    """How many questions a room gets. Env-tunable because the right number is
    a matter of appetite, not engineering: a question nobody forecasts scores
    nobody, so covering less and answering all of it beats the reverse.
    Clamped to 1..10 — a round of thirty is a chore, and a round of zero is a
    silent job that looks broken."""
    try:
        raw = int(os.getenv("QUESTIONS_PER_ROUND", "5"))
    except ValueError:
        return 5
    return max(1, min(raw, 10))


# The default, and what the tests pin. Read questions_per_round() at call time.
QUESTIONS_PER_ROUND = 5
QUESTION_MODEL = "claude-sonnet-5"

# Mixed horizons, the way a real round arrives: something that resolves before
# you have forgotten you forecast it, and something that makes you commit to a
# view you cannot walk back next week.
HORIZONS_DAYS = (14, 30, 90)


ENABLED_ENV = "QUESTION_ROUND_ENABLED"


def is_round_day(today: date) -> bool:
    """Sunday only. The scheduler has daily slots, not weekly ones, so the
    job wakes every day at its hour and returns immediately six days out of
    seven — cheaper than teaching the scheduler a new cadence for one job."""
    return today.weekday() == ROUND_WEEKDAY


ROUND_SYSTEM = """You write forecasting questions for two former IARPA/ACE Good \
Judgment Project superforecasters. They know the craft; do not explain it to \
them, and do not pad.

Every question MUST satisfy all four:
1. BINARY — exactly one event with a yes/no outcome. If you need "and" or "or" \
to join two separately-resolvable events, you have two questions; pick one.
2. NAMED RESOLUTION SOURCE — the specific public source that will settle it \
(e.g. "EIA Weekly Petroleum Status Report", "BLS CPI release", "Bank of Japan \
policy statement"). Never "consensus", "reporting suggests", or "widely viewed".
3. HARD CLOSE DATE — the exact date the outcome is read off that source.
4. NON-TRIVIAL — a question whose answer is already 2% or 98% teaches nothing. \
Aim for genuine uncertainty. State a base rate when one exists.

Write in their register: plain, specific, no hedging, no throat-clearing.

Return EXACTLY this format, one block per question, separated by a line of ---:
QUESTION: <the binary question, ending in a question mark>
SOURCE: <the named resolution source>
RESOLVES: <YYYY-MM-DD>
BASE_RATE: <a percentage and where it comes from, or NONE>
WHY: <one sentence on why this is live for these two right now>
---
No preamble, no numbering, no commentary outside the blocks."""


def _horizon_dates(today: date) -> list[str]:
    out = []
    for i in range(questions_per_round()):
        out.append((today + timedelta(days=HORIZONS_DAYS[i % len(HORIZONS_DAYS)])).isoformat())
    return out


def _build_prompt(room_name: str, thesis_context: str, readings: list[dict],
                  today: date) -> str:
    lines = [
        f"Room: {room_name}. Today is {today.isoformat()} (a Sunday).",
        "",
        f"Write {questions_per_round()} questions for this week's round.",
        "Spread the close dates across roughly these horizons: "
        + ", ".join(_horizon_dates(today)) + ".",
        "",
    ]
    if thesis_context:
        lines += ["The room's live thesis state:", thesis_context, ""]
    if readings:
        lines.append("What the room read this week:")
        for item in readings[:8]:
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()
            if title:
                lines.append(f"- {title}: {summary[:180]}")
        lines.append("")
    lines.append(
        "Ground the questions in the above where you can. A question that "
        "could have been written without reading any of it is a wasted slot."
    )
    return "\n".join(lines)


def parse_round(raw: str, *, today: Optional[date] = None) -> list[dict]:
    """Parse the model's blocks into questions, dropping anything malformed.

    A question missing its source or its close date is NOT repaired — an
    invented resolution source is exactly the failure the format exists to
    prevent, and a question nobody can settle is worse than one fewer question.
    """
    today = today or date.today()
    questions: list[dict] = []
    for block in raw.split("---"):
        fields: dict[str, str] = {}
        for line in block.strip().splitlines():
            line = line.strip()
            for key in ("QUESTION", "SOURCE", "RESOLVES", "BASE_RATE", "WHY"):
                prefix = f"{key}:"
                if line.upper().startswith(prefix):
                    fields[key.lower()] = line[len(prefix):].strip()
                    break
        if not fields.get("question") or not fields.get("source"):
            continue
        raw_date = (fields.get("resolves") or "").strip()
        try:
            closes = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if closes <= today:
            # A question that has already closed cannot be forecast.
            continue
        base = (fields.get("base_rate") or "").strip()
        questions.append({
            "question": fields["question"],
            "source": fields["source"],
            "closes": closes.isoformat(),
            "base_rate": None if base.upper() in ("", "NONE") else base,
            "why": (fields.get("why") or "").strip() or None,
            # NOTE what is deliberately NOT here: the forecasts. They live in
            # commitment_confidence rows, one per (question, human, revision).
            # schema.sql:249-259 states the rule, about reactions: "Rows rather
            # than a JSONB blob on the message: concurrent reactions cannot
            # clobber each other." Two people setting a number on the same card
            # within one round trip is exactly that race, and there is no
            # array-append-into-JSONB idiom in this codebase to make it safe.
            # `commitment_id` is filled in once the row exists.
            "commitment_id": None,
            "binned": False,
        })
    return questions


def render_round(questions: list[dict], today: date) -> str:
    lines = [f"**The Sunday Round — {today.isoformat()}**", ""]
    for i, q in enumerate(questions, 1):
        lines.append(f"**{i}. {q['question']}**")
        detail = f"closes {q['closes']} · resolves on {q['source']}"
        if q.get("base_rate"):
            detail += f" · base rate {q['base_rate']}"
        lines.append(detail)
        if q.get("why"):
            lines.append(f"_{q['why']}_")
        lines.append("")
    lines.append("Set your own number on each. Revise any time before it closes — "
                 "the update history is what gets scored, not your first guess.")
    return "\n".join(lines)


async def _recent_readings(conn, room_id) -> list[dict]:
    rows = await conn.fetch(
        """SELECT title, summary FROM reading_items
           WHERE room_id = $1 AND created_at > now() - interval '7 days'
           ORDER BY created_at DESC LIMIT 8""",
        room_id,
    )
    return [dict(r) for r in rows]


async def _open_questions(conn, room_id, thread_id, msg_id, questions: list[dict]):
    """One commitments row per question, so a round question is born WITH its
    deadline and its forecasts have something to hang off.

    This is also the fix for the defect that emptied the ledger: every other
    path into it produced claims with deadline NULL and no confidence, which
    api/stakes_relay.py then correctly refused to relay. A round question
    cannot be malformed that way — the close date IS the question.

    category='round' and the source_message_id are what make these findable;
    neither column has a check constraint, so no migration is needed.
    """
    manager = CommitmentManager(conn)
    for question in questions:
        created = await manager.create_commitment(
            room_id=room_id,
            claim=question["question"],
            resolution_criteria=(
                f"Resolves on {question['source']} as read on {question['closes']}."
            ),
            created_by_user_id=None,   # drafted, not claimed by either human
            thread_id=thread_id,
            source_message_id=msg_id,
            deadline=datetime.fromisoformat(question["closes"]).replace(
                tzinfo=timezone.utc,
            ),
            category="round",
            initial_confidence=None,   # nobody has forecast it yet
        )
        question["commitment_id"] = str(created["id"])


async def _post_round(conn, ctx, room, questions: list[dict], today: date) -> str:
    msg_id = uuid4()
    now = datetime.now(timezone.utc)
    thread_row = await conn.fetchrow(
        "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
        room["id"],
    )
    if thread_row is None:
        return "no_thread"
    content = render_round(questions, today)
    metadata = {
        "source": "question_round",
        "question_round": {
            "opened": today.isoformat(),
            "questions": questions,
        },
    }
    await conn.execute(
        """INSERT INTO messages
           (id, thread_id, sequence, created_at, speaker_type, user_id,
            message_type, content, metadata)
           VALUES (
               $1, $2,
               (SELECT COALESCE(MAX(sequence), 0) + 1
                FROM messages WHERE thread_id = $2),
               $3, $4, NULL, $5, $6, $7
           )""",
        msg_id, thread_row["id"], now,
        SpeakerType.LLM_ANNOTATOR.value, MessageType.TEXT.value,
        content, metadata,
    )
    # After the message row exists — source_message_id is a foreign key — and
    # before the broadcast, so the payload carries the ids the card needs.
    await _open_questions(conn, room["id"], thread_row["id"], msg_id, questions)
    metadata["question_round"]["questions"] = questions
    await conn.execute(
        """UPDATE messages SET metadata = $2 WHERE id = $1""",
        msg_id, metadata,
    )
    await conn.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), now, EventType.ANNOTATION_CREATED.value,
        room["id"], thread_row["id"],
        {"message_id": str(msg_id), "source": "question_round"},
    )
    if ctx.broadcast is not None:
        await ctx.broadcast(room["id"], OutboundMessage(
            type=MessageTypes.MESSAGE_CREATED,
            payload={
                "id": str(msg_id),
                "thread_id": str(thread_row["id"]),
                "speaker_type": SpeakerType.LLM_ANNOTATOR.value,
                "message_type": MessageType.TEXT.value,
                "content": content,
                "created_at": now.isoformat(),
                "metadata": metadata,
            },
        ))
    return str(msg_id)


async def _already_ran_today(conn, room_id, today: date) -> bool:
    """A round is one per room per day, whatever the scheduler retries."""
    return bool(await conn.fetchval(
        """SELECT 1 FROM messages m
           JOIN threads t ON t.id = m.thread_id
           WHERE t.room_id = $1
             AND m.metadata->>'source' = 'question_round'
             AND m.created_at >= $2
           LIMIT 1""",
        room_id, datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
    ))


async def question_round(ctx: SchedulerContext) -> dict:
    """Sunday: post one round of forecastable questions per active room."""
    today = datetime.now(timezone.utc).date()
    if not is_round_day(today):
        return {"skipped": "not_sunday"}

    detail: dict[str, Any] = {}
    async with ctx.pool.acquire() as conn:
        rooms = await conn.fetch(
            """SELECT DISTINCT r.id, r.name, r.trading_config
               FROM rooms r
               JOIN threads t ON t.room_id = r.id
               JOIN messages m ON m.thread_id = t.id
               WHERE m.created_at > now() - interval '14 days'
                 AND NOT r.is_home"""
        )
        for room in rooms:
            key = str(room["id"])
            if await _already_ran_today(conn, room["id"], today):
                detail[key] = "already_ran"
                continue
            try:
                readings = await _recent_readings(conn, room["id"])
                thesis = ""
                config = room["trading_config"]
                if isinstance(config, dict):
                    thesis = str(config.get("title") or "")
                    phase = config.get("cascadePhase")
                    if phase:
                        thesis += f" — phase {phase}"
                provider = get_provider(ProviderName.ANTHROPIC)
                response = await provider.complete(LLMRequest(
                    messages=[{
                        "role": "user",
                        "content": _build_prompt(
                            room["name"] or "this room", thesis, readings, today,
                        ),
                    }],
                    system=ROUND_SYSTEM,
                    model=QUESTION_MODEL,
                    max_tokens=1600,
                    temperature=0.7,
                ))
                questions = parse_round(response.content, today=today)
                if not questions:
                    detail[key] = "no_valid_questions"
                    continue
                msg_id = await _post_round(conn, ctx, room, questions, today)
                detail[key] = {"message_id": msg_id, "questions": len(questions)}
            except Exception as e:  # noqa: BLE001 — one bad room must not
                # take the round down for the others.
                logger.warning("question round failed for room %s: %s", key, e)
                detail[key] = f"error: {e}"
    return detail


def register_question_round_jobs(scheduler) -> None:
    """Sunday 09:00 CT. Registered daily because the scheduler has interval
    buckets and wall-clock daily slots but no weekly cadence; is_round_day()
    returns immediately on the other six mornings, which is cheaper than
    teaching the scheduler a new cadence for one job."""
    scheduler.register(Job(
        "question_round", 86400, question_round,
        enabled_env=ENABLED_ENV,
        daily_at="09:00", daily_tz="America/Chicago",
    ))
