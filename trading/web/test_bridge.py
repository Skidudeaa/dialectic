"""
Tests for /api/bridge/outbox status endpoint.

WHY: The dashboard top-bar badge depends on this endpoint to show stuck
snapshots. Test the empty case (no badge), the populated case (per-room
breakdown + oldest/newest timestamps), and JWT-gating (browsers should
get 401 without a token).
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# WHY: Same env-var trick as test_web.py — JWT secret deterministic per run.
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token

# Load push_to_dialectic via the same importer the route uses, so
# OUTBOX_DIR monkeypatching works against the same module instance.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "bridge"))
push_mod = importlib.import_module("push_to_dialectic")


client = TestClient(app)


VALID_PAYLOAD = b'{"v":1,"timestamp":"2026-04-17T00:00:00Z","nodeStates":{}}'


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def isolated_outbox(tmp_path, monkeypatch):
    """Redirect OUTBOX_DIR for both push_to_dialectic and the route's view."""
    outbox = tmp_path / "outbox"
    monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
    return outbox


class TestOutboxStatusAuth:
    def test_requires_jwt(self):
        """No token -> 401/403, never anonymous data exposure."""
        resp = client.get("/api/bridge/outbox")
        assert resp.status_code in (401, 403)

    def test_rejects_garbage_token(self):
        resp = client.get(
            "/api/bridge/outbox",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert resp.status_code in (401, 403)


class TestOutboxStatusEmpty:
    def test_empty_outbox_returns_zeros_not_404(self, auth_headers, isolated_outbox):
        """Missing/empty dir -> {queued: 0, ...}, never 404."""
        resp = client.get("/api/bridge/outbox", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] == 0
        assert data["byRoom"] == {}
        assert data["oldest"] is None
        assert data["newest"] is None
        assert data["totalBytes"] == 0
        assert data["replayCap"] == 500  # default cap after Change 1

    def test_empty_dir_exists_returns_zeros(self, auth_headers, isolated_outbox):
        isolated_outbox.mkdir(parents=True, exist_ok=True)
        resp = client.get("/api/bridge/outbox", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["queued"] == 0


class TestOutboxStatusPopulated:
    def test_groups_by_room(self, auth_headers, isolated_outbox):
        push_mod.spool_to_outbox("room-A", VALID_PAYLOAD)
        push_mod.spool_to_outbox(
            "room-A",
            b'{"v":1,"timestamp":"2026-04-17T00:00:01Z","nodeStates":{"x":"fired"}}',
        )
        push_mod.spool_to_outbox("room-B", VALID_PAYLOAD)
        resp = client.get("/api/bridge/outbox", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] == 3
        assert data["byRoom"] == {"room-A": 2, "room-B": 1}
        assert data["totalBytes"] > 0
        assert data["oldest"] is not None
        assert data["newest"] is not None
        # ISO 8601 with microseconds + Z
        assert data["oldest"].endswith("Z") and "T" in data["oldest"]
        assert data["oldest"] <= data["newest"]

    def test_skips_files_not_matching_convention(self, auth_headers, isolated_outbox):
        """Stray .json files (manual paste, half-written temps) are ignored."""
        push_mod.spool_to_outbox("room-A", VALID_PAYLOAD)
        isolated_outbox.mkdir(parents=True, exist_ok=True)
        (isolated_outbox / "garbage.json").write_text("{}")
        (isolated_outbox / "stray-no-pattern.json").write_text("{}")
        resp = client.get("/api/bridge/outbox", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] == 1
        assert data["byRoom"] == {"room-A": 1}

    def test_replay_cap_reflects_env(self, auth_headers, isolated_outbox, monkeypatch):
        """Endpoint surfaces the live cap so the frontend knows the backstop."""
        monkeypatch.setenv("BRIDGE_OUTBOX_REPLAY_CAP", "750")
        resp = client.get("/api/bridge/outbox", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["replayCap"] == 750


# =============================================================================
# DRAIN-NOW endpoint tests
#
# WHY: The /api/bridge/outbox/replay endpoint kicks off real network IO in
# production via push_to_dialectic.replay_outbox. We monkeypatch that function
# here so tests stay hermetic — no mock dialectic server needed for the
# happy/sad-path matrix.
# =============================================================================


class TestOutboxReplayAuth:
    def test_requires_jwt(self):
        resp = client.post("/api/bridge/outbox/replay", json={})
        assert resp.status_code in (401, 403)

    def test_rejects_garbage_token(self):
        resp = client.post(
            "/api/bridge/outbox/replay",
            headers={"Authorization": "Bearer not-a-real-jwt"},
            json={},
        )
        assert resp.status_code in (401, 403)


class TestOutboxReplayEmpty:
    def test_empty_outbox_returns_zeros_not_404(
        self, auth_headers, isolated_outbox, monkeypatch,
    ):
        """No queued spools -> 200 with zeros, idempotent."""
        monkeypatch.setenv("DIALECTIC_ROOM_TOKEN", "test-token")
        # Even with the token set, there's nothing to drain -> nothing called.
        called = {"n": 0}
        def stub_replay(*args, **kwargs):
            called["n"] += 1
            return (0, 0)
        monkeypatch.setattr(push_mod, "replay_outbox", stub_replay)

        resp = client.post(
            "/api/bridge/outbox/replay", headers=auth_headers, json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["replayed"] == 0
        assert data["remaining"] == 0
        assert data["perRoom"] == []
        assert "dialecticUrl" in data
        assert isinstance(data["durationMs"], int)
        assert called["n"] == 0  # no rooms discovered, no replay called


class TestOutboxReplayPopulated:
    def test_drains_when_dialectic_healthy(
        self, auth_headers, isolated_outbox, monkeypatch,
    ):
        """Healthy dialectic -> replay_outbox returns (n, 0) and unlinks
        spools, so remaining drops to 0."""
        monkeypatch.setenv("DIALECTIC_ROOM_TOKEN", "test-token")
        push_mod.spool_to_outbox("room-A", VALID_PAYLOAD)
        push_mod.spool_to_outbox(
            "room-A",
            b'{"v":1,"timestamp":"2026-04-17T00:00:01Z","nodeStates":{}}',
        )
        push_mod.spool_to_outbox("room-B", VALID_PAYLOAD)

        # Stub: simulate "all queued spools accepted" by deleting the files.
        def stub_replay(url, room_id, token, max_per_run=None):
            spools = push_mod.list_outbox(room_id)
            for s in spools:
                s.unlink()
            return (len(spools), 0)
        monkeypatch.setattr(push_mod, "replay_outbox", stub_replay)

        resp = client.post(
            "/api/bridge/outbox/replay", headers=auth_headers, json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["replayed"] == 3
        assert data["remaining"] == 0
        rooms = {r["roomId"]: r for r in data["perRoom"]}
        assert set(rooms.keys()) == {"room-A", "room-B"}
        assert rooms["room-A"]["replayed"] == 2
        assert rooms["room-A"]["remaining"] == 0
        assert rooms["room-A"]["errors"] == []
        assert rooms["room-B"]["replayed"] == 1
        assert rooms["room-B"]["errors"] == []

    def test_returns_partial_when_dialectic_unreachable(
        self, auth_headers, isolated_outbox, monkeypatch,
    ):
        """Unreachable dialectic -> 200 with errors populated, remaining > 0.

        Operators deserve to see the partial result, not a generic 5xx.
        """
        monkeypatch.setenv("DIALECTIC_ROOM_TOKEN", "test-token")
        push_mod.spool_to_outbox("room-A", VALID_PAYLOAD)
        push_mod.spool_to_outbox("room-B", VALID_PAYLOAD)

        # Stub: leave files in place, return (0, 1) -- "halted on first spool".
        def stub_replay(url, room_id, token, max_per_run=None):
            return (0, 1)
        monkeypatch.setattr(push_mod, "replay_outbox", stub_replay)

        resp = client.post(
            "/api/bridge/outbox/replay", headers=auth_headers, json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["replayed"] == 0
        assert data["remaining"] == 2
        for r in data["perRoom"]:
            assert r["replayed"] == 0
            assert r["remaining"] == 1
            assert r["errors"], "expected error message about halted replay"
            assert "dialectic" in r["errors"][0].lower()

    def test_room_id_filter_limits_drain_to_one_room(
        self, auth_headers, isolated_outbox, monkeypatch,
    ):
        """Body {roomId: X} should only drain X, not other rooms."""
        monkeypatch.setenv("DIALECTIC_ROOM_TOKEN", "test-token")
        push_mod.spool_to_outbox("room-A", VALID_PAYLOAD)
        push_mod.spool_to_outbox("room-B", VALID_PAYLOAD)

        called_rooms: list[str] = []

        def stub_replay(url, room_id, token, max_per_run=None):
            called_rooms.append(room_id)
            spools = push_mod.list_outbox(room_id)
            for s in spools:
                s.unlink()
            return (len(spools), 0)
        monkeypatch.setattr(push_mod, "replay_outbox", stub_replay)

        resp = client.post(
            "/api/bridge/outbox/replay",
            headers=auth_headers,
            json={"roomId": "room-A"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert called_rooms == ["room-A"]
        assert data["replayed"] == 1
        # room-B was NOT drained -> still has 1 spool sitting on disk.
        assert len(push_mod.list_outbox("room-B")) == 1
        assert {r["roomId"] for r in data["perRoom"]} == {"room-A"}

    def test_missing_token_surfaces_error_not_500(
        self, auth_headers, isolated_outbox, monkeypatch,
    ):
        """No env token + no book token -> per-room error, still 200."""
        monkeypatch.delenv("DIALECTIC_ROOM_TOKEN", raising=False)
        push_mod.spool_to_outbox("orphan-room", VALID_PAYLOAD)
        # Stub so even if the token check is bypassed, no real network call.
        monkeypatch.setattr(push_mod, "replay_outbox",
                            lambda *a, **kw: (0, 0))

        resp = client.post(
            "/api/bridge/outbox/replay", headers=auth_headers, json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["perRoom"][0]["roomId"] == "orphan-room"
        assert data["perRoom"][0]["replayed"] == 0
        assert any("token" in e.lower() for e in data["perRoom"][0]["errors"])
