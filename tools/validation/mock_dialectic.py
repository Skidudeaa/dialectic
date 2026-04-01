#!/usr/bin/env python3
"""
Mock Dialectic Server -- lightweight HTTP server that mimics the Dialectic
trading snapshot endpoint for local testing and E2E validation.

Endpoints:
    POST /rooms/{room_id}/trading/snapshot  — receive a snapshot
    GET  /snapshots                         — list received snapshots (debug)

Usage:
    python3 mock_dialectic.py              # starts on port 8002
    python3 mock_dialectic.py --port 9000  # custom port

The server validates the snapshot payload shape and the Authorization header.
All received snapshots are stored in-memory for later assertion by tests.
"""

import argparse
import json
import re
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional


# WHY: Snapshot schema requires these top-level keys per INTEGRATION.md.
# Used for validation — a 400 is returned if any are missing.
REQUIRED_SNAPSHOT_KEYS = {
    "v", "timestamp", "title", "nodeStates", "confluenceScores",
    "cascadePhase", "countdowns", "marketSnapshot",
    "scenarioImpacts", "portfolioSummary",
}

# Regex for the snapshot endpoint path: /rooms/{uuid-or-id}/trading/snapshot
SNAPSHOT_PATH_RE = re.compile(r"^/rooms/([^/]+)/trading/snapshot$")


class ReceivedSnapshot:
    """Container for a received snapshot with its request metadata."""

    def __init__(self, room_id: str, payload: dict, auth_header: str,
                 content_type: str, user_agent: str) -> None:
        self.room_id = room_id
        self.payload = payload
        self.auth_header = auth_header
        self.content_type = content_type
        self.user_agent = user_agent

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "payload": self.payload,
            "auth_header": self.auth_header,
            "content_type": self.content_type,
            "user_agent": self.user_agent,
        }


class MockDialecticHandler(BaseHTTPRequestHandler):
    """HTTP request handler that mimics the Dialectic trading endpoint."""

    # WHY: Class-level storage so all handler instances share state.
    # The server object also holds a reference for test access.
    received: list[ReceivedSnapshot] = []
    lock = threading.Lock()

    # WHY: Allow tests to inject a custom response code for error simulation.
    # When set to a non-200 value, the next POST returns that code and resets.
    forced_status_code: Optional[int] = None

    def log_message(self, format: str, *args) -> None:
        """Send access logs to stderr so they don't pollute test output."""
        print(f"[mock-dialectic] {format % args}", file=sys.stderr)

    def _send_json(self, code: int, body: dict) -> None:
        """Send a JSON response with the given status code."""
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        """Handle POST /rooms/{room_id}/trading/snapshot."""
        match = SNAPSHOT_PATH_RE.match(self.path)
        if not match:
            self._send_json(404, {"error": f"Not found: {self.path}"})
            return

        room_id = match.group(1)

        # --- Check forced error (for testing server failures) ---
        with self.lock:
            forced = MockDialecticHandler.forced_status_code
            if forced is not None:
                MockDialecticHandler.forced_status_code = None
                self._send_json(forced, {
                    "error": f"Forced test error (status {forced})",
                })
                return

        # --- Validate Authorization header ---
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth.split(" ", 1)[1].strip()) == 0:
            self._send_json(401, {
                "error": "Missing or invalid Authorization header. "
                         "Expected: Bearer <token>",
            })
            return

        # --- Read and parse body ---
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Empty request body"})
            return

        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {
                "error": f"Expected JSON object, got {type(payload).__name__}",
            })
            return

        # --- Validate snapshot schema ---
        missing = REQUIRED_SNAPSHOT_KEYS - set(payload.keys())
        if missing:
            self._send_json(400, {
                "error": f"Missing required snapshot keys: {sorted(missing)}",
            })
            return

        # --- Store the snapshot ---
        content_type = self.headers.get("Content-Type", "")
        user_agent = self.headers.get("User-Agent", "")
        snap = ReceivedSnapshot(room_id, payload, auth, content_type, user_agent)

        with self.lock:
            MockDialecticHandler.received.append(snap)

        self.log_message(
            "Received snapshot for room %s (v=%s, nodes=%d)",
            room_id, payload.get("v"), len(payload.get("nodeStates", {})),
        )

        self._send_json(200, {
            "status": "ok",
            "room_id": room_id,
            "snapshot_version": payload.get("v"),
            "nodes_received": len(payload.get("nodeStates", {})),
        })

    def do_GET(self) -> None:
        """Handle GET /snapshots -- debug endpoint listing received snapshots."""
        if self.path == "/snapshots":
            with self.lock:
                snapshots = [s.to_dict() for s in MockDialecticHandler.received]
            self._send_json(200, {"count": len(snapshots), "snapshots": snapshots})
        else:
            self._send_json(404, {"error": f"Not found: {self.path}"})


def create_server(port: int = 0) -> HTTPServer:
    """Create and return a mock Dialectic server.

    Args:
        port: Port to bind to. Use 0 for a random available port.

    Returns:
        An HTTPServer instance. Call .server_address[1] to get the
        actual port (useful when port=0).
    """
    # WHY: Reset shared state each time a new server is created so tests
    # that create multiple servers don't see stale data.
    with MockDialecticHandler.lock:
        MockDialecticHandler.received = []
        MockDialecticHandler.forced_status_code = None

    server = HTTPServer(("127.0.0.1", port), MockDialecticHandler)
    return server


def start_server_thread(port: int = 0) -> tuple[HTTPServer, threading.Thread]:
    """Start the mock server in a daemon thread.

    Returns:
        (server, thread) tuple. The server is ready to accept requests
        when this function returns. Use server.server_address[1] for
        the actual port. Call server.shutdown() to stop.
    """
    server = create_server(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def get_received_snapshots() -> list[ReceivedSnapshot]:
    """Return a copy of all received snapshots (thread-safe)."""
    with MockDialecticHandler.lock:
        return list(MockDialecticHandler.received)


def clear_received_snapshots() -> None:
    """Clear the received snapshots list (thread-safe)."""
    with MockDialecticHandler.lock:
        MockDialecticHandler.received = []


def force_next_status(code: int) -> None:
    """Force the next POST to return this status code (for error testing)."""
    with MockDialecticHandler.lock:
        MockDialecticHandler.forced_status_code = code


# =========================================================================
# STANDALONE MODE
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mock Dialectic server for testing the tradingDesk bridge.",
    )
    parser.add_argument(
        "--port", type=int, default=8002,
        help="Port to listen on (default: 8002)",
    )
    args = parser.parse_args()

    server = create_server(args.port)
    actual_port = server.server_address[1]
    print(f"Mock Dialectic server listening on http://127.0.0.1:{actual_port}",
          file=sys.stderr)
    print(f"  POST /rooms/{{room_id}}/trading/snapshot  — receive snapshots",
          file=sys.stderr)
    print(f"  GET  /snapshots                           — list received",
          file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.shutdown()


if __name__ == "__main__":
    main()
