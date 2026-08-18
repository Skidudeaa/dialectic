# api/prediction_relay.py — the human Accept that turns a drafted prediction
# into a logged one.
#
# The draft_prediction tool (llm/tools.py) performs NO write: it validates a
# proposal and the orchestrator hoists it to messages.metadata.proposal.
# This endpoint is the only write path — a room member taps Accept, and we
# relay the proposal to tradingDesk's prediction tracker as the dialectic
# service principal (TRADINGDESK_USER/TRADINGDESK_PASSWORD), then atomically
# record the acceptance and response so later taps replay without duplicating.

import logging
from datetime import date
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.external_operations import (
    ExternalOperation,
    OperationBusy,
    claim_operation,
    fail_operation,
    succeed_operation,
)
from api.token_utils import extract_room_token
from llm import tradingdesk_client as td

logger = logging.getLogger(__name__)

router = APIRouter(tags=["predictions"])

_db_pool = None


def set_prediction_relay_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("prediction relay database pool is not initialized")
    return _db_pool


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


async def _claim(
    pool: asyncpg.Pool,
    *,
    room_id: UUID,
    kind: str,
    operation_key: str,
    user_id: UUID,
    message_id: UUID,
    proposal_slot: str,
) -> ExternalOperation:
    try:
        return await claim_operation(
            pool,
            room_id=room_id,
            kind=kind,
            operation_key=operation_key,
            initiated_by=user_id,
            source_message_id=message_id,
            proposal_slot=proposal_slot,
        )
    except (OperationBusy, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _replayed_result(operation: ExternalOperation) -> dict | None:
    if operation.status != "succeeded":
        return None
    if operation.external_result is None:
        raise RuntimeError("Succeeded external operation has no recorded result")
    return operation.external_result


class AcceptPredictionRequest(BaseModel):
    message_id: UUID


@router.post("/rooms/{room_id}/predictions/accept")
async def accept_prediction(
    room_id: UUID,
    request: AcceptPredictionRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Log a drafted prediction to tradingDesk. The human tap IS the write."""
    async with pool.acquire() as db:
        await _verify_room_token(room_id, token, db)
        await _verify_room_member(room_id, current_user.user_id, db)
        row = await db.fetchrow(
            """SELECT m.id, m.metadata
               FROM messages m
               JOIN threads t ON t.id = m.thread_id
               WHERE m.id = $1 AND t.room_id = $2 AND NOT m.is_deleted""",
            request.message_id,
            room_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found in this room")

    metadata = row["metadata"]
    proposal = metadata.get("proposal") if isinstance(metadata, dict) else None
    if not isinstance(proposal, dict):
        raise HTTPException(
            status_code=404, detail="This message carries no prediction draft"
        )
    # The tool validated these at draft time, but metadata is a document, not
    # a trust boundary — re-check at the write. Body shape is tradingDesk's
    # PredictionCreate (trading/web/models.py).
    statement = str(proposal.get("statement") or "").strip()
    deadline = str(proposal.get("deadline") or "").strip()
    malformed = not statement
    confidence = -1.0
    try:
        confidence = float(str(proposal.get("confidence")))
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
        # Claims-ledger provenance. Stamped HERE rather than in the
        # draft_prediction tool because draft_prediction is the ONLY writer
        # of metadata.proposal — authorship is a property of this path, not
        # of the payload, and the human tap authorizes the write without
        # becoming its author.
        "source_type": "llm",
        "source_label": "Claude",
    }
    book = str(proposal.get("linked_book_id") or "").strip()
    if book:
        body["linked_book_id"] = book

    operation_key = f"prediction:{request.message_id}:proposal"
    operation = await _claim(
        pool,
        room_id=room_id,
        kind="prediction",
        operation_key=operation_key,
        user_id=current_user.user_id,
        message_id=request.message_id,
        proposal_slot="proposal",
    )
    replayed = _replayed_result(operation)
    if replayed is not None:
        return replayed
    if proposal.get("accepted"):
        await fail_operation(pool, operation, error="proposal was already accepted")
        raise HTTPException(
            status_code=409, detail="Prediction already logged to tradingDesk"
        )
    body["source_key"] = operation_key

    try:
        created = await td.post("/api/predictions", json_body=body)
    except td.TradingDeskError as e:
        await fail_operation(pool, operation, error=str(e))
        logger.warning("prediction relay to tradingDesk failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"tradingDesk refused the prediction: {e}"
        ) from e
    if not isinstance(created, dict):
        await fail_operation(pool, operation, error="tradingDesk returned a non-object")
        raise HTTPException(
            status_code=502,
            detail="tradingDesk returned an invalid prediction",
        )

    async with pool.acquire() as db:
        async with db.transaction():
            await succeed_operation(db, operation, result=created)
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
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Relay the human's verdict on a deadline proposal to tradingDesk.

    The prediction_watch job only PROPOSES (metadata.resolution_proposal);
    this tap IS the resolution write. The card's two buttons both land here —
    the human's verdict is what's relayed, so a human who disagrees with the
    machine's proposed verdict still settles the prediction their way. The
    server only requires a valid verdict literal and a live proposal.
    """
    async with pool.acquire() as db:
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
            room_id,
            prediction_id,
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
    operation_key = f"resolution:{row['id']}:resolution_proposal"
    operation = await _claim(
        pool,
        room_id=room_id,
        kind="resolution",
        operation_key=operation_key,
        user_id=current_user.user_id,
        message_id=row["id"],
        proposal_slot="resolution_proposal",
    )
    replayed = _replayed_result(operation)
    if replayed is not None:
        return replayed
    if proposal.get("accepted"):
        await fail_operation(pool, operation, error="proposal was already accepted")
        raise HTTPException(
            status_code=409, detail="Resolution already logged to tradingDesk"
        )

    try:
        resolved = await td.post(
            f"/api/predictions/{prediction_id}/resolve",
            json_body={"resolution": request.verdict, "source_key": operation_key},
        )
    except td.TradingDeskError as e:
        await fail_operation(pool, operation, error=str(e))
        logger.warning("resolution relay to tradingDesk failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"tradingDesk refused the resolution: {e}"
        ) from e
    if not isinstance(resolved, dict):
        await fail_operation(pool, operation, error="tradingDesk returned a non-object")
        raise HTTPException(
            status_code=502,
            detail="tradingDesk returned an invalid resolution",
        )

    async with pool.acquire() as db:
        async with db.transaction():
            await succeed_operation(db, operation, result=resolved)
    return resolved
