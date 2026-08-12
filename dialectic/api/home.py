# api/home.py — Home membership administration.
#
# ARCHITECTURE: Home is the one is_home room (migration 013). Membership is
# nondelegable: only can_manage_home members (the founder-activated pair)
# may add, and added members never receive the capability. The generic join
# path refuses Home in api/main.py — this router is the only door.
#
# WHY two steps (candidate → add): the add must land on exactly the account
# the administrator previewed. Requiring confirmed_user_id to re-match the
# normalized email prevents an email/account change between preview and
# confirmation.

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from home_activity import (
    HomeActivityProjection,
    HomeActivityService,
    HomeUnavailable,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["home"])

_db_pool = None


def set_home_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


class HomeMemberCandidateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class AddHomeMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    confirmed_user_id: UUID


class HomeMemberCandidateResponse(BaseModel):
    user_id: UUID
    display_name: str


class AddHomeMemberResponse(BaseModel):
    user_id: UUID
    display_name: str
    status: Literal["added", "already_member"]


async def _require_home_manager(token: str, caller_id: UUID, db) -> UUID:
    """
    WHY two queries in this order: an invalid credential must be 401 before
    membership is consulted — preserving the token-versus-membership error
    contract every other room route follows.
    """
    home = await db.fetchrow(
        "SELECT id FROM rooms WHERE is_home AND token = $1", token
    )
    if not home:
        raise HTTPException(status_code=401, detail="Invalid room token")
    membership = await db.fetchrow(
        """SELECT can_manage_home FROM room_memberships
           WHERE room_id = $1 AND user_id = $2""",
        home["id"], caller_id,
    )
    if not membership or not membership["can_manage_home"]:
        raise HTTPException(
            status_code=403,
            detail="Home membership requires a Home administrator",
        )
    return home["id"]


@router.post(
    "/users/me/home/member-candidate",
    response_model=HomeMemberCandidateResponse,
)
async def resolve_home_member_candidate(
    request: HomeMemberCandidateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(extract_room_token),
    db=Depends(get_db),
) -> HomeMemberCandidateResponse:
    """Preview which existing account an email resolves to. Writes nothing."""
    await _require_home_manager(token, current_user.user_id, db)
    email = str(request.email).strip().lower()
    row = await db.fetchrow(
        """SELECT uc.user_id, u.display_name
           FROM user_credentials uc
           JOIN users u ON u.id = uc.user_id
           WHERE lower(uc.email) = $1""",
        email,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No account with that email")
    return HomeMemberCandidateResponse(
        user_id=row["user_id"], display_name=row["display_name"]
    )


# One target/add/event statement so idempotency cannot duplicate the event:
# the event INSERT selects FROM added, which is empty on a conflict.
_ADD_MEMBER_SQL = """
WITH target AS (
    SELECT uc.user_id, u.display_name
    FROM user_credentials uc
    JOIN users u ON u.id = uc.user_id
    WHERE lower(uc.email) = $2 AND uc.user_id = $4
), added AS (
    INSERT INTO room_memberships
        (room_id, user_id, joined_at, can_manage_home)
    SELECT $1, user_id, NOW(), FALSE FROM target
    ON CONFLICT (room_id, user_id) DO NOTHING
    RETURNING user_id
), event_write AS (
    INSERT INTO events
        (id, timestamp, event_type, room_id, user_id, payload)
    SELECT gen_random_uuid(), NOW(), 'user_joined', $1, added.user_id,
           jsonb_build_object('added_by_user_id', $3::text)
    FROM added
)
SELECT target.user_id, target.display_name,
       EXISTS (SELECT 1 FROM added) AS added
FROM target
"""


@router.post("/users/me/home/members", response_model=AddHomeMemberResponse)
async def add_home_member(
    request: AddHomeMemberRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    token: str = Depends(extract_room_token),
    db=Depends(get_db),
) -> AddHomeMemberResponse:
    home_id = await _require_home_manager(token, current_user.user_id, db)
    email = str(request.email).strip().lower()
    row = await db.fetchrow(
        _ADD_MEMBER_SQL,
        home_id, email, current_user.user_id, request.confirmed_user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No account with that email")
    return AddHomeMemberResponse(
        user_id=row["user_id"],
        display_name=row["display_name"],
        status="added" if row["added"] else "already_member",
    )


@router.get(
    "/users/me/home/activity",
    response_model=HomeActivityProjection,
)
async def get_home_activity(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> HomeActivityProjection:
    """
    The shared cross-room activity projection for the caller's Home.

    WHY no room token: authorization is the JWT identity plus current Home
    membership, enforced inside the service. Missing Home and
    authenticated nonmembership are deliberately the same 404 — the
    response must not reveal whether Home exists.
    """
    try:
        return await HomeActivityService(db).build(current_user.user_id)
    except HomeUnavailable:
        raise HTTPException(status_code=404, detail="Home unavailable")
