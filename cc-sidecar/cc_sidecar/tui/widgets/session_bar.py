"""
Session bar widget: model, cwd, context %, cost, compactions, agent count.

ARCHITECTURE: Horizontal strip at the top of the TUI. Updates reactively
from session and statusline data pushed via WebSocket.
WHY: Provides at-a-glance session health — the most-checked information.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


def _context_bar(pct: float) -> str:
    """
    Render a 10-char bar with color indicator.

    WHY: Visual representation is faster to parse than a number.
    Green <70%, yellow 70-89%, red >=90%.
    """
    filled = int(pct / 10)
    empty = 10 - filled
    bar = "█" * filled + "░" * empty

    if pct >= 90:
        return f"[red]{bar}[/] {pct:.0f}%"
    elif pct >= 70:
        return f"[yellow]{bar}[/] {pct:.0f}%"
    else:
        return f"[green]{bar}[/] {pct:.0f}%"


def _short_cwd(cwd: str) -> str:
    """Shorten cwd to last 2 components."""
    if not cwd:
        return "—"
    parts = cwd.rstrip("/").split("/")
    if len(parts) > 2:
        return "/".join(parts[-2:])
    return cwd


class SessionBar(Widget):
    """Top bar showing session metadata."""

    model: reactive[str] = reactive("—")
    cwd: reactive[str] = reactive("—")
    context_pct: reactive[float] = reactive(0.0)
    cost_usd: reactive[float] = reactive(0.0)
    compaction_count: reactive[int] = reactive(0)
    active_agents: reactive[int] = reactive(0)
    session_id: reactive[str] = reactive("—")

    def compose(self) -> ComposeResult:
        yield Label("—", classes="model-label", id="model")
        yield Label("—", classes="cwd-label", id="cwd")
        yield Label("░░░░░░░░░░ 0%", classes="context-bar", id="context")
        yield Label("$0.00", classes="cost-label", id="cost")
        yield Label("C:0", classes="compact-label", id="compact")
        yield Label("agents:0", classes="agent-count-label", id="agents")

    def watch_model(self, value: str) -> None:
        self.query_one("#model", Label).update(f"[bold cyan]{value}[/]")

    def watch_cwd(self, value: str) -> None:
        self.query_one("#cwd", Label).update(_short_cwd(value))

    def watch_context_pct(self, value: float) -> None:
        self.query_one("#context", Label).update(_context_bar(value))

    def watch_cost_usd(self, value: float) -> None:
        self.query_one("#cost", Label).update(f"[yellow]${value:.2f}[/]")

    def watch_compaction_count(self, value: int) -> None:
        self.query_one("#compact", Label).update(f"C:{value}")

    def watch_active_agents(self, value: int) -> None:
        self.query_one("#agents", Label).update(f"agents:{value}")

    def update_from_session(self, session: dict) -> None:
        """Bulk update from a session snapshot dict."""
        if session.get("model"):
            self.model = session["model"]
        if session.get("cwd"):
            self.cwd = session["cwd"]
        if session.get("context_used_pct") is not None:
            self.context_pct = session["context_used_pct"]
        if session.get("total_cost_usd") is not None:
            self.cost_usd = session["total_cost_usd"]
        if session.get("compaction_count") is not None:
            self.compaction_count = session["compaction_count"]
        if session.get("session_id"):
            self.session_id = session["session_id"]
