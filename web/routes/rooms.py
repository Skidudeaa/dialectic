"""Room CRUD routes."""

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.models import User, Room, RoomCreate
from web import state

router = APIRouter(prefix="/api/rooms", tags=["rooms"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_rooms() -> list:
    return state.list_rooms()


@router.post("")
async def create_room(req: RoomCreate, user: User = Depends(get_current_user)) -> dict:
    return state.create_room(
        name=req.name, topic=req.topic,
        linked_book_id=req.linked_book_id,
        participants=[user.username],
    )


@router.get("/{room_id}")
async def get_room(room_id: str) -> dict:
    room = state.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return room
