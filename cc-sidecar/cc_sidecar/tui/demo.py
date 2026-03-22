"""
Demo mode: run the TUI with synthetic data, no daemon required.

WHY: Enables development, testing, and showcasing without a
running Claude Code session or daemon.

Usage:
    python -m cc_sidecar.tui.demo
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from cc_sidecar.tui.app import SidecarApp


# ============================================================
# Synthetic session data
# ============================================================

DEMO_SESSION = {
    "session_id": "demo-session-001",
    "model": "claude-opus-4-6",
    "cwd": "/home/user/my-project",
    "context_used_pct": 42.5,
    "context_remaining_pct": 57.5,
    "total_cost_usd": 1.47,
    "compaction_count": 1,
}

DEMO_AGENTS = [
    {
        "agent_pk": "main:demo-session-001",
        "state": "running_tool",
        "state_source": "observed",
        "is_compacting": False,
        "started_at_ms": int(time.time() * 1000) - 120000,
        "last_event_at_ms": int(time.time() * 1000) - 3000,
        "last_tool_name": "Edit",
        "last_resource": "reducer/machine.py",
        "visibility_mode": "full",
    },
    {
        "agent_pk": "sub:demo-session-001:agent-explore-1",
        "state": "running_tool",
        "state_source": "observed",
        "is_compacting": False,
        "started_at_ms": int(time.time() * 1000) - 45000,
        "last_event_at_ms": int(time.time() * 1000) - 1000,
        "last_tool_name": "Grep",
        "last_resource": "/TODO/ in *.py",
        "visibility_mode": "full",
    },
    {
        "agent_pk": "sub:demo-session-001:agent-test-runner",
        "state": "awaiting_perm",
        "state_source": "observed",
        "is_compacting": False,
        "started_at_ms": int(time.time() * 1000) - 30000,
        "last_event_at_ms": int(time.time() * 1000) - 15000,
        "last_tool_name": "Bash",
        "last_resource": "pytest tests/ -v",
        "visibility_mode": "lifecycle_only",
    },
    {
        "agent_pk": "sub:demo-session-001:agent-security",
        "state": "finished",
        "state_source": "observed",
        "is_compacting": False,
        "started_at_ms": int(time.time() * 1000) - 90000,
        "last_event_at_ms": int(time.time() * 1000) - 60000,
        "stopped_at_ms": int(time.time() * 1000) - 60000,
        "last_tool_name": None,
        "last_resource": None,
        "last_summary": "No critical vulnerabilities found",
        "visibility_mode": "lifecycle_only",
    },
]

DEMO_ALERTS = [
    {
        "severity": "info",
        "kind": "compaction",
        "message": "Context compaction started (1st)",
        "created_at_ms": int(time.time() * 1000) - 60000,
    },
    {
        "severity": "warn",
        "kind": "stuck",
        "message": "Agent sub:agent-test-runner awaiting permission for 15s",
        "created_at_ms": int(time.time() * 1000) - 5000,
    },
]

DEMO_EVENTS = [
    {
        "received_at_ms": int(time.time() * 1000) - 120000,
        "event_name": "SessionStart",
        "tool_name": None,
        "resource_summary": None,
        "agent_id": None,
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 115000,
        "event_name": "InstructionsLoaded",
        "tool_name": None,
        "resource_summary": "CLAUDE.md (session_start)",
        "agent_id": None,
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 110000,
        "event_name": "UserPromptSubmit",
        "tool_name": None,
        "resource_summary": None,
        "agent_id": None,
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 100000,
        "event_name": "PreToolUse",
        "tool_name": "Read",
        "resource_summary": "src/models.py:1-50",
        "agent_id": None,
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 98000,
        "event_name": "PostToolUse",
        "tool_name": "Read",
        "resource_summary": "src/models.py:1-50",
        "agent_id": None,
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 90000,
        "event_name": "SubagentStart",
        "tool_name": "Agent",
        "resource_summary": "security: 'Review for vulnerabilities'",
        "agent_id": "agent-security",
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 60000,
        "event_name": "SubagentStop",
        "tool_name": None,
        "resource_summary": "No critical vulnerabilities found",
        "agent_id": "agent-security",
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 58000,
        "event_name": "PreCompact",
        "tool_name": None,
        "resource_summary": None,
        "agent_id": None,
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 55000,
        "event_name": "PostCompact",
        "tool_name": None,
        "resource_summary": None,
        "agent_id": None,
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 45000,
        "event_name": "SubagentStart",
        "tool_name": "Agent",
        "resource_summary": "Explore: 'Find all TODO items'",
        "agent_id": "agent-explore-1",
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 30000,
        "event_name": "SubagentStart",
        "tool_name": "Agent",
        "resource_summary": "test-runner: 'Run all tests' [bg]",
        "agent_id": "agent-test-runner",
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 15000,
        "event_name": "PermissionRequest",
        "tool_name": "Bash",
        "resource_summary": "pytest tests/ -v",
        "agent_id": "agent-test-runner",
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 5000,
        "event_name": "PreToolUse",
        "tool_name": "Grep",
        "resource_summary": "/TODO/ in *.py",
        "agent_id": "agent-explore-1",
        "source_kind": "hook",
    },
    {
        "received_at_ms": int(time.time() * 1000) - 3000,
        "event_name": "PreToolUse",
        "tool_name": "Edit",
        "resource_summary": "reducer/machine.py",
        "agent_id": None,
        "source_kind": "hook",
    },
]


class DemoApp(SidecarApp):
    """TUI with synthetic demo data — no daemon required."""

    SUB_TITLE = "DEMO MODE"

    def on_mount(self) -> None:
        """Load demo data instead of connecting to WebSocket."""
        # Cancel the parent's WebSocket task
        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None

        # Load demo data
        self._handle_snapshot({
            "type": "full_snapshot",
            "sessions": [DEMO_SESSION],
            "agents": DEMO_AGENTS,
            "alerts": DEMO_ALERTS,
            "recent_events": DEMO_EVENTS,
        })

        # Simulate live events every few seconds
        self.set_interval(4, self._simulate_event)
        self._sim_counter = 0

    def _simulate_event(self) -> None:
        """Push a synthetic event to simulate live activity."""
        self._sim_counter += 1
        now_ms = int(time.time() * 1000)

        events = [
            {
                "received_at_ms": now_ms,
                "event_name": "PostToolUse",
                "tool_name": "Grep",
                "resource_summary": "/TODO/ in *.py (3 matches)",
                "agent_id": "agent-explore-1",
                "source_kind": "hook",
            },
            {
                "received_at_ms": now_ms,
                "event_name": "PreToolUse",
                "tool_name": "Read",
                "resource_summary": f"src/file_{self._sim_counter}.py",
                "agent_id": "agent-explore-1",
                "source_kind": "hook",
            },
            {
                "received_at_ms": now_ms,
                "event_name": "PostToolUse",
                "tool_name": "Edit",
                "resource_summary": "reducer/machine.py",
                "agent_id": None,
                "source_kind": "hook",
            },
            {
                "received_at_ms": now_ms,
                "event_name": "PreToolUse",
                "tool_name": "Bash",
                "resource_summary": "python -m pytest tests/ -q",
                "agent_id": None,
                "source_kind": "hook",
            },
        ]

        event = events[self._sim_counter % len(events)]
        self._handle_event({"type": "event", "event": event})

        # Occasionally update context percentage
        if self._sim_counter % 3 == 0:
            pct = min(95, DEMO_SESSION["context_used_pct"] + self._sim_counter * 0.5)
            cost = DEMO_SESSION["total_cost_usd"] + self._sim_counter * 0.03
            sb = self.query_one("SessionBar")
            sb.context_pct = pct
            sb.cost_usd = round(cost, 2)


def main() -> None:
    """Run the demo TUI."""
    app = DemoApp()
    app.run()


if __name__ == "__main__":
    main()
