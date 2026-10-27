# api/workshop.py — read the Workshop's jobs, and the one human write: stop one
"""
ARCHITECTURE: three room-fenced routes over `workshop_jobs` (room token +
JWT + membership, the api/geo.py door). Reads project the ledger row plus a
live stdout tail for a running job; the kill stamps killed_by and SIGKILLs
the process group, and the watcher records the outcome. Starting a job is
the participant's act (the start_job tool), never a human route — a human
who wants code run asks the participant, which is the product.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from llm import workshop_jobs

router = APIRouter(tags=["workshop"])
_db_pool: Any = None


def set_workshop_db_pool(pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


async def _authorize(room_id: UUID, token: str, user_id: UUID, db) -> None:
    """Both credentials, exactly as every other room endpoint requires them
    (copied from api/geo.py:66)."""
    room = await db.fetchrow("SELECT 1 FROM rooms WHERE id = $1 AND token = $2", room_id, token)
    if not room:
        raise HTTPException(status_code=401, detail="Invalid room token")
    member = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2", room_id, user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="User is not a member of this room")


@router.get("/rooms/{room_id}/workshop/jobs")
async def list_workshop_jobs(
    room_id: UUID,
    limit: int = 20,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    await _authorize(room_id, token, current_user.user_id, db)
    return {"jobs": await workshop_jobs.list_jobs(db, room_id, limit)}


@router.get("/rooms/{room_id}/workshop/jobs/{job_id}")
async def get_workshop_job(
    room_id: UUID,
    job_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    await _authorize(room_id, token, current_user.user_id, db)
    job = await workshop_jobs.get_job(db, room_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job in this room")
    return job


@router.post("/rooms/{room_id}/workshop/jobs/{job_id}/kill")
async def kill_workshop_job(
    room_id: UUID,
    job_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    await _authorize(room_id, token, current_user.user_id, db)
    killed = await workshop_jobs.kill(db, room_id, job_id, current_user.user_id)
    if not killed:
        raise HTTPException(status_code=404, detail="No running job with that id in this room")
    return {"killed": True, "job_id": str(job_id)}
