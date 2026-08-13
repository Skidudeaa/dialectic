# llm/reading_echo.py — the cross-session echo: one room's reading, another
# room's thesis.

"""
ARCHITECTURE: One half-hourly scheduler job — reading_echo. It scans the
reading library for rows saved since the last run, finds OTHER rooms that
are recently active and hold a thesis (linked_book_id), asks Haiku whether
the reading bears on that room's thesis, and on a hit posts ONE quiet
annotator-lane note in the target room plus a cross-session memory
reference from the origin reading's memory twin.

WHY: two rooms working adjacent theses never hear about each other. When
one room files an article that bears on another room's cascade, the other
room should find a note waiting — not a copy of the memory, not an injected
prompt, a note.

WHY a scheduler job rather than a fan-out inside save_reading (the plan's
original shape): save_reading runs in request contexts (api/reading_relay.py)
that carry no broadcast handle. The job keeps the echo on the established
Path A — SchedulerContext.pool + SchedulerContext.broadcast — and the
overlap between runs is harmless because dedup is by metadata, not timing.

HARD RULE (the cross_session.py:158-160 SECURITY gate, unchanged): no
automatic cross-room prompt injection. The echo is a visible note plus a
memory reference; riding auto-injection still requires explicit user
promotion. This module never touches that path.

GUARDRAILS:
  - enabled_env READING_ECHO_ENABLED — default ON (unset means on). The kill
    switch exists because this job spends LLM money on a wall-clock timer and posts across rooms; set it to 0 to stop it.
  - READING_ECHO_TARGET_CAP rooms per reading; READING_ECHO_DAILY_CAP echo
    notes per target room per UTC-day, counted by posted reading_echo
    messages (night_shift._briefs_posted_today pattern: the message count
    IS the note budget)
  - dedup on (target room, url) by metadata->>'source' = 'reading_echo'
    carrying the same url (prediction_watch._already_proposed pattern), and
    on the target room's own reading_items (they read it themselves —
    llm/reading.seen_urls)
  - per-reading/per-room failures (a bad parse, a dead pool, a
    missing thread) skip that pair and are recorded in the detail dict —
    the job itself never raises

CONNECTIONS: the job body acquires its own connections from ctx.pool and
never touches the scheduler's ledger connection (the scheduler caution —
a long job holding the ledger conn stalls every other tick).
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from scheduler import Job, SchedulerContext
from models import SpeakerType, MessageType, EventType
from transport.websocket import OutboundMessage, MessageTypes
from llm.reading import _reading_key, seen_urls

logger = logging.getLogger(__name__)

# Two intervals plus slack: at 1800s a save lands in the next run's window
# even under scheduler jitter; the metadata dedup makes the overlap free.
LOOKBACK_S = 3700
ACTIVE_WINDOW_HOURS = 48
READING_ECHO_TARGET_CAP = 3
READING_ECHO_DAILY_CAP = 6
# The thesis snapshot goes into the prompt truncated: a trading_config JSON
# can carry whole orderbooks; the model needs the posture, not the ticks.
THESIS_CONTEXT_CAP = 3000
KEY_CLAIMS_CAP = 5
BACKGROUND_MODEL = "claude-sonnet-5"


async def _recent_readings(conn) -> list:
    """Library rows saved since the last run, with the origin room's name."""
    return await conn.fetch(
        """SELECT ri.room_id, ri.url, ri.title, ri.site, ri.summary,
                  ri.key_claims, r.name AS origin_room_name
           FROM reading_items ri
           JOIN rooms r ON r.id = ri.room_id
           WHERE ri.created_at > now() - interval '3700 seconds'
           ORDER BY ri.created_at DESC"""
    )


async def _candidate_rooms(conn, origin_room_id) -> list:
    """Other rooms: active in 48h (night_shift._active_rooms pattern) AND
    holding a thesis (news_night._linked_rooms pattern).

    trading_config is cast to text so the thesis context is a string
    regardless of the pool's JSONB codec.
    """
    return await conn.fetch(
        """SELECT DISTINCT r.id, r.name,
                  r.trading_config::text AS trading_config
           FROM rooms r
           JOIN threads t ON t.room_id = r.id
           JOIN messages m ON m.thread_id = t.id
           WHERE r.linked_book_id IS NOT NULL
             AND r.id != $1
             AND m.created_at > now() - interval '48 hours'""",
        origin_room_id,
    )


async def _echoed_urls(conn, room_id) -> set:
    """URLs already echoed INTO this room — the dedup gauge (mirrors
    prediction_watch._already_proposed: dedup by metadata, not by time)."""
    rows = await conn.fetch(
        """SELECT m.metadata->>'url' AS url
           FROM messages m
           JOIN threads t ON m.thread_id = t.id
           WHERE t.room_id = $1
             AND m.metadata->>'source' = 'reading_echo'""",
        room_id,
    )
    return {r["url"] for r in rows if r["url"]}


async def _echoes_posted_today(conn, room_id) -> int:
    """Echo notes posted into this room so far today (UTC) — the budget
    gauge (mirrors night_shift._briefs_posted_today)."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM messages m
           JOIN threads t ON m.thread_id = t.id
           WHERE t.room_id = $1
             AND m.created_at >= $2
             AND m.metadata->>'source' = 'reading_echo'""",
        room_id, start_of_day,
    )
    return count or 0


async def _find_memory_twin(conn, reading) -> Optional[str]:
    """The origin room's memory twin for this reading (key
    'reading:<domain>-<slug>', llm/reading._reading_key) — the reference's
    source. Absent twin → no reference, but the note still posts."""
    key = _reading_key({"url": reading["url"], "title": reading["title"]})
    return await conn.fetchval(
        """SELECT id FROM memories
           WHERE room_id = $1 AND key = $2 AND status = 'active'""",
        reading["room_id"], key,
    )


def _parse_relevance(text: str) -> Optional[dict]:
    """Tolerant JSON parse of the Haiku verdict (news_night._parse_distill
    pattern)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        parsed = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except ValueError:
            return None
    if not isinstance(parsed, dict) or "relevant" not in parsed:
        return None
    return {"relevant": bool(parsed["relevant"]),
            "why": str(parsed.get("why") or "")}


async def _relevance(reading: dict, thesis_context: str) -> Optional[dict]:
    """One background-model call: does this reading bear on the target room's thesis?

    Provider import stays lazy (news_night._distill pattern) so importing
    this module never touches provider config; a missing API key, a provider
    failure, or an unparseable answer degrades to None — the caller skips
    the pair.
    """
    from llm.providers import get_provider, ProviderName, LLMRequest

    claims = [str(c) for c in (reading.get("key_claims") or [])][:KEY_CLAIMS_CAP]
    provider = get_provider(ProviderName.ANTHROPIC)
    request = LLMRequest(
        messages=[{
            "role": "user",
            "content": (
                "A room read this article. Does it bear on the thesis held "
                "by ANOTHER room, whose thesis state is below?\n\n"
                f"ARTICLE — {reading.get('title') or 'untitled'}"
                f" ({reading.get('site') or 'unknown site'}):\n"
                f"Summary: {reading.get('summary') or ''}\n"
                f"Key claims: {json.dumps(claims)}\n\n"
                f"THESIS STATE (truncated):\n"
                f"{thesis_context or '(no thesis snapshot)'}\n\n"
                "Respond with ONLY JSON: {\"relevant\": true | false, "
                "\"why\": \"one sentence\"}. Relevant means the article "
                "confirms, threatens, or changes something the thesis "
                "depends on."
            ),
        }],
        system="You judge whether an article bears on a trading thesis. Be terse, factual, and output only the JSON object asked for.",
        model=BACKGROUND_MODEL,
        max_tokens=256,
        temperature=0.2,
    )
    try:
        response = await provider.complete(request)
    except Exception as e:
        logger.info("reading echo relevance LLM call failed: %s", e)
        return None
    return _parse_relevance(response.content or "")


async def _create_reference(conn, memory_id, room, thread_id, msg_id,
                            why: str) -> None:
    """Cross-session reference from the origin reading's memory twin to the
    echo note — a citation, never a copy. The lazy import keeps this module
    importable without the memory stack's embedding config."""
    from memory.cross_session import CrossSessionMemoryManager

    await CrossSessionMemoryManager(conn).create_reference(
        source_memory_id=memory_id,
        target_room_id=room["id"],
        target_thread_id=thread_id,
        target_message_id=msg_id,
        referenced_by_llm=True,
        citation_context=why,
    )


async def _post_echo_note(conn, ctx, room, origin_name: str,
                          reading: dict, why: str):
    """Annotator-lane echo, mirroring night_shift._post_brief_message. No
    web push — the echo is quiet by design. Returns (msg_id, thread_id) or
    "no_thread" when the room has no thread to land in."""
    msg_id = uuid4()
    now = datetime.now(timezone.utc)
    thread_row = await conn.fetchrow(
        "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
        room["id"],
    )
    if thread_row is None:
        return "no_thread"
    url = reading["url"]
    title = reading.get("title") or url
    site = reading.get("site") or "unknown site"
    content = (
        f"The {origin_name} room read this — bears on your cascade: "
        f"**{title}** ({site}, {url})\n\n{why}"
    )
    metadata = {"source": "reading_echo", "url": url,
                "origin_room": origin_name}
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
    await conn.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), now, EventType.ANNOTATION_CREATED.value,
        room["id"], thread_row["id"],
        {"message_id": str(msg_id), "source": "reading_echo"},
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
    return msg_id, thread_row["id"]


async def echo(ctx: SchedulerContext) -> dict:
    """Echo new readings into the other thesis-holding rooms they bear on."""
    detail: dict = {"echoed": [], "skipped": []}
    async with ctx.pool.acquire() as conn:
        readings = await _recent_readings(conn)
        for reading in readings:
            url = reading["url"]
            origin_name = reading["origin_room_name"]
            try:
                rooms = (await _candidate_rooms(conn, reading["room_id"]))[
                    :READING_ECHO_TARGET_CAP
                ]
                for room in rooms:
                    room_key = str(room["id"])
                    try:
                        if url in await _echoed_urls(conn, room["id"]):
                            detail["skipped"].append({
                                "url": url, "room": room_key,
                                "reason": "already_echoed"})
                            continue
                        if url in await seen_urls(conn, room["id"]):
                            # The target room read it themselves.
                            detail["skipped"].append({
                                "url": url, "room": room_key,
                                "reason": "already_read"})
                            continue
                        # Cap BEFORE the relevance call: no note budget
                        # means no LLM spend either.
                        if await _echoes_posted_today(conn, room["id"]) \
                                >= READING_ECHO_DAILY_CAP:
                            detail["skipped"].append({
                                "url": url, "room": room_key,
                                "reason": "cap_reached"})
                            continue
                        thesis = str(room["trading_config"] or "").strip()
                        if not thesis or thesis == "null":
                            detail["skipped"].append({
                                "url": url, "room": room_key,
                                "reason": "no_thesis"})
                            continue
                        verdict = await _relevance(
                            dict(reading), thesis[:THESIS_CONTEXT_CAP])
                        if verdict is None:
                            detail["skipped"].append({
                                "url": url, "room": room_key,
                                "reason": "relevance_failed"})
                            continue
                        if not verdict["relevant"]:
                            detail["skipped"].append({
                                "url": url, "room": room_key,
                                "reason": "not_relevant"})
                            continue

                        posted = await _post_echo_note(
                            conn, ctx, room, origin_name, reading,
                            verdict["why"])
                        if posted == "no_thread":
                            detail["skipped"].append({
                                "url": url, "room": room_key,
                                "reason": "no_thread"})
                            continue
                        msg_id, thread_id = posted

                        referenced = False
                        twin_id = await _find_memory_twin(conn, reading)
                        if twin_id is not None:
                            try:
                                await _create_reference(
                                    conn, twin_id, room, thread_id,
                                    msg_id, verdict["why"])
                                referenced = True
                            except Exception:
                                # The note stands on its own; a failed
                                # citation degrades, never sinks.
                                logger.exception(
                                    "echo reference failed for %s -> %s",
                                    url, room_key)
                        detail["echoed"].append({
                            "url": url, "room": room_key,
                            "message_id": str(msg_id),
                            "referenced": referenced,
                        })
                    except Exception:
                        # A broken pair must not sink the reading's other
                        # rooms, let alone the run.
                        logger.exception(
                            "reading echo failed for %s -> %s", url, room_key)
                        detail["skipped"].append({
                            "url": url, "room": room_key, "reason": "error"})
            except Exception:
                logger.exception("reading echo failed for %s", url)
                detail["skipped"].append({"url": url, "reason": "error"})
    return detail


def register_reading_echo_jobs(scheduler) -> None:
    scheduler.register(Job(
        "reading_echo", 1800, echo,
        enabled_env="READING_ECHO_ENABLED",
    ))
