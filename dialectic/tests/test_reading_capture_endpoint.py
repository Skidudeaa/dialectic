"""HTTP contract for direct Safari browser captures.

These tests keep authentication, request validation, and the no-refetch seam
separate from the real-PostgreSQL ordering tests.
"""

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

import api.main as main_mod
import api.reading_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user


ROOM_ID = UUID("00000000-0000-4000-8000-000000000042")
CALLER_ID = UUID("00000000-0000-4000-8000-0000000000aa")
CAPTURE_ID = UUID("00000000-0000-4000-8000-0000000000ab")
MARKDOWN = "# Browser truth\n\nRendered after JavaScript.\n"


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


def _payload(**overrides: object) -> dict[str, object]:
    markdown = str(overrides.pop("markdown", MARKDOWN))
    payload: dict[str, object] = {
        "capture_id": str(CAPTURE_ID),
        "url": "https://example.com/rendered",
        "canonical_url": "https://example.com/rendered",
        "title": "Browser truth",
        "author": "A. Reporter",
        "site": "Example",
        "published": "2026-08-28",
        "description": "A rendered-page description.",
        "language": "en",
        "word_count": 5,
        "capture_mode": "article",
        "markdown": markdown,
        "content_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        "captured_at": datetime(2026, 8, 28, 12, tzinfo=timezone.utc).isoformat(),
        "note": None,
        "extraction": {
            "engine": "defuddle",
            "engine_version": "0.19.3",
            "client_version": "0.1.0",
            "fallback_reason": None,
        },
    }
    payload.update(overrides)
    return payload


def _db(*, room_token_valid: bool = True, members: set[UUID] | None = None):
    members = {CALLER_ID} if members is None else members
    db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            return {"ok": 1} if room_token_valid else None
        if "FROM room_memberships" in query:
            return {"ok": 1} if params[1] in members else None
        return None

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    db.transaction = lambda: _AsyncContext()
    return db


def _post(
    monkeypatch,
    payload: dict[str, object],
    *,
    db=None,
    authenticated: bool = True,
    twin_error: Exception | None = None,
):
    db = db or _db()
    result = {
        "reading": {
            "id": "00000000-0000-4000-8000-000000000101",
            "room_id": str(ROOM_ID),
            "url": payload.get("canonical_url") or payload["url"],
            "title": payload.get("title"),
            "site": payload.get("site"),
            "source": "browser_capture",
            "current_revision_id": "00000000-0000-4000-8000-000000000102",
            "current_captured_at": payload["captured_at"],
            "content_sha256": payload["content_sha256"],
        },
        "revision": {
            "id": "00000000-0000-4000-8000-000000000102",
            "capture_id": str(CAPTURE_ID),
            "capture_mode": payload.get("capture_mode"),
            "content_sha256": payload["content_sha256"],
            "captured_at": payload["captured_at"],
            "received_at": payload["captured_at"],
            "is_current": True,
        },
        "idempotent_replay": False,
    }
    save = AsyncMock(return_value=result)
    twin = AsyncMock(side_effect=twin_error)
    monkeypatch.setattr(relay.reading_mod, "save_browser_capture", save)
    monkeypatch.setattr(relay.reading_mod, "ensure_reading_memory_twin", twin)
    extract = AsyncMock()
    monkeypatch.setattr(relay.dc, "extract_article", extract)
    main_mod.app.dependency_overrides[relay.get_pool] = lambda: _Pool(db)
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: "room-token"
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=CALLER_ID,
            email="caller@example.com",
            email_verified=True,
            display_name="Caller",
        )
    try:
        response = TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/reading/capture",
            json=payload,
        )
    finally:
        main_mod.app.dependency_overrides.clear()
    return response, save, twin, extract


def test_capture_requires_bearer_authentication(monkeypatch):
    response, save, _, _ = _post(monkeypatch, _payload(), authenticated=False)
    assert response.status_code == 401
    save.assert_not_awaited()


def test_capture_rejects_wrong_room_token(monkeypatch):
    response, save, _, _ = _post(
        monkeypatch, _payload(), db=_db(room_token_valid=False),
    )
    assert response.status_code == 401
    save.assert_not_awaited()


def test_capture_rejects_nonmember(monkeypatch):
    response, save, _, _ = _post(monkeypatch, _payload(), db=_db(members=set()))
    assert response.status_code == 403
    save.assert_not_awaited()


def test_capture_rejects_empty_markdown(monkeypatch):
    response, save, _, _ = _post(monkeypatch, _payload(markdown=""))
    assert response.status_code == 422
    save.assert_not_awaited()


def test_capture_rejects_hash_mismatch(monkeypatch):
    response, save, _, _ = _post(
        monkeypatch,
        _payload(content_sha256="0" * 64),
    )
    assert response.status_code == 422
    assert "hash" in response.json()["detail"].lower()
    save.assert_not_awaited()


def test_capture_enforces_utf8_byte_ceiling(monkeypatch):
    markdown = "\N{SNOWMAN}" * 700_000
    response, save, _, _ = _post(monkeypatch, _payload(markdown=markdown))
    assert response.status_code == 413
    save.assert_not_awaited()


def test_capture_rejects_active_url(monkeypatch):
    response, save, _, _ = _post(
        monkeypatch, _payload(url="javascript:alert(1)", canonical_url=None),
    )
    assert response.status_code == 422
    save.assert_not_awaited()


def test_capture_rejects_malformed_url_authority_without_database_write(monkeypatch):
    for url in ("https://exa mple.com/article", "https://example.com:bad/article"):
        response, save, _, _ = _post(
            monkeypatch,
            _payload(url=url, canonical_url=None),
        )
        assert response.status_code == 422
        save.assert_not_awaited()


def test_capture_rejects_non_postgresql_text_without_database_write(monkeypatch):
    nul_payload = _payload(markdown="valid prefix\x00invalid suffix")
    response, save, _, _ = _post(monkeypatch, nul_payload)
    assert response.status_code == 422
    save.assert_not_awaited()

    surrogate_payload = _payload()
    surrogate_payload["markdown"] = "\ud800"
    surrogate_payload["content_sha256"] = "0" * 64
    response, save, _, _ = _post(monkeypatch, surrogate_payload)
    assert response.status_code == 422
    save.assert_not_awaited()


def test_capture_files_exact_browser_body_without_refetch_or_llm(monkeypatch):
    payload = _payload()
    response, save, twin, extract = _post(monkeypatch, payload)

    assert response.status_code == 200
    assert response.json()["reading"]["source"] == "browser_capture"
    save.assert_awaited_once()
    assert save.await_args.kwargs["capture"]["markdown"] == MARKDOWN
    assert save.await_args.kwargs["capture"]["content_sha256"] == payload["content_sha256"]
    extract.assert_not_awaited()
    twin.assert_awaited_once()


def test_twin_failure_cannot_rollback_a_committed_capture(monkeypatch):
    response, save, twin, _ = _post(
        monkeypatch,
        _payload(),
        twin_error=RuntimeError("embedding unavailable"),
    )
    assert response.status_code == 200
    save.assert_awaited_once()
    twin.assert_awaited_once()
