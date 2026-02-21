# stakes/routes.py — REST endpoints for commitments and predictions

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
import logging

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from .manager import CommitmentManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stakes", tags=["stakes"])

_db_pool = None


def set_stakes_db_pool(pool):
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


async def _verify_room_token(room_id: UUID, token: str, db) -> None:
    row = await db.fetchrow(
        "SELECT 1 FROM rooms WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")


async def _verify_room_member(room_id: UUID, user_id: UUID, db) -> None:
    row = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=403, detail="User is not a member of this room")


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class CreateCommitmentRequest(BaseModel):
    claim: str
    resolution_criteria: str
    category: str = "prediction"
    thread_id: Optional[UUID] = None
    source_message_id: Optional[UUID] = None
    deadline: Optional[datetime] = None
    initial_confidence: Optional[float] = Field(None, ge=0, le=1)


class RecordConfidenceRequest(BaseModel):
    confidence: float = Field(..., ge=0, le=1)
    reasoning: Optional[str] = None


class ResolveRequest(BaseModel):
    resolution: str  # 'correct' | 'incorrect' | 'partial' | 'voided'
    resolution_notes: Optional[str] = None


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/rooms/{room_id}/commitments")
async def create_commitment(
    room_id: UUID,
    request: CreateCommitmentRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """
    Create a new prediction or commitment.

    ARCHITECTURE: REST endpoint for explicit commitment creation.
    WHY: Users can formalize predictions from conversation or create them directly.
    """
    await _verify_room_token(room_id, token, db)
    await _verify_room_member(room_id, user_id, db)

    if request.category not in ("prediction", "commitment", "bet"):
        raise HTTPException(status_code=400, detail="Invalid category")

    mgr = CommitmentManager(db)
    result = await mgr.create_commitment(
        room_id=room_id,
        claim=request.claim,
        resolution_criteria=request.resolution_criteria,
        created_by_user_id=user_id,
        thread_id=request.thread_id,
        source_message_id=request.source_message_id,
        deadline=request.deadline,
        category=request.category,
        initial_confidence=request.initial_confidence,
    )

    # Serialize UUIDs and datetimes for JSON response
    return _serialize(result)


@router.get("/rooms/{room_id}/commitments")
async def list_commitments(
    room_id: UUID,
    token: str = Query(...),
    status: Optional[str] = None,
    db=Depends(get_db),
):
    """
    List commitments in a room.

    ARCHITECTURE: Filterable by status to support active/resolved/all views.
    WHY: Room commitment board needs flexible querying.
    """
    await _verify_room_token(room_id, token, db)

    mgr = CommitmentManager(db)
    commitments = await mgr.get_room_commitments(room_id, status=status)
    return [_serialize(c) for c in commitments]


@router.get("/commitments/{commitment_id}")
async def get_commitment(
    commitment_id: UUID,
    token: str = Query(...),
    db=Depends(get_db),
):
    """Get a commitment with full confidence history."""
    mgr = CommitmentManager(db)
    try:
        c = await mgr.get_commitment(commitment_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Commitment not found")

    # Verify room token
    await _verify_room_token(c["room_id"], token, db)
    return _serialize(c)


@router.post("/commitments/{commitment_id}/confidence")
async def record_confidence(
    commitment_id: UUID,
    request: RecordConfidenceRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """
    Record your confidence level on a commitment.

    ARCHITECTURE: Append-only confidence history per participant.
    WHY: Tracking confidence changes over time reveals epistemic evolution.
    """
    # Verify room membership through the commitment's room
    row = await db.fetchrow(
        "SELECT room_id FROM commitments WHERE id = $1", commitment_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Commitment not found")

    await _verify_room_token(row["room_id"], token, db)
    await _verify_room_member(row["room_id"], user_id, db)

    mgr = CommitmentManager(db)
    try:
        result = await mgr.record_confidence(
            commitment_id=commitment_id,
            user_id=user_id,
            confidence=request.confidence,
            reasoning=request.reasoning,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _serialize(result)


@router.post("/commitments/{commitment_id}/resolve")
async def resolve_commitment(
    commitment_id: UUID,
    request: ResolveRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """
    Resolve a commitment.

    ARCHITECTURE: Resolution triggers calibration score updates.
    WHY: Accountability requires closure — predictions must be scored.
    """
    row = await db.fetchrow(
        "SELECT room_id FROM commitments WHERE id = $1", commitment_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Commitment not found")

    await _verify_room_token(row["room_id"], token, db)
    await _verify_room_member(row["room_id"], user_id, db)

    mgr = CommitmentManager(db)
    try:
        result = await mgr.resolve(
            commitment_id=commitment_id,
            resolution=request.resolution,
            resolved_by_user_id=user_id,
            resolution_notes=request.resolution_notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _serialize(result)


@router.get("/rooms/{room_id}/calibration")
async def get_calibration(
    room_id: UUID,
    token: str = Query(...),
    user_id: Optional[UUID] = None,
    db=Depends(get_db),
):
    """
    Get calibration curve for a user or room.

    ARCHITECTURE: Computes bucketed accuracy for confidence vs outcomes.
    WHY: Calibration is the gold standard for prediction quality — shows
         whether 70% confident predictions are correct ~70% of the time.
    """
    await _verify_room_token(room_id, token, db)

    mgr = CommitmentManager(db)
    return await mgr.get_calibration(user_id=user_id, room_id=room_id)


@router.get("/rooms/{room_id}/commitments/expiring")
async def get_expiring(
    room_id: UUID,
    token: str = Query(...),
    days: int = Query(7, ge=1, le=90),
    db=Depends(get_db),
):
    """
    Get commitments with approaching deadlines.

    ARCHITECTURE: Deadline-based filtering for urgency surfacing.
    WHY: Predictions should be resolved, not forgotten.
    """
    await _verify_room_token(room_id, token, db)

    mgr = CommitmentManager(db)
    expiring = await mgr.get_expiring_soon(room_id, days=days)
    return [_serialize(c) for c in expiring]


# ============================================================
# HELPERS
# ============================================================

def _serialize(obj: dict) -> dict:
    """Serialize UUIDs and datetimes for JSON response."""
    result = {}
    for key, value in obj.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [_serialize(item) if isinstance(item, dict) else item for item in value]
        elif isinstance(value, dict):
            result[key] = _serialize(value)
        else:
            result[key] = value
    return result
