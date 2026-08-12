# memory/cross_session.py — Cross-session memory search and referencing

"""
ARCHITECTURE: Manages memory access and references across rooms/sessions.
WHY: Enables persistent knowledge graph spanning all user conversations.
TRADEOFF: Query complexity vs powerful cross-conversation insights.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID, uuid4
import logging

from models import (
    Memory, MemoryReference,
    UserMemoryCollection, CollectionMembership, CrossRoomMemoryResult,
    EventType, MemoryReferencedPayload
)
from .embeddings import EmbeddingProvider, get_embedding_provider
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class GlobalSearchResult:
    """Result from searching across all user's rooms."""
    memory_id: UUID
    room_id: UUID
    room_name: str
    content: str
    key: str
    similarity: float
    created_at: datetime
    is_current_room: bool


class CrossSessionMemoryManager:
    """
    ARCHITECTURE: Handles cross-room memory operations.
    WHY: Separate from MemoryManager to keep single-room logic clean.
    TRADEOFF: Some duplication vs clear separation of concerns.
    """

    def __init__(self, db):
        self.db = db
        self.vector_store = VectorStore(db)
        self._embedder: Optional[EmbeddingProvider] = None

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = get_embedding_provider()
        return self._embedder

    # ================================================================
    # GLOBAL MEMORY SEARCH
    # ================================================================

    async def search_user_memories(
        self,
        user_id: UUID,
        query: str,
        current_room_id: Optional[UUID] = None,
        limit: int = 10,
        include_current_room: bool = True,
        require_global_scope: bool = False,
    ) -> List[GlobalSearchResult]:
        """
        Search all memories accessible to a user across all their rooms.
        
        Uses vector similarity search with room membership filtering.
        """
        # Generate embedding for query.
        # WHY str conversion: asyncpg has no codec for ::vector, so the
        # embedding must be passed in pgvector's text form ('[0.1,0.2,...]').
        # Passing the raw list raised "expected str, got list" and silently
        # disabled cross-session memory search via graceful degradation.
        from .vector_store import VectorStore
        embedding_result = await self.embedder.embed(query)
        query_vector = VectorStore._vector_to_str(embedding_result.vector)

        # Search across all rooms user is member of
        sql = """
        WITH user_rooms AS (
            SELECT room_id FROM room_memberships WHERE user_id = $1
        )
        SELECT 
            m.id as memory_id,
            m.room_id,
            r.name as room_name,
            m.content,
            m.key,
            m.created_at,
            1 - (m.embedding <=> $2::vector) as similarity,
            CASE WHEN m.room_id = $3 THEN true ELSE false END as is_current_room
        FROM memories m
        JOIN rooms r ON m.room_id = r.id
        WHERE m.room_id IN (SELECT room_id FROM user_rooms)
          AND m.status = 'active'
          AND m.embedding IS NOT NULL
          AND ($4 OR m.room_id != $3)  -- Optionally exclude current room
          AND (
              NOT $6::boolean
              OR EXISTS (
                  SELECT 1
                  FROM user_memory_promotions ump
                  WHERE ump.memory_id = m.id AND ump.user_id = $1
              )
          )
        ORDER BY similarity DESC
        LIMIT $5
        """
        
        rows = await self.db.fetch(
            sql,
            user_id,
            query_vector,
            current_room_id or uuid4(),  # Dummy UUID if not provided
            include_current_room,
            limit,
            require_global_scope,
        )

        return [
            GlobalSearchResult(
                memory_id=row['memory_id'],
                room_id=row['room_id'],
                room_name=row['room_name'],
                content=row['content'],
                key=row['key'],
                similarity=row['similarity'],
                created_at=row['created_at'],
                is_current_room=row['is_current_room']
            )
            for row in rows
        ]

    async def get_relevant_cross_room_memories(
        self,
        user_id: UUID,
        current_room_id: UUID,
        context: str,
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> List[CrossRoomMemoryResult]:
        """
        Get memories from OTHER rooms that are relevant to current context.
        Used for automatic context injection.
        """
        results = await self.search_user_memories(
            user_id=user_id,
            query=context,
            current_room_id=current_room_id,
            limit=limit * 2,  # Get more, then filter
            include_current_room=False,  # Only cross-room
            # SECURITY: Automatic prompt injection may only cross room
            # boundaries after a user explicitly promoted the memory.
            require_global_scope=True,
        )

        # Filter by similarity threshold
        filtered = [r for r in results if r.similarity >= min_similarity][:limit]

        # Fetch full memory objects
        if not filtered:
            return []

        memory_ids = [r.memory_id for r in filtered]
        rows = await self.db.fetch(
            "SELECT * FROM memories WHERE id = ANY($1)",
            memory_ids
        )
        memories_by_id = {row['id']: Memory(**dict(row)) for row in rows}

        return [
            CrossRoomMemoryResult(
                memory=memories_by_id[r.memory_id],
                source_room_id=r.room_id,
                source_room_name=r.room_name,
                relevance_score=r.similarity,
                is_local=False
            )
            for r in filtered
            if r.memory_id in memories_by_id
        ]

    # ================================================================
    # PERSONAL CROSS-ROOM PROMOTION
    # ================================================================

    async def promote_memory_to_global(
        self,
        memory_id: UUID,
        user_id: UUID,
    ) -> Memory:
        """
        Grant one member cross-room recall of a shared active memory.

        The authorization, grant, and lifecycle event are one SQL statement so
        a failed event append cannot leave an unrecorded visibility change.
        """
        row = await self.db.fetchrow(
            """
            WITH authorized_memory AS (
                SELECT m.*
                FROM memories m
                JOIN room_memberships rm
                  ON rm.room_id = m.room_id AND rm.user_id = $2
                WHERE m.id = $1 AND m.status = 'active'
            ), inserted_promotion AS (
                INSERT INTO user_memory_promotions (memory_id, user_id)
                SELECT id, $2 FROM authorized_memory
                ON CONFLICT (memory_id, user_id) DO NOTHING
                RETURNING memory_id
            ), inserted_event AS (
                INSERT INTO events (
                    id, timestamp, event_type, room_id, user_id, payload
                )
                SELECT
                    gen_random_uuid(),
                    NOW(),
                    'memory_promoted',
                    room_id,
                    $2,
                    jsonb_build_object(
                        'memory_id', id,
                        'original_room_id', room_id,
                        'promoted_by_user_id', $2
                    )
                FROM authorized_memory
                WHERE EXISTS (SELECT 1 FROM inserted_promotion)
            )
            SELECT * FROM authorized_memory
            """,
            memory_id,
            user_id,
        )

        if not row:
            raise ValueError("Memory not found or inaccessible")

        memory = Memory(**dict(row))
        logger.info("Memory %s personally promoted by user %s", memory_id, user_id)
        return memory

    async def demote_memory_from_global(
        self,
        memory_id: UUID,
        user_id: UUID,
    ) -> Memory:
        """Remove only the requesting member's cross-room recall grant."""
        row = await self.db.fetchrow(
            """
            WITH authorized_memory AS (
                SELECT m.*
                FROM memories m
                JOIN room_memberships rm
                  ON rm.room_id = m.room_id AND rm.user_id = $2
                WHERE m.id = $1 AND m.status = 'active'
            ), deleted_promotion AS (
                DELETE FROM user_memory_promotions ump
                USING authorized_memory m
                WHERE ump.memory_id = m.id AND ump.user_id = $2
                RETURNING ump.memory_id
            ), inserted_event AS (
                INSERT INTO events (
                    id, timestamp, event_type, room_id, user_id, payload
                )
                SELECT
                    gen_random_uuid(),
                    NOW(),
                    'memory_demoted',
                    room_id,
                    $2,
                    jsonb_build_object(
                        'memory_id', id,
                        'original_room_id', room_id,
                        'demoted_by_user_id', $2
                    )
                FROM authorized_memory
                WHERE EXISTS (SELECT 1 FROM deleted_promotion)
            )
            SELECT * FROM authorized_memory
            """,
            memory_id,
            user_id,
        )

        if not row:
            raise ValueError("Memory not found or inaccessible")

        return Memory(**dict(row))

    async def get_user_promoted_memory_ids(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> List[UUID]:
        """Return the caller's active personal promotions in one source room."""
        rows = await self.db.fetch(
            """
            SELECT ump.memory_id
            FROM user_memory_promotions ump
            JOIN memories m ON m.id = ump.memory_id
            JOIN room_memberships rm
              ON rm.room_id = m.room_id AND rm.user_id = $2
            WHERE m.room_id = $1
              AND m.status = 'active'
              AND ump.user_id = $2
            ORDER BY ump.promoted_at DESC
            """,
            room_id,
            user_id,
        )
        return [row['memory_id'] for row in rows]

    # ================================================================
    # MEMORY REFERENCES (Citations)
    # ================================================================

    async def create_reference(
        self,
        source_memory_id: UUID,
        target_room_id: UUID,
        target_thread_id: Optional[UUID] = None,
        target_message_id: Optional[UUID] = None,
        referenced_by_user_id: Optional[UUID] = None,
        referenced_by_llm: bool = False,
        citation_context: Optional[str] = None,
        relevance_score: Optional[float] = None,
    ) -> MemoryReference:
        """
        Create a reference from a memory to a message in another room.
        This is the "citation" that links conversations.
        """
        now = datetime.now(timezone.utc)
        ref_id = uuid4()

        # Get source memory's room for event
        source_row = await self.db.fetchrow(
            "SELECT room_id FROM memories WHERE id = $1",
            source_memory_id
        )
        if not source_row:
            raise ValueError(f"Source memory {source_memory_id} not found")

        row = await self.db.fetchrow(
            """
            INSERT INTO memory_references (
                id, source_memory_id, target_room_id, target_thread_id,
                target_message_id, referenced_at, referenced_by_user_id,
                referenced_by_llm, citation_context, relevance_score
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (source_memory_id, target_message_id) DO UPDATE
            SET citation_context = EXCLUDED.citation_context,
                relevance_score = EXCLUDED.relevance_score
            RETURNING *
            """,
            ref_id, source_memory_id, target_room_id, target_thread_id,
            target_message_id, now, referenced_by_user_id,
            referenced_by_llm, citation_context, relevance_score
        )

        reference = MemoryReference(**dict(row))

        # Record event in target room
        await self._record_event(
            EventType.MEMORY_REFERENCED,
            room_id=target_room_id,
            thread_id=target_thread_id,
            user_id=referenced_by_user_id,
            payload=MemoryReferencedPayload(
                reference_id=reference.id,
                source_memory_id=source_memory_id,
                source_room_id=source_row['room_id'],
                target_room_id=target_room_id,
                target_message_id=target_message_id,
                citation_context=citation_context
            ).model_dump()
        )

        logger.info(
            f"Created memory reference: {source_memory_id} -> "
            f"room {target_room_id} (by_llm={referenced_by_llm})"
        )
        return reference

    async def get_references_for_room(
        self,
        room_id: UUID,
        limit: int = 50,
    ) -> List[MemoryReference]:
        """Get all memory references pointing TO a room."""
        rows = await self.db.fetch(
            """
            SELECT * FROM memory_references
            WHERE target_room_id = $1
            ORDER BY referenced_at DESC
            LIMIT $2
            """,
            room_id, limit
        )
        return [MemoryReference(**dict(row)) for row in rows]

    async def get_references_from_memory(
        self,
        memory_id: UUID,
    ) -> List[MemoryReference]:
        """Get all places where a memory has been cited."""
        rows = await self.db.fetch(
            """
            SELECT * FROM memory_references
            WHERE source_memory_id = $1
            ORDER BY referenced_at DESC
            """,
            memory_id
        )
        return [MemoryReference(**dict(row)) for row in rows]

    # ================================================================
    # USER COLLECTIONS
    # ================================================================

    async def create_collection(
        self,
        user_id: UUID,
        name: str,
        description: Optional[str] = None,
        auto_inject: bool = False,
    ) -> UserMemoryCollection:
        """Create a new memory collection for a user."""
        now = datetime.now(timezone.utc)
        collection_id = uuid4()

        row = await self.db.fetchrow(
            """
            INSERT INTO user_memory_collections (
                id, user_id, name, description, created_at, updated_at, auto_inject
            ) VALUES ($1, $2, $3, $4, $5, $5, $6)
            RETURNING *
            """,
            collection_id, user_id, name, description, now, auto_inject
        )

        collection = UserMemoryCollection(**dict(row))

        await self._record_event(
            EventType.COLLECTION_CREATED,
            user_id=user_id,
            payload={"collection_id": str(collection_id), "name": name}
        )

        return collection

    async def add_memory_to_collection(
        self,
        collection_id: UUID,
        memory_id: UUID,
        user_id: UUID,
        notes: Optional[str] = None,
    ) -> CollectionMembership:
        """Add a memory to a collection."""
        now = datetime.now(timezone.utc)

        row = await self.db.fetchrow(
            """
            INSERT INTO collection_memories (
                collection_id, memory_id, added_at, added_by_user_id, notes
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (collection_id, memory_id) DO UPDATE
            SET notes = EXCLUDED.notes
            RETURNING *
            """,
            collection_id, memory_id, now, user_id, notes
        )

        membership = CollectionMembership(**dict(row))

        await self._record_event(
            EventType.COLLECTION_MEMORY_ADDED,
            user_id=user_id,
            payload={
                "collection_id": str(collection_id),
                "memory_id": str(memory_id)
            }
        )

        return membership

    async def get_user_collections(
        self,
        user_id: UUID,
    ) -> List[UserMemoryCollection]:
        """Get all collections for a user."""
        rows = await self.db.fetch(
            """
            SELECT * FROM user_memory_collections
            WHERE user_id = $1
            ORDER BY display_order, created_at
            """,
            user_id
        )
        return [UserMemoryCollection(**dict(row)) for row in rows]

    async def get_collection_memories(
        self,
        collection_id: UUID,
    ) -> List[Memory]:
        """Get all memories in a collection."""
        rows = await self.db.fetch(
            """
            SELECT m.* FROM memories m
            JOIN collection_memories cm ON m.id = cm.memory_id
            WHERE cm.collection_id = $1 AND m.status = 'active'
            ORDER BY cm.added_at DESC
            """,
            collection_id
        )
        return [Memory(**dict(row)) for row in rows]

    async def get_auto_inject_memories(
        self,
        user_id: UUID,
    ) -> List[Memory]:
        """Get all memories from user's auto-inject collections."""
        rows = await self.db.fetch(
            """
            SELECT DISTINCT m.* FROM memories m
            JOIN collection_memories cm ON m.id = cm.memory_id
            JOIN user_memory_collections c ON cm.collection_id = c.id
            JOIN user_memory_promotions ump
              ON ump.memory_id = m.id AND ump.user_id = $1
            JOIN room_memberships rm
              ON rm.room_id = m.room_id AND rm.user_id = $1
            WHERE c.user_id = $1 
              AND c.auto_inject = true
              AND m.status = 'active'
            ORDER BY m.updated_at DESC
            """,
            user_id
        )
        return [Memory(**dict(row)) for row in rows]

    # ================================================================
    # HELPERS
    # ================================================================

    async def _record_event(
        self,
        event_type: EventType,
        room_id: Optional[UUID] = None,
        thread_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        payload: Optional[dict] = None,
    ) -> None:
        """Record an event in the event log."""
        now = datetime.now(timezone.utc)
        await self.db.execute(
            """
            INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            uuid4(), now, event_type.value, room_id, thread_id, user_id, payload or {}
        )
