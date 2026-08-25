# api/home_proposals.py — the cross-room proposal inbox for Home.
#
# ARCHITECTURE: aggregates two things that already exist rather than
# reimplementing either. Room selection reuses home_activity.py's own
# membership-intersection queries (imported, not copied — one copy of the
# privacy-sensitive SQL, not two that can drift). Per-room normalization
# reuses proposal_envelope.build_proposal_projection, the same function
# GET /rooms/{room_id}/workspace/proposals calls. This file only merges,
# labels by room, and sorts. Reads only — acceptance still goes through the
# relay that owns the write, same convention as api/workspace.py.
#
# WHY a plain function pair instead of a service class: HomeActivityService
# is a class because it carries a lot of per-room state across many queries.
# This is one merge over one existing per-room call in a loop; a class would
# be state with nothing to hold.

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from home_activity import _AUTHORIZE_SQL, _ELIGIBLE_SQL, HomeUnavailable
from proposal_envelope import build_proposal_projection

router = APIRouter(tags=["home"])

_db_pool = None


def set_home_proposals_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


class HomeProposalItem(BaseModel):
    id: str
    proposal_kind: str
    source_message_id: UUID
    room_id: UUID
    room_name: str
    branch_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    rationale: str
    payload: dict = {}
    status: str
    accepted_by: Optional[UUID] = None
    accepted_at: Optional[datetime] = None
    target_object: Optional[str] = None
    available_actions: list[str] = []


class HomeProposalsResponse(BaseModel):
    generated_at: datetime
    proposals: list[HomeProposalItem]


# proposal_envelope._actions() already draws the "needs a human now" line:
# only "proposed" ever offers accept/dismiss: every other status (accepted,
# dismissed, superseded, expired, failed) offers just inspect. Sorting on
# that same line rather than inventing a second one.
_NEEDS_ACTION_STATUS = "proposed"


async def _build_home_proposals(db, viewer_id: UUID) -> HomeProposalsResponse:
    generated_at = datetime.now(timezone.utc)

    # Same two queries home_activity.HomeActivityService._build uses to
    # resolve the caller's Home-shared rooms — imported so there is one copy
    # of the membership-intersection text, not a second that can drift.
    home = await db.fetchrow(_AUTHORIZE_SQL, viewer_id)
    if home is None:
        raise HomeUnavailable()
    rooms = await db.fetch(_ELIGIBLE_SQL, viewer_id, home["id"])

    items: list[HomeProposalItem] = []
    for room in rooms:
        projection = await build_proposal_projection(db, room["id"])
        for p in projection.proposals:
            items.append(HomeProposalItem(
                room_name=room["name"] or "Untitled room",
                **p.model_dump(),
            ))

    # Needs-a-human-now first, then newest first within each group.
    items.sort(key=lambda item: (
        0 if item.status == _NEEDS_ACTION_STATUS else 1,
        -item.created_at.timestamp(),
    ))
    return HomeProposalsResponse(generated_at=generated_at, proposals=items)


@router.get(
    "/users/me/home/proposals",
    response_model=HomeProposalsResponse,
)
async def get_home_proposals(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> HomeProposalsResponse:
    """Every pending proposal across the caller's Home-shared rooms, in one
    list, newest-and-needs-you first (design v2 H03: the House's "Needs
    you" inbox).

    WHY no room token: same as GET /users/me/home/activity — authorization
    is the JWT identity plus current Home membership. Missing Home and
    authenticated nonmembership are deliberately the same 404, matching that
    endpoint's convention: the response must not reveal whether Home exists.
    A Home member with no shared rooms yet gets an empty list, not a 404.

    WHY the same snapshot dance as HomeActivityService.build: room
    eligibility and every proposal read that follows it should see one
    consistent view of membership, not one query's view then another's.
    Test fixtures wrap everything in a rollback transaction; asyncpg refuses
    isolation options on a nested transaction, and there the outer
    transaction already IS the snapshot.
    """
    try:
        if db.is_in_transaction():
            return await _build_home_proposals(db, current_user.user_id)
        async with db.transaction(isolation="repeatable_read", readonly=True):
            return await _build_home_proposals(db, current_user.user_id)
    except HomeUnavailable:
        raise HTTPException(status_code=404, detail="Home unavailable")
