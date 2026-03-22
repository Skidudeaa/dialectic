"""
Tests for the reducer state machine.

Covers all mandatory test cases from the spec plus edge cases.
"""
from __future__ import annotations

import time

import pytest

from cc_sidecar.models import AgentState, StateSource, VisibilityMode
from cc_sidecar.reducer.machine import AgentStateMachine, ReducerRegistry


class TestAgentStateMachine:
    """Test individual state transitions."""

    def _machine(self, **kwargs) -> AgentStateMachine:
        return AgentStateMachine(
            session_id="test-001",
            **kwargs,
        )

    # ── Basic transitions ──

    def test_idle_to_running_on_pre_tool_use(self):
        m = self._machine()
        assert m.state == AgentState.IDLE
        new = m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert new == AgentState.RUNNING_TOOL
        assert m.last_tool_name == "Read"
        assert m.tool_count == 1

    def test_running_to_idle_on_post_tool_use(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        new = m.apply("PostToolUse", {"tool_use_id": "t1"})
        assert new == AgentState.IDLE
        assert m.last_tool_name is None

    def test_running_to_idle_on_failure(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Bash", "tool_input": {}})
        new = m.apply("PostToolUseFailure", {"error": "timeout"})
        assert new == AgentState.IDLE
        assert m.error_count == 1

    def test_running_to_awaiting_perm(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Bash", "tool_input": {}})
        new = m.apply("PermissionRequest", {"tool_name": "Bash"})
        assert new == AgentState.AWAITING_PERM

    def test_awaiting_perm_to_running_on_grant(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Bash", "tool_input": {}})
        m.apply("PermissionRequest", {})
        new = m.apply("PreToolUse", {"tool_name": "Bash", "tool_input": {}})
        assert new == AgentState.RUNNING_TOOL

    def test_awaiting_perm_to_blocked_on_denial(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Bash", "tool_input": {}})
        m.apply("PermissionRequest", {})
        new = m.apply("PostToolUseFailure", {"error": "denied"})
        assert new == AgentState.BLOCKED

    def test_blocked_to_running_on_new_tool(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Bash", "tool_input": {}})
        m.apply("PermissionRequest", {})
        m.apply("PostToolUseFailure", {"error": "denied"})
        assert m.state == AgentState.BLOCKED
        new = m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        assert new == AgentState.RUNNING_TOOL

    def test_stop_from_idle(self):
        m = self._machine()
        new = m.apply("Stop", {})
        assert new == AgentState.FINISHED

    def test_stop_from_running(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        new = m.apply("Stop", {})
        assert new == AgentState.FINISHED
        assert m.stopped_at_ms is not None

    def test_session_end_from_idle(self):
        m = self._machine()
        new = m.apply("SessionEnd", {})
        assert new == AgentState.FINISHED

    def test_stop_failure_to_retrying(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        new = m.apply("StopFailure", {})
        assert new == AgentState.RETRYING
        assert m.error_count == 1

    def test_retrying_to_running_on_new_tool(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        m.apply("StopFailure", {})
        assert m.state == AgentState.RETRYING
        new = m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        assert new == AgentState.RUNNING_TOOL

    # ── Compaction (flag, not state) ──

    def test_compaction_sets_flag(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        assert m.state == AgentState.RUNNING_TOOL
        m.apply("PreCompact", {})
        assert m.is_compacting is True
        # Underlying state should be preserved
        assert m.state == AgentState.RUNNING_TOOL

    def test_post_compact_clears_flag_and_downgrades(self):
        m = self._machine()
        m.apply("PreCompact", {})
        assert m.is_compacting is True
        m.apply("PostCompact", {})
        assert m.is_compacting is False
        assert m.state_source == StateSource.INFERRED

    def test_session_start_compact_resets(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        m.apply("PreCompact", {})
        new = m.apply("SessionStart", {"source": "compact"})
        assert new == AgentState.IDLE
        assert m.is_compacting is False
        assert m.state_source == StateSource.INFERRED

    # ── Orphan detection ──

    def test_mark_orphaned(self):
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        m.mark_orphaned()
        assert m.state == AgentState.ORPHANED
        assert m.state_source == StateSource.INFERRED

    def test_orphan_can_resurrect(self):
        m = self._machine()
        m.mark_orphaned()
        new = m.apply("PreToolUse", {"tool_name": "Read", "tool_input": {}})
        assert new == AgentState.RUNNING_TOOL

    # ── Finished can resume ──

    def test_finished_can_resume_on_session_start(self):
        m = self._machine()
        m.apply("Stop", {})
        assert m.state == AgentState.FINISHED
        new = m.apply("SessionStart", {"source": "resume"})
        assert new == AgentState.IDLE

    # ── Tool tracking ──

    def test_tool_name_normalized(self):
        """Task tool name should be normalized to Agent."""
        m = self._machine()
        m.apply("PreToolUse", {"tool_name": "Task", "tool_input": {"prompt": "test"}})
        assert m.last_tool_name == "Agent"

    def test_subagent_stop_captures_summary(self):
        m = self._machine()
        m.apply("SubagentStop", {"last_assistant_message": "Found 3 files"})
        assert m.last_summary == "Found 3 files"

    # ── Unknown transitions ──

    def test_unknown_transition_returns_none(self):
        m = self._machine()
        result = m.apply("UnknownEvent", {})
        assert result is None
        assert m.state == AgentState.IDLE  # Unchanged


class TestReducerRegistry:
    """Test event routing across multiple agents."""

    def test_main_agent_created_on_first_event(self):
        reg = ReducerRegistry()
        machine, state = reg.route_event("s1", None, "PreToolUse", {"tool_name": "Read", "tool_input": {}})
        assert machine.agent_pk == "main:s1"
        assert state == AgentState.RUNNING_TOOL

    def test_subagent_created_on_start(self):
        reg = ReducerRegistry()
        machine, state = reg.route_event(
            "s1", None, "SubagentStart",
            {"agent_id": "a1", "agent_type": "Explore"},
        )
        assert machine.agent_pk == "sub:s1:a1"
        assert machine.agent_type == "Explore"

    def test_concurrent_agents_independent(self):
        """Multiple agents in same session have independent state machines."""
        reg = ReducerRegistry()

        # Main agent starts tool
        reg.route_event("s1", None, "PreToolUse", {"tool_name": "Read", "tool_input": {}})

        # Subagent starts
        reg.route_event("s1", None, "SubagentStart", {"agent_id": "a1", "agent_type": "test"})

        # Subagent starts tool
        reg.route_event("s1", "a1", "PreToolUse", {"tool_name": "Bash", "tool_input": {}})

        main = reg.get("main:s1")
        sub = reg.get("sub:s1:a1")

        assert main is not None
        assert sub is not None
        assert main.state == AgentState.RUNNING_TOOL
        assert sub.state == AgentState.RUNNING_TOOL

        # Main finishes tool
        reg.route_event("s1", None, "PostToolUse", {"tool_use_id": "t1"})

        assert main.state == AgentState.IDLE
        assert sub.state == AgentState.RUNNING_TOOL  # Still running

    def test_subagent_stop_without_start(self):
        """SubagentStop without prior SubagentStart should not crash."""
        reg = ReducerRegistry()
        machine, state = reg.route_event(
            "s1", None, "SubagentStop",
            {"agent_id": "orphan", "agent_type": "unknown", "last_assistant_message": "done"},
        )
        assert machine.agent_pk == "sub:s1:orphan"
        assert state == AgentState.FINISHED

    def test_agent_pk_scoped_to_session(self):
        """Same agent_id in different sessions should not collide."""
        reg = ReducerRegistry()
        reg.route_event("s1", None, "SubagentStart", {"agent_id": "a1", "agent_type": "t1"})
        reg.route_event("s2", None, "SubagentStart", {"agent_id": "a1", "agent_type": "t2"})

        m1 = reg.get("sub:s1:a1")
        m2 = reg.get("sub:s2:a1")

        assert m1 is not None
        assert m2 is not None
        assert m1.agent_pk != m2.agent_pk
        assert m1.session_id == "s1"
        assert m2.session_id == "s2"

    def test_get_active_agents(self):
        reg = ReducerRegistry()
        reg.route_event("s1", None, "PreToolUse", {"tool_name": "Read", "tool_input": {}})
        reg.route_event("s1", None, "SubagentStart", {"agent_id": "a1", "agent_type": "test"})

        active = reg.get_active_agents()
        assert len(active) == 2

        # Finish the subagent
        reg.route_event("s1", None, "SubagentStop", {"agent_id": "a1", "last_assistant_message": "done"})

        active = reg.get_active_agents()
        assert len(active) == 1
        assert active[0].agent_pk == "main:s1"
