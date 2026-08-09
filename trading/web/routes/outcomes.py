"""Outcomes routes — morning brief, trades, cross-book scan."""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from web.auth import get_current_user
from web.adapters import outcomes as outcomes_adapter

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"], dependencies=[Depends(get_current_user)])


@router.get("/brief")
async def get_brief(book_id: Optional[str] = Query(default=None)) -> dict:
    book_ids = [book_id] if book_id else None
    text = await asyncio.to_thread(outcomes_adapter.generate_brief, book_ids)
    return {"brief": text}


@router.get("/trades")
async def list_trades() -> list:
    return await asyncio.to_thread(outcomes_adapter.list_open_trades)


@router.get("/trades/{trade_id}/evaluate")
async def evaluate_trade(trade_id: str) -> dict:
    try:
        return await asyncio.to_thread(outcomes_adapter.evaluate_trade, trade_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/cross-book")
async def cross_book_scan(book_ids: Optional[str] = Query(default=None)) -> dict:
    ids = book_ids.split(",") if book_ids else None
    return await asyncio.to_thread(outcomes_adapter.scan_cross_book, ids)


@router.get("/ledger/{trade_id}")
async def get_ledger(trade_id: str) -> list:
    return await asyncio.to_thread(outcomes_adapter.get_trade_ledger, trade_id)
