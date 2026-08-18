# api/trading_relay.py — the Bench's read window onto tradingDesk.
#
# ARCHITECTURE: the LLM has had eight trading tools since the fusion; the
# humans had one JSONB badge blob. These routes give the browser the same
# feeds the tool loop exercises daily — structure, quotes, polymarket, the
# hourly diff, open trades, the morning brief, news, and scenario what-ifs —
# each a thin proxy over llm/tradingdesk_client, room-scoped and
# member-gated exactly like thesis_relay. The book id never leaves the
# server: the browser addresses everything by room, the resolution happens
# here (rooms.linked_book_id, then the snapshot's thesisId — the same order
# as llm.tools.resolve_book_id).
#
# Reads plus exactly TWO write-shaped routes: the scenario evaluate POST is
# a pure what-if on tradingDesk's side, and trades/accept is the human tap
# that fills Claude's proposed PAPER trade (propose_trade writes nothing;
# the tap is the write, idempotent through external_operations). Real order
# placement stays categorically out — the paper book is a scoreboard.

import logging
from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.external_operations import (
    ExternalOperation,
    OperationBusy,
    claim_operation,
    fail_operation,
    succeed_operation,
)
from api.token_utils import extract_room_token
from llm import tradingdesk_client as td
from llm.tools import validate_resolution_spec

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trading"])

_db_pool = None

# MEASURED 2026-08-09 (llm/tools.py): a cold /api/market/quotes re-fetches
# Yahoo and takes ~18.5s; the desk now fronts it with a 240s TTL cache, so
# warm hits are milliseconds. The margin covers the cold path.
QUOTES_TIMEOUT_S = 25.0

# Must EXCEED td's own GDELT timeout: when GDELT stalls, td holds the request
# and then answers a graceful {"articles": [], "note": ...} — a proxy timeout
# that loses that race turns the graceful empty into a 502 (observed live
# 2026-08-14, three renders in a row). td caches 15 min, so the margin is paid
# rarely.
#
# Amended 2026-08-16: this local 25.0 was derived from GDELT's 20s SOCKET
# timeout, but GDELT retries, and td's own ceiling for the pull is 45s
# (slow_feeds.py:88). 25s therefore still lost the race on a cold cache —
# measured cold pulls that day ran 15.8s / 26.7s / 28.9s. Deferring to the one
# shared constant so all five callers of this route agree.
#
# TRADEOFF, this call site only: it is the one INTERACTIVE caller, so the
# budget is now a 60s spinner rather than a 25s error. Accepted because the
# wire warms this exact cache every 900s (once its own timeout was fixed in
# the same change), so a Bench render meets a cold cache only just after a
# restart or a td cache flush.
NEWS_TIMEOUT_S = td.NEWS_TIMEOUT_S

# Same seam law as news: the browser relay must not cancel tradingDesk before
# the configured markets' bounded producer budget has elapsed.
POLYMARKET_TIMEOUT_S = td.POLYMARKET_TIMEOUT_S


def set_trading_relay_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("trading relay database pool is not initialized")
    return _db_pool


async def _verify_room_member(room_id: UUID, user_id: UUID, db) -> None:
    row = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=403, detail="User is not a member of this room")


async def _room_book(room_id: UUID, token: str, user_id: UUID, db) -> str:
    """Authorize the caller and resolve which book this room talks about.

    Resolution mirrors llm.tools.resolve_book_id minus the explicit arg:
    the binding wins, then whatever the pushed snapshot carries. An
    unbound room (Home always is) answers 409 — the Bench renders its
    create/stub state on that, so the copy stays calm, not alarming.
    """
    row = await db.fetchrow(
        "SELECT token, linked_book_id, trading_config FROM rooms "
        "WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")
    await _verify_room_member(room_id, user_id, db)

    if row["linked_book_id"]:
        return str(row["linked_book_id"])
    config = row["trading_config"] or {}
    if isinstance(config, dict):
        for key in ("book_id", "bookId", "book", "thesisId"):
            if config.get(key):
                return str(config[key])
    raise HTTPException(
        status_code=409, detail="This room is not bound to a thesis."
    )


async def _resolve_room_book(
    room_id: UUID,
    token: str,
    user_id: UUID,
    pool: asyncpg.Pool,
) -> str:
    """Resolve the room binding while holding a connection only for SQL."""
    async with pool.acquire() as db:
        return await _room_book(room_id, token, user_id, db)


def _bad_gateway(context: str, e: td.TradingDeskError) -> HTTPException:
    logger.warning("trading relay %s: %s", context, e)
    return HTTPException(status_code=502, detail=f"tradingDesk: {e}")


@router.get("/rooms/{room_id}/trading/structure")
async def get_structure(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """The authored causal DAG — nodes with positions, edges with mechanism.

    Live node state is NOT here: it rides the snapshot the room already
    holds (rooms.trading_config + the trading_update WS event), and the
    client overlays it. Two sources because they are two truths — the
    structure is authored, the states are evaluated.
    """
    book_id = await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.service_get(f"/api/bridge/structure/{book_id}")
    except td.TradingDeskError as e:
        raise _bad_gateway("structure", e)


@router.get("/rooms/{room_id}/trading/quotes")
async def get_quotes(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.get("/api/market/quotes", timeout=QUOTES_TIMEOUT_S)
    except td.TradingDeskError as e:
        raise _bad_gateway("quotes", e)


@router.get("/rooms/{room_id}/trading/polymarket")
async def get_polymarket(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list:
    book_id = await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        result = await td.service_get(
            f"/api/bridge/polymarket/{book_id}",
            timeout=POLYMARKET_TIMEOUT_S,
        )
        if not isinstance(result, dict) or not isinstance(result.get("markets"), list):
            raise td.TradingDeskError(
                "tradingDesk polymarket bridge returned an unexpected shape"
            )
        status = result.get("status")
        markets = result["markets"]
        freshness = result.get("freshness")
        state = freshness.get("state") if isinstance(freshness, dict) else None
        if status in {"ok", "partial", "no_data"}:
            if state not in {"live", "cached"}:
                raise td.TradingDeskError(
                    "tradingDesk polymarket bridge returned an unexpected shape"
                )
            return markets
        if status == "not_configured":
            if state != "not_applicable" or markets:
                raise td.TradingDeskError(
                    "tradingDesk polymarket bridge returned an unexpected shape"
                )
            return []
        if status == "unavailable":
            if state != "stale" or markets:
                raise td.TradingDeskError(
                    "tradingDesk polymarket bridge returned an unexpected shape"
                )
            return []
        raise td.TradingDeskError(
            "tradingDesk polymarket bridge returned an unexpected shape"
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("polymarket", e)


@router.get("/rooms/{room_id}/trading/diff")
async def get_diff(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    book_id = await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.run_command(
            "thesis.diff.last_hour", {"book_id": book_id}
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("diff", e)


@router.get("/rooms/{room_id}/trading/trades")
async def get_trades(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Open trades desk-wide, not per-book — exposure is one pool of money.

    Same shape the LLM's get_open_trades tool reads; the room gate is about
    who may look, not about filtering what they see.
    """
    await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.run_command("outcomes.open_trades", {})
    except td.TradingDeskError as e:
        raise _bad_gateway("trades", e)


@router.get("/rooms/{room_id}/trading/brief")
async def get_brief(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    book_id = await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.run_command(
            "outcomes.morning_brief", {"book_id": book_id}
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("brief", e)


@router.get("/rooms/{room_id}/trading/news")
async def get_news(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    book_id = await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.service_get(
            f"/api/bridge/news/{book_id}", timeout=NEWS_TIMEOUT_S
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("news", e)


@router.get("/rooms/{room_id}/trading/calibration")
async def get_calibration(
    room_id: UUID,
    source_label: str | None = None,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """The claims ledger's calibration curve — desk-wide, like trades.

    Optional source_label narrows to one forecaster ("Claude", a human, a
    newsletter). The room gate is about who may look, not what they see.
    """
    await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        params = {"source_label": source_label} if source_label else None
        return await td.get("/api/predictions/calibration", params=params)
    except td.TradingDeskError as e:
        raise _bad_gateway("calibration", e)


@router.get("/rooms/{room_id}/trading/leaderboard")
async def get_leaderboard(
    room_id: UUID,
    split_by: str = "source_label",
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Per-source Brier/BSS leaderboard — the de-biasing instrument.

    split_by passes through untouched (source_label | tag | horizon | ...);
    the desk owns the vocabulary and 422s what it doesn't know.
    """
    await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.get(
            "/api/predictions/leaderboard", params={"split_by": split_by}
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("leaderboard", e)


@router.post("/rooms/{room_id}/trading/scenarios/{scenario_id}/evaluate")
async def evaluate_scenario(
    room_id: UUID,
    scenario_id: str,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """A pure what-if against the live snapshot — evaluated, never placed."""
    book_id = await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        return await td.post(
            f"/api/v1/theses/{book_id}/scenarios/{scenario_id}/evaluate",
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("scenario evaluate", e)


# ── the paper book: portfolio read + the trade Accept ────────────────────

# The empty-book shape, mirroring td's _book_view keys exactly — a bound
# book with no fills yet is a calm "nothing here", never an error: seeding
# the first deposit is an operator act, not something a render should nag.
_EMPTY_BOOK = {
    "cash": 0.0,
    "positions": [],
    "equity": 0.0,
    "inception": None,
    "flows": [],
    "marks": [],
    "spy_baseline": [],
    "spy_baseline_now": None,
    "price_return_only": True,
}


def _strip_book_ids(view: dict) -> dict:
    """The relay's house rule: the book id never reaches the browser.

    td's equity-mark rows are SELECT * and carry book_id; everything else
    in the book view is already clean (fills are reshaped into flows).
    """
    marks = view.get("marks")
    if isinstance(marks, list):
        view = {**view, "marks": [
            {k: v for k, v in m.items() if k != "book_id"}
            if isinstance(m, dict) else m
            for m in marks
        ]}
    return view


@router.get("/rooms/{room_id}/trading/portfolio")
async def get_portfolio(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """This room's paper book: cash, derived positions, equity, and the
    unitized SPY benchmark (price-return-only, labeled as such by td).

    td's GET /api/portfolio returns EVERY book; the room's binding filters
    it here so the browser addresses everything by room, like the rest of
    the relay. Unbound room: 409 (the Bench's calm create state).
    """
    book_id = await _resolve_room_book(room_id, token, current_user.user_id, pool)
    try:
        # Same seam law as quotes: td values positions off its quote cache,
        # so a cold cache pays the ~18.5s Yahoo path — the proxy must not
        # cancel first.
        data = await td.get("/api/portfolio", timeout=QUOTES_TIMEOUT_S)
    except td.TradingDeskError as e:
        raise _bad_gateway("portfolio", e)
    books = data.get("books") if isinstance(data, dict) else None
    view = books.get(book_id) if isinstance(books, dict) else None
    if not isinstance(view, dict):
        return dict(_EMPTY_BOOK)
    return _strip_book_ids(view)


class AcceptTradeRequest(BaseModel):
    message_id: UUID


def _malformed(reason: str) -> HTTPException:
    return HTTPException(
        status_code=422, detail=f"The stored trade proposal is malformed: {reason}"
    )


def _validated_trade(proposal: dict) -> dict:
    """Re-validate the stored proposal at the write.

    The propose_trade tool validated these at draft time, but metadata is a
    document, not a trust boundary — same rule as prediction_relay. Returns
    the normalized trade; raises 422 on anything the tool would have
    refused, including the forecast-XOR-discretionary gate.
    """
    symbol = str(proposal.get("symbol") or "").strip().upper()
    if not symbol or len(symbol) > 32 or symbol == "CASH":
        raise _malformed("symbol")
    side = proposal.get("side")
    if side not in ("buy", "sell"):
        raise _malformed("side")
    try:
        dollars = float(proposal.get("dollars"))
    except (TypeError, ValueError):
        raise _malformed("dollars")
    if not 0 < dollars <= 10_000_000:
        raise _malformed("dollars")
    rationale = str(proposal.get("rationale") or "").strip()
    if not rationale or len(rationale) > 2000:
        raise _malformed("rationale")

    trade: dict = {"symbol": symbol, "side": side, "dollars": dollars,
                   "rationale": rationale}
    node_id = str(proposal.get("node_id") or "").strip()
    if node_id:
        trade["node_id"] = node_id

    forecast = proposal.get("prediction")
    discretionary = bool(proposal.get("discretionary"))
    has_forecast = isinstance(forecast, dict) and bool(forecast)
    if has_forecast == discretionary:
        # Neither (unevaluable) or both (contradictory) — the tool's gate,
        # re-asserted at the write.
        raise _malformed("exactly one of prediction or discretionary")
    if has_forecast:
        statement = str(forecast.get("statement") or "").strip()
        deadline = str(forecast.get("deadline") or "").strip()
        try:
            confidence = float(forecast.get("confidence"))
            date.fromisoformat(deadline)
        except (TypeError, ValueError):
            raise _malformed("prediction")
        if not statement or not 0.0 <= confidence <= 1.0:
            raise _malformed("prediction")
        checked: dict = {"statement": statement, "confidence": confidence,
                         "deadline": deadline}
        spec = forecast.get("resolution_spec")
        if spec is not None:
            try:
                checked["resolution_spec"] = validate_resolution_spec(spec)
            except ValueError:
                raise _malformed("resolution_spec")
        trade["prediction"] = checked
    else:
        trade["discretionary"] = True
    return trade


@router.post("/rooms/{room_id}/trading/trades/accept")
async def accept_trade(
    room_id: UUID,
    request: AcceptTradeRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Fill Claude's proposed paper trade. The human tap IS the write.

    Two idempotent td writes in ORDER when a forecast rides along: the
    prediction first (the claims ledger is the point of the whole loop),
    then the fill carrying its id. Both source_keys derive from ONE
    operation_key, so a crash between the two writes replays cleanly —
    td's INSERT OR IGNORE on source_key makes the re-POST of the
    prediction return the same row, and the fill lands on the retry.
    A discretionary trade skips the prediction write entirely: an explicit
    unscored label, never a fabricated confidence.
    """
    async with pool.acquire() as db:
        book_id = await _room_book(room_id, token, current_user.user_id, db)
        row = await db.fetchrow(
            """SELECT m.id, m.metadata
               FROM messages m
               JOIN threads t ON t.id = m.thread_id
               WHERE m.id = $1 AND t.room_id = $2 AND NOT m.is_deleted""",
            request.message_id,
            room_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found in this room")

    metadata = row["metadata"]
    proposal = metadata.get("trade_proposal") if isinstance(metadata, dict) else None
    if not isinstance(proposal, dict):
        raise HTTPException(
            status_code=404, detail="This message carries no trade proposal"
        )
    trade = _validated_trade(proposal)

    operation_key = f"trade:{request.message_id}:trade_proposal"
    try:
        operation: ExternalOperation = await claim_operation(
            pool,
            room_id=room_id,
            kind="trade",
            operation_key=operation_key,
            initiated_by=current_user.user_id,
            source_message_id=request.message_id,
            proposal_slot="trade_proposal",
        )
    except (OperationBusy, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if operation.status == "succeeded":
        if operation.external_result is None:
            raise RuntimeError("Succeeded external operation has no recorded result")
        return operation.external_result
    if proposal.get("accepted"):
        await fail_operation(pool, operation, error="proposal was already accepted")
        raise HTTPException(
            status_code=409, detail="Trade already filled on the paper book"
        )

    forecast = trade.get("prediction")
    rationale = trade["rationale"]
    if "discretionary" in trade:
        # The fill's own record says it dodged no scoreboard — it was
        # labeled out of it.
        rationale = f"[unscored discretionary] {rationale}"

    prediction_row: dict | None = None
    try:
        if forecast is not None:
            prediction_body = {
                "statement": forecast["statement"],
                "confidence": forecast["confidence"],
                "deadline": forecast["deadline"],
                "tags": ["dialectic"],
                # Provenance stamped HERE, as in prediction_relay: the tool
                # is metadata.trade_proposal's only writer, so authorship is
                # a property of this path, not of the payload.
                "source_type": "llm",
                "source_label": "Claude",
                "linked_book_id": book_id,
                "source_key": f"{operation_key}:prediction",
            }
            if "resolution_spec" in forecast:
                prediction_body["resolution_spec"] = forecast["resolution_spec"]
            prediction_row = await td.post("/api/predictions", json_body=prediction_body)
            if not isinstance(prediction_row, dict) or not prediction_row.get("id"):
                raise td.TradingDeskError("tradingDesk returned an invalid prediction")
        fill_body = {
            "book_id": book_id,
            "kind": "trade",
            "symbol": trade["symbol"],
            "side": trade["side"],
            "dollars": trade["dollars"],
            "rationale": rationale,
            "node_id": trade.get("node_id"),
            "prediction_id": prediction_row["id"] if prediction_row else None,
            "source_key": operation_key,
        }
        # Seam law: td prices the fill off its quote cache, and the cold
        # path re-fetches Yahoo (~18.5s measured) — the 10s client default
        # would 502 exactly then, after td may still land the fill. The
        # source_key makes that retry-safe, but the margin makes it rare.
        fill = await td.post("/api/portfolio/fills", json_body=fill_body,
                             timeout=QUOTES_TIMEOUT_S)
        if not isinstance(fill, dict):
            raise td.TradingDeskError("tradingDesk returned an invalid fill")
    except td.TradingDeskError as e:
        # The operation is released, not finalized — a retry is a fresh
        # accept, and both td writes replay off their source_keys.
        await fail_operation(pool, operation, error=str(e))
        logger.warning("trade relay to tradingDesk failed: %s", e)
        if "HTTP 422" in str(e):
            # td's own guards: no live quote for the symbol, or a sell past
            # flat on the long-only book. A client error, not a dead desk.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"tradingDesk refused the trade: {e}. Most likely the desk "
                    f"has no live quote for {trade['symbol']!r}, or the sell "
                    "exceeds what the book holds."
                ),
            ) from e
        raise HTTPException(
            status_code=502, detail=f"tradingDesk refused the trade: {e}"
        ) from e

    result = {"fill": fill, "prediction": prediction_row}
    async with pool.acquire() as db:
        async with db.transaction():
            # succeed_operation also writes the acceptance stamp into
            # metadata.trade_proposal (acceptance_stamp via ACCEPT_SLOT_SQL)
            # — accepted/accepted_by/accepted_at in one patch, per §9.3.
            await succeed_operation(db, operation, result=result)
    return result
