"""
Tests for push-to-dialectic.py bridge script.

Run:
    python3 -m pytest test_push.py -v
    # or from the bridge directory:
    python3 -m pytest -v
"""

import io
import json
import os
import sys
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from unittest.mock import patch, MagicMock

# Ensure the bridge directory is importable
sys.path.insert(0, str(Path(__file__).parent))

# We import specific functions rather than `main()` to avoid argparse sys.exit
# during import. The module's top-level code is guarded by __name__ == "__main__".
import importlib
push_mod = importlib.import_module("push-to-dialectic")

get_room_token = push_mod.get_room_token
check_transport_security = push_mod.check_transport_security
load_snapshot = push_mod.load_snapshot
push_snapshot = push_mod.push_snapshot
build_parser = push_mod.build_parser
main = push_mod.main


# =========================================================================
# FIXTURES
# =========================================================================

VALID_SNAPSHOT = {
    "v": 1,
    "timestamp": "2026-03-30T14:00:00Z",
    "title": "Test Thesis",
    "nodeStates": {"hormuz": "fired", "brent": "approaching"},
    "confluenceScores": {"em-stress": 1.30},
    "cascadePhase": {"number": 2, "key": "transmission", "status": "STARTING"},
    "countdowns": [
        {"nodeId": "planting-miss", "label": "Planting", "deadline": "2026-04-15", "daysRemaining": 17}
    ],
    "marketSnapshot": {"brent": 112.57, "diesel": 5.38},
    "scenarioImpacts": {
        "kharg-strike": {"probability": 0.15, "netImpact": 22.4}
    },
    "portfolioSummary": {
        "monthlyBudget": 8000,
        "topPositions": ["XOP $1400/mo"],
        "sgovAvailable": 1200,
    },
}

VALID_SNAPSHOT_BYTES = json.dumps(VALID_SNAPSHOT).encode("utf-8")
ROOM_ID = "00000000-0000-0000-0000-000000000001"
FAKE_TOKEN = "test-room-token-abc123"


# =========================================================================
# TOKEN TESTS
# =========================================================================

class TestGetRoomToken(unittest.TestCase):
    """Test that missing DIALECTIC_ROOM_TOKEN produces a clear error."""

    def test_missing_token_exits_2(self):
        """Missing DIALECTIC_ROOM_TOKEN env var should print error and exit 2."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove DIALECTIC_ROOM_TOKEN if it exists
            os.environ.pop("DIALECTIC_ROOM_TOKEN", None)
            with self.assertRaises(SystemExit) as ctx:
                get_room_token()
            self.assertEqual(ctx.exception.code, 2)

    def test_empty_token_exits_2(self):
        """Empty/whitespace DIALECTIC_ROOM_TOKEN should be treated as missing."""
        with patch.dict(os.environ, {"DIALECTIC_ROOM_TOKEN": "   "}):
            with self.assertRaises(SystemExit) as ctx:
                get_room_token()
            self.assertEqual(ctx.exception.code, 2)

    def test_missing_token_error_message(self):
        """Error message should mention the env var name and 'secret'."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DIALECTIC_ROOM_TOKEN", None)
            captured = io.StringIO()
            with self.assertRaises(SystemExit):
                with patch("sys.stderr", captured):
                    get_room_token()
            output = captured.getvalue()
            self.assertIn("DIALECTIC_ROOM_TOKEN", output)
            self.assertIn("secret", output)

    def test_valid_token_returns_value(self):
        """Valid token should be returned as-is (stripped)."""
        with patch.dict(os.environ, {"DIALECTIC_ROOM_TOKEN": f"  {FAKE_TOKEN}  "}):
            token = get_room_token()
            self.assertEqual(token, FAKE_TOKEN)


# =========================================================================
# TRANSPORT SECURITY TESTS
# =========================================================================

class TestTransportSecurity(unittest.TestCase):
    """Test that non-HTTPS non-localhost URLs produce warnings."""

    def test_http_remote_warns(self):
        """HTTP to a remote host should produce a warning on stderr."""
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            check_transport_security("http://dialectic.example.com:8002")
        output = captured.getvalue()
        self.assertIn("WARNING", output)
        self.assertIn("unencrypted HTTP", output)

    def test_https_remote_no_warning(self):
        """HTTPS to a remote host should not produce a warning."""
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            check_transport_security("https://dialectic.example.com:8002")
        self.assertEqual(captured.getvalue(), "")

    def test_http_localhost_no_warning(self):
        """HTTP to localhost should not produce a warning."""
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            check_transport_security("http://localhost:8002")
        self.assertEqual(captured.getvalue(), "")

    def test_http_127_no_warning(self):
        """HTTP to 127.0.0.1 should not produce a warning."""
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            check_transport_security("http://127.0.0.1:8002")
        self.assertEqual(captured.getvalue(), "")


# =========================================================================
# SNAPSHOT LOADING TESTS
# =========================================================================

class TestLoadSnapshot(unittest.TestCase):
    """Test snapshot loading from file and stdin."""

    def test_load_from_file(self, tmp_path=None):
        """Loading a valid JSON file should return raw bytes."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as f:
            f.write(VALID_SNAPSHOT_BYTES)
            f.flush()
            path = f.name
        try:
            raw = load_snapshot(path)
            parsed = json.loads(raw)
            self.assertEqual(parsed["v"], 1)
            self.assertEqual(parsed["title"], "Test Thesis")
        finally:
            os.unlink(path)

    def test_load_from_stdin(self):
        """Loading from '-' should read from stdin."""
        fake_stdin = io.BytesIO(VALID_SNAPSHOT_BYTES)
        with patch("sys.stdin", MagicMock()):
            with patch.object(sys.stdin, "buffer", fake_stdin):
                # Re-import to get fresh reference
                raw = load_snapshot("-")
                parsed = json.loads(raw)
                self.assertEqual(parsed["v"], 1)

    def test_missing_file_exits_2(self):
        """Missing file should exit 2 with a clear error."""
        with self.assertRaises(SystemExit) as ctx:
            load_snapshot("/nonexistent/path/snapshot.json")
        self.assertEqual(ctx.exception.code, 2)

    def test_empty_file_exits_2(self):
        """Empty file should exit 2."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(SystemExit) as ctx:
                load_snapshot(path)
            self.assertEqual(ctx.exception.code, 2)
        finally:
            os.unlink(path)

    def test_invalid_json_exits_2(self):
        """Invalid JSON content should exit 2."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as f:
            f.write(b"not json {{{")
            f.flush()
            path = f.name
        try:
            with self.assertRaises(SystemExit) as ctx:
                load_snapshot(path)
            self.assertEqual(ctx.exception.code, 2)
        finally:
            os.unlink(path)


# =========================================================================
# HTTP REQUEST FORMATTING TESTS
# =========================================================================

class TestPushSnapshotRequestFormat(unittest.TestCase):
    """Test that the HTTP request is formatted correctly (mock the HTTP call)."""

    def test_request_url_format(self):
        """URL should be {base}/rooms/{room_id}/trading/snapshot."""
        captured_req = {}

        def mock_urlopen(req, timeout=None):
            captured_req["url"] = req.full_url
            captured_req["method"] = req.method
            captured_req["headers"] = dict(req.headers)
            captured_req["data"] = req.data
            # Return a fake response
            resp = MagicMock()
            resp.read.return_value = b'{"stored_at": "2026-03-30T14:00:00Z", "memory_id": "abc"}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            return resp

        with patch.object(push_mod, "urlopen", mock_urlopen):
            with self.assertRaises(SystemExit) as ctx:
                push_snapshot("http://localhost:8002", ROOM_ID, FAKE_TOKEN, VALID_SNAPSHOT_BYTES)
            self.assertEqual(ctx.exception.code, 0)

        expected_url = f"http://localhost:8002/rooms/{ROOM_ID}/trading/snapshot"
        self.assertEqual(captured_req["url"], expected_url)

    def test_request_method_is_post(self):
        """HTTP method should be POST."""
        captured_req = {}

        def mock_urlopen(req, timeout=None):
            captured_req["method"] = req.method
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            return resp

        with patch.object(push_mod, "urlopen", mock_urlopen):
            with self.assertRaises(SystemExit):
                push_snapshot("http://localhost:8002", ROOM_ID, FAKE_TOKEN, VALID_SNAPSHOT_BYTES)

        self.assertEqual(captured_req["method"], "POST")

    def test_request_headers(self):
        """Request should include Content-Type and Authorization headers."""
        captured_req = {}

        def mock_urlopen(req, timeout=None):
            captured_req["headers"] = {k: v for k, v in req.headers.items()}
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            return resp

        with patch.object(push_mod, "urlopen", mock_urlopen):
            with self.assertRaises(SystemExit):
                push_snapshot("http://localhost:8002", ROOM_ID, FAKE_TOKEN, VALID_SNAPSHOT_BYTES)

        self.assertEqual(captured_req["headers"].get("Content-type"), "application/json")
        self.assertEqual(captured_req["headers"].get("Authorization"), f"Bearer {FAKE_TOKEN}")

    def test_request_body_is_snapshot(self):
        """Request body should be the raw snapshot JSON bytes."""
        captured_req = {}

        def mock_urlopen(req, timeout=None):
            captured_req["data"] = req.data
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            return resp

        with patch.object(push_mod, "urlopen", mock_urlopen):
            with self.assertRaises(SystemExit):
                push_snapshot("http://localhost:8002", ROOM_ID, FAKE_TOKEN, VALID_SNAPSHOT_BYTES)

        self.assertEqual(captured_req["data"], VALID_SNAPSHOT_BYTES)

    def test_success_prints_response_json(self):
        """Successful push should print pretty-printed response JSON to stdout."""
        response_body = b'{"stored_at": "2026-03-30T14:00:00Z", "memory_id": "abc-123"}'

        def mock_urlopen(req, timeout=None):
            resp = MagicMock()
            resp.read.return_value = response_body
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            return resp

        captured_stdout = io.StringIO()
        with patch.object(push_mod, "urlopen", mock_urlopen):
            with patch("sys.stdout", captured_stdout):
                with self.assertRaises(SystemExit) as ctx:
                    push_snapshot("http://localhost:8002", ROOM_ID, FAKE_TOKEN, VALID_SNAPSHOT_BYTES)
                self.assertEqual(ctx.exception.code, 0)

        output = json.loads(captured_stdout.getvalue())
        self.assertEqual(output["stored_at"], "2026-03-30T14:00:00Z")
        self.assertEqual(output["memory_id"], "abc-123")


# =========================================================================
# HTTP ERROR HANDLING TESTS
# =========================================================================

class TestPushSnapshotErrors(unittest.TestCase):
    """Test error handling for HTTP errors and connection failures."""

    def test_http_error_exits_1(self):
        """HTTP 4xx/5xx should exit 1 and print status."""
        from urllib.error import HTTPError

        def mock_urlopen(req, timeout=None):
            raise HTTPError(
                url=req.full_url,
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=io.BytesIO(b'{"error": "invalid token"}'),
            )

        captured_stderr = io.StringIO()
        with patch.object(push_mod, "urlopen", mock_urlopen):
            with patch("sys.stderr", captured_stderr):
                with self.assertRaises(SystemExit) as ctx:
                    push_snapshot("http://localhost:8002", ROOM_ID, "bad-token", VALID_SNAPSHOT_BYTES)
                self.assertEqual(ctx.exception.code, 1)

        output = captured_stderr.getvalue()
        self.assertIn("401", output)

    def test_connection_error_exits_2(self):
        """Connection refused / unreachable should exit 2."""
        from urllib.error import URLError

        def mock_urlopen(req, timeout=None):
            raise URLError("Connection refused")

        with patch.object(push_mod, "urlopen", mock_urlopen):
            with self.assertRaises(SystemExit) as ctx:
                push_snapshot("http://localhost:9999", ROOM_ID, FAKE_TOKEN, VALID_SNAPSHOT_BYTES)
            self.assertEqual(ctx.exception.code, 2)

    def test_timeout_exits_2(self):
        """Timeout should exit 2."""
        def mock_urlopen(req, timeout=None):
            raise TimeoutError("timed out")

        with patch.object(push_mod, "urlopen", mock_urlopen):
            with self.assertRaises(SystemExit) as ctx:
                push_snapshot("http://localhost:8002", ROOM_ID, FAKE_TOKEN, VALID_SNAPSHOT_BYTES)
            self.assertEqual(ctx.exception.code, 2)


# =========================================================================
# CLI ARGUMENT PARSING TESTS
# =========================================================================

class TestCLIParsing(unittest.TestCase):
    """Test argument parsing."""

    def test_required_args(self):
        """--snapshot and --room-id are required."""
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_default_dialectic_url(self):
        """Default dialectic URL should be http://localhost:8002."""
        parser = build_parser()
        args = parser.parse_args(["--snapshot", "snap.json", "--room-id", ROOM_ID])
        self.assertEqual(args.dialectic_url, "http://localhost:8002")

    def test_custom_dialectic_url(self):
        """--dialectic-url should override the default."""
        parser = build_parser()
        args = parser.parse_args([
            "--snapshot", "snap.json",
            "--room-id", ROOM_ID,
            "--dialectic-url", "https://custom.example.com",
        ])
        self.assertEqual(args.dialectic_url, "https://custom.example.com")

    def test_stdin_snapshot_arg(self):
        """--snapshot - should be accepted for stdin."""
        parser = build_parser()
        args = parser.parse_args(["--snapshot", "-", "--room-id", ROOM_ID])
        self.assertEqual(args.snapshot, "-")


# =========================================================================
# INTEGRATION TEST (with real HTTP server)
# =========================================================================

class TestEndToEndWithMockServer(unittest.TestCase):
    """Integration test using a real HTTP server in a background thread."""

    @classmethod
    def setUpClass(cls):
        """Start a minimal HTTP server that captures the request."""
        cls.captured_requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self_handler):
                content_length = int(self_handler.headers.get("Content-Length", 0))
                body = self_handler.rfile.read(content_length)
                cls.captured_requests.append({
                    "path": self_handler.path,
                    "headers": dict(self_handler.headers),
                    "body": body,
                })
                self_handler.send_response(200)
                self_handler.send_header("Content-Type", "application/json")
                self_handler.end_headers()
                response = json.dumps({
                    "stored_at": "2026-03-30T14:00:00Z",
                    "memory_id": "integ-test-id",
                }).encode()
                self_handler.wfile.write(response)

            def log_message(self_handler, format, *args):
                pass  # Suppress server log noise

        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_full_push(self):
        """End-to-end: push snapshot to mock server, verify request and response."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as f:
            f.write(VALID_SNAPSHOT_BYTES)
            f.flush()
            path = f.name

        self.__class__.captured_requests.clear()
        captured_stdout = io.StringIO()

        try:
            with patch.dict(os.environ, {"DIALECTIC_ROOM_TOKEN": FAKE_TOKEN}):
                with patch("sys.stdout", captured_stdout):
                    with self.assertRaises(SystemExit) as ctx:
                        push_snapshot(
                            f"http://127.0.0.1:{self.port}",
                            ROOM_ID,
                            FAKE_TOKEN,
                            VALID_SNAPSHOT_BYTES,
                        )
                    self.assertEqual(ctx.exception.code, 0)
        finally:
            os.unlink(path)

        # Verify the request hit the correct path
        self.assertEqual(len(self.captured_requests), 1)
        req = self.captured_requests[0]
        self.assertEqual(req["path"], f"/rooms/{ROOM_ID}/trading/snapshot")
        self.assertIn("application/json", req["headers"].get("Content-Type", ""))

        # Verify the request body is our snapshot
        body_parsed = json.loads(req["body"])
        self.assertEqual(body_parsed["v"], 1)
        self.assertEqual(body_parsed["title"], "Test Thesis")

        # Verify stdout got the response
        response = json.loads(captured_stdout.getvalue())
        self.assertEqual(response["memory_id"], "integ-test-id")


if __name__ == "__main__":
    unittest.main()
