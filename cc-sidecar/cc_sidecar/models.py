"""
Pydantic models, enums, and event schemas for cc-sidecar.

ARCHITECTURE: These mirror Claude Code's hook payload structure.
WHY: Typed models catch schema drift early and enable IDE completion.
TRADEOFF: Tight coupling to upstream payloads — version adapters may be
needed as Claude Code evolves.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# Enums
# ============================================================

class AgentState(str, Enum):
    """
    Finite state set for agent lifecycle.

    WHY: Exhaustive enum prevents invalid states; str mixin enables
    JSON serialization and SQLite TEXT storage.
    """
    IDLE = "idle"
    RUNNING_TOOL = "running_tool"
    AWAITING_PERM = "awaiting_perm"
    BLOCKED = "blocked"
    RETRYING = "retrying"
    FINISHED = "finished"
    ORPHANED = "orphaned"


class StateSource(str, Enum):
    """Source-of-truth tier for a derived state value."""
    OBSERVED = "observed"
    RECONCILED = "reconciled"
    INFERRED = "inferred"


class SourceKind(str, Enum):
    """Origin of a raw event."""
    HOOK = "hook"
    STATUSLINE = "statusline"
    GIT = "git"
    TRANSCRIPT = "transcript"


class ToolCallStatus(str, Enum):
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class AlertKind(str, Enum):
    PERMISSION_DENIED = "permission_denied"
    STUCK = "stuck"
    ORPHANED = "orphaned"
    COMPACTION = "compaction"
    CONFIG_CHANGE = "config_change"
    SKILL_CHANGE = "skill_change"
    PARSE_ERROR = "parse_error"


class VisibilityMode(str, Enum):
    """
    Whether we have full tool-level telemetry or only lifecycle events.

    WHY: Settings-level hooks only capture SubagentStart/SubagentStop for
    built-in subagents. Full telemetry requires frontmatter hooks.
    """
    FULL = "full"
    LIFECYCLE_ONLY = "lifecycle_only"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class TaskStatusSource(str, Enum):
    OBSERVED = "observed"
    CUSTOM_PLAN = "custom_plan"
    INFERRED = "inferred"


# ============================================================
# Hook event names (canonical set as of Claude Code v2.1.80+)
# ============================================================

HOOK_EVENTS = frozenset({
    "SessionStart",
    "InstructionsLoaded",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "StopFailure",
    "TeammateIdle",
    "TaskCompleted",
    "ConfigChange",
    "WorktreeCreate",
    "WorktreeRemove",
    "PreCompact",
    "PostCompact",
    "Elicitation",
    "ElicitationResult",
    "SessionEnd",
})


# ============================================================
# Envelope: metadata wrapper added by the emit CLI
# ============================================================

class EventEnvelope(BaseModel):
    """
    Wrapper added by cc-sidecar-emit around the upstream hook payload.

    WHY: Separates sidecar metadata (received_at, mono_seq) from the
    upstream payload so dedup_hash covers only upstream content.
    """
    received_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    mono_seq: int
    emitter_version: str
    hook_event: str
    is_subagent: bool = False
    session_id: str = ""
    agent_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    dedup_hash: str = ""


# ============================================================
# Snapshot models (derived state served to UI clients)
# ============================================================

class AgentSnapshot(BaseModel):
    """Current state of a single agent, served via WebSocket."""
    agent_pk: str
    session_id: str
    agent_id: Optional[str] = None
    parent_agent_pk: Optional[str] = None
    agent_type: str
    state: AgentState
    state_source: StateSource
    is_compacting: bool = False
    started_at_ms: Optional[int] = None
    last_event_at_ms: Optional[int] = None
    stopped_at_ms: Optional[int] = None
    last_tool_name: Optional[str] = None
    last_resource: Optional[str] = None
    last_summary: Optional[str] = None
    visibility_mode: VisibilityMode
    tool_count: int = 0
    error_count: int = 0


class SessionSnapshot(BaseModel):
    """Current state of a session, served via WebSocket."""
    session_id: str
    source: Optional[str] = None
    model: Optional[str] = None
    cwd: Optional[str] = None
    project_dir: Optional[str] = None
    started_at_ms: Optional[int] = None
    last_seen_at_ms: Optional[int] = None
    context_used_pct: Optional[float] = None
    context_remaining_pct: Optional[float] = None
    total_cost_usd: float = 0.0
    compaction_count: int = 0
    worktree_path: Optional[str] = None
    worktree_branch: Optional[str] = None


class AlertSnapshot(BaseModel):
    """An alert event served to UI clients."""
    id: int
    session_id: str
    severity: AlertSeverity
    kind: AlertKind
    message: str
    created_at_ms: int
    resolved_at_ms: Optional[int] = None


class ToolCallSnapshot(BaseModel):
    """A tool invocation record."""
    tool_use_id: str
    session_id: str
    agent_pk: str
    tool_name: str
    status: ToolCallStatus
    started_at_ms: int
    ended_at_ms: Optional[int] = None
    input_summary: Optional[str] = None
    error: Optional[str] = None


class TimelineEvent(BaseModel):
    """A single event in the timeline feed."""
    id: int
    received_at_ms: int
    session_id: str
    agent_id: Optional[str] = None
    event_name: str
    tool_name: Optional[str] = None
    resource_summary: Optional[str] = None
    source_kind: SourceKind


class FullStateSnapshot(BaseModel):
    """Complete state push on WebSocket connect."""
    sessions: list[SessionSnapshot] = Field(default_factory=list)
    agents: list[AgentSnapshot] = Field(default_factory=list)
    alerts: list[AlertSnapshot] = Field(default_factory=list)
    recent_events: list[TimelineEvent] = Field(default_factory=list)


class StateUpdate(BaseModel):
    """Incremental update pushed via WebSocket."""
    event: Optional[TimelineEvent] = None
    agent: Optional[AgentSnapshot] = None
    session: Optional[SessionSnapshot] = None
    alert: Optional[AlertSnapshot] = None
