"""Paper portfolio routes — the fill door and the valuation read.

ARCHITECTURE: the only write is POST /fills; everything else is derived.
Positions and cash replay from the append-only paper_fills ledger
(repository.portfolio_positions), intraday equity prices off the 240s
fetch_quotes cache, and the SPY benchmark is computed at read time from
equity_marks — nothing here stores a number that could drift from its
source ledger.
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from web.adapters import market
from web.auth import get_current_user
from web.deps import get_repo
from web.models import PaperFillCreate, User
from web.persistence.repository import Repository

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"],
                   dependencies=[Depends(get_current_user)])


def _quote_map(quotes: List[Dict[str, Any]]) -> Dict[str, float]:
    return {q["symbol"]: q["price"] for q in quotes
            if isinstance(q.get("price"), (int, float))}


@router.post("/fills")
async def create_fill(req: PaperFillCreate,
                      user: User = Depends(get_current_user),
                      repo: Repository = Depends(get_repo)) -> dict:
    if req.kind == "deposit":
        # Deposits never need a quote: cash in at par.
        fill = {
            "book_id": req.book_id,
            "kind": "deposit",
            "symbol": "CASH",
            "side": "buy",
            "quantity": req.dollars,
            "price": 1.0,
        }
    else:
        quotes = _quote_map(await asyncio.to_thread(market.fetch_quotes))
        price = quotes.get(req.symbol)
        if not price or price <= 0:
            raise HTTPException(
                status_code=422,
                detail=f"No live quote for {req.symbol!r} — trades are priced "
                       "off the desk's quote feed, not client-supplied prices",
            )
        quantity = req.dollars / price
        if req.side == "sell":
            # ponytail: long-only ceiling — selling past flat would open a
            # short with none of its accounting modeled (restricted proceeds,
            # borrow, margin). Shorts return when those semantics are defined.
            held = (await asyncio.to_thread(
                repo.portfolio_positions, req.book_id
            ))["positions"].get(req.symbol, {}).get("qty", 0.0)
            # Epsilon absorbs float dust so an exact-flat sell never 422s.
            if quantity > held + 1e-9:
                raise HTTPException(
                    status_code=422,
                    detail=f"Sell of {quantity:.6f} {req.symbol} exceeds the "
                           f"{held:.6f} held — the paper book is long-only",
                )
        fill = {
            "book_id": req.book_id,
            "kind": "trade",
            "symbol": req.symbol,
            "side": req.side,
            "quantity": quantity,
            "price": price,
        }
    fill.update({
        "rationale": req.rationale,
        "node_id": req.node_id,
        "prediction_id": req.prediction_id,
        "source_key": req.source_key,
    })
    record, _created = await asyncio.to_thread(
        repo.record_fill_once, user.username, fill
    )
    return record


def _book_view(repo: Repository, book_id: str,
               quotes: Dict[str, float]) -> dict:
    """One book's derived state. Synchronous — wrapped in to_thread."""
    state = repo.portfolio_positions(book_id)
    marks = repo.list_equity_marks(book_id)
    # ponytail: a symbol Yahoo won't quote intraday is valued at the latest
    # mark's close — last known truth beats a hole in the equity number.
    mark_closes: Dict[str, float] = {}
    if marks:
        for symbol, snap in (marks[-1].get("positions") or {}).items():
            if isinstance(snap, dict) and isinstance(snap.get("close"), (int, float)):
                mark_closes[symbol] = snap["close"]

    positions = []
    equity = state["cash"]
    for symbol, pos in sorted(state["positions"].items()):
        # Fallback chain: live quote -> latest mark close -> entry basis
        # (marked at cost, unrealized 0 — visible, never a crash or a hole).
        price = quotes.get(symbol, mark_closes.get(symbol, pos["avg_cost"]))
        value = pos["qty"] * price
        equity += value
        positions.append({
            "symbol": symbol,
            "qty": pos["qty"],
            "avg_cost": pos["avg_cost"],
            "price": price,
            "value": value,
            "unrealized": pos["qty"] * (price - pos["avg_cost"]),
        })

    fills = repo.list_fills(book_id)
    # External cash flows are exactly the deposit fills — the schema's own
    # record of money entering the book. Dated at day granularity to match
    # mark_date.
    flows = [
        {"date": f["created_at"][:10], "amount": f["quantity"] * f["price"]}
        for f in fills if f["kind"] == "deposit"
    ]

    # WHY unitized: "seed x spy_t/spy_first" is only right for a single
    # deposit. Instead the benchmark holds SPY UNITS — each mark converts
    # the net external flow since the previous mark into units at THAT
    # mark's close, so every dollar competes with the index from (about)
    # when it arrived. WHY the one-day fuzz is acceptable: deposits carry
    # timestamps but marks are daily, so a deposit "executes" at the next
    # mark's close — up to a day late, paper-grade precision, and the same
    # rule for every deposit.
    spy_units = 0.0
    spy_baseline: List[dict] = []
    prev_date: Optional[str] = None
    for m in marks:
        if not m["spy_close"]:
            continue
        flow = sum(
            f["amount"] for f in flows
            if (prev_date is None or f["date"] > prev_date)
            and f["date"] <= m["mark_date"]
        )
        spy_units += flow / m["spy_close"]
        spy_baseline.append({
            "mark_date": m["mark_date"],
            "value": spy_units * m["spy_close"],
        })
        prev_date = m["mark_date"]

    spy_now = quotes.get("SPY")
    if spy_units and spy_now:
        benchmark_now: Optional[float] = spy_units * spy_now
    elif spy_baseline:
        benchmark_now = spy_baseline[-1]["value"]
    else:
        benchmark_now = None

    return {
        "cash": state["cash"],
        "positions": positions,
        "equity": equity,
        "inception": fills[0]["created_at"] if fills else None,
        "flows": flows,
        "marks": marks,
        "spy_baseline": spy_baseline,
        "spy_baseline_now": benchmark_now,
        # No dividends modeled on either side of the comparison.
        "price_return_only": True,
    }


@router.get("")
async def get_portfolio(repo: Repository = Depends(get_repo)) -> dict:
    books = await asyncio.to_thread(repo.list_fill_books)
    quotes = _quote_map(await asyncio.to_thread(market.fetch_quotes)) if books else {}
    views = {}
    for book_id in books:
        views[book_id] = await asyncio.to_thread(_book_view, repo, book_id, quotes)
    return {"books": views}
