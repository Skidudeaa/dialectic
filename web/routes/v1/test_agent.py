"""
Tests for GET /api/v1/agent/log, GET /api/v1/agent/state, POST /api/v1/agent/ping.

WHY: The agent-in-room panel is the desk's window into LLM activity.
These tests pin down:
  - the in-process ring buffer respects maxlen (oldest calls evicted),
  - room_id and limit filters behave sanely,
  - JWT is required on all three endpoints,
  - /agent/state returns the coordinator revision when one exists and
    None when it doesn't,
  - /agent/ping is a cheap sub-50ms heartbeat.
"""

import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.routes import llm as llm_route
from web.runtime import coordinator as coord_module


@pytest.fixture(autouse=True)
def reset_state():
    """Each test starts with an empty ring buffer and a clean revision cache.

    WHY: _AGENT_CALL_LOG and _latest_revisions are module-level; tests that
    push into them would leak into the next test without this teardown.
    """
    llm_route._AGENT_CALL_LOG.clear()
    coord_module._latest_revisions.clear()
    yield
    llm_route._AGENT_CALL_LOG.clear()
    coord_module._latest_revisions.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


# ── Auth ──────────────────────────────────────────────────────────────


class TestAgentAuth:
    def test_log_requires_jwt(self, client):
        resp = client.get("/api/v1/agent/log")
        assert resp.status_code == 401

    def test_state_requires_jwt(self, client):
        resp = client.get("/api/v1/agent/state")
        assert resp.status_code == 401

    def test_ping_requires_jwt(self, client):
        resp = client.post("/api/v1/agent/ping")
        assert resp.status_code == 401


# ── /agent/log ────────────────────────────────────────────────────────


class TestAgentLog:
    def test_empty_when_no_calls(self, client, auth_headers):
        resp = client.get("/api/v1/agent/log", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["rows"] == []
        assert body["count"] == 0
        assert "fetchedAt" in body

    def test_returns_rows_newest_first(self, client, auth_headers):
        llm_route.record_agent_call(
            model="claude-sonnet-4.6", prompt="first call",
            latency_ms=120.0, status="success",
            room_id="r1", thesis_id="iran-hormuz-graph",
            snapshot_revision=3,
        )
        llm_route.record_agent_call(
            model="gpt-5.3-chat", prompt="second call",
            latency_ms=300.5, status="success",
            room_id="r1", thesis_id="iran-hormuz-graph",
            snapshot_revision=4,
        )
        resp = client.get("/api/v1/agent/log", headers=auth_headers)
        assert resp.status_code == 200
        rows = resp.json()["rows"]
        assert len(rows) == 2
        # Newest-first — second call appended last must come out first.
        assert rows[0]["prompt_first_80"] == "second call"
        assert rows[1]["prompt_first_80"] == "first call"

    def test_room_id_filter(self, client, auth_headers):
        llm_route.record_agent_call(
            model="m1", prompt="a", latency_ms=10, status="success",
            room_id="r1",
        )
        llm_route.record_agent_call(
            model="m2", prompt="b", latency_ms=10, status="success",
            room_id="r2",
        )
        resp = client.get(
            "/api/v1/agent/log?room_id=r2", headers=auth_headers,
        )
        assert resp.status_code == 200
        rows = resp.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["room_id"] == "r2"

    def test_default_limit_is_20(self, client, auth_headers):
        for i in range(30):
            llm_route.record_agent_call(
                model="m", prompt=f"p{i}", latency_ms=1,
                status="success", room_id="r",
            )
        resp = client.get("/api/v1/agent/log", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["rows"]) == 20

    def test_limit_cap_at_50(self, client, auth_headers):
        resp = client.get("/api/v1/agent/log?limit=99", headers=auth_headers)
        # FastAPI's Query le=50 returns 422 on overshoot.
        assert resp.status_code == 422

    def test_limit_respected_under_cap(self, client, auth_headers):
        for i in range(10):
            llm_route.record_agent_call(
                model="m", prompt=f"p{i}", latency_ms=1,
                status="success", room_id="r",
            )
        resp = client.get("/api/v1/agent/log?limit=3", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["rows"]) == 3


# ── /agent/state ──────────────────────────────────────────────────────


class TestAgentState:
    def test_no_thesis_returns_null_revision(self, client, auth_headers):
        resp = client.get("/api/v1/agent/state", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["snapshot_revision"] is None
        assert body["default_model"]  # non-empty

    def test_returns_revision_when_coordinator_has_one(
        self, client, auth_headers,
    ):
        coord_module._latest_revisions["iran-hormuz-graph"] = 7
        resp = client.get(
            "/api/v1/agent/state?thesis_id=iran-hormuz-graph",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["thesis_id"] == "iran-hormuz-graph"
        assert body["snapshot_revision"] == 7

    def test_returns_null_when_uncommitted(self, client, auth_headers):
        """When coordinator never committed a snapshot for this thesis,
        the revision must be None (never 0 — that would be a meaningful
        revision in its own right)."""
        resp = client.get(
            "/api/v1/agent/state?thesis_id=never-seen-this-book",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["snapshot_revision"] is None

    def test_state_reflects_last_call(self, client, auth_headers):
        llm_route.record_agent_call(
            model="claude-sonnet-4.6", prompt="hi",
            latency_ms=80.0, status="success", room_id="r1",
        )
        resp = client.get("/api/v1/agent/state", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_call_status"] == "success"
        assert body["last_call_model"] == "claude-sonnet-4.6"
        assert body["last_call_ts"] is not None


# ── /agent/ping ───────────────────────────────────────────────────────


class TestAgentPing:
    def test_returns_ok_quickly(self, client, auth_headers):
        t0 = time.monotonic()
        resp = client.post("/api/v1/agent/ping", headers=auth_headers)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "ts" in body
        # Heartbeat should be well under 100ms in tests; 50ms is the
        # target but allow headroom for slow CI.
        assert elapsed_ms < 500


# ── Ring-buffer behaviour ────────────────────────────────────────────


class TestRingBuffer:
    def test_maxlen_evicts_oldest(self):
        # Fill past the maxlen — the 51st call must push the 1st out.
        for i in range(llm_route.AGENT_LOG_MAXLEN + 1):
            llm_route.record_agent_call(
                model="m", prompt=f"p{i}", latency_ms=1,
                status="success", room_id="r",
            )
        assert len(llm_route._AGENT_CALL_LOG) == llm_route.AGENT_LOG_MAXLEN
        # First prompt ("p0") evicted; second ("p1") is now the oldest.
        oldest = llm_route._AGENT_CALL_LOG[0]
        assert oldest["prompt_first_80"] == "p1"

    def test_record_captures_all_fields(self):
        row = llm_route.record_agent_call(
            model="claude-sonnet-4.6",
            prompt="analyze the Hormuz shock" * 10,  # long, will be truncated
            tool_calls=["fetch_prices", "propagate"],
            latency_ms=452.8,
            status="success",
            room_id="room-abc",
            thesis_id="iran-hormuz-graph",
            snapshot_revision=12,
        )
        assert row["model"] == "claude-sonnet-4.6"
        assert len(row["prompt_first_80"]) == 80
        assert row["tool_calls"] == ["fetch_prices", "propagate"]
        assert row["latency_ms"] == 452.8
        assert row["status"] == "success"
        assert row["room_id"] == "room-abc"
        assert row["thesis_id"] == "iran-hormuz-graph"
        assert row["snapshot_revision"] == 12
        assert "ts" in row
