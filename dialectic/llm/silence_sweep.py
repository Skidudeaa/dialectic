# llm/silence_sweep.py — the participation sweep (W6 / P4)

"""
ARCHITECTURE: One 60-second scheduler job — participation_sweep. It walks
every room with a participation-FSM row and acts on the states that mean
"the LLM owes the room a turn": question_pending and ignored. Rooms in
awaiting_human are skipped on purpose (mirror cc-sidecar daemon/timers.py:
the LLM spoke last; human silence there is expected, not a breach).

WHY a new module instead of folding into night_shift.py: night_shift is the
jobs that run while the humans sleep — one wall-clock brief a day. The sweep
is a 60-second liveness job with opposite quiet-hour semantics (it must NOT
speak at night). Different cadence, different guardrails, different module.

GUARDRAILS (locked taste calls, env-tunable where noted):
  - follow-up delay: 10 minutes in question_pending/ignored before the one
    follow-up (FSM_FOLLOWUP_DELAY_MIN)
  - quiet hours: 23:00–07:00 America/Chicago — zero follow-ups, zero FSM
    writes (FSM_QUIET_START / FSM_QUIET_END, "HH:MM")
  - per quiet event: exactly one follow-up — the FollowUpSent transition
    moves the machine OUT of question_pending/ignored, so a second sweep
    finds awaiting_human and skips; the cap is structural, not counted
  - per room: at most DAILY_FOLLOWUP_CAP follow-ups per UTC day, counted on
    the llm_decisions ledger (reason = 'silence_follow_up') — the count_today
    pattern. WHY the decision ledger rather than messages.metadata: the
    follow-up goes through force_response, which already writes the decision
    row with this reason, so the ledger needs no new plumbing.
  - rooms.auto_interjection_enabled = false: no follow-ups (the same toggle
    that now also gates the heuristic path in transport/handlers.py)
  - kill switch: PARTICIPATION_SWEEP_ENABLED (default on)

The sweep also feeds the FSM's timer-driven transitions: a machine whose
state has not changed for DORMANT_AFTER_HOURS is marked dormant with
INFERRED confidence (bypasses the transition table — mirror mark_orphaned).
"""

import logging
import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from scheduler import Job, SchedulerContext
from models import Room, Thread, User
from transport.websocket import OutboundMessage, MessageTypes
from llm.orchestrator import LLMOrchestrator
from llm.participation_fsm import (
    EVENT_FOLLOW_UP_SENT,
    ParticipationFSM,
    ParticipationState,
)
from llm.self_model import SelfModel

logger = logging.getLogger(__name__)

FOLLOWUP_REASON = "silence_follow_up"
DAILY_FOLLOWUP_CAP = 3
QUIET_TZ = "America/Chicago"
RECENT_MESSAGE_WINDOW = 50


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _followup_delay() -> timedelta:
    return timedelta(minutes=_env_int("FSM_FOLLOWUP_DELAY_MIN", 10))


def _dormant_after() -> timedelta:
    return timedelta(hours=_env_int("FSM_DORMANT_HOURS", 24))


def _quiet_bound(env_name: str, default: str) -> time:
    raw = os.environ.get(env_name, default).strip() or default
    try:
        hour, minute = (int(part) for part in raw.split(":"))
        return time(hour, minute)
    except ValueError:
        hour, minute = (int(part) for part in default.split(":"))
        return time(hour, minute)


def in_quiet_hours(now: Optional[datetime] = None) -> bool:
    """Whether `now` (UTC; defaults to the real clock) is inside quiet hours.

    The window may wrap midnight (23:00–07:00 does), so the check is
    "after start OR before end" when start > end.
    """
    tz = ZoneInfo(QUIET_TZ)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    start = _quiet_bound("FSM_QUIET_START", "23:00")
    end = _quiet_bound("FSM_QUIET_END", "07:00")
    current = local.time().replace(tzinfo=None)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


async def _followups_today(conn, room_id) -> int:
    """Follow-ups already sent in this room today (UTC day — count_today
    pattern: a day boundary is something a human can reason about)."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM llm_decisions
           WHERE room_id = $1
           AND should_interject
           AND reason = $2
           AND decided_at >= $3""",
        room_id, FOLLOWUP_REASON, start_of_day,
    )
    return count or 0


async def _load_room_context(conn, room_id):
    """Room/Thread/users/recent messages/memories for force_response.

    Mirrors the loader in transport/handlers.py, minus the typing cache:
    first thread of the room, full membership roster, the visible message
    window, and the standard memory slice.
    """
    room_row = await conn.fetchrow("SELECT * FROM rooms WHERE id = $1", room_id)
    if room_row is None:
        return None
    thread_row = await conn.fetchrow(
        "SELECT * FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
        room_id,
    )
    if thread_row is None:
        return None
    user_rows = await conn.fetch(
        """SELECT u.* FROM users u
           JOIN room_memberships rm ON u.id = rm.user_id
           WHERE rm.room_id = $1""",
        room_id,
    )

    from operations import get_thread_messages
    messages = await get_thread_messages(conn, thread_row["id"], include_ancestry=True)
    messages = messages[-RECENT_MESSAGE_WINDOW:]

    try:
        from memory.manager import MemoryManager
        memories = await MemoryManager(conn).get_context_for_prompt(
            room_id, max_memories=20,
        )
    except Exception:
        logger.debug("Sweep memory context unavailable", exc_info=True)
        memories = []

    return (
        Room(**dict(room_row)),
        Thread(**dict(thread_row)),
        [User(**dict(row)) for row in user_rows],
        messages,
        memories,
    )


async def _broadcast_follow_up(ctx: SchedulerContext, room_id, response) -> None:
    """Push the follow-up to connected clients — force_response persists but
    does not broadcast (that lives in handlers on the human-message path)."""
    if ctx.broadcast is None:
        return
    await ctx.broadcast(room_id, OutboundMessage(
        type=MessageTypes.MESSAGE_CREATED,
        payload={
            "id": str(response.id),
            "thread_id": str(response.thread_id),
            "sequence": response.sequence,
            "created_at": response.created_at.isoformat(),
            "speaker_type": response.speaker_type.value,
            "user_id": None,
            "user_name": "Claude",
            "message_type": response.message_type.value,
            "content": response.content,
            "model_used": response.model_used,
        },
    ))


async def participation_sweep(ctx: SchedulerContext) -> dict:
    """One pass over every room's participation FSM."""
    if in_quiet_hours():
        return {"skipped": "quiet_hours"}

    now = datetime.now(timezone.utc)
    delay = _followup_delay()
    dormant_after = _dormant_after()
    detail: dict = {}

    async with ctx.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ps.room_id, ps.fsm_state, ps.state_entered_at, ps.state_source,
                      r.auto_interjection_enabled
               FROM llm_participation_state ps
               JOIN rooms r ON r.id = ps.room_id
               WHERE ps.fsm_state IS NOT NULL"""
        )

        for row in rows:
            room_id = row["room_id"]
            key = str(room_id)

            if not row["auto_interjection_enabled"]:
                detail[key] = "toggle_off"
                continue

            state = row["fsm_state"]
            entered_at = row["state_entered_at"]

            # Timer-driven transition, bypasses the table (INFERRED): a
            # machine this stale is dormant no matter what it last was.
            if (state != ParticipationState.DORMANT.value
                    and entered_at is not None
                    and now - entered_at > dormant_after):
                fsm = ParticipationFSM.from_snapshot({
                    "state": state,
                    "state_entered_at": entered_at,
                    "state_source": row["state_source"],
                })
                fsm.mark_dormant()
                await SelfModel(conn).update_fsm_state(
                    room_id,
                    fsm_state=fsm.state.value,
                    state_entered_at=fsm.state_entered_at,
                    state_source=fsm.state_source.value,
                )
                detail[key] = "dormant"
                continue

            # awaiting_human / dormant / engaged: nothing owed (mirror
            # daemon/timers.py — waiting on a human is expected silence).
            if state not in (
                ParticipationState.QUESTION_PENDING.value,
                ParticipationState.IGNORED.value,
            ):
                continue

            if entered_at is None or now - entered_at < delay:
                detail[key] = "cooling"
                continue

            if await _followups_today(conn, room_id) >= DAILY_FOLLOWUP_CAP:
                detail[key] = "cap_reached"
                continue

            loaded = await _load_room_context(conn, room_id)
            if loaded is None:
                detail[key] = "no_thread"
                continue
            room, thread, users, messages, memories = loaded

            orchestrator = LLMOrchestrator(conn, db_pool=ctx.pool)
            result = await orchestrator.force_response(
                room=room,
                thread=thread,
                users=users,
                messages=messages,
                memories=memories,
                reason=FOLLOWUP_REASON,
            )
            if not (result.triggered and result.response):
                detail[key] = "follow_up_failed"
                continue

            # The per-event cap is this transition: after FollowUpSent the
            # machine has left question_pending/ignored, so the next pass
            # finds awaiting_human and skips.
            fsm = ParticipationFSM.from_snapshot({
                "state": state,
                "state_entered_at": entered_at,
                "state_source": row["state_source"],
            })
            fsm.apply(EVENT_FOLLOW_UP_SENT)
            await SelfModel(conn).update_fsm_state(
                room_id,
                fsm_state=fsm.state.value,
                state_entered_at=fsm.state_entered_at,
                state_source=fsm.state_source.value,
            )
            await _broadcast_follow_up(ctx, room_id, result.response)
            detail[key] = {"follow_up": str(result.response.id)}

    return detail


def register_sweep_jobs(scheduler) -> None:
    scheduler.register(Job(
        "participation_sweep", 60, participation_sweep,
        enabled_env="PARTICIPATION_SWEEP_ENABLED",
    ))
