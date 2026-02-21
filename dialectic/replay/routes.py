# replay/routes.py — REST + SSE endpoints for event replay

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse

from replay.engine import EventReplayEngine
from replay.models import RoomSnapshot, StateDiff, LLMDecisionReplay, TimelineBucket


router = APIRouter(prefix="/replay", tags=["replay"])

_db_pool: Optional[asyncpg.Pool] = None


def set_replay_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def _get_db():
    """Dependency: acquire connection from module-level pool."""
    if not _db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    async with _db_pool.acquire() as conn:
        yield conn


async def _verify_room_token(room_id: UUID, token: str, db: asyncpg.Connection):
    """Verify room token. Raises 401 if invalid."""
    row = await db.fetchrow(
        "SELECT id FROM rooms WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")


# ============================================================
# GET /replay/rooms/{room_id}/state
# ============================================================

@router.get("/rooms/{room_id}/state")
async def get_state_at(
    room_id: UUID,
    at_sequence: int = Query(..., description="Event sequence to materialize state at"),
    token: str = Query(...),
    db=Depends(_get_db),
):
    """
    Get room state at a specific event sequence.

    ARCHITECTURE: Replays all events up to target_sequence, returns materialized snapshot.
    WHY: Temporal queries — "what did the room look like at event N?"
    """
    await _verify_room_token(room_id, token, db)

    engine = EventReplayEngine(db)
    snapshot = await engine.state_at(room_id, at_sequence)

    return snapshot.model_dump(mode="json")


# ============================================================
# GET /replay/rooms/{room_id}/stream (SSE)
# ============================================================

@router.get("/rooms/{room_id}/stream")
async def replay_stream(
    room_id: UUID,
    token: str = Query(...),
    start: Optional[int] = Query(None, description="Start sequence (inclusive)"),
    end: Optional[int] = Query(None, description="End sequence (inclusive)"),
    speed: float = Query(1.0, ge=0.1, le=20.0, description="Playback speed multiplier"),
    db=Depends(_get_db),
):
    """
    SSE stream of events for replay playback.

    ARCHITECTURE: Server-Sent Events with timing delays between events.
    WHY: Recreates real-time pacing for playback UI.
    TRADEOFF: Server holds connection open — bounded by event count and max delay cap.
    """
    await _verify_room_token(room_id, token, db)

    async def generate():
        try:
            engine = EventReplayEngine(db)
            async for replay_event in engine.replay_stream(room_id, start, end, speed):
                if replay_event.delay_ms > 0:
                    await asyncio.sleep(replay_event.delay_ms / 1000.0)

                data = json.dumps(replay_event.model_dump(mode="json"), default=str)
                yield f"data: {data}\n\n"

            yield 'data: {"type": "replay_complete"}\n\n'
        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected mid-stream — normal for SSE
            return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# GET /replay/rooms/{room_id}/diff
# ============================================================

@router.get("/rooms/{room_id}/diff")
async def get_diff(
    room_id: UUID,
    from_seq: int = Query(..., description="Start sequence"),
    to_seq: int = Query(..., description="End sequence"),
    token: str = Query(...),
    db=Depends(_get_db),
):
    """
    Get changes between two event sequences.

    ARCHITECTURE: Scans events in range and categorizes mutations.
    WHY: Enables "what changed?" queries for catch-up and auditing.
    """
    await _verify_room_token(room_id, token, db)

    engine = EventReplayEngine(db)
    diff = await engine.diff_states(room_id, from_seq, to_seq)

    return diff.model_dump(mode="json")


# ============================================================
# GET /replay/messages/{message_id}/llm-context
# ============================================================

@router.get("/messages/{message_id}/llm-context")
async def get_llm_decision(
    message_id: UUID,
    token: str = Query(...),
    db=Depends(_get_db),
):
    """
    Reconstruct the LLM's decision context for a specific message.

    ARCHITECTURE: Traces back to exact inputs that produced an LLM response.
    WHY: Transparency — understand why the LLM said what it said.
    """
    # Verify the message exists and get its room for token check
    msg = await db.fetchrow("SELECT * FROM messages WHERE id = $1", message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    thread = await db.fetchrow("SELECT room_id FROM threads WHERE id = $1", msg["thread_id"])
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    await _verify_room_token(thread["room_id"], token, db)

    engine = EventReplayEngine(db)
    try:
        decision = await engine.get_llm_decision_context(message_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return decision.model_dump(mode="json")


# ============================================================
# GET /replay/rooms/{room_id}/timeline
# ============================================================

@router.get("/rooms/{room_id}/timeline")
async def get_timeline(
    room_id: UUID,
    token: str = Query(...),
    buckets: int = Query(50, ge=10, le=200, description="Number of time buckets"),
    db=Depends(_get_db),
):
    """
    Get event timeline with density/heat map data for scrubber UI.

    ARCHITECTURE: Bucketized event counts + type distribution.
    WHY: Enables timeline visualization — dense red = intense, sparse blue = quiet.
    TRADEOFF: Fixed bucket count — simple and predictable for UI rendering.
    """
    await _verify_room_token(room_id, token, db)

    engine = EventReplayEngine(db)
    timeline = await engine.get_timeline(room_id, bucket_count=buckets)

    return timeline
