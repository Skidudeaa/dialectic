"""
Contracts for POST /rooms/{room_id}/reading/accept — the human tap that
files Claude's drafted reading into the room's library.

Strategy matches tests/test_prediction_relay_endpoint.py — FastAPI dependency
overrides + a fake db whose fetchrow answers based on which table the helper
queried. The sidecar re-fetch is mocked at reading_relay.dc.extract_article
and the write at reading_relay.reading_mod.save_reading; no live Postgres,
no live sidecar.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import api.main as main_mod
import api.reading_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm.defuddle_client import DefuddleError

ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000ab")

PROPOSAL = {
    "url": "https://ex.com/1",
    "title": "Tankers divert",
    "site": "Example News",
    "published": "2026-08-10",
    "summary": "Tanker diversions tightened the straits premium.",
    "key_claims": ["Rates doubled"],
    "accepted": False,
}

ARTICLE = {
    "url": "https://ex.com/1",
    "title": "Tankers divert",
    "author": "A. Reporter",
    "site": "Example News",
    "published": "2026-08-10",
    "word_count": 900,
    "content": "The straits narrowed overnight and the tankers turned.",
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
        metadata = {"reading_proposal": dict(PROPOSAL)}
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


def _accept(fake_db, monkeypatch, extract, save):
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
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: "tok"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )
    monkeypatch.setattr(relay.dc, "extract_article", extract)
    monkeypatch.setattr(relay.reading_mod, "save_reading", save)
    monkeypatch.setattr(relay, "claim_operation", claim)
    monkeypatch.setattr(relay, "succeed_operation", succeed)
    monkeypatch.setattr(relay, "fail_operation", fail)
    try:
        return TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/reading/accept",
            json={"message_id": str(MESSAGE_ID)},
        )
    finally:
        main_mod.app.dependency_overrides.clear()


def test_accept_refetches_and_files_the_article(monkeypatch):
    fake_db = _make_db()
    extract = AsyncMock(return_value=dict(ARTICLE))
    saved_row = {"id": str(uuid4()), "url": "https://ex.com/1",
                 "title": "Tankers divert", "source": "proposal"}
    save = AsyncMock(return_value=saved_row)

    resp = _accept(fake_db, monkeypatch, extract, save)

    assert resp.status_code == 200
    assert resp.json() == saved_row
    extract.assert_awaited_once_with("https://ex.com/1")
    save.assert_awaited_once()
    kwargs = save.await_args.kwargs
    assert kwargs["room_id"] == ROOM_ID
    assert kwargs["article"]["content"].startswith("The straits narrowed")
    assert kwargs["summary"] == PROPOSAL["summary"]
    assert kwargs["key_claims"] == ["Rates doubled"]
    assert kwargs["source"] == "proposal"
    assert kwargs["source_message_id"] == MESSAGE_ID
    assert kwargs["saved_by_user_id"] == CALLER_ID
    fake_db._claim.assert_awaited_once_with(
        fake_db._pool,
        room_id=ROOM_ID,
        kind="reading",
        operation_key=f"reading:{MESSAGE_ID}:reading_proposal",
        initiated_by=CALLER_ID,
        source_message_id=MESSAGE_ID,
        proposal_slot="reading_proposal",
    )
    fake_db._succeed.assert_awaited_once()
    assert fake_db._succeed.await_args.kwargs["result"] == saved_row


def test_second_tap_is_a_conflict(monkeypatch):
    accepted = {**PROPOSAL, "accepted": True}
    fake_db = _make_db(metadata={"reading_proposal": accepted})
    extract = AsyncMock(return_value=dict(ARTICLE))
    save = AsyncMock()

    resp = _accept(fake_db, monkeypatch, extract, save)

    assert resp.status_code == 409
    extract.assert_not_awaited()
    save.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_succeeded_operation_replays_the_filed_reading(monkeypatch):
    accepted = {**PROPOSAL, "accepted": True}
    fake_db = _make_db(metadata={"reading_proposal": accepted})
    fake_db._operation_status = "succeeded"
    fake_db._external_result = {"id": "reading-1", "url": PROPOSAL["url"]}
    extract = AsyncMock()
    save = AsyncMock()

    resp = _accept(fake_db, monkeypatch, extract, save)

    assert resp.status_code == 200
    assert resp.json() == fake_db._external_result
    extract.assert_not_awaited()
    save.assert_not_awaited()


def test_message_without_draft_is_404(monkeypatch):
    fake_db = _make_db(metadata={})
    resp = _accept(fake_db, monkeypatch, AsyncMock(), AsyncMock())
    assert resp.status_code == 404


def test_malformed_draft_is_422(monkeypatch):
    bad = {**PROPOSAL, "summary": ""}
    fake_db = _make_db(metadata={"reading_proposal": bad})
    extract = AsyncMock(return_value=dict(ARTICLE))

    resp = _accept(fake_db, monkeypatch, extract, AsyncMock())

    assert resp.status_code == 422
    extract.assert_not_awaited()


def test_sidecar_failure_is_502_and_leaves_the_draft_open(monkeypatch):
    fake_db = _make_db()
    extract = AsyncMock(side_effect=DefuddleError("unreachable"))
    save = AsyncMock()

    resp = _accept(fake_db, monkeypatch, extract, save)

    assert resp.status_code == 502
    save.assert_not_awaited()
    fake_db._succeed.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_unreadable_refetch_is_422(monkeypatch):
    fake_db = _make_db()
    extract = AsyncMock(return_value={**ARTICLE, "content": ""})
    save = AsyncMock()

    resp = _accept(fake_db, monkeypatch, extract, save)

    assert resp.status_code == 422
    save.assert_not_awaited()
    fake_db._fail.assert_awaited_once()


def test_non_member_is_403(monkeypatch):
    fake_db = _make_db(members=set())
    resp = _accept(fake_db, monkeypatch, AsyncMock(), AsyncMock())
    assert resp.status_code == 403


def test_bad_room_token_is_401(monkeypatch):
    fake_db = _make_db(room_token_valid=False)
    resp = _accept(fake_db, monkeypatch, AsyncMock(), AsyncMock())
    assert resp.status_code == 401
