# llm/round_close_watch.py — the settlement, and the credit line.
#
# ARCHITECTURE: one hourly job with two sweeps over `commitments` where
# category='round'.
#
#   1. SETTLE — a question whose deadline has passed and whose status is
#      still 'active'. The participant takes the question's OWN named
#      resolution source (it is written into `resolution_criteria` at draft
#      time, which is the whole point of the GJP form), goes and looks with
#      the real tool registry, and posts one annotator card carrying the
#      evidence and a SUGGESTED verdict.
#
#   2. CREDIT — a question a human has since settled through
#      POST /rooms/{id}/rounds/{cid}/resolve. The room gets one flat
#      sentence naming who called it, at what number, on what date, against
#      what the other one said.
#
# THE LAW, and it is not negotiable: this job gathers evidence and suggests.
# It never resolves. `api/rounds.resolve_question` is the only write, and a
# human's tap is the only thing that reaches it. The first wrong
# auto-settlement costs the ledger its standing permanently and there is no
# way to earn that back — which is exactly why the machine is allowed to do
# the tedious part (finding out what happened) and none of the binding part.
#
# WHY this exists: `time_weighted_brier` shipped 2026-08-18 and had never
# once run on real data by 2026-08-20. Not because it was wrong — because
# nothing ever CLOSED. A question would pass its deadline and sit there
# 'active' forever, since resolution needed a human to remember a date they
# had no reason to be holding. A round that never settles is a round that
# scores nobody, which is the same failure the round itself was built to fix
# one layer up.
#
# WHY the credit line is in this file rather than in the resolve door: the
# door is a request/response, and the line needs an LLM call plus a
# validation pass that can DROP it. Making a human's tap wait on that (or
# fail with it) trades the thing that matters for the thing that is funny.
# Here it lands within the hour, and a dropped line costs nobody a 500.
#
# GUARDRAILS:
#   - enabled_env ROUND_CLOSE_ENABLED (kill switch, default on) — this job
#     spends tool-loop money on a wall-clock timer.
#   - SETTLE_RUN_CAP / CREDIT_RUN_CAP per run, so a backlog drains over
#     hours instead of in one bill.
#   - Idempotence by QUERY, not by a flag column: a settlement card and a
#     credit line each carry their commitment_id in message metadata, and
#     each sweep reads back what it already posted. The scheduler retries
#     and the service restarts often; neither may double-post.
#   - Every per-question failure is caught and recorded in the detail dict.
#     One dead question must not strand the rest of the backlog.

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from models import EventType, MessageType, SpeakerType
from scheduler import Job, SchedulerContext
from stakes.house import split_by_actor
from transport.websocket import MessageTypes, OutboundMessage
from llm.providers import LLMRequest, ProviderName, get_provider
from llm.router import ModelRouter
from llm.tool_loop import ToolLoop
from llm.tools import build_registry
# The verdict vocabulary and the tolerant JSON parse are already settled in
# prediction_watch, which asks the same question of a model about a different
# kind of claim. Two copies of "did this land?" would drift apart on the
# first vocabulary change.
from llm.prediction_watch import _parse_verdict

logger = logging.getLogger(__name__)

ENABLED_ENV = "ROUND_CLOSE_ENABLED"
INTERVAL_S = 3600

SETTLEMENT_SOURCE = "round_settlement"
CREDIT_SOURCE = "round_credit"

SETTLE_RUN_CAP = 3
CREDIT_RUN_CAP = 3
# How far back the credit sweep looks. A question settled a fortnight ago has
# been absorbed; a line about it now reads as a bot catching up, not as a
# note in the margin. Bounds the scan too.
CREDIT_WINDOW = "7 days"
# The backlog scan. Larger than either cap on purpose: the caps decide what
# gets WORKED this hour, this decides what is visible to the dedup filter.
BACKLOG_SCAN = 50

# A settlement is a research errand, not a conversation: several checks
# against a named source, then a verdict. Between the ordinary turn (5/60)
# and the deep dive (15/300).
MAX_ITERATIONS = 8
LOOP_BUDGET_S = 180

CREDIT_MODEL = "claude-sonnet-5"

_MONTHS = {
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "sept",
    "september", "oct", "october", "nov", "november", "dec", "december",
}
_NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "half", "no", "zero",
}


SETTLE_SYSTEM = """A forecasting question has reached its close date. Find out \
what actually happened.

The question names the source that settles it. Go to that source with the \
tools you have — thesis news, article extraction, live quotes, the room's own \
reading. Check what it says. If the source cannot be reached or does not \
settle the question, say so; a wrong verdict is far more expensive than an \
unclear one, because a human is about to act on this.

You are not settling anything. A person reads your answer and taps the \
verdict themselves.

Respond with only this JSON object and nothing else:
{"verdict": "correct" | "incorrect" | "unclear", "rationale": "one or two \
sentences, naming what you actually read"}"""


# The register is taught by the pair below and nowhere else. Describing it in
# adjectives puts the adjectives in the output — this codebase has shipped
# "First items of business:" into a live document that way.
CREDIT_SYSTEM = """You write the one line that goes under a forecasting \
question after it settles.

Good:
Dan, 0.85, Aug 17 — three days before the print, while Amo stood at 0.40.

Bad:
Incredible call by Dan! He absolutely nailed this one at 0.85 while Amo was \
way off at 0.40 — a masterclass in reading the data.

One sentence. Every name, number and date in it must come from the packet \
below; if something is not in the packet you do not know it. No greeting, no \
sign-off, no quotation marks around the line."""


# ── the settle sweep ─────────────────────────────────────────────────


async def _posted_ids(conn, source: str) -> set:
    """Commitment ids this sweep has already posted a card for.

    The dedup gauge, mirroring prediction_watch._already_proposed. It is a
    query rather than a column because a round question's row belongs to the
    stakes ledger — a `settlement_posted` flag there would be this job's
    private bookkeeping living in the table two other subsystems score from.
    """
    rows = await conn.fetch(
        """SELECT m.metadata->($1::text)->>'commitment_id' AS commitment_id
           FROM messages m
           WHERE m.metadata->>'source' = $1""",
        source,
    )
    return {r["commitment_id"] for r in rows if r["commitment_id"]}


def _as_uuids(done: set) -> list:
    """The done set as UUIDs for `= ANY($n::uuid[])`.

    It is carried as strings because it is read out of message metadata,
    where everything is a string. A malformed entry is dropped rather than
    raised on: the cost of dropping one is a duplicate card, and the cost of
    raising is the whole sweep.
    """
    out = []
    for value in done:
        try:
            out.append(UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            continue
    return out


async def _closed_questions(conn, done: set, limit: int) -> list:
    """Round questions past their close date that nobody has settled.

    THE DONE-SET IS EXCLUDED IN SQL, BEFORE THE LIMIT, and that ordering is
    the whole correctness of this sweep. THE LAW forbids this job writing to
    `commitments`, so a question that has been carded but not tapped stays
    `status='active'` with `deadline < now()` FOREVER. Filtering after
    `LIMIT BACKLOG_SCAN` meant those rows kept their places in the window:
    once BACKLOG_SCAN of them accumulated, every scan returned nothing but
    already-carded questions, the Python filter emptied the list, and the
    settlement stopped — no error, no log, an empty detail identical to
    "nothing closed this hour". Partial starvation starts long before the
    limit, because done rows crowd out live ones by `deadline ASC`.
    """
    rows = await conn.fetch(
        """SELECT id, room_id, claim, resolution_criteria, deadline
           FROM commitments
           WHERE category = 'round' AND status = 'active' AND deadline < now()
             AND NOT (id = ANY($2::uuid[]))
           ORDER BY deadline ASC LIMIT $1""",
        BACKLOG_SCAN, _as_uuids(done),
    )
    return list(rows)[:limit]


async def _gather(db, room, question) -> Optional[dict]:
    """One tool-loop errand against the question's own resolution source.

    Returns {"verdict", "rationale", "checked"} or None when the model gave
    nothing usable. Every failure below degrades to a weaker suggestion or to
    None; none of them raises, because a question that cannot be researched
    still deserves the card that asks a human to look.
    """
    try:
        registry = build_registry(room, db)
    except Exception:  # noqa: BLE001
        logger.exception("settlement: tool registry unavailable")
        registry = None

    errand = [
        f"QUESTION: {question['claim']}",
        f"RESOLUTION SOURCE: {question['resolution_criteria']}",
    ]
    if question["deadline"]:
        errand.append(f"CLOSED: {question['deadline'].date().isoformat()}")

    request = LLMRequest(
        messages=[{"role": "user", "content": "\n".join(errand)}],
        system=SETTLE_SYSTEM,
        model=room.primary_model,
        max_tokens=1024,
        temperature=0.2,
    )
    router = ModelRouter(
        primary_provider=ProviderName(room.primary_provider),
        fallback_provider=ProviderName(room.fallback_provider),
        primary_model=room.primary_model,
        fallback_model=room.provoker_model,
    )
    try:
        if registry is None:
            result = await router.route(request)
            trace = []
        else:
            loop = ToolLoop(router, registry,
                            max_iterations=MAX_ITERATIONS,
                            loop_budget_s=LOOP_BUDGET_S)
            outcome = await loop.run(request)
            result, trace = outcome.routing, outcome.tool_trace
    except Exception:  # noqa: BLE001 — a dead provider is a quiet skip.
        logger.exception("settlement: research failed for %s", question["id"])
        return None

    if result is None or not result.success or result.response is None:
        return None
    verdict = _parse_verdict(result.response.content or "")
    if verdict is None:
        return None
    # What it ACTUALLY reached, not what it says it reached. A tool that
    # failed is evidence about the evidence, so failures stay in the list.
    verdict["checked"] = [
        {"tool": entry.get("tool") or entry.get("name"), "ok": bool(entry.get("ok"))}
        for entry in trace
    ]
    return verdict


def render_settlement(question, finding: dict) -> str:
    """Deterministic card text — the claim, then what was found."""
    closed = (question["deadline"].date().isoformat()
              if question["deadline"] else "its close date")
    lines = [
        f"🔔 Closed {closed} — {question['claim']}",
        f"Resolves on: {question['resolution_criteria']}",
        f"Looks {finding['verdict']} — {finding['rationale']}",
    ]
    reached = [c["tool"] for c in finding.get("checked", []) if c["ok"]]
    if reached:
        lines.append("Checked: " + ", ".join(sorted(set(reached))))
    lines.append("Your call — nothing is scored until one of you taps it.")
    return "\n".join(lines)


# ── the credit line ──────────────────────────────────────────────────



def fact_packet(question, history) -> dict:
    """Everything the credit line is allowed to know, and nothing else.

    ARCHITECTURE: this is the validation surface as much as it is the prompt.
    `_phrase` sees only this dict, and the output is then checked back
    against it — so a number or a name that is not here cannot survive.
    Widening the packet widens what the model may say, which is why days-to-
    close is computed here rather than left for the model to subtract.
    """
    humans, house_rows = split_by_actor(history)
    close = question["resolved_at"] or question["deadline"]
    forecasters = []

    def _add(name: str, rows) -> None:
        entries = []
        for row in rows:
            recorded = row["recorded_at"]
            entry = {
                "forecast": round(float(row["confidence"]), 4),
                "on": recorded.date().isoformat(),
            }
            if close is not None:
                entry["days_before_close"] = (close.date() - recorded.date()).days
            entries.append(entry)
        if entries:
            forecasters.append({"name": name, "forecasts": entries,
                                "final": entries[-1]["forecast"],
                                "revisions": len(entries)})

    for user_id in dict.fromkeys(h["user_id"] for h in humans):
        rows = [h for h in humans if h["user_id"] == user_id]
        _add(rows[0]["display_name"] or "Someone", rows)
    if house_rows:
        _add("the house", house_rows)

    return {
        "question": question["claim"],
        "outcome": question["resolution"],
        "settled_on": close.date().isoformat() if close is not None else None,
        "closed_on": (question["deadline"].date().isoformat()
                      if question["deadline"] else None),
        "forecasters": forecasters,
    }


def _packet_numbers(packet: dict) -> set:
    """Every number quotable from the packet, including the ones inside its
    strings (a date carries its day and its year) and percent renderings of
    a probability. Rounded, because 0.40 and 0.4 are the same claim."""
    blob = json.dumps(packet)
    out = set()
    for token in re.findall(r"\d+(?:\.\d+)?", blob):
        value = float(token)
        out.add(round(value, 4))
        if value <= 1:
            out.add(round(value * 100, 4))
    return out


def _packet_words(packet: dict) -> set:
    """Every word the packet contains, lowercased."""
    return set(re.findall(r"[a-z]+", json.dumps(packet).lower()))


def validate_line(line: str, packet: dict) -> bool:
    """True when every number and every proper noun in the line is the
    packet's own.

    WHY both checks: a fabricated number misstates the record, and a
    fabricated NAME credits the wrong person — which in a two-person ledger
    is the worst output this system could produce. Capitalised tokens are
    the cheap proxy for a name; months and counting words are allowed
    because they are English, not claims about who said what.
    """
    if not line or len(line.splitlines()) != 1:
        return False
    numbers = _packet_numbers(packet)
    for token in re.findall(r"\d+(?:\.\d+)?", line):
        if round(float(token), 4) not in numbers:
            return False
    words = _packet_words(packet)
    # `_SENTENCE_WORDS` rather than skipping the first token: a capitalised
    # word at position one is USUALLY sentence-initial English ("The house,
    # 0.85 ...") and was being dropped whenever the packet happened not to
    # contain "the", which is most packets. But exempting position one
    # outright lets a fabricated name through in exactly the place a credit
    # line puts a name -- "Sarah, 0.85 ..." -- so every token is checked and
    # the allowance is a small vocabulary instead of a position.
    for token in re.findall(r"\b[A-Z][A-Za-z]+\b", line):
        low = token.lower()
        if low in words or low in _MONTHS or low in _NUMBER_WORDS \
                or low in _SENTENCE_WORDS:
            continue
        return False
    if not _pairs_are_the_packets(line, packet):
        return False
    outcome = packet.get("outcome")
    for word in ("correct", "incorrect"):
        # "incorrect" contains "correct", so test the longer one first via
        # word boundaries rather than substring.
        if re.search(rf"\b{word}\b", line.lower()) and word != outcome:
            return False
    return True


# Capitalised because English capitalises them, not because they name anyone.
# Only ever consulted for tokens AFTER the first, so this is a small list on
# purpose -- widening it widens what an invented proper noun can hide behind.
_SENTENCE_WORDS = frozenset({
    "the", "a", "an", "it", "both", "after", "before", "by", "and", "but",
    "that", "this", "while", "when", "neither", "either", "no", "not",
})

# How far after a name a number is still plausibly ABOUT that name. Long
# enough for "Dan, at 0.85" and "Dan came in at 0.85"; short enough that the
# next clause's number is not swept in.
_PAIR_WINDOW = 24


def _pairs_are_the_packets(line: str, packet: dict) -> bool:
    """Every number sitting next to a name must be THAT forecaster's own.

    WHY this is separate from the two checks above, and why they are not
    enough: they test the number set and the name set INDEPENDENTLY, so a
    line that swaps the attributions -- "Amo, 0.85 ... while Dan stood at
    0.40" when it was the other way round -- uses only packet numbers and
    only packet names and sails through. This module's own docstring calls
    crediting the wrong human the worst output this system could produce,
    and the fence that was supposed to stop it stopped only the invented
    stranger, which is not what a model reading the packet will produce.
    """
    for forecaster in packet.get("forecasters", []):
        name = forecaster.get("name") or ""
        if not name:
            continue
        mine = set()
        for entry in forecaster.get("forecasts", []):
            value = entry.get("forecast")
            if value is None:
                continue
            mine.add(round(float(value), 4))
            mine.add(round(float(value) * 100, 4))
        for match in re.finditer(re.escape(name), line, re.IGNORECASE):
            window = line[match.end():match.end() + _PAIR_WINDOW]
            found = re.search(r"\d+(?:\.\d+)?", window)
            if found is None:
                continue
            if round(float(found.group()), 4) not in mine:
                return False
    return True


async def _phrase(packet: dict) -> Optional[str]:
    """One model call for the line. Any failure is a missing joke, never an
    error — the caller drops it and the settlement stands on its own."""
    try:
        provider = get_provider(ProviderName.ANTHROPIC)
        response = await provider.complete(LLMRequest(
            messages=[{"role": "user", "content": json.dumps(packet, indent=2)}],
            system=CREDIT_SYSTEM,
            model=CREDIT_MODEL,
            max_tokens=200,
            temperature=0.6,
        ))
    except Exception:  # noqa: BLE001
        logger.info("credit line: model call failed", exc_info=True)
        return None
    return (response.content or "").strip()


async def credit_line(question, history) -> Optional[str]:
    """The one line that goes under a settled question, or None.

    Async because it phrases with a model; Optional because it would rather
    say nothing than say something it cannot support. A question only one
    person forecast has no credit to assign — the sentence's whole shape is
    "against what the other one said" — so it returns None there too.
    """
    if question.get("resolution") not in ("correct", "incorrect"):
        return None
    packet = fact_packet(question, history)
    # TWO HUMANS, not two forecasters. `fact_packet` counts the house among
    # the forecasters, and `llm/house_forecast.py` writes one house row per
    # question -- so this gate was satisfied by ONE person plus the machine,
    # and the line would then post that one person's number as an ordinary
    # message in the room. `api/rounds._round_state` would still be sealing
    # it (`revealed` needs both humans), so the credit line would have walked
    # around the blindness rule through the message lane while the API lane
    # held. The house may appear IN the line; it may not be what unlocks it.
    humans, _ = split_by_actor(history)
    if len({h["user_id"] for h in humans}) < 2:
        return None
    line = await _phrase(packet)
    if line is None:
        return None
    line = line.strip().strip('"')
    return line if validate_line(line, packet) else None


async def _resolved_questions(conn, done: set, limit: int) -> list:
    """Recently settled round questions with no credit line yet."""
    rows = await conn.fetch(
        f"""SELECT id, room_id, claim, deadline, resolution, resolved_at
            FROM commitments
            WHERE category = 'round'
              AND resolution IN ('correct', 'incorrect')
              AND resolved_at > now() - interval '{CREDIT_WINDOW}'
              AND NOT (id = ANY($2::uuid[]))
            ORDER BY resolved_at DESC LIMIT $1""",
        BACKLOG_SCAN, _as_uuids(done),
    )
    return list(rows)[:limit]


async def _history(conn, commitment_id) -> list:
    """The full forecast history with names attached — every row, because the
    line may cite when someone moved, not only where they ended."""
    rows = await conn.fetch(
        """SELECT cc.user_id, cc.confidence, cc.recorded_at, cc.actor,
                  u.display_name
           FROM commitment_confidence cc
           LEFT JOIN users u ON u.id = cc.user_id
           WHERE cc.commitment_id = $1
           ORDER BY cc.recorded_at ASC""",
        commitment_id,
    )
    return [dict(r) for r in rows]


# ── posting ──────────────────────────────────────────────────────────


async def _post_card(conn, ctx, room_id, thread_id, content: str,
                     metadata: dict) -> str:
    """Annotator-lane message + event + broadcast, the question_round shape."""
    msg_id = uuid4()
    now = datetime.now(timezone.utc)
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
        msg_id, thread_id, now,
        SpeakerType.LLM_ANNOTATOR.value, MessageType.TEXT.value,
        content, metadata,
    )
    await conn.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), now, EventType.ANNOTATION_CREATED.value,
        room_id, thread_id,
        {"message_id": str(msg_id), "source": metadata["source"]},
    )
    if ctx.broadcast is not None:
        await ctx.broadcast(room_id, OutboundMessage(
            type=MessageTypes.MESSAGE_CREATED,
            payload={
                "id": str(msg_id),
                "thread_id": str(thread_id),
                "speaker_type": SpeakerType.LLM_ANNOTATOR.value,
                "message_type": MessageType.TEXT.value,
                "content": content,
                "created_at": now.isoformat(),
                "metadata": metadata,
            },
        ))
    return str(msg_id)


async def _push_settlement(conn, ctx, room, question, thread_id: str,
                           message_id: str) -> int:
    """Push the settlement to members without an active WS to the room.

    Recipient filter mirrors night_shift._push_brief. The settlement is
    pushed and the credit line is not, deliberately: one is a task with a
    tap at the end of it, the other is a remark. Pushing the remark would
    teach them to ignore the push.
    """
    members = await conn.fetch(
        "SELECT user_id FROM room_memberships WHERE room_id = $1", room.id,
    )
    recipients = []
    for member in members:
        mgr = ctx.connection_manager
        if mgr is not None:
            try:
                if mgr.is_user_connected(member["user_id"], room.id):
                    continue
            except Exception:  # noqa: BLE001 — unknown manager shape pushes.
                logger.debug("connection check unavailable; pushing anyway",
                             exc_info=True)
        recipients.append(str(member["user_id"]))
    if not recipients:
        return 0

    from api.notifications.webpush import send_web_notifications

    await send_web_notifications(
        db=conn,
        recipient_user_ids=recipients,
        title=f"{room.name}: a question closed",
        body=question["claim"][:140],
        data={"room_id": str(room.id), "type": "round_settlement",
              "thread_id": thread_id, "message_id": message_id},
        # PER ROOM, not per question. A distinct tag per question means the
        # OS stacks one notification per closing question; this room's
        # thesis book asks five a Sunday and four rooms qualify, so a day on
        # which several close is several separate buzzes for one errand.
        # A shared tag makes the newest REPLACE the last, which is what the
        # reader wants: the errand is "some questions closed in here", and
        # the card in the room is where the detail already lives.
        #
        # This project has been bitten by exactly this before (2026-08-15: a
        # stray timer produced 32 of 35 curator alerts, and the room learned
        # to ignore them). A push people swipe away costs the settlement its
        # tap, and the tap is the only thing that turns a closed question
        # into a score.
        tag=f"settlement_{room.id}",
    )
    return len(recipients)


# ── the job ──────────────────────────────────────────────────────────


async def _load(conn, room_id):
    """Room + first thread, via the dive's own loader (Room model, room's
    first thread, members). Imported here rather than at module scope: it
    pulls the orchestrator's hoist helpers, and a scheduler job should not
    make the whole turn machinery an import-time dependency."""
    from llm.research import load_room_context

    return await load_room_context(conn, room_id)


async def round_close_watch(ctx: SchedulerContext) -> dict:
    """Settle what closed, then credit what settled."""
    detail: dict = {"settled": [], "credited": [], "skipped": []}
    async with ctx.pool.acquire() as conn:
        settled_ids = await _posted_ids(conn, SETTLEMENT_SOURCE)
        for question in await _closed_questions(conn, settled_ids, SETTLE_RUN_CAP):
            qid = str(question["id"])
            try:
                loaded = await _load(conn, question["room_id"])
                if loaded is None:
                    detail["skipped"].append({"id": qid, "reason": "no_thread"})
                    continue
                room, thread, _ = loaded
                finding = await _gather(conn, room, question)
                if finding is None:
                    detail["skipped"].append({"id": qid, "reason": "no_finding"})
                    continue
                metadata = {
                    "source": SETTLEMENT_SOURCE,
                    SETTLEMENT_SOURCE: {
                        "commitment_id": qid,
                        "claim": question["claim"],
                        "source": question["resolution_criteria"],
                        "closed": (question["deadline"].isoformat()
                                   if question["deadline"] else None),
                        "evidence": finding.get("checked", []),
                        "rationale": finding["rationale"],
                        "suggested_verdict": finding["verdict"],
                        # Nothing here resolves anything. The card is an
                        # argument for a tap, and this says so to every
                        # reader of the row, not just to the UI.
                        "resolved": False,
                    },
                }
                msg_id = await _post_card(
                    conn, ctx, room.id, thread.id,
                    render_settlement(question, finding), metadata,
                )
                pushed = await _push_settlement(
                    conn, ctx, room, question, str(thread.id), msg_id,
                )
                detail["settled"].append({
                    "id": qid, "room_id": str(room.id),
                    "suggested": finding["verdict"], "message_id": msg_id,
                    "pushed": pushed,
                })
            except Exception:  # noqa: BLE001 — one bad question must not
                # strand the backlog behind it.
                logger.exception("settlement failed for %s", qid)
                detail["skipped"].append({"id": qid, "reason": "error"})

        credited_ids = await _posted_ids(conn, CREDIT_SOURCE)
        for question in await _resolved_questions(conn, credited_ids, CREDIT_RUN_CAP):
            qid = str(question["id"])
            try:
                history = await _history(conn, question["id"])
                line = await credit_line(dict(question), history)
                if not line:
                    detail["skipped"].append({"id": qid, "reason": "no_line"})
                    continue
                loaded = await _load(conn, question["room_id"])
                if loaded is None:
                    detail["skipped"].append({"id": qid, "reason": "no_thread"})
                    continue
                room, thread, _ = loaded
                msg_id = await _post_card(
                    conn, ctx, room.id, thread.id, line,
                    {"source": CREDIT_SOURCE,
                     CREDIT_SOURCE: {"commitment_id": qid,
                                     "resolution": question["resolution"]}},
                )
                detail["credited"].append({"id": qid, "message_id": msg_id})
            except Exception:  # noqa: BLE001
                logger.exception("credit line failed for %s", qid)
                detail["skipped"].append({"id": qid, "reason": "error"})
    return detail


def register_round_close_jobs(scheduler) -> None:
    scheduler.register(Job(
        "round_close_watch", INTERVAL_S, round_close_watch,
        enabled_env=ENABLED_ENV,
    ))
