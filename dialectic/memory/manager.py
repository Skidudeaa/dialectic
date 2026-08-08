# memory/manager.py — Memory lifecycle + conflict resolution

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
import logging
import re

from models import (
    Memory, MemoryScope, MemoryStatus, Event, EventType,
    MemoryAddedPayload, MemoryEditedPayload, MemoryInvalidatedPayload,
    MemorySupersededPayload,
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
        created_by_user_id: Optional[UUID] = None,
        scope: MemoryScope = MemoryScope.ROOM,
        owner_user_id: Optional[UUID] = None,
        source_message_id: Optional[UUID] = None,
        speaker_user_id: Optional[UUID] = None,
        dedup: bool = True,
    ) -> Memory:
        """
        Create a new memory entry, with write-path dedup.

        dedup=False is for system-managed documents (identity docs, protocol
        synthesis slots, thesis state) that upsert by deterministic key —
        their near-identical boilerplate must never collapse across slots.

        ARCHITECTURE: embed first, then run both dedup passes (cosine + trigram)
        against active room memories before inserting.
        WHY: two humans restating the same point in different words is the
        common case in three-way dialogue; storing every restatement buries
        recall in near-duplicates. A same-speaker restatement supersedes the
        old fact (their fact changed); a cross-speaker restatement of the same
        fact slot is confirmation and keeps the original attribution.
        """

        now = datetime.now(timezone.utc)
        memory_id = uuid4()

        # Attribution: whose statement is this? Source message author wins,
        # then the explicit speaker, then whoever saved it.
        if speaker_user_id is None and source_message_id is not None:
            src = await self.db.fetchrow(
                "SELECT user_id FROM messages WHERE id = $1", source_message_id
            )
            if src:
                speaker_user_id = src['user_id']
        if speaker_user_id is None:
            speaker_user_id = created_by_user_id

        # Embed before insert so dedup can use the vector and the INSERT
        # carries it in one pass.
        embedding = None
        try:
            embedding = (await self.embedder.embed(content)).vector
        except Exception as e:
            logger.error(f"Embedding failed, memory will be text-searchable only: {e}")

        existing = None
        if dedup:
            existing = await self._dedup_check(
                room_id, key, content, embedding, speaker_user_id
            )
        if existing is not None and existing['action'] == 'skip':
            row = await self.db.fetchrow(
                "SELECT * FROM memories WHERE id = $1", existing['id']
            )
            logger.info(
                f"Memory dedup: skipped near-duplicate of {existing['id']} "
                f"(cos={existing['cosine']}, trgm={existing['trigram']})"
            )
            return Memory(**dict(row))
        supersede_target = existing if existing is not None else None

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
            speaker_user_id=speaker_user_id,
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
                key, content, source_message_id, created_by_user_id, status,
                speaker_user_id, embedding)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                       $14::vector)""",
            memory.id, memory.room_id, memory.created_at, memory.updated_at,
            memory.version, memory.scope.value, memory.owner_user_id,
            memory.key, memory.content, memory.source_message_id,
            memory.created_by_user_id, memory.status.value,
            memory.speaker_user_id,
            self.vector_store._vector_to_str(embedding) if embedding else None,
        )

        await self.db.execute(
            """INSERT INTO memory_versions (memory_id, version, content, updated_at, updated_by_user_id)
               VALUES ($1, $2, $3, $4, $5)""",
            memory.id, 1, content, now, created_by_user_id  # NULL for LLM-authored
        )

        if supersede_target is not None:
            await self._supersede(
                old_id=supersede_target['id'],
                new_id=memory.id,
                room_id=room_id,
                actor_user_id=created_by_user_id,
                cosine=supersede_target['cosine'],
                trigram=supersede_target['trigram'],
                now=now,
            )
            logger.info(
                f"Memory {supersede_target['id']} superseded by {memory_id}"
            )

        logger.info(f"Created memory {memory_id}: {key}")
        return memory

    async def _dedup_check(
        self,
        room_id: UUID,
        key: str,
        content: str,
        embedding: Optional[list[float]],
        speaker_user_id: Optional[UUID],
    ) -> Optional[dict]:
        """
        Decide what to do about near-duplicates of incoming content.

        Returns None (create freely), or a dict with 'action' of:
        - 'skip': exact restatement or cross-speaker confirmation — caller
          returns the existing memory instead of creating one.
        - 'supersede': the new statement replaces the old fact — caller
          creates the new memory then marks the old one superseded.
        """
        candidates = await self.vector_store.find_near_duplicates(
            room_id, content, embedding
        )
        if not candidates:
            return None

        top = candidates[0]
        cos = top['cosine'] or 0.0
        trgm = top['trigram'] or 0.0
        verbatim = cos >= 0.95 or trgm >= 0.85
        same_key = (top['key'] or '').strip().lower() == (key or '').strip().lower()
        same_speaker = top['speaker_user_id'] == speaker_user_id

        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip().lower())

        result = {'id': top['id'], 'cosine': cos, 'trigram': trgm}
        if norm(top['content']) == norm(content):
            # Identical statement — nothing new to record.
            result['action'] = 'skip'
        elif verbatim or (same_key and same_speaker):
            # Near-verbatim with a change (a corrected number, a tightened
            # claim), or the same person updating their own fact slot: the
            # new statement wins, the old is preserved with a closed
            # validity window.
            result['action'] = 'supersede'
        elif same_key:
            # Someone else restating the same fact slot mid-band:
            # confirmation, keep the original attribution.
            result['action'] = 'skip'
        else:
            # Related but distinct facts coexist (e.g. two speakers with
            # different targets on the same ticker).
            return None
        return result

    async def _supersede(
        self,
        old_id: UUID,
        new_id: UUID,
        room_id: UUID,
        actor_user_id: Optional[UUID],
        cosine: Optional[float],
        trigram: Optional[float],
        now: datetime,
    ) -> None:
        """Close the old memory's validity window, pointing at its successor."""
        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=EventType.MEMORY_SUPERSEDED,
            room_id=room_id,
            user_id=actor_user_id,
            payload=MemorySupersededPayload(
                memory_id=old_id,
                superseded_by_memory_id=new_id,
                cosine_similarity=cosine,
                trigram_similarity=trigram,
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
               SET status = $1, superseded_at = $2, superseded_by_memory_id = $3
               WHERE id = $4""",
            MemoryStatus.SUPERSEDED.value, now, new_id, old_id
        )

    async def edit_memory(
        self,
        memory_id: UUID,
        new_content: str,
        edited_by_user_id: Optional[UUID] = None,
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
        """
        Three-lane recall over room memories (dense + FTS + entity/speaker),
        fused by reciprocal rank fusion.

        WHY: pure cosine smooths over exact names, tickers and numbers, and
        can't answer "what did Dan say about X" — the FTS lane catches exact
        terms, the entity lane ranks by key match and speaker attribution.
        min_score keeps its historical meaning as a similarity floor, but only
        for dense-only hits — an exact text or speaker match is evidence enough.
        """
        embedding = None
        try:
            embedding = (await self.embedder.embed(query)).vector
        except Exception as e:
            logger.warning(f"Query embedding failed, recall degrades to text lanes: {e}")

        speaker_ids = await self._resolve_speaker_mentions(room_id, query)

        matches = await self.vector_store.recall(
            room_id=room_id,
            query_text=query,
            query_embedding=embedding,
            speaker_ids=speaker_ids,
            limit=limit,
        )
        return [
            m for m in matches
            if 'fts' in m.lanes or 'entity' in m.lanes
            or (m.similarity is not None and m.similarity >= min_score)
        ]

    async def _resolve_speaker_mentions(
        self, room_id: UUID, query: str
    ) -> list[UUID]:
        """Map member names appearing in the query to user ids for the entity lane."""
        try:
            rows = await self.db.fetch(
                """SELECT u.id, u.display_name FROM users u
                   JOIN room_memberships rm ON rm.user_id = u.id
                   WHERE rm.room_id = $1""",
                room_id
            )
        except Exception:
            return []

        q = (query or "").lower()
        ids = []
        for row in rows:
            name = (row['display_name'] or '').strip().lower()
            first = name.split()[0] if name else ''
            for candidate in (name, first):
                if candidate and re.search(rf"\b{re.escape(candidate)}\b", q):
                    ids.append(row['id'])
                    break
        return ids

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
            # Preserve recall ranking — ANY($1) returns rows in table order.
            by_id = {row['id']: Memory(**dict(row)) for row in rows}
            return [by_id[mid] for mid in memory_ids if mid in by_id]
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
