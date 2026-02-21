# analytics/knowledge_graph.py — Graph traversal over existing relational data

"""
ARCHITECTURE: Graph traversal over existing relational data.
WHY: The data model already encodes graph relationships — this surfaces them.
TRADEOFF: Materialized view (fast reads, stale data) vs live queries (slow, always fresh).
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg
import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================
# MATERIALIZED VIEW DDL
# ============================================================

KNOWLEDGE_GRAPH_VIEW_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS knowledge_graph AS

-- Memory cross-room citations
SELECT
    'citation'::text AS edge_type,
    mr.source_memory_id AS source_id,
    'memory'::text AS source_type,
    COALESCE(mr.target_message_id, mr.source_memory_id) AS target_id,
    CASE WHEN mr.target_message_id IS NOT NULL THEN 'message' ELSE 'memory' END AS target_type,
    COALESCE(mr.relevance_score, 0.5)::float AS weight,
    mr.target_room_id AS room_id,
    mr.referenced_at AS created_at
FROM memory_references mr

UNION ALL

-- Thread fork relationships
SELECT
    'fork'::text AS edge_type,
    t.parent_thread_id AS source_id,
    'thread'::text AS source_type,
    t.id AS target_id,
    'thread'::text AS target_type,
    1.0::float AS weight,
    t.room_id AS room_id,
    t.created_at AS created_at
FROM threads t
WHERE t.parent_thread_id IS NOT NULL

UNION ALL

-- Message-to-message references
SELECT
    'message_reference'::text AS edge_type,
    m.id AS source_id,
    'message'::text AS source_type,
    m.references_message_id AS target_id,
    'message'::text AS target_type,
    1.0::float AS weight,
    t.room_id AS room_id,
    m.created_at AS created_at
FROM messages m
JOIN threads t ON m.thread_id = t.id
WHERE m.references_message_id IS NOT NULL AND NOT m.is_deleted

UNION ALL

-- Message-to-memory references
SELECT
    'memory_reference'::text AS edge_type,
    m.id AS source_id,
    'message'::text AS source_type,
    m.references_memory_id AS target_id,
    'memory'::text AS target_type,
    1.0::float AS weight,
    t.room_id AS room_id,
    m.created_at AS created_at
FROM messages m
JOIN threads t ON m.thread_id = t.id
WHERE m.references_memory_id IS NOT NULL AND NOT m.is_deleted

UNION ALL

-- Memory crystallization: memory sourced from a message
SELECT
    'crystallized'::text AS edge_type,
    mem.source_message_id AS source_id,
    'message'::text AS source_type,
    mem.id AS target_id,
    'memory'::text AS target_type,
    1.0::float AS weight,
    mem.room_id AS room_id,
    mem.created_at AS created_at
FROM memories mem
WHERE mem.source_message_id IS NOT NULL AND mem.status = 'active'

UNION ALL

-- Memory evolution: version-to-version lineage
SELECT
    'memory_evolution'::text AS edge_type,
    m.id AS source_id,
    'memory'::text AS source_type,
    m.id AS target_id,
    'memory_version'::text AS target_type,
    (mv.version::float / NULLIF(m.version, 0))::float AS weight,
    m.room_id AS room_id,
    mv.updated_at AS created_at
FROM memory_versions mv
JOIN memories m ON mv.memory_id = m.id
WHERE mv.version > 1
"""

KNOWLEDGE_GRAPH_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_kg_source ON knowledge_graph (source_type, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_kg_target ON knowledge_graph (target_type, target_id)",
    "CREATE INDEX IF NOT EXISTS idx_kg_room ON knowledge_graph (room_id)",
    "CREATE INDEX IF NOT EXISTS idx_kg_edge_type ON knowledge_graph (edge_type)",
]


# ============================================================
# RESPONSE MODELS
# ============================================================

class GraphNode(BaseModel):
    """A node in the knowledge graph."""
    id: UUID
    type: str  # 'memory', 'message', 'thread', 'room', 'memory_version'
    label: str
    metadata: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """An edge connecting two nodes in the knowledge graph."""
    source_id: UUID
    target_id: UUID
    edge_type: str  # 'memory_reference', 'thread_fork', 'message_reference', 'memory_evolution'
    weight: float


class ConceptMap(BaseModel):
    """Cross-room concept map for a semantic query."""
    query: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    rooms_involved: list[UUID]


class IdeaProvenance(BaseModel):
    """Full provenance chain for a memory."""
    memory: GraphNode
    versions: list[dict]  # version history entries
    source_message: Optional[GraphNode] = None
    thread_path: list[GraphNode]  # thread ancestry from root to source
    room: Optional[GraphNode] = None


class ContributorStats(BaseModel):
    """Contribution statistics for a single participant."""
    user_id: UUID
    display_name: str
    memories_created: int
    memories_cited: int
    total_messages: int


class ContributionGraph(BaseModel):
    """Contribution breakdown for a room."""
    room_id: UUID
    contributors: list[ContributorStats]


# ============================================================
# KNOWLEDGE GRAPH ENGINE
# ============================================================

class KnowledgeGraphEngine:
    """
    ARCHITECTURE: Graph traversal over existing relational data.
    WHY: The data model already encodes graph relationships — this surfaces them.
    TRADEOFF: Materialized view (fast reads, stale data) vs live queries (slow, always fresh).
    """

    def __init__(self, db: asyncpg.Connection):
        self.db = db

    async def _view_exists(self) -> bool:
        """Check if the materialized view has been created."""
        row = await self.db.fetchrow(
            "SELECT 1 FROM pg_matviews WHERE matviewname = 'knowledge_graph'"
        )
        return row is not None

    async def ensure_view(self) -> None:
        """
        Create the materialized view and indexes if they don't exist.

        ARCHITECTURE: Idempotent — safe to call on every startup.
        WHY: Eliminates manual migration step for the knowledge graph.
        TRADEOFF: Startup cost on first run; no-op thereafter.
        """
        await self.db.execute(KNOWLEDGE_GRAPH_VIEW_SQL)
        for idx_sql in KNOWLEDGE_GRAPH_INDEXES_SQL:
            await self.db.execute(idx_sql)
        logger.info("Knowledge graph materialized view ensured")

    async def refresh(self) -> None:
        """
        Refresh the materialized view with latest data.

        ARCHITECTURE: CONCURRENTLY allows reads during refresh.
        WHY: Graph queries don't block while the view rebuilds.
        TRADEOFF: Requires a unique index for CONCURRENTLY; falls back to blocking refresh.
        """
        if not await self._view_exists():
            logger.warning("knowledge_graph materialized view does not exist — creating it")
            await self.ensure_view()
            return
        try:
            await self.db.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY knowledge_graph")
        except Exception:
            logger.warning("CONCURRENTLY refresh failed, using blocking refresh")
            await self.db.execute("REFRESH MATERIALIZED VIEW knowledge_graph")

    # ================================================================
    # CONCEPT MAP
    # ================================================================

    async def get_concept_map(
        self,
        user_id: UUID,
        query: str,
        limit: int = 20,
    ) -> ConceptMap:
        """
        'Show me everything we've discussed about X across all rooms.'

        ARCHITECTURE: Combines vector similarity search with graph edge traversal.
        WHY: Semantic search finds relevant memories; graph edges reveal connections.
        TRADEOFF: Two-pass approach (search then expand) vs single complex query.
        """
        from memory.embeddings import get_embedding_provider

        nodes: dict[UUID, GraphNode] = {}
        edges: list[GraphEdge] = []
        rooms_involved: set[UUID] = set()

        # Phase 1: Semantic search for seed memories
        embedder = get_embedding_provider()
        embedding_result = await embedder.embed(query)
        query_vector = embedding_result.vector

        seed_rows = await self.db.fetch(
            """
            SELECT
                m.id, m.key, m.content, m.room_id, m.scope, m.version,
                r.name as room_name,
                1 - (m.embedding <=> $1::vector) as similarity
            FROM memories m
            JOIN rooms r ON m.room_id = r.id
            JOIN room_memberships rm ON r.id = rm.room_id
            WHERE rm.user_id = $2
              AND m.status = 'active'
              AND m.embedding IS NOT NULL
            ORDER BY similarity DESC
            LIMIT $3
            """,
            query_vector, user_id, limit
        )

        for row in seed_rows:
            nodes[row['id']] = GraphNode(
                id=row['id'],
                type='memory',
                label=row['key'],
                metadata={
                    'content': row['content'],
                    'room_name': row['room_name'],
                    'similarity': float(row['similarity']),
                    'scope': row['scope'],
                    'version': row['version'],
                },
            )
            rooms_involved.add(row['room_id'])

        # Phase 2: Expand via graph edges (if materialized view exists)
        if nodes and await self._view_exists():
            seed_ids = list(nodes.keys())
            edge_rows = await self.db.fetch(
                """
                SELECT edge_type, source_id, source_type, target_id, target_type, weight
                FROM knowledge_graph
                WHERE source_id = ANY($1) OR target_id = ANY($1)
                """,
                seed_ids
            )

            connected_ids: set[UUID] = set()
            for row in edge_rows:
                edges.append(GraphEdge(
                    source_id=row['source_id'],
                    target_id=row['target_id'],
                    edge_type=row['edge_type'],
                    weight=float(row['weight']),
                ))
                if row['source_id'] not in nodes:
                    connected_ids.add(row['source_id'])
                if row['target_id'] not in nodes:
                    connected_ids.add(row['target_id'])

            # Resolve connected nodes that aren't already in our set
            if connected_ids:
                # Try memories first
                mem_rows = await self.db.fetch(
                    "SELECT id, key, room_id FROM memories WHERE id = ANY($1)",
                    list(connected_ids)
                )
                for row in mem_rows:
                    nodes[row['id']] = GraphNode(
                        id=row['id'], type='memory', label=row['key'],
                    )
                    rooms_involved.add(row['room_id'])
                    connected_ids.discard(row['id'])

                # Try threads
                if connected_ids:
                    thr_rows = await self.db.fetch(
                        "SELECT id, title, room_id FROM threads WHERE id = ANY($1)",
                        list(connected_ids)
                    )
                    for row in thr_rows:
                        nodes[row['id']] = GraphNode(
                            id=row['id'], type='thread',
                            label=row['title'] or 'Untitled thread',
                        )
                        rooms_involved.add(row['room_id'])
                        connected_ids.discard(row['id'])

                # Try messages
                if connected_ids:
                    msg_rows = await self.db.fetch(
                        """SELECT m.id, LEFT(m.content, 80) as preview, t.room_id
                           FROM messages m JOIN threads t ON m.thread_id = t.id
                           WHERE m.id = ANY($1)""",
                        list(connected_ids)
                    )
                    for row in msg_rows:
                        nodes[row['id']] = GraphNode(
                            id=row['id'], type='message', label=row['preview'],
                        )
                        rooms_involved.add(row['room_id'])

        return ConceptMap(
            query=query,
            nodes=list(nodes.values()),
            edges=edges,
            rooms_involved=list(rooms_involved),
        )

    # ================================================================
    # IDEA PROVENANCE
    # ================================================================

    async def trace_idea_provenance(self, memory_id: UUID) -> IdeaProvenance:
        """
        Trace a memory back through its version history, the message that spawned it,
        the thread fork that created the context, to the original conversation.

        ARCHITECTURE: Multi-step traversal: memory -> versions -> source message -> thread ancestry.
        WHY: Reveals the full genealogy of an idea from conversation to codified knowledge.
        TRADEOFF: Multiple queries vs single complex CTE (readability wins here).
        """
        # 1. Get the memory itself
        mem_row = await self.db.fetchrow(
            """SELECT m.id, m.key, m.content, m.room_id, m.version, m.scope,
                      m.source_message_id, m.created_at,
                      r.name as room_name
               FROM memories m
               JOIN rooms r ON m.room_id = r.id
               WHERE m.id = $1""",
            memory_id
        )
        if not mem_row:
            raise ValueError(f"Memory {memory_id} not found")

        memory_node = GraphNode(
            id=mem_row['id'], type='memory', label=mem_row['key'],
            metadata={
                'content': mem_row['content'],
                'version': mem_row['version'],
                'scope': mem_row['scope'],
                'room_name': mem_row['room_name'],
            },
        )

        # 2. Get version history
        version_rows = await self.db.fetch(
            """SELECT version, content, updated_at, updated_by_user_id
               FROM memory_versions
               WHERE memory_id = $1
               ORDER BY version ASC""",
            memory_id
        )
        versions = [
            {
                'version': row['version'],
                'content': row['content'],
                'updated_at': row['updated_at'].isoformat(),
                'updated_by_user_id': str(row['updated_by_user_id']) if row['updated_by_user_id'] else None,
            }
            for row in version_rows
        ]

        # 3. Get source message (if any)
        source_message_node = None
        source_thread_id = None
        if mem_row['source_message_id']:
            msg_row = await self.db.fetchrow(
                """SELECT m.id, m.content, m.thread_id, m.speaker_type,
                          m.created_at, m.sequence
                   FROM messages m WHERE m.id = $1""",
                mem_row['source_message_id']
            )
            if msg_row:
                source_message_node = GraphNode(
                    id=msg_row['id'], type='message',
                    label=msg_row['content'][:80],
                    metadata={
                        'speaker_type': msg_row['speaker_type'],
                        'sequence': msg_row['sequence'],
                        'created_at': msg_row['created_at'].isoformat(),
                    },
                )
                source_thread_id = msg_row['thread_id']

        # 4. Get thread ancestry path
        thread_path: list[GraphNode] = []
        if source_thread_id:
            ancestry_rows = await self.db.fetch(
                """
                WITH RECURSIVE thread_ancestry AS (
                    SELECT id, parent_thread_id, title, created_at, 0 as depth
                    FROM threads WHERE id = $1

                    UNION ALL

                    SELECT t.id, t.parent_thread_id, t.title, t.created_at, ta.depth + 1
                    FROM threads t
                    JOIN thread_ancestry ta ON t.id = ta.parent_thread_id
                    WHERE ta.depth < 50
                )
                SELECT * FROM thread_ancestry ORDER BY depth DESC
                """,
                source_thread_id
            )
            for row in ancestry_rows:
                thread_path.append(GraphNode(
                    id=row['id'], type='thread',
                    label=row['title'] or 'Untitled thread',
                    metadata={
                        'depth': row['depth'],
                        'created_at': row['created_at'].isoformat(),
                    },
                ))

        # 5. Room node
        room_node = GraphNode(
            id=mem_row['room_id'], type='room',
            label=mem_row['room_name'] or 'Unnamed room',
        )

        return IdeaProvenance(
            memory=memory_node,
            versions=versions,
            source_message=source_message_node,
            thread_path=thread_path,
            room=room_node,
        )

    # ================================================================
    # CONTRIBUTION GRAPH
    # ================================================================

    async def get_contribution_graph(self, room_id: UUID) -> ContributionGraph:
        """
        Which participants introduced ideas that became shared memories?
        Which memories get cited most?

        ARCHITECTURE: Aggregation queries over messages, memories, and references.
        WHY: Surfaces contribution patterns for room-level analytics.
        TRADEOFF: Multiple aggregations vs single complex CTE.
        """
        rows = await self.db.fetch(
            """
            SELECT
                u.id as user_id,
                u.display_name,
                COALESCE(mc.memories_created, 0) as memories_created,
                COALESCE(mr.memories_cited, 0) as memories_cited,
                COALESCE(msg.total_messages, 0) as total_messages
            FROM room_memberships rm
            JOIN users u ON rm.user_id = u.id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) as memories_created
                FROM memories m
                WHERE m.created_by_user_id = u.id AND m.room_id = $1
            ) mc ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*) as memories_cited
                FROM memory_references ref
                JOIN memories m ON ref.source_memory_id = m.id
                WHERE m.created_by_user_id = u.id AND ref.target_room_id = $1
            ) mr ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*) as total_messages
                FROM messages msg
                JOIN threads t ON msg.thread_id = t.id
                WHERE msg.user_id = u.id AND t.room_id = $1
                  AND msg.speaker_type = 'human'
            ) msg ON true
            WHERE rm.room_id = $1
            ORDER BY msg.total_messages DESC
            """,
            room_id
        )

        contributors = [
            ContributorStats(
                user_id=row['user_id'],
                display_name=row['display_name'],
                memories_created=row['memories_created'],
                memories_cited=row['memories_cited'],
                total_messages=row['total_messages'],
            )
            for row in rows
        ]

        return ContributionGraph(room_id=room_id, contributors=contributors)

    # ================================================================
    # CONNECTED MEMORIES
    # ================================================================

    async def get_connected_memories(
        self,
        memory_id: UUID,
        max_depth: int = 2,
    ) -> list[GraphNode]:
        """
        Find memories connected to the given one via references, same-thread,
        or semantic similarity.

        ARCHITECTURE: BFS expansion through graph edges + semantic fallback.
        WHY: Graph edges capture explicit connections; embeddings capture implicit ones.
        TRADEOFF: Bounded depth prevents runaway traversal at cost of missing distant connections.
        """
        visited: set[UUID] = {memory_id}
        result_nodes: list[GraphNode] = []

        # 1. Graph-edge expansion (if materialized view exists)
        if await self._view_exists():
            frontier = [memory_id]
            for depth in range(max_depth):
                if not frontier:
                    break
                edge_rows = await self.db.fetch(
                    """
                    SELECT edge_type, source_id, source_type, target_id, target_type, weight
                    FROM knowledge_graph
                    WHERE (source_id = ANY($1) OR target_id = ANY($1))
                      AND (source_type = 'memory' OR target_type = 'memory')
                    """,
                    frontier
                )
                next_frontier: list[UUID] = []
                for row in edge_rows:
                    neighbor_id = row['target_id'] if row['source_id'] in visited else row['source_id']
                    neighbor_type = row['target_type'] if row['source_id'] in visited else row['source_type']
                    if neighbor_id not in visited and neighbor_type == 'memory':
                        visited.add(neighbor_id)
                        next_frontier.append(neighbor_id)
                frontier = next_frontier

        # 2. Semantic similarity fallback: find memories with similar embeddings
        mem_row = await self.db.fetchrow(
            "SELECT embedding, room_id FROM memories WHERE id = $1 AND embedding IS NOT NULL",
            memory_id
        )
        if mem_row and mem_row['embedding']:
            sim_rows = await self.db.fetch(
                """
                SELECT id, key, content, room_id,
                       1 - (embedding <=> $1::vector) as similarity
                FROM memories
                WHERE id != $2
                  AND status = 'active'
                  AND embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT 10
                """,
                mem_row['embedding'], memory_id
            )
            for row in sim_rows:
                if row['similarity'] >= 0.75 and row['id'] not in visited:
                    visited.add(row['id'])

        # 3. Resolve all visited IDs (except the seed) to GraphNodes
        resolve_ids = list(visited - {memory_id})
        if resolve_ids:
            rows = await self.db.fetch(
                """SELECT id, key, content, room_id, scope, version
                   FROM memories WHERE id = ANY($1) AND status = 'active'""",
                resolve_ids
            )
            for row in rows:
                result_nodes.append(GraphNode(
                    id=row['id'], type='memory', label=row['key'],
                    metadata={
                        'content': row['content'],
                        'scope': row['scope'],
                        'version': row['version'],
                    },
                ))

        return result_nodes
