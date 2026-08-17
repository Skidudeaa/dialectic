"""
Contracts for the trading relay — the Bench's read window onto tradingDesk
(api/trading_relay.py): structure, quotes, polymarket, diff, trades, brief,
news, and the scenario what-if.

Strategy matches tests/test_thesis_relay_endpoint.py — dependency overrides +
a fake db routing fetchrow by table; tradingDesk mocked at trading_relay.td.
The contracts that matter: membership gates every route, an unbound room is
a 409 (the Bench's calm stub state, never an error), the book id resolves
binding-first then snapshot, it never appears in any URL the browser sent,
and a dead desk is a 502 — not a hang, not HTML.
"""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.trading_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm.tradingdesk_client import TradingDeskError

ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
ROOM_TOKEN = "room-token-secret"
BOOK_ID = "iran-hormuz-graph"


class _AsyncContext:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc_info):
        return None


class _Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _AsyncContext(self.db)


def _make_db(room_found=True, linked_book_id=BOOK_ID, trading_config=None,
             members=None):
    if members is None:
        members = {CALLER_ID}
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            if not room_found:
                return None
            return {"token": ROOM_TOKEN, "linked_book_id": linked_book_id,
                    "trading_config": trading_config}
        if "FROM room_memberships" in query:
            _room_id, user_id = params
            return {"?column?": 1} if user_id in members else None
        return None

    fake_db.fetchrow = AsyncMock(side_effect=fetchrow)
    return fake_db


def _call(fake_db, monkeypatch, path, *, method="GET", td_mocks=None):
    fake_db._pool = _Pool(fake_db)

    main_mod.app.dependency_overrides[relay.get_pool] = lambda: fake_db._pool
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: ROOM_TOKEN
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True,
        display_name="Caller",
    )
    for name, mock in (td_mocks or {}).items():
        monkeypatch.setattr(relay.td, name, mock)
    try:
        client = TestClient(main_mod.app)
        url = f"/rooms/{ROOM_ID}/trading/{path}"
        return client.post(url) if method == "POST" else client.get(url)
    finally:
        main_mod.app.dependency_overrides.clear()


# ---------------------------------------------------------------- routing

def test_structure_resolves_book_and_proxies_bridge(monkeypatch):
    structure = {"id": BOOK_ID, "nodes": [{"id": "a"}], "edges": []}
    service_get = AsyncMock(return_value=structure)

    resp = _call(_make_db(), monkeypatch, "structure",
                 td_mocks={"service_get": service_get})

    assert resp.status_code == 200
    assert resp.json() == structure
    service_get.assert_awaited_once_with(f"/api/bridge/structure/{BOOK_ID}")


def test_quotes_uses_the_cold_path_timeout(monkeypatch):
    get = AsyncMock(return_value={"quotes": []})
    resp = _call(_make_db(), monkeypatch, "quotes", td_mocks={"get": get})
    assert resp.status_code == 200
    get.assert_awaited_once_with("/api/market/quotes",
                                 timeout=relay.QUOTES_TIMEOUT_S)


def test_polymarket_is_book_scoped_but_remains_list_shaped(monkeypatch):
    markets = [{"slug": "m", "probability": 0.4}]
    service_get = AsyncMock(return_value={
        "status": "ok",
        "configured_markets": ["m"],
        "missing_markets": [],
        "markets": markets,
        "freshness": {"state": "live"},
    })

    resp = _call(
        _make_db(), monkeypatch, "polymarket",
        td_mocks={"service_get": service_get},
    )

    assert resp.status_code == 200
    assert resp.json() == markets
    service_get.assert_awaited_once_with(
        f"/api/bridge/polymarket/{BOOK_ID}",
        timeout=relay.POLYMARKET_TIMEOUT_S,
    )


@pytest.mark.parametrize("payload", [
    [],
    {"status": "ok", "configured_markets": ["m"]},
    {"status": "mystery", "markets": []},
    {
        "status": "unavailable",
        "markets": [{"slug": "m", "probability": 0.4}],
        "freshness": {"state": "stale"},
    },
    {
        "status": "no_data",
        "markets": [],
        "freshness": {"state": "stale"},
    },
])
def test_polymarket_rejects_legacy_or_incomplete_shapes(monkeypatch, payload):
    service_get = AsyncMock(return_value=payload)

    resp = _call(
        _make_db(), monkeypatch, "polymarket",
        td_mocks={"service_get": service_get},
    )

    assert resp.status_code == 502
    assert "unexpected shape" in resp.json()["detail"]


def test_polymarket_unavailable_never_unwraps_stale_history(monkeypatch):
    service_get = AsyncMock(return_value={
        "status": "unavailable",
        "configured_markets": ["m"],
        "missing_markets": ["m"],
        "markets": [],
        "freshness": {"state": "stale"},
        "last_observation": {
            "markets": [{"slug": "m", "probability": 0.4}],
            "observed_at": "2026-08-17T01:00:00+00:00",
        },
    })

    resp = _call(
        _make_db(), monkeypatch, "polymarket",
        td_mocks={"service_get": service_get},
    )

    assert resp.status_code == 200
    assert resp.json() == []


def test_diff_and_brief_pass_the_book_id(monkeypatch):
    run_command = AsyncMock(return_value={"changes": []})
    resp = _call(_make_db(), monkeypatch, "diff",
                 td_mocks={"run_command": run_command})
    assert resp.status_code == 200
    run_command.assert_awaited_once_with(
        "thesis.diff.last_hour", {"book_id": BOOK_ID})

    run_command = AsyncMock(return_value={"brief": "..."})
    resp = _call(_make_db(), monkeypatch, "brief",
                 td_mocks={"run_command": run_command})
    assert resp.status_code == 200
    run_command.assert_awaited_once_with(
        "outcomes.morning_brief", {"book_id": BOOK_ID})


def test_trades_are_desk_wide(monkeypatch):
    run_command = AsyncMock(return_value=[{"id": "t1"}])
    resp = _call(_make_db(), monkeypatch, "trades",
                 td_mocks={"run_command": run_command})
    assert resp.status_code == 200
    run_command.assert_awaited_once_with("outcomes.open_trades", {})


def test_news_proxies_bridge(monkeypatch):
    service_get = AsyncMock(return_value={"articles": []})
    resp = _call(_make_db(), monkeypatch, "news",
                 td_mocks={"service_get": service_get})
    assert resp.status_code == 200
    service_get.assert_awaited_once_with(
        f"/api/bridge/news/{BOOK_ID}", timeout=relay.NEWS_TIMEOUT_S)


def test_scenario_evaluate_posts_the_what_if(monkeypatch):
    post = AsyncMock(return_value={"scenario_id": "s1", "impact": 0.4})
    resp = _call(_make_db(), monkeypatch, "scenarios/s1/evaluate",
                 method="POST", td_mocks={"post": post})
    assert resp.status_code == 200
    post.assert_awaited_once_with(
        f"/api/v1/theses/{BOOK_ID}/scenarios/s1/evaluate")


# ---------------------------------------------------------------- auth

def test_wrong_room_token_is_401(monkeypatch):
    service_get = AsyncMock()
    resp = _call(_make_db(room_found=False), monkeypatch, "structure",
                 td_mocks={"service_get": service_get})
    assert resp.status_code == 401
    service_get.assert_not_awaited()


def test_non_member_is_403_and_desk_is_never_called(monkeypatch):
    service_get = AsyncMock()
    resp = _call(_make_db(members=set()), monkeypatch, "structure",
                 td_mocks={"service_get": service_get})
    assert resp.status_code == 403
    service_get.assert_not_awaited()


# ---------------------------------------------------------------- binding

def test_unbound_room_is_409_calm_not_an_error(monkeypatch):
    service_get = AsyncMock()
    resp = _call(_make_db(linked_book_id=None), monkeypatch, "structure",
                 td_mocks={"service_get": service_get})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "This room is not bound to a thesis."
    service_get.assert_not_awaited()


def test_snapshot_thesis_id_is_the_binding_fallback(monkeypatch):
    """A room whose binding predates linked_book_id still resolves via the
    pushed snapshot's thesisId — the resolve_book_id order, minus explicit."""
    service_get = AsyncMock(return_value={"id": "japan-rate-shock-graph"})
    db = _make_db(linked_book_id=None,
                  trading_config={"thesisId": "japan-rate-shock-graph"})
    resp = _call(db, monkeypatch, "structure",
                 td_mocks={"service_get": service_get})
    assert resp.status_code == 200
    service_get.assert_awaited_once_with(
        "/api/bridge/structure/japan-rate-shock-graph")


# ---------------------------------------------------------------- failure

def test_dead_desk_is_a_502_with_the_reason(monkeypatch):
    service_get = AsyncMock(side_effect=TradingDeskError("connection refused"))
    resp = _call(_make_db(), monkeypatch, "structure",
                 td_mocks={"service_get": service_get})
    assert resp.status_code == 502
    assert "connection refused" in resp.json()["detail"]


@pytest.mark.parametrize("path,method,mock_name", [
    ("quotes", "GET", "get"),
    ("diff", "GET", "run_command"),
    ("trades", "GET", "run_command"),
    ("brief", "GET", "run_command"),
    ("news", "GET", "service_get"),
    ("scenarios/s1/evaluate", "POST", "post"),
])
def test_every_route_maps_desk_failure_to_502(monkeypatch, path, method,
                                              mock_name):
    mock = AsyncMock(side_effect=TradingDeskError("boom"))
    resp = _call(_make_db(), monkeypatch, path, method=method,
                 td_mocks={mock_name: mock})
    assert resp.status_code == 502
