"""Trade journal CRUD routes."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.deps import get_repo
from web.models import User, JournalEntryCreate, JournalEntryUpdate
from web.persistence.repository import Repository

router = APIRouter(prefix="/api/journal", tags=["journal"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_entries(repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.list_journal_entries)


@router.post("")
async def create_entry(req: JournalEntryCreate, user: User = Depends(get_current_user),
                       repo: Repository = Depends(get_repo)) -> dict:
    return await asyncio.to_thread(repo.save_journal_entry, user.username, req.model_dump())


@router.patch("/{entry_id}")
async def update_entry(entry_id: str, req: JournalEntryUpdate,
                       _user: User = Depends(get_current_user),
                       repo: Repository = Depends(get_repo)) -> dict:
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    result = await asyncio.to_thread(repo.update_journal_entry, entry_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return result
