"""
Alert feed widget: scrolling log of alerts (orphans, compaction, errors).

ARCHITECTURE: RichLog with newest-first ordering, auto-scroll.
WHY: Alerts are the "something needs attention" signal. They must be
visible without clicking or scrolling.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog

# Severity → Rich markup
_SEVERITY_MARKUP = {
    "info": "[cyan]INFO[/]",
    "warn": "[yellow]WARN[/]",
    "error": "[bold red]ERROR[/]",
}

# Kind → icon
_KIND_ICONS = {
    "permission_denied": "⛔",
    "stuck": "⏳",
    "orphaned": "👻",
    "compaction": "📦",
    "config_change": "⚙",
    "skill_change": "🔧",
    "parse_error": "⚠",
}


class AlertFeed(Widget):
    """Scrolling log of alerts."""

    def compose(self) -> ComposeResult:
        yield Label(" Alerts", classes="section-title")
        log = RichLog(id="alert-log", markup=True, max_lines=100)
        log.auto_scroll = True
        yield log

    def add_alert(self, alert: dict[str, Any]) -> None:
        """Add a single alert to the feed."""
        log = self.query_one("#alert-log", RichLog)

        ts_ms = alert.get("created_at_ms", 0)
        ts = datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S") if ts_ms else "??:??:??"

        severity = _SEVERITY_MARKUP.get(alert.get("severity", "info"), "[cyan]INFO[/]")
        kind = alert.get("kind", "")
        icon = _KIND_ICONS.get(kind, "●")
        message = alert.get("message", "")

        log.write(f"[dim]{ts}[/] {severity} {icon} {message}")

    def load_alerts(self, alerts: list[dict[str, Any]]) -> None:
        """Load a batch of alerts (e.g., on initial connect)."""
        log = self.query_one("#alert-log", RichLog)
        log.clear()
        # Show oldest first so newest is at bottom
        for alert in sorted(alerts, key=lambda a: a.get("created_at_ms", 0)):
            self.add_alert(alert)
