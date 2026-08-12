# api/thesis_relay.py — the Create Thesis flow: a room births its book.
#
# ARCHITECTURE: Dialectic's PWA has no thesis-authoring surface of its own —
# the Thesis Builder + DAG canvas live on tradingDesk's deep surface by
# design (fusion plan, kept indefinitely). What Dialectic owns is the
# BINDING: a room member names a thesis, and this endpoint mints the book on
# tradingDesk already bound to the room, registers the room's push token,
# and records the link locally. From that moment the coordinator's next
# cycle pushes the first snapshot, and the deep-surface builder is where the
# DAG gets drawn.
#
# Relay order is deliberate — each step's failure leaves a consistent world:
#   1. register the room token on td's bridge  (idempotent; a leftover
#      registration with no book simply never pushes)
#   2. create the book, born with meta.dialecticRoomId  (fails → nothing
#      links, retry is fresh)
#   3. link rooms.linked_book_id + log THESIS_CREATED  (local, last, so a
#      td failure can never leave Dialectic pointing at a book that does
#      not exist)

import logging
from uuid import UUID, uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from llm import tradingdesk_client as td
from llm.thesis_drafter import DraftError, draft_thesis_graph
from models import EventType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trading"])

_db_pool = None


def set_thesis_relay_db_pool(pool):
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


async def _verify_room_member(room_id: UUID, user_id: UUID, db) -> None:
    row = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=403, detail="User is not a member of this room")


class CreateThesisRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    claim: str = Field(default="", max_length=2000)
    monthly_budget: int = Field(default=5000, ge=0, le=10_000_000)
    # An accepted draft rides along here (builder format — see
    # llm/thesis_drafter.py). Shape validation is tradingDesk's builder
    # model's job; these caps only bound the payload. Room members hold
    # the same trust the desk's own Builder UI grants them.
    nodes: list[dict] = Field(default_factory=list, max_length=60)
    edges: list[dict] = Field(default_factory=list, max_length=100)


@router.post("/rooms/{room_id}/trading/thesis")
async def create_thesis(
    room_id: UUID,
    request: CreateThesisRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """Create a thesis book on tradingDesk, born bound to this room."""
    row = await db.fetchrow(
        "SELECT token, linked_book_id FROM rooms WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")
    await _verify_room_member(room_id, current_user.user_id, db)

    if row["linked_book_id"]:
        raise HTTPException(
            status_code=409,
            detail=f"This room is already bound to '{row['linked_book_id']}'",
        )

    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title must not be blank")

    # The verified room token IS the push credential — hand it to td so the
    # coordinator can deliver snapshots without a desk restart.
    try:
        await td.service_post(
            "/api/bridge/room-token",
            json_body={"room_id": str(room_id), "token": row["token"]},
        )
    except td.TradingDeskError as e:
        logger.warning("thesis create: token registration failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"tradingDesk refused the room token: {e}",
        )

    try:
        created = await td.post(
            "/api/thesis/builder/books",
            json_body={
                "meta": {
                    "title": title,
                    "claim": request.claim.strip(),
                    "monthlyBudget": request.monthly_budget,
                    "dialecticRoomId": str(room_id),
                },
                "nodes": request.nodes,
                "edges": request.edges,
            },
        )
    except td.TradingDeskError as e:
        # The token registration above is idempotent and harmless on its
        # own, so a retry after the desk recovers is a fresh create.
        logger.warning("thesis create: book creation failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"tradingDesk refused the thesis: {e}",
        )

    book_id = str((created or {}).get("id") or "").strip()
    if not book_id:
        logger.error("thesis create: td returned no book id: %r", created)
        raise HTTPException(
            status_code=502, detail="tradingDesk returned no book id"
        )

    await db.execute(
        "UPDATE rooms SET linked_book_id = $1 WHERE id = $2",
        book_id, room_id,
    )
    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), datetime.now(timezone.utc), EventType.THESIS_CREATED.value,
        room_id, current_user.user_id,
        {"book_id": book_id, "title": title},
    )

    logger.info(
        "thesis created: room %s -> book %s (%s)", room_id, book_id, title
    )
    return {"book_id": book_id, "title": title}


@router.post("/rooms/{room_id}/trading/thesis/draft")
async def draft_thesis(
    room_id: UUID,
    request: CreateThesisRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """Claude drafts the causal DAG for review — a proposal, never a write.

    Stateless on purpose: nothing is stored, nothing touches td. The human
    reviews the returned nodes/edges in the panel and, on Accept, sends
    them through create_thesis above — the tap is the write, exactly the
    draft_prediction trust shape. Same auth and same already-bound gate as
    create, so a draft can never be minted for a room that cannot take it.
    """
    row = await db.fetchrow(
        """SELECT token, linked_book_id, primary_provider, primary_model
           FROM rooms WHERE id = $1 AND token = $2""",
        room_id, token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")
    await _verify_room_member(room_id, current_user.user_id, db)

    if row["linked_book_id"]:
        raise HTTPException(
            status_code=409,
            detail=f"This room is already bound to '{row['linked_book_id']}'",
        )

    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title must not be blank")

    # The room's own primary model drafts — but only when it is an
    # Anthropic one, because the drafter speaks that provider directly.
    kwargs = {}
    if (row["primary_provider"] or "").lower() == "anthropic" and row["primary_model"]:
        kwargs["model"] = row["primary_model"]

    try:
        draft = await draft_thesis_graph(
            title, request.claim.strip(), request.monthly_budget, **kwargs
        )
    except DraftError as e:
        raise HTTPException(status_code=502, detail=str(e))

    logger.info(
        "thesis draft for room %s: %d nodes, %d edges",
        room_id, len(draft["nodes"]), len(draft["edges"]),
    )
    return draft
