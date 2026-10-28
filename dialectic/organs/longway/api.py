"""Room-fenced Long Way projections, evidence proposals and consent ledger."""
from datetime import date
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.dependencies import get_current_user
from api.token_utils import extract_room_token
from api.field import _authorize
from api.home import _require_home_manager
from .register import get_register
from .fixes import overlay
from .proposals import propose, list_proposals

router = APIRouter(prefix="/rooms/{room_id}/longway", tags=["longway"])
_pool = None


def set_db_pool(pool):
    global _pool
    _pool = pool


async def get_db():
    async with _pool.acquire() as conn:
        yield conn


async def authorized(room_id: UUID, token=Depends(extract_room_token), user=Depends(get_current_user), db=Depends(get_db)):
    await _authorize(room_id, token, user.user_id, db)
    return user


async def manager(user, db):
    # The credential on this request is the journey's room token; the reused
    # Home capability check needs Home's token after that room was authorized.
    token = await db.fetchval("SELECT token FROM rooms WHERE is_home")
    if not token:
        raise HTTPException(403, "A Home administrator is required")
    await _require_home_manager(token, user.user_id, db)


def journey(slug):
    try:
        return get_register().journey(slug)
    except (KeyError, ValueError):
        raise HTTPException(404, "Unknown journey")


@router.get("/chart")
async def chart(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    result = await overlay(get_register().chart())
    room = await db.fetchrow("SELECT id,linked_journey,is_home FROM rooms WHERE id=$1", room_id)
    rooms = await db.fetch("""SELECT r.id,r.name,r.linked_journey FROM rooms r
        JOIN room_memberships m ON m.room_id=r.id WHERE m.user_id=$1 ORDER BY r.created_at,r.id""", user.user_id)
    return dict(result, room=dict(room), rooms=[dict(r) for r in rooms])


@router.get("/journey/{slug}")
async def get_journey(room_id: UUID, slug: str, user=Depends(authorized)):
    result = journey(slug)
    live = await overlay({"vehicles": result["vehicles"]})
    return dict(result, vehicles=live["vehicles"])


class Bind(BaseModel):
    slug: str


@router.post("/bind")
async def bind(room_id: UUID, body: Bind, user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    journey(body.slug)
    await db.execute("UPDATE rooms SET linked_journey=$2 WHERE id=$1", room_id, body.slug)
    return {"linked_journey": body.slug}


class Proposal(BaseModel):
    candidate: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=4000)
    claim: str = Field(min_length=1, max_length=2000)
    scope: str = Field(min_length=1, max_length=4000)


@router.get("/proposals")
async def proposals(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    return await list_proposals(db, room_id)


@router.post("/proposals")
async def post_proposal(room_id: UUID, body: Proposal, user=Depends(authorized), db=Depends(get_db)):
    try:
        return await propose(db, room_id, **body.model_dump(), proposed_by="human", user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class Confirmation(BaseModel):
    member_id: UUID
    binds: str = Field(min_length=1, max_length=4000)
    confirmed_on: date
    channel: str = Field(min_length=1, max_length=300)


@router.get("/confirmations")
async def confirmations(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    return [dict(r) for r in await db.fetch("SELECT c.*,u.display_name AS member_name FROM longway_confirmations c JOIN users u ON u.id=c.member_id WHERE c.room_id=$1 ORDER BY c.created_at,c.id", room_id)]


@router.post("/confirmations")
async def post_confirmation(room_id: UUID, body: Confirmation, user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    async with db.transaction():
        member = await db.fetchrow("SELECT u.display_name FROM room_memberships m JOIN users u ON u.id=m.user_id WHERE m.room_id=$1 AND m.user_id=$2 FOR SHARE OF m", room_id, body.member_id)
        if not member:
            raise HTTPException(422, "Consent must name a member of this room")
        row = await db.fetchrow("""INSERT INTO longway_confirmations
            (id,room_id,member_id,binds,confirmed_on,channel,recorded_by,created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,clock_timestamp()) RETURNING *""",
            uuid4(), room_id, body.member_id, body.binds, body.confirmed_on, body.channel, user.user_id)
    return dict(row, member_name=member["display_name"])


@router.get("/dispatch/latest")
async def latest_dispatch(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    row = await db.fetchrow("""SELECT m.* FROM messages m JOIN threads t ON t.id=m.thread_id
        WHERE t.room_id=$1 AND NOT m.is_deleted AND m.metadata ? 'longway_dispatch'
        ORDER BY m.created_at DESC,m.id DESC LIMIT 1""", room_id)
    if not row:
        raise HTTPException(404, "No dispatch yet")
    return dict(row)
