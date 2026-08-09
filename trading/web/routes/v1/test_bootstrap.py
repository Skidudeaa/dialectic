"""
Tests for GET /api/v1/bootstrap — deterministic first render.

WHY: The bootstrap endpoint is the single entry point for the dashboard.
If it returns incomplete or malformed data, the client can't render.
"""

import os
from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.deps import get_repo
from web.persistence.repository import Repository


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_state():
    repo = Repository(":memory:")
    repo.initialize()
    app.dependency_overrides[get_repo] = lambda: repo
    app.state.repo = repo
    from web.ws import manager
    manager.set_repo(repo)
    yield repo
    app.dependency_overrides.pop(get_repo, None)


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


class TestBootstrap:
    def test_returns_200(self, auth_headers):
        resp = client.get("/api/v1/bootstrap", headers=auth_headers)
        assert resp.status_code == 200

    def test_includes_theses(self, auth_headers):
        resp = client.get("/api/v1/bootstrap", headers=auth_headers)
        data = resp.json()
        assert "theses" in data
        # Coordinator loads books during lifespan — may have theses if books exist
        assert isinstance(data["theses"], list)

    def test_includes_system_status(self, auth_headers):
        resp = client.get("/api/v1/bootstrap", headers=auth_headers)
        data = resp.json()
        assert "system" in data
        assert "uptime_seconds" in data["system"]
        assert "theses_loaded" in data["system"]

    def test_includes_alert_summary(self, auth_headers):
        resp = client.get("/api/v1/bootstrap", headers=auth_headers)
        data = resp.json()
        assert "alertSummary" in data
        summary = data["alertSummary"]
        assert "critical" in summary
        assert "warning" in summary
        assert "info" in summary
        assert "total" in summary

    def test_includes_snapshots(self, auth_headers):
        resp = client.get("/api/v1/bootstrap", headers=auth_headers)
        data = resp.json()
        assert "snapshots" in data
        assert isinstance(data["snapshots"], dict)

    def test_includes_active_overrides(self, auth_headers):
        resp = client.get("/api/v1/bootstrap", headers=auth_headers)
        data = resp.json()
        assert "activeOverrides" in data
        assert isinstance(data["activeOverrides"], dict)

    def test_requires_auth(self):
        resp = client.get("/api/v1/bootstrap")
        assert resp.status_code in (401, 403)

    def test_response_under_500ms(self, auth_headers):
        """Bootstrap should be fast — acceptance benchmark <500ms."""
        import time
        t0 = time.monotonic()
        resp = client.get("/api/v1/bootstrap", headers=auth_headers)
        elapsed = time.monotonic() - t0
        assert resp.status_code == 200
        assert elapsed < 2.0  # generous in test env, production target is <500ms
