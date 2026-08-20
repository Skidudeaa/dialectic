"""
Contract for the read-state fields on GET /users/me/rooms.

WHY: every unread badge in the app is derived from `message_receipts`, but no
client ever wrote a receipt — the table was empty in production while the badge
counted every message ever sent and never went down. The web client now sends
read receipts, and this endpoint exposes the boundary those receipts establish
so the "new since you were last here" line in the stream and the badge on the
room card are computed from the same instant and cannot disagree.

`last_read_at` is NULL for a member who has never marked anything read; the
client falls back to `joined_at`, which is why both are returned.

Strategy matches tests/test_calibration_endpoint.py — FastAPI dependency
overrides plus a fake db. No live Postgres.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user

USER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-0000000000bb")

JOINED_AT = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
LAST_READ_AT = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)


def _row(*, last_read_at, unread_count=0, is_home=False, can_manage_home=False,
         others_present=None):
    return {
        "id": ROOM_ID,
        "name": "Trading Room",
        "token": "tok",
        "unread_count": unread_count,
        "last_message_at": LAST_READ_AT + timedelta(hours=1),
        "last_message_preview": "hello",
        "last_read_at": last_read_at,
        "joined_at": JOINED_AT,
        "is_home": is_home,
        "can_manage_home": can_manage_home,
        # Who else is in this room right now. The rail reads it to answer
        # "where are you talking?" without leaving the room you are in.
        "others_present": others_present if others_present is not None else [],
    }


def _client(rows):
    fake_db = AsyncMock()
    fake_db.fetch = AsyncMock(return_value=rows)

    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=USER_ID, email="a@example.com", display_name="Amo", email_verified=True
    )
    main_mod.app.dependency_overrides[main_mod.get_db] = lambda: fake_db
    return TestClient(main_mod.app), fake_db


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main_mod.app.dependency_overrides.clear()


def test_exposes_last_read_boundary():
    """The instant the unread count is measured from is returned to the client."""
    client, _ = _client([_row(last_read_at=LAST_READ_AT, unread_count=3)])

    body = client.get("/users/me/rooms").json()

    assert len(body) == 1
    assert body[0]["unread_count"] == 3
    assert body[0]["last_read_at"] is not None
    assert datetime.fromisoformat(body[0]["last_read_at"]) == LAST_READ_AT


def test_never_read_returns_null_boundary_and_join_time():
    """
    A member who has never marked anything read has no boundary. The join time
    is returned so the client can draw the line at the point they arrived rather
    than suppressing it entirely.
    """
    client, _ = _client([_row(last_read_at=None, unread_count=12)])

    body = client.get("/users/me/rooms").json()

    assert body[0]["last_read_at"] is None
    assert datetime.fromisoformat(body[0]["joined_at"]) == JOINED_AT


def test_read_boundary_is_scoped_to_the_requesting_user():
    """
    The receipt subquery must filter on the caller, not just the room —
    otherwise one member reading would clear the other member's badge.
    """
    client, fake_db = _client([_row(last_read_at=LAST_READ_AT)])

    client.get("/users/me/rooms")

    query, *params = fake_db.fetch.call_args.args
    assert "last_read_at" in query
    assert "mr.receipt_type = 'read'" in query
    # The receipt subquery constrains the user, and the only bound parameter is
    # the caller — so it cannot be widened to another member by accident.
    assert "mr.user_id = $1" in query
    assert params == [USER_ID]


def test_home_flags_are_projected():
    """The rail needs is_home to pin Home and can_manage_home for settings."""
    client, _ = _client([_row(last_read_at=None, is_home=True, can_manage_home=True)])

    body = client.get("/users/me/rooms").json()

    assert body[0]["is_home"] is True
    assert body[0]["can_manage_home"] is True


def test_ordinary_room_flags_default_false():
    client, _ = _client([_row(last_read_at=None)])

    body = client.get("/users/me/rooms").json()

    assert body[0]["is_home"] is False
    assert body[0]["can_manage_home"] is False


def test_derived_fields_exclude_deleted_messages():
    """
    Unread count, latest timestamp, and preview must all follow soft-delete
    truth — a deleted message may not leak through any derived field. The
    real SQL semantics are proven against Postgres in test_home_activity_pg;
    this pins the query the endpoint actually sends.
    """
    client, fake_db = _client([_row(last_read_at=LAST_READ_AT)])

    client.get("/users/me/rooms")

    query, *_ = fake_db.fetch.call_args.args
    assert query.count("NOT m.is_deleted") >= 3
    assert "r.is_home" in query
    assert "rm.can_manage_home" in query


def test_present_members_are_projected_onto_the_room():
    """The cross-room presence answer, carried on the room list the rail
    already fetches — no second round trip, and no presence endpoint per room."""
    client, _ = _client([_row(
        last_read_at=None,
        others_present=[{"user_id": str(OTHER_USER_ID), "display_name": "Dan"}],
    )])

    body = client.get("/users/me/rooms").json()

    assert body[0]["others_present"] == [
        {"user_id": str(OTHER_USER_ID), "display_name": "Dan"}
    ]


def test_absent_members_project_as_an_empty_list_not_null():
    """The rail maps over this; null would be a render crash on a quiet room."""
    client, _ = _client([_row(last_read_at=None)])

    assert client.get("/users/me/rooms").json()[0]["others_present"] == []
