# memory/manager.py — Memory lifecycle + conflict resolution

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
import logging
import sys
import pathlib

_package_root = str(pathlib.Path(__file__).resolve().parent.parent)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

from models import (
    Memory, MemoryScope, MemoryStatus, Event, EventType,
    MemoryAddedPayload, MemoryEditedPayload, MemoryInvalidatedPayload
)
from .embeddings import EmbeddingProvider, get_embedding_provider
from .vector_store import VectorStore, SimilarityMatch

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    ARCHITECTURE: Central memory lifecycle management.
    WHY: Encapsulates embedding, versioning, conflict detection.
    TRADEOFF: Coupling vs coherent memory operations.
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

    async def add_memory(
        self,
        room_id: UUID,
        key: str,
        content: str,
        created_by_user_id: UUID,
        scope: MemoryScope = MemoryScope.ROOM,
        owner_user_id: Optional[UUID] = None,
        source_message_id: Optional[UUID] = None,
    ) -> Memory:
        """Create a new memory entry."""

        now = datetime.now(timezone.utc)
        memory_id = uuid4()

        memory = Memory(
            id=memory_id,
            room_id=room_id,
            created_at=now,
            updated_at=now,
            version=1,
            scope=scope,
            owner_user_id=owner_user_id,
            key=key,
            content=content,
            source_message_id=source_message_id,
            created_by_user_id=created_by_user_id,
            status=MemoryStatus.ACTIVE,
        )

        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=EventType.MEMORY_ADDED,
            room_id=room_id,
            user_id=created_by_user_id,
            payload=MemoryAddedPayload(
                memory_id=memory_id,
                scope=scope,
                owner_user_id=owner_user_id,
                key=key,
                content=content,
                source_message_id=source_message_id,
            ).model_dump()
        )

        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            event.id, event.timestamp, event.event_type.value,
            event.room_id, event.user_id, event.payload
        )

        await self.db.execute(
            """INSERT INTO memories
               (id, room_id, created_at, updated_at, version, scope, owner_user_id,
                key, content, source_message_id, created_by_user_id, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            memory.id, memory.room_id, memory.created_at, memory.updated_at,
            memory.version, memory.scope.value, memory.owner_user_id,
            memory.key, memory.content, memory.source_message_id,
            memory.created_by_user_id, memory.status.value
        )

        await self.db.execute(
            """INSERT INTO memory_versions (memory_id, version, content, updated_at, updated_by_user_id)
               VALUES ($1, $2, $3, $4, $5)""",
            memory.id, 1, content, now, created_by_user_id
        )

        # Generate embedding async
        await self._generate_embedding(memory.id, content)

        logger.info(f"Created memory {memory_id}: {key}")
        return memory

    async def edit_memory(
        self,
        memory_id: UUID,
        new_content: str,
        edited_by_user_id: UUID,
        edit_reason: Optional[str] = None,
    ) -> Memory:
        """Edit existing memory. Creates new version, logs change."""

        row = await self.db.fetchrow(
            "SELECT * FROM memories WHERE id = $1", memory_id
        )
        if not row:
            raise ValueError(f"Memory {memory_id} not found")

        previous_version = row['version']
        previous_content = row['content']
        new_version = previous_version + 1
        now = datetime.now(timezone.utc)

        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=EventType.MEMORY_EDITED,
            room_id=row['room_id'],
            user_id=edited_by_user_id,
            payload=MemoryEditedPayload(
                memory_id=memory_id,
                previous_version=previous_version,
                new_version=new_version,
                previous_content=previous_content,
                new_content=new_content,
                edit_reason=edit_reason,
            ).model_dump()
        )

        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            event.id, event.timestamp, event.event_type.value,
            event.room_id, event.user_id, event.payload
        )

        await self.db.execute(
            """UPDATE memories
               SET content = $1, version = $2, updated_at = $3
               WHERE id = $4""",
            new_content, new_version, now, memory_id
        )

        await self.db.execute(
            """INSERT INTO memory_versions (memory_id, version, content, updated_at, updated_by_user_id)
               VALUES ($1, $2, $3, $4, $5)""",
            memory_id, new_version, new_content, now, edited_by_user_id
        )

        await self._generate_embedding(memory_id, new_content)

        logger.info(f"Edited memory {memory_id}: v{previous_version} → v{new_version}")

        updated_row = await self.db.fetchrow(
            "SELECT * FROM memories WHERE id = $1", memory_id
        )
        return Memory(**dict(updated_row))

    async def invalidate_memory(
        self,
        memory_id: UUID,
        invalidated_by_user_id: UUID,
        reason: Optional[str] = None,
    ) -> Memory:
        """Soft-delete a memory."""

        row = await self.db.fetchrow(
            "SELECT * FROM memories WHERE id = $1", memory_id
        )
        if not row:
            raise ValueError(f"Memory {memory_id} not found")

        now = datetime.now(timezone.utc)

        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=EventType.MEMORY_INVALIDATED,
            room_id=row['room_id'],
            user_id=invalidated_by_user_id,
            payload=MemoryInvalidatedPayload(
                memory_id=memory_id,
                reason=reason,
            ).model_dump()
        )

        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            event.id, event.timestamp, event.event_type.value,
            event.room_id, event.user_id, event.payload
        )

        await self.db.execute(
            """UPDATE memories
               SET status = $1, invalidated_by_user_id = $2,
                   invalidated_at = $3, invalidation_reason = $4
               WHERE id = $5""",
            MemoryStatus.INVALIDATED.value, invalidated_by_user_id,
            now, reason, memory_id
        )

        logger.info(f"Invalidated memory {memory_id}")

        updated_row = await self.db.fetchrow(
            "SELECT * FROM memories WHERE id = $1", memory_id
        )
        return Memory(**dict(updated_row))

    async def get_room_memories(
        self,
        room_id: UUID,
        include_invalidated: bool = False,
    ) -> list[Memory]:
        """Get all active memories for a room."""

        if include_invalidated:
            rows = await self.db.fetch(
                "SELECT * FROM memories WHERE room_id = $1 ORDER BY created_at",
                room_id
            )
        else:
            rows = await self.db.fetch(
                "SELECT * FROM memories WHERE room_id = $1 AND status = 'active' ORDER BY created_at",
                room_id
            )
        return [Memory(**dict(row)) for row in rows]

    async def search_memories(
        self,
        room_id: UUID,
        query: str,
        limit: int = 10,
        min_score: float = 0.5,
    ) -> list[SimilarityMatch]:
        """Semantic search over room memories."""

        result = await self.embedder.embed(query)

        return await self.vector_store.search(
            room_id=room_id,
            query_embedding=result.vector,
            limit=limit,
            min_score=min_score,
        )

    async def compute_message_novelty(
        self,
        room_id: UUID,
        message_content: str,
    ) -> float:
        """Compute semantic novelty of a message vs room memory."""

        result = await self.embedder.embed(message_content)
        return await self.vector_store.compute_novelty(
            room_id=room_id,
            query_embedding=result.vector,
        )

    async def get_context_for_prompt(
        self,
        room_id: UUID,
        query: Optional[str] = None,
        max_memories: int = 20,
    ) -> list[Memory]:
        """Get relevant memories for LLM prompt injection."""

        if query:
            matches = await self.search_memories(
                room_id=room_id,
                query=query,
                limit=max_memories,
            )
            memory_ids = [m.memory_id for m in matches]
            if not memory_ids:
                return []

            rows = await self.db.fetch(
                "SELECT * FROM memories WHERE id = ANY($1)",
                memory_ids
            )
            return [Memory(**dict(row)) for row in rows]
        else:
            rows = await self.db.fetch(
                """SELECT * FROM memories
                   WHERE room_id = $1 AND status = 'active'
                   ORDER BY updated_at DESC
                   LIMIT $2""",
                room_id, max_memories
            )
            return [Memory(**dict(row)) for row in rows]

    async def _generate_embedding(self, memory_id: UUID, content: str) -> None:
        """Generate and store embedding for memory content."""
        try:
            result = await self.embedder.embed(content)
            await self.vector_store.upsert_embedding(memory_id, result.vector)
        except Exception as e:
            logger.error(f"Failed to generate embedding for {memory_id}: {e}")
