# transport/handlers.py — WebSocket message handlers

import asyncio
from asyncio import Task, CancelledError
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
import logging
import sys
import pathlib

_package_root = str(pathlib.Path(__file__).resolve().parent.parent)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

from models import (
    Room, User, Thread, Message, Memory, Event, EventType,
    SpeakerType, MessageType, MessageCreatedPayload
)
from memory.manager import MemoryManager
from llm.orchestrator import LLMOrchestrator
from .websocket import (
    ConnectionManager, Connection, InboundMessage, OutboundMessage, MessageTypes
)

logger = logging.getLogger(__name__)


class MessageHandler:
    """
    ARCHITECTURE: Dispatches inbound WebSocket messages to appropriate handlers.
    WHY: Clean separation between transport and business logic.
    """

    # Class-level tracking for active LLM streams across handler instances
    # Key: thread_id, Value: asyncio.Task
    _active_streams: dict[UUID, Task] = {}

    def __init__(
        self,
        db,
        connection_manager: ConnectionManager,
        memory_manager: MemoryManager,
        llm_orchestrator: LLMOrchestrator,
    ):
        self.db = db
        self.connections = connection_manager
        self.memory = memory_manager
        self.llm = llm_orchestrator

    async def handle(self, conn: Connection, message: InboundMessage) -> None:
        """Route message to appropriate handler."""

        handlers = {
            MessageTypes.SEND_MESSAGE: self._handle_send_message,
            MessageTypes.TYPING_START: self._handle_typing,
            MessageTypes.TYPING_STOP: self._handle_typing,
            MessageTypes.FORK_THREAD: self._handle_fork_thread,
            MessageTypes.SWITCH_THREAD: self._handle_switch_thread,
            MessageTypes.ADD_MEMORY: self._handle_add_memory,
            MessageTypes.EDIT_MEMORY: self._handle_edit_memory,
            MessageTypes.INVALIDATE_MEMORY: self._handle_invalidate_memory,
            MessageTypes.PING: self._handle_ping,
            MessageTypes.PRESENCE_HEARTBEAT: self._handle_presence_heartbeat,
            MessageTypes.PRESENCE_UPDATE: self._handle_presence_update,
            MessageTypes.MESSAGE_DELIVERED: self._handle_message_delivered,
            MessageTypes.MESSAGE_READ: self._handle_message_read,
            MessageTypes.SUMMON_LLM: self._handle_summon_llm,
            MessageTypes.CANCEL_LLM: self._handle_cancel_llm,
        }

        handler = handlers.get(message.type)
        if handler:
            try:
                await handler(conn, message.payload)
            except Exception as e:
                logger.exception(f"Handler error for {message.type}")
                await self._send_error(conn, str(e))
        else:
            logger.warning(f"Unknown message type: {message.type}")
            await self._send_error(conn, f"Unknown message type: {message.type}")

    async def _handle_send_message(self, conn: Connection, payload: dict) -> None:
        """Handle new message from user."""

        content = payload.get("content", "").strip()
        if not content:
            return

        message_type = MessageType(payload.get("type", "text"))
        references_message_id = payload.get("references_message_id")

        thread_id = conn.thread_id
        if not thread_id:
            row = await self.db.fetchrow(
                """SELECT id FROM threads
                   WHERE room_id = $1 AND parent_thread_id IS NULL
                   ORDER BY created_at LIMIT 1""",
                conn.room_id
            )
            thread_id = row['id'] if row else None

        if not thread_id:
            await self._send_error(conn, "No active thread")
            return

        now = datetime.utcnow()
        message_id = uuid4()
        refs_msg_id = UUID(references_message_id) if references_message_id else None

        # Atomic INSERT with inline sequence calculation to prevent TOCTOU race
        row = await self.db.fetchrow(
            """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content, references_message_id)
               VALUES (
                   $1, $2,
                   (SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = $2),
                   $3, $4, $5, $6, $7, $8
               )
               RETURNING sequence""",
            message_id, thread_id, now,
            SpeakerType.HUMAN.value, conn.user_id, message_type.value,
            content, refs_msg_id
        )
        sequence = row['sequence']

        message = Message(
            id=message_id,
            thread_id=thread_id,
            sequence=sequence,
            created_at=now,
            speaker_type=SpeakerType.HUMAN,
            user_id=conn.user_id,
            message_type=message_type,
            content=content,
            references_message_id=refs_msg_id,
        )

        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=EventType.MESSAGE_CREATED,
            room_id=conn.room_id,
            thread_id=thread_id,
            user_id=conn.user_id,
            payload=MessageCreatedPayload(
                message_id=message_id,
                sequence=sequence,
                speaker_type=SpeakerType.HUMAN,
                user_id=conn.user_id,
                message_type=message_type,
                content=content,
                references_message_id=message.references_message_id,
            ).model_dump()
        )

        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            event.id, event.timestamp, event.event_type.value,
            event.room_id, event.thread_id, event.user_id, event.payload
        )

        user_row = await self.db.fetchrow(
            "SELECT display_name FROM users WHERE id = $1", conn.user_id
        )

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.MESSAGE_CREATED,
            payload={
                "id": str(message.id),
                "thread_id": str(message.thread_id),
                "sequence": message.sequence,
                "created_at": message.created_at.isoformat(),
                "speaker_type": message.speaker_type.value,
                "user_id": str(message.user_id),
                "user_name": user_row['display_name'] if user_row else "Unknown",
                "message_type": message.message_type.value,
                "content": message.content,
            }
        ))

        # Trigger push notifications for offline/away users
        await self._trigger_push_notifications(
            room_id=conn.room_id,
            thread_id=thread_id,
            message=message,
            sender_name=user_row['display_name'] if user_row else "Unknown",
            sender_id=conn.user_id,
        )

        mentioned = "@llm" in content.lower()

        try:
            novelty = await self.memory.compute_message_novelty(conn.room_id, content)
        except Exception:
            novelty = 0.5

        await self._trigger_llm(conn.room_id, thread_id, mentioned, novelty)

    async def _trigger_llm(
        self,
        room_id: UUID,
        thread_id: UUID,
        mentioned: bool,
        semantic_novelty: float,
    ) -> None:
        """Invoke LLM orchestrator and broadcast response."""

        room_row = await self.db.fetchrow("SELECT * FROM rooms WHERE id = $1", room_id)
        room = Room(**dict(room_row))

        thread_row = await self.db.fetchrow("SELECT * FROM threads WHERE id = $1", thread_id)
        thread = Thread(**dict(thread_row))

        user_rows = await self.db.fetch(
            """SELECT u.* FROM users u
               JOIN room_memberships rm ON u.id = rm.user_id
               WHERE rm.room_id = $1""",
            room_id
        )
        users = [User(**dict(row)) for row in user_rows]

        from operations import get_thread_messages
        messages = await get_thread_messages(self.db, thread_id, include_ancestry=True)

        memories = await self.memory.get_context_for_prompt(room_id)

        # Use streaming for explicit @Claude mentions
        if mentioned:
            message_id = uuid4()
            async for event_type, data in self.llm.stream_response(
                room=room,
                thread=thread,
                users=users,
                messages=messages,
                memories=memories,
                use_provoker=False,
            ):
                if event_type == "thinking":
                    await self.connections.broadcast(room_id, OutboundMessage(
                        type=MessageTypes.LLM_THINKING,
                        payload={"thread_id": str(thread_id)},
                    ))
                elif event_type == "streaming":
                    await self.connections.broadcast(room_id, OutboundMessage(
                        type=MessageTypes.LLM_STREAMING,
                        payload={
                            "thread_id": str(thread_id),
                            "message_id": str(message_id),
                            "token": data["token"],
                            "index": data["index"],
                            "speaker_type": SpeakerType.LLM_PRIMARY.value,
                        },
                    ))
                elif event_type == "done":
                    await self.connections.broadcast(room_id, OutboundMessage(
                        type=MessageTypes.LLM_DONE,
                        payload={
                            "thread_id": str(thread_id),
                            "message_id": data["message_id"],
                            "content": data["content"],
                            "model_used": data["model_used"],
                            "truncated": data["truncated"],
                        },
                    ))
                    # Trigger push for LLM streaming response
                    llm_message = Message(
                        id=UUID(data["message_id"]) if isinstance(data["message_id"], str) else data["message_id"],
                        thread_id=thread_id,
                        sequence=0,  # Not needed for push
                        created_at=datetime.utcnow(),
                        speaker_type=SpeakerType.LLM_PRIMARY,
                        user_id=None,
                        message_type=MessageType.TEXT,
                        content=data["content"],
                    )
                    await self._trigger_push_notifications(
                        room_id=room_id,
                        thread_id=thread_id,
                        message=llm_message,
                        sender_name="Claude",
                        sender_id=UUID('00000000-0000-0000-0000-000000000000'),  # Sentinel for LLM
                    )
                elif event_type == "error":
                    await self.connections.broadcast(room_id, OutboundMessage(
                        type=MessageTypes.LLM_ERROR,
                        payload={
                            "thread_id": str(thread_id),
                            "error": data["error"],
                            "partial_content": data["partial_content"],
                        },
                    ))
            return

        # Non-streaming path for heuristic interjections
        await self.connections.broadcast(room_id, OutboundMessage(
            type=MessageTypes.LLM_THINKING,
            payload={"thread_id": str(thread_id)},
        ))

        result = await self.llm.on_message(
            room=room,
            thread=thread,
            users=users,
            messages=messages,
            memories=memories,
            mentioned=mentioned,
            semantic_novelty=semantic_novelty,
        )

        if result.triggered and result.response:
            await self.connections.broadcast(room_id, OutboundMessage(
                type=MessageTypes.MESSAGE_CREATED,
                payload={
                    "id": str(result.response.id),
                    "thread_id": str(result.response.thread_id),
                    "sequence": result.response.sequence,
                    "created_at": result.response.created_at.isoformat(),
                    "speaker_type": result.response.speaker_type.value,
                    "user_id": None,
                    "user_name": "Claude" if "primary" in result.response.speaker_type.value else "Provoker",
                    "message_type": result.response.message_type.value,
                    "content": result.response.content,
                    "model_used": result.response.model_used,
                },
            ))
            # Trigger push for LLM heuristic interjection
            sender_name = "Claude" if result.response.speaker_type == SpeakerType.LLM_PRIMARY else "Provoker"
            await self._trigger_push_notifications(
                room_id=room_id,
                thread_id=thread_id,
                message=result.response,
                sender_name=sender_name,
                sender_id=UUID('00000000-0000-0000-0000-000000000000'),  # Sentinel for LLM
            )

    async def _handle_typing(self, conn: Connection, payload: dict) -> None:
        """Broadcast typing indicator."""
        is_typing = payload.get("typing", False)

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.USER_TYPING,
            payload={
                "user_id": str(conn.user_id),
                "typing": is_typing,
            },
        ), exclude_user=conn.user_id)

    async def _handle_fork_thread(self, conn: Connection, payload: dict) -> None:
        """Create a new thread forking from current."""

        source_thread_id = UUID(payload["source_thread_id"])
        fork_after_message_id = UUID(payload["fork_after_message_id"])
        title = payload.get("title")

        from operations import fork_thread
        new_thread = await fork_thread(
            self.db,
            room_id=conn.room_id,
            source_thread_id=source_thread_id,
            fork_after_message_id=fork_after_message_id,
            forking_user_id=conn.user_id,
            title=title,
        )

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.THREAD_CREATED,
            payload={
                "id": str(new_thread.id),
                "parent_thread_id": str(new_thread.parent_thread_id),
                "fork_point_message_id": str(new_thread.fork_point_message_id),
                "title": new_thread.title,
            },
        ))

    async def _handle_switch_thread(self, conn: Connection, payload: dict) -> None:
        """Switch user's active thread."""
        thread_id = UUID(payload["thread_id"])
        conn.thread_id = thread_id
        logger.info(f"User {conn.user_id} switched to thread {thread_id}")

    async def _handle_add_memory(self, conn: Connection, payload: dict) -> None:
        """Add a new memory."""
        memory = await self.memory.add_memory(
            room_id=conn.room_id,
            key=payload["key"],
            content=payload["content"],
            created_by_user_id=conn.user_id,
        )

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.MEMORY_UPDATED,
            payload={
                "action": "added",
                "memory_id": str(memory.id),
                "key": memory.key,
                "content": memory.content,
            },
        ))

    async def _handle_edit_memory(self, conn: Connection, payload: dict) -> None:
        """Edit existing memory."""
        memory = await self.memory.edit_memory(
            memory_id=UUID(payload["memory_id"]),
            new_content=payload["content"],
            edited_by_user_id=conn.user_id,
        )

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.MEMORY_UPDATED,
            payload={
                "action": "edited",
                "memory_id": str(memory.id),
                "key": memory.key,
                "content": memory.content,
                "version": memory.version,
            },
        ))

    async def _handle_invalidate_memory(self, conn: Connection, payload: dict) -> None:
        """Invalidate a memory."""
        memory = await self.memory.invalidate_memory(
            memory_id=UUID(payload["memory_id"]),
            invalidated_by_user_id=conn.user_id,
            reason=payload.get("reason"),
        )

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.MEMORY_UPDATED,
            payload={
                "action": "invalidated",
                "memory_id": str(memory.id),
            },
        ))

    async def _handle_ping(self, conn: Connection, payload: dict) -> None:
        """Respond to ping."""
        await self.connections.send_to_user(conn.user_id, conn.room_id, OutboundMessage(
            type=MessageTypes.PONG,
            payload={"timestamp": datetime.utcnow().isoformat()},
        ))

    async def _handle_presence_heartbeat(self, conn: Connection, payload: dict) -> None:
        """
        Handle presence heartbeat from client.
        Updates user status to 'online' and broadcasts to room.
        """
        now = datetime.utcnow()

        # Upsert presence record
        await self.db.execute(
            """INSERT INTO user_presence (user_id, room_id, status, last_heartbeat)
               VALUES ($1, $2, 'online', $3)
               ON CONFLICT (user_id, room_id)
               DO UPDATE SET status = 'online', last_heartbeat = $3""",
            conn.user_id, conn.room_id, now
        )

        # Broadcast presence update to room (exclude sender)
        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.PRESENCE_BROADCAST,
            payload={
                "user_id": str(conn.user_id),
                "status": "online",
                "timestamp": now.isoformat(),
            },
        ), exclude_user=conn.user_id)

    async def _handle_presence_update(self, conn: Connection, payload: dict) -> None:
        """
        Handle explicit presence status change from client.
        Status can be 'online', 'away', or 'offline'.
        """
        status = payload.get("status", "online")
        if status not in ("online", "away", "offline"):
            await self._send_error(conn, f"Invalid presence status: {status}")
            return

        now = datetime.utcnow()

        # Update presence record
        await self.db.execute(
            """INSERT INTO user_presence (user_id, room_id, status, last_heartbeat)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (user_id, room_id)
               DO UPDATE SET status = $3, last_heartbeat = $4""",
            conn.user_id, conn.room_id, status, now
        )

        # Broadcast presence update to room (exclude sender)
        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.PRESENCE_BROADCAST,
            payload={
                "user_id": str(conn.user_id),
                "status": status,
                "timestamp": now.isoformat(),
            },
        ), exclude_user=conn.user_id)

    async def _handle_message_delivered(self, conn: Connection, payload: dict) -> None:
        """
        Handle delivery receipt from client.
        Records that a message was delivered to the user.
        """
        message_id = payload.get("message_id")
        if not message_id:
            await self._send_error(conn, "message_id required")
            return

        from uuid import UUID
        message_uuid = UUID(message_id)
        now = datetime.utcnow()

        # Insert delivery receipt (ignore if already exists)
        await self.db.execute(
            """INSERT INTO message_receipts (message_id, user_id, receipt_type, timestamp)
               VALUES ($1, $2, 'delivered', $3)
               ON CONFLICT (message_id, user_id, receipt_type) DO NOTHING""",
            message_uuid, conn.user_id, now
        )

        # Get message sender to notify them
        sender_row = await self.db.fetchrow(
            "SELECT user_id FROM messages WHERE id = $1",
            message_uuid
        )

        if sender_row and sender_row['user_id']:
            # Send delivery receipt to sender only
            await self.connections.send_to_user(
                sender_row['user_id'],
                conn.room_id,
                OutboundMessage(
                    type=MessageTypes.DELIVERY_RECEIPT,
                    payload={
                        "message_id": str(message_uuid),
                        "status": "delivered",
                        "recipient_id": str(conn.user_id),
                    },
                )
            )

    async def _handle_message_read(self, conn: Connection, payload: dict) -> None:
        """
        Handle read receipt from client.
        Records that a message was read by the user.
        """
        message_id = payload.get("message_id")
        if not message_id:
            await self._send_error(conn, "message_id required")
            return

        from uuid import UUID
        message_uuid = UUID(message_id)
        now = datetime.utcnow()

        # Insert read receipt (ignore if already exists)
        await self.db.execute(
            """INSERT INTO message_receipts (message_id, user_id, receipt_type, timestamp)
               VALUES ($1, $2, 'read', $3)
               ON CONFLICT (message_id, user_id, receipt_type) DO NOTHING""",
            message_uuid, conn.user_id, now
        )

        # Get message sender to notify them
        sender_row = await self.db.fetchrow(
            "SELECT user_id FROM messages WHERE id = $1",
            message_uuid
        )

        if sender_row and sender_row['user_id']:
            # Send read receipt to sender only
            await self.connections.send_to_user(
                sender_row['user_id'],
                conn.room_id,
                OutboundMessage(
                    type=MessageTypes.READ_RECEIPT,
                    payload={
                        "message_id": str(message_uuid),
                        "reader_id": str(conn.user_id),
                    },
                )
            )

    async def _handle_summon_llm(self, conn: Connection, payload: dict) -> None:
        """
        Handle explicit @Claude summon from client.
        Streams LLM response token-by-token via WebSocket.

        ARCHITECTURE: Wraps streaming in asyncio.Task for cancellation support.
        WHY: Enables stop button to interrupt in-progress responses.
        TRADEOFF: Slightly more complex, but essential for user control.
        """
        thread_id = payload.get("thread_id")
        if thread_id:
            thread_id = UUID(thread_id)
        else:
            thread_id = conn.thread_id

        if not thread_id:
            await self._send_error(conn, "No active thread for LLM summon")
            return

        # Cancel any existing stream for this thread
        if thread_id in MessageHandler._active_streams:
            existing_task = MessageHandler._active_streams[thread_id]
            if not existing_task.done():
                existing_task.cancel()
                logger.info(f"Cancelled existing stream for thread {thread_id}")

        use_provoker = payload.get("use_provoker", False)

        # Load context
        room_row = await self.db.fetchrow("SELECT * FROM rooms WHERE id = $1", conn.room_id)
        room = Room(**dict(room_row))

        thread_row = await self.db.fetchrow("SELECT * FROM threads WHERE id = $1", thread_id)
        thread = Thread(**dict(thread_row))

        user_rows = await self.db.fetch(
            """SELECT u.* FROM users u
               JOIN room_memberships rm ON u.id = rm.user_id
               WHERE rm.room_id = $1""",
            conn.room_id
        )
        users = [User(**dict(row)) for row in user_rows]

        from operations import get_thread_messages
        messages = await get_thread_messages(self.db, thread_id, include_ancestry=True)

        memories = await self.memory.get_context_for_prompt(conn.room_id)

        # Create streaming task for cancellation support
        task = asyncio.create_task(
            self._stream_llm_response(conn, thread_id, room, thread, users, messages, memories, use_provoker)
        )
        MessageHandler._active_streams[thread_id] = task

        try:
            await task
        except CancelledError:
            logger.info(f"Stream cancelled for thread {thread_id}")
            # Notify client that cancellation completed
            await self.connections.broadcast(conn.room_id, OutboundMessage(
                type=MessageTypes.LLM_CANCELLED,
                payload={"thread_id": str(thread_id)},
            ))
        finally:
            # Clean up task tracking
            MessageHandler._active_streams.pop(thread_id, None)

    async def _stream_llm_response(
        self,
        conn: Connection,
        thread_id: UUID,
        room: Room,
        thread: Thread,
        users: list,
        messages: list,
        memories: list,
        use_provoker: bool,
    ) -> None:
        """
        Execute LLM streaming in a separate coroutine for cancellation support.

        ARCHITECTURE: Extracted from _handle_summon_llm for task wrapping.
        WHY: asyncio.create_task requires a coroutine, not async for loop.
        """
        # Generate message_id upfront for streaming correlation
        message_id = uuid4()

        # Stream response and broadcast events
        async for event_type, data in self.llm.stream_response(
            room=room,
            thread=thread,
            users=users,
            messages=messages,
            memories=memories,
            use_provoker=use_provoker,
        ):
            if event_type == "thinking":
                await self.connections.broadcast(conn.room_id, OutboundMessage(
                    type=MessageTypes.LLM_THINKING,
                    payload={"thread_id": str(thread_id)},
                ))
            elif event_type == "streaming":
                await self.connections.broadcast(conn.room_id, OutboundMessage(
                    type=MessageTypes.LLM_STREAMING,
                    payload={
                        "thread_id": str(thread_id),
                        "message_id": str(message_id),
                        "token": data["token"],
                        "index": data["index"],
                        "speaker_type": SpeakerType.LLM_PROVOKER.value if use_provoker else SpeakerType.LLM_PRIMARY.value,
                    },
                ))
            elif event_type == "done":
                await self.connections.broadcast(conn.room_id, OutboundMessage(
                    type=MessageTypes.LLM_DONE,
                    payload={
                        "thread_id": str(thread_id),
                        "message_id": data["message_id"],
                        "content": data["content"],
                        "model_used": data["model_used"],
                        "truncated": data["truncated"],
                    },
                ))
            elif event_type == "error":
                await self.connections.broadcast(conn.room_id, OutboundMessage(
                    type=MessageTypes.LLM_ERROR,
                    payload={
                        "thread_id": str(thread_id),
                        "error": data["error"],
                        "partial_content": data["partial_content"],
                    },
                ))

    async def _handle_cancel_llm(self, conn: Connection, payload: dict) -> None:
        """
        Handle cancel request for in-progress LLM response.

        ARCHITECTURE: Uses class-level task tracking to cancel active streams.
        WHY: Enables stop button to interrupt in-progress responses.
        TRADEOFF: Class-level dict works for single-server; Redis needed for scale.
        """
        thread_id_str = payload.get("thread_id", str(conn.thread_id) if conn.thread_id else None)
        logger.info(f"LLM cancel requested by user {conn.user_id} for thread {thread_id_str}")

        if thread_id_str:
            thread_id = UUID(thread_id_str)
            task = MessageHandler._active_streams.get(thread_id)

            if task and not task.done():
                task.cancel()
                logger.info(f"Cancelled LLM stream for thread {thread_id}")

                # LLM_CANCELLED will be sent by the task's except CancelledError handler
                # Just acknowledge the cancel request here
                await self.connections.send_to_user(conn.user_id, conn.room_id, OutboundMessage(
                    type=MessageTypes.PONG,
                    payload={
                        "action": "cancel_llm_initiated",
                        "thread_id": thread_id_str,
                    },
                ))
            else:
                # No active stream to cancel
                await self.connections.send_to_user(conn.user_id, conn.room_id, OutboundMessage(
                    type=MessageTypes.PONG,
                    payload={
                        "action": "cancel_llm_no_stream",
                        "thread_id": thread_id_str,
                    },
                ))
        else:
            await self._send_error(conn, "No thread_id provided for cancel")

    async def _should_send_push(self, user_id: UUID, room_id: UUID) -> bool:
        """
        Check if user should receive push notification.
        Returns False if user is actively connected to the room (foreground suppression).
        """
        # Check if user has active WebSocket connection to this room
        if self.connections.is_user_connected(user_id, room_id):
            return False

        # Check user's presence status - only push if offline or away
        presence = await self.db.fetchrow(
            "SELECT status FROM user_presence WHERE user_id = $1 AND room_id = $2",
            user_id, room_id
        )
        # Send push if no presence record or status is not 'online'
        return presence is None or presence['status'] != 'online'

    async def _trigger_push_notifications(
        self,
        room_id: UUID,
        thread_id: UUID,
        message: Message,
        sender_name: str,
        sender_id: UUID,
    ) -> None:
        """Send push notifications to offline/away room members."""
        from api.notifications.service import push_service, calculate_badge_count

        # Get room members except sender, respecting mute settings
        members = await self.db.fetch(
            """
            SELECT rm.user_id FROM room_memberships rm
            LEFT JOIN room_notification_settings rns
                ON rm.user_id = rns.user_id AND rm.room_id = rns.room_id
            WHERE rm.room_id = $1
              AND rm.user_id != $2
              AND (rns.muted IS NULL OR rns.muted = false)
              AND (rns.muted_until IS NULL OR rns.muted_until < NOW())
            """,
            room_id, sender_id
        )

        if not members:
            return

        # Filter to users who should receive push (not actively connected)
        recipients = []
        for member in members:
            if await self._should_send_push(member['user_id'], room_id):
                recipients.append(str(member['user_id']))

        if not recipients:
            return

        # Calculate badge counts for each recipient
        badge_counts = {}
        for user_id in recipients:
            badge_counts[user_id] = await calculate_badge_count(self.db, user_id)

        # Determine if LLM message
        is_llm = message.speaker_type.value in ('LLM_PRIMARY', 'LLM_PROVOKER')
        display_name = "Claude" if is_llm else sender_name

        # Send push notifications (fire and forget, don't block message flow)
        try:
            await push_service.send_message_notification(
                db=self.db,
                recipient_user_ids=recipients,
                room_id=str(room_id),
                thread_id=str(thread_id),
                message_id=str(message.id),
                sender_name=display_name,
                content=message.content,
                is_llm=is_llm,
                badge_counts=badge_counts,
            )
        except Exception as e:
            logger.warning(f"Push notification failed: {e}")

    async def _send_error(self, conn: Connection, error: str) -> None:
        """Send error to client."""
        await self.connections.send_to_user(conn.user_id, conn.room_id, OutboundMessage(
            type=MessageTypes.ERROR,
            payload={"error": error},
        ))
