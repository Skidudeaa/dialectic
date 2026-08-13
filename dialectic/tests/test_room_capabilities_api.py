"""
HTTP contract for GET /rooms/{room_id}/capabilities (api/capabilities.py).

WHY it exists: the help modal was the only place the product explained itself,
and every word of it was hardcoded. It advertised "five live theses" and a daily
rhythm of jobs that are, in this deployment, mostly OFF — WIRE_ENABLED,
NEWS_DIGEST_ENABLED, PREDICTION_WATCH_ENABLED and READING_ECHO_ENABLED all
default to off. A new user read a description of a system that was not running.

So the map is generated from state. The tests that matter here are the ones that
prove it reads the RUNNING scheduler rather than a second list of job names: a
hardcoded roster would satisfy every "does it mention wire" assertion while
saying the opposite of the truth.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.capabilities as capabilities_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user
from scheduler import Job

CALLER_ID = UUID("00000000-0000-0000-0000-000000000601")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000602")
PATH = f"/rooms/{ROOM_ID}/capabilities"
HEADERS = {"X-Room-Token": "room-token"}


class _FakeScheduler:
    def __init__(self, jobs):
        self.jobs = jobs


@pytest.fixture(autouse=True)
def _clean():
    yield
    main_mod.app.dependency_overrides.clear()
    if hasattr(main_mod.app.state, "scheduler"):
        delattr(main_mod.app.state, "scheduler")


def _client(*, room=True, member=True, thesis=False, settings=None) -> TestClient:
    db = AsyncMock()

    async def fetchrow(sql, *args):
        if "FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        if "FROM rooms" in sql:
            if not room:
                return None
            return {
                "linked_book_id": "book-1" if thesis else None,
                "auto_interjection_enabled": (settings or {}).get("auto", True),
                "interjection_turn_threshold": (settings or {}).get("turns", 4),
            }
        return None

    db.fetchrow.side_effect = fetchrow

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[capabilities_mod.get_db] = db_dependency
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="c@test", email_verified=True, display_name="C",
    )
    return TestClient(main_mod.app)


def _noop(_ctx):  # pragma: no cover - never invoked
    raise AssertionError("job body must not run")


def test_requires_both_credentials() -> None:
    assert _client().get(PATH).status_code == 401          # no room token
    assert _client(room=False).get(PATH, headers=HEADERS).status_code == 401
    assert _client(member=False).get(PATH, headers=HEADERS).status_code == 403


def test_reports_whether_this_room_has_a_thesis() -> None:
    body = _client(thesis=True).get(PATH, headers=HEADERS).json()
    assert body["thesis_bound"] is True
    body = _client(thesis=False).get(PATH, headers=HEADERS).json()
    assert body["thesis_bound"] is False


def test_reports_this_room_s_own_participation_settings() -> None:
    body = _client(settings={"auto": False, "turns": 7}).get(PATH, headers=HEADERS).json()
    assert body["auto_interjection"] is False
    assert body["interjection_turn_threshold"] == 7


def test_job_state_comes_from_the_running_scheduler(monkeypatch) -> None:
    """The assertion a hardcoded roster would fail.

    A second list of job names satisfies every "is wire mentioned" check while
    reporting the opposite of what is running. Registering a scheduler with ONE
    oddly-named job proves the endpoint is reading the real registry: a
    hardcoded list cannot invent this name, and cannot drop the others.
    """
    monkeypatch.setenv("A_MADE_UP_FLAG", "0")
    main_mod.app.state.scheduler = _FakeScheduler([
        Job(name="only_job_registered", interval_s=60, func=_noop,
            enabled_env="A_MADE_UP_FLAG"),
    ])
    body = _client().get(PATH, headers=HEADERS).json()
    names = [job["name"] for job in body["jobs"]]
    assert names == ["only_job_registered"]
    assert body["jobs"][0]["enabled"] is False


def test_a_job_s_enabled_flag_follows_its_own_env(monkeypatch) -> None:
    main_mod.app.state.scheduler = _FakeScheduler([
        Job(name="on_job", interval_s=60, func=_noop, enabled_env="CAP_TEST_ON"),
        Job(name="off_job", interval_s=60, func=_noop, enabled_env="CAP_TEST_OFF"),
        Job(name="always", interval_s=60, func=_noop),
    ])
    monkeypatch.setenv("CAP_TEST_ON", "1")
    monkeypatch.setenv("CAP_TEST_OFF", "0")
    jobs = {j["name"]: j["enabled"] for j in _client().get(PATH, headers=HEADERS).json()["jobs"]}
    assert jobs == {"on_job": True, "off_job": False, "always": True}


def test_no_scheduler_means_no_claims_about_jobs() -> None:
    """SCHEDULER_ENABLED=0 is a real configuration, and the honest answer is an
    empty list — never the roster it WOULD have run."""
    body = _client().get(PATH, headers=HEADERS).json()
    assert body["jobs"] == []
    assert body["scheduler_running"] is False
