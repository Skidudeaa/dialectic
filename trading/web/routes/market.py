"""Market data routes — quotes, Polymarket, watchlist."""

import asyncio

from fastapi import APIRouter, Depends

from web.auth import get_current_user
from web.adapters import market as market_adapter

router = APIRouter(prefix="/api/market", tags=["market"], dependencies=[Depends(get_current_user)])


@router.get("/quotes")
async def get_quotes() -> list:
    return await asyncio.to_thread(market_adapter.fetch_quotes)


@router.get("/polymarket")
async def get_polymarket() -> list:
    return await asyncio.to_thread(market_adapter.fetch_polymarket_probs)


@router.get("/watchlist")
async def get_watchlist() -> list:
    return await asyncio.to_thread(market_adapter.get_watchlist)
