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
    """

    def __init__(self):
        self._rooms: dict[UUID, list[Connection]] = {}
        self._users: dict[tuple[UUID, UUID], Connection] = {}

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

        if room_id not in self._rooms:
            self._rooms[room_id] = []
        self._rooms[room_id].append(conn)

        self._users[(user_id, room_id)] = conn

        logger.info(f"Connected: user={user_id}, room={room_id}")

        await self.broadcast(room_id, OutboundMessage(
            type="user_joined",
            payload={"user_id": str(user_id)},
        ), exclude_user=user_id)

        return conn

    async def disconnect(self, conn: Connection) -> None:
        """Remove connection from registry."""
        room_id = conn.room_id
        user_id = conn.user_id

        if room_id in self._rooms:
            self._rooms[room_id] = [c for c in self._rooms[room_id] if c != conn]
            if not self._rooms[room_id]:
                del self._rooms[room_id]

        key = (user_id, room_id)
        if key in self._users:
            del self._users[key]

        logger.info(f"Disconnected: user={user_id}, room={room_id}")

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

        for conn in self._rooms[room_id]:
            if exclude_user and conn.user_id == exclude_user:
                continue

            try:
                await conn.websocket.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to {conn.user_id}: {e}")

    async def send_to_user(
        self,
        user_id: UUID,
        room_id: UUID,
        message: OutboundMessage,
    ) -> bool:
        """Send message to specific user in room."""
        key = (user_id, room_id)
        conn = self._users.get(key)

        if not conn:
            return False

        payload = json.dumps({
            "type": message.type,
            "payload": message.payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        try:
            await conn.websocket.send_text(payload)
            return True
        except Exception as e:
            logger.warning(f"Failed to send to {user_id}: {e}")
            return False

    def get_room_users(self, room_id: UUID) -> list[UUID]:
        """Get list of connected user IDs in room."""
        if room_id not in self._rooms:
            return []
        return [conn.user_id for conn in self._rooms[room_id]]

    def get_user_connections(self, user_id: UUID, room_id: UUID) -> list[Connection]:
        """
        Get all active connections for a user in a specific room.
        Used to determine if user is currently viewing the room (foreground suppression).
        """
        if room_id not in self._rooms:
            return []
        return [conn for conn in self._rooms[room_id] if conn.user_id == user_id]

    def is_user_connected(self, user_id: UUID, room_id: UUID) -> bool:
        """Check if user has any active WebSocket connections to room."""
        return (user_id, room_id) in self._users


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
    # Presence & receipts (inbound)
    PRESENCE_HEARTBEAT = "presence_heartbeat"
    PRESENCE_UPDATE = "presence_update"
    MESSAGE_DELIVERED = "message_delivered"
    MESSAGE_READ = "message_read"
    # LLM control (inbound)
    SUMMON_LLM = "summon_llm"
    CANCEL_LLM = "cancel_llm"
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
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    USER_TYPING = "user_typing"
    THREAD_CREATED = "thread_created"
    MEMORY_UPDATED = "memory_updated"
    LLM_THINKING = "llm_thinking"
    LLM_STREAMING = "llm_streaming"
    LLM_DONE = "llm_done"
    LLM_ERROR = "llm_error"
    LLM_CANCELLED = "llm_cancelled"
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
    # Async dialogue (outbound)
    ANNOTATION_CREATED = "annotation_created"
    # Stakes / commitments (outbound)
    COMMITMENT_CREATED = "commitment_created"
    COMMITMENT_RESOLVED = "commitment_resolved"
    COMMITMENT_SURFACED = "commitment_surfaced"
    # Multi-model personas (outbound)
    PERSONA_RESPONSE = "persona_response"
    # Trading integration (inbound/outbound)
    TRADING_UPDATE = "trading_update"
