# api/reading_relay.py — the human Accept that files a drafted reading into
# the room's library.
#
# The save_reading tool (llm/tools.py) performs NO write: it validates a
# proposal and the orchestrator hoists it to messages.metadata.reading_proposal.
# This endpoint is the only write path — a room member taps Accept, we
# re-fetch the page through the defuddle sidecar (the library files the page,
# not the model's memory of it), and mark the proposal accepted so a second
# tap is a conflict, not a duplicate.

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from llm import defuddle_client as dc
from llm import reading as reading_mod

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reading"])

_db_pool = None


def set_reading_relay_db_pool(pool):
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


class AcceptReadingRequest(BaseModel):
    message_id: UUID


@router.post("/rooms/{room_id}/reading/accept")
async def accept_reading(
    room_id: UUID,
    request: AcceptReadingRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """File a drafted reading into the library. The human tap IS the write."""
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
    proposal = metadata.get("reading_proposal") if isinstance(metadata, dict) else None
    if not isinstance(proposal, dict):
        raise HTTPException(
            status_code=404, detail="This message carries no reading draft"
        )
    if proposal.get("accepted"):
        raise HTTPException(status_code=409, detail="Reading already filed")

    # Metadata is a document, not a trust boundary — re-validate at the write.
    url = str(proposal.get("url") or "").strip()
    summary = str(proposal.get("summary") or "").strip()
    if not url.startswith(("http://", "https://")) or not summary or len(summary) > 1000:
        raise HTTPException(status_code=422, detail="The stored draft is malformed")
    claims = proposal.get("key_claims")
    claims = [str(c) for c in claims][:10] if isinstance(claims, list) else []

    # The library files the page, not the model's memory of it.
    try:
        article = await dc.extract_article(url)
    except dc.DefuddleError as e:
        # The proposal stays unaccepted, so a retry once the sidecar recovers
        # is a fresh accept, not a conflict.
        logger.warning("reading relay re-fetch failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"article extractor refused the fetch: {e}"
        )
    if not isinstance(article, dict) or not str(article.get("content") or "").strip():
        raise HTTPException(
            status_code=422, detail="The URL no longer yields a readable article"
        )

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

    await db.execute(
        """UPDATE messages
           SET metadata = jsonb_set(metadata, '{reading_proposal,accepted}', 'true'::jsonb)
           WHERE id = $1""",
        request.message_id,
    )
    return saved
