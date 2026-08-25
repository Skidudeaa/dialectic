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

import json
import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.thread_titles import ROOT_THREAD_TITLE
from api.token_utils import extract_room_token
from home_activity import (
    HomeActivityProjection,
    HomeActivityService,
    HomeUnavailable,
)
from models import EventType

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


class SpawnSchemeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SpawnSchemeResponse(BaseModel):
    room_id: UUID
    thread_id: UUID
    name: str
    member_count: int


# Create the scheme's room and put EVERY Home member in it, in one statement.
#
# WHY THIS EXISTS: Home refuses to bind a thesis — thesis_relay answers 409
# "Propose it in the scheme's room" — and Home has no Bench, so the tap on a
# proposed thesis there resolved to nothing. General talk that turned into work
# hit a wall and the conversation moved out, which is the exact failure Home was
# created to prevent. The refusal is right; the dead end was the bug. Now the
# product makes the scheme's room instead of naming it as somewhere you must go.
#
# WHY THE MEMBERSHIP INSERT IS THE LOAD-BEARING PART: POST /rooms writes ZERO
# room_memberships — it takes no caller identity at all. That is why
# 8adcabb7 "Trump Tariffs Trading Room" is bound to a live book with 0 members,
# and why T123 / firstRoom! / the rest have none. A spawned room nobody belongs
# to is a room neither of them can open, so the membership is not a follow-up
# step that could fail separately; it is in the same statement as the room.
#
# can_manage_home is FALSE here without exception — the capability is Home's
# and nondelegable, and an ordinary room has no use for it.
_SPAWN_SCHEME_SQL = f"""
WITH home AS (
    SELECT r.id
    FROM rooms r
    JOIN room_memberships m ON m.room_id = r.id AND m.user_id = $1
    WHERE r.is_home
    LIMIT 1
), new_room AS (
    INSERT INTO rooms (id, created_at, token, name)
    SELECT $2, NOW(), $3, $4 FROM home
    RETURNING id
), new_thread AS (
    INSERT INTO threads (id, room_id, created_at, title)
    SELECT $5, id, NOW(), $6 FROM new_room
    RETURNING id
), members AS (
    INSERT INTO room_memberships (room_id, user_id, joined_at, can_manage_home)
    SELECT nr.id, m.user_id, NOW(), FALSE
    FROM new_room nr, home h
    JOIN room_memberships m ON m.room_id = h.id
    RETURNING user_id
), room_event AS (
    INSERT INTO events (id, timestamp, event_type, room_id, payload)
    SELECT $7, NOW(), '{EventType.ROOM_CREATED.value}', id, $8::jsonb FROM new_room
), thread_event AS (
    INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload)
    SELECT $9, NOW(), '{EventType.THREAD_CREATED.value}', nr.id, nt.id, $10::jsonb
    FROM new_room nr, new_thread nt
)
SELECT
    (SELECT id FROM new_room) AS room_id,
    (SELECT id FROM new_thread) AS thread_id,
    (SELECT COUNT(*) FROM members) AS member_count
"""


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
           jsonb_build_object('added_by_user_id', ($3::uuid)::text)
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


@router.post("/users/me/home/schemes", response_model=SpawnSchemeResponse)
async def spawn_scheme_room(
    request: SpawnSchemeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> SpawnSchemeResponse:
    """
    Create the scheme's room from Home, carrying Home's membership into it.

    WHY no room token and no manage capability: this creates an ORDINARY room,
    which any Home member may do — it is the same act as pressing New Room,
    only with the members filled in and the conversation's subject as the name.
    Adding to Home stays nondelegable and stays above; nothing here touches
    Home's own membership.

    Authorization is Home membership itself: the CTE's first term joins
    room_memberships for the caller, so a non-member matches no Home, inserts
    nothing, and falls out as the same 404 the activity projection gives —
    the response must not reveal whether Home exists.

    The thesis is NOT created here. The human still reviews the drafted cascade
    in the new room's Bench before anything binds a book; this only opens the
    door that used to be a refusal.
    """
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A scheme needs a name")

    room_id, thread_id = uuid4(), uuid4()
    row = await db.fetchrow(
        _SPAWN_SCHEME_SQL,
        current_user.user_id,
        room_id,
        uuid4().hex,
        name,
        thread_id,
        ROOT_THREAD_TITLE,
        uuid4(),
        json.dumps({"name": name, "spawned_from": "home"}),
        uuid4(),
        json.dumps({"title": ROOT_THREAD_TITLE}),
    )
    if not row or row["room_id"] is None:
        raise HTTPException(status_code=404, detail="Home unavailable")

    logger.info(
        "Spawned scheme room %s from Home with %s members",
        row["room_id"], row["member_count"],
    )
    return SpawnSchemeResponse(
        room_id=row["room_id"],
        thread_id=row["thread_id"],
        name=name,
        member_count=row["member_count"],
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
