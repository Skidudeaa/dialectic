"""
Agent list widget: DataTable showing all tracked agents with state badges.

ARCHITECTURE: DataTable with columns for ID, State, Elapsed, Tool, Resource, Source.
WHY: The "what is Claude doing now" question is answered here.
TRADEOFF: DataTable has limited rich text support — state colors use
Rich markup in cell values rather than per-cell CSS classes.
"""
from __future__ import annotations

import time
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

# State → Rich markup color
_STATE_COLORS = {
    "idle": "dim white",
    "running_tool": "bold green",
    "awaiting_perm": "bold yellow",
    "blocked": "bold red",
    "retrying": "yellow",
    "finished": "dim",
    "orphaned": "bold red blink",
}

# Source badges
_SOURCE_BADGES = {
    "observed": "[cyan]obs[/]",
    "reconciled": "[blue]rec[/]",
    "inferred": "[yellow]inf[/]",
}

_VISIBILITY_BADGES = {
    "full": "",
    "lifecycle_only": " [dim]●life[/]",
}


def _format_state(state: str, is_compacting: bool = False) -> str:
    """Render state with color markup."""
    color = _STATE_COLORS.get(state, "white")
    display = state.replace("_", " ")
    if is_compacting:
        display += " ⟳"
    return f"[{color}]{display}[/]"


def _format_elapsed(started_ms: int | None, last_event_ms: int | None) -> str:
    """Format elapsed time since state entry."""
    if not last_event_ms:
        return "—"
    elapsed_s = (int(time.time() * 1000) - last_event_ms) / 1000
    if elapsed_s < 60:
        return f"{int(elapsed_s)}s"
    elif elapsed_s < 3600:
        m, s = divmod(int(elapsed_s), 60)
        return f"{m}m{s:02d}s"
    else:
        h, remainder = divmod(int(elapsed_s), 3600)
        m = remainder // 60
        return f"{h}h{m:02d}m"


def _short_pk(agent_pk: str) -> str:
    """Shorten agent_pk for display."""
    if agent_pk.startswith("main:"):
        return "main"
    if agent_pk.startswith("sub:"):
        parts = agent_pk.split(":")
        if len(parts) >= 3:
            # sub:<session>:<agent_id> → show agent_id truncated
            aid = parts[2]
            return aid[:12] if len(aid) > 12 else aid
    return agent_pk[:16]


class AgentList(Widget):
    """Table of all tracked agents."""

    def compose(self) -> ComposeResult:
        yield Label(" Agents", classes="section-title")
        table = DataTable(id="agent-table")
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.show_cursor = True
        yield table

    def on_mount(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.add_columns("ID", "State", "Elapsed", "Tool", "Resource", "Source")

    def update_agents(self, agents: list[dict[str, Any]]) -> None:
        """Replace the full agent list."""
        table = self.query_one("#agent-table", DataTable)
        table.clear()

        for agent in agents:
            pk = _short_pk(agent.get("agent_pk", "?"))
            state = _format_state(
                agent.get("state", "?"),
                agent.get("is_compacting", False),
            )
            elapsed = _format_elapsed(
                agent.get("started_at_ms"),
                agent.get("last_event_at_ms"),
            )
            tool = agent.get("last_tool_name") or "—"
            resource = agent.get("last_resource") or "—"

            # Source badge
            source = _SOURCE_BADGES.get(
                agent.get("state_source", "observed"), "[cyan]obs[/]"
            )
            vis = _VISIBILITY_BADGES.get(
                agent.get("visibility_mode", "full"), ""
            )
            source_display = f"{source}{vis}"

            # Truncate resource for display
            if len(resource) > 45:
                resource = resource[:44] + "…"

            table.add_row(pk, state, elapsed, tool, resource, source_display)
