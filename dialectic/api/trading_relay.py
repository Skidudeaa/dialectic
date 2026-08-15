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
# Read-only by construction: the one POST (scenario evaluate) is a pure
# what-if on tradingDesk's side. Order placement stays categorically out.

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from llm import tradingdesk_client as td

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trading"])

_db_pool = None

# MEASURED 2026-08-09 (llm/tools.py): a cold /api/market/quotes re-fetches
# Yahoo and takes ~18.5s; the desk now fronts it with a 240s TTL cache, so
# warm hits are milliseconds. The margin covers the cold path.
QUOTES_TIMEOUT_S = 25.0

# Must EXCEED td's own GDELT timeout (tools/data_fetch/gdelt.py
# DEFAULT_TIMEOUT = 20): when GDELT stalls, td holds the request the full
# 20s and then answers a graceful {"articles": [], "note": ...} — a proxy
# timeout at exactly 20s loses that race and turns the graceful empty into
# a 502 (observed live 2026-08-14, three renders in a row). td caches 15
# min, so the margin is paid rarely.
NEWS_TIMEOUT_S = 25.0


def set_trading_relay_db_pool(pool):
    global _db_pool
    _db_pool = pool


async def get_db():
    async with _db_pool.acquire() as conn:
        yield conn


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


def _bad_gateway(context: str, e: td.TradingDeskError) -> HTTPException:
    logger.warning("trading relay %s: %s", context, e)
    return HTTPException(status_code=502, detail=f"tradingDesk: {e}")


@router.get("/rooms/{room_id}/trading/structure")
async def get_structure(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """The authored causal DAG — nodes with positions, edges with mechanism.

    Live node state is NOT here: it rides the snapshot the room already
    holds (rooms.trading_config + the trading_update WS event), and the
    client overlays it. Two sources because they are two truths — the
    structure is authored, the states are evaluated.
    """
    book_id = await _room_book(room_id, token, current_user.user_id, db)
    try:
        return await td.service_get(f"/api/bridge/structure/{book_id}")
    except td.TradingDeskError as e:
        raise _bad_gateway("structure", e)


@router.get("/rooms/{room_id}/trading/quotes")
async def get_quotes(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    await _room_book(room_id, token, current_user.user_id, db)
    try:
        return await td.get("/api/market/quotes", timeout=QUOTES_TIMEOUT_S)
    except td.TradingDeskError as e:
        raise _bad_gateway("quotes", e)


@router.get("/rooms/{room_id}/trading/polymarket")
async def get_polymarket(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    await _room_book(room_id, token, current_user.user_id, db)
    try:
        return await td.get("/api/market/polymarket")
    except td.TradingDeskError as e:
        raise _bad_gateway("polymarket", e)


@router.get("/rooms/{room_id}/trading/diff")
async def get_diff(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    book_id = await _room_book(room_id, token, current_user.user_id, db)
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
    db=Depends(get_db),
):
    """Open trades desk-wide, not per-book — exposure is one pool of money.

    Same shape the LLM's get_open_trades tool reads; the room gate is about
    who may look, not about filtering what they see.
    """
    await _room_book(room_id, token, current_user.user_id, db)
    try:
        return await td.run_command("outcomes.open_trades", {})
    except td.TradingDeskError as e:
        raise _bad_gateway("trades", e)


@router.get("/rooms/{room_id}/trading/brief")
async def get_brief(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    book_id = await _room_book(room_id, token, current_user.user_id, db)
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
    db=Depends(get_db),
):
    book_id = await _room_book(room_id, token, current_user.user_id, db)
    try:
        return await td.service_get(
            f"/api/bridge/news/{book_id}", timeout=NEWS_TIMEOUT_S
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("news", e)


@router.post("/rooms/{room_id}/trading/scenarios/{scenario_id}/evaluate")
async def evaluate_scenario(
    room_id: UUID,
    scenario_id: str,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """A pure what-if against the live snapshot — evaluated, never placed."""
    book_id = await _room_book(room_id, token, current_user.user_id, db)
    try:
        return await td.post(
            f"/api/v1/theses/{book_id}/scenarios/{scenario_id}/evaluate",
        )
    except td.TradingDeskError as e:
        raise _bad_gateway("scenario evaluate", e)
