"""
Tests for the outbox (durable retry) and health-probe additions to the
bridge.

WHY: A 3-attempt in-process retry handles seconds of dialectic blip; the
outbox handles minutes-to-hours of outage between cron runs. These tests
cover the retry path that was previously a silent data-loss path.

Run:
    python3 -m pytest tools/bridge/test_outbox.py -q
"""

import importlib
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

push_mod = importlib.import_module("push_to_dialectic")
run_all = importlib.import_module("run-all")


# =========================================================================
# OUTBOX
# =========================================================================

VALID_PAYLOAD = json.dumps({
    "v": 1, "timestamp": "2026-04-17T00:00:00Z", "title": "T",
    "nodeStates": {"a": "fired"}, "confluenceScores": {},
    "cascadePhase": {"number": 1, "key": "shock", "status": "STARTING"},
    "countdowns": [], "marketSnapshot": {}, "scenarioImpacts": {},
    "portfolioSummary": {},
}).encode()


class TestSpoolToOutbox:
    def test_creates_directory_if_missing(self, tmp_path, monkeypatch):
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        path = push_mod.spool_to_outbox("room-1", VALID_PAYLOAD, reason="test")
        assert path is not None
        assert outbox.is_dir()
        assert path.read_bytes() == VALID_PAYLOAD

    def test_filename_includes_room_and_hash(self, tmp_path, monkeypatch):
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        path = push_mod.spool_to_outbox("room-XYZ", VALID_PAYLOAD)
        assert "room-XYZ" in path.name
        assert path.name.endswith(".json")

    def test_dedupe_collapses_identical_payloads(self, tmp_path, monkeypatch):
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        first = push_mod.spool_to_outbox("room-1", VALID_PAYLOAD)
        second = push_mod.spool_to_outbox("room-1", VALID_PAYLOAD)
        assert first == second
        assert len(list(outbox.glob("*.json"))) == 1

    def test_different_payloads_create_separate_spools(self, tmp_path, monkeypatch):
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        push_mod.spool_to_outbox("room-1", VALID_PAYLOAD)
        other = json.dumps({"v": 1, "timestamp": "2026-04-17T00:00:01Z",
                            "nodeStates": {"x": "fired"}}).encode()
        push_mod.spool_to_outbox("room-1", other)
        assert len(list(outbox.glob("*.json"))) == 2

    def test_list_outbox_is_room_scoped(self, tmp_path, monkeypatch):
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        push_mod.spool_to_outbox("room-A", VALID_PAYLOAD)
        push_mod.spool_to_outbox("room-B", VALID_PAYLOAD)
        a = push_mod.list_outbox("room-A")
        b = push_mod.list_outbox("room-B")
        all_ = push_mod.list_outbox()
        assert len(a) == 1 and len(b) == 1 and len(all_) == 2

    def test_parse_outbox_filename_roundtrip(self, tmp_path, monkeypatch):
        """parse_outbox_filename returns ts (ISO), room, hash; rejects garbage."""
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        path = push_mod.spool_to_outbox("room-XYZ", VALID_PAYLOAD)
        parsed = push_mod.parse_outbox_filename(path.name)
        assert parsed is not None
        assert parsed["room"] == "room-XYZ"
        assert parsed["hash"] == push_mod._payload_hash(VALID_PAYLOAD)
        # ISO 8601 with microseconds + Z
        assert parsed["ts"].endswith("Z") and "T" in parsed["ts"]
        assert push_mod.parse_outbox_filename("garbage.txt") is None
        assert push_mod.parse_outbox_filename("not-a-spool.json") is None


# =========================================================================
# REPLAY
# =========================================================================


class _RecordingHandler(BaseHTTPRequestHandler):
    """Mock dialectic that records POSTs and lets a test inject failures."""
    received: list[bytes] = []
    fail_until: int = 0  # fail this many requests, then succeed

    def log_message(self, *_a, **_k):  # silence access logs in tests
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        cls = type(self)
        if len(cls.received) < cls.fail_until:
            cls.received.append(body)
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"forced"}')
            return
        cls.received.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


@pytest.fixture
def mock_server():
    _RecordingHandler.received = []
    _RecordingHandler.fail_until = 0
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


class TestReplayOutbox:
    def test_replay_drains_queued_spools_in_fifo_order(self, tmp_path,
                                                       monkeypatch, mock_server):
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        # Spool two distinct payloads (timestamps differ).
        p1 = json.dumps({"v": 1, "timestamp": "2026-04-17T00:00:01Z",
                         "nodeStates": {"a": "fired"}}).encode()
        p2 = json.dumps({"v": 1, "timestamp": "2026-04-17T00:00:02Z",
                         "nodeStates": {"b": "fired"}}).encode()
        push_mod.spool_to_outbox("room-1", p1)
        push_mod.spool_to_outbox("room-1", p2)
        port = mock_server.server_address[1]
        ok, fail = push_mod.replay_outbox(
            f"http://127.0.0.1:{port}", "room-1", "tok",
        )
        assert ok == 2 and fail == 0
        # Spool dir should be empty after success.
        assert list(outbox.glob("*.json")) == []
        # Server received both payloads in spool order.
        assert _RecordingHandler.received == [p1, p2]

    def test_replay_cap_default_is_500(self, monkeypatch):
        """Default replay cap is 500 (bumped from the previous 25)."""
        monkeypatch.delenv("BRIDGE_OUTBOX_REPLAY_CAP", raising=False)
        assert push_mod._resolve_replay_cap() == 500
        assert push_mod.DEFAULT_REPLAY_CAP == 500

    def test_replay_cap_env_override(self, monkeypatch):
        """BRIDGE_OUTBOX_REPLAY_CAP env var overrides the default."""
        monkeypatch.setenv("BRIDGE_OUTBOX_REPLAY_CAP", "1000")
        assert push_mod._resolve_replay_cap() == 1000

    def test_replay_cap_explicit_wins_over_env(self, monkeypatch):
        """Explicit kwarg wins over env var (single-call override)."""
        monkeypatch.setenv("BRIDGE_OUTBOX_REPLAY_CAP", "1000")
        assert push_mod._resolve_replay_cap(7) == 7

    def test_replay_cap_invalid_env_falls_back(self, monkeypatch, capsys):
        """Invalid env value warns to stderr and falls back to default."""
        monkeypatch.setenv("BRIDGE_OUTBOX_REPLAY_CAP", "not-a-number")
        assert push_mod._resolve_replay_cap() == 500
        assert "BRIDGE_OUTBOX_REPLAY_CAP" in capsys.readouterr().err

    def test_replay_cap_negative_env_falls_back(self, monkeypatch):
        """Non-positive cap falls back to the default."""
        monkeypatch.setenv("BRIDGE_OUTBOX_REPLAY_CAP", "-5")
        assert push_mod._resolve_replay_cap() == 500

    def test_replay_halts_on_failure_keeps_remaining_queued(
        self, tmp_path, monkeypatch, mock_server,
    ):
        outbox = tmp_path / "outbox"
        monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
        for ts in ("01", "02", "03"):
            payload = json.dumps({
                "v": 1, "timestamp": f"2026-04-17T00:00:{ts}Z",
                "nodeStates": {ts: "fired"}}).encode()
            push_mod.spool_to_outbox("room-X", payload)
        # Fail every request -- replay should bail after the first.
        _RecordingHandler.fail_until = 100
        port = mock_server.server_address[1]
        ok, fail = push_mod.replay_outbox(
            f"http://127.0.0.1:{port}", "room-X", "tok",
        )
        assert ok == 0 and fail == 1
        # All three should still be queued.
        assert len(list(outbox.glob("*.json"))) == 3


# =========================================================================
# HEALTH PROBE (run-all)
# =========================================================================


class TestProbeDialectic:
    def test_returns_healthy_on_status_ok(self, mock_server):
        # The recording handler only does POST; build a minimal handler
        # for GET /health.
        class HealthHandler(BaseHTTPRequestHandler):
            def log_message(self, *_a, **_k): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok","checks":{}}')
        srv = HTTPServer(("127.0.0.1", 0), HealthHandler)
        Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ok, detail = run_all.probe_dialectic(
                f"http://127.0.0.1:{srv.server_address[1]}", timeout=1.0,
            )
            assert ok is True
            assert "ok" in detail
        finally:
            srv.shutdown()

    def test_returns_unhealthy_on_503(self):
        class DegradedHandler(BaseHTTPRequestHandler):
            def log_message(self, *_a, **_k): pass
            def do_GET(self):
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"degraded","checks":{"db":"down"}}')
        srv = HTTPServer(("127.0.0.1", 0), DegradedHandler)
        Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ok, detail = run_all.probe_dialectic(
                f"http://127.0.0.1:{srv.server_address[1]}", timeout=1.0,
            )
            assert ok is False
            assert "503" in detail
        finally:
            srv.shutdown()

    def test_returns_unhealthy_on_unreachable(self):
        # Bind a port, immediately close so the connection is refused.
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        ok, detail = run_all.probe_dialectic(
            f"http://127.0.0.1:{port}", timeout=1.0,
        )
        assert ok is False
        assert "unreachable" in detail or "connection" in detail.lower()
