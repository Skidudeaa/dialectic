"""
Web layer tests — auth, state, routes, validation.

WHY: The web layer previously had zero tests. These cover the critical paths:
auth flow, file persistence integrity, input validation, and path traversal defense.
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# WHY: Set test env vars before importing the app so JWT_SECRET and passwords
# are deterministic across test runs.
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token, decode_token, authenticate_user
from web.deps import get_repo
from web.persistence.repository import Repository


client = TestClient(app)


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_state():
    """Inject fresh in-memory SQLite per test via dependency override."""
    repo = Repository(":memory:")
    repo.initialize()
    app.dependency_overrides[get_repo] = lambda: repo
    # WHY: Also set on app.state so WebSocket endpoints (which can't use
    # Depends) and the WS manager's broadcast_to_book_rooms can find it.
    app.state.repo = repo
    from web.ws import manager
    manager.set_repo(repo)
    yield repo
    app.dependency_overrides.pop(get_repo, None)


@pytest.fixture
def auth_headers():
    """Return Authorization headers for user 'amo'."""
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


# ── Auth Tests ───────────────────────────────────────────────────────────

class TestAuth:
    def test_login_valid(self):
        resp = client.post("/api/auth/login", json={"username": "amo", "password": "testpass"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "amo"
        assert data["display_name"] == "Amo"
        assert "access_token" in data

    def test_login_wrong_password(self):
        resp = client.post("/api/auth/login", json={"username": "amo", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_unknown_user(self):
        resp = client.post("/api/auth/login", json={"username": "hacker", "password": "test"})
        assert resp.status_code == 401

    def test_login_case_insensitive(self):
        resp = client.post("/api/auth/login", json={"username": "AMO", "password": "testpass"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "amo"

    def test_token_roundtrip(self):
        token = create_access_token("dan", "Dan")
        payload = decode_token(token)
        assert payload["sub"] == "dan"
        assert payload["name"] == "Dan"

    def test_protected_route_no_token(self):
        resp = client.get("/api/rooms")
        assert resp.status_code in (401, 403)

    def test_protected_route_bad_token(self):
        resp = client.get("/api/rooms", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code in (401, 403)

    def test_protected_route_valid_token(self, auth_headers):
        resp = client.get("/api/rooms", headers=auth_headers)
        assert resp.status_code == 200


# ── State Tests ──────────────────────────────────────────────────────────

class TestState:
    """Repository-backed state operations (replaces old file-based tests)."""

    def test_room_crud(self, isolate_state):
        repo = isolate_state
        room = repo.create_room("test", participants=["amo"])
        assert room["name"] == "test"
        assert room["participants"] == ["amo"]

        found = repo.get_room(room["id"])
        assert found is not None
        assert found["name"] == "test"

        rooms = repo.list_rooms()
        assert len(rooms) == 1

    def test_message_roundtrip(self, isolate_state):
        repo = isolate_state
        room = repo.create_room("msg-test")
        msg = repo.save_message(room["id"], "amo", "hello")
        assert msg["content"] == "hello"
        assert msg["user"] == "amo"

        messages = repo.list_messages(room["id"])
        assert len(messages) == 1
        assert messages[0]["id"] == msg["id"]
        # Plain messages default to kind="text" with no meta.
        assert messages[0]["kind"] == "text"
        assert messages[0]["meta"] is None

    def test_message_kinds_roundtrip(self, isolate_state):
        """Article clippings + code exhibits persist kind + structured meta."""
        repo = isolate_state
        room = repo.create_room("kind-test")
        repo.save_message(
            room["id"], "dan", "📎 Tanker traffic drops — reuters.com",
            kind="article",
            meta={"source": "reuters.com", "title": "Tanker traffic drops 18%", "take": "the gap"},
        )
        repo.save_message(
            room["id"], "amo", "```python\nprint(1)\n```",
            kind="code",
            meta={"fn": "reroute.py", "lang": "python", "code": "print(1)"},
        )
        msgs = repo.list_messages(room["id"])
        assert len(msgs) == 2
        art = next(m for m in msgs if m["kind"] == "article")
        # meta survives the JSON round-trip as a parsed dict.
        assert art["meta"]["source"] == "reuters.com"
        assert art["meta"]["title"].startswith("Tanker")
        code = next(m for m in msgs if m["kind"] == "code")
        assert code["meta"]["fn"] == "reroute.py"
        assert code["meta"]["code"] == "print(1)"

    def test_prediction_create_resolve(self, isolate_state):
        repo = isolate_state
        pred = repo.save_prediction("amo", {"statement": "test", "confidence": 0.8, "deadline": "2026-12-31"})
        assert pred["resolution"] is None

        resolved = repo.resolve_prediction(pred["id"], "correct")
        assert resolved is not None
        assert resolved["resolution"] == "correct"
        assert resolved["resolved_at"] is not None

    def test_resolve_nonexistent_prediction(self, isolate_state):
        repo = isolate_state
        result = repo.resolve_prediction("nonexistent-id", "correct")
        assert result is None

    def test_pin_crud(self, isolate_state):
        repo = isolate_state
        room = repo.create_room("pin-test")
        msg = {"id": "msg-1", "content": "important", "user": "amo", "ts": "2026-01-01"}
        pins = repo.add_pin(room["id"], msg)
        assert len(pins) == 1

        # Dedup: pinning same message again returns same count
        pins = repo.add_pin(room["id"], msg)
        assert len(pins) == 1

        pins = repo.remove_pin(room["id"], "msg-1")
        assert len(pins) == 0


# ── Path Validation Tests ────────────────────────────────────────────────

class TestPathValidation:
    def test_room_id_traversal_rejected(self, isolate_state):
        repo = isolate_state
        with pytest.raises(ValueError):
            repo.get_room("../../etc/passwd")

    def test_room_id_valid(self, isolate_state):
        repo = isolate_state
        # Should not raise — UUID-style IDs are valid
        repo.get_room("abc-123-def")

    def test_messages_room_id_traversal_rejected(self, isolate_state):
        repo = isolate_state
        with pytest.raises(ValueError):
            repo.list_messages("../../../tmp/evil")

    def test_book_id_traversal_rejected(self):
        from web.adapters.thesis import _validate_book_id
        with pytest.raises(ValueError):
            _validate_book_id("../../etc/passwd")

    def test_book_id_valid(self):
        from web.adapters.thesis import _validate_book_id
        _validate_book_id("iran-hormuz-graph")  # Should not raise
        _validate_book_id("trump-tariffs-graph")


# ── Route Tests ──────────────────────────────────────────────────────────

class TestRoutes:
    def test_health(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "llm_available" in data

    def test_rooms_list_empty(self, auth_headers):
        resp = client.get("/api/rooms", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_room_get_after_repo_seed(self, auth_headers, isolate_state):
        room = isolate_state.create_room("alpha", participants=["amo"])
        resp = client.get(f"/api/rooms/{room['id']}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "alpha"

    def test_room_writes_are_gone(self, auth_headers):
        # C4 cull contract: the chat-era write surface stays dead.
        assert client.post("/api/rooms", json={"name": "x"}, headers=auth_headers).status_code == 405
        assert client.patch("/api/rooms/some-id", json={"name": "x"}, headers=auth_headers).status_code == 405
        assert client.delete("/api/rooms/some-id", headers=auth_headers).status_code == 405

    def test_room_not_found(self, auth_headers):
        resp = client.get("/api/rooms/nonexistent-uuid", headers=auth_headers)
        assert resp.status_code == 404

    def test_prediction_lifecycle(self, auth_headers):
        # Create
        resp = client.post("/api/predictions", json={
            "statement": "Oil hits $120",
            "confidence": 0.75,
            "deadline": "2026-06-01",
        }, headers=auth_headers)
        assert resp.status_code == 200
        pred = resp.json()
        assert pred["statement"] == "Oil hits $120"

        # List
        resp = client.get("/api/predictions", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Resolve
        resp = client.post(f"/api/predictions/{pred['id']}/resolve", json={
            "resolution": "correct",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "correct"

    def test_prediction_resolve_invalid_resolution(self, auth_headers):
        # Create first
        resp = client.post("/api/predictions", json={
            "statement": "test", "confidence": 0.5, "deadline": "2026-12-31",
        }, headers=auth_headers)
        pred_id = resp.json()["id"]

        # Try invalid resolution
        resp = client.post(f"/api/predictions/{pred_id}/resolve", json={
            "resolution": "maybe",
        }, headers=auth_headers)
        assert resp.status_code == 422  # Validation error

    def test_prediction_resolve_not_found(self, auth_headers):
        resp = client.post("/api/predictions/nonexistent/resolve", json={
            "resolution": "correct",
        }, headers=auth_headers)
        assert resp.status_code == 404

    def test_journal_crud(self, auth_headers):
        resp = client.post("/api/journal", json={
            "thesis": "oil shock",
            "instrument": "XOP",
            "direction": "long",
            "entry_price": 45.50,
        }, headers=auth_headers)
        assert resp.status_code == 200

        resp = client.get("/api/journal", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestAgentAPI:
    """Tests for agent-friendly endpoints — full CRUD, protocol docs, single-resource GET."""

    def test_journal_update(self, auth_headers):
        resp = client.post("/api/journal", json={
            "thesis": "oil", "instrument": "CL", "direction": "long", "entry_price": 80.0,
        }, headers=auth_headers)
        entry_id = resp.json()["id"]
        resp = client.patch(f"/api/journal/{entry_id}", json={
            "exit_price": 95.0, "pnl": 15.0, "notes": "closed at target",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["exit_price"] == 95.0
        assert resp.json()["pnl"] == 15.0
        assert "updated_at" in resp.json()

    def test_journal_update_not_found(self, auth_headers):
        resp = client.patch("/api/journal/nonexistent", json={"pnl": 10}, headers=auth_headers)
        assert resp.status_code == 404

    def test_prediction_single_get(self, auth_headers):
        resp = client.post("/api/predictions", json={
            "statement": "findme", "confidence": 0.9, "deadline": "2026-12-31",
        }, headers=auth_headers)
        pred_id = resp.json()["id"]
        resp = client.get(f"/api/predictions/{pred_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["statement"] == "findme"

    def test_prediction_single_get_not_found(self, auth_headers):
        resp = client.get("/api/predictions/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    def test_ws_protocol_docs(self):
        resp = client.get("/api/ws/protocol")
        assert resp.status_code == 200
        data = resp.json()
        assert "url_pattern" in data
        assert "auth" in data
        assert data["auth"]["query_param"] == "token"
        assert "send_types" in data
        assert "receive_types" in data

    def test_health_includes_llm_available(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert "llm_available" in resp.json()


# ── Concurrent State Tests ───────────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_prediction_resolve_no_data_loss(self, tmp_path):
        """Verify resolve_prediction under concurrent creates doesn't lose data.

        WHY: Uses a file-backed SQLite DB (not :memory:) so WAL mode is
        available. WAL mode allows concurrent readers and serialized writers,
        which is the production configuration.
        """
        db_path = tmp_path / "concurrent_test.db"
        repo = Repository(db_path)
        repo.initialize()

        for i in range(5):
            repo.save_prediction("amo", {
                "statement": f"pred-{i}", "confidence": 0.5, "deadline": "2026-12-31",
            })

        preds = repo.list_predictions()
        assert len(preds) == 5
        target_id = preds[0]["id"]

        errors = []

        def create_preds():
            try:
                for i in range(5, 10):
                    repo.save_prediction("dan", {
                        "statement": f"pred-{i}", "confidence": 0.6, "deadline": "2026-12-31",
                    })
            except Exception as e:
                errors.append(e)

        def resolve_pred():
            try:
                repo.resolve_prediction(target_id, "correct")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=create_preds)
        t2 = threading.Thread(target=resolve_pred)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Errors during concurrent operations: {errors}"

        all_preds = repo.list_predictions()
        resolved = [p for p in all_preds if p.get("resolution") == "correct"]
        assert len(resolved) >= 1
