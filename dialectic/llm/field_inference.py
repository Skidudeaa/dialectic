# llm/field_inference.py — Dialectic pencils in provisional structure.

"""
ARCHITECTURE: One half-hourly scheduler job — field_inference. Per room
active in the last 48h, it gathers the last 30 non-deleted messages, the
room's currently-active (non-superseded) marks, and the correction digest
(every contest/correct/supersede/split/merge review, with what it targeted),
asks FIELD_MODEL (§1.19, pinned by name — structure extraction over <=30
messages is claim-check-grade work, not judgment) for candidate marks, hard-
validates every candidate against the room's own rows, and inserts what
survives as `mark_kind='relation'`, `origin='inferred'` rows.

WHY a scheduler job rather than inline on message send: the same reasoning as
llm/reading_echo.py — a wall-clock timer with its own budget, not a per-
message tax, and dedup by content (dedup_key) rather than by timing means a
missed or doubled tick is harmless.

THE §14.5 GUARANTEE, mechanically: `dedup_key` is computed by
field_marks.compute_dedup_key(relation, subjects) — the SAME function
api/field.py uses for a human's correct/split/merge replacement. A contested
mark's OWN row keeps its OWN dedup_key untouched (contest is a review row,
never an UPDATE), so when this job later proposes the identical
{relation, subjects} pair again, it computes the identical key and
`ON CONFLICT (room_id, dedup_key) DO NOTHING` silently drops it. The
"do not re-assert" text in the prompt below is advisory, aimed at steering
the model away from wasting a candidate slot on something already ruled on;
the unique index is the actual law (§1.10).

GUARDRAILS:
  - enabled_env FIELD_INFERENCE_ENABLED — default ON.
  - cheap gate BEFORE any LLM spend: skip a room with no message newer than
    both its own newest mark AND this job's lookback window; skip a room
    that already hit its daily cap. An idle room costs ~zero calls.
  - FIELD_INFERENCE_ROOM_CAP (6) marks actually INSERTED per room per run;
    FIELD_INFERENCE_DAILY_CAP (20) per room per UTC-day — both counted from
    field_marks rows themselves (provenance='field_inference'), never a
    separate counter that could drift from the table.
  - hard validation, not prompt trust: relation must be in FIELD_RELATIONS;
    every subject must resolve to a real row IN THIS ROOM
    (field_marks.resolve_subjects_in_room) — the model cannot mint
    provenance no matter what it emits. Room-field subjects are refused even
    when their grammar is valid: only api.field performs the authenticated
    trading structure proof required for a causal binding.
  - Home is never a candidate room: the Field does not render there (TG-B),
    so there is nothing to spend the budget on.
  - no WS push this release — the scene refetches on entry and after a
    review (§5.1). Do not add a broadcast path here.
  - per-room try/except: a broken room must not sink the run, mirroring
    reading_echo.echo.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from field_marks import (
    FIELD_RELATIONS,
    FieldMarkService,
    compute_dedup_key,
    resolve_subjects_in_room,
)
from models import EventType
from scheduler import Job, SchedulerContext

logger = logging.getLogger(__name__)

# Pinned by NAME (§1.19), not "the usual background model" — reading_echo.py's
# BACKGROUND_MODEL has already drifted once (docstring says Haiku-grade, the
# constant now reads claude-sonnet-5), which is exactly why this plan wants an
# exact string here instead. Bumping it is a one-line amendment if mark
# quality disappoints.
FIELD_MODEL = "claude-haiku-4-5-20251001"

RECENT_MESSAGE_LIMIT = 30
ACTIVE_WINDOW_HOURS = 48
# Two intervals (2x1800s) plus slack, matching reading_echo.LOOKBACK_S's
# "a save lands in the next run's window even under scheduler jitter" pattern.
LOOKBACK_S = 3700
ACTIVE_MARKS_PROMPT_CAP = 40
CORRECTION_DIGEST_CAP = 20
FIELD_INFERENCE_ROOM_CAP = 6
FIELD_INFERENCE_DAILY_CAP = 20
MAX_TOKENS = 1500
TEMPERATURE = 0.2


async def _active_rooms(conn) -> list:
    """Rooms with any message in the last 48h, EXCLUDING Home — the Field
    never renders there (TG-B: 'Home holds no Field'), so there is nothing to
    spend inference budget on."""
    return await conn.fetch(
        """SELECT DISTINCT r.id, r.name
           FROM rooms r
           JOIN threads t ON t.room_id = r.id
           JOIN messages m ON m.thread_id = t.id
           WHERE NOT r.is_home
             AND m.created_at > now() - interval '48 hours'"""
    )


async def _has_fresh_content(conn, room_id: UUID) -> bool:
    """The cheap gate: skip unless a message exists newer than BOTH the
    room's newest mark and this job's lookback window."""
    newest_mark_at = await conn.fetchval(
        "SELECT MAX(created_at) FROM field_marks WHERE room_id = $1", room_id,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=LOOKBACK_S)
    since = max(newest_mark_at, cutoff) if newest_mark_at is not None else cutoff
    return bool(await conn.fetchval(
        """SELECT EXISTS (
               SELECT 1 FROM messages m JOIN threads t ON t.id = m.thread_id
               WHERE t.room_id = $1 AND NOT m.is_deleted AND m.created_at > $2
           )""",
        room_id, since,
    ))


async def _marks_inserted_today(conn, room_id: UUID) -> int:
    """Inference inserts so far today (UTC) — the daily budget gauge
    (night_shift._briefs_posted_today pattern: the row count IS the budget)."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM field_marks
           WHERE room_id = $1 AND provenance = 'field_inference'
             AND created_at >= $2""",
        room_id, start_of_day,
    )
    return count or 0


async def _recent_messages(conn, room_id: UUID) -> list:
    return await conn.fetch(
        """SELECT m.id, m.thread_id, m.created_at, m.content, m.speaker_type
           FROM messages m JOIN threads t ON t.id = m.thread_id
           WHERE t.room_id = $1 AND NOT m.is_deleted
           ORDER BY m.created_at DESC
           LIMIT $2""",
        room_id, RECENT_MESSAGE_LIMIT,
    )


async def _correction_digest_rows(conn, room_id: UUID) -> list:
    """Every review the humans have already ruled on — §14.5's "inform future
    room-specific inference"."""
    return await conn.fetch(
        """SELECT rv.action, rv.created_at, tgt.relation AS target_relation,
                  tgt.title AS target_title
           FROM field_marks rv
           JOIN field_marks tgt ON tgt.id = rv.target_mark_id
           WHERE rv.room_id = $1 AND rv.mark_kind = 'review'
             AND rv.action IN ('contest','correct','supersede','split','merge')
           ORDER BY rv.created_at DESC
           LIMIT $2""",
        room_id, CORRECTION_DIGEST_CAP,
    )


def _render_messages(messages: list) -> str:
    lines = []
    for row in reversed(messages):  # chronological in the prompt
        speaker = row["speaker_type"] or "unknown"
        content = " ".join(str(row["content"] or "").split())[:400]
        lines.append(f"- [{row['id']}] ({speaker}): {content}")
    return "\n".join(lines) or "(no messages)"


def _render_active_marks(marks: list) -> str:
    if not marks:
        return "(no marks yet)"
    lines = [
        f"- [{m.relation}] {m.title}"
        for m in marks[:ACTIVE_MARKS_PROMPT_CAP]
    ]
    return "\n".join(lines)


def _render_digest(rows: list) -> str:
    if not rows:
        return "(no corrections yet)"
    lines = [
        f"- {row['action']} on [{row['target_relation']}] {row['target_title']}"
        for row in rows
    ]
    return "\n".join(lines)


FIELD_INFERENCE_SYSTEM = """You extract STRUCTURE from a room's conversation
into candidate marks — provisional, reversible, and always attributed to
Dialectic, never to a human. You place LOW-RISK structure only: contribution
type, claim grouping, support/challenge between claims, repeated definitions,
possible contradictions, an emerging position, evidence attached to a claim,
a branch candidate, an unanswered question, a candidate synthesis. You NEVER
declare a decision, a consensus, a resolved tension, a final definition, a
branch merge, a rejection, or that someone changed position — those require a
human's own judgment and are not choices you get to make.

Respond with ONLY a JSON array (may be empty) of candidate marks:
[{"relation": "one of the allowed relations", "subjects": [{"entity":
"messages", "id": "<uuid from the transcript above>"}], "title": "short
label", "quote": "the source span, verbatim"}]

Every subject id MUST be copied from the message ids shown above — never
invented. Do not repeat a correction the humans have already ruled on."""


def _parse_candidates(text: str) -> Optional[list]:
    """Tolerant JSON parse (news_night._parse_distill / reading_echo pattern)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        parsed = json.loads(text)
    except ValueError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except ValueError:
            return None
    return parsed if isinstance(parsed, list) else None


async def _generate_candidates(
    messages: list, active_marks: list, digest_rows: list,
) -> Optional[list]:
    """One FIELD_MODEL call. Provider import stays lazy (news_night/
    reading_echo pattern) so importing this module never touches provider
    config. A missing key, a provider failure, or unparseable JSON degrades
    to None — the caller skips the room, spending nothing further.

    Kept as its own function (rather than inlined into `run`) so tests can
    monkeypatch it directly and exercise the real database around it.
    """
    from llm.providers import LLMRequest, ProviderName, get_provider

    provider = get_provider(ProviderName.ANTHROPIC)
    request = LLMRequest(
        messages=[{
            "role": "user",
            "content": (
                f"ALLOWED RELATIONS: {', '.join(FIELD_RELATIONS)}\n\n"
                f"RECENT TRANSCRIPT:\n{_render_messages(messages)}\n\n"
                f"CURRENTLY ACTIVE MARKS:\n{_render_active_marks(active_marks)}\n\n"
                "THE HUMANS HAVE RULED ON THESE — do not re-assert:\n"
                f"{_render_digest(digest_rows)}"
            ),
        }],
        system=FIELD_INFERENCE_SYSTEM,
        model=FIELD_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    try:
        response = await provider.complete(request)
    except Exception as e:
        logger.info("field inference LLM call failed: %s", e)
        return None
    return _parse_candidates(response.content or "")


def _candidate_valid(candidate: dict) -> bool:
    if not isinstance(candidate, dict):
        return False
    if candidate.get("relation") not in FIELD_RELATIONS:
        return False
    subjects = candidate.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        return False
    for subject in subjects:
        if not isinstance(subject, dict) or not subject.get("entity") or not subject.get("id"):
            return False
        if subject.get("entity") == "rooms":
            return False
    return True


def _infer_thread_id(subjects: list, message_thread_map: dict) -> Optional[UUID]:
    for subject in subjects:
        if subject.get("entity") == "messages":
            thread_id = message_thread_map.get(str(subject.get("id")))
            if thread_id is not None:
                return thread_id
    return None


# The ON CONFLICT target must repeat idx_field_marks_dedup's own partial
# predicate (WHERE dedup_key IS NOT NULL) — Postgres will not infer a match
# against a partial unique index otherwise, and silently falls back to
# raising InvalidColumnReferenceError ("no unique or exclusion constraint
# matching the ON CONFLICT specification") instead of deduplicating at all.
_INSERT_CANDIDATE_SQL = """
INSERT INTO field_marks
    (id, room_id, thread_id, mark_kind, relation, origin, provenance,
     subjects, title, payload, dedup_key)
VALUES ($1, $2, $3, 'relation', $4, 'inferred', 'field_inference', $5, $6, $7, $8)
ON CONFLICT (room_id, dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING
RETURNING id
"""

_INSERT_EVENT_SQL = """
INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
VALUES ($1, $2, $3, $4, $5, $6, $7)
"""


async def _insert_candidate(
    conn, room_id: UUID, candidate: dict, message_thread_map: dict,
) -> Optional[UUID]:
    relation = candidate["relation"]
    subjects = candidate["subjects"]
    thread_id = _infer_thread_id(subjects, message_thread_map)
    title = str(candidate.get("title") or "")[:200]
    payload = {"quote": str(candidate.get("quote") or "")[:600]}
    dedup_key = compute_dedup_key(relation, subjects)
    # Row + its event land together or not at all (the reading_echo
    # event+row transaction pattern) — a mark without its event is a record
    # the Record cannot explain.
    async with conn.transaction():
        row = await conn.fetchrow(
            _INSERT_CANDIDATE_SQL, uuid4(), room_id, thread_id, relation,
            subjects, title, payload, dedup_key,
        )
        if row is None:
            return None
        mark_id = row["id"]
        await conn.execute(
            _INSERT_EVENT_SQL, uuid4(), datetime.now(timezone.utc),
            EventType.FIELD_MARK_INFERRED.value, room_id, thread_id, None,
            {"mark_id": str(mark_id), "relation": relation},
        )
    return mark_id


async def run(ctx: SchedulerContext) -> dict:
    """Pencil in provisional structure for every active, non-Home room."""
    detail: dict = {"processed": [], "skipped": []}
    async with ctx.pool.acquire() as conn:
        rooms = await _active_rooms(conn)
        for room in rooms:
            room_key = str(room["id"])
            try:
                if not await _has_fresh_content(conn, room["id"]):
                    detail["skipped"].append({"room": room_key, "reason": "no_new_content"})
                    continue
                inserted_today = await _marks_inserted_today(conn, room["id"])
                if inserted_today >= FIELD_INFERENCE_DAILY_CAP:
                    detail["skipped"].append({"room": room_key, "reason": "daily_cap"})
                    continue

                messages = await _recent_messages(conn, room["id"])
                if not messages:
                    detail["skipped"].append({"room": room_key, "reason": "no_messages"})
                    continue
                message_thread_map = {
                    str(m["id"]): m["thread_id"] for m in messages
                }
                active_marks = [
                    m for m in (await FieldMarkService(conn).build(room["id"])).marks
                    if m.review != "superseded"
                ]
                digest_rows = await _correction_digest_rows(conn, room["id"])

                candidates = await _generate_candidates(messages, active_marks, digest_rows)
                if not candidates:
                    detail["skipped"].append({"room": room_key, "reason": "no_candidates"})
                    continue

                inserted = []
                remaining_daily = FIELD_INFERENCE_DAILY_CAP - inserted_today
                for candidate in candidates:
                    if len(inserted) >= FIELD_INFERENCE_ROOM_CAP:
                        break
                    if len(inserted) >= remaining_daily:
                        break
                    if not _candidate_valid(candidate):
                        continue
                    if not await resolve_subjects_in_room(
                        conn, room["id"], candidate["subjects"], candidate["relation"],
                    ):
                        continue
                    mark_id = await _insert_candidate(
                        conn, room["id"], candidate, message_thread_map,
                    )
                    if mark_id is not None:
                        inserted.append(str(mark_id))

                detail["processed"].append({
                    "room": room_key, "candidates": len(candidates),
                    "inserted": len(inserted),
                })
            except Exception:
                logger.exception("field inference failed for room %s", room_key)
                detail["skipped"].append({"room": room_key, "reason": "error"})
    return detail


def register_field_inference_jobs(scheduler) -> None:
    scheduler.register(Job(
        "field_inference", 1800, run,
        enabled_env="FIELD_INFERENCE_ENABLED",
    ))
