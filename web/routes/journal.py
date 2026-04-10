"""Trade journal CRUD routes."""

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.models import User, JournalEntryCreate, JournalEntryUpdate
from web import state

router = APIRouter(prefix="/api/journal", tags=["journal"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_entries() -> list:
    return state.list_journal_entries()


@router.post("")
async def create_entry(req: JournalEntryCreate, user: User = Depends(get_current_user)) -> dict:
    return state.save_journal_entry(user.username, req.model_dump())


@router.patch("/{entry_id}")
async def update_entry(entry_id: str, req: JournalEntryUpdate, _user: User = Depends(get_current_user)) -> dict:
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    result = state.update_journal_entry(entry_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return result
