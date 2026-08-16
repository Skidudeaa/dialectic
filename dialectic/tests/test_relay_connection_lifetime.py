"""Connection-lifetime contracts for relays that wait on another service."""

from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

import api.main as main_mod
import api.reading_relay as reading_relay
import api.trading_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user


ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000bb")
ARTICLE_URL = "https://example.test/article"


class _Connection:
    async def fetchrow(self, query: str, *params: object) -> dict[str, object] | None:
        if "FROM rooms" in query:
            return {
                "token": "room-token-secret",
                "linked_book_id": "iran-hormuz-graph",
                "trading_config": None,
            }
        if "FROM room_memberships" in query:
            return {"?column?": 1}
        if "FROM messages" in query:
            return {"id": MESSAGE_ID, "content": f"read this: {ARTICLE_URL}"}
        return None


class _Acquire:
    def __init__(self, pool: "_TrackingPool") -> None:
        self.pool = pool

    async def __aenter__(self) -> _Connection:
        self.pool.checked_out += 1
        return self.pool.connection

    async def __aexit__(self, *exc_info: object) -> None:
        self.pool.checked_out -= 1


class _TrackingPool:
    def __init__(self) -> None:
        self.connection = _Connection()
        self.checked_out = 0

    def acquire(self) -> _Acquire:
        return _Acquire(self)


def test_network_wait_holds_no_pool_connection(monkeypatch) -> None:
    pool = _TrackingPool()
    checked_out_during_http: list[int] = []

    async def get_quotes(*args: object, **kwargs: object) -> dict[str, list[object]]:
        checked_out_during_http.append(pool.checked_out)
        return {"quotes": []}

    monkeypatch.setattr(relay, "_db_pool", pool)
    monkeypatch.setattr(relay.td, "get", AsyncMock(side_effect=get_quotes))
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: "room-token-secret"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID,
        email="caller@test",
        email_verified=True,
        display_name="Caller",
    )
    try:
        response = TestClient(main_mod.app).get(f"/rooms/{ROOM_ID}/trading/quotes")
    finally:
        main_mod.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert checked_out_during_http == [0]


def test_human_reading_fetch_holds_no_pool_connection(monkeypatch) -> None:
    """Moving article extraction inside pool.acquire() must fail this test."""
    pool = _TrackingPool()
    checked_out_during_http: list[int] = []

    async def extract_article(url: str) -> dict[str, object]:
        checked_out_during_http.append(pool.checked_out)
        return {
            "url": url,
            "title": "An article",
            "word_count": 100,
            "content": "evidence " * 100,
        }

    monkeypatch.setattr(reading_relay, "_db_pool", pool)
    monkeypatch.setattr(
        reading_relay.dc,
        "extract_article",
        AsyncMock(side_effect=extract_article),
    )
    monkeypatch.setattr(
        reading_relay.reading_mod,
        "save_reading",
        AsyncMock(return_value={"url": ARTICLE_URL}),
    )
    main_mod.app.dependency_overrides[reading_relay.extract_room_token] = (
        lambda: "room-token-secret"
    )
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID,
        email="caller@test",
        email_verified=True,
        display_name="Caller",
    )
    try:
        response = TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/reading/file",
            json={"message_id": str(MESSAGE_ID), "url": ARTICLE_URL},
        )
    finally:
        main_mod.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert checked_out_during_http == [0]
