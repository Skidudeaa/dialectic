"""
v1 trade-lifecycle endpoints — list, inspect, two-step kill.

WHY: The thesis graph side of the system propagates and evaluates; the
trade side (outcomes/*) is where operator consequences live. Until now
the web UI only surfaced canonical trades through morning-brief text.
This route gives the UI a dedicated panel to inspect live predicate
state and manually invalidate a trade when the thesis falls apart.

Read endpoints (list / detail) are unauthenticated to match the
pattern used by /api/thesis and /api/market — the dashboard assumes
anyone who can load the SPA can see trade state. The write endpoint
(kill) is JWT-required and uses a two-step confirm-token flow so a
misclicked "KILL" button can't remove a trade in one network round
trip.
"""

import asyncio
import logging
import secrets
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from web.auth import get_current_user
from web.adapters import outcomes as outcomes_adapter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trades", tags=["v1", "trades"])


# ── Confirm token store ──────────────────────────────────────────────────
# WHY: Two-step kill (confirm_required → execute). A simple in-memory
# dict is sufficient: single-process uvicorn, short TTL, single-use.
# Thread-safe via a module-level lock so concurrent POSTs to the same
# trade_id don't corrupt the token map.

_CONFIRM_TTL_SECONDS = 30.0

_kill_tokens: Dict[str, Dict[str, Any]] = {}
_kill_tokens_lock = threading.Lock()


def _prune_tokens(now: float) -> None:
    """Drop expired tokens. Caller must hold _kill_tokens_lock."""
    expired = [tid for tid, t in _kill_tokens.items() if t["expires"] <= now]
    for tid in expired:
        _kill_tokens.pop(tid, None)


def _issue_token(trade_id: str) -> Dict[str, Any]:
    """Create a fresh single-use confirm token for this trade_id.

    WHY: overwrites any prior unused token so a stuck confirm (e.g. user
    navigated away) doesn't block the next attempt. The token itself is
    randomly generated so knowing the trade_id isn't enough to replay.
    """
    now = time.time()
    token = secrets.token_urlsafe(16)
    with _kill_tokens_lock:
        _prune_tokens(now)
        record = {
            "token": token,
            "expires": now + _CONFIRM_TTL_SECONDS,
            "issued_at": now,
        }
        _kill_tokens[trade_id] = record
    return {
        "confirm_required": True,
        "confirm_token": token,
        "expires_at": record["expires"],
        "ttl_seconds": _CONFIRM_TTL_SECONDS,
    }


def _consume_token(trade_id: str, presented: str) -> str:
    """Validate and consume a confirm token.

    Returns the validation outcome: "ok" | "missing" | "expired" | "mismatch".
    The token is single-use: any validation attempt removes it, so a
    wrong token cannot be retried without a fresh issue step.
    """
    now = time.time()
    with _kill_tokens_lock:
        _prune_tokens(now)
        record = _kill_tokens.pop(trade_id, None)
    if record is None:
        return "missing"
    if record["expires"] <= now:
        return "expired"
    if not secrets.compare_digest(record["token"], presented):
        return "mismatch"
    return "ok"


# ── Schemas ──────────────────────────────────────────────────────────────

class KillRequest(BaseModel):
    """Body for POST /api/v1/trades/{trade_id}/kill.

    WHY required reason: a manual kill without a note is an audit hole —
    the ledger KILL row should say WHY the operator pulled the trade.
    """
    reason: str = Field(min_length=1, max_length=500)
    confirm_token: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("")
async def list_trades() -> list:
    """List open trades with a per-trade predicate summary.

    WHY the join: the panel's header shows "3 trades, 1 fired" at a
    glance. Doing it client-side means 1 + N fetches on cold load.
    Doing it here keeps the header fast and lets the per-trade detail
    view lazy-load only what's clicked.
    """
    trades = await asyncio.to_thread(outcomes_adapter.list_open_trades)
    out = []
    for t in trades:
        trade_id = t.get("trade_id")
        summary: Dict[str, Any] = {
            "trade_id": trade_id,
            "ticker": t.get("ticker", ""),
            "book": t.get("book", ""),
            "ref_price": t.get("ref_price"),
            "direction": t.get("direction", "long"),
            "predicate_count": len(t.get("predicates", [])),
            "fired_count": 0,
            "approaching_count": 0,
            "error": None,
        }
        try:
            detail = await asyncio.to_thread(
                outcomes_adapter.get_trade_predicates, trade_id,
            )
            summary["fired_count"] = detail["fired_count"]
            summary["approaching_count"] = detail["approaching_count"]
            summary["snapshot_timestamp"] = detail["snapshot_timestamp"]
        except (FileNotFoundError, ValueError) as e:
            # WHY don't fail the whole list: one missing snapshot shouldn't
            # hide the other trades. Annotate and continue.
            summary["error"] = str(e)
        out.append(summary)
    return out


@router.get("/{trade_id}")
async def get_trade(trade_id: str) -> dict:
    """Full predicate detail for a single trade."""
    try:
        return await asyncio.to_thread(
            outcomes_adapter.get_trade_predicates, trade_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{trade_id}/kill")
async def kill_trade(
    trade_id: str,
    req: KillRequest,
    user=Depends(get_current_user),
) -> dict:
    """Two-step trade kill.

    First call (no confirm_token): returns {confirm_required, confirm_token,
    expires_at}. Second call (confirm_token matches): writes a KILL row
    to the ledger, removes the trade from open_trades.json, returns the
    kill record.
    """
    # Verify the trade exists up front so we don't issue tokens for ghosts.
    trades = await asyncio.to_thread(outcomes_adapter.list_open_trades)
    known = any(t.get("trade_id") == trade_id for t in trades)
    if not known:
        # Already killed? Surface 409 so the UI can distinguish
        # "never existed" (404) from "someone else just killed it" (409).
        ledger_path = outcomes_adapter.LEDGER_DIR / f"{trade_id}.jsonl"
        if ledger_path.exists():
            for line in ledger_path.read_text().splitlines():
                if not line.strip():
                    continue
                import json as _json
                try:
                    rec = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if rec.get("event_type") == "KILL":
                    raise HTTPException(status_code=409, detail="already_closed")
        raise HTTPException(status_code=404, detail=f"Trade not found: {trade_id}")

    if req.confirm_token is None:
        # First call: issue a confirm token, demand a second POST.
        token_info = _issue_token(trade_id)
        raise HTTPException(status_code=409, detail=token_info)

    outcome = _consume_token(trade_id, req.confirm_token)
    if outcome == "missing":
        raise HTTPException(
            status_code=400,
            detail="no_pending_confirm — call POST without confirm_token first",
        )
    if outcome == "expired":
        raise HTTPException(status_code=400, detail="confirm_token_expired")
    if outcome == "mismatch":
        raise HTTPException(status_code=400, detail="confirm_token_mismatch")

    actor = getattr(user, "username", None) or "unknown"
    try:
        result = await asyncio.to_thread(
            outcomes_adapter.kill_trade, trade_id, actor, req.reason,
        )
    except ValueError as e:
        msg = str(e)
        if msg == "already_closed":
            raise HTTPException(status_code=409, detail="already_closed")
        raise HTTPException(status_code=404, detail=msg)
    return result
