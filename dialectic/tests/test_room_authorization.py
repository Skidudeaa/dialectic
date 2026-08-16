"""Bearer identity fences for room creation, joining, and user models."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token


ROOM_ID = UUID("00000000-0000-0000-0000-000000000401")
CALLER_ID = UUID("00000000-0000-0000-0000-000000000402")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000403")


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> None:
    main_mod.app.dependency_overrides.clear()
    yield
    main_mod.app.dependency_overrides.clear()


@pytest.fixture
def db() -> AsyncMock:
    return AsyncMock()


def override_db(db: AsyncMock) -> None:
    async def dependency() -> AsyncIterator[AsyncMock]:
        yield db

    main_mod.app.dependency_overrides[main_mod.get_db] = dependency


def authenticate_caller(db: AsyncMock) -> TestClient:
    override_db(db)
    main_mod.app.dependency_overrides[extract_room_token] = lambda: "room-token"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID,
        email="caller@example.com",
        email_verified=True,
        display_name="Caller",
    )
    return TestClient(main_mod.app)


def test_create_room_requires_bearer_auth(db: AsyncMock) -> None:
    override_db(db)
    response = TestClient(main_mod.app).post(
        "/rooms",
        json={"name": "No ghost room"},
    )
    assert response.status_code == 401
    db.execute.assert_not_awaited()


def test_join_rejects_a_different_body_user(db: AsyncMock) -> None:
    response = authenticate_caller(db).post(
        f"/rooms/{ROOM_ID}/join",
        headers={"X-Room-Token": "room-token"},
        json={"user_id": str(OTHER_ID)},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Cannot join a room as another user"
    db.fetchrow.assert_not_awaited()


def test_user_model_rejects_a_different_path_user(db: AsyncMock) -> None:
    response = authenticate_caller(db).get(
        f"/rooms/{ROOM_ID}/user-models/{OTHER_ID}",
        headers={"X-Room-Token": "room-token"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Cannot view another user's model"
    db.fetchrow.assert_not_awaited()
