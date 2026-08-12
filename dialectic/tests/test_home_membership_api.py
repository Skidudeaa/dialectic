"""
HTTP contracts for Home membership administration (api/home.py) and the
generic-join denial for Home (api/main.py join_room).

Strategy matches tests/test_memory_promotion_api.py — FastAPI dependency
overrides plus a fake db. No live Postgres; the real SQL semantics are
covered by tests/test_home_schema_pg.py against dialectic_test.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.home as home_mod
import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token
from models import EventType

HOME_ID = UUID("00000000-0000-0000-0000-000000000301")
CALLER_ID = UUID("00000000-0000-0000-0000-000000000302")
TARGET_ID = UUID("00000000-0000-0000-0000-000000000303")
HOME_TOKEN = "home-token"


def _make_db(
    *,
    home_token_valid: bool = True,
    caller_is_member: bool = True,
    caller_can_manage: bool = True,
    target_found: bool = True,
    added: bool = True,
) -> AsyncMock:
    db = AsyncMock()

    async def fetchrow(query: str, *params: object) -> object | None:
        if "WITH target" in query:
            if not target_found:
                return None
            return {
                "user_id": TARGET_ID,
                "display_name": "New Member",
                "added": added,
            }
        if "FROM rooms" in query and "is_home" in query:
            if not home_token_valid or params[0] != HOME_TOKEN:
                return None
            return {"id": HOME_ID}
        if "FROM room_memberships" in query:
            if not caller_is_member:
                return None
            return {"can_manage_home": caller_can_manage}
        if "FROM user_credentials" in query:
            if not target_found:
                return None
            return {"user_id": TARGET_ID, "display_name": "New Member"}
        raise AssertionError(f"Unexpected query: {query}")

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    return db


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main_mod.app.dependency_overrides.clear()


def _client(
    db: AsyncMock,
    *,
    authenticated: bool = True,
    token: str = HOME_TOKEN,
) -> TestClient:
    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[home_mod.get_db] = db_dependency
    main_mod.app.dependency_overrides[extract_room_token] = lambda: token
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=CALLER_ID,
            email="caller@test",
            email_verified=True,
            display_name="Caller",
        )
    return TestClient(main_mod.app)


# ── Candidate resolution ──

def test_candidate_resolves_and_does_not_write() -> None:
    db = _make_db()
    response = _client(db).post(
        "/users/me/home/member-candidate",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": " New.Member@Example.com "},
    )
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(TARGET_ID),
        "display_name": "New Member",
    }
    db.execute.assert_not_awaited()
    # The lookup received the normalized email.
    lookup = [
        c for c in db.fetchrow.await_args_list
        if "FROM user_credentials" in c.args[0]
    ]
    assert lookup and lookup[-1].args[1] == "new.member@example.com"


def test_candidate_unknown_email_is_404() -> None:
    db = _make_db(target_found=False)
    response = _client(db).post(
        "/users/me/home/member-candidate",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "nobody@example.com"},
    )
    assert response.status_code == 404


# ── Add member ──

def test_founder_adds_existing_user() -> None:
    db = _make_db()
    client = _client(db)
    candidate = client.post(
        "/users/me/home/member-candidate",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": " New.Member@Example.com "},
    )
    assert candidate.status_code == 200
    response = client.post(
        "/users/me/home/members",
        headers={"X-Room-Token": HOME_TOKEN},
        json={
            "email": " New.Member@Example.com ",
            "confirmed_user_id": candidate.json()["user_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "added"
    query = db.fetchrow.await_args_list[-1].args[0]
    assert "ON CONFLICT (room_id, user_id) DO NOTHING" in query
    assert "INSERT INTO events" in query
    assert f"'{EventType.USER_JOINED_ROOM.value}'" in query


def test_add_passes_confirmed_user_id_into_the_statement() -> None:
    db = _make_db()
    _client(db).post(
        "/users/me/home/members",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "new.member@example.com", "confirmed_user_id": str(TARGET_ID)},
    )
    call = db.fetchrow.await_args_list[-1]
    assert "WITH target" in call.args[0]
    assert TARGET_ID in call.args[1:]


def test_repeated_add_returns_already_member() -> None:
    db = _make_db(added=False)
    response = _client(db).post(
        "/users/me/home/members",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "new.member@example.com", "confirmed_user_id": str(TARGET_ID)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "already_member"


def test_add_unknown_or_changed_email_is_404() -> None:
    db = _make_db(target_found=False)
    response = _client(db).post(
        "/users/me/home/members",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "nobody@example.com", "confirmed_user_id": str(TARGET_ID)},
    )
    assert response.status_code == 404


# ── Authorization chain ──

def test_missing_bearer_is_401() -> None:
    db = _make_db()
    response = _client(db, authenticated=False).post(
        "/users/me/home/members",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "x@example.com", "confirmed_user_id": str(TARGET_ID)},
    )
    assert response.status_code == 401


def test_bad_home_token_is_401() -> None:
    db = _make_db()
    response = _client(db, token="wrong-token").post(
        "/users/me/home/members",
        headers={"X-Room-Token": "wrong-token"},
        json={"email": "x@example.com", "confirmed_user_id": str(TARGET_ID)},
    )
    assert response.status_code == 401


def test_home_nonmember_is_403() -> None:
    db = _make_db(caller_is_member=False)
    response = _client(db).post(
        "/users/me/home/members",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "x@example.com", "confirmed_user_id": str(TARGET_ID)},
    )
    assert response.status_code == 403


def test_added_member_cannot_add_another() -> None:
    db = _make_db(caller_can_manage=False)
    response = _client(db).post(
        "/users/me/home/members",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "target@example.com", "confirmed_user_id": str(TARGET_ID)},
    )
    assert response.status_code == 403


def test_candidate_requires_the_same_capability() -> None:
    db = _make_db(caller_can_manage=False)
    response = _client(db).post(
        "/users/me/home/member-candidate",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"email": "target@example.com"},
    )
    assert response.status_code == 403


# ── Generic join denial (api/main.py) ──

def _join_db(*, is_home: bool, existing_member: bool) -> AsyncMock:
    db = AsyncMock()

    async def fetchrow(query: str, *params: object) -> object | None:
        if "FROM rooms" in query:
            return {"id": HOME_ID, "token": HOME_TOKEN, "is_home": is_home}
        if "FROM room_memberships" in query:
            return {"room_id": HOME_ID} if existing_member else None
        raise AssertionError(f"Unexpected query: {query}")

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    db.execute = AsyncMock()
    return db


def _join(db: AsyncMock):
    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[main_mod.get_db] = db_dependency
    main_mod.app.dependency_overrides[extract_room_token] = lambda: HOME_TOKEN
    return TestClient(main_mod.app).post(
        f"/rooms/{HOME_ID}/join",
        headers={"X-Room-Token": HOME_TOKEN},
        json={"user_id": str(TARGET_ID)},
    )


def test_generic_join_of_home_is_403_for_nonmember() -> None:
    db = _join_db(is_home=True, existing_member=False)
    response = _join(db)
    assert response.status_code == 403
    db.execute.assert_not_awaited()


def test_existing_home_member_replaying_join_keeps_already_member() -> None:
    db = _join_db(is_home=True, existing_member=True)
    response = _join(db)
    assert response.status_code == 200
    assert response.json() == {"status": "already_member"}
    db.execute.assert_not_awaited()


def test_ordinary_room_join_is_unchanged() -> None:
    db = _join_db(is_home=False, existing_member=False)
    response = _join(db)
    assert response.status_code == 200
    assert response.json() == {"status": "joined"}
