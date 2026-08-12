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
            return {"token": ROOM_TOKEN, "linked_book_id": linked_book_id,
                    "primary_provider": "anthropic",
                    "primary_model": "claude-sonnet-4-6"}
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


def test_create_carries_an_accepted_draft_through(monkeypatch):
    """The Accept tap sends the drafted nodes/edges through create — they
    must reach td's builder verbatim."""
    fake_db = _make_db()
    service_post = AsyncMock(return_value={"ok": True})
    post = AsyncMock(return_value={"id": "ai-bubble-deflation-graph"})
    nodes = [{"id": "shock", "label": "Shock", "type": "event", "phase": 1,
              "state": "monitoring", "x": 100, "y": 60}]
    edges = []

    resp = _create(
        fake_db, monkeypatch, service_post=service_post, post=post,
        body={**REQUEST_BODY, "nodes": nodes, "edges": edges},
    )

    assert resp.status_code == 200
    td_body = post.await_args.kwargs["json_body"]
    assert td_body["nodes"] == nodes
    assert td_body["edges"] == edges


# =========================================================================
# DRAFT ENDPOINT — the proposal half of the flow
# =========================================================================


def _draft(fake_db, monkeypatch, *, drafter, body=None):
    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[relay.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: ROOM_TOKEN
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )
    monkeypatch.setattr(relay, "draft_thesis_graph", drafter)
    try:
        return TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/trading/thesis/draft",
            json=REQUEST_BODY if body is None else body,
        )
    finally:
        main_mod.app.dependency_overrides.clear()


DRAFT = {
    "nodes": [{"id": "shock", "label": "Shock", "type": "event", "phase": 1,
               "state": "monitoring", "x": 100, "y": 60}],
    "edges": [],
    "rationale": "The spine.",
}


def test_draft_returns_the_proposal_and_writes_nothing(monkeypatch):
    fake_db = _make_db()
    drafter = AsyncMock(return_value=dict(DRAFT))

    resp = _draft(fake_db, monkeypatch, drafter=drafter)

    assert resp.status_code == 200
    assert resp.json() == DRAFT
    # The room's own primary model drafts.
    assert drafter.await_args.kwargs.get("model") == "claude-sonnet-4-6"
    # Stateless: a proposal must not touch the database.
    fake_db.execute.assert_not_awaited()


def test_draft_on_a_bound_room_is_409(monkeypatch):
    fake_db = _make_db(linked_book_id="iran-hormuz-graph")
    drafter = AsyncMock()

    resp = _draft(fake_db, monkeypatch, drafter=drafter)

    assert resp.status_code == 409
    drafter.assert_not_awaited()


def test_draft_failure_is_502(monkeypatch):
    from llm.thesis_drafter import DraftError
    fake_db = _make_db()
    drafter = AsyncMock(side_effect=DraftError("could not produce a cascade"))

    resp = _draft(fake_db, monkeypatch, drafter=drafter)

    assert resp.status_code == 502
    assert "cascade" in resp.json()["detail"]


def test_draft_requires_membership(monkeypatch):
    fake_db = _make_db(members=set())
    drafter = AsyncMock()

    resp = _draft(fake_db, monkeypatch, drafter=drafter)

    assert resp.status_code == 403
    drafter.assert_not_awaited()


# =========================================================================
# RETIRE — the lifecycle exit
# =========================================================================


def _retire(fake_db, monkeypatch, *, service_post, memory_manager=None):
    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[relay.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: ROOM_TOKEN
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )
    monkeypatch.setattr(relay.td, "service_post", service_post)
    if memory_manager is not None:
        monkeypatch.setattr("memory.manager.MemoryManager", memory_manager)
    try:
        return TestClient(main_mod.app).delete(f"/rooms/{ROOM_ID}/trading/thesis")
    finally:
        main_mod.app.dependency_overrides.clear()


def test_retire_unbinds_td_first_then_clears_locally(monkeypatch):
    fake_db = _make_db(linked_book_id="sovereign-debt-doom-loop-graph")
    service_post = AsyncMock(return_value={"unbound": ["sovereign-debt-doom-loop-graph"]})

    resp = _retire(fake_db, monkeypatch, service_post=service_post)

    assert resp.status_code == 200
    assert resp.json() == {"retired_book_id": "sovereign-debt-doom-loop-graph"}
    service_post.assert_awaited_once_with(
        "/api/bridge/room-unbind", json_body={"room_id": str(ROOM_ID)},
    )
    sqls = [c.args[0] for c in fake_db.execute.await_args_list]
    assert any("linked_book_id = NULL" in s and "trading_config = NULL" in s
               for s in sqls)
    assert any("INSERT INTO events" in s for s in sqls)


def test_retire_without_a_thesis_is_404(monkeypatch):
    fake_db = _make_db(linked_book_id=None)
    service_post = AsyncMock()

    resp = _retire(fake_db, monkeypatch, service_post=service_post)

    assert resp.status_code == 404
    service_post.assert_not_awaited()
    fake_db.execute.assert_not_awaited()


def test_retire_survives_td_refusal_with_binding_intact(monkeypatch):
    """td-first ordering: a failed unbind must leave Dialectic's binding
    alone so the retry is a fresh retire."""
    fake_db = _make_db(linked_book_id="some-graph")
    service_post = AsyncMock(side_effect=TradingDeskError("desk down"))

    resp = _retire(fake_db, monkeypatch, service_post=service_post)

    assert resp.status_code == 502
    fake_db.execute.assert_not_awaited()


def test_retire_invalidates_every_active_thesis_state_row(monkeypatch):
    """Plural on purpose: a racing pair of pushes can twin the slot, and a
    retire must silence every copy."""
    from uuid import uuid4 as _uuid4
    memory_id, twin_id = _uuid4(), _uuid4()
    fake_db = _make_db(linked_book_id="some-graph")

    async def fetch(query, *params):
        if "thesis_state_current" in query:
            return [{"id": memory_id}, {"id": twin_id}]
        return []

    fake_db.fetch = AsyncMock(side_effect=fetch)

    invalidations = []

    class StubManager:
        def __init__(self, db):
            pass

        async def invalidate_memory(self, **kwargs):
            invalidations.append(kwargs)

    service_post = AsyncMock(return_value={"unbound": ["some-graph"]})
    resp = _retire(fake_db, monkeypatch, service_post=service_post,
                   memory_manager=StubManager)

    assert resp.status_code == 200
    assert {i["memory_id"] for i in invalidations} == {memory_id, twin_id}
    assert all("retired" in i["reason"] for i in invalidations)
