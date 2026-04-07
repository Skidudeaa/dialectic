"""Thesis graph routes — state, scenarios, horizon, price fetch."""

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.models import User, HorizonRequest
from web.adapters import thesis as thesis_adapter

router = APIRouter(prefix="/api/thesis", tags=["thesis"], dependencies=[Depends(get_current_user)])


@router.get("/books")
async def list_books() -> list:
    return thesis_adapter.list_books()


@router.get("/{book_id}/state")
async def get_state(book_id: str) -> dict:
    try:
        return thesis_adapter.get_state(book_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{book_id}/scenarios")
async def get_scenarios(book_id: str) -> list:
    try:
        return thesis_adapter.get_scenarios(book_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{book_id}/horizon")
async def run_horizon(book_id: str, req: HorizonRequest) -> dict:
    try:
        return thesis_adapter.run_horizon(book_id, req.horizon_days)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{book_id}/fetch-prices")
async def fetch_prices(book_id: str) -> dict:
    try:
        return thesis_adapter.fetch_prices_for_book(book_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Price fetch failed: {e}")
