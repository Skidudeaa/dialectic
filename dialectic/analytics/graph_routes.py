# analytics/graph_routes.py — Knowledge graph REST endpoints

"""
ARCHITECTURE: REST API layer for knowledge graph traversal.
WHY: Separates HTTP concerns from graph engine logic.
TRADEOFF: Thin route layer with auth checks — all heavy lifting in KnowledgeGraphEngine.
"""

import logging
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from api.token_utils import extract_room_token

from analytics.knowledge_graph import (
    KnowledgeGraphEngine,
    ConceptMap,
    IdeaProvenance,
    ContributionGraph,
    GraphNode,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["knowledge-graph"])


# ============================================================
# AUTH HELPERS
# ============================================================

async def _verify_token(token: str, db: asyncpg.Connection) -> None:
    """Verify that the token belongs to a valid room."""
    row = await db.fetchrow("SELECT 1 FROM rooms WHERE token = $1", token)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")


async def _verify_room_access(
    room_id: UUID, token: str, db: asyncpg.Connection,
) -> None:
    """Verify token matches the given room."""
    row = await db.fetchrow(
        "SELECT 1 FROM rooms WHERE id = $1 AND token = $2",
        room_id, token
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")


async def _verify_user_membership(
    user_id: UUID, db: asyncpg.Connection,
) -> None:
    """Verify the user exists and has at least one room membership."""
    row = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE user_id = $1 LIMIT 1",
        user_id
    )
    if not row:
        raise HTTPException(status_code=403, detail="User has no room memberships")


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

_db_pool = None


def set_graph_db_pool(pool):
    """Set the database pool for graph routes. Called by main.py at startup."""
    global _db_pool
    _db_pool = pool


async def _get_db():
    """Get a database connection from the pool."""
    if _db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    async with _db_pool.acquire() as conn:
        yield conn


# ============================================================
# ROUTES
# ============================================================

@router.get("/concept-map", response_model=ConceptMap)
async def concept_map(
    query: str = Query(..., min_length=1, description="Semantic search query"),
    user_id: UUID = Query(..., description="User requesting the map"),
    token: str = Depends(extract_room_token),
    limit: int = Query(20, ge=1, le=100, description="Max seed nodes"),
    db=Depends(_get_db),
):
    """
    Build a concept map across all rooms the user participates in.

    Combines vector similarity search (seed nodes) with graph edge
    traversal (connections between those nodes).
    """
    await _verify_token(token, db)
    await _verify_user_membership(user_id, db)

    engine = KnowledgeGraphEngine(db)
    return await engine.get_concept_map(user_id=user_id, query=query, limit=limit)


@router.get("/memories/{memory_id}/provenance", response_model=IdeaProvenance)
async def memory_provenance(
    memory_id: UUID,
    token: str = Depends(extract_room_token),
    db=Depends(_get_db),
):
    """
    Trace a memory back to its origins: version history, source message,
    thread fork chain, and originating room.
    """
    await _verify_token(token, db)

    # Verify memory exists and user has access via token
    mem_row = await db.fetchrow(
        """SELECT m.room_id FROM memories m
           JOIN rooms r ON m.room_id = r.id
           WHERE m.id = $1 AND r.token = $2""",
        memory_id, token
    )
    if not mem_row:
        raise HTTPException(status_code=404, detail="Memory not found or access denied")

    engine = KnowledgeGraphEngine(db)
    try:
        return await engine.trace_idea_provenance(memory_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/rooms/{room_id}/contributions", response_model=ContributionGraph)
async def room_contributions(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    db=Depends(_get_db),
):
    """
    Get contribution statistics for all participants in a room:
    memories created, memories cited, total messages.
    """
    await _verify_room_access(room_id, token, db)

    engine = KnowledgeGraphEngine(db)
    return await engine.get_contribution_graph(room_id)


@router.get("/memories/{memory_id}/connections", response_model=list[GraphNode])
async def memory_connections(
    memory_id: UUID,
    token: str = Depends(extract_room_token),
    max_depth: int = Query(2, ge=1, le=5, description="Max traversal depth"),
    db=Depends(_get_db),
):
    """
    Find memories connected to the given one via graph edges
    (references, same-thread, forks) and semantic similarity.
    """
    await _verify_token(token, db)

    # Verify memory exists and user has access
    mem_row = await db.fetchrow(
        """SELECT m.room_id FROM memories m
           JOIN rooms r ON m.room_id = r.id
           WHERE m.id = $1 AND r.token = $2""",
        memory_id, token
    )
    if not mem_row:
        raise HTTPException(status_code=404, detail="Memory not found or access denied")

    engine = KnowledgeGraphEngine(db)
    return await engine.get_connected_memories(memory_id, max_depth=max_depth)


@router.post("/refresh")
async def refresh_graph(
    db=Depends(_get_db),
):
    """
    Refresh the knowledge graph materialized view.

    Call this after bulk data changes to ensure the graph
    reflects the latest state. Gracefully handles the case
    where the materialized view hasn't been created yet.
    """
    engine = KnowledgeGraphEngine(db)
    await engine.refresh()
    return {"status": "refreshed"}
