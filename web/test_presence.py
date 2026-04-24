"""
Tests for global presence pills (Unit 9).

WHY: Presence is cross-room — Dan in room A must see Amo join room B and the
book they're viewing. These tests exercise the broadcast_presence fan-out,
the presence.update C2S handler, the debounce (duplicate updates collapse to
one broadcast), and the synthetic agent pill that appears when the LLM is
mid-tool-call.
"""

from __future__ import annotations

import json
import os
import time
from typing import List

import pytest
from fastapi.testclient import TestClient

# WHY: Match test_web.py — deterministic secret + default password so auth
# works without a live .env file.
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.deps import get_repo
from web.persistence.repository import Repository
from web.ws import (
    _AGENT_ACTIVE_WINDOW_S,
    _reset_agent_state_for_tests,
    mark_agent_idle,
    mark_agent_thinking,
    manager,
)


client = TestClient(app)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_state():
    """Inject fresh in-memory SQLite per test + clear presence/agent state."""
    repo = Repository(":memory:")
    repo.initialize()
    app.dependency_overrides[get_repo] = lambda: repo
    app.state.repo = repo
    manager.set_repo(repo)
    # WHY: Each test starts with empty presence + idle agent — the manager
    # is a module singleton and carries state between tests otherwise.
    # Clear ALL shared state to defend against pollution from unrelated
    # websocket tests run before this module (test_web.py opens sockets).
    manager._presence.clear()
    manager._last_presence_payload = None
    manager._rooms.clear()
    manager._user_activity.clear()
    manager._seq_counters.clear()
    manager._bus_forwarders.clear()
    _reset_agent_state_for_tests()
    yield repo
    app.dependency_overrides.pop(get_repo, None)
    manager._presence.clear()
    manager._last_presence_payload = None
    manager._rooms.clear()
    manager._user_activity.clear()
    _reset_agent_state_for_tests()


def _make_token(username: str = "amo", display: str = "Amo") -> str:
    return create_access_token(username, display)


def _make_room(repo: Repository, name: str = "r1", linked_book_id=None) -> str:
    room = repo.create_room(name=name, linked_book_id=linked_book_id)
    return room["id"]


def _drain(ws, *, max_frames: int = 50, settle_ms: int = 200) -> List[dict]:
    """Drain any pending frames from a TestClient WS, return as parsed dicts.

    WHY: Starlette's WebSocketTestSession.receive_text blocks forever when
    the buffer is empty. We peek at the underlying anyio stream's buffer
    statistics to only call receive_text when a frame is waiting. The
    settle_ms pause lets the server's broadcast tasks enqueue frames before
    we sample.
    """
    time.sleep(settle_ms / 1000.0)
    frames: List[dict] = []
    for _ in range(max_frames):
        try:
            stats = ws._send_rx.statistics()
        except Exception:
            break
        if stats.current_buffer_used == 0:
            break
        try:
            raw = ws.receive_text()
        except Exception:
            break
        try:
            frames.append(json.loads(raw))
        except Exception:
            pass
    return frames


def _receive_until(ws, msg_type: str, *, max_frames: int = 50, settle_ms: int = 200) -> dict:
    """Read frames until one with `type == msg_type` arrives.

    WHY settle_ms: broadcast_presence() runs as a task; the caller needs to
    let the asyncio loop tick so the frame is enqueued before we start
    consuming. Without it, receive_text() can race the broadcast.
    """
    time.sleep(settle_ms / 1000.0)
    for _ in range(max_frames):
        try:
            stats = ws._send_rx.statistics()
        except Exception:
            stats = None
        if stats is not None and stats.current_buffer_used == 0:
            # No frame waiting — give the server a moment to produce one.
            time.sleep(0.05)
        raw = ws.receive_text()
        try:
            frame = json.loads(raw)
        except Exception:
            continue
        if frame.get("type") == msg_type:
            return frame
    raise AssertionError(f"no frame of type {msg_type} received in {max_frames} frames")


def _latest_of_type(ws, msg_type: str, *, settle_ms: int = 250) -> dict:
    """Drain all pending frames and return the most recent one of `msg_type`.

    WHY: Several frames of the same type may be queued from prior state
    transitions (e.g. initial connect triggers both a direct send AND the
    cross-room broadcast). The test cares about the LATEST state.
    """
    frames = _drain(ws, settle_ms=settle_ms)
    matching = [f for f in frames if f.get("type") == msg_type]
    assert matching, f"no frame of type {msg_type} in drain"
    return matching[-1]


# ════════════════════════════════════════════════════════════════════════
# CONNECT / DISCONNECT
# ════════════════════════════════════════════════════════════════════════

class TestPresenceLifecycle:
    def test_connect_broadcasts_presence(self, isolate_state):
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            # First presence.changed frame has this user
            frame = _receive_until(ws, "presence.changed")
            users = frame["payload"]["users"]
            ids = {u["user_id"] for u in users}
            assert "amo" in ids

    def test_disconnect_removes_user(self, isolate_state):
        """Disconnect removes the user from broadcast_presence payloads.

        Rather than chase specific queued frames (flaky under parallel
        threads + lifespan contamination from prior tests), assert directly
        on the manager's internal presence map: connecting dan → both in
        map; closing ws2 → dan dropped. The fan-out path is exercised by
        test_cross_room_broadcast.
        """
        repo = isolate_state
        rid = _make_room(repo)
        t1 = _make_token("amo")
        t2 = _make_token("dan")

        with client.websocket_connect(f"/ws/{rid}?token={t1}") as ws1:
            _drain(ws1)
            ids = {e["user_id"] for e in manager._presence.values()}
            assert "amo" in ids
            with client.websocket_connect(f"/ws/{rid}?token={t2}") as ws2:
                _drain(ws2)
                time.sleep(0.2)
                ids = {e["user_id"] for e in manager._presence.values()}
                assert "amo" in ids
                assert "dan" in ids
            # ws2 closed — give the server's async disconnect a moment.
            time.sleep(0.3)
            ids = {e["user_id"] for e in manager._presence.values()}
            assert "dan" not in ids, f"dan lingered: {ids}"
            assert "amo" in ids

    def test_cross_room_broadcast(self, isolate_state):
        """3 connections across 2 rooms — every client sees the same roster."""
        repo = isolate_state
        r1 = _make_room(repo, "r1")
        r2 = _make_room(repo, "r2")

        t1 = _make_token("amo")
        t2 = _make_token("dan")
        t3 = _make_token("amo")  # second tab for amo

        with client.websocket_connect(f"/ws/{r1}?token={t1}") as w1, \
             client.websocket_connect(f"/ws/{r2}?token={t2}") as w2, \
             client.websocket_connect(f"/ws/{r2}?token={t3}") as w3:
            # All three should see a roster containing both users. Each
            # socket's buffer accumulates presence.changed frames; the most
            # recent frame is the full roster.
            def latest_presence(ws):
                frames = _drain(ws, settle_ms=400)
                presence = [f for f in frames if f.get("type") == "presence.changed"]
                assert presence, "no presence.changed frame received"
                return presence[-1]
            f1 = latest_presence(w1)
            f2 = latest_presence(w2)
            f3 = latest_presence(w3)
            for frame in (f1, f2, f3):
                ids = {u["user_id"] for u in frame["payload"]["users"]}
                assert "amo" in ids
                assert "dan" in ids


# ════════════════════════════════════════════════════════════════════════
# PRESENCE.UPDATE C2S FRAME
# ════════════════════════════════════════════════════════════════════════

class TestPresenceUpdate:
    def test_update_with_new_book_id_broadcasts(self, isolate_state):
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            _drain(ws)
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "iran-hormuz"},
            }))
            frame = _latest_of_type(ws, "presence.changed")
            me = next(
                u for u in frame["payload"]["users"]
                if u["user_id"] == "amo" and u["kind"] == "human"
            )
            assert me["book_id"] == "iran-hormuz"

    def test_duplicate_update_debounced(self, isolate_state):
        """Posting the same presence.update twice produces only one broadcast."""
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            _drain(ws)
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "iran-hormuz"},
            }))
            _drain(ws)  # absorb the first broadcast
            # Second identical update — should debounce to zero new frames.
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "iran-hormuz"},
            }))
            frames = _drain(ws)
            presence_frames = [f for f in frames if f.get("type") == "presence.changed"]
            assert len(presence_frames) == 0

    def test_rapid_book_switches_broadcast_each_change(self, isolate_state):
        """Each actual change produces exactly one broadcast."""
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            _drain(ws)
            for book in ("iran-hormuz", "trump-tariffs", "iran-hormuz"):
                ws.send_text(json.dumps({
                    "type": "presence.update",
                    "payload": {"book_id": book},
                }))
                frame = _latest_of_type(ws, "presence.changed")
                me = next(
                    u for u in frame["payload"]["users"]
                    if u["user_id"] == "amo" and u["kind"] == "human"
                )
                assert me["book_id"] == book

    def test_any_c2s_message_updates_last_activity(self, isolate_state):
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            _receive_until(ws, "presence.changed")
            # Snapshot the last_activity of our entry via the manager dict.
            ws_id = next(iter(manager._presence.keys()))
            old_activity = manager._presence[ws_id]["last_activity"]
            time.sleep(0.05)
            # Send a typing frame — not a presence.update.
            ws.send_text(json.dumps({"type": "typing", "typing": True}))
            # Drain whatever came back; just ensure bump_activity ran.
            _drain(ws)
            new_activity = manager._presence[ws_id]["last_activity"]
            assert new_activity > old_activity


# ════════════════════════════════════════════════════════════════════════
# PAYLOAD SHAPE
# ════════════════════════════════════════════════════════════════════════

class TestPresencePayloadShape:
    def test_payload_matches_schema(self, isolate_state):
        from web.schemas.ws import PresenceChangedPayload
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            frame = _receive_until(ws, "presence.changed")
            # Schema parses without error.
            parsed = PresenceChangedPayload(**frame["payload"])
            assert parsed.generated_at
            assert any(u.user_id == "amo" for u in parsed.users)

    def test_payload_user_shape(self, isolate_state):
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            frame = _receive_until(ws, "presence.changed")
            assert frame.get("type") == "presence.changed"
            payload = frame["payload"]
            assert "users" in payload and "generated_at" in payload
            for u in payload["users"]:
                assert "user_id" in u
                assert "last_activity" in u
                assert "kind" in u
                assert u["kind"] in ("human", "agent")


# ════════════════════════════════════════════════════════════════════════
# AGENT PILL
# ════════════════════════════════════════════════════════════════════════

class TestAgentPill:
    def _seed_agent_state(self, status: str, book_id: str = "iran-hormuz") -> None:
        """Set agent state without triggering a broadcast from a non-loop thread.

        WHY: mark_agent_thinking() calls asyncio.get_running_loop() which
        fails from the pytest thread. We mutate the state dict directly —
        the next broadcast (triggered by a C2S presence.update) reflects it.
        """
        from datetime import datetime, timezone
        from web.ws import _AGENT_STATE
        _AGENT_STATE["status"] = status
        _AGENT_STATE["last_activity"] = datetime.now(timezone.utc).isoformat()
        _AGENT_STATE["book_id"] = book_id

    def test_agent_appears_when_thinking(self, isolate_state):
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            _drain(ws)
            # Seed agent state, then trigger a broadcast via a C2S frame.
            self._seed_agent_state("thinking", "iran-hormuz")
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "iran-hormuz"},
            }))
            frame = _latest_of_type(ws, "presence.changed")
            users = frame["payload"]["users"]
            agents = [u for u in users if u.get("kind") == "agent"]
            assert len(agents) == 1
            assert agents[0]["status"] == "thinking"
            assert agents[0]["book_id"] == "iran-hormuz"

    def test_agent_disappears_after_window(self, isolate_state):
        """Agent pill drops out of the roster after _AGENT_ACTIVE_WINDOW_S."""
        from web.ws import _AGENT_STATE
        from datetime import datetime, timezone, timedelta

        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            _drain(ws)
            # Seed agent-thinking and push a broadcast to observe it first.
            self._seed_agent_state("thinking", "iran-hormuz")
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "trump-tariffs"},
            }))
            frame = _latest_of_type(ws, "presence.changed")
            assert any(u.get("kind") == "agent" for u in frame["payload"]["users"])
            # Backdate last_activity to simulate window expiry.
            stale = datetime.now(timezone.utc) - timedelta(
                seconds=_AGENT_ACTIVE_WINDOW_S + 5
            )
            _AGENT_STATE["last_activity"] = stale.isoformat()
            _AGENT_STATE["status"] = "idle"
            # Force a fresh broadcast by flipping our book_id.
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "iran-hormuz"},
            }))
            frame = _latest_of_type(ws, "presence.changed")
            users = frame["payload"]["users"]
            assert all(u.get("kind") != "agent" for u in users)

    def test_mark_agent_idle_clears_thinking_status(self, isolate_state):
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            _drain(ws)
            self._seed_agent_state("thinking", "iran-hormuz")
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "iran-hormuz"},
            }))
            _drain(ws)
            # Flip agent state to idle via the public helper (state mutation).
            # mark_agent_idle will try to schedule a broadcast but silently
            # no-op from the non-loop thread; that's fine — we force one next.
            mark_agent_idle()
            ws.send_text(json.dumps({
                "type": "presence.update",
                "payload": {"book_id": "trump-tariffs"},
            }))
            frame = _latest_of_type(ws, "presence.changed")
            users = frame["payload"]["users"]
            agents = [u for u in users if u.get("kind") == "agent"]
            # Agent row still present (within window) but status = idle.
            assert len(agents) == 1
            assert agents[0]["status"] == "idle"


# ════════════════════════════════════════════════════════════════════════
# AUTH / ACCESS
# ════════════════════════════════════════════════════════════════════════

class TestPresenceAuth:
    def test_presence_read_requires_ws_auth_only(self, isolate_state):
        """Once a WS is authenticated, presence pushes arrive without extra auth.

        The client never calls a REST endpoint for presence — the server
        pushes the envelope over the already-authenticated WS.
        """
        repo = isolate_state
        rid = _make_room(repo)
        token = _make_token("amo")
        with client.websocket_connect(f"/ws/{rid}?token={token}") as ws:
            frame = _receive_until(ws, "presence.changed")
            # No Authorization header needed per-frame — the WS auth at
            # connect time is sufficient.
            assert frame.get("type") == "presence.changed"
