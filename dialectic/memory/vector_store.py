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
    score: float                 # RRF-fused score from recall(); raw cosine from search()
    scope: str
    owner_user_id: Optional[UUID]
    similarity: Optional[float] = None   # dense cosine similarity, when an embedding exists
    speaker_user_id: Optional[UUID] = None
    lanes: str = "dense"                 # which lanes matched, e.g. "dense+fts"


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

    async def recall(
        self,
        room_id: UUID,
        query_text: str,
        query_embedding: Optional[list[float]],
        speaker_ids: Optional[list[UUID]] = None,
        limit: int = 10,
        lane_depth: int = 20,
        rrf_k: int = 60,
    ) -> list[SimilarityMatch]:
        """
        Three-lane recall fused with reciprocal rank fusion.

        ARCHITECTURE: dense vector + Postgres FTS + entity/speaker lane, fused
        as sum(1/(k+rank)) per lane, one round-trip SQL.
        WHY: ported from the July 2026 agent-memory research — embeddings smooth
        over exact names/numbers that FTS catches, and a three-way conversation
        needs "what did Dan say" to rank Dan's memories. Single query keeps the
        interjection latency budget (~1s total per turn).
        TRADEOFF: RRF scores are rank-based (~0.016–0.049), not similarities —
        callers needing a similarity floor use the `similarity` field.
        """
        speaker_ids = speaker_ids or []

        lanes_sql = []
        if query_embedding is not None:
            lanes_sql.append("""
                SELECT id, row_number() OVER (ORDER BY embedding <=> $2::vector) AS rank,
                       'dense' AS lane
                FROM (
                    SELECT id, embedding FROM memories
                    WHERE room_id = $1 AND status = 'active' AND embedding IS NOT NULL
                    ORDER BY embedding <=> $2::vector
                    LIMIT $5
                ) d
            """)
        lanes_sql.append("""
            SELECT id, row_number() OVER (ORDER BY rnk DESC) AS rank, 'fts' AS lane
            FROM (
                SELECT id, ts_rank_cd(fts, websearch_to_tsquery('english', $3)) AS rnk
                FROM memories
                WHERE room_id = $1 AND status = 'active'
                  AND fts @@ websearch_to_tsquery('english', $3)
                ORDER BY rnk DESC
                LIMIT $5
            ) f
        """)
        lanes_sql.append("""
            SELECT id, row_number() OVER (ORDER BY ent_score DESC) AS rank, 'entity' AS lane
            FROM (
                SELECT id, GREATEST(
                    word_similarity(key, $3),
                    CASE WHEN speaker_user_id = ANY($4::uuid[]) THEN 0.5 ELSE 0.0 END
                ) AS ent_score
                FROM memories
                WHERE room_id = $1 AND status = 'active'
                  AND (key <% $3 OR speaker_user_id = ANY($4::uuid[]))
                ORDER BY ent_score DESC
                LIMIT $5
            ) e
        """)

        sql = f"""
            WITH lanes AS ({' UNION ALL '.join(lanes_sql)}),
            fused AS (
                SELECT id,
                       sum(1.0 / ($6 + rank)) AS rrf,
                       string_agg(lane, '+' ORDER BY lane) AS matched_lanes
                FROM lanes
                GROUP BY id
            )
            SELECT m.id, m.key, m.content, m.scope, m.owner_user_id, m.speaker_user_id,
                   f.rrf, f.matched_lanes,
                   CASE WHEN m.embedding IS NOT NULL AND $2::text IS NOT NULL
                        THEN 1 - (m.embedding <=> $2::vector) END AS cosine
            FROM fused f
            JOIN memories m ON m.id = f.id
            ORDER BY f.rrf DESC
            LIMIT $7
        """

        embedding_str = self._vector_to_str(query_embedding) if query_embedding is not None else None
        rows = await self.db.fetch(
            sql,
            room_id, embedding_str, query_text or "",
            speaker_ids, lane_depth, rrf_k, limit,
        )

        return [
            SimilarityMatch(
                memory_id=row['id'],
                key=row['key'],
                content=row['content'],
                score=float(row['rrf']),
                scope=row['scope'],
                owner_user_id=row['owner_user_id'],
                similarity=float(row['cosine']) if row['cosine'] is not None else None,
                speaker_user_id=row['speaker_user_id'],
                lanes=row['matched_lanes'],
            )
            for row in rows
        ]

    async def find_near_duplicates(
        self,
        room_id: UUID,
        content: str,
        embedding: Optional[list[float]],
        cosine_floor: float = 0.88,
        trigram_floor: float = 0.55,
    ) -> list[dict]:
        """
        Find active memories that restate `content`, by either dedup pass.

        WHY both passes: two humans restating one point in different words is
        the common case — trigram catches near-verbatim restatement that
        embeddings smooth over, embeddings catch paraphrase trigram misses.
        """
        if embedding is not None:
            rows = await self.db.fetch(
                """
                SELECT id, key, content, speaker_user_id,
                       CASE WHEN embedding IS NOT NULL
                            THEN 1 - (embedding <=> $2::vector) END AS cosine,
                       similarity(content, $3) AS trigram
                FROM memories
                WHERE room_id = $1 AND status = 'active'
                  AND ((embedding IS NOT NULL AND 1 - (embedding <=> $2::vector) >= $4)
                       OR similarity(content, $3) >= $5)
                ORDER BY GREATEST(coalesce(1 - (embedding <=> $2::vector), 0),
                                  similarity(content, $3)) DESC
                LIMIT 3
                """,
                room_id, self._vector_to_str(embedding), content,
                cosine_floor, trigram_floor,
            )
        else:
            rows = await self.db.fetch(
                """
                SELECT id, key, content, speaker_user_id,
                       NULL::float AS cosine,
                       similarity(content, $2) AS trigram
                FROM memories
                WHERE room_id = $1 AND status = 'active'
                  AND similarity(content, $2) >= $3
                ORDER BY similarity(content, $2) DESC
                LIMIT 3
                """,
                room_id, content, trigram_floor,
            )
        return [dict(row) for row in rows]

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
