"""
Event timeline widget: filterable stream of raw events.

ARCHITECTURE: DataTable with append-only rows, capped at 500.
Filter bar toggleable with 'f' key.
WHY: The timeline answers "what happened" — the raw event feed
behind the derived state shown in other widgets.
TRADEOFF: 500-row cap in memory. Historical queries go through the
daemon's API, not the TUI's in-memory buffer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label
from textual.containers import Horizontal

MAX_TIMELINE_ROWS = 500

# Event name → Rich color
_EVENT_COLORS = {
    "PreToolUse": "green",
    "PostToolUse": "dim green",
    "PostToolUseFailure": "red",
    "PermissionRequest": "yellow",
    "SessionStart": "bold cyan",
    "SessionEnd": "dim cyan",
    "SubagentStart": "magenta",
    "SubagentStop": "dim magenta",
    "Stop": "dim",
    "StopFailure": "bold red",
    "PreCompact": "yellow",
    "PostCompact": "dim yellow",
    "Notification": "blue",
    "ConfigChange": "cyan",
    "InstructionsLoaded": "dim cyan",
    "UserPromptSubmit": "bold white",
    "TaskCompleted": "bold green",
}


def _format_event_name(name: str) -> str:
    """Color-code event name."""
    color = _EVENT_COLORS.get(name, "white")
    return f"[{color}]{name}[/]"


def _short_agent(agent_id: str | None) -> str:
    """Shorten agent ID for display."""
    if not agent_id:
        return "main"
    return agent_id[:10] if len(agent_id) > 10 else agent_id


class EventTimeline(Widget):
    """Filterable event stream."""

    def __init__(self) -> None:
        super().__init__()
        self._filter_event: str = ""
        self._filter_tool: str = ""
        self._filter_agent: str = ""
        self._show_filter = False
        self._events: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Label(" Timeline [dim](f=filter, p=pause)[/]", classes="section-title")
        with Horizontal(id="filter-bar"):
            yield Input(placeholder="event…", id="filter-event")
            yield Input(placeholder="tool…", id="filter-tool")
            yield Input(placeholder="agent…", id="filter-agent")
        table = DataTable(id="timeline-table")
        table.cursor_type = "row"
        table.zebra_stripes = True
        yield table

    def on_mount(self) -> None:
        table = self.query_one("#timeline-table", DataTable)
        table.add_columns("Time", "Event", "Tool", "Resource", "Agent", "Src")

        # Hide filter bar initially
        filter_bar = self.query_one("#filter-bar")
        filter_bar.display = False

    def toggle_filter(self) -> None:
        """Show/hide the filter bar."""
        filter_bar = self.query_one("#filter-bar")
        self._show_filter = not self._show_filter
        filter_bar.display = self._show_filter
        if self._show_filter:
            self.query_one("#filter-event", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update filters when input changes."""
        input_id = event.input.id
        if input_id == "filter-event":
            self._filter_event = event.value.lower()
        elif input_id == "filter-tool":
            self._filter_tool = event.value.lower()
        elif input_id == "filter-agent":
            self._filter_agent = event.value.lower()
        self._rerender()

    def add_event(self, event: dict[str, Any]) -> None:
        """Add a single event to the timeline."""
        self._events.append(event)
        # Cap at MAX_TIMELINE_ROWS
        if len(self._events) > MAX_TIMELINE_ROWS:
            self._events = self._events[-MAX_TIMELINE_ROWS:]

        if self._matches_filter(event):
            self._append_row(event)

    def load_events(self, events: list[dict[str, Any]]) -> None:
        """Load a batch of events (e.g., on initial connect)."""
        self._events = events[-MAX_TIMELINE_ROWS:]
        self._rerender()

    def _matches_filter(self, event: dict[str, Any]) -> bool:
        """Check if an event passes the current filters."""
        if self._filter_event:
            event_name = (event.get("event_name") or "").lower()
            if self._filter_event not in event_name:
                return False
        if self._filter_tool:
            tool = (event.get("tool_name") or "").lower()
            if self._filter_tool not in tool:
                return False
        if self._filter_agent:
            agent = (event.get("agent_id") or "main").lower()
            if self._filter_agent not in agent:
                return False
        return True

    def _rerender(self) -> None:
        """Re-render the table with current filters applied."""
        table = self.query_one("#timeline-table", DataTable)
        table.clear()
        for event in self._events:
            if self._matches_filter(event):
                self._append_row(event)

    def _append_row(self, event: dict[str, Any]) -> None:
        """Append a single event row to the DataTable."""
        table = self.query_one("#timeline-table", DataTable)

        ts_ms = event.get("received_at_ms", 0)
        ts = datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S") if ts_ms else "??:??:??"

        event_name = _format_event_name(event.get("event_name", "?"))
        tool = event.get("tool_name") or "—"
        resource = event.get("resource_summary") or "—"
        agent = _short_agent(event.get("agent_id"))
        source = f"[dim]{event.get('source_kind', 'hook')}[/]"

        # Truncate resource
        if len(resource) > 40:
            resource = resource[:39] + "…"

        table.add_row(ts, event_name, tool, resource, agent, source)

        # Auto-scroll to bottom
        table.scroll_end(animate=False)

        # Cap visible rows
        while table.row_count > MAX_TIMELINE_ROWS:
            table.remove_row(table.rows[0].key)
