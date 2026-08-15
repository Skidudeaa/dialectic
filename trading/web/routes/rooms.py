"""Room READ routes — the writes died in the C4 chat cull (2026-08).

WHY reads survive: the machine WS lane (/ws/{room_id}) is room-addressed
and agents need discovery; rooms themselves are still the join surface for
book-linked broadcasts. Room creation/edit/deletion had no caller left
once the chat UI was deleted — if a room must change now, it changes in
the sqlite repo by operator hand, on purpose.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.deps import get_repo
from web.persistence.repository import Repository

router = APIRouter(prefix="/api/rooms", tags=["rooms"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_rooms(repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.list_rooms)


@router.get("/{room_id}")
async def get_room(room_id: str, repo: Repository = Depends(get_repo)) -> dict:
    room = await asyncio.to_thread(repo.get_room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return room
