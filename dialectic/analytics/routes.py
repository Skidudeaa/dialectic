# analytics/routes.py — REST API for conversation analytics
"""
ARCHITECTURE: FastAPI router with read-only analytics endpoints.
WHY: Separate router keeps analytics concerns decoupled from core messaging.
TRADEOFF: Requires db pool injection from main.py (same pattern as auth module).
"""

import logging
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from api.token_utils import extract_room_token

from analytics.analyzer import ConversationAnalyzer, ThreadAnalytics, RoomAnalytics
from analytics.dna import ConversationDNA

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

_db_pool = None


def set_analytics_db_pool(pool):
    """Set the database pool for analytics routes. Called by main.py at startup."""
    global _db_pool
    _db_pool = pool


async def get_db():
    """Get a database connection from the pool."""
    if _db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available"
        )
    async with _db_pool.acquire() as conn:
        yield conn


# ============================================================
# AUTH HELPERS
# ============================================================

async def _verify_room_token(room_id: UUID, token: str, db: asyncpg.Connection) -> None:
    """
    Verify room token for analytics access.

    ARCHITECTURE: Duplicates verify_room_token from main.py to avoid circular imports.
    WHY: Analytics routes are imported by main.py, so cannot import from it.
    TRADEOFF: Small duplication vs import complexity.
    """
    row = await db.fetchrow(
        "SELECT 1 FROM rooms WHERE id = $1 AND token = $2",
        room_id, token
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")


async def _verify_thread_access(
    thread_id: UUID, token: str, db: asyncpg.Connection
) -> UUID:
    """Verify token grants access to the thread's room. Returns room_id."""
    thread_row = await db.fetchrow(
        "SELECT room_id FROM threads WHERE id = $1", thread_id
    )
    if not thread_row:
        raise HTTPException(status_code=404, detail="Thread not found")

    room_id = thread_row['room_id']
    await _verify_room_token(room_id, token, db)
    return room_id


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/threads/{thread_id}", response_model=ThreadAnalytics)
async def get_thread_analytics(
    thread_id: UUID,
    token: str = Depends(extract_room_token),
    db=Depends(get_db),
):
    """
    Compute analytics for a single thread.

    Returns message counts, type distribution, argument density,
    speaker balance, fork count, memory operations, and DNA fingerprint.
    """
    await _verify_thread_access(thread_id, token, db)

    analyzer = ConversationAnalyzer(db)
    return await analyzer.analyze_thread(thread_id)


@router.get("/rooms/{room_id}", response_model=RoomAnalytics)
async def get_room_analytics(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    db=Depends(get_db),
):
    """
    Aggregate analytics across all threads in a room.

    Returns room-level rollups of message counts, type distribution,
    argument density, and a weighted-average DNA fingerprint.
    """
    await _verify_room_token(room_id, token, db)

    analyzer = ConversationAnalyzer(db)
    return await analyzer.analyze_room(room_id)


@router.get("/threads/{thread_id}/dna")
async def get_thread_dna(
    thread_id: UUID,
    token: str = Depends(extract_room_token),
    db=Depends(get_db),
):
    """
    Compute the 6-dimensional DNA fingerprint for a thread.

    Returns tension, velocity, asymmetry, depth, divergence,
    memory_density plus the derived fingerprint hex and archetype label.
    """
    await _verify_thread_access(thread_id, token, db)

    analyzer = ConversationAnalyzer(db)
    dna = await analyzer.compute_dna(thread_id)

    return {
        "thread_id": str(dna.thread_id),
        "computed_at": dna.computed_at.isoformat(),
        "tension": dna.tension,
        "velocity": dna.velocity,
        "asymmetry": dna.asymmetry,
        "depth": dna.depth,
        "divergence": dna.divergence,
        "memory_density": dna.memory_density,
        "fingerprint": dna.fingerprint,
        "archetype": dna.archetype,
    }


@router.get("/rooms/{room_id}/dna")
async def get_room_dna(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    db=Depends(get_db),
):
    """
    Compute weighted-average DNA fingerprint across all threads in a room.

    Returns the same 6 dimensions plus fingerprint and archetype,
    weighted by message count per thread.
    """
    await _verify_room_token(room_id, token, db)

    analyzer = ConversationAnalyzer(db)
    dna = await analyzer.compute_room_dna(room_id)

    return {
        "room_id": str(dna.thread_id),
        "computed_at": dna.computed_at.isoformat(),
        "tension": dna.tension,
        "velocity": dna.velocity,
        "asymmetry": dna.asymmetry,
        "depth": dna.depth,
        "divergence": dna.divergence,
        "memory_density": dna.memory_density,
        "fingerprint": dna.fingerprint,
        "archetype": dna.archetype,
    }
