"""
cc-sidecard: the long-lived local daemon.

ARCHITECTURE: asyncio event loop managing three concurrent services:
1. Unix socket listener (receives events from cc-sidecar-emit)
2. WebSocket server (pushes state to TUI / web clients)
3. Periodic timers (orphan detection, maintenance)

WHY: Single-process daemon keeps operational complexity low.
TRADEOFF: Python's GIL limits true parallelism, but at 35 events/sec
peak, the bottleneck is I/O (socket, SQLite), not CPU.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional

from cc_sidecar.constants import (
    AUTH_TOKEN_FILE,
    DAEMON_SOCKET_PATH,
    DIR_MODE,
    FILE_MODE,
    PID_FILE,
    RUNTIME_DIR,
    STATUSLINE_FILE,
    WS_DEBOUNCE_MS,
    WS_DEFAULT_PORT,
)
from cc_sidecar.daemon.ingest import IngestPipeline
from cc_sidecar.daemon.spool import ensure_spool_dir, replay_spool_files
from cc_sidecar.daemon.timers import MaintenanceTimer, OrphanDetector
from cc_sidecar.reducer.machine import ReducerRegistry
from cc_sidecar.store.database import apply_schema, get_connection

logger = logging.getLogger(__name__)


class SidecarDaemon:
    """
    Main daemon orchestrator.

    Manages lifecycle of all services, holds shared state
    (database connection, reducer registry, WebSocket clients).
    """

    def __init__(
        self,
        ws_port: Optional[int] = None,
        ws_host: Optional[str] = None,
        http_port: Optional[int] = None,
    ) -> None:
        self.ws_port = ws_port or int(os.environ.get("CC_SIDECAR_WS_PORT", WS_DEFAULT_PORT))
        self.ws_host = ws_host or os.environ.get("CC_SIDECAR_WS_HOST", "127.0.0.1")
        self.http_port = http_port or int(os.environ.get("CC_SIDECAR_HTTP_PORT", "0"))  # 0 = disabled
        self.registry = ReducerRegistry()
        self.db: Optional[Any] = None
        self.pipeline: Optional[IngestPipeline] = None
        self.orphan_detector: Optional[OrphanDetector] = None
        self.maintenance_timer: Optional[MaintenanceTimer] = None
        self._ws_clients: set[Any] = set()
        self._auth_token: str = ""
        self._debounce_handle: Optional[asyncio.TimerHandle] = None
        self._pending_updates: list[dict[str, Any]] = []
        self._running = False

    async def start(self) -> None:
        """Initialize all services and enter the main loop."""
        logger.info("cc-sidecard starting...")

        # Create runtime directories
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        ensure_spool_dir()

        # Generate auth token for WebSocket
        self._auth_token = secrets.token_urlsafe(32)
        AUTH_TOKEN_FILE.write_text(self._auth_token)
        os.chmod(AUTH_TOKEN_FILE, FILE_MODE)
        logger.info("Auth token written to %s", AUTH_TOKEN_FILE)

        # Check for existing daemon
        if PID_FILE.exists():
            try:
                old_pid = int(PID_FILE.read_text().strip())
                os.kill(old_pid, 0)  # Check if process exists
                logger.error(
                    "Another daemon is already running (pid=%d). "
                    "Kill it first or remove %s",
                    old_pid, PID_FILE,
                )
                raise RuntimeError(f"Daemon already running (pid={old_pid})")
            except (ProcessLookupError, ValueError):
                # Stale PID file — previous daemon crashed
                logger.info("Removing stale PID file (pid=%s)", PID_FILE.read_text().strip())
                PID_FILE.unlink(missing_ok=True)

        # Write PID file
        PID_FILE.write_text(str(os.getpid()))
        os.chmod(PID_FILE, FILE_MODE)

        # Open database
        self.db = await get_connection()
        await apply_schema(self.db)
        logger.info("Database ready")

        # Initialize pipeline
        self.pipeline = IngestPipeline(
            db=self.db,
            registry=self.registry,
            broadcast_fn=self._queue_broadcast,
        )

        # Replay spool files
        replay_count = 0
        async for event_json in replay_spool_files():
            await self.pipeline.process_event(event_json)
            replay_count += 1
        if replay_count:
            logger.info("Replayed %d spool events", replay_count)

        # Start timers
        self.orphan_detector = OrphanDetector(
            db=self.db,
            registry=self.registry,
            broadcast_fn=self._queue_broadcast,
        )
        self.orphan_detector.start()

        self.maintenance_timer = MaintenanceTimer(db=self.db)
        self.maintenance_timer.start()

        self._running = True

        # Start services concurrently
        services = [
            self._run_socket_server(),
            self._run_ws_server(),
        ]
        if self.http_port:
            services.append(self._run_http_server())
        await asyncio.gather(*services)

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("cc-sidecard shutting down...")
        self._running = False

        if self.orphan_detector:
            self.orphan_detector.stop()
        if self.maintenance_timer:
            self.maintenance_timer.stop()

        # Close WebSocket clients
        for client in list(self._ws_clients):
            try:
                await client.close()
            except Exception:
                pass

        # Close database
        if self.db:
            await self.db.close()

        # Clean up PID file
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass

        logger.info("cc-sidecard stopped")

    # ── Unix socket server ──

    async def _run_socket_server(self) -> None:
        """Listen on Unix domain socket for events from cc-sidecar-emit."""
        # Remove stale socket
        if DAEMON_SOCKET_PATH.exists():
            DAEMON_SOCKET_PATH.unlink()

        server = await asyncio.start_unix_server(
            self._handle_socket_client,
            path=str(DAEMON_SOCKET_PATH),
        )

        # Set socket permissions to owner-only
        os.chmod(DAEMON_SOCKET_PATH, FILE_MODE)
        logger.info("Socket server listening on %s", DAEMON_SOCKET_PATH)

        async with server:
            await server.serve_forever()

    async def _handle_socket_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single connection from cc-sidecar-emit."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                event_json = line.decode("utf-8").strip()
                if event_json and self.pipeline:
                    await self.pipeline.process_event(event_json)
        except Exception as e:
            logger.debug("Socket client error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── WebSocket server ──

    async def _run_ws_server(self) -> None:
        """Serve WebSocket connections for UI clients."""
        try:
            import websockets
            from websockets.asyncio.server import serve
        except ImportError:
            logger.warning("websockets not installed — WebSocket server disabled")
            # Keep running without WS
            while self._running:
                await asyncio.sleep(60)
            return

        async def handler(websocket: Any) -> None:
            # Validate auth token
            token = None
            if hasattr(websocket, 'request') and websocket.request:
                # Check query parameter
                path = str(getattr(websocket.request, 'path', ''))
                if '?token=' in path:
                    token = path.split('?token=')[-1].split('&')[0]
                # Check header
                headers = getattr(websocket.request, 'headers', {})
                auth_header = headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header[7:]

            if token != self._auth_token:
                logger.warning("WebSocket client rejected: invalid auth token")
                await websocket.close(4001, "Invalid auth token")
                return

            self._ws_clients.add(websocket)
            logger.info("WebSocket client connected (%d total)", len(self._ws_clients))

            try:
                # Send full state snapshot on connect
                snapshot = await self._build_full_snapshot()
                await websocket.send(json.dumps(snapshot))

                # Keep connection alive, handle pings
                async for message in websocket:
                    # Clients don't send meaningful messages in v1
                    pass
            except Exception:
                pass
            finally:
                self._ws_clients.discard(websocket)
                logger.info("WebSocket client disconnected (%d remaining)", len(self._ws_clients))

        async with serve(handler, self.ws_host, self.ws_port):
            logger.info("WebSocket server listening on ws://%s:%d", self.ws_host, self.ws_port)
            while self._running:
                await asyncio.sleep(1)

    # ── HTTP server (web dashboard) ──

    async def _run_http_server(self) -> None:
        """
        Serve the web dashboard over HTTP.

        WHY: Provides browser-accessible UI for remote access (e.g., from
        a DigitalOcean droplet). Serves a single HTML page that connects
        to the WebSocket on the same host.
        """
        from http.server import BaseHTTPRequestHandler
        from http import HTTPStatus

        daemon_ref = self

        class Handler(asyncio.Protocol):
            """Minimal async HTTP handler."""
            pass

        # Use aiohttp-free approach: raw asyncio HTTP server
        async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                request_line = await asyncio.wait_for(reader.readline(), timeout=5)
                if not request_line:
                    writer.close()
                    return

                # Read headers (consume them)
                while True:
                    line = await reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break

                path = request_line.decode().split(" ")[1] if b" " in request_line else "/"

                if path == "/api/state":
                    # JSON API endpoint
                    snapshot = await daemon_ref._build_full_snapshot()
                    body = json.dumps(snapshot).encode()
                    content_type = "application/json"
                elif path == "/api/health":
                    body = json.dumps({"status": "ok", "pid": os.getpid()}).encode()
                    content_type = "application/json"
                else:
                    # Serve the dashboard HTML
                    dashboard_path = Path(__file__).parent / "dashboard.html"
                    if dashboard_path.exists():
                        body = dashboard_path.read_bytes()
                    else:
                        body = b"<h1>cc-sidecar</h1><p>dashboard.html not found</p>"
                    content_type = "text/html; charset=utf-8"

                response = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"Access-Control-Allow-Origin: *\r\n"
                    f"Connection: close\r\n"
                    f"\r\n"
                ).encode() + body

                writer.write(response)
                await writer.drain()
            except Exception as e:
                logger.debug("HTTP handler error: %s", e)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        server = await asyncio.start_server(
            handle_http, "0.0.0.0", self.http_port,
        )
        logger.info("HTTP dashboard listening on http://0.0.0.0:%d", self.http_port)

        async with server:
            await server.serve_forever()

    async def _build_full_snapshot(self) -> dict[str, Any]:
        """Build a complete state snapshot for new WebSocket clients."""
        sessions = []
        for machine_session_id in {m.session_id for m in self.registry.get_all_agents()}:
            if self.db:
                session_data = await self.db.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (machine_session_id,),
                )
                row = await session_data.fetchone()
                if row:
                    sessions.append(dict(row))

        agents = [m.to_snapshot() for m in self.registry.get_all_agents()]

        alerts = []
        if self.db:
            for session in sessions:
                sid = session.get("session_id", "")
                from cc_sidecar.store.queries import get_active_alerts
                session_alerts = await get_active_alerts(self.db, sid)
                alerts.extend(session_alerts)

        return {
            "type": "full_snapshot",
            "sessions": sessions,
            "agents": agents,
            "alerts": alerts,
        }

    async def _queue_broadcast(self, update: dict[str, Any]) -> None:
        """
        Queue a state update for WebSocket broadcast with debouncing.

        WHY: During rapid tool use (5-10 events/sec), pushing every state
        change is wasteful. 200ms debounce coalesces bursts.
        Alert updates bypass the debounce for immediate delivery.
        """
        if not self._ws_clients:
            return

        # Alerts bypass debounce
        if update.get("type") == "alert" or "alert" in update:
            await self._broadcast_now(update)
            return

        self._pending_updates.append(update)

        # Reset debounce timer
        if self._debounce_handle:
            self._debounce_handle.cancel()

        loop = asyncio.get_event_loop()
        self._debounce_handle = loop.call_later(
            WS_DEBOUNCE_MS / 1000.0,
            lambda: asyncio.ensure_future(self._flush_pending()),
        )

    async def _flush_pending(self) -> None:
        """Send all pending updates to WebSocket clients."""
        if not self._pending_updates:
            return

        updates = self._pending_updates
        self._pending_updates = []

        # Send the most recent update (coalesced)
        # WHY: For state updates, only the latest matters
        await self._broadcast_now(updates[-1])

    async def _broadcast_now(self, data: dict[str, Any]) -> None:
        """Send data to all connected WebSocket clients immediately."""
        if not self._ws_clients:
            return

        message = json.dumps(data)
        dead_clients = set()

        for client in self._ws_clients:
            try:
                await client.send(message)
            except Exception:
                dead_clients.add(client)

        self._ws_clients -= dead_clients

    # ── Statusline state file ──

    async def _write_statusline_file(self, data: dict[str, Any]) -> None:
        """
        Write enriched statusline data to a shared file.

        WHY: The statusline script reads this file via `cat` (3ms) instead
        of connecting to the daemon socket (25-40ms with Python).
        """
        try:
            tmp = STATUSLINE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.rename(STATUSLINE_FILE)
            os.chmod(STATUSLINE_FILE, FILE_MODE)
        except OSError as e:
            logger.debug("Failed to write statusline file: %s", e)


def main() -> None:
    """Entry point for cc-sidecard."""
    import argparse

    parser = argparse.ArgumentParser(description="cc-sidecar daemon")
    parser.add_argument("--ws-port", type=int, default=None, help="WebSocket port")
    parser.add_argument("--ws-host", default=None, help="WebSocket bind host")
    parser.add_argument("--http-port", type=int, default=None, help="HTTP dashboard port (0=disabled)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    daemon = SidecarDaemon(
        ws_port=args.ws_port,
        ws_host=args.ws_host,
        http_port=args.http_port,
    )
    shutdown_event = asyncio.Event()

    async def run_daemon() -> None:
        """Run daemon until shutdown signal."""
        # WHY: We use an Event instead of loop.stop() so that the
        # shutdown coroutine can complete before the loop exits.
        loop = asyncio.get_event_loop()

        def handle_signal(sig: int) -> None:
            logger.info("Received signal %d", sig)
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal, sig)

        # Start daemon services as background tasks
        start_task = asyncio.create_task(daemon.start())

        # Wait for shutdown signal
        await shutdown_event.wait()

        # Cancel the start task (which runs serve_forever)
        start_task.cancel()
        try:
            await start_task
        except (asyncio.CancelledError, RuntimeError):
            pass

        # Graceful cleanup
        await daemon.stop()

    try:
        asyncio.run(run_daemon())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
