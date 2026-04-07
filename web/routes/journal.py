"""Trade journal CRUD routes."""

from fastapi import APIRouter, Depends

from web.auth import get_current_user
from web.models import User, JournalEntryCreate
from web import state

router = APIRouter(prefix="/api/journal", tags=["journal"], dependencies=[Depends(get_current_user)])


@router.get("")
async def list_entries() -> list:
    return state.list_journal_entries()


@router.post("")
async def create_entry(req: JournalEntryCreate, user: User = Depends(get_current_user)) -> dict:
    return state.save_journal_entry(user.username, req.model_dump())
