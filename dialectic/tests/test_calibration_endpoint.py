"""
Auth contracts for GET /stakes/rooms/{room_id}/calibration.

WHY: this endpoint used to verify only the room token — never that the
caller was a member of the room — so anyone holding the shared token could
read any member's calibration curve. It keeps its `user_id` query param
(unlike the write endpoints, where user_id was an identity claim and moved
to the JWT) because here it is a filter: omitted means the whole room,
which is the view the dashboard renders.

Strategy matches tests/test_trading_alerts_endpoint.py — FastAPI
dependency overrides + a fake db whose fetchrow answers based on which
table the helper queried. No live Postgres.
"""

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import stakes.routes as stakes_routes
from api.auth.dependencies import AuthenticatedUser, get_current_user

ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
OTHER_MEMBER_ID = UUID("00000000-0000-0000-0000-0000000000bb")
OUTSIDER_ID = UUID("00000000-0000-0000-0000-0000000000cc")

MEMBERS = {CALLER_ID, OTHER_MEMBER_ID}


def _make_db(members=MEMBERS, room_token_valid=True):
    """Fake db routing fetchrow by the table the caller queried."""
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            return {"?column?": 1} if room_token_valid else None
        if "FROM room_memberships" in query:
            _room_id, user_id = params
            return {"?column?": 1} if user_id in members else None
        return None

    fake_db.fetchrow = AsyncMock(side_effect=fetchrow)
    fake_db.fetch = AsyncMock(return_value=[])
    return fake_db


@pytest.fixture
def client_and_calibration():
    """TestClient with room token + JWT stubbed; yields (client, get_calibration mock)."""
    fake_db = _make_db()

    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[stakes_routes.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[stakes_routes.extract_room_token] = lambda: "tok"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )

    calibration = AsyncMock(return_value={"calibration": []})
    with patch.object(stakes_routes, "CommitmentManager") as mgr_cls:
        mgr_cls.return_value.get_calibration = calibration
        yield TestClient(main_mod.app), calibration

    main_mod.app.dependency_overrides.clear()


def test_member_gets_whole_room_curve_by_default(client_and_calibration):
    client, calibration = client_and_calibration

    resp = client.get(f"/stakes/rooms/{ROOM_ID}/calibration")

    assert resp.status_code == 200
    # No filter -> whole room, the view the dashboard actually requests.
    calibration.assert_awaited_once_with(user_id=None, room_id=ROOM_ID)


def test_member_may_filter_to_another_member(client_and_calibration):
    client, calibration = client_and_calibration

    resp = client.get(
        f"/stakes/rooms/{ROOM_ID}/calibration", params={"user_id": str(OTHER_MEMBER_ID)},
    )

    assert resp.status_code == 200
    calibration.assert_awaited_once_with(user_id=OTHER_MEMBER_ID, room_id=ROOM_ID)


def test_subject_outside_the_room_is_rejected(client_and_calibration):
    """A clear 403 rather than a silently-empty curve, and no ID probing."""
    client, calibration = client_and_calibration

    resp = client.get(
        f"/stakes/rooms/{ROOM_ID}/calibration", params={"user_id": str(OUTSIDER_ID)},
    )

    assert resp.status_code == 403
    calibration.assert_not_awaited()


def test_non_member_holding_a_valid_room_token_is_rejected():
    """The original hole: room token alone was enough to read the curve."""
    fake_db = _make_db(members={OTHER_MEMBER_ID})  # caller is NOT a member

    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[stakes_routes.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[stakes_routes.extract_room_token] = lambda: "tok"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True, display_name="Caller",
    )

    calibration = AsyncMock(return_value={"calibration": []})
    try:
        with patch.object(stakes_routes, "CommitmentManager") as mgr_cls:
            mgr_cls.return_value.get_calibration = calibration
            resp = TestClient(main_mod.app).get(f"/stakes/rooms/{ROOM_ID}/calibration")

        assert resp.status_code == 403
        calibration.assert_not_awaited()
    finally:
        main_mod.app.dependency_overrides.clear()


def test_requires_authentication():
    """Without a JWT the endpoint must not serve data."""
    fake_db = _make_db()

    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[stakes_routes.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[stakes_routes.extract_room_token] = lambda: "tok"
    # Deliberately no get_current_user override and no Authorization header.

    try:
        resp = TestClient(main_mod.app).get(f"/stakes/rooms/{ROOM_ID}/calibration")
        assert resp.status_code == 401
    finally:
        main_mod.app.dependency_overrides.clear()
