"""Room CRUD routes."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.deps import get_repo
from web.models import User, Room, RoomCreate, RoomUpdate
from web.persistence.repository import Repository

router = APIRouter(prefix="/api/rooms", tags=["rooms"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_rooms(repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.list_rooms)


@router.post("")
async def create_room(req: RoomCreate, user: User = Depends(get_current_user),
                      repo: Repository = Depends(get_repo)) -> dict:
    return await asyncio.to_thread(
        repo.create_room,
        name=req.name, topic=req.topic,
        linked_book_id=req.linked_book_id,
        participants=[user.username],
    )


@router.get("/{room_id}")
async def get_room(room_id: str, repo: Repository = Depends(get_repo)) -> dict:
    room = await asyncio.to_thread(repo.get_room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.patch("/{room_id}")
async def update_room(room_id: str, req: RoomUpdate, _user: User = Depends(get_current_user),
                      repo: Repository = Depends(get_repo)) -> dict:
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    result = await asyncio.to_thread(repo.update_room, room_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return result


@router.delete("/{room_id}")
async def delete_room(room_id: str, _user: User = Depends(get_current_user),
                      repo: Repository = Depends(get_repo)) -> dict:
    room = await asyncio.to_thread(repo.get_room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    await asyncio.to_thread(repo.delete_room, room_id)
    return {"deleted": True}
