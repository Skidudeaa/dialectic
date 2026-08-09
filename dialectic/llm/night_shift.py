# llm/night_shift.py — the jobs that run while the humans sleep

"""
ARCHITECTURE: One daily scheduler job — morning_brief at 07:00
America/Chicago. It iterates rooms with any message in the last 48h, builds
the SAME briefing the /rooms/{id}/briefing endpoint serves (llm/briefing.py,
since = now-24h), posts it as an annotator-lane message, and web-pushes the
members who aren't looking at the room.

WHY: async dialogue only works if the room comes to you. A brief that waits
for someone to ask is a feature nobody remembers; a 7am brief on the phone
is how the room re-enters the day.

GUARDRAILS:
  - enabled_env NIGHT_SHIFT_ENABLED (kill switch, default on)
  - hard cap of NIGHT_SHIFT_LLM_CAP briefs per UTC-day, counted by posted
    night_shift messages (TradingCurator.count_today pattern) — each brief
    is at most one Haiku call, so the message count IS the LLM budget
  - rooms quiet for 48h are never iterated; rooms with nothing to say
    (no missed messages, no expiring commitments, no unanswered questions)
    are skipped without an LLM call

TRADEOFF: annotator posts do NOT push for free — the job calls
send_web_notifications itself, with the trading_ingest._push_critical
recipient filter (room members minus active WS connections to the room).
"""

import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from scheduler import Job, SchedulerContext
from models import SpeakerType, MessageType, EventType
from transport.websocket import OutboundMessage, MessageTypes
from llm.briefing import BriefingResponse, build_briefing

logger = logging.getLogger(__name__)

ACTIVE_WINDOW_HOURS = 48
BRIEF_WINDOW_HOURS = 24
NIGHT_SHIFT_LLM_CAP = 20


async def _active_rooms(pool):
    """Rooms with any message in the last 48h (mirror _linked_rooms)."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT DISTINCT r.id, r.name
               FROM rooms r
               JOIN threads t ON t.room_id = r.id
               JOIN messages m ON m.thread_id = t.id
               WHERE m.created_at > now() - interval '48 hours'"""
        )


async def _briefs_posted_today(conn) -> int:
    """Night-shift briefs posted so far today (UTC) — the LLM budget gauge.

    WHY UTC-day rather than a rolling window: mirrors count_today — a day
    boundary is something a human can reason about, and the brief is itself
    a once-a-day thing.
    """
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM messages m
           JOIN threads t ON m.thread_id = t.id
           WHERE m.speaker_type = $1
           AND m.created_at >= $2
           AND m.metadata->>'source' = 'night_shift'""",
        SpeakerType.LLM_ANNOTATOR.value, start_of_day,
    )
    return count or 0


def _render_brief(briefing: BriefingResponse) -> str:
    """Deterministic message text: summary first, then the fact sections."""
    lines = [f"☀️ Morning brief — {briefing.summary}"]
    if briefing.thesis_staleness:
        hours = briefing.thesis_staleness["stale_hours"]
        lines.append(
            f"📉 Thesis data is {hours:g}h old — treat its numbers accordingly."
        )
    for c in briefing.commitments_due[:5]:
        deadline = c["deadline"]
        when = deadline.strftime("%b %d %H:%M UTC") if hasattr(deadline, "strftime") else str(deadline)
        lines.append(f"⏳ Commitment due {when}: {c['claim'][:140]}")
    for q in briefing.unanswered_questions[:5]:
        lines.append(f"❓ Unanswered ({q.speaker}): {q.content_preview[:140]}")
    return "\n".join(lines)


async def _post_brief_message(conn, ctx, room, content: str) -> str:
    """Annotator-lane brief, mirroring trading_watch._post_watchdog_message."""
    msg_id = uuid4()
    now = datetime.now(timezone.utc)
    thread_row = await conn.fetchrow(
        "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
        room["id"],
    )
    if thread_row is None:
        return "no_thread"
    metadata = {"source": "night_shift"}
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
        {"message_id": str(msg_id), "source": "night_shift"},
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


async def _push_brief(conn, ctx, room, briefing: BriefingResponse) -> int:
    """Web-push the brief to members without an active WS to the room.

    Recipient filter mirrors trading_ingest._push_critical: a brief is not
    an ordinary message — only an ACTIVE WebSocket connection to this room
    counts as "already seeing it". No connection manager on the context
    means push everyone (the safe direction to be wrong in).
    """
    members = await conn.fetch(
        "SELECT user_id FROM room_memberships WHERE room_id = $1", room["id"]
    )
    recipients = []
    for member in members:
        user_id = member["user_id"]
        mgr = ctx.connection_manager
        if mgr is not None:
            try:
                if mgr.is_user_connected(user_id, room["id"]):
                    continue
            except Exception:  # noqa: BLE001 — unknown manager shape pushes
                logger.debug("connection check unavailable; pushing anyway",
                             exc_info=True)
        recipients.append(str(user_id))

    if not recipients:
        return 0

    from api.notifications.webpush import send_web_notifications

    await send_web_notifications(
        db=conn,
        recipient_user_ids=recipients,
        title=f"{room['name']}: morning brief",
        body=briefing.summary,
        data={"room_id": str(room["id"]), "type": "morning_brief"},
        tag=f"brief_{room['id']}",
    )
    return len(recipients)


async def morning_brief(ctx: SchedulerContext) -> dict:
    """Post (and push) the 7am brief into every recently-active room."""
    detail: dict = {}
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=BRIEF_WINDOW_HOURS)
    rooms = await _active_rooms(ctx.pool)

    async with ctx.pool.acquire() as conn:
        posted = await _briefs_posted_today(conn)
        for room in rooms:
            room_key = str(room["id"])
            if posted >= NIGHT_SHIFT_LLM_CAP:
                detail[room_key] = "cap_reached"
                continue

            briefing = await build_briefing(conn, room["id"], since)
            if (briefing.messages_missed == 0
                    and not briefing.commitments_due
                    and not briefing.unanswered_questions):
                detail[room_key] = "quiet"
                continue

            content = _render_brief(briefing)
            msg_id = await _post_brief_message(conn, ctx, room, content)
            if msg_id == "no_thread":
                detail[room_key] = "no_thread"
                continue
            pushed = await _push_brief(conn, ctx, room, briefing)
            posted += 1
            detail[room_key] = {
                "message_id": msg_id,
                "messages_missed": briefing.messages_missed,
                "pushed": pushed,
            }
    return detail


def register_brief_jobs(scheduler) -> None:
    scheduler.register(Job(
        "morning_brief", 86400, morning_brief,
        enabled_env="NIGHT_SHIFT_ENABLED",
        daily_at="07:00", daily_tz="America/Chicago",
    ))
