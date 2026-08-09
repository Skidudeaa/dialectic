"""
Bloodstream jobs: keep trading data fresh, and tell the humans when it isn't.

ARCHITECTURE: Three scheduler jobs.
  - trading_reconcile (15 min): pull the latest snapshot from tradingDesk and
    self-ingest if it is newer than what the room holds. The self-healing
    layer — survives push-path bugs, env loss, and token rot independently.
  - trading_freshness_watchdog (30 min): if a linked room's feed has been
    quiet >3h, post ONE deterministic in-room warning (no LLM); at >12h,
    escalate once with a web push to the members.
  - scheduler_heartbeat (10 min): writes only its ledger row — proves the
    scheduler itself is alive (the acceptance check queries it).

WHY: the Iran room sat 64 days stale with nothing anywhere that could
notice. Layer 1 (tradingDesk pushes) can rot silently; these jobs make
silent death impossible: either the data heals itself or the humans are
told, in-room, automatically.

TRADEOFF: the watchdog message is deterministic text, not a curator/LLM
message — a warning about a broken pipe must not depend on the LLM pipeline
being healthy.
"""

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from scheduler import Job, SchedulerContext
from models import SpeakerType, MessageType, EventType
from transport.websocket import OutboundMessage, MessageTypes

logger = logging.getLogger(__name__)

TRADINGDESK_URL = os.environ.get("TRADINGDESK_URL", "http://127.0.0.1:8006")
SELF_URL = os.environ.get("DIALECTIC_SELF_URL", "http://127.0.0.1:8002")

WATCHDOG_WARN_HOURS = 3
WATCHDOG_ESCALATE_HOURS = 12


async def _linked_rooms(pool):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, name, token, linked_book_id, last_trading_push_at,
                      created_at, trading_config->>'timestamp' AS snap_ts
               FROM rooms WHERE linked_book_id IS NOT NULL"""
        )


# ── trading_reconcile ─────────────────────────────────────────────


async def trading_reconcile(ctx: SchedulerContext) -> dict:
    """Pull latest snapshot per linked book; self-ingest if newer.

    NOTE: the tradingDesk read endpoint (/api/bridge/snapshot/{book}) ships
    with the coordinator-push work (fusion Part B4). Until then this job
    records 'endpoint_missing' per book and is harmless by design.
    """
    detail: dict = {}
    rooms = await _linked_rooms(ctx.pool)
    token = os.environ.get("TD_SERVICE_TOKEN", "")
    headers = {"X-Service-Token": token} if token else {}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for room in rooms:
            book = room["linked_book_id"]
            try:
                resp = await client.get(
                    f"{TRADINGDESK_URL}/api/bridge/snapshot/{book}",
                    headers=headers,
                )
            except httpx.HTTPError as e:
                detail[book] = f"unreachable: {type(e).__name__}"
                continue
            if resp.status_code == 404:
                detail[book] = "endpoint_missing"
                continue
            if resp.status_code != 200:
                detail[book] = f"http_{resp.status_code}"
                continue
            # tradingDesk's SPA catch-all answers unknown paths with 200 +
            # index.html — a 200 is not proof the endpoint exists yet.
            if not resp.headers.get("content-type", "").startswith("application/json"):
                detail[book] = "endpoint_missing"
                continue

            try:
                snapshot = resp.json()
            except ValueError:
                detail[book] = "bad_json"
                continue
            new_ts = snapshot.get("timestamp") or ""
            cur_ts = room["snap_ts"] or ""
            if new_ts <= cur_ts:
                detail[book] = "current"
                continue

            # Self-ingest through the real endpoint so ALL receipt semantics
            # (memory upsert, event, broadcast, curator gating) apply.
            # ?source=reconcile: a 15-min-old repair is not an event — the
            # ingest path suppresses the curator for reconcile pulls even if
            # the payload ever starts carrying alertEvents (defence in depth).
            ingest = await client.post(
                f"{SELF_URL}/rooms/{room['id']}/trading/snapshot?source=reconcile",
                headers={"X-Room-Token": room["token"]},
                json=snapshot,
            )
            detail[book] = f"ingested_{ingest.status_code}"
    return detail


# ── trading_freshness_watchdog ────────────────────────────────────


WATCHDOG_TEXT = (
    "⚠️ Trading feed has been quiet since {since} ({hours}h). tradingDesk "
    "may be down or the bridge broken. The thesis state shown is aging — "
    "treat its numbers accordingly."
)


async def trading_freshness_watchdog(ctx: SchedulerContext) -> dict:
    detail: dict = {}
    now = datetime.now(timezone.utc)
    rooms = await _linked_rooms(ctx.pool)

    async with ctx.pool.acquire() as conn:
        for room in rooms:
            last = room["last_trading_push_at"] or room["created_at"]
            hours = (now - last).total_seconds() / 3600
            if hours < WATCHDOG_WARN_HOURS:
                detail[room["linked_book_id"]] = "fresh"
                continue

            # ONE warning per outage: a watchdog message newer than the last
            # successful push means this outage is already announced.
            existing = await conn.fetchrow(
                """SELECT m.id, m.metadata FROM messages m
                   JOIN threads t ON m.thread_id = t.id
                   WHERE t.room_id = $1
                     AND m.metadata->>'source' = 'trading_watchdog'
                     AND m.created_at > $2
                   ORDER BY m.created_at DESC LIMIT 1""",
                room["id"], last,
            )

            if existing is None:
                msg_id = await _post_watchdog_message(
                    conn, ctx, room, last, int(hours)
                )
                detail[room["linked_book_id"]] = f"warned:{msg_id}"
                continue

            # Escalate exactly once per outage at the 12h line.
            meta = existing["metadata"] or {}
            if hours >= WATCHDOG_ESCALATE_HOURS and not meta.get("escalated"):
                await _escalate_push(conn, room, int(hours))
                meta["escalated"] = True
                await conn.execute(
                    "UPDATE messages SET metadata = $2 WHERE id = $1",
                    existing["id"], meta,
                )
                detail[room["linked_book_id"]] = "escalated"
            else:
                detail[room["linked_book_id"]] = "already_warned"
    return detail


async def _post_watchdog_message(conn, ctx, room, last, hours: int) -> str:
    """Deterministic annotator-lane message, mirroring the curator persist."""
    msg_id = uuid4()
    now = datetime.now(timezone.utc)
    thread_row = await conn.fetchrow(
        "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
        room["id"],
    )
    if thread_row is None:
        return "no_thread"
    content = WATCHDOG_TEXT.format(
        since=last.strftime("%Y-%m-%d %H:%M UTC"), hours=hours
    )
    metadata = {"source": "trading_watchdog"}
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
        {"message_id": str(msg_id), "source": "trading_watchdog"},
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


async def _escalate_push(conn, room, hours: int) -> None:
    from api.notifications.webpush import send_web_notifications

    members = await conn.fetch(
        "SELECT user_id FROM room_memberships WHERE room_id = $1", room["id"]
    )
    if not members:
        return
    await send_web_notifications(
        db=conn,
        recipient_user_ids=[str(m["user_id"]) for m in members],
        title=f"{room['name']}: trading feed down",
        body=f"No snapshot for {hours}h. tradingDesk or the bridge needs a look.",
        data={"room_id": str(room["id"]), "type": "trading_feed_down"},
        tag=f"trading_feed_{room['id']}",
    )


# ── heartbeat ─────────────────────────────────────────────────────


async def scheduler_heartbeat(ctx: SchedulerContext) -> dict:
    return {"alive": True}


def register_bloodstream_jobs(scheduler) -> None:
    scheduler.register(Job("scheduler_heartbeat", 600, scheduler_heartbeat))
    scheduler.register(Job("trading_reconcile", 900, trading_reconcile))
    scheduler.register(Job("trading_freshness_watchdog", 1800, trading_freshness_watchdog))
