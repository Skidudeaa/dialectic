"""
Tests for GET /api/v1/audit — destructive-action audit feed.

WHY: The audit panel is the only place an operator can verify "did
that kill button I clicked actually fire?". These tests pin down the
contract: 401 without JWT, newest-first ordering, working filters,
and a hard cap on limit so a misclick can't dump the entire table.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.deps import get_repo
from web.persistence.repository import Repository


@pytest.fixture
def repo():
    """Fresh in-memory repo wired into the FastAPI dependency override."""
    r = Repository(":memory:")
    r.initialize()
    app.dependency_overrides[get_repo] = lambda: r
    app.state.repo = r
    yield r
    app.dependency_overrides.pop(get_repo, None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


class TestAuditAuth:
    def test_requires_jwt(self, client, repo):
        resp = client.get("/api/v1/audit")
        assert resp.status_code == 401


class TestAuditList:
    def test_empty_when_no_rows(self, client, auth_headers, repo):
        resp = client.get("/api/v1/audit", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_recent_rows_newest_first(self, client, auth_headers, repo):
        repo.add_audit_row(actor="amo", action="trade.kill", target="t1", reason="r1")
        repo.add_audit_row(actor="amo", action="trade.kill", target="t2", reason="r2")
        resp = client.get("/api/v1/audit", headers=auth_headers)
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        # Newest-first ordering — t2 inserted second.
        assert rows[0]["target"] == "t2"
        assert rows[1]["target"] == "t1"
        # Field shape sanity check.
        for row in rows:
            assert "id" in row
            assert "ts" in row
            assert "actor" in row
            assert "action" in row
            assert "target" in row

    def test_filter_by_actor(self, client, auth_headers, repo):
        repo.add_audit_row(actor="amo", action="trade.kill", target="t1")
        repo.add_audit_row(actor="dan", action="trade.kill", target="t2")
        resp = client.get("/api/v1/audit?actor=dan", headers=auth_headers)
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["target"] == "t2"

    def test_filter_by_action(self, client, auth_headers, repo):
        repo.add_audit_row(actor="amo", action="trade.kill", target="t1")
        repo.add_audit_row(actor="amo", action="scenario.apply", target="s1")
        resp = client.get("/api/v1/audit?action=scenario.apply", headers=auth_headers)
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["target"] == "s1"

    def test_filter_by_since(self, client, auth_headers, repo):
        repo.add_audit_row(actor="amo", action="x.y", target="old")
        # Far-future since → nothing.
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        resp = client.get(f"/api/v1/audit?since={future}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []
        # Far-past since → returns the row.
        past = "2000-01-01T00:00:00+00:00"
        resp = client.get(f"/api/v1/audit?since={past}", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_limit_caps_response(self, client, auth_headers, repo):
        for i in range(20):
            repo.add_audit_row(actor="amo", action="x.y", target=f"t{i}")
        resp = client.get("/api/v1/audit?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 5

    def test_limit_max_enforced(self, client, auth_headers, repo):
        """limit > 1000 is rejected by FastAPI's Query validator."""
        resp = client.get("/api/v1/audit?limit=10000", headers=auth_headers)
        assert resp.status_code == 422
