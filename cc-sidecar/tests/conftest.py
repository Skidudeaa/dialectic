"""
Test fixtures and factories for cc-sidecar tests.

ARCHITECTURE: Factory-based fixtures with sensible defaults.
WHY: Every test gets a fresh temp database — no cross-test contamination.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import aiosqlite

from cc_sidecar.reducer.machine import AgentStateMachine, ReducerRegistry
from cc_sidecar.models import VisibilityMode
from cc_sidecar.store.database import apply_schema, get_connection


# ============================================================
# Database fixtures
# ============================================================

@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Provide a fresh SQLite database for each test."""
    db_path = tmp_path / "test_events.db"
    conn = await get_connection(db_path)
    await apply_schema(conn)
    yield conn
    await conn.close()


# ============================================================
# Reducer fixtures
# ============================================================

@pytest.fixture
def registry() -> ReducerRegistry:
    """Provide a fresh reducer registry."""
    return ReducerRegistry()


@pytest.fixture
def main_machine() -> AgentStateMachine:
    """Provide a main agent state machine."""
    return AgentStateMachine(
        session_id="test-session-001",
        agent_type="main",
        visibility_mode=VisibilityMode.FULL,
    )


# ============================================================
# Event factories
# ============================================================

_seq_counter = 0


def make_envelope(
    hook_event: str,
    session_id: str = "test-session-001",
    agent_id: str | None = None,
    payload: dict[str, Any] | None = None,
    **extra: Any,
) -> str:
    """Create a JSON envelope string as the emit CLI would produce."""
    global _seq_counter
    _seq_counter += 1

    envelope = {
        "received_at_ms": int(time.time() * 1000),
        "mono_seq": _seq_counter,
        "emitter_version": "cc-sidecar/test",
        "hook_event": hook_event,
        "session_id": session_id,
        "agent_id": agent_id,
        "is_subagent": agent_id is not None,
        "payload": {
            "session_id": session_id,
            "hook_event_name": hook_event,
            **(payload or {}),
        },
    }
    envelope.update(extra)
    return json.dumps(envelope)


def make_session_start(
    session_id: str = "test-session-001",
    source: str = "startup",
    model: str = "claude-sonnet-4-6",
) -> str:
    """Create a SessionStart event."""
    return make_envelope(
        "SessionStart",
        session_id=session_id,
        payload={"source": source, "model": model},
    )


def make_pre_tool_use(
    tool_name: str = "Read",
    tool_input: dict[str, Any] | None = None,
    tool_use_id: str = "tool-001",
    session_id: str = "test-session-001",
    agent_id: str | None = None,
) -> str:
    """Create a PreToolUse event."""
    return make_envelope(
        "PreToolUse",
        session_id=session_id,
        agent_id=agent_id,
        payload={
            "tool_name": tool_name,
            "tool_input": tool_input or {},
            "tool_use_id": tool_use_id,
        },
    )


def make_post_tool_use(
    tool_use_id: str = "tool-001",
    tool_name: str = "Read",
    session_id: str = "test-session-001",
    agent_id: str | None = None,
) -> str:
    """Create a PostToolUse event."""
    return make_envelope(
        "PostToolUse",
        session_id=session_id,
        agent_id=agent_id,
        payload={
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "tool_response": "success",
        },
    )


def make_post_tool_use_failure(
    tool_use_id: str = "tool-001",
    error: str = "Permission denied",
    session_id: str = "test-session-001",
    agent_id: str | None = None,
) -> str:
    """Create a PostToolUseFailure event."""
    return make_envelope(
        "PostToolUseFailure",
        session_id=session_id,
        agent_id=agent_id,
        payload={
            "tool_use_id": tool_use_id,
            "error": error,
            "is_interrupt": False,
        },
    )


def make_subagent_start(
    agent_id: str = "sub-001",
    agent_type: str = "Explore",
    session_id: str = "test-session-001",
) -> str:
    """Create a SubagentStart event."""
    return make_envelope(
        "SubagentStart",
        session_id=session_id,
        payload={
            "agent_id": agent_id,
            "agent_type": agent_type,
        },
    )


def make_subagent_stop(
    agent_id: str = "sub-001",
    agent_type: str = "Explore",
    summary: str = "Found 5 test files",
    session_id: str = "test-session-001",
) -> str:
    """Create a SubagentStop event."""
    return make_envelope(
        "SubagentStop",
        session_id=session_id,
        payload={
            "agent_id": agent_id,
            "agent_type": agent_type,
            "last_assistant_message": summary,
        },
    )


def make_permission_request(
    tool_name: str = "Bash",
    tool_use_id: str = "tool-001",
    session_id: str = "test-session-001",
) -> str:
    """Create a PermissionRequest event."""
    return make_envelope(
        "PermissionRequest",
        session_id=session_id,
        payload={
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
        },
    )


def make_pre_compact(session_id: str = "test-session-001") -> str:
    """Create a PreCompact event."""
    return make_envelope("PreCompact", session_id=session_id)


def make_post_compact(session_id: str = "test-session-001") -> str:
    """Create a PostCompact event."""
    return make_envelope("PostCompact", session_id=session_id)


def make_stop(session_id: str = "test-session-001") -> str:
    """Create a Stop event."""
    return make_envelope("Stop", session_id=session_id)


def make_session_end(session_id: str = "test-session-001") -> str:
    """Create a SessionEnd event."""
    return make_envelope("SessionEnd", session_id=session_id)
