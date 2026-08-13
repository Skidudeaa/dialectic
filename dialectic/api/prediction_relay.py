# api/prediction_relay.py — the human Accept that turns a drafted prediction
# into a logged one.
#
# The draft_prediction tool (llm/tools.py) performs NO write: it validates a
# proposal and the orchestrator hoists it to messages.metadata.proposal.
# This endpoint is the only write path — a room member taps Accept, and we
# relay the proposal to tradingDesk's prediction tracker as the dialectic
# service principal (TRADINGDESK_USER/TRADINGDESK_PASSWORD), then mark the
# proposal accepted so a second tap is a conflict, not a duplicate.

import logging
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from llm import tradingdesk_client as td

logger = logging.getLogger(__name__)

router = APIRouter(tags=["predictions"])

_db_pool = None


def set_prediction_relay_db_pool(pool):
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


class AcceptPredictionRequest(BaseModel):
    message_id: UUID


@router.post("/rooms/{room_id}/predictions/accept")
async def accept_prediction(
    room_id: UUID,
    request: AcceptPredictionRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """Log a drafted prediction to tradingDesk. The human tap IS the write."""
    await _verify_room_token(room_id, token, db)
    await _verify_room_member(room_id, current_user.user_id, db)

    row = await db.fetchrow(
        """SELECT m.id, m.metadata
           FROM messages m
           JOIN threads t ON t.id = m.thread_id
           WHERE m.id = $1 AND t.room_id = $2 AND NOT m.is_deleted""",
        request.message_id, room_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found in this room")

    metadata = row["metadata"]
    proposal = metadata.get("proposal") if isinstance(metadata, dict) else None
    if not isinstance(proposal, dict):
        raise HTTPException(
            status_code=404, detail="This message carries no prediction draft"
        )
    if proposal.get("accepted"):
        raise HTTPException(
            status_code=409, detail="Prediction already logged to tradingDesk"
        )

    # The tool validated these at draft time, but metadata is a document, not
    # a trust boundary — re-check at the write. Body shape is tradingDesk's
    # PredictionCreate (trading/web/models.py).
    statement = str(proposal.get("statement") or "").strip()
    deadline = str(proposal.get("deadline") or "").strip()
    malformed = not statement
    try:
        confidence = float(proposal.get("confidence"))
        malformed = malformed or not 0.0 <= confidence <= 1.0
        date.fromisoformat(deadline)
    except (TypeError, ValueError):
        malformed = True
    if malformed:
        raise HTTPException(
            status_code=422, detail="The stored draft is malformed"
        )

    body = {
        "statement": statement,
        "confidence": confidence,
        "deadline": deadline,
        "tags": ["dialectic"],
    }
    book = str(proposal.get("linked_book_id") or "").strip()
    if book:
        body["linked_book_id"] = book

    try:
        created = await td.post("/api/predictions", json_body=body)
    except td.TradingDeskError as e:
        # The proposal stays unaccepted, so a retry once the desk recovers is
        # a fresh accept, not a conflict.
        logger.warning("prediction relay to tradingDesk failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"tradingDesk refused the prediction: {e}"
        )

    await db.execute(
        """UPDATE messages
           SET metadata = jsonb_set(metadata, '{proposal,accepted}', 'true'::jsonb)
           WHERE id = $1""",
        request.message_id,
    )
    return created


class ResolveAcceptRequest(BaseModel):
    verdict: Literal["correct", "incorrect"]


@router.post("/rooms/{room_id}/predictions/{prediction_id}/resolve-accept")
async def resolve_accept(
    room_id: UUID,
    prediction_id: str,
    request: ResolveAcceptRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """Relay the human's verdict on a deadline proposal to tradingDesk.

    The prediction_watch job only PROPOSES (metadata.resolution_proposal);
    this tap IS the resolution write. The card's two buttons both land here —
    the human's verdict is what's relayed, so a human who disagrees with the
    machine's proposed verdict still settles the prediction their way. The
    server only requires a valid verdict literal and a live proposal.
    """
    await _verify_room_token(room_id, token, db)
    await _verify_room_member(room_id, current_user.user_id, db)

    row = await db.fetchrow(
        """SELECT m.id, m.metadata
           FROM messages m
           JOIN threads t ON t.id = m.thread_id
           WHERE t.room_id = $1 AND NOT m.is_deleted
           AND m.metadata->>'source' = 'prediction_watch'
           AND m.metadata->'resolution_proposal'->>'prediction_id' = $2
           ORDER BY m.created_at DESC LIMIT 1""",
        room_id, prediction_id,
    )
    if not row:
        raise HTTPException(
            status_code=404, detail="No resolution proposal for this prediction"
        )

    metadata = row["metadata"]
    proposal = metadata.get("resolution_proposal") if isinstance(metadata, dict) else None
    if not isinstance(proposal, dict):
        raise HTTPException(
            status_code=404, detail="No resolution proposal for this prediction"
        )
    if proposal.get("accepted"):
        raise HTTPException(
            status_code=409, detail="Resolution already logged to tradingDesk"
        )

    try:
        resolved = await td.post(
            f"/api/predictions/{prediction_id}/resolve",
            json_body={"resolution": request.verdict},
        )
    except td.TradingDeskError as e:
        # The proposal stays unaccepted, so a retry once the desk recovers is
        # a fresh accept, not a conflict.
        logger.warning("resolution relay to tradingDesk failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"tradingDesk refused the resolution: {e}"
        )

    await db.execute(
        """UPDATE messages
           SET metadata = jsonb_set(
               metadata, '{resolution_proposal,accepted}', 'true'::jsonb)
           WHERE id = $1""",
        row["id"],
    )
    return resolved
