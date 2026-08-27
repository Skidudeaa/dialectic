# transport/websocket.py — WebSocket connection management

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    """Single WebSocket connection."""
    websocket: WebSocket
    user_id: UUID
    room_id: UUID
    thread_id: Optional[UUID] = None
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Typing analysis cache (ephemeral, never persisted)
    typing_cache: Optional[dict] = field(default=None)
    _typing_analysis_task: Optional[asyncio.Task] = field(default=None, repr=False)


@dataclass
class OutboundMessage:
    """Message to send to clients."""
    type: str
    payload: dict
    target_user_id: Optional[UUID] = None

    def to_dict(self) -> dict:
        return {"type": self.type, "payload": self.payload}


class ConnectionManager:
    """
    ARCHITECTURE: In-memory connection registry with room-based routing.
    WHY: Single-server MVP; swap for Redis pub/sub for horizontal scale.
    TRADEOFF: `_rooms` is the single source of truth, and per-user lookups
        are linear scans over one room rather than an index.

    WHY no `(user_id, room_id) -> Connection` index: there used to be one
    alongside `_rooms`, but it held only ONE connection per user per room
    while `_rooms` held them all. A user's second tab overwrote the first
    tab's entry, and closing *either* tab deleted the single shared key —
    so the surviving tab stayed in `_rooms` and kept receiving broadcasts
    while every directed send to it silently returned False. Rooms hold a
    handful of participants, so the index bought no measurable lookup win
    in exchange for that whole class of desync.
    """

    def __init__(self):
        self._rooms: dict[UUID, list[Connection]] = {}

    def _remove_connection(self, conn: Connection) -> None:
        """
        Drop a single connection from the registry.

        WHY identity (`is not`) and not equality: Connection is a dataclass,
        so `==` compares field-by-field and two live connections could
        compare equal — removing both when only one closed.
        """
        room_conns = self._rooms.get(conn.room_id)
        if room_conns is None:
            return

        remaining = [c for c in room_conns if c is not conn]
        if remaining:
            self._rooms[conn.room_id] = remaining
        else:
            del self._rooms[conn.room_id]

    async def connect(
        self,
        websocket: WebSocket,
        user_id: UUID,
        room_id: UUID,
        thread_id: Optional[UUID] = None,
    ) -> Connection:
        """Register an already-accepted WebSocket connection."""
        conn = Connection(
            websocket=websocket,
            user_id=user_id,
            room_id=room_id,
            thread_id=thread_id,
        )

        room_conns = self._rooms.setdefault(room_id, [])
        # Opening a second tab is not a join event for anyone else, so only
        # a user's FIRST connection to the room announces presence.
        is_first_connection = not any(c.user_id == user_id for c in room_conns)
        room_conns.append(conn)

        logger.info(
            f"Connected: user={user_id}, room={room_id} "
            f"(connections for this user: {len(self.get_user_connections(user_id, room_id))})"
        )

        if is_first_connection:
            await self.broadcast(room_id, OutboundMessage(
                type="user_joined",
                payload={"user_id": str(user_id)},
            ), exclude_user=user_id)

        return conn

    async def disconnect(self, conn: Connection) -> None:
        """Remove connection from registry."""
        room_id = conn.room_id
        user_id = conn.user_id

        self._remove_connection(conn)

        # Mirror of connect(): a user is only "gone" once their LAST
        # connection closes. Announcing on every tab close evicted users
        # from the participants list while they were still present.
        still_present = bool(self.get_user_connections(user_id, room_id))

        logger.info(
            f"Disconnected: user={user_id}, room={room_id}"
            + (" (other connections remain)" if still_present else "")
        )

        if not still_present:
            await self.broadcast(room_id, OutboundMessage(
                type="user_left",
                payload={"user_id": str(user_id)},
            ))

    async def broadcast(
        self,
        room_id: UUID,
        message: OutboundMessage,
        exclude_user: Optional[UUID] = None,
    ) -> None:
        """Send message to all connections in a room."""
        if room_id not in self._rooms:
            return

        payload = json.dumps({
            "type": message.type,
            "payload": message.payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Snapshot: sends await, so another task may mutate the room list.
        dead: list[Connection] = []
        for conn in list(self._rooms[room_id]):
            if exclude_user and conn.user_id == exclude_user:
                continue

            try:
                await conn.websocket.send_text(payload)
            except Exception as e:
                # !r because ConnectionClosed and friends stringify to "",
                # which logged a bare "Failed to send to <uuid>: " with no
                # indication of what actually went wrong.
                logger.warning(f"Failed to send to {conn.user_id}: {e!r}")
                dead.append(conn)

        # Evict failed sockets instead of retrying them on every subsequent
        # broadcast. The endpoint's own finally-block still calls
        # disconnect() for the user_left announcement — dropping the entry
        # here (rather than calling disconnect()) keeps broadcast
        # non-reentrant.
        for conn in dead:
            self._remove_connection(conn)

    async def send_to_user(
        self,
        user_id: UUID,
        room_id: UUID,
        message: OutboundMessage,
    ) -> bool:
        """
        Send message to a user in a room — to EVERY connection they hold,
        so a directed message reaches all of their open tabs.

        Returns True if at least one connection accepted the message.
        """
        conns = self.get_user_connections(user_id, room_id)
        if not conns:
            return False

        payload = json.dumps({
            "type": message.type,
            "payload": message.payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        delivered = False
        dead: list[Connection] = []
        for conn in conns:
            try:
                await conn.websocket.send_text(payload)
                delivered = True
            except Exception as e:
                logger.warning(f"Failed to send to {user_id}: {e!r}")
                dead.append(conn)

        for conn in dead:
            self._remove_connection(conn)

        return delivered

    def get_room_users(self, room_id: UUID) -> list[UUID]:
        """
        Get list of connected user IDs in room, deduplicated — a user with
        two tabs open is one participant, not two.
        """
        users: list[UUID] = []
        for conn in self._rooms.get(room_id, ()):
            if conn.user_id not in users:
                users.append(conn.user_id)
        return users

    def get_user_connections(self, user_id: UUID, room_id: UUID) -> list[Connection]:
        """
        Get all active connections for a user in a specific room.
        Used to determine if user is currently viewing the room (foreground suppression).
        """
        return [c for c in self._rooms.get(room_id, ()) if c.user_id == user_id]

    def is_user_connected(self, user_id: UUID, room_id: UUID) -> bool:
        """Check if user has any active WebSocket connections to room."""
        return bool(self.get_user_connections(user_id, room_id))


@dataclass
class InboundMessage:
    """Message received from client."""
    type: str
    payload: dict

    @classmethod
    def from_json(cls, data: str) -> "InboundMessage":
        parsed = json.loads(data)
        return cls(
            type=parsed.get("type", "unknown"),
            payload=parsed.get("payload", {}),
        )


class MessageTypes:
    # Inbound
    SEND_MESSAGE = "send_message"
    TYPING_START = "typing_start"
    TYPING_STOP = "typing_stop"
    SWITCH_THREAD = "switch_thread"
    FORK_THREAD = "fork_thread"
    ADD_MEMORY = "add_memory"
    EDIT_MEMORY = "edit_memory"
    INVALIDATE_MEMORY = "invalidate_memory"
    PING = "ping"
    TYPING_CONTENT = "typing_content"
    # Message revision (inbound). MESSAGE_EDITED/MESSAGE_DELETED have existed on
    # the outbound side since the beginning with nothing able to produce them.
    EDIT_MESSAGE = "edit_message"
    DELETE_MESSAGE = "delete_message"
    ADD_REACTION = "add_reaction"
    REMOVE_REACTION = "remove_reaction"
    # Presence & receipts (inbound)
    PRESENCE_HEARTBEAT = "presence_heartbeat"
    PRESENCE_UPDATE = "presence_update"
    MESSAGE_DELIVERED = "message_delivered"
    MESSAGE_READ = "message_read"
    # LLM control (inbound)
    SUMMON_LLM = "summon_llm"
    CANCEL_LLM = "cancel_llm"
    # Research mode (inbound): a human asks for the long tool loop
    # (llm/research.py); the brief lands as an llm_primary message.
    DEEP_DIVE = "deep_dive"
    # Cross-session memory (inbound)
    SEARCH_GLOBAL_MEMORIES = "search_global_memories"
    PROMOTE_MEMORY = "promote_memory"
    REFERENCE_MEMORY = "reference_memory"
    # Thinking protocols (inbound)
    INVOKE_PROTOCOL = "invoke_protocol"
    ADVANCE_PROTOCOL = "advance_protocol"
    ABORT_PROTOCOL = "abort_protocol"
    # Stakes / commitments (inbound)
    CREATE_COMMITMENT = "create_commitment"
    RECORD_CONFIDENCE = "record_confidence"
    RESOLVE_COMMITMENT = "resolve_commitment"

    # Outbound
    MESSAGE_CREATED = "message_created"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_DELETED = "message_deleted"
    # Carries the full reaction set for one message, not a delta — a client that
    # missed an event still converges on the right state.
    REACTION_UPDATED = "reaction_updated"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    USER_TYPING = "user_typing"
    THREAD_CREATED = "thread_created"
    MEMORY_UPDATED = "memory_updated"
    LLM_THINKING = "llm_thinking"
    LLM_STREAMING = "llm_streaming"
    # The participant reaching for a tool mid-turn. Transient by design: the
    # client shows it while the check runs and drops it on llm_done/error/
    # cancelled — the durable record is the message's own tool trace.
    LLM_TOOL_ACTIVITY = "llm_tool_activity"
    LLM_DONE = "llm_done"
    LLM_ERROR = "llm_error"
    LLM_CANCELLED = "llm_cancelled"
    # Research-mode brackets (outbound): the dive itself speaks the ordinary
    # llm_* vocabulary between these two, so clients only need the brackets
    # to keep the Research button disarmed while a dive is in flight.
    DEEP_DIVE_STARTED = "deep_dive_started"
    DEEP_DIVE_DONE = "deep_dive_done"
    ERROR = "error"
    PONG = "pong"
    # Presence & receipts (outbound)
    PRESENCE_BROADCAST = "presence_update"
    DELIVERY_RECEIPT = "delivery_receipt"
    READ_RECEIPT = "read_receipt"
    # Cross-session memory (outbound)
    GLOBAL_MEMORY_RESULTS = "global_memory_results"
    MEMORY_PROMOTED = "memory_promoted"
    MEMORY_REFERENCED = "memory_referenced"
    CROSS_ROOM_CONTEXT = "cross_room_context"
    # Thinking protocols (outbound)
    PROTOCOL_STARTED = "protocol_started"
    PROTOCOL_PHASE_ADVANCED = "protocol_phase_advanced"
    PROTOCOL_CONCLUDED = "protocol_concluded"
    PROTOCOL_ABORTED = "protocol_aborted"
    PROTOCOL_STATE = "protocol_state"
    # Async dialogue (outbound)
    ANNOTATION_CREATED = "annotation_created"
    # Stakes / commitments (outbound)
    COMMITMENT_CREATED = "commitment_created"
    # A server-side enrichment landed on an existing message's metadata
    # (e.g. detected commitment proposals) — clients merge, not replace.
    MESSAGE_METADATA = "message_metadata"
    COMMITMENT_CONFIDENCE_UPDATED = "commitment_confidence_updated"
    COMMITMENT_RESOLVED = "commitment_resolved"
    COMMITMENT_SURFACED = "commitment_surfaced"
    # Multi-model personas (outbound)
    PERSONA_RESPONSE = "persona_response"
    # Trading integration (inbound/outbound)
    TRADING_UPDATE = "trading_update"
