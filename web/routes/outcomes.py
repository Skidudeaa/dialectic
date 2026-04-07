"""Outcomes routes — morning brief, trades, cross-book scan."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from web.auth import get_current_user
from web.adapters import outcomes as outcomes_adapter

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"], dependencies=[Depends(get_current_user)])


@router.get("/brief")
async def get_brief() -> dict:
    text = outcomes_adapter.generate_brief()
    return {"brief": text}


@router.get("/trades")
async def list_trades() -> list:
    return outcomes_adapter.list_open_trades()


@router.get("/trades/{trade_id}/evaluate")
async def evaluate_trade(trade_id: str) -> dict:
    try:
        return outcomes_adapter.evaluate_trade(trade_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/cross-book")
async def cross_book_scan() -> dict:
    return outcomes_adapter.scan_cross_book()


@router.get("/ledger/{trade_id}")
async def get_ledger(trade_id: str) -> list:
    return outcomes_adapter.get_trade_ledger(trade_id)
