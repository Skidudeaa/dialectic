# api/trading_ingest.py — snapshot receipt, independent of the HTTP route

"""
ARCHITECTURE: Everything that happens when a trading snapshot arrives —
persist, upsert the room memory, log the event, broadcast, and decide
whether a human needs to be told. The route in api/main.py keeps only
auth, body parsing and version validation.

WHY the split: receipt has three callers with different intent. The bridge
POST is a live push and should alert. The scheduler's reconcile job is a
repair read of a snapshot the room may already have seen, and must never
alert. Tests want the receipt semantics without a live server. One
function with an explicit `fire_curator` flag beats three copies drifting.

WHY the curator is now gated on events rather than fired on every receipt:
the coordinator pushes every 300s per book. Firing an LLM alert on each
one meant the room's alert history was mostly "nothing happened, here is a
paragraph about nothing" — the 5-minute dedup was the only thing keeping it
survivable, which made the dedup window load-bearing for cost rather than
for sense. v3 payloads state what actually changed, so silence is now
expressible.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from models import (
    EventType,
    MemoryScope,
    TradingSnapshotRequest,
)
from memory.manager import MemoryManager
from transport.websocket import OutboundMessage, MessageTypes
from llm.trading_curator import TradingCuratorEngine
from api.trading import TradingSnapshotResponse, format_thesis_summary

logger = logging.getLogger(__name__)

# The deterministic memory slot that shadows rooms.trading_config, so recall
# can find the live thesis without reading JSONB. It is named here, once,
# because three call sites now depend on it -- this upsert, the retire path in
# api/thesis_relay.py, and the thesis adapter in workspace_objects.py, which
# must fold the slot back into the thesis it shadows rather than projecting it
# as a second, independently-worded object.
THESIS_STATE_MEMORY_KEY = "thesis_state_current"


# WHY 8/day: two humans and a thesis book. More than eight unprompted LLM
# paragraphs in a waking day is a notification the room learns to ignore,
# which costs more than the alerts are worth. Criticals are exempt — a node
# firing is the event the whole pipeline exists to deliver, and suppressing
# the ninth one because eight warnings arrived first would be exactly the
# wrong failure.
CURATOR_DAILY_CAP = 8

# Dedup windows by severity. A critical repeating inside 5 minutes is
# genuinely new; a warning repeating inside 30 is the same warning.
CRITICAL_DEDUP_MINUTES = 5
WARNING_DEDUP_MINUTES = 30

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def max_severity(alert_events: list[dict]) -> Optional[str]:
    """Highest severity present, or None for an empty/severity-less list."""
    best: Optional[str] = None
    best_rank = -1
    for event in alert_events or []:
        if not isinstance(event, dict):
            continue
        severity = str(event.get("severity") or "").lower()
        rank = _SEVERITY_RANK.get(severity, -1)
        if rank > best_rank:
            best_rank = rank
            best = severity
    return best


def critical_events(alert_events: list[dict]) -> list[dict]:
    return [
        e for e in (alert_events or [])
        if isinstance(e, dict)
        and str(e.get("severity") or "").lower() == "critical"
    ]


def curator_plan(request: TradingSnapshotRequest) -> Optional[dict]:
    """Decide whether the curator runs, and under which limits.

    Returns None to stay silent, else {'dedup_window_minutes', 'daily_cap'}.

    v3 payloads carry alertEvents and are therefore self-describing: no
    warning or critical means nothing worth waking anyone for. v1 and v2
    make no such statement — the CLI bridge and any older pusher predate the
    field entirely — so they keep the legacy behavior of alerting on every
    receipt, still gated on somebody being offline.
    """
    if request.v >= 3:
        severity = max_severity(request.alertEvents)
        if severity == "critical":
            # Criticals bypass the daily cap but NOT dedup.
            return {
                "dedup_window_minutes": CRITICAL_DEDUP_MINUTES,
                "daily_cap": None,
            }
        if severity == "warning":
            return {
                "dedup_window_minutes": WARNING_DEDUP_MINUTES,
                "daily_cap": CURATOR_DAILY_CAP,
            }
        return None

    # Legacy v1/v2 — unchanged trigger, plus the room-level daily budget.
    return {
        "dedup_window_minutes": CRITICAL_DEDUP_MINUTES,
        "daily_cap": CURATOR_DAILY_CAP,
    }


def _push_text(room_name: str, events: list[dict]) -> tuple[str, str]:
    """Build (title, one-line body) for a critical web push."""
    first = events[0]
    node = first.get("node_id") or first.get("event_type") or "state"
    new_value = first.get("new_value")
    title = f"{room_name}: {node} {new_value}"

    parts = []
    for event in events[:3]:
        node_id = event.get("node_id") or event.get("event_type") or "state"
        old = event.get("old_value")
        new = event.get("new_value")
        parts.append(f"{node_id} {old} → {new}")
    body = "; ".join(parts)
    if len(events) > 3:
        body += f"; +{len(events) - 3} more"
    return title, body


async def _push_critical(db, connection_manager, room_id: UUID,
                         events: list[dict], *,
                         thread_id: UUID | None = None,
                         message_id: UUID | None = None) -> None:
    """Web-push a critical transition to every room member not looking at it.

    WHY every member rather than only the offline ones: an ordinary message
    push is suppressed for anyone marked 'online', because a person who is
    present will see it. A node firing is not an ordinary message — the
    room may be open in a background tab for hours. Only an ACTIVE WebSocket
    connection to this room is treated as "they are already seeing it".

    LIMIT: is_user_connected only knows this server's connections. Under the
    Redis manager a user connected to another instance would still be
    pushed. That is the safe direction to be wrong in.
    """
    room = await db.fetchrow("SELECT name FROM rooms WHERE id = $1", room_id)
    room_name = (room and room["name"]) or "Trading"

    members = await db.fetch(
        "SELECT user_id FROM room_memberships WHERE room_id = $1", room_id,
    )
    recipients = []
    for member in members:
        user_id = member["user_id"]
        try:
            if connection_manager.is_user_connected(user_id, room_id):
                continue
        except Exception:  # noqa: BLE001 — an unknown manager shape pushes
            logger.debug("connection check unavailable; pushing anyway",
                         exc_info=True)
        recipients.append(str(user_id))

    if not recipients:
        return

    title, body = _push_text(room_name, events)
    from api.notifications.webpush import send_web_notifications

    # Carry the alert's own coordinates when the curator produced one. A
    # room-only payload lands the tap on the legacy `open-room` branch, which
    # moves no navigation state — so the reader arrives at the list they were
    # already looking at and the alert is not on it.
    data = {"room_id": str(room_id), "type": "trading_alert"}
    if thread_id is not None and message_id is not None:
        data["thread_id"] = str(thread_id)
        data["message_id"] = str(message_id)

    await send_web_notifications(
        db,
        recipients,
        title,
        body,
        data,
        tag=f"trading_{room_id}",
    )


async def ingest_snapshot(
    db,
    connection_manager,
    room_id: UUID,
    request: TradingSnapshotRequest,
    *,
    fire_curator: bool = True,
) -> TradingSnapshotResponse:
    """Store a trading snapshot and notify whoever needs to know.

    `fire_curator=False` makes receipt purely archival: persist, upsert the
    memory, log, broadcast to anyone watching — but no LLM alert and no web
    push. It is the reconcile path's setting, because a repair read of an
    existing snapshot is not news.

    Assumes the caller has already verified the room token and validated
    the payload version.
    """
    now = datetime.now(timezone.utc)
    snapshot_data = request.model_dump()

    # Store raw snapshot in rooms.trading_config
    # WHY: Pass dict directly — the pool's JSONB codec (registered in lifespan
    # with UUID/datetime support) serializes it correctly. Avoids double-encoding
    # that json.dumps() + ::jsonb cast would produce.
    await db.execute(
        """UPDATE rooms
           SET trading_config = $2,
               last_trading_push_at = $3,
               trading_push_count = trading_push_count + 1
           WHERE id = $1""",
        room_id, snapshot_data, now
    )

    # Format human-readable summary for memory
    summary = format_thesis_summary(request)

    # Upsert memory: check for existing key, update if found, create if not
    memory_manager = MemoryManager(db)
    memory_key = THESIS_STATE_MEMORY_KEY

    # WHY fetch (plural) and heal: the slot's invariant is ONE active row,
    # but the check-then-insert below has no DB constraint behind it, so two
    # ingests racing (instant adoption push + tick, live push + reconcile)
    # can twin the slot — observed live 2026-08-12, two actives 115ms apart.
    # Editing the NEWEST and flipping the twins keeps the slot self-healing:
    # a duplicate survives at most until the next push.
    existing_rows = await db.fetch(
        """SELECT id FROM memories
           WHERE room_id = $1 AND key = $2 AND status = 'active'
           ORDER BY created_at DESC""",
        room_id, memory_key
    )
    existing = existing_rows[0] if existing_rows else None
    if len(existing_rows) > 1:
        stale_ids = [r["id"] for r in existing_rows[1:]]
        logger.warning(
            "thesis_state_current slot had %d active rows in room %s — healing",
            len(existing_rows), room_id,
        )
        await db.execute(
            "UPDATE memories SET status = 'invalidated' WHERE id = ANY($1)",
            stale_ids,
        )

    if existing:
        memory = await memory_manager.edit_memory(
            memory_id=existing['id'],
            new_content=summary,
            edit_reason="Trading snapshot updated",
        )
        memory_id = memory.id
    else:
        memory = await memory_manager.add_memory(
            room_id=room_id,
            key=memory_key,
            content=summary,
            scope=MemoryScope.ROOM,
            # thesis_state_current is a deterministic-key slot upserted above.
            dedup=False,
        )
        memory_id = memory.id

    # Log TRADING_SNAPSHOT_RECEIVED event
    node_count = len(request.nodeStates)
    phase_key = None
    if request.cascadePhase:
        phase_key = request.cascadePhase.get("key")

    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, payload)
           VALUES ($1, $2, $3, $4, $5)""",
        uuid4(), now, EventType.TRADING_SNAPSHOT_RECEIVED.value,
        room_id,
        {
            "timestamp": request.timestamp,
            "node_count": node_count,
            "phase": phase_key,
            "memory_id": str(memory_id),
            "alert_events": len(request.alertEvents),
            "severity": max_severity(request.alertEvents),
        }
    )

    # Broadcast to connected WebSocket clients
    await connection_manager.broadcast(room_id, OutboundMessage(
        type=MessageTypes.TRADING_UPDATE,
        payload=snapshot_data,
    ))

    if fire_curator:
        await _notify(db, connection_manager, room_id, request, snapshot_data)

    return TradingSnapshotResponse(
        stored_at=now.isoformat(),
        memory_id=memory_id,
    )


async def _notify(db, connection_manager, room_id: UUID,
                  request: TradingSnapshotRequest, snapshot_data: dict) -> None:
    """Curator alert + critical web push. Neither may fail the receipt."""
    alert_thread_id = None
    alert_message_id = None
    plan = curator_plan(request)
    if plan is not None:
        try:
            memory_manager = MemoryManager(db)
            curator = TradingCuratorEngine(db, memory_manager, None)
            thread_row = await db.fetchrow(
                "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
                room_id
            )
            if thread_row:
                alert = await curator.generate_alert(
                    room_id, thread_row["id"], snapshot_data,
                    dedup_window_minutes=plan["dedup_window_minutes"],
                    daily_cap=plan["daily_cap"],
                )
                if alert:
                    alert_thread_id = thread_row["id"]
                    alert_message_id = alert.id
                    await connection_manager.broadcast(room_id, OutboundMessage(
                        type=MessageTypes.TRADING_UPDATE,
                        payload={"message": alert.model_dump(mode="json")},
                    ))
        except Exception as e:
            logger.warning(f"Trading curator alert failed (non-critical): {e}")

    criticals = critical_events(request.alertEvents)
    if criticals:
        try:
            await _push_critical(
                db, connection_manager, room_id, criticals,
                thread_id=alert_thread_id, message_id=alert_message_id,
            )
        except Exception as e:
            # A push failure must never turn a stored snapshot into a 500.
            logger.warning(f"Trading critical push failed (non-critical): {e}")
