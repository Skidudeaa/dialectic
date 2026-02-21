# transport/cross_session_handlers.py — WebSocket handlers for cross-session memory

"""
ARCHITECTURE: WebSocket message handlers for cross-session memory operations.
WHY: Real-time cross-room memory search and promotion via WebSocket.
TRADEOFF: More complex handler vs REST-only approach.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
import json
import logging

from .websocket import Connection, OutboundMessage, MessageTypes
from memory.cross_session import CrossSessionMemoryManager, GlobalSearchResult

logger = logging.getLogger(__name__)


class CrossSessionHandlers:
    """
    Handlers for cross-session memory WebSocket messages.
    
    Integrates with the main MessageHandler class.
    """

    def __init__(self, cross_session_manager: CrossSessionMemoryManager):
        self.manager = cross_session_manager

    async def handle_search_global_memories(
        self,
        conn: Connection,
        payload: dict,
    ) -> None:
        """
        Handle SEARCH_GLOBAL_MEMORIES message.
        
        Payload:
            query: str - Search query
            include_current_room: bool - Include memories from current room
            limit: int - Max results (default 10)
        
        Response: GLOBAL_MEMORY_RESULTS with list of matching memories
        """
        query = payload.get("query", "")
        include_current = payload.get("include_current_room", True)
        limit = min(payload.get("limit", 10), 50)  # Cap at 50

        if not query or len(query) < 3:
            await self._send_error(conn, "Query must be at least 3 characters")
            return

        try:
            results = await self.manager.search_user_memories(
                user_id=conn.user_id,
                query=query,
                current_room_id=conn.room_id,
                limit=limit,
                include_current_room=include_current,
            )

            # Format results for WebSocket response
            formatted = [
                {
                    "memory_id": str(r.memory_id),
                    "room_id": str(r.room_id),
                    "room_name": r.room_name,
                    "key": r.key,
                    "content": r.content,
                    "similarity": r.similarity,
                    "is_current_room": r.is_current_room,
                    "created_at": r.created_at.isoformat(),
                }
                for r in results
            ]

            await self._send_message(conn, MessageTypes.GLOBAL_MEMORY_RESULTS, {
                "query": query,
                "results": formatted,
                "total": len(formatted),
            })

        except Exception as e:
            logger.exception(f"Error searching global memories: {e}")
            await self._send_error(conn, f"Search failed: {str(e)}")

    async def handle_promote_memory(
        self,
        conn: Connection,
        payload: dict,
    ) -> None:
        """
        Handle PROMOTE_MEMORY message.
        
        Payload:
            memory_id: str - UUID of memory to promote
        
        Response: MEMORY_PROMOTED with updated memory
        """
        memory_id_str = payload.get("memory_id")
        if not memory_id_str:
            await self._send_error(conn, "memory_id required")
            return

        try:
            memory_id = UUID(memory_id_str)
            memory = await self.manager.promote_memory_to_global(
                memory_id=memory_id,
                user_id=conn.user_id,
            )

            await self._send_message(conn, MessageTypes.MEMORY_PROMOTED, {
                "memory_id": str(memory.id),
                "key": memory.key,
                "scope": memory.scope.value,
                "promoted_at": memory.updated_at.isoformat(),
            })

        except ValueError as e:
            await self._send_error(conn, str(e))
        except Exception as e:
            logger.exception(f"Error promoting memory: {e}")
            await self._send_error(conn, f"Promotion failed: {str(e)}")

    async def handle_reference_memory(
        self,
        conn: Connection,
        payload: dict,
    ) -> None:
        """
        Handle REFERENCE_MEMORY message.
        
        Creates a citation from a memory to the current room/thread.
        
        Payload:
            source_memory_id: str - UUID of memory being referenced
            target_message_id: str - Optional message where it's cited
            context: str - Optional context for why it's referenced
        
        Response: MEMORY_REFERENCED with reference details
        """
        source_memory_id_str = payload.get("source_memory_id")
        if not source_memory_id_str:
            await self._send_error(conn, "source_memory_id required")
            return

        try:
            source_memory_id = UUID(source_memory_id_str)
            target_message_id = None
            if payload.get("target_message_id"):
                target_message_id = UUID(payload["target_message_id"])

            reference = await self.manager.create_reference(
                source_memory_id=source_memory_id,
                target_room_id=conn.room_id,
                target_thread_id=conn.thread_id,
                target_message_id=target_message_id,
                referenced_by_user_id=conn.user_id,
                referenced_by_llm=False,
                citation_context=payload.get("context"),
            )

            await self._send_message(conn, MessageTypes.MEMORY_REFERENCED, {
                "reference_id": str(reference.id),
                "source_memory_id": str(reference.source_memory_id),
                "target_room_id": str(reference.target_room_id),
                "referenced_at": reference.referenced_at.isoformat(),
            })

        except ValueError as e:
            await self._send_error(conn, str(e))
        except Exception as e:
            logger.exception(f"Error creating memory reference: {e}")
            await self._send_error(conn, f"Reference failed: {str(e)}")

    async def send_cross_room_context(
        self,
        conn: Connection,
        context_text: str,
    ) -> None:
        """
        Proactively send relevant cross-room memories to client.
        
        Called when LLM context is being built, to show user what
        external memories are being injected.
        """
        try:
            memories = await self.manager.get_relevant_cross_room_memories(
                user_id=conn.user_id,
                current_room_id=conn.room_id,
                context=context_text,
                limit=5,
                min_similarity=0.75,
            )

            if memories:
                formatted = [
                    {
                        "memory_id": str(m.memory.id),
                        "key": m.memory.key,
                        "content": m.memory.content[:200],  # Truncate for preview
                        "source_room_name": m.source_room_name,
                        "relevance": m.relevance_score,
                    }
                    for m in memories
                ]

                await self._send_message(conn, MessageTypes.CROSS_ROOM_CONTEXT, {
                    "memories": formatted,
                    "message": "Related memories from your other conversations",
                })

        except Exception as e:
            logger.warning(f"Failed to send cross-room context: {e}")

    async def _send_message(self, conn: Connection, msg_type: str, payload: dict) -> None:
        """Send a typed message to the client via WebSocket."""
        data = json.dumps({
            "type": msg_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await conn.websocket.send_text(data)

    async def _send_error(self, conn: Connection, message: str) -> None:
        """Send error message to client."""
        await self._send_message(conn, MessageTypes.ERROR, {"message": message})
