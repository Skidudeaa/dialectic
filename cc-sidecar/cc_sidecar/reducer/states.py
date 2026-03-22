"""
Agent state transition table.

ARCHITECTURE: Table-driven state machine. Every legal transition is an
explicit entry. Unknown transitions are logged but do not crash.
WHY: Exhaustive enumeration makes the state machine fully testable
and prevents implicit state changes.
TRADEOFF: Adding a new state or event requires updating this table —
but that is the point. Implicit transitions cause bugs.
"""
from __future__ import annotations

from cc_sidecar.models import AgentState

# Type alias for readability
_S = AgentState

# ============================================================
# Transition table: (current_state, event_name) → new_state
# ============================================================
# WHY: Every entry documents one legal state change. If a
# (state, event) pair is not in this table, the reducer logs
# a warning and leaves the state unchanged.

TRANSITIONS: dict[tuple[AgentState, str], AgentState] = {
    # ── From IDLE ──────────────────────────────────────────
    (_S.IDLE, "PreToolUse"):        _S.RUNNING_TOOL,
    (_S.IDLE, "Stop"):              _S.FINISHED,
    (_S.IDLE, "SessionEnd"):        _S.FINISHED,
    (_S.IDLE, "SubagentStart"):     _S.IDLE,        # spawns child; parent stays idle
    (_S.IDLE, "SubagentStop"):      _S.FINISHED,    # subagent finishing from idle

    # ── From RUNNING_TOOL ─────────────────────────────────
    (_S.RUNNING_TOOL, "PostToolUse"):          _S.IDLE,
    (_S.RUNNING_TOOL, "PostToolUseFailure"):   _S.IDLE,
    (_S.RUNNING_TOOL, "PermissionRequest"):    _S.AWAITING_PERM,
    (_S.RUNNING_TOOL, "PreToolUse"):           _S.RUNNING_TOOL,  # new tool replaces current
    (_S.RUNNING_TOOL, "Stop"):                 _S.FINISHED,
    (_S.RUNNING_TOOL, "SessionEnd"):           _S.FINISHED,
    (_S.RUNNING_TOOL, "StopFailure"):          _S.RETRYING,

    # ── From AWAITING_PERM ────────────────────────────────
    # WHY: No explicit "PermissionGranted" event exists.
    # Permission grant is signaled by the subsequent PreToolUse or PostToolUse.
    (_S.AWAITING_PERM, "PreToolUse"):          _S.RUNNING_TOOL,   # permission granted, tool proceeds
    (_S.AWAITING_PERM, "PostToolUse"):         _S.IDLE,           # granted inline
    (_S.AWAITING_PERM, "PostToolUseFailure"):  _S.BLOCKED,        # denied or failed
    (_S.AWAITING_PERM, "Stop"):                _S.FINISHED,
    (_S.AWAITING_PERM, "SessionEnd"):          _S.FINISHED,

    # ── From BLOCKED (permission denied or repeated failure) ─
    (_S.BLOCKED, "PreToolUse"):    _S.RUNNING_TOOL,  # Claude pivoted to different approach
    (_S.BLOCKED, "Stop"):          _S.FINISHED,
    (_S.BLOCKED, "SessionEnd"):    _S.FINISHED,

    # ── From RETRYING (after StopFailure / rate limit) ────
    (_S.RETRYING, "PreToolUse"):   _S.RUNNING_TOOL,
    (_S.RETRYING, "Stop"):         _S.FINISHED,
    (_S.RETRYING, "SessionEnd"):   _S.FINISHED,
    (_S.RETRYING, "StopFailure"):  _S.RETRYING,      # still retrying

    # ── From FINISHED (terminal, but session can resume) ──
    (_S.FINISHED, "SessionStart"):     _S.IDLE,      # session resume after compaction
    (_S.FINISHED, "PreToolUse"):       _S.RUNNING_TOOL,

    # ── From ORPHANED (can resurrect on any new event) ────
    (_S.ORPHANED, "PreToolUse"):       _S.RUNNING_TOOL,
    (_S.ORPHANED, "PostToolUse"):      _S.IDLE,
    (_S.ORPHANED, "SessionStart"):     _S.IDLE,
    (_S.ORPHANED, "SubagentStart"):    _S.IDLE,
}
