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

Unit 12 swap: confirm tokens used to live in a per-process dict; they
now live in the SQLite ``confirm_tokens`` table via the shared
``deps_confirm`` helpers. After a successful kill we also write a row
to ``audit_log`` so destructive actions have a durable trail.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from web.auth import get_current_user
from web.adapters import outcomes as outcomes_adapter
from web.deps import get_repo
from web.persistence.repository import Repository

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trades", tags=["v1", "trades"])


# WHY: Default TTL for kill tokens. Short — operators are expected to
# confirm in seconds, not minutes; a long TTL just widens the replay
# window if a tab is left open.
_CONFIRM_TTL_SECONDS = 30
_KILL_ACTION = "trade.kill"


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
    repo: Repository = Depends(get_repo),
) -> dict:
    """Two-step trade kill.

    First call (no confirm_token): returns 409 with a fresh confirm
    token in the detail. Second call (matching token): writes a KILL
    row to the ledger, removes the trade from open_trades.json,
    appends an ``audit_log`` row, returns the kill record.

    WHY the same 409/400 split as Unit 10: the frontend modal and
    existing client tests already understand this contract — Unit 12
    is a backend storage swap, not a wire-level redesign.
    """
    actor = getattr(user, "username", None) or "unknown"

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

    # Garbage-collect old tokens opportunistically — keeps the table
    # bounded without a separate worker.
    await asyncio.to_thread(repo.purge_expired_confirm_tokens)

    if req.confirm_token is None:
        # First call: persist a confirm token, demand a second POST.
        record = await asyncio.to_thread(
            repo.issue_confirm_token, actor, _KILL_ACTION, trade_id,
            _CONFIRM_TTL_SECONDS,
        )
        token_info = {
            "confirm_required": True,
            "confirm_token": record["token"],
            "expires_at": record["expires_at"],
            "ttl_seconds": _CONFIRM_TTL_SECONDS,
        }
        raise HTTPException(status_code=409, detail=token_info)

    # Second call: validate-and-consume in one shot. Wrong / expired /
    # missing all collapse to 400 — same as Unit 10 — so the UI can show
    # "confirm step required again" without parsing sub-states.
    consumed = await asyncio.to_thread(
        repo.consume_confirm_token,
        req.confirm_token, actor, _KILL_ACTION, trade_id,
    )
    if not consumed:
        raise HTTPException(
            status_code=400,
            detail="confirm_token_invalid — call POST without confirm_token first",
        )

    try:
        result = await asyncio.to_thread(
            outcomes_adapter.kill_trade, trade_id, actor, req.reason,
        )
    except ValueError as e:
        msg = str(e)
        if msg == "already_closed":
            raise HTTPException(status_code=409, detail="already_closed")
        raise HTTPException(status_code=404, detail=msg)

    # WHY audit AFTER the mutation: the row only exists if the ledger
    # write succeeded. A failed kill leaves no audit ghost row.
    try:
        await asyncio.to_thread(
            repo.add_audit_row,
            actor, _KILL_ACTION, trade_id,
            req.reason, req.confirm_token, result,
        )
    except Exception:
        log.exception("Audit log write failed for trade.kill %s", trade_id)
        # Don't fail the response — the kill itself is durable in the
        # ledger; a missing audit row is a soft degradation, not a
        # rollback condition.
    return result
