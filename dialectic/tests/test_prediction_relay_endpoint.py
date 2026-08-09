"""
Contracts for POST /rooms/{room_id}/predictions/accept — the human tap that
turns Claude's drafted prediction into a logged one on tradingDesk.

Strategy matches tests/test_calibration_endpoint.py — FastAPI dependency
overrides + a fake db whose fetchrow answers based on which table the helper
queried. tradingDesk itself is mocked at prediction_relay.td.post; no live
Postgres, no live desk.
"""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.prediction_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm.tradingdesk_client import TradingDeskError

ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000ab")

PROPOSAL = {
    "statement": "Brent closes above $90 by end of Q3",
    "confidence": 0.7,
    "deadline": "2026-09-30",
    "linked_book_id": "iran-hormuz-graph",
    "accepted": False,
}

EXPECTED_TD_BODY = {
    "statement": "Brent closes above $90 by end of Q3",
    "confidence": 0.7,
    "deadline": "2026-09-30",
    "tags": ["dialectic"],
    "linked_book_id": "iran-hormuz-graph",
}


_DEFAULT = object()


def _make_db(metadata=_DEFAULT, message_found=True, members=None, room_token_valid=True):
    """Fake db routing fetchrow by the table the caller queried."""
    if members is None:
        members = {CALLER_ID}
    if metadata is _DEFAULT:
        metadata = {"proposal": dict(PROPOSAL)}
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
    return fake_db


def _accept(fake_db, monkeypatch, td_post):
    """Run the accept call against overridden deps; returns the response."""
    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[relay.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: "tok"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )
    monkeypatch.setattr(relay.td, "post", td_post)
    try:
        return TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/predictions/accept",
            json={"message_id": str(MESSAGE_ID)},
        )
    finally:
        main_mod.app.dependency_overrides.clear()


def test_accept_relays_the_proposal_and_marks_it_accepted(monkeypatch):
    fake_db = _make_db()
    created = {"id": "pred-1", "user": "dialectic", **EXPECTED_TD_BODY}
    post = AsyncMock(return_value=created)

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 200
    assert resp.json() == created
    post.assert_awaited_once_with("/api/predictions", json_body=EXPECTED_TD_BODY)
    fake_db.execute.assert_awaited_once()
    update_sql = fake_db.execute.await_args.args[0]
    assert "jsonb_set" in update_sql
    assert fake_db.execute.await_args.args[1] == MESSAGE_ID


def test_message_without_a_proposal_is_a_404(monkeypatch):
    fake_db = _make_db(metadata={"tools": {"iterations": 1, "calls": []}})
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 404
    post.assert_not_awaited()
    fake_db.execute.assert_not_awaited()


def test_message_with_no_metadata_at_all_is_a_404(monkeypatch):
    fake_db = _make_db(metadata=None)
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


def test_already_accepted_is_a_409_and_never_reposts(monkeypatch):
    accepted = {**PROPOSAL, "accepted": True}
    fake_db = _make_db(metadata={"proposal": accepted})
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 409
    post.assert_not_awaited()
    fake_db.execute.assert_not_awaited()


def test_tradingdesk_failure_is_a_502_and_the_draft_stays_open(monkeypatch):
    """The proposal must NOT be marked accepted, so a retry after the desk
    recovers is a fresh accept rather than a conflict."""
    fake_db = _make_db()
    post = AsyncMock(side_effect=TradingDeskError("tradingDesk unreachable"))

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 502
    fake_db.execute.assert_not_awaited()


def test_non_member_holding_a_valid_room_token_is_rejected(monkeypatch):
    fake_db = _make_db(members=set())  # caller is NOT a member
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 403
    post.assert_not_awaited()


def test_invalid_room_token_is_rejected(monkeypatch):
    fake_db = _make_db(room_token_valid=False)
    post = AsyncMock()

    resp = _accept(fake_db, monkeypatch, post)

    assert resp.status_code == 401
    post.assert_not_awaited()
