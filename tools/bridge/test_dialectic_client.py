"""
Tests for tools/bridge/dialectic_client.py.

WHY: The client pulls LLM_ANNOTATOR alerts back from Dialectic so the
morning brief can surface them. These tests stand up a tiny mock
Dialectic, exercise the threads/messages walk, and verify the alert
filtering and sort.

Run:
    python3 -m pytest tools/bridge/test_dialectic_client.py -q
"""

import importlib
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

sys.path.insert(0, str(Path(__file__).parent))

dc = importlib.import_module("dialectic_client")


def _make_server(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# =========================================================================
# FIXTURES
# =========================================================================

class _StubDialectic(BaseHTTPRequestHandler):
    """Minimal dialectic mock: /rooms/{id}/threads + /threads/{id}/messages."""

    threads = {
        "ROOM-1": [{"id": "T-1", "title": "main", "message_count": 4}],
    }
    messages = {
        "T-1": [
            {"id": "M-1", "thread_id": "T-1", "sequence": 1,
             "created_at": "2026-04-15T08:00:00+00:00",
             "speaker_type": "human", "content": "hi"},
            {"id": "M-2", "thread_id": "T-1", "sequence": 2,
             "created_at": "2026-04-15T08:01:00+00:00",
             "speaker_type": "llm_primary", "content": "hello"},
            {"id": "M-3", "thread_id": "T-1", "sequence": 3,
             "created_at": "2026-04-16T03:00:00+00:00",
             "speaker_type": "llm_annotator",
             "content": "Trading: brent crossed $115, watch persistence."},
            {"id": "M-4", "thread_id": "T-1", "sequence": 4,
             "created_at": "2026-04-16T09:00:00+00:00",
             "speaker_type": "llm_annotator",
             "content": "Trading: planting deadline 17d."},
        ],
    }
    require_auth = True

    def log_message(self, *_a, **_k):
        pass

    def do_GET(self):
        if type(self).require_auth:
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                self._json(401, {"error": "missing token"})
                return
        if self.path == "/health":
            self._json(200, {"status": "ok", "checks": {}})
            return
        if self.path.startswith("/rooms/") and self.path.endswith("/threads"):
            room = self.path.split("/")[2]
            self._json(200, type(self).threads.get(room, []))
            return
        if self.path.startswith("/threads/") and "/messages" in self.path:
            tid = self.path.split("/")[2].split("?")[0]
            self._json(200, {"messages": type(self).messages.get(tid, []),
                             "has_more": False})
            return
        self._json(404, {"error": "not found"})

    def _json(self, code, body):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def server():
    srv = _make_server(_StubDialectic)
    yield srv
    srv.shutdown()


# =========================================================================
# TESTS
# =========================================================================


class TestDialecticClient:
    def test_health_returns_status_ok(self, server):
        port = server.server_address[1]
        client = dc.DialecticClient(f"http://127.0.0.1:{port}", token="t")
        result = client.health()
        assert result["status"] == "ok"

    def test_list_threads_returns_room_threads(self, server):
        port = server.server_address[1]
        client = dc.DialecticClient(f"http://127.0.0.1:{port}", token="t")
        threads = client.list_threads("ROOM-1")
        assert len(threads) == 1
        assert threads[0]["id"] == "T-1"

    def test_fetch_curator_alerts_filters_to_annotator(self, server):
        port = server.server_address[1]
        client = dc.DialecticClient(f"http://127.0.0.1:{port}", token="t")
        alerts = client.fetch_curator_alerts("ROOM-1")
        assert len(alerts) == 2
        assert all(a.speaker_type == "llm_annotator" for a in alerts)
        # Sort is by created_at ascending.
        assert alerts[0].sequence < alerts[1].sequence

    def test_fetch_curator_alerts_respects_since_cutoff(self, server):
        port = server.server_address[1]
        client = dc.DialecticClient(f"http://127.0.0.1:{port}", token="t")
        # M-3 is 2026-04-16T03:00, M-4 is 09:00; cutoff between them.
        alerts = client.fetch_curator_alerts(
            "ROOM-1", since_iso="2026-04-16T06:00:00Z",
        )
        assert len(alerts) == 1
        assert alerts[0].message_id == "M-4"

    def test_unauthorized_raises_dialectic_api_error(self, server):
        port = server.server_address[1]
        client = dc.DialecticClient(f"http://127.0.0.1:{port}", token="")
        with pytest.raises(dc.DialecticAPIError) as excinfo:
            client.fetch_curator_alerts("ROOM-1")
        # _StubDialectic returns 401, but fetch swallows per-thread errors.
        # Threads list itself fails -> propagates.
        assert "401" in str(excinfo.value) or "missing token" in str(excinfo.value).lower()

    def test_empty_room_returns_empty_list(self, server):
        port = server.server_address[1]
        client = dc.DialecticClient(f"http://127.0.0.1:{port}", token="t")
        alerts = client.fetch_curator_alerts("UNKNOWN-ROOM")
        assert alerts == []

    def test_token_falls_back_to_env(self, server, monkeypatch):
        port = server.server_address[1]
        monkeypatch.setenv("DIALECTIC_ROOM_TOKEN", "env-token")
        client = dc.DialecticClient(f"http://127.0.0.1:{port}")
        assert client.token == "env-token"
        # And it works.
        alerts = client.fetch_curator_alerts("ROOM-1")
        assert len(alerts) == 2
