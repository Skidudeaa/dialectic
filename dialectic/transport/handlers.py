# transport/handlers.py — WebSocket message handlers

import asyncio
from asyncio import Task, CancelledError
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
import logging

from models import (
    Room, User, Thread, Message, Memory, Event, EventType,
    SpeakerType, MessageType, MessageCreatedPayload,
    ProtocolType,
)
from memory.manager import MemoryManager
from llm.orchestrator import LLMOrchestrator
from llm.annotator import AnnotatorEngine
from llm.protocol_manager import ProtocolManager
from llm.protocol_library import get_protocol_definition
from llm.multi_model import MultiModelCoordinator
from stakes.manager import CommitmentManager
from stakes.detector import CommitmentDetector
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
        self.protocols = ProtocolManager(db)

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
            MessageTypes.TYPING_CONTENT: self._handle_typing_content,
            MessageTypes.SUMMON_LLM: self._handle_summon_llm,
            MessageTypes.CANCEL_LLM: self._handle_cancel_llm,
            MessageTypes.INVOKE_PROTOCOL: self._handle_invoke_protocol,
            MessageTypes.ADVANCE_PROTOCOL: self._handle_advance_protocol,
            MessageTypes.ABORT_PROTOCOL: self._handle_abort_protocol,
            MessageTypes.CREATE_COMMITMENT: self._handle_create_commitment,
            MessageTypes.RECORD_CONFIDENCE: self._handle_record_confidence,
            MessageTypes.RESOLVE_COMMITMENT: self._handle_resolve_commitment,
        }

        handler = handlers.get(message.type)
        if handler:
            try:
                await handler(conn, message.payload)
            except Exception as e:
                logger.exception(f"Handler error for {message.type}: %s", e)
                await self._send_error(conn, "An internal error occurred. Please try again.")
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

        now = datetime.now(timezone.utc)
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

        # Annotator mode: when the other user is offline, generate a context annotation
        # for when they return. This runs IN ADDITION TO the normal primary LLM path so
        # the online user still gets a live response.
        # WHY: The original design had annotator replace the primary LLM (early return).
        # That meant the online user got no response — only a "for when X returns" note.
        # For a two-person trading room where one is often offline, that broke the live
        # session experience. Both responses serve different needs:
        #   - Annotator: context breadcrumb for Dan when he logs back in
        #   - Primary LLM: live answer to Amo's question right now
        # TRADEOFF: Two LLM calls per message when one user is offline (cheap annotator
        # is Haiku; primary is Sonnet but only fires when heuristic triggers).
        annotator = AnnotatorEngine(self.db, self.memory, self.llm)
        member_count = await self.db.fetchval(
            "SELECT COUNT(*) FROM room_memberships WHERE room_id = $1", conn.room_id
        )
        annotation = None
        if member_count >= 2 and await annotator.should_annotate(conn.room_id, conn.user_id):
            annotation = await annotator.annotate(
                room_id=conn.room_id,
                thread_id=thread_id,
                message=message,
            )
            if annotation:
                await self.connections.broadcast(conn.room_id, OutboundMessage(
                    type=MessageTypes.ANNOTATION_CREATED,
                    payload={
                        "id": str(annotation.id),
                        "thread_id": str(annotation.thread_id),
                        "sequence": annotation.sequence,
                        "speaker_type": SpeakerType.LLM_ANNOTATOR.value,
                        "content": annotation.content,
                        "created_at": annotation.created_at.isoformat(),
                    },
                ))

        # Normal path: push notifications + LLM interjection (always runs)
        await self._trigger_push_notifications(
            room_id=conn.room_id,
            thread_id=thread_id,
            message=message,
            sender_name=user_row['display_name'] if user_row else "Unknown",
            sender_id=conn.user_id,
        )

        mentioned = "@llm" in content.lower()

        # Check typing cache first (pre-computed while user was typing)
        cache = conn.typing_cache
        pre_memories = None
        if cache and self._is_typing_cache_fresh(cache, content, thread_id):
            novelty = cache["novelty"]
            pre_memories = cache.get("memories")
            logger.debug("Using typing cache (age=%.1fs)",
                         (datetime.now(timezone.utc) - cache["computed_at"]).total_seconds())
        else:
            try:
                novelty = await self.memory.compute_message_novelty(conn.room_id, content)
            except Exception:
                novelty = 0.5

        # Clear cache after consumption
        conn.typing_cache = None

        await self._trigger_llm(
            conn.room_id, thread_id, mentioned, novelty, content,
            pre_computed_memories=pre_memories,
        )

    async def _trigger_llm(
        self,
        room_id: UUID,
        thread_id: UUID,
        mentioned: bool,
        semantic_novelty: float,
        message_content: str = "",
        pre_computed_memories: list = None,
    ) -> None:
        """
        Invoke LLM orchestrator and broadcast response.

        ARCHITECTURE: Accepts pre_computed_memories from typing analysis cache.
        WHY: Avoids redundant embedding + vector search when cache is fresh.
        TRADEOFF: Slightly stale memories possible vs 50-85% latency reduction.
        """

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

        # Use pre-computed memories if available, else fetch
        if pre_computed_memories is not None:
            memories = pre_computed_memories
        else:
            try:
                memories = await self.memory.get_context_for_prompt(
                    room_id, query=message_content or None, max_memories=20
                )
            except Exception:
                logger.warning("Semantic memory search failed, falling back to recent memories")
                memories = await self.memory.get_context_for_prompt(room_id, max_memories=20)

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
                        created_at=datetime.now(timezone.utc),
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

        # Fetch active protocol for this thread (if any)
        protocol = await self.protocols.get_active(thread_id)

        result = await self.llm.on_message(
            room=room,
            thread=thread,
            users=users,
            messages=messages,
            memories=memories,
            mentioned=mentioned,
            semantic_novelty=semantic_novelty,
            protocol=protocol,
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
                    "user_name": "Facilitator" if protocol else (
                        "Claude" if "primary" in result.response.speaker_type.value else "Provoker"
                    ),
                    "message_type": result.response.message_type.value,
                    "content": result.response.content,
                    "model_used": result.response.model_used,
                },
            ))
            # Trigger push for LLM heuristic interjection
            sender_name = "Facilitator" if protocol else (
                "Claude" if result.response.speaker_type == SpeakerType.LLM_PRIMARY else "Provoker"
            )
            await self._trigger_push_notifications(
                room_id=room_id,
                thread_id=thread_id,
                message=result.response,
                sender_name=sender_name,
                sender_id=UUID('00000000-0000-0000-0000-000000000000'),  # Sentinel for LLM
            )

            # Handle auto-advance on phase completion signal
            if protocol and result.phase_complete_signal:
                await self._handle_phase_complete(
                    room_id, thread_id, protocol, result.phase_complete_signal,
                    room, thread, users, memories,
                )

        # After LLM response, check if any persona should speak (fire-and-forget)
        # ARCHITECTURE: Persona check runs after primary LLM, not blocking message flow.
        # WHY: Personas are opt-in enhancement; failures should never break normal messaging.
        asyncio.create_task(
            self._trigger_persona_response(
                room_id, thread_id, messages, memories, message_content,
            )
        )

        # After LLM response, check if any active commitments are relevant
        try:
            commitment_mgr = CommitmentManager(self.db)
            relevant = await commitment_mgr.check_relevant_commitments(
                room_id, message_content,
            )
            if relevant:
                await self.connections.broadcast(room_id, OutboundMessage(
                    type=MessageTypes.COMMITMENT_SURFACED,
                    payload={
                        "commitments": [
                            {
                                "id": str(c["id"]),
                                "claim": c["claim"],
                                "category": c.get("category", "prediction"),
                                "relevance_score": c.get("relevance_score", 0),
                                "deadline": c["deadline"].isoformat() if c.get("deadline") else None,
                            }
                            for c in relevant
                        ],
                    },
                ))
        except Exception as e:
            logger.debug("Commitment surfacing failed (non-critical): %s", e)

    async def _trigger_persona_response(
        self,
        room_id: UUID,
        thread_id: UUID,
        messages: list,
        memories: list,
        trigger_content: str,
    ) -> None:
        """
        Check if any multi-model persona should speak and generate their response.

        ARCHITECTURE: Fire-and-forget — runs as background task after primary LLM.
        WHY: Persona responses are an enhancement, never blocking the main message flow.
        TRADEOFF: Slight delay before persona response appears vs simpler sequential flow.
        """
        try:
            coordinator = MultiModelCoordinator(self.db)
            persona = await coordinator.get_next_persona(
                room_id, messages, trigger_content,
            )
            if not persona:
                return

            logger.info(
                "Persona %s triggered (strategy=%s) in room %s",
                persona.name, persona.trigger_strategy, room_id,
            )

            # Broadcast thinking indicator for the persona
            await self.connections.broadcast(room_id, OutboundMessage(
                type=MessageTypes.LLM_THINKING,
                payload={
                    "thread_id": str(thread_id),
                    "persona_name": persona.name,
                },
            ))

            content = await coordinator.generate_persona_response(
                persona, messages, memories,
            )
            if not content:
                return

            response_msg = await coordinator.persist_persona_response(
                persona, thread_id, room_id, content,
            )

            await self.connections.broadcast(room_id, OutboundMessage(
                type=MessageTypes.PERSONA_RESPONSE,
                payload={
                    "id": str(response_msg.id),
                    "thread_id": str(response_msg.thread_id),
                    "sequence": response_msg.sequence,
                    "created_at": response_msg.created_at.isoformat(),
                    "speaker_type": SpeakerType.LLM_PERSONA.value,
                    "user_id": None,
                    "user_name": persona.name,
                    "persona_id": str(persona.id),
                    "persona_name": persona.name,
                    "message_type": response_msg.message_type.value,
                    "content": response_msg.content,
                    "model_used": persona.model,
                },
            ))

        except Exception as e:
            logger.error("Persona response failed (non-critical): %s", e)

    async def _handle_typing(self, conn: Connection, payload: dict) -> None:
        """Broadcast typing indicator."""
        is_typing = payload.get("typing", False)

        # Clear typing cache when user stops typing (abandoned draft)
        if not is_typing:
            conn.typing_cache = None
            if conn._typing_analysis_task and not conn._typing_analysis_task.done():
                conn._typing_analysis_task.cancel()

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.USER_TYPING,
            payload={
                "user_id": str(conn.user_id),
                "typing": is_typing,
            },
        ), exclude_user=conn.user_id)

    async def _handle_typing_content(self, conn: Connection, payload: dict) -> None:
        """
        ARCHITECTURE: Pre-compute novelty and memory context from partial typing.
        WHY: Reduces perceived LLM latency by 50-85% on the pre-LLM pipeline.
        TRADEOFF: Extra embedding API calls while typing vs faster response on send.
        """
        content = payload.get("content", "").strip()
        if not content or len(content) < 10:  # Minimum content for meaningful analysis
            return

        # Check room has typing analysis enabled
        room_row = await self.db.fetchrow(
            "SELECT enable_typing_analysis FROM rooms WHERE id = $1", conn.room_id
        )
        if not room_row or not room_row["enable_typing_analysis"]:
            return

        # Cancel any pending analysis task (debounce)
        if conn._typing_analysis_task and not conn._typing_analysis_task.done():
            conn._typing_analysis_task.cancel()

        # Launch debounced analysis
        async def _analyze():
            try:
                await asyncio.sleep(0.5)  # 500ms debounce

                # Pre-compute novelty
                novelty = await self.memory.compute_message_novelty(conn.room_id, content)

                # Pre-fetch relevant memories
                try:
                    memories = await self.memory.get_context_for_prompt(
                        conn.room_id, query=content, max_memories=20
                    )
                except Exception:
                    memories = None

                # Store in connection cache
                conn.typing_cache = {
                    "content": content,
                    "novelty": novelty,
                    "memories": memories,
                    "computed_at": datetime.now(timezone.utc),
                    "thread_id": conn.thread_id,
                }

            except asyncio.CancelledError:
                pass  # Superseded by newer typing
            except Exception as e:
                logger.debug("Typing analysis error (non-critical): %s", e)

        conn._typing_analysis_task = asyncio.create_task(_analyze())

    def _is_typing_cache_fresh(self, cache: dict, sent_content: str, thread_id: UUID) -> bool:
        """
        Check if typing cache is fresh enough to use for the sent message.

        ARCHITECTURE: Heuristic match between partial and sent content.
        WHY: User may have edited heavily after last typing_content event.
        TRADEOFF: False positives (stale cache used) vs false negatives (re-compute).
        """
        # Thread must match
        if cache.get("thread_id") != thread_id:
            return False

        # Max 5 seconds old
        age = (datetime.now(timezone.utc) - cache["computed_at"]).total_seconds()
        if age > 5.0:
            return False

        # Content similarity: sent message should be related to partial
        partial = cache.get("content", "")
        if not partial:
            return False

        # Accept if sent starts with majority of partial content
        if sent_content.startswith(partial[:max(len(partial) // 2, 5)]):
            return True

        # Word overlap heuristic
        partial_words = set(partial.lower().split())
        sent_words = set(sent_content.lower().split())
        if not sent_words:
            return False
        overlap = len(partial_words & sent_words) / len(sent_words)
        return overlap >= 0.5

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
            payload={"timestamp": datetime.now(timezone.utc).isoformat()},
        ))

    async def _handle_presence_heartbeat(self, conn: Connection, payload: dict) -> None:
        """
        Handle presence heartbeat from client.
        Updates user status to 'online' and broadcasts to room.
        """
        now = datetime.now(timezone.utc)

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

        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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

        # Semantic search: use latest message content to find relevant memories
        last_content = messages[-1].content if messages else None
        try:
            memories = await self.memory.get_context_for_prompt(
                conn.room_id, query=last_content, max_memories=20
            )
        except Exception:
            logger.warning("Semantic memory search failed, falling back to recent memories")
            memories = await self.memory.get_context_for_prompt(conn.room_id, max_memories=20)

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
        annotation_summary: str = None,
    ) -> None:
        """
        Send push notifications to offline/away room members.

        ARCHITECTURE: Optional annotation_summary enriches push content in async mode.
        WHY: "Alice says X — Claude annotated with connections to Y" is more useful
             than "New message in room".
        TRADEOFF: Slightly longer push body vs much more informative notification.
        """
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
        is_llm = message.speaker_type.value in ('LLM_PRIMARY', 'LLM_PROVOKER', 'LLM_ANNOTATOR')
        display_name = "Claude" if is_llm else sender_name

        # Enrich content with annotation summary when available
        content = message.content
        if annotation_summary:
            content = f"{sender_name}: {message.content[:80]} — Claude annotated: {annotation_summary}"

        # Send push notifications (fire and forget, don't block message flow)
        try:
            await push_service.send_message_notification(
                db=self.db,
                recipient_user_ids=recipients,
                room_id=str(room_id),
                thread_id=str(thread_id),
                message_id=str(message.id),
                sender_name=display_name,
                content=content,
                is_llm=is_llm,
                badge_counts=badge_counts,
            )
        except Exception as e:
            logger.warning(f"Push notification failed: {e}")

    # ============================================================
    # THINKING PROTOCOL HANDLERS
    # ============================================================

    async def _handle_invoke_protocol(self, conn: Connection, payload: dict) -> None:
        """
        Start a thinking protocol on the current thread.

        ARCHITECTURE: Creates protocol state, broadcasts start, triggers framing response.
        WHY: Protocol invocation is a single user action that kicks off a multi-phase flow.
        TRADEOFF: Immediate LLM call on invoke vs waiting for user to send first message.
        """
        protocol_type = payload.get("protocol_type")
        if not protocol_type:
            await self._send_error(conn, "protocol_type required")
            return

        # Validate protocol type
        try:
            ProtocolType(protocol_type)
        except ValueError:
            valid = ", ".join(t.value for t in ProtocolType)
            await self._send_error(conn, f"Invalid protocol_type. Valid: {valid}")
            return

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

        config = payload.get("config", {})

        try:
            protocol = await self.protocols.invoke(
                thread_id=thread_id,
                room_id=conn.room_id,
                protocol_type=protocol_type,
                user_id=conn.user_id,
                config=config,
            )
        except ValueError as e:
            await self._send_error(conn, str(e))
            return

        definition = get_protocol_definition(protocol_type)

        # Broadcast protocol started
        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.PROTOCOL_STARTED,
            payload={
                "protocol_id": str(protocol.id),
                "thread_id": str(thread_id),
                "protocol_type": protocol_type,
                "display_name": definition.display_name,
                "total_phases": definition.total_phases,
                "phase_names": definition.phase_names,
                "current_phase": 0,
                "current_phase_name": definition.phase_names[0],
                "invoked_by": str(conn.user_id),
            },
        ))

        # Trigger initial framing response from LLM
        await self._trigger_protocol_response(
            conn.room_id, thread_id, protocol,
        )

    async def _handle_advance_protocol(self, conn: Connection, payload: dict) -> None:
        """
        Manually advance a protocol to the next phase.

        ARCHITECTURE: Allows users to control pace when auto-advance isn't triggered.
        WHY: LLM may not always emit [PHASE_COMPLETE]; users need manual control.
        """
        protocol_id_str = payload.get("protocol_id")
        if not protocol_id_str:
            await self._send_error(conn, "protocol_id required")
            return

        protocol_id = UUID(protocol_id_str)

        try:
            # Check if this is the last phase — conclude instead of advance
            is_final = await self.protocols.is_final_phase(protocol_id)
            if is_final:
                await self._conclude_protocol(conn.room_id, protocol_id)
                return

            protocol = await self.protocols.advance_phase(protocol_id)
        except ValueError as e:
            await self._send_error(conn, str(e))
            return

        definition = get_protocol_definition(protocol.protocol_type.value)

        # Broadcast phase advancement
        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.PROTOCOL_PHASE_ADVANCED,
            payload={
                "protocol_id": str(protocol.id),
                "thread_id": str(protocol.thread_id),
                "protocol_type": protocol.protocol_type.value,
                "current_phase": protocol.current_phase,
                "current_phase_name": definition.phase_names[protocol.current_phase],
                "total_phases": definition.total_phases,
            },
        ))

        # Trigger LLM response for new phase
        await self._trigger_protocol_response(
            protocol.room_id, protocol.thread_id, protocol,
        )

    async def _handle_abort_protocol(self, conn: Connection, payload: dict) -> None:
        """Abort an active protocol."""
        protocol_id_str = payload.get("protocol_id")
        if not protocol_id_str:
            # Try to find active protocol on current thread
            thread_id = conn.thread_id
            if thread_id:
                active = await self.protocols.get_active(thread_id)
                if active:
                    protocol_id_str = str(active.id)

        if not protocol_id_str:
            await self._send_error(conn, "protocol_id required or no active protocol on thread")
            return

        protocol_id = UUID(protocol_id_str)
        reason = payload.get("reason", "User aborted")

        try:
            protocol = await self.protocols.abort(
                protocol_id=protocol_id,
                user_id=conn.user_id,
                reason=reason,
            )
        except ValueError as e:
            await self._send_error(conn, str(e))
            return

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.PROTOCOL_ABORTED,
            payload={
                "protocol_id": str(protocol.id),
                "thread_id": str(protocol.thread_id),
                "protocol_type": protocol.protocol_type.value,
                "reason": reason,
                "aborted_by": str(conn.user_id),
            },
        ))

    async def _trigger_protocol_response(
        self,
        room_id: UUID,
        thread_id: UUID,
        protocol,
    ) -> None:
        """
        Force an LLM response in protocol mode.

        ARCHITECTURE: Reuses existing force_response path with protocol context.
        WHY: Protocol phases require an immediate LLM response, not heuristic-gated.
        """
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

        try:
            memories = await self.memory.get_context_for_prompt(room_id, max_memories=20)
        except Exception:
            memories = []

        await self.connections.broadcast(room_id, OutboundMessage(
            type=MessageTypes.LLM_THINKING,
            payload={"thread_id": str(thread_id)},
        ))

        result = await self.llm.force_response(
            room=room,
            thread=thread,
            users=users,
            messages=messages,
            memories=memories,
            protocol=protocol,
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
                    "user_name": "Facilitator",
                    "message_type": result.response.message_type.value,
                    "content": result.response.content,
                    "model_used": result.response.model_used,
                },
            ))

            # Auto-advance on phase completion signal
            if result.phase_complete_signal:
                await self._handle_phase_complete(
                    room_id, thread_id, protocol, result.phase_complete_signal,
                    room, thread, users, memories,
                )

    async def _handle_phase_complete(
        self,
        room_id: UUID,
        thread_id: UUID,
        protocol,
        signal: str,
        room: Room,
        thread: Thread,
        users: list[User],
        memories: list[Memory],
    ) -> None:
        """
        Handle automatic phase advancement when LLM signals phase completion.

        ARCHITECTURE: Auto-advance to next phase or trigger conclusion.
        WHY: Smooth protocol flow without requiring manual user intervention.
        TRADEOFF: Automatic advancement may be too fast; users can disable via config.
        """
        logger.info(
            f"Phase complete signal for protocol {protocol.id}: {signal}"
        )

        is_final = await self.protocols.is_final_phase(protocol.id)

        if is_final:
            # Auto-conclude: trigger synthesis response then conclude
            await self._conclude_protocol(room_id, protocol.id)
        else:
            # Advance to next phase
            try:
                advanced = await self.protocols.advance_phase(protocol.id)
            except ValueError as e:
                logger.warning(f"Auto-advance failed: {e}")
                return

            definition = get_protocol_definition(advanced.protocol_type.value)

            await self.connections.broadcast(room_id, OutboundMessage(
                type=MessageTypes.PROTOCOL_PHASE_ADVANCED,
                payload={
                    "protocol_id": str(advanced.id),
                    "thread_id": str(thread_id),
                    "protocol_type": advanced.protocol_type.value,
                    "current_phase": advanced.current_phase,
                    "current_phase_name": definition.phase_names[advanced.current_phase],
                    "total_phases": definition.total_phases,
                    "auto_advanced": True,
                    "reason": signal,
                },
            ))

            # Trigger LLM for next phase
            await self._trigger_protocol_response(room_id, thread_id, advanced)

    async def _conclude_protocol(self, room_id: UUID, protocol_id: UUID) -> None:
        """
        Conclude a protocol: trigger synthesis, save as memory, broadcast conclusion.

        ARCHITECTURE: Synthesis is generated as a final LLM response, then persisted as a memory.
        WHY: The synthesis document is the durable artifact of the protocol session.
        TRADEOFF: Extra LLM call + memory write vs just ending the protocol.
        """
        # Get protocol state
        row = await self.db.fetchrow(
            "SELECT * FROM thread_protocols WHERE id = $1", protocol_id
        )
        if row is None:
            return

        protocol_type = row["protocol_type"]
        thread_id = row["thread_id"]
        definition = get_protocol_definition(protocol_type)

        # Generate synthesis memory content via LLM
        # We use the synthesis prompt from the protocol definition
        synthesis_key = f"protocol:{protocol_type}:synthesis:{str(protocol_id)[:8]}"

        try:
            synthesis_memory = await self.memory.add_memory(
                room_id=room_id,
                key=synthesis_key,
                content=f"[Protocol {definition.display_name} concluded — synthesis pending]",
                created_by_user_id=row.get("invoked_by_user_id"),
            )
            synthesis_memory_id = synthesis_memory.id
        except Exception as e:
            logger.warning(f"Failed to create synthesis memory: {e}")
            synthesis_memory_id = None

        # Conclude the protocol
        try:
            concluded = await self.protocols.conclude(
                protocol_id=protocol_id,
                synthesis_memory_id=synthesis_memory_id,
            )
        except ValueError as e:
            logger.warning(f"Conclude failed: {e}")
            return

        # Broadcast conclusion
        await self.connections.broadcast(room_id, OutboundMessage(
            type=MessageTypes.PROTOCOL_CONCLUDED,
            payload={
                "protocol_id": str(concluded.id),
                "thread_id": str(thread_id),
                "protocol_type": concluded.protocol_type.value,
                "display_name": definition.display_name,
                "synthesis_memory_id": str(synthesis_memory_id) if synthesis_memory_id else None,
            },
        ))

    # ============================================================
    # STAKES / COMMITMENTS HANDLERS
    # ============================================================

    async def _handle_create_commitment(self, conn: Connection, payload: dict) -> None:
        """
        Create a new commitment via WebSocket.

        ARCHITECTURE: WebSocket path for in-conversation commitment creation.
        WHY: Commitments arise naturally in dialogue; creating them should be seamless.
        """
        claim = payload.get("claim", "").strip()
        resolution_criteria = payload.get("resolution_criteria", "").strip()

        if not claim or not resolution_criteria:
            await self._send_error(conn, "claim and resolution_criteria are required")
            return

        category = payload.get("category", "prediction")
        if category not in ("prediction", "commitment", "bet"):
            category = "prediction"

        deadline_str = payload.get("deadline")
        deadline = None
        if deadline_str:
            try:
                deadline = datetime.fromisoformat(deadline_str)
            except (ValueError, TypeError):
                pass

        initial_confidence = payload.get("initial_confidence")
        if initial_confidence is not None:
            try:
                initial_confidence = float(initial_confidence)
                if not (0 <= initial_confidence <= 1):
                    initial_confidence = None
            except (ValueError, TypeError):
                initial_confidence = None

        source_message_id = payload.get("source_message_id")
        if source_message_id:
            source_message_id = UUID(source_message_id)

        mgr = CommitmentManager(self.db)
        result = await mgr.create_commitment(
            room_id=conn.room_id,
            claim=claim,
            resolution_criteria=resolution_criteria,
            created_by_user_id=conn.user_id,
            thread_id=conn.thread_id,
            source_message_id=source_message_id,
            deadline=deadline,
            category=category,
            initial_confidence=initial_confidence,
        )

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.COMMITMENT_CREATED,
            payload={
                "id": str(result["id"]),
                "room_id": str(result["room_id"]),
                "claim": result["claim"],
                "resolution_criteria": result["resolution_criteria"],
                "category": result["category"],
                "created_by_user_id": str(conn.user_id),
                "deadline": result["deadline"].isoformat() if result["deadline"] else None,
                "initial_confidence": result["initial_confidence"],
                "status": "active",
            },
        ))

    async def _handle_record_confidence(self, conn: Connection, payload: dict) -> None:
        """Record confidence level via WebSocket."""
        commitment_id_str = payload.get("commitment_id")
        if not commitment_id_str:
            await self._send_error(conn, "commitment_id required")
            return

        try:
            confidence = float(payload.get("confidence", 0.5))
            if not (0 <= confidence <= 1):
                raise ValueError
        except (ValueError, TypeError):
            await self._send_error(conn, "confidence must be a number between 0 and 1")
            return

        reasoning = payload.get("reasoning")
        commitment_id = UUID(commitment_id_str)

        # SECURITY: Verify commitment belongs to user's room (prevent cross-room IDOR)
        room_check = await self.db.fetchval(
            "SELECT room_id FROM commitments WHERE id = $1", commitment_id
        )
        if room_check != conn.room_id:
            await self._send_error(conn, "Commitment not found in this room")
            return

        mgr = CommitmentManager(self.db)
        try:
            await mgr.record_confidence(
                commitment_id=commitment_id,
                user_id=conn.user_id,
                confidence=confidence,
                reasoning=reasoning,
            )
        except ValueError as e:
            await self._send_error(conn, str(e))

    async def _handle_resolve_commitment(self, conn: Connection, payload: dict) -> None:
        """Resolve a commitment via WebSocket."""
        commitment_id_str = payload.get("commitment_id")
        resolution = payload.get("resolution")

        if not commitment_id_str or not resolution:
            await self._send_error(conn, "commitment_id and resolution required")
            return

        commitment_id = UUID(commitment_id_str)
        resolution_notes = payload.get("resolution_notes")

        # SECURITY: Verify commitment belongs to user's room (prevent cross-room IDOR)
        room_check = await self.db.fetchval(
            "SELECT room_id FROM commitments WHERE id = $1", commitment_id
        )
        if room_check != conn.room_id:
            await self._send_error(conn, "Commitment not found in this room")
            return

        mgr = CommitmentManager(self.db)
        try:
            result = await mgr.resolve(
                commitment_id=commitment_id,
                resolution=resolution,
                resolved_by_user_id=conn.user_id,
                resolution_notes=resolution_notes,
            )
        except ValueError as e:
            await self._send_error(conn, str(e))
            return

        await self.connections.broadcast(conn.room_id, OutboundMessage(
            type=MessageTypes.COMMITMENT_RESOLVED,
            payload={
                "id": str(commitment_id),
                "resolution": result["resolution"],
                "resolution_notes": result["resolution_notes"],
                "resolved_at": result["resolved_at"].isoformat(),
                "resolved_by_user_id": str(conn.user_id),
                "status": result["status"],
            },
        ))

    async def _send_error(self, conn: Connection, error: str) -> None:
        """Send error to client."""
        await self.connections.send_to_user(conn.user_id, conn.room_id, OutboundMessage(
            type=MessageTypes.ERROR,
            payload={"error": error},
        ))
