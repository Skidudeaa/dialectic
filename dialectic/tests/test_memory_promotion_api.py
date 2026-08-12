"""HTTP contracts for authenticated personal memory promotion."""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient
from httpx import Response
import pytest

import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user


ROOM_ID = UUID("00000000-0000-0000-0000-000000000201")
MEMORY_ID = UUID("00000000-0000-0000-0000-000000000202")
CALLER_ID = UUID("00000000-0000-0000-0000-000000000203")


def _make_db(
    *,
    memory_found: bool = True,
    room_token_valid: bool = True,
    caller_is_member: bool = True,
) -> AsyncMock:
    db = AsyncMock()

    async def fetchrow(query: str, *params: object) -> object | None:
        if "SELECT room_id FROM memories" in query:
            return {"room_id": ROOM_ID} if memory_found else None
        if "FROM rooms" in query:
            if not room_token_valid:
                return None
            return {
                "id": ROOM_ID,
                "created_at": datetime.now(timezone.utc),
                "token": "tok",
            }
        if "FROM room_memberships" in query:
            return {"?column?": 1} if caller_is_member else None
        raise AssertionError(f"Unexpected query: {query}")

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    return db


def _request(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    *,
    db: AsyncMock | None = None,
    manager: SimpleNamespace | None = None,
    authenticated: bool = True,
) -> Response:
    fake_db = db or _make_db()
    fake_manager = manager or SimpleNamespace(
        promote_memory_to_global=AsyncMock(
            return_value=SimpleNamespace(id=MEMORY_ID)
        ),
        demote_memory_from_global=AsyncMock(
            return_value=SimpleNamespace(id=MEMORY_ID)
        ),
        get_user_promoted_memory_ids=AsyncMock(return_value=[MEMORY_ID]),
    )

    async def db_dependency() -> AsyncIterator[object]:
        yield fake_db

    main_mod.app.dependency_overrides[main_mod.get_db] = db_dependency
    main_mod.app.dependency_overrides[main_mod.extract_room_token] = lambda: "tok"
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=CALLER_ID,
            email="caller@test",
            email_verified=True,
            display_name="Caller",
        )
    monkeypatch.setattr(
        main_mod,
        "CrossSessionMemoryManager",
        lambda _db: fake_manager,
        raising=False,
    )

    try:
        return TestClient(main_mod.app).request(method, path)
    finally:
        main_mod.app.dependency_overrides.clear()


def test_promote_returns_the_callers_personal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        promote_memory_to_global=AsyncMock(
            return_value=SimpleNamespace(id=MEMORY_ID)
        )
    )

    response = _request(
        monkeypatch,
        "PUT",
        f"/memories/{MEMORY_ID}/promotion",
        manager=manager,
    )

    assert response.status_code == 200
    assert response.json() == {
        "memory_id": str(MEMORY_ID),
        "promoted": True,
    }
    manager.promote_memory_to_global.assert_awaited_once_with(MEMORY_ID, CALLER_ID)


def test_demote_returns_the_callers_personal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        demote_memory_from_global=AsyncMock(
            return_value=SimpleNamespace(id=MEMORY_ID)
        )
    )

    response = _request(
        monkeypatch,
        "DELETE",
        f"/memories/{MEMORY_ID}/promotion",
        manager=manager,
    )

    assert response.status_code == 200
    assert response.json() == {
        "memory_id": str(MEMORY_ID),
        "promoted": False,
    }
    manager.demote_memory_from_global.assert_awaited_once_with(MEMORY_ID, CALLER_ID)


def test_personal_promotion_list_returns_only_the_callers_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        get_user_promoted_memory_ids=AsyncMock(return_value=[MEMORY_ID])
    )

    response = _request(
        monkeypatch,
        "GET",
        f"/rooms/{ROOM_ID}/memory-promotions",
        manager=manager,
    )

    assert response.status_code == 200
    assert response.json() == {"memory_ids": [str(MEMORY_ID)]}
    manager.get_user_promoted_memory_ids.assert_awaited_once_with(ROOM_ID, CALLER_ID)


def test_promotion_requires_bearer_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _request(
        monkeypatch,
        "PUT",
        f"/memories/{MEMORY_ID}/promotion",
        authenticated=False,
    )

    assert response.status_code == 401


def test_promotion_rejects_an_invalid_source_room_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _request(
        monkeypatch,
        "PUT",
        f"/memories/{MEMORY_ID}/promotion",
        db=_make_db(room_token_valid=False),
    )

    assert response.status_code == 401


def test_promotion_rejects_a_nonmember(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _request(
        monkeypatch,
        "PUT",
        f"/memories/{MEMORY_ID}/promotion",
        db=_make_db(caller_is_member=False),
    )

    assert response.status_code == 403


def test_promotion_hides_missing_or_inaccessible_memories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_response = _request(
        monkeypatch,
        "PUT",
        f"/memories/{MEMORY_ID}/promotion",
        db=_make_db(memory_found=False),
    )
    manager = SimpleNamespace(
        promote_memory_to_global=AsyncMock(
            side_effect=ValueError("Memory not found or inaccessible")
        )
    )
    inaccessible_response = _request(
        monkeypatch,
        "PUT",
        f"/memories/{MEMORY_ID}/promotion",
        manager=manager,
    )

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "detail": "Memory not found or inaccessible"
    }
    assert inaccessible_response.status_code == 404
    assert inaccessible_response.json() == {
        "detail": "Memory not found or inaccessible"
    }
