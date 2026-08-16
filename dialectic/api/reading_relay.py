# api/reading_relay.py — the human Accept that files a drafted reading into
# the room's library.
#
# The save_reading tool (llm/tools.py) performs NO write: it validates a
# proposal and the orchestrator hoists it to messages.metadata.reading_proposal.
# This endpoint is the only write path — a room member taps Accept, we
# re-fetch the page through the defuddle sidecar (the library files the page,
# not the model's memory of it), and atomically record the filing plus
# acceptance so later taps replay without duplicating.

import logging
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.external_operations import (
    OperationBusy,
    claim_operation,
    fail_operation,
    succeed_operation,
)
from api.token_utils import extract_room_token
from llm import defuddle_client as dc
from llm import reading as reading_mod

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reading"])

_db_pool = None


def set_reading_relay_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("reading relay database pool is not initialized")
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


class AcceptReadingRequest(BaseModel):
    message_id: UUID


@router.post("/rooms/{room_id}/reading/accept")
async def accept_reading(
    room_id: UUID,
    request: AcceptReadingRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """File a drafted reading into the library. The human tap IS the write."""
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
    proposal = metadata.get("reading_proposal") if isinstance(metadata, dict) else None
    if not isinstance(proposal, dict):
        raise HTTPException(
            status_code=404, detail="This message carries no reading draft"
        )
    # Metadata is a document, not a trust boundary — re-validate at the write.
    url = str(proposal.get("url") or "").strip()
    summary = str(proposal.get("summary") or "").strip()
    if not url.startswith(("http://", "https://")) or not summary or len(summary) > 1000:
        raise HTTPException(status_code=422, detail="The stored draft is malformed")
    claims = proposal.get("key_claims")
    claims = [str(c) for c in claims][:10] if isinstance(claims, list) else []

    operation_key = f"reading:{request.message_id}:reading_proposal"
    try:
        operation = await claim_operation(
            pool,
            room_id=room_id,
            kind="reading",
            operation_key=operation_key,
            initiated_by=current_user.user_id,
            source_message_id=request.message_id,
            proposal_slot="reading_proposal",
        )
    except (OperationBusy, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if operation.status == "succeeded":
        if operation.external_result is None:
            raise RuntimeError("Succeeded external operation has no recorded result")
        return operation.external_result
    if proposal.get("accepted"):
        await fail_operation(pool, operation, error="proposal was already accepted")
        raise HTTPException(status_code=409, detail="Reading already filed")

    # The library files the page, not the model's memory of it.
    try:
        article = await dc.extract_article(url)
    except dc.DefuddleError as e:
        await fail_operation(pool, operation, error=str(e))
        logger.warning("reading relay re-fetch failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"article extractor refused the fetch: {e}"
        ) from e
    if not isinstance(article, dict) or not str(article.get("content") or "").strip():
        await fail_operation(
            pool,
            operation,
            error="URL no longer yields a readable article",
        )
        raise HTTPException(
            status_code=422, detail="The URL no longer yields a readable article"
        )

    try:
        async with pool.acquire() as db:
            async with db.transaction():
                saved = await reading_mod.save_reading(
                    db,
                    room_id=room_id,
                    article=article,
                    summary=summary,
                    key_claims=claims,
                    source="proposal",
                    source_message_id=request.message_id,
                    saved_by_user_id=current_user.user_id,
                )
                await succeed_operation(db, operation, result=saved)
    except Exception as exc:
        await fail_operation(pool, operation, error=str(exc))
        raise
    return saved
