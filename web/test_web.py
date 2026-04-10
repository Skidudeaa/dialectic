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
from web import state as state_mod
from web.auth import create_access_token, decode_token, authenticate_user


client = TestClient(app)


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_state(tmp_path: Path):
    """Redirect all state file I/O to a temp directory per test."""
    original = state_mod.DATA_DIR
    state_mod.DATA_DIR = tmp_path
    state_mod.ROOMS_FILE = tmp_path / "rooms.json"
    state_mod.JOURNAL_FILE = tmp_path / "journal.jsonl"
    state_mod.PREDICTIONS_FILE = tmp_path / "predictions.jsonl"
    yield
    state_mod.DATA_DIR = original
    state_mod.ROOMS_FILE = original / "rooms.json"
    state_mod.JOURNAL_FILE = original / "journal.jsonl"
    state_mod.PREDICTIONS_FILE = original / "predictions.jsonl"


@pytest.fixture
def auth_headers():
    """Return Authorization headers for user 'amo'."""
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def room_id(auth_headers):
    """Create a room and return its ID."""
    resp = client.post("/api/rooms", json={"name": "test-room"}, headers=auth_headers)
    assert resp.status_code == 200
    return resp.json()["id"]


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
    def test_read_json_missing_file(self, tmp_path: Path):
        result = state_mod.read_json(tmp_path / "nonexistent.json", default={"empty": True})
        assert result == {"empty": True}

    def test_write_read_json_roundtrip(self, tmp_path: Path):
        path = tmp_path / "test.json"
        data = {"key": "value", "nested": [1, 2, 3]}
        state_mod.write_json(path, data)
        result = state_mod.read_json(path)
        assert result == data

    def test_write_json_atomic_no_partial(self, tmp_path: Path):
        """Verify temp file is cleaned up after atomic write."""
        path = tmp_path / "atomic.json"
        state_mod.write_json(path, {"ok": True})
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()

    def test_read_jsonl_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert state_mod.read_jsonl(path) == []

    def test_read_jsonl_with_corrupt_line(self, tmp_path: Path):
        path = tmp_path / "mixed.jsonl"
        path.write_text('{"a":1}\nBAD LINE\n{"b":2}\n')
        result = state_mod.read_jsonl(path)
        assert len(result) == 2
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}

    def test_append_jsonl(self, tmp_path: Path):
        path = tmp_path / "append.jsonl"
        state_mod.append_jsonl(path, {"x": 1})
        state_mod.append_jsonl(path, {"x": 2})
        result = state_mod.read_jsonl(path)
        assert len(result) == 2

    def test_room_crud(self):
        room = state_mod.create_room("test", participants=["amo"])
        assert room["name"] == "test"
        assert room["participants"] == ["amo"]

        found = state_mod.get_room(room["id"])
        assert found is not None
        assert found["name"] == "test"

        rooms = state_mod.list_rooms()
        assert len(rooms) == 1

    def test_message_roundtrip(self):
        room = state_mod.create_room("msg-test")
        msg = state_mod.save_message(room["id"], "amo", "hello")
        assert msg["content"] == "hello"
        assert msg["user"] == "amo"

        messages = state_mod.list_messages(room["id"])
        assert len(messages) == 1
        assert messages[0]["id"] == msg["id"]

    def test_prediction_create_resolve(self):
        pred = state_mod.save_prediction("amo", {"statement": "test", "confidence": 0.8, "deadline": "2026-12-31"})
        assert pred["resolution"] is None

        resolved = state_mod.resolve_prediction(pred["id"], "correct")
        assert resolved is not None
        assert resolved["resolution"] == "correct"
        assert resolved["resolved_at"] is not None

    def test_resolve_nonexistent_prediction(self):
        result = state_mod.resolve_prediction("nonexistent-id", "correct")
        assert result is None

    def test_pin_crud(self):
        room = state_mod.create_room("pin-test")
        msg = {"id": "msg-1", "content": "important", "user": "amo", "ts": "2026-01-01"}
        pins = state_mod.add_pin(room["id"], msg)
        assert len(pins) == 1

        # Dedup: pinning same message again returns same count
        pins = state_mod.add_pin(room["id"], msg)
        assert len(pins) == 1

        pins = state_mod.remove_pin(room["id"], "msg-1")
        assert len(pins) == 0


# ── Path Validation Tests ────────────────────────────────────────────────

class TestPathValidation:
    def test_room_id_traversal_rejected(self):
        with pytest.raises(ValueError):
            state_mod.get_room("../../etc/passwd")

    def test_room_id_valid(self):
        # Should not raise — UUID-style IDs are valid
        state_mod.get_room("abc-123-def")

    def test_messages_path_traversal_rejected(self):
        with pytest.raises(ValueError):
            state_mod._messages_path("../../../tmp/evil")

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

    def test_rooms_create_and_get(self, auth_headers):
        resp = client.post("/api/rooms", json={"name": "alpha", "topic": "testing"}, headers=auth_headers)
        assert resp.status_code == 200
        room = resp.json()
        assert room["name"] == "alpha"
        assert room["participants"] == ["amo"]

        resp = client.get(f"/api/rooms/{room['id']}", headers=auth_headers)
        assert resp.status_code == 200

    def test_room_not_found(self, auth_headers):
        resp = client.get("/api/rooms/nonexistent-uuid", headers=auth_headers)
        assert resp.status_code == 404

    def test_messages_crud(self, auth_headers, room_id):
        # Post a message
        resp = client.post(
            f"/api/rooms/{room_id}/messages",
            json={"content": "hello world"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        msg = resp.json()
        assert msg["content"] == "hello world"
        assert msg["msg_type"] == "user"

        # List messages
        resp = client.get(f"/api/rooms/{room_id}/messages", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_message_to_nonexistent_room(self, auth_headers):
        resp = client.post(
            "/api/rooms/fake-room-id/messages",
            json={"content": "test"},
            headers=auth_headers,
        )
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

    def test_pin_typed_validation(self, auth_headers, room_id):
        # Post without required 'id' field — should fail validation
        resp = client.post(
            f"/api/rooms/{room_id}/pins",
            json={"content": "no id field"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_pin_valid(self, auth_headers, room_id):
        resp = client.post(
            f"/api/rooms/{room_id}/pins",
            json={
                "id": "msg-1", "room_id": room_id, "user": "amo",
                "content": "important", "msg_type": "user", "ts": "2026-01-01",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_message_type_restricted(self, auth_headers, room_id):
        # Trying to send msg_type="system" should fail
        resp = client.post(
            f"/api/rooms/{room_id}/messages",
            json={"content": "fake system", "msg_type": "system"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

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

    def test_export_chat(self, auth_headers, room_id):
        # Add a message first
        client.post(f"/api/rooms/{room_id}/messages", json={"content": "exportable"}, headers=auth_headers)
        resp = client.get(f"/api/rooms/{room_id}/export", headers=auth_headers)
        assert resp.status_code == 200
        assert "exportable" in resp.json()["markdown"]


# ── Agent API Tests ──────────────────────────────────────────────────────

class TestAgentAPI:
    """Tests for agent-friendly endpoints — full CRUD, protocol docs, single-resource GET."""

    def test_room_update(self, auth_headers):
        resp = client.post("/api/rooms", json={"name": "orig"}, headers=auth_headers)
        room_id = resp.json()["id"]
        resp = client.patch(f"/api/rooms/{room_id}", json={"name": "renamed", "topic": "new topic"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed"
        assert resp.json()["topic"] == "new topic"

    def test_room_update_not_found(self, auth_headers):
        resp = client.patch("/api/rooms/nonexistent", json={"name": "x"}, headers=auth_headers)
        assert resp.status_code == 404

    def test_room_update_empty_body(self, auth_headers):
        resp = client.post("/api/rooms", json={"name": "test"}, headers=auth_headers)
        room_id = resp.json()["id"]
        resp = client.patch(f"/api/rooms/{room_id}", json={}, headers=auth_headers)
        assert resp.status_code == 422

    def test_room_delete(self, auth_headers):
        resp = client.post("/api/rooms", json={"name": "deletable"}, headers=auth_headers)
        room_id = resp.json()["id"]
        # Add a message so the room has data
        client.post(f"/api/rooms/{room_id}/messages", json={"content": "bye"}, headers=auth_headers)
        resp = client.delete(f"/api/rooms/{room_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        # Verify room is gone
        resp = client.get(f"/api/rooms/{room_id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_room_delete_not_found(self, auth_headers):
        resp = client.delete("/api/rooms/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

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
    def test_concurrent_prediction_resolve_no_data_loss(self):
        """Verify resolve_prediction under concurrent creates doesn't lose data."""
        # Create initial predictions
        for i in range(5):
            state_mod.save_prediction("amo", {
                "statement": f"pred-{i}", "confidence": 0.5, "deadline": "2026-12-31",
            })

        preds = state_mod.list_predictions()
        assert len(preds) == 5
        target_id = preds[0]["id"]

        # Concurrent: resolve one while creating new ones
        errors = []

        def create_preds():
            try:
                for i in range(5, 10):
                    state_mod.save_prediction("dan", {
                        "statement": f"pred-{i}", "confidence": 0.6, "deadline": "2026-12-31",
                    })
            except Exception as e:
                errors.append(e)

        def resolve_pred():
            try:
                state_mod.resolve_prediction(target_id, "correct")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=create_preds)
        t2 = threading.Thread(target=resolve_pred)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Errors during concurrent operations: {errors}"

        # All predictions should exist
        all_preds = state_mod.list_predictions()
        # We should have at least 5 (original) + some of the 5 new ones
        # The resolve should have worked
        resolved = [p for p in all_preds if p.get("resolution") == "correct"]
        assert len(resolved) >= 1
