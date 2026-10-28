"""The Long Way's two scheduled effects: weekly posts and confirmed git writes."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from scheduler import Job
from models import SpeakerType, MessageType, EventType
from transport.websocket import OutboundMessage, MessageTypes
from .register import append_evidence, CommitsDisabled
from .proposals import review
from .dispatch import draft

logger = logging.getLogger(__name__)


def register_jobs(scheduler):
    scheduler.register(Job("sunday_dispatch", 86400, sunday_dispatch,
                           daily_at="08:00", daily_tz="America/Chicago"))
    scheduler.register(Job("scout_nightly", 86400, scout_nightly,
                           enabled_env="LONGWAY_SCOUT_ENABLED", enabled_default=False,
                           daily_at="02:00", daily_tz="America/Chicago"))
    scheduler.register(Job("evidence_writer", 60, evidence_writer,
                           enabled_env="LONGWAY_COMMIT_ENABLED", enabled_default=False))


async def evidence_writer(ctx):
    if os.environ.get("LONGWAY_COMMIT_ENABLED") != "1":
        return {"queued": True, "written": 0}
    results = {}
    async with ctx.pool.acquire() as db:
        pending = await db.fetch("SELECT id FROM longway_evidence_proposals WHERE written_at IS NULL ORDER BY created_at LIMIT 100")
        for pending_row in pending:
            pid = pending_row["id"]
            try:
                async with db.transaction():
                    row = await db.fetchrow("SELECT * FROM longway_evidence_proposals WHERE id=$1 AND written_at IS NULL FOR UPDATE SKIP LOCKED", pid)
                    if not row:
                        continue
                    state = await review(db, row, lock=True)
                    mark = state["confirmation"]
                    if not mark or (row["load_bearing"] and not row["counter_searched_at"]):
                        continue
                    actor = await db.fetchrow("""SELECT u.id,u.display_name,c.email FROM users u
                        JOIN user_credentials c ON c.user_id=u.id WHERE u.id=$1""", mark["actor_user_id"])
                    if not actor:
                        results[str(pid)] = "confirming member lacks git identity"
                        continue
                    entry = {k: row[k] for k in ("url", "claim", "scope", "support", "publisher")}
                    scope_fields = [f"{key}: {row[key]}" for key in ('direction','passport','vehicle') if row[key]]
                    if scope_fields:
                        entry['scope'] += '; ' + '; '.join(scope_fields)
                    if row['applies_from'] and row['applies_to']:
                        entry['applies'] = f"{row['applies_from'].isoformat()} to {row['applies_to'].isoformat()}"
                    elif row['applies_from'] or row['applies_to']:
                        key = 'applies_from' if row['applies_from'] else 'applies_to'
                        entry['applies'] = ('from ' if key == 'applies_from' else 'until ') + row[key].isoformat()
                    entry['checked_by'] = actor['display_name']
                    entry.update(status="verified", checked_at=mark["created_at"].date().isoformat(),
                                 published_at=row["published_at"].isoformat() if row["published_at"] else None,
                                 recheck_before="set by the researcher")
                    task = asyncio.create_task(asyncio.to_thread(append_evidence, row["candidate"], entry,
                        actor["display_name"], actor["email"], proposal_id=str(pid)))
                    try:
                        written = await asyncio.shield(task)
                    except asyncio.CancelledError:
                        # Keep Field locks until the filesystem operation ends.
                        # Its proposal trailer repairs the un-stamped DB row.
                        await task
                        raise
                    await db.execute("""UPDATE longway_evidence_proposals
                        SET written_sid=$2,written_at=clock_timestamp(),written_commit=$3,written_by=$4
                        WHERE id=$1""", pid, written["sid"], written["commit"], actor["id"])
                    results[str(pid)] = written
            except CommitsDisabled:
                results[str(pid)] = "queued"
            except Exception as exc:
                logger.exception("Evidence proposal %s remains queued", pid)
                results[str(pid)] = {"error": str(exc)}
    return results


async def _post_dispatch(db, ctx, room, content, week_of):
    metadata = {"longway_dispatch": {"journey": room["linked_journey"], "week_of": week_of}}
    return await post_participant(db, ctx, room, content, metadata, 'longway_dispatch', 'week_of', week_of)


async def post_participant(db, ctx, room, content, metadata, kind, dedup_field, dedup_value):
    """The night_shift posting pattern, with participant lane and own metadata.

    WHY a local adapter: the shared helper hardcodes annotator/night_shift and
    broadcasts before commit. The Long Way needs participant attribution and
    durable weekly deduplication before announcing a message.
    """
    async with db.transaction():
        await db.fetchval("SELECT id FROM rooms WHERE id=$1 FOR NO KEY UPDATE", room["id"])
        exists = await db.fetchval("""SELECT 1 FROM messages m JOIN threads t ON t.id=m.thread_id
            WHERE t.room_id=$1 AND m.metadata->$2->>$3=$4 LIMIT 1""", room["id"], kind, dedup_field, dedup_value)
        if exists:
            return None
        thread = await db.fetchval("SELECT id FROM threads WHERE room_id=$1 ORDER BY created_at,id LIMIT 1 FOR UPDATE", room["id"])
        if not thread:
            # A receipt must exist even in a newly bound room with no thread.
            thread = uuid4()
            await db.execute("INSERT INTO threads(id,room_id,created_at,title) VALUES ($1,$2,clock_timestamp(),'Main')", thread, room['id'])
        mid = uuid4()
        row = await db.fetchrow("""INSERT INTO messages
            (id,thread_id,sequence,created_at,speaker_type,message_type,content,metadata)
            VALUES ($1,$2,(SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE thread_id=$2),
                clock_timestamp(),$3,$4,$5,$6) RETURNING *""",
            mid, thread, SpeakerType.LLM_PRIMARY.value, MessageType.TEXT.value, content, metadata)
        await db.execute("""INSERT INTO events(id,timestamp,event_type,room_id,thread_id,payload)
            VALUES ($1,clock_timestamp(),$2,$3,$4,$5)""", uuid4(), EventType.MESSAGE_CREATED.value,
            room["id"], thread, {"message_id": str(mid), "source": kind})
    if ctx.broadcast:
        await ctx.broadcast(room["id"], OutboundMessage(type=MessageTypes.MESSAGE_CREATED, payload={
            "id": str(mid), "thread_id": str(thread), "sequence": row["sequence"],
            "speaker_type": SpeakerType.LLM_PRIMARY.value, "message_type": MessageType.TEXT.value,
            "content": content, "created_at": row["created_at"].isoformat(), "metadata": metadata,
        }))
    return str(mid), str(thread)


async def _push_dispatch(db, ctx, room, content, message_id, thread_id):
    # Same active-room recipient filter and deep link as night_shift._push_brief.
    from api.notifications.webpush import send_web_notifications
    members = await db.fetch("SELECT user_id FROM room_memberships WHERE room_id=$1", room["id"])
    recipients = []
    for member in members:
        connected = False
        if ctx.connection_manager:
            try:
                connected = ctx.connection_manager.is_user_connected(member["user_id"], room["id"])
            except Exception:
                logger.debug("Connection check unavailable", exc_info=True)
        if not connected:
            recipients.append(str(member["user_id"]))
    if recipients:
        await send_web_notifications(db=db, recipient_user_ids=recipients,
            title=f"{room['name']}: Sunday dispatch", body=content[:240],
            data={"room_id": str(room["id"]), "type": "longway_dispatch", "message_id": message_id, "thread_id": thread_id},
            tag=f"longway_dispatch_{room['id']}")
    return len(recipients)


async def dispatch_now(ctx, room_id, *, now=None):
    """A manager's "send this week's dispatch now": the Sunday post for one room, today, pushed.

    WHY a door beside the clock: the ritual is the pull mechanism, and a ritual that cannot be seen before its
    first Sunday cannot be judged. Same draft, same post, same push, same per-day deduplication (a second press
    the same day returns the existing message instead of a duplicate). No weekday check.
    """
    now = now or datetime.now(timezone.utc)
    week_of = now.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    async with ctx.pool.acquire() as db:
        room = await db.fetchrow("SELECT id,name,linked_journey,is_home FROM rooms WHERE id=$1", room_id)
        if not room or not (room["is_home"] or room["linked_journey"]):
            raise ValueError("The dispatch goes to the house or to a room bound to a journey")
        existing = await db.fetchval("""SELECT m.id FROM messages m JOIN threads t ON t.id=m.thread_id
            WHERE t.room_id=$1 AND m.metadata->'longway_dispatch'->>'week_of'=$2 ORDER BY m.created_at DESC LIMIT 1""", room["id"], week_of)
        if existing:
            return {"message_id": str(existing), "pushed": 0, "already": True}
        content = await draft(room["linked_journey"], now, db=db, room_id=room["id"])
        posted = await _post_dispatch(db, ctx, room, content, week_of)
        if not posted:
            existing = await db.fetchval("""SELECT m.id FROM messages m JOIN threads t ON t.id=m.thread_id
                WHERE t.room_id=$1 AND m.metadata->'longway_dispatch'->>'week_of'=$2 ORDER BY m.created_at DESC LIMIT 1""", room["id"], week_of)
            return {"message_id": str(existing) if existing else None, "pushed": 0, "already": True}
        mid, thread = posted
        pushed = await _push_dispatch(db, ctx, room, content, mid, thread)
        return {"message_id": mid, "pushed": pushed, "already": False}


async def sunday_dispatch(ctx, *, now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/Chicago"))
    if local.weekday() != 6:
        return {"skipped": "not Sunday"}
    week_of = local.date().isoformat()
    result = {}
    async with ctx.pool.acquire() as db:
        rooms = await db.fetch("""SELECT r.id,r.name,r.linked_journey FROM rooms r
            WHERE r.is_home OR (r.linked_journey IS NOT NULL AND EXISTS (
              SELECT 1 FROM messages m JOIN threads t ON t.id=m.thread_id
              WHERE t.room_id=r.id AND m.speaker_type='human' AND NOT m.is_deleted AND m.created_at >= $1))
            ORDER BY r.id""", now-timedelta(days=14))
        for room in rooms:
            try:
                exists = await db.fetchval("""SELECT 1 FROM messages m JOIN threads t ON t.id=m.thread_id
                    WHERE t.room_id=$1 AND m.metadata->'longway_dispatch'->>'week_of'=$2 LIMIT 1""", room["id"], week_of)
                if exists:
                    continue
                content = await draft(room["linked_journey"], now, db=db, room_id=room["id"])
                posted = await _post_dispatch(db, ctx, room, content, week_of)
                if posted:
                    mid, thread = posted
                    pushed = await _push_dispatch(db, ctx, room, content, mid, thread)
                    result[str(room["id"])] = {"message_id": mid, "pushed": pushed}
            except Exception as exc:
                logger.exception("Sunday dispatch failed for %s", room["id"])
                result[str(room["id"])] = {"error": str(exc)}
    return result


async def scout_nightly(ctx):
    if os.environ.get('LONGWAY_SCOUT_ENABLED') != '1':
        return {'skipped': 'disabled'}
    from .scout import run, AlreadyRunning
    async with ctx.pool.acquire() as db:
        rooms = await db.fetch("""SELECT id,linked_journey FROM rooms r WHERE NOT is_home
            AND linked_journey IS NOT NULL AND EXISTS (SELECT 1 FROM longway_questions q
                WHERE q.journey=r.linked_journey AND q.closed_at IS NULL)
            ORDER BY r.id""")
    result = {}
    for room in rooms:
        try:
            result[str(room['id'])] = await run(ctx.pool, room['id'], room['linked_journey'], trigger='nightly', ctx=ctx)
        except AlreadyRunning:
            result[str(room['id'])] = {'skipped': 'running'}
    return result
