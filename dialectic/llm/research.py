# llm/research.py — Research mode ("deep dive"): the long-loop answer to a hard question

"""
ARCHITECTURE: A human clicks Research with a question in the composer, and
the room gets ONE deliberate turn instead of a quick interjection: the
standard tool registry (read_article, search_memories, search_reading,
search_transcript, the trading checks) driven by a ToolLoop with a research
budget — 15 iterations / 300s where an ordinary turn gets 5 / 60. The loop's
events ride the exact vocabulary the client already renders (llm_thinking /
llm_streaming / llm_tool_activity / llm_done), so progress shows up for
free and the finished brief lands as an ordinary llm_primary message.

WHY a separate module rather than an orchestrator flag: everything around
the loop is different — the trigger is a WS message type, not a heuristic;
the prompt is the question, not the thread window (the dive gathers its own
context through tools); persistence carries metadata.source='deep_dive';
and the concurrency guard (one active dive per room) belongs to the feature,
not the turn machinery.

GUARDRAILS:
  - one active dive per room (module-level set + lock; a second request
    gets an ephemeral refusal, never a queue)
  - the question is capped (MAX_QUESTION_CHARS) — a research question is a
    sentence or three, not a pasted brief
  - proposals made along the way (draft_prediction / propose_thesis /
    save_reading) hoist into message metadata exactly like an ordinary tool
    turn: Claude proposes, a human disposes
  - every failure path is a broadcast (llm_error) plus a paired
    deep_dive_done — a failed dive must never leave the room thinking
  - kill switch: DEEP_DIVE_ENABLED (ships enabled; set 0 to turn it off)
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import asyncpg

from models import (
    Event,
    EventType,
    Message,
    MessageCreatedPayload,
    MessageType,
    Room,
    SpeakerType,
    Thread,
    User,
)
from transport.websocket import MessageTypes, OutboundMessage

from .orchestrator import (
    _hoisted_prediction_proposal,
    _hoisted_reading_proposal,
    _hoisted_thesis_proposal,
)
from .prompts import PromptBuilder
from .providers import LLMRequest, ProviderName
from .router import ModelRouter
from .tool_loop import ToolLoop
from .tools import build_registry

logger = logging.getLogger(__name__)

# The research budget — deliberately 3x the ordinary turn's (tool_loop.py
# defaults to 5 / 60): a research question is the one turn where "go read
# the sources" is the whole point. The loop still ends on a forced text
# turn, so a model that keeps asking for one more fetch is cut off with a
# sentence, not silence.
MAX_ITERATIONS = 15
LOOP_BUDGET_S = 300.0

# A research question is a sentence or three. Past this it is a brief being
# pasted wholesale into the prompt, and the composer is the wrong tool.
MAX_QUESTION_CHARS = 2000

# Same kill-switch shape as DIALECTIC_TOOLS_ENABLED (orchestrator.py):
# unset means ON — the feature ships enabled, and the env var exists so it
# can be turned off in one restart if the long loop misbehaves live.
_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def deep_dive_enabled() -> bool:
    """Whether the Research affordance works at all, per environment."""
    return os.getenv("DEEP_DIVE_ENABLED", "").strip().lower() not in _OFF_VALUES


# WHY this wording: the dive's failure mode is not a wrong answer, it is a
# confident answer resting on one unread headline. The ordinary TOOLS_SECTION
# already says "never summarize a page you have not read"; this section adds
# what a longer budget is FOR — corroboration — and what it may end with.
RESEARCH_IDENTITY = """## Research Mode

The room has asked you a hard question and given you time to answer it
properly. Work in three moves: gather, cross-check, synthesize.

Gather: read the sources themselves with read_article, and check what the
room already knows — search_memories, search_reading, and search_transcript
before reaching for the open web. Cross-check: no load-bearing claim stands
on one source. Find a second, and when you could not, the sentence carrying
the claim says so. Synthesize: land a brief the room can argue with, not a
pile of quotes.

Cite only what you actually fetched. Be plain about what could not be
verified — do not round up.

If the research sharpens into a call, you may end with a proposal:
draft_prediction for a falsifiable claim, propose_thesis when the finding
deserves a tracked cascade, save_reading for a source worth keeping. You
propose; the room disposes."""


# One active dive per room. A deep dive narrates its legwork into the room
# transcript (tool activity, then the brief); two of them interleaving
# traces into one thread would be unreadable. WHY a set + lock rather than
# per-room asyncio.Lock objects: the guard's whole job is the atomic
# check-and-mark, and a dict of locks would still need a lock around it.
_active_dives: set[UUID] = set()
_dives_lock = asyncio.Lock()


async def try_acquire_dive(room_id: UUID) -> bool:
    """Mark this room as having a dive in flight, or False if one already has."""
    async with _dives_lock:
        if room_id in _active_dives:
            return False
        _active_dives.add(room_id)
        return True


def release_dive(room_id: UUID) -> None:
    """Clear the room's in-flight mark. Idempotent — the caller's finally
    runs no matter which path the dive took out."""
    _active_dives.discard(room_id)


async def load_room_context(
    db, room_id: UUID, thread_id: Optional[UUID] = None
) -> Optional[tuple[Room, Thread, list[User]]]:
    """Room/Thread/users for a dive, or None when the room has no thread.

    Mirrors silence_sweep._load_room_context minus the message/memory
    windows: the dive's prompt is the question, and it gathers room context
    through tools (search_transcript / search_memories) rather than riding
    a window assembled before it started. `thread_id` pins the thread the
    asker was composing in; absent, the room's first thread takes the brief.
    """
    room_row = await db.fetchrow("SELECT * FROM rooms WHERE id = $1", room_id)
    if room_row is None:
        return None
    if thread_id is not None:
        thread_row = await db.fetchrow(
            "SELECT * FROM threads WHERE id = $1 AND room_id = $2",
            thread_id, room_id,
        )
    else:
        thread_row = await db.fetchrow(
            "SELECT * FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
            room_id,
        )
    if thread_row is None:
        return None
    user_rows = await db.fetch(
        """SELECT u.* FROM users u
           JOIN room_memberships rm ON u.id = rm.user_id
           WHERE rm.room_id = $1""",
        room_id,
    )
    return (
        Room(**dict(room_row)),
        Thread(**dict(thread_row)),
        [User(**dict(row)) for row in user_rows],
    )


async def deep_dive(
    db,
    room: Room,
    thread: Thread,
    users: list[User],
    question: str,
    broadcast,
) -> None:
    """Run one research turn and land the brief in the room.

    Broadcasts the ordinary stream vocabulary (so the client renders the
    dive exactly like a summoned turn) framed by deep_dive_started /
    deep_dive_done (so the composer can disarm until this one lands).
    NEVER raises: every failure ends in an llm_error broadcast, and the
    paired deep_dive_done fires from the finally either way.
    """
    # Generated upfront for stream correlation, exactly like the summon
    # path in transport/handlers.py — the persisted message gets its own id.
    stream_message_id = uuid4()
    accumulated = ""

    async def send(message_type: str, payload: dict) -> None:
        await broadcast(room.id, OutboundMessage(type=message_type, payload=payload))

    await send(MessageTypes.DEEP_DIVE_STARTED, {
        "thread_id": str(thread.id),
        "question": question,
    })
    await send(MessageTypes.LLM_THINKING, {"thread_id": str(thread.id)})

    try:
        try:
            registry = build_registry(room, db)
        except Exception:
            # A registry that cannot be built costs the dive its legs — a
            # research turn with no tools is just a slower ordinary turn,
            # so say so rather than burn the budget pretending.
            logger.exception("Deep dive: tool registry unavailable")
            registry = None
        if registry is None or not registry.schemas():
            await send(MessageTypes.LLM_ERROR, {
                "thread_id": str(thread.id),
                "error": "Research needs the tool channel, which is unavailable right now.",
                "partial_content": "",
            })
            return

        labels = registry.labels()

        # The standard layered prompt (room rules, participant preferences,
        # trading state, tool policy) with the research contract appended
        # last, where it cannot be buried. The message window is just the
        # question — the dive fetches whatever else it needs.
        prompt = PromptBuilder().build(
            room=room,
            users=users,
            messages=[],
            memories=[],
            tools_enabled=True,
        )
        request = LLMRequest(
            messages=[{"role": "user", "content": question}],
            system=prompt.system + "\n\n" + RESEARCH_IDENTITY,
            model=room.primary_model,
            stream=True,
        )

        # Same construction as the orchestrator's _get_router, minus the
        # cache: a dive is a one-off task, not a per-room long-lived turn.
        router = ModelRouter(
            primary_provider=ProviderName(room.primary_provider),
            fallback_provider=ProviderName(room.fallback_provider),
            primary_model=room.primary_model,
            fallback_model=room.provoker_model,
        )

        token_index = 0
        tool_trace: list[dict] = []
        iterations = 0
        degraded = False

        loop = ToolLoop(
            router, registry,
            max_iterations=MAX_ITERATIONS, loop_budget_s=LOOP_BUDGET_S,
        )
        async for kind, payload in loop.run_streaming(request):
            if kind == "token":
                accumulated += payload["token"]
                await send(MessageTypes.LLM_STREAMING, {
                    "thread_id": str(thread.id),
                    "message_id": str(stream_message_id),
                    "token": payload["token"],
                    "index": token_index,
                    "speaker_type": SpeakerType.LLM_PRIMARY.value,
                })
                token_index += 1
            elif kind == "tool_start":
                await send(MessageTypes.LLM_TOOL_ACTIVITY, {
                    "thread_id": str(thread.id),
                    "tool": payload["name"],
                    "label": payload.get("label") or "checking",
                    "status": "started",
                })
            elif kind == "tool_result":
                await send(MessageTypes.LLM_TOOL_ACTIVITY, {
                    "thread_id": str(thread.id),
                    "tool": payload["name"],
                    # tool_result carries no label — the registry that
                    # produced the tool_start is still right here.
                    "label": labels.get(payload["name"], "checking"),
                    "status": "finished" if payload.get("ok") else "failed",
                    "latency_ms": payload.get("latency_ms"),
                })
            elif kind == "loop_done":
                # The loop's own accumulation is authoritative: it spans
                # every iteration, including a degraded text-only retry
                # whose tokens we may have started emitting mid-turn.
                accumulated = payload.get("text", accumulated)
                tool_trace = payload.get("tool_trace") or []
                iterations = payload.get("iterations", 0)
                degraded = bool(payload.get("degraded"))

        if not accumulated.strip():
            await send(MessageTypes.LLM_ERROR, {
                "thread_id": str(thread.id),
                "error": "The research dive came back with nothing to say.",
                "partial_content": "",
            })
            return

        metadata: dict = {"source": "deep_dive"}
        if tool_trace:
            # Same stamps as the orchestrator: labels baked in so a reader
            # of a months-old trace needs no client-side label table, and
            # proposals hoisted so the Accept cards render off metadata.
            metadata["tools"] = {
                "iterations": iterations,
                "degraded": degraded,
                "calls": [
                    {**entry, "label": labels.get(entry.get("name"), "")}
                    for entry in tool_trace
                ],
            }
            proposal = _hoisted_prediction_proposal(tool_trace)
            if proposal is not None:
                metadata["proposal"] = proposal
            thesis = _hoisted_thesis_proposal(tool_trace)
            if thesis is not None:
                metadata["thesis_proposal"] = thesis
            reading = _hoisted_reading_proposal(tool_trace)
            if reading is not None:
                metadata["reading_proposal"] = reading

        message = await _persist_brief(
            db, thread, accumulated, room.primary_model, metadata,
        )

        # llm_done, not message_created: the streamed tokens are already on
        # the client's synthetic bubble, and llm_done is the event that
        # swaps it for the persisted message — the same contract the summon
        # path uses, metadata included.
        await send(MessageTypes.LLM_DONE, {
            "thread_id": str(thread.id),
            "message_id": str(message.id),
            "content": accumulated,
            "model_used": room.primary_model,
            "truncated": False,
            "sequence": message.sequence,
            "created_at": message.created_at.isoformat(),
            "speaker_type": message.speaker_type.value,
            "message_type": message.message_type.value,
            "metadata": metadata,
        })

    except Exception as e:
        # ToolLoop re-raises a provider death that happens after the first
        # token; the room gets told, and the partial text rides along —
        # exactly the ordinary streaming failure contract.
        logger.exception("Deep dive failed for room %s", room.id)
        await send(MessageTypes.LLM_ERROR, {
            "thread_id": str(thread.id),
            "error": str(e),
            "partial_content": accumulated,
        })
    finally:
        await send(MessageTypes.DEEP_DIVE_DONE, {"thread_id": str(thread.id)})


async def _persist_brief(
    db,
    thread: Thread,
    content: str,
    model_used: str,
    metadata: dict,
) -> Message:
    """Insert the brief as an llm_primary message (+ event), mirroring
    orchestrator._persist_response.

    WHY its own copy: the orchestrator's version is bound to a turn's
    prompt hash / speaker-mode machinery, and a dive is neither a mention
    nor an interjection. What is kept identical is the part that must not
    drift: the atomic sequence insert with the UNIQUE-collision retry.
    """
    now = datetime.now(timezone.utc)
    message_id = uuid4()
    # A brief is prose — running the orchestrator's message-type heuristic
    # on it would gamble on trailing question marks.
    message_type = MessageType.TEXT
    prompt_hash = hashlib.sha256(RESEARCH_IDENTITY.encode()).hexdigest()[:16]

    row = None
    for attempt in range(3):
        try:
            row = await db.fetchrow(
                """INSERT INTO messages
                   (id, thread_id, sequence, created_at, speaker_type, user_id,
                    message_type, content, model_used, prompt_hash, token_count,
                    metadata)
                   VALUES (
                       $1, $2,
                       (SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = $2),
                       $3, $4, $5, $6, $7, $8, $9, $10, $11
                   )
                   RETURNING sequence""",
                message_id, thread.id, now,
                SpeakerType.LLM_PRIMARY.value, None, message_type.value,
                content, model_used, prompt_hash, 0,
                # JSONB: the pool's codec serializes the dict — see
                # CLAUDE.md "pass dict directly to asyncpg".
                metadata,
            )
            break
        except asyncpg.UniqueViolationError:
            if attempt == 2:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
    sequence = row["sequence"]

    message = Message(
        id=message_id,
        thread_id=thread.id,
        sequence=sequence,
        created_at=now,
        speaker_type=SpeakerType.LLM_PRIMARY,
        user_id=None,
        message_type=message_type,
        content=content,
        model_used=model_used,
        prompt_hash=prompt_hash,
        token_count=0,
        metadata=metadata,
    )

    event = Event(
        id=uuid4(),
        timestamp=now,
        event_type=EventType.MESSAGE_CREATED,
        room_id=thread.room_id,
        thread_id=thread.id,
        user_id=None,
        payload=MessageCreatedPayload(
            message_id=message_id,
            sequence=sequence,
            speaker_type=SpeakerType.LLM_PRIMARY,
            user_id=None,
            message_type=message_type,
            content=content,
            model_used=model_used,
            prompt_hash=prompt_hash,
            token_count=0,
        ).model_dump(),
    )

    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        event.id, event.timestamp, event.event_type.value,
        event.room_id, event.thread_id, event.user_id, event.payload,
    )

    return message
