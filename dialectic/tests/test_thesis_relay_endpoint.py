"""
Contracts for POST /rooms/{room_id}/trading/thesis — the Create Thesis flow
that mints a book on tradingDesk born bound to its room.

Strategy matches tests/test_prediction_relay_endpoint.py — FastAPI dependency
overrides + a fake db routing fetchrow by table. tradingDesk is mocked at
thesis_relay.td.{service_post,post}; no live Postgres, no live desk.

The ordering contract matters most: token registration BEFORE book creation
(a leftover registration is harmless; a book Dialectic can't hear from is
not), and the local link LAST (a td failure must never leave the room
pointing at a book that does not exist).
"""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.thesis_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm.tradingdesk_client import TradingDeskError

ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
ROOM_TOKEN = "room-token-secret"

REQUEST_BODY = {
    "title": "AI Bubble Deflation",
    "claim": "Capex cuts cascade into earnings misses",
    "monthly_budget": 4000,
}


def _make_db(room_found=True, linked_book_id=None, members=None):
    if members is None:
        members = {CALLER_ID}
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            if not room_found:
                return None
            return {"token": ROOM_TOKEN, "linked_book_id": linked_book_id}
        if "FROM room_memberships" in query:
            _room_id, user_id = params
            return {"?column?": 1} if user_id in members else None
        return None

    fake_db.fetchrow = AsyncMock(side_effect=fetchrow)
    fake_db.execute = AsyncMock(return_value=None)
    return fake_db


def _create(fake_db, monkeypatch, *, service_post, post, body=None):
    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[relay.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: ROOM_TOKEN
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )
    monkeypatch.setattr(relay.td, "service_post", service_post)
    monkeypatch.setattr(relay.td, "post", post)
    try:
        return TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/trading/thesis",
            json=REQUEST_BODY if body is None else body,
        )
    finally:
        main_mod.app.dependency_overrides.clear()


def test_create_registers_token_then_mints_a_bound_book(monkeypatch):
    fake_db = _make_db()
    service_post = AsyncMock(return_value={"ok": True, "room_id": str(ROOM_ID)})
    post = AsyncMock(return_value={"id": "ai-bubble-deflation-graph",
                                   "filename": "ai-bubble-deflation-graph.json"})

    resp = _create(fake_db, monkeypatch, service_post=service_post, post=post)

    assert resp.status_code == 200
    assert resp.json() == {"book_id": "ai-bubble-deflation-graph",
                           "title": "AI Bubble Deflation"}

    service_post.assert_awaited_once_with(
        "/api/bridge/room-token",
        json_body={"room_id": str(ROOM_ID), "token": ROOM_TOKEN},
    )
    post.assert_awaited_once()
    td_body = post.await_args.kwargs["json_body"]
    assert td_body["meta"]["dialecticRoomId"] == str(ROOM_ID)
    assert td_body["meta"]["title"] == "AI Bubble Deflation"
    assert td_body["meta"]["monthlyBudget"] == 4000
    assert td_body["nodes"] == [] and td_body["edges"] == []

    # Local writes: the link, then the THESIS_CREATED event.
    sqls = [c.args[0] for c in fake_db.execute.await_args_list]
    assert any("UPDATE rooms SET linked_book_id" in s for s in sqls)
    assert any("INSERT INTO events" in s for s in sqls)


def test_already_bound_room_is_a_409_and_touches_nothing(monkeypatch):
    fake_db = _make_db(linked_book_id="iran-hormuz-graph")
    service_post, post = AsyncMock(), AsyncMock()

    resp = _create(fake_db, monkeypatch, service_post=service_post, post=post)

    assert resp.status_code == 409
    service_post.assert_not_awaited()
    post.assert_not_awaited()
    fake_db.execute.assert_not_awaited()


def test_invalid_room_token_is_401(monkeypatch):
    fake_db = _make_db(room_found=False)
    service_post, post = AsyncMock(), AsyncMock()

    resp = _create(fake_db, monkeypatch, service_post=service_post, post=post)

    assert resp.status_code == 401
    service_post.assert_not_awaited()


def test_non_member_is_403(monkeypatch):
    fake_db = _make_db(members=set())
    service_post, post = AsyncMock(), AsyncMock()

    resp = _create(fake_db, monkeypatch, service_post=service_post, post=post)

    assert resp.status_code == 403
    service_post.assert_not_awaited()


def test_token_registration_failure_is_502_and_no_book_is_created(monkeypatch):
    fake_db = _make_db()
    service_post = AsyncMock(side_effect=TradingDeskError("desk down"))
    post = AsyncMock()

    resp = _create(fake_db, monkeypatch, service_post=service_post, post=post)

    assert resp.status_code == 502
    post.assert_not_awaited()
    fake_db.execute.assert_not_awaited()


def test_book_creation_failure_is_502_and_nothing_links(monkeypatch):
    """A retry after the desk recovers must be a fresh create — the only
    leftover is an idempotent token registration, which never pushes on
    its own."""
    fake_db = _make_db()
    service_post = AsyncMock(return_value={"ok": True})
    post = AsyncMock(side_effect=TradingDeskError("builder refused"))

    resp = _create(fake_db, monkeypatch, service_post=service_post, post=post)

    assert resp.status_code == 502
    fake_db.execute.assert_not_awaited()


def test_missing_book_id_in_td_answer_is_502(monkeypatch):
    fake_db = _make_db()
    service_post = AsyncMock(return_value={"ok": True})
    post = AsyncMock(return_value={"filename": "x.json"})  # no id

    resp = _create(fake_db, monkeypatch, service_post=service_post, post=post)

    assert resp.status_code == 502
    fake_db.execute.assert_not_awaited()


def test_blank_title_is_422(monkeypatch):
    fake_db = _make_db()
    service_post, post = AsyncMock(), AsyncMock()

    resp = _create(
        fake_db, monkeypatch, service_post=service_post, post=post,
        body={"title": "   "},
    )

    assert resp.status_code == 422
    service_post.assert_not_awaited()
