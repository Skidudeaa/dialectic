"""
Contracts for POST /rooms/{room_id}/trading/trades/accept — the human tap
that fills Claude's proposed paper trade on tradingDesk, logging the paired
forecast into the claims ledger first.

Strategy matches tests/test_prediction_relay_endpoint.py — FastAPI dependency
overrides + a fake db routing fetchrow by table; tradingDesk mocked at
trading_relay.td; the external_operations lease mocked at the relay's own
imported names. The contracts that matter: re-validation at the write
(metadata is a document, not a trust boundary), prediction-then-fill ORDER
with the derived source_keys, the discretionary path skipping the prediction
write, replay returning the recorded result without re-POSTing, and a dead
desk releasing the operation so a retry is fresh.
"""

import asyncio
from types import SimpleNamespace
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
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000ab")
ROOM_TOKEN = "room-token-secret"
BOOK_ID = "iran-hormuz-graph"

OPERATION_KEY = f"trade:{MESSAGE_ID}:trade_proposal"

FORECAST = {
    "statement": "XOP closes above $150 by end of Q3",
    "confidence": 0.65,
    "deadline": "2026-09-30",
}

PROPOSAL = {
    "symbol": "XOP",
    "side": "buy",
    "dollars": 2000,
    "rationale": "brent node fired, refiners lag",
    "node_id": "brent",
    "prediction": dict(FORECAST),
    "accepted": False,
}

EXPECTED_PREDICTION_BODY = {
    "statement": FORECAST["statement"],
    "confidence": 0.65,
    "deadline": "2026-09-30",
    "tags": ["dialectic"],
    "source_type": "llm",
    "source_label": "Claude",
    "linked_book_id": BOOK_ID,
    "source_key": f"{OPERATION_KEY}:prediction",
}

EXPECTED_FILL_BODY = {
    "book_id": BOOK_ID,
    "kind": "trade",
    "symbol": "XOP",
    "side": "buy",
    "dollars": 2000.0,
    "rationale": "brent node fired, refiners lag",
    "node_id": "brent",
    "prediction_id": "pred-1",
    "source_key": OPERATION_KEY,
}

_DEFAULT = object()


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


def _make_db(metadata=_DEFAULT, message_found=True, members=None,
             room_found=True, linked_book_id=BOOK_ID):
    """Fake db routing fetchrow by the table the caller queried."""
    if members is None:
        members = {CALLER_ID}
    if metadata is _DEFAULT:
        metadata = {"trade_proposal": dict(PROPOSAL)}
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            if not room_found:
                return None
            return {"token": ROOM_TOKEN, "linked_book_id": linked_book_id,
                    "trading_config": None}
        if "FROM room_memberships" in query:
            _room_id, user_id = params
            return {"?column?": 1} if user_id in members else None
        if "FROM messages" in query:
            if not message_found:
                return None
            return {"id": MESSAGE_ID, "metadata": metadata}
        return None

    fake_db.fetchrow = AsyncMock(side_effect=fetchrow)
    fake_db.execute = AsyncMock(return_value=None)
    fake_db.transaction = lambda: _AsyncContext()
    fake_db._operation_status = "pending"
    fake_db._external_result = None
    return fake_db


def _accept(fake_db, monkeypatch, td_post):
    """Run the accept call against overridden deps; returns the response."""
    operation = SimpleNamespace(
        status=fake_db._operation_status,
        external_result=fake_db._external_result,
    )
    claim = AsyncMock(return_value=operation)
    succeed = AsyncMock()
    fail = AsyncMock()
    fake_db._claim = claim
    fake_db._succeed = succeed
    fake_db._fail = fail
    fake_db._pool = _Pool(fake_db)

    main_mod.app.dependency_overrides[relay.get_pool] = lambda: fake_db._pool
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: ROOM_TOKEN
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True,
        display_name="Caller",
    )
    monkeypatch.setattr(relay.td, "post", td_post)
    monkeypatch.setattr(relay, "claim_operation", claim)
    monkeypatch.setattr(relay, "succeed_operation", succeed)
    monkeypatch.setattr(relay, "fail_operation", fail)
    try:
        return TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/trading/trades/accept",
            json={"message_id": str(MESSAGE_ID)},
        )
    finally:
        main_mod.app.dependency_overrides.clear()


def test_accept_writes_prediction_then_fill_with_derived_source_keys(monkeypatch):
    """The happy path: BOTH bodies, both source_keys, prediction FIRST."""
    fake_db = _make_db()
    prediction = {"id": "pred-1", "user": "dialectic", **EXPECTED_PREDICTION_BODY}
    fill = {"id": 7, **EXPECTED_FILL_BODY, "quantity": 14.2, "price": 140.8}

    calls = []

    async def post(path, *, json_body=None, **kwargs):
        calls.append((path, json_body, kwargs.get("timeout")))
        return prediction if path == "/api/predictions" else fill

    resp = _accept(fake_db, monkeypatch, AsyncMock(side_effect=post))

    assert resp.status_code == 200
    assert resp.json() == {"fill": fill, "prediction": prediction}
    # Order is the contract: the claim lands in the ledger, THEN the fill
    # carries its id — a crash between the two replays off the source_keys.
    assert [c[0] for c in calls] == ["/api/predictions", "/api/portfolio/fills"]
    assert calls[0][1] == EXPECTED_PREDICTION_BODY
    assert calls[1][1] == EXPECTED_FILL_BODY
    # Seam law: the fill POST must outlive td's cold quote path (~18.5s).
    assert calls[1][2] == relay.QUOTES_TIMEOUT_S
    fake_db._claim.assert_awaited_once_with(
        fake_db._pool,
        room_id=ROOM_ID,
        kind="trade",
        operation_key=OPERATION_KEY,
        initiated_by=CALLER_ID,
        source_message_id=MESSAGE_ID,
        proposal_slot="trade_proposal",
    )
    fake_db._succeed.assert_awaited_once()
    assert fake_db._succeed.await_args.kwargs["result"] == {
        "fill": fill, "prediction": prediction,
    }


def test_forecast_resolution_spec_is_forwarded(monkeypatch):
    spec = {"kind": "price_cross", "symbol": "XOP",
            "comparator": "above", "threshold": 150.0}
    proposal = {**PROPOSAL,
                "prediction": {**FORECAST, "resolution_spec": dict(spec)}}
    fake_db = _make_db(metadata={"trade_proposal": proposal})
    calls = []

    async def post(path, *, json_body=None, **kwargs):
        calls.append((path, json_body))
        return {"id": "pred-1"} if path == "/api/predictions" else {"id": 7}

    resp = _accept(fake_db, monkeypatch, AsyncMock(side_effect=post))

    assert resp.status_code == 200
    assert calls[0][1]["resolution_spec"] == spec


def test_discretionary_accept_skips_the_prediction_write(monkeypatch):
    """Only the fill lands, its rationale labeled unscored — an explicit
    label, never a fabricated confidence."""
    proposal = {"symbol": "XOP", "side": "sell", "dollars": 500,
                "rationale": "trim into strength", "discretionary": True,
                "accepted": False}
    fake_db = _make_db(metadata={"trade_proposal": proposal})
    calls = []

    async def post(path, *, json_body=None, **kwargs):
        calls.append((path, json_body))
        return {"id": 9, **(json_body or {})}

    resp = _accept(fake_db, monkeypatch, AsyncMock(side_effect=post))

    assert resp.status_code == 200
    assert [path for path, _ in calls] == ["/api/portfolio/fills"]
    body = calls[0][1]
    assert body["prediction_id"] is None
    assert body["rationale"] == "[unscored discretionary] trim into strength"
    assert body["source_key"] == OPERATION_KEY
    assert resp.json()["prediction"] is None


@pytest.mark.parametrize("broken", [
    {"symbol": ""},
    {"symbol": "CASH"},
    {"side": "short"},
    {"dollars": 0},
    {"dollars": "a lot"},
    {"rationale": " "},
    {"prediction": None, "discretionary": None},           # neither
    {"discretionary": True},                               # both
    {"prediction": {**FORECAST, "confidence": 7.5}},       # the 75.0 poison
    {"prediction": {**FORECAST, "deadline": "someday"}},
    {"prediction": {**FORECAST,
                    "resolution_spec": {"kind": "coin_flip"}}},
])
def test_malformed_stored_proposal_is_a_422_and_never_posts(monkeypatch, broken):
    """Metadata is a document, not a trust boundary — every field the tool
    checked at draft time is re-checked at the write."""
    proposal = {**PROPOSAL, **broken}
    if proposal.get("prediction") is None:
        proposal.pop("prediction", None)
    if proposal.get("discretionary") is None:
        proposal.pop("discretionary", None)
    fake_db = _make_db(metadata={"trade_proposal": proposal})
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 422
    assert "malformed" in resp.json()["detail"]
    post.assert_not_awaited()
    fake_db._succeed.assert_not_awaited()


def test_message_without_a_trade_proposal_is_a_404(monkeypatch):
    fake_db = _make_db(metadata={"proposal": {"statement": "not a trade"}})
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 404
    post.assert_not_awaited()


def test_unknown_message_is_a_404(monkeypatch):
    fake_db = _make_db(message_found=False)
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 404
    post.assert_not_awaited()


def test_unbound_room_is_a_409_before_anything_else(monkeypatch):
    """Same calm unbound mapping as every cockpit read."""
    fake_db = _make_db(linked_book_id=None)
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 409
    assert "not bound" in resp.json()["detail"]
    post.assert_not_awaited()


def test_already_accepted_is_a_409_and_never_reposts(monkeypatch):
    fake_db = _make_db(metadata={"trade_proposal": {**PROPOSAL, "accepted": True}})
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 409
    post.assert_not_awaited()
    fake_db._succeed.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_succeeded_operation_replays_the_recorded_result(monkeypatch):
    fake_db = _make_db(metadata={"trade_proposal": {**PROPOSAL, "accepted": True}})
    fake_db._operation_status = "succeeded"
    fake_db._external_result = {"fill": {"id": 7}, "prediction": {"id": "pred-1"}}
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 200
    assert resp.json() == {"fill": {"id": 7}, "prediction": {"id": "pred-1"}}
    post.assert_not_awaited()
    fake_db._fail.assert_not_awaited()


def test_dead_desk_is_a_502_and_the_operation_is_released(monkeypatch):
    """The proposal must NOT be marked accepted — a retry after the desk
    recovers is a fresh accept, and both td writes replay off source_keys."""
    fake_db = _make_db()
    post = AsyncMock(side_effect=TradingDeskError("tradingDesk unreachable"))

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 502
    fake_db._succeed.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_desk_crash_between_the_two_writes_is_released_for_retry(monkeypatch):
    """Prediction lands, fill fails: the operation is failed (not finalized),
    so a retry re-runs BOTH writes — td's source_key idempotency makes the
    prediction re-POST return the same row."""
    fake_db = _make_db()

    async def post(path, *, json_body=None, **kwargs):
        if path == "/api/predictions":
            return {"id": "pred-1"}
        raise TradingDeskError("tradingDesk /api/portfolio/fills timed out")

    resp = _accept(fake_db, monkeypatch, AsyncMock(side_effect=post))

    assert resp.status_code == 502
    fake_db._succeed.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_unquoted_symbol_422_maps_to_a_clear_client_error(monkeypatch):
    """td's fill door 422s a symbol its quote feed cannot price; the relay
    names the likely cause instead of calling the desk dead."""
    fake_db = _make_db()

    async def post(path, *, json_body=None, **kwargs):
        if path == "/api/predictions":
            return {"id": "pred-1"}
        raise TradingDeskError("tradingDesk /api/portfolio/fills returned HTTP 422")

    resp = _accept(fake_db, monkeypatch, AsyncMock(side_effect=post))

    assert resp.status_code == 422
    assert "XOP" in resp.json()["detail"]
    fake_db._succeed.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_non_member_holding_a_valid_room_token_is_rejected(monkeypatch):
    fake_db = _make_db(members=set())
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 403
    post.assert_not_awaited()


def test_invalid_room_token_is_rejected(monkeypatch):
    fake_db = _make_db(room_found=False)
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 401
    post.assert_not_awaited()
