"""
Contracts for POST /rooms/{room_id}/predictions/{prediction_id}/resolve-accept
— the human tap that settles a deadline-watch proposal by relaying a verdict
to tradingDesk's resolve endpoint.

Strategy matches tests/test_prediction_relay_endpoint.py — FastAPI dependency
overrides + a fake db whose fetchrow answers based on which table the helper
queried. tradingDesk itself is mocked at prediction_relay.td.post; no live
Postgres, no live desk.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

import api.main as main_mod
import api.prediction_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm.tradingdesk_client import TradingDeskError

ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000ab")
PREDICTION_ID = "pred-7"

PROPOSAL = {
    "prediction_id": PREDICTION_ID,
    "statement": "Brent closes above $90 by end of Q3",
    "verdict": "correct",
    "rationale": "Traffic through the strait fell overnight.",
    "evidence": [{"url": "https://reuters.com/s1", "title": "Tankers divert"}],
    "accepted": False,
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


def _make_db(metadata=_DEFAULT, message_found=True, members=None, room_token_valid=True):
    """Fake db routing fetchrow by the table the caller queried."""
    if members is None:
        members = {CALLER_ID}
    if metadata is _DEFAULT:
        metadata = {"source": "prediction_watch",
                    "resolution_proposal": dict(PROPOSAL)}
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            return {"?column?": 1} if room_token_valid else None
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


def _resolve(fake_db, monkeypatch, td_post, verdict="correct", prediction_id=PREDICTION_ID):
    """Run the resolve-accept call against overridden deps."""
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
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: "tok"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )
    monkeypatch.setattr(relay.td, "post", td_post)
    monkeypatch.setattr(relay, "claim_operation", claim)
    monkeypatch.setattr(relay, "succeed_operation", succeed)
    monkeypatch.setattr(relay, "fail_operation", fail)
    try:
        return TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/predictions/{prediction_id}/resolve-accept",
            json={"verdict": verdict},
        )
    finally:
        main_mod.app.dependency_overrides.clear()


def test_resolve_accept_relays_the_verdict_and_stamps_accepted(monkeypatch):
    fake_db = _make_db()
    resolved = {"id": PREDICTION_ID, "resolution": "correct",
                "resolved_at": "2026-08-13T00:00:00Z"}
    post = AsyncMock(return_value=resolved)

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 200
    assert resp.json() == resolved
    post.assert_awaited_once_with(
        f"/api/predictions/{PREDICTION_ID}/resolve",
        json_body={
            "resolution": "correct",
            "source_key": f"resolution:{MESSAGE_ID}:resolution_proposal",
        },
    )
    fake_db._claim.assert_awaited_once_with(
        fake_db._pool,
        room_id=ROOM_ID,
        kind="resolution",
        operation_key=f"resolution:{MESSAGE_ID}:resolution_proposal",
        initiated_by=CALLER_ID,
        source_message_id=MESSAGE_ID,
        proposal_slot="resolution_proposal",
    )
    fake_db._succeed.assert_awaited_once()
    assert fake_db._succeed.await_args.kwargs["result"] == resolved


def test_the_humans_verdict_is_what_gets_relayed(monkeypatch):
    """The card offers both buttons: a human who disagrees with the machine's
    proposed verdict settles the prediction THEIR way. The server requires a
    valid literal and a live proposal, not agreement with the proposal."""
    fake_db = _make_db()  # proposal verdict is "correct"
    post = AsyncMock(return_value={"id": PREDICTION_ID})

    resp = _resolve(fake_db, monkeypatch, post, verdict="incorrect")

    assert resp.status_code == 200
    post.assert_awaited_once_with(
        f"/api/predictions/{PREDICTION_ID}/resolve",
        json_body={
            "resolution": "incorrect",
            "source_key": f"resolution:{MESSAGE_ID}:resolution_proposal",
        },
    )


def test_message_without_a_proposal_is_a_404(monkeypatch):
    fake_db = _make_db(metadata={"source": "prediction_watch"})
    post = AsyncMock()

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 404
    post.assert_not_awaited()
    fake_db._succeed.assert_not_awaited()


def test_unknown_proposal_is_a_404(monkeypatch):
    fake_db = _make_db(message_found=False)
    post = AsyncMock()

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 404
    post.assert_not_awaited()


def test_already_accepted_is_a_409_and_never_reposts(monkeypatch):
    accepted = {**PROPOSAL, "accepted": True}
    fake_db = _make_db(metadata={"source": "prediction_watch",
                                 "resolution_proposal": accepted})
    post = AsyncMock()

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 409
    post.assert_not_awaited()
    fake_db._succeed.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_succeeded_resolution_replays_the_recorded_result(monkeypatch):
    accepted = {**PROPOSAL, "accepted": True}
    fake_db = _make_db(
        metadata={"source": "prediction_watch", "resolution_proposal": accepted}
    )
    fake_db._operation_status = "succeeded"
    fake_db._external_result = {"id": PREDICTION_ID, "resolution": "correct"}
    post = AsyncMock()

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 200
    assert resp.json() == fake_db._external_result
    post.assert_not_awaited()
    fake_db._fail.assert_not_awaited()


def test_tradingdesk_failure_is_a_502_and_the_proposal_stays_open(monkeypatch):
    """The proposal must NOT be marked accepted, so a retry after the desk
    recovers is a fresh accept rather than a conflict."""
    fake_db = _make_db()
    post = AsyncMock(side_effect=TradingDeskError("tradingDesk unreachable"))

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 502
    fake_db._succeed.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_an_invalid_verdict_literal_is_a_422(monkeypatch):
    fake_db = _make_db()
    post = AsyncMock()

    resp = _resolve(fake_db, monkeypatch, post, verdict="unclear")

    assert resp.status_code == 422
    post.assert_not_awaited()


def test_non_member_holding_a_valid_room_token_is_rejected(monkeypatch):
    fake_db = _make_db(members=set())  # caller is NOT a member
    post = AsyncMock()

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 403
    post.assert_not_awaited()


def test_invalid_room_token_is_rejected(monkeypatch):
    fake_db = _make_db(room_token_valid=False)
    post = AsyncMock()

    resp = _resolve(fake_db, monkeypatch, post)

    assert resp.status_code == 401
    post.assert_not_awaited()
