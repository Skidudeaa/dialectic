"""
cc-sidecar TUI: Textual-based terminal dashboard.

ARCHITECTURE: Four-pane vertical layout connected to the daemon
via WebSocket. Receives full state snapshot on connect, then
incremental updates. Falls back to offline mode if daemon is
unavailable.

WHY: Terminal-native dashboard works everywhere — no browser,
no VS Code dependency.

TRADEOFF: Textual's DataTable has limited rich text support
compared to a web UI. We compensate with Rich markup in cell
values and color-coded badges.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from cc_sidecar.constants import AUTH_TOKEN_FILE, WS_DEFAULT_PORT
from cc_sidecar.tui.widgets.agent_list import AgentList
from cc_sidecar.tui.widgets.alert_feed import AlertFeed
from cc_sidecar.tui.widgets.event_timeline import EventTimeline
from cc_sidecar.tui.widgets.session_bar import SessionBar

logger = logging.getLogger(__name__)


class SidecarApp(App):
    """cc-sidecar terminal dashboard."""

    TITLE = "cc-sidecar"
    SUB_TITLE = "Claude Code observability"
    CSS_PATH = "styles.css"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f", "toggle_filter", "Filter"),
        Binding("r", "refresh", "Refresh"),
        Binding("c", "clear_alerts", "Clear alerts"),
    ]

    def __init__(
        self,
        ws_port: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.ws_port = ws_port or int(os.environ.get("CC_SIDECAR_WS_PORT", WS_DEFAULT_PORT))
        self._ws_task: Optional[asyncio.Task[None]] = None
        self._connected = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield SessionBar()
        yield AgentList()
        yield AlertFeed()
        yield EventTimeline()
        yield Footer()

    def on_mount(self) -> None:
        """Start WebSocket client on mount."""
        self._ws_task = asyncio.create_task(self._ws_loop())
        # Periodic agent elapsed time refresh
        self.set_interval(2, self._refresh_elapsed)

    async def _ws_loop(self) -> None:
        """
        Connect to daemon WebSocket with reconnect logic.

        WHY: The TUI should survive daemon restarts gracefully.
        Exponential backoff prevents busy-looping on repeated failures.
        """
        backoff = 1.0

        while True:
            try:
                await self._connect_ws()
                backoff = 1.0  # Reset on successful connection
            except Exception as e:
                logger.debug("WebSocket error: %s", e)
                if self._connected:
                    self._connected = False
                    self.sub_title = "disconnected — retrying..."
                    self.query_one(SessionBar).model = "[dim]disconnected[/]"

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _connect_ws(self) -> None:
        """Establish WebSocket connection and process messages."""
        try:
            import websockets
        except ImportError:
            self.sub_title = "websockets not installed"
            await asyncio.sleep(999999)
            return

        # Read auth token
        token = ""
        try:
            token = AUTH_TOKEN_FILE.read_text().strip()
        except FileNotFoundError:
            logger.debug("Auth token file not found at %s", AUTH_TOKEN_FILE)

        uri = f"ws://127.0.0.1:{self.ws_port}/ws?token={token}"

        async with websockets.connect(uri) as ws:
            self._connected = True
            self.sub_title = f"connected (port {self.ws_port})"
            logger.info("Connected to daemon at %s", uri)

            async for message in ws:
                try:
                    data = json.loads(message)
                    self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from WebSocket")

    def _handle_message(self, data: dict[str, Any]) -> None:
        """Dispatch incoming WebSocket message to widgets."""
        msg_type = data.get("type", "")

        if msg_type == "full_snapshot":
            self._handle_snapshot(data)
        elif msg_type == "event":
            self._handle_event(data)
        elif msg_type == "alert":
            self._handle_alert(data)
        else:
            # Try to handle as an event update
            if "event" in data:
                self._handle_event(data)
            if "alert" in data:
                self._handle_alert(data)

    def _handle_snapshot(self, data: dict[str, Any]) -> None:
        """Process full state snapshot on initial connect."""
        sessions = data.get("sessions", [])
        agents = data.get("agents", [])
        alerts = data.get("alerts", [])
        events = data.get("recent_events", [])

        # Update session bar with the most recent active session
        session_bar = self.query_one(SessionBar)
        if sessions:
            # Prefer active (not ended) sessions, or fall back to most recent
            active = [s for s in sessions if not s.get("ended_at_ms")]
            session = active[0] if active else sessions[0]
            session_bar.update_from_session(session)

        # Update agent list
        agent_list = self.query_one(AgentList)
        agent_list.update_agents(agents)
        session_bar.active_agents = len([
            a for a in agents
            if a.get("state") not in ("finished", "orphaned")
        ])

        # Load alerts
        alert_feed = self.query_one(AlertFeed)
        alert_feed.load_alerts(alerts)

        # Load timeline events
        timeline = self.query_one(EventTimeline)
        timeline.load_events(events)

    def _handle_event(self, data: dict[str, Any]) -> None:
        """Process an incremental event update."""
        event = data.get("event", data)

        # Add to timeline
        timeline = self.query_one(EventTimeline)
        timeline.add_event(event)

        # If the event contains agent state, update agent list
        if "agents" in data:
            agent_list = self.query_one(AgentList)
            agent_list.update_agents(data["agents"])

        # Update session bar if session data included
        if "session" in data:
            session_bar = self.query_one(SessionBar)
            session_bar.update_from_session(data["session"])

    def _handle_alert(self, data: dict[str, Any]) -> None:
        """Process an alert."""
        alert = data.get("alert", data)
        alert_feed = self.query_one(AlertFeed)
        alert_feed.add_alert(alert)

    def _refresh_elapsed(self) -> None:
        """
        Periodically refresh elapsed times in the agent list.

        WHY: Elapsed times are computed from timestamps, not pushed
        by the daemon. The TUI must recompute them locally.
        """
        # The agent list stores state but doesn't auto-refresh elapsed.
        # We trigger a refresh request to the daemon by doing nothing here
        # in v1 — the 2s timer exists to remind us this is needed.
        # In practice, each WebSocket update triggers a full agent list
        # refresh, which recomputes elapsed times.
        pass

    # ── Key bindings ──

    def action_toggle_filter(self) -> None:
        """Toggle the timeline filter bar."""
        timeline = self.query_one(EventTimeline)
        timeline.toggle_filter()

    def action_refresh(self) -> None:
        """Force reconnect to daemon."""
        if self._ws_task:
            self._ws_task.cancel()
        self._ws_task = asyncio.create_task(self._ws_loop())
        self.sub_title = "reconnecting..."

    def action_clear_alerts(self) -> None:
        """Clear the alert feed display."""
        from textual.widgets import RichLog
        alert_log = self.query_one("#alert-log", RichLog)
        alert_log.clear()


def main() -> None:
    """Entry point for cc-sidecar-tui."""
    import argparse

    parser = argparse.ArgumentParser(description="cc-sidecar TUI dashboard")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"WebSocket port (default: {WS_DEFAULT_PORT})",
    )
    args = parser.parse_args()

    app = SidecarApp(ws_port=args.port)
    app.run()


if __name__ == "__main__":
    main()
