# memory/vector_store.py — pgvector operations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID
import logging

logger = logging.getLogger(__name__)


@dataclass
class SimilarityMatch:
    memory_id: UUID
    key: str
    content: str
    score: float
    scope: str
    owner_user_id: Optional[UUID]


class VectorStore:
    """
    ARCHITECTURE: pgvector-backed semantic search.
    WHY: Postgres-native, no separate vector DB.
    TRADEOFF: Scale limits vs operational simplicity.
    """

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _vector_to_str(embedding: list[float]) -> str:
        """Convert embedding list to pgvector-compatible string format."""
        return '[' + ','.join(str(x) for x in embedding) + ']'

    async def upsert_embedding(
        self,
        memory_id: UUID,
        embedding: list[float],
    ) -> None:
        """Store or update embedding for a memory."""
        await self.db.execute(
            "UPDATE memories SET embedding = $1::vector WHERE id = $2",
            self._vector_to_str(embedding), memory_id
        )
        logger.debug(f"Upserted embedding for memory {memory_id}")

    async def search(
        self,
        room_id: UUID,
        query_embedding: list[float],
        limit: int = 10,
        min_score: float = 0.5,
        include_invalidated: bool = False,
    ) -> list[SimilarityMatch]:
        """
        Find memories similar to query embedding.
        Uses pgvector's <=> operator (cosine distance).
        """

        status_filter = "" if include_invalidated else "AND status = 'active'"

        rows = await self.db.fetch(
            f"""
            SELECT
                id, key, content, scope, owner_user_id,
                1 - (embedding <=> $1::vector) as score
            FROM memories
            WHERE room_id = $2
              AND embedding IS NOT NULL
              {status_filter}
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            self._vector_to_str(query_embedding), room_id, limit
        )

        matches = []
        for row in rows:
            if row['score'] >= min_score:
                matches.append(SimilarityMatch(
                    memory_id=row['id'],
                    key=row['key'],
                    content=row['content'],
                    score=row['score'],
                    scope=row['scope'],
                    owner_user_id=row['owner_user_id'],
                ))

        return matches

    async def compute_novelty(
        self,
        room_id: UUID,
        query_embedding: list[float],
        recent_window: int = 20,
    ) -> float:
        """
        Compute semantic novelty of a message.
        Returns 0-1 score where 0 = highly similar, 1 = completely novel.
        """

        matches = await self.search(
            room_id=room_id,
            query_embedding=query_embedding,
            limit=5,
            min_score=0.0,
        )

        if not matches:
            return 1.0

        max_similarity = max(m.score for m in matches)
        return 1.0 - max_similarity
