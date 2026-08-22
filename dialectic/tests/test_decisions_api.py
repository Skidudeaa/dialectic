"""
HTTP contract for GET /rooms/{room_id}/threads/{thread_id}/decisions
(api/decisions.py).

Same shape as tests/test_room_capabilities_api.py on purpose: this route is
fenced with the EXACT same two checks, in the EXACT same order, as
api/capabilities.py::get_room_capabilities (room token, then membership) —
mirroring that test proves the fence, not just the response shape. The row
shaping and the room/thread SQL fence itself are proven separately, against
real Postgres, in tests/test_decisions_pg.py — a mocked `db.fetchrow` cannot
tell a correctly-scoped query from an unscoped one.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.decisions as decisions_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user

CALLER_ID = UUID("00000000-0000-0000-0000-000000000701")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000702")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000703")
OTHER_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000704")
PATH = f"/rooms/{ROOM_ID}/threads/{THREAD_ID}/decisions"
HEADERS = {"X-Room-Token": "room-token"}


@pytest.fixture(autouse=True)
def _clean():
    yield
    main_mod.app.dependency_overrides.clear()


def _row(**overrides):
    base = {
        "response_message_id": OTHER_MESSAGE_ID,
        "reason": "explicit_mention",
        "confidence": 1.0,
        "mode": "primary",
        "use_provoker": False,
        "human_turn_count": None,
        "semantic_novelty": None,
        "unsurfaced_memory_count": None,
    }
    base.update(overrides)
    return base


def _client(*, room=True, member=True, decision_rows=None) -> TestClient:
    db = AsyncMock()

    async def fetchrow(sql, *args):
        if "FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        if "FROM rooms" in sql:
            return {"?column?": 1} if room else None
        return None

    async def fetch(sql, *args):
        assert "FROM llm_decisions" in sql
        # The room/thread fence must be bound parameters on THIS query, not
        # assumed from the earlier membership check — args[0]/args[1] are
        # (room_id, thread_id) as passed by the handler.
        assert args[0] == ROOM_ID
        assert args[1] == THREAD_ID
        return decision_rows or []

    db.fetchrow.side_effect = fetchrow
    db.fetch.side_effect = fetch

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[decisions_mod.get_db] = db_dependency
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="c@test", email_verified=True, display_name="C",
    )
    return TestClient(main_mod.app)


def test_requires_both_credentials() -> None:
    assert _client().get(PATH).status_code == 401           # no room token
    assert _client(room=False).get(PATH, headers=HEADERS).status_code == 401
    assert _client(member=False).get(PATH, headers=HEADERS).status_code == 403


def test_no_decisions_is_200_and_empty_not_an_error() -> None:
    """An empty thread (or one where nothing was ever logged) is the ordinary
    case, not a 404 — see the module docstring's contrast with mirror.py."""
    resp = _client(decision_rows=[]).get(PATH, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"decisions": {}}


def test_returns_a_map_keyed_by_the_message_id_the_decision_produced() -> None:
    resp = _client(decision_rows=[_row()]).get(PATH, headers=HEADERS)
    body = resp.json()
    assert list(body["decisions"].keys()) == [str(OTHER_MESSAGE_ID)]
    entry = body["decisions"][str(OTHER_MESSAGE_ID)]
    assert entry["reason"] == "explicit_mention"
    assert entry["mode"] == "primary"
    assert entry["use_provoker"] is False
    assert entry["confidence"] == 1.0


def test_absent_inputs_stay_null_not_zero() -> None:
    """A forced turn never ran the heuristic rungs — NULL must survive as
    null in the JSON, not become 0 (which would read as "measured, and
    low")."""
    resp = _client(decision_rows=[_row(
        reason="wire_interjection", confidence=1.0, mode="primary",
        human_turn_count=None, semantic_novelty=None,
        unsurfaced_memory_count=None,
    )]).get(PATH, headers=HEADERS)
    entry = resp.json()["decisions"][str(OTHER_MESSAGE_ID)]
    assert entry["human_turn_count"] is None
    assert entry["semantic_novelty"] is None
    assert entry["unsurfaced_memory_count"] is None


def test_does_not_leak_raw_internals() -> None:
    """tool_calls / speaker_balance / decided_at / id / triggered_by_message_id
    are not part of the contract — only the response_model's own fields can
    appear (FastAPI enforces this via response_model, but the SELECT itself
    must not even fetch them; see the module docstring's reasoning)."""
    resp = _client(decision_rows=[_row()]).get(PATH, headers=HEADERS)
    entry = resp.json()["decisions"][str(OTHER_MESSAGE_ID)]
    assert set(entry.keys()) == {
        "reason", "confidence", "mode", "use_provoker",
        "human_turn_count", "semantic_novelty", "unsurfaced_memory_count",
    }
