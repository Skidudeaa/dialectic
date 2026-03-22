"""
Agent state machine: per-agent reducer driven by hook events.

ARCHITECTURE: Each agent (main thread or subagent) gets its own
AgentStateMachine instance. The reducer feeds events to the correct
machine based on agent_pk routing.
WHY: Centralizes all state logic in one testable place.
TRADEOFF: Table-driven transitions are rigid but exhaustively verifiable.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from cc_sidecar.models import AgentState, StateSource, VisibilityMode
from cc_sidecar.reducer.extractor import extract_resource, normalize_tool_name
from cc_sidecar.reducer.states import TRANSITIONS

logger = logging.getLogger(__name__)


class AgentStateMachine:
    """
    Per-agent state reducer.

    Maintains the current state of a single agent and applies
    events according to the transition table. Tracks tool activity,
    error counts, and compaction flag.
    """

    def __init__(
        self,
        session_id: str,
        agent_id: Optional[str] = None,
        agent_type: str = "main",
        visibility_mode: VisibilityMode = VisibilityMode.FULL,
        parent_agent_pk: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.visibility_mode = visibility_mode
        self.parent_agent_pk = parent_agent_pk

        # Derived state
        self.state = AgentState.IDLE
        self.state_source = StateSource.OBSERVED
        self.is_compacting = False
        self.started_at_ms = int(time.time() * 1000)
        self.last_event_at_ms = self.started_at_ms
        self.stopped_at_ms: Optional[int] = None

        # Tool tracking
        self.last_tool_name: Optional[str] = None
        self.last_resource: Optional[str] = None
        self.last_summary: Optional[str] = None
        self.current_tool_use_id: Optional[str] = None
        self.tool_count = 0
        self.error_count = 0

    @property
    def agent_pk(self) -> str:
        """
        Canonical primary key for this agent.

        WHY: Scoped to session_id to prevent cross-session collision.
        Format: main:<session_id> or sub:<session_id>:<agent_id>
        """
        if self.agent_id:
            return f"sub:{self.session_id}:{self.agent_id}"
        return f"main:{self.session_id}"

    def apply(self, event_name: str, payload: dict[str, Any]) -> Optional[AgentState]:
        """
        Apply a hook event and return the new state, or None if no transition.

        This is the core reducer function. It:
        1. Looks up the transition in the table
        2. Updates tool tracking state
        3. Handles compaction as a flag (not a state)
        4. Returns the new state for persistence
        """
        now_ms = int(time.time() * 1000)
        self.last_event_at_ms = now_ms

        # ── Compaction: handled as a flag, not a state ──
        if event_name == "PreCompact":
            self.is_compacting = True
            return self.state  # State unchanged, flag set

        if event_name == "PostCompact":
            self.is_compacting = False
            # WHY: After compaction, we cannot be certain the agent is still
            # active — context was truncated. Downgrade confidence.
            self.state_source = StateSource.INFERRED
            return self.state

        if event_name == "SessionStart" and payload.get("source") == "compact":
            # Compaction-triggered session restart
            self.is_compacting = False
            self.state = AgentState.IDLE
            self.state_source = StateSource.INFERRED
            self._clear_tool_state()
            return self.state

        # ── Standard transition lookup ──
        key = (self.state, event_name)
        new_state = TRANSITIONS.get(key)

        if new_state is None:
            # WHY: Unknown transitions are logged but do not crash.
            # This allows the sidecar to handle new hook events from
            # future Claude Code versions gracefully.
            logger.debug(
                "No transition for (%s, %s) in agent %s",
                self.state.value, event_name, self.agent_pk,
            )
            return None

        old_state = self.state
        self.state = new_state
        self.state_source = StateSource.OBSERVED

        # ── Update tool tracking ──
        if event_name == "PreToolUse":
            tool_name = normalize_tool_name(payload.get("tool_name", "?"))
            tool_input = payload.get("tool_input", {})
            self.last_tool_name = tool_name
            self.last_resource = extract_resource(tool_name, tool_input)
            self.current_tool_use_id = payload.get("tool_use_id")
            self.tool_count += 1

        elif event_name in ("PostToolUse", "PostToolUseFailure"):
            if event_name == "PostToolUseFailure":
                self.error_count += 1
            self._clear_tool_state()

        elif event_name in ("Stop", "SessionEnd", "SubagentStop"):
            self._clear_tool_state()
            self.stopped_at_ms = now_ms
            # Capture final summary from SubagentStop
            if event_name == "SubagentStop":
                self.last_summary = payload.get("last_assistant_message")

        elif event_name == "StopFailure":
            self.error_count += 1

        return new_state

    def mark_orphaned(self) -> None:
        """
        Transition to ORPHANED state (called by stuck/orphan timer).

        WHY: This is an inferred transition, not driven by an observed event.
        """
        self.state = AgentState.ORPHANED
        self.state_source = StateSource.INFERRED
        self._clear_tool_state()

    def mark_stuck_warn(self) -> None:
        """Record that this agent has exceeded the stuck warning threshold."""
        # State doesn't change, but we track it for alert generation
        pass

    def _clear_tool_state(self) -> None:
        """Reset transient tool tracking fields."""
        self.last_tool_name = None
        self.last_resource = None
        self.current_tool_use_id = None

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize current state for persistence or WebSocket push."""
        return {
            "agent_pk": self.agent_pk,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "parent_agent_pk": self.parent_agent_pk,
            "agent_type": self.agent_type,
            "state": self.state.value,
            "state_source": self.state_source.value,
            "is_compacting": self.is_compacting,
            "started_at_ms": self.started_at_ms,
            "last_event_at_ms": self.last_event_at_ms,
            "stopped_at_ms": self.stopped_at_ms,
            "last_tool_name": self.last_tool_name,
            "last_resource": self.last_resource,
            "last_summary": self.last_summary,
            "visibility_mode": self.visibility_mode.value,
            "tool_count": self.tool_count,
            "error_count": self.error_count,
        }


class ReducerRegistry:
    """
    Registry of AgentStateMachine instances, keyed by agent_pk.

    ARCHITECTURE: The daemon maintains one ReducerRegistry. It routes
    incoming events to the correct machine based on session_id and
    agent_id extracted from the event envelope.
    """

    def __init__(self) -> None:
        self._machines: dict[str, AgentStateMachine] = {}

    def get_or_create_main(self, session_id: str) -> AgentStateMachine:
        """Get or create the main agent machine for a session."""
        pk = f"main:{session_id}"
        if pk not in self._machines:
            self._machines[pk] = AgentStateMachine(
                session_id=session_id,
                agent_type="main",
                visibility_mode=VisibilityMode.FULL,
            )
        return self._machines[pk]

    def get_or_create_subagent(
        self,
        session_id: str,
        agent_id: str,
        agent_type: str = "unknown",
        visibility_mode: VisibilityMode = VisibilityMode.LIFECYCLE_ONLY,
        parent_agent_pk: Optional[str] = None,
    ) -> AgentStateMachine:
        """Get or create a subagent machine."""
        pk = f"sub:{session_id}:{agent_id}"
        if pk not in self._machines:
            self._machines[pk] = AgentStateMachine(
                session_id=session_id,
                agent_id=agent_id,
                agent_type=agent_type,
                visibility_mode=visibility_mode,
                parent_agent_pk=parent_agent_pk,
            )
        return self._machines[pk]

    def get(self, agent_pk: str) -> Optional[AgentStateMachine]:
        """Look up a machine by pk."""
        return self._machines.get(agent_pk)

    def route_event(
        self,
        session_id: str,
        agent_id: Optional[str],
        event_name: str,
        payload: dict[str, Any],
    ) -> tuple[AgentStateMachine, Optional[AgentState]]:
        """
        Route an event to the correct machine and apply it.

        Returns (machine, new_state). new_state is None if no transition occurred.

        WHY: Centralizes the routing logic that determines which agent
        owns an event. For main-session hooks, agent_id is None and events
        route to the main machine. For subagent frontmatter hooks,
        agent_id is present.
        """
        # Handle subagent lifecycle events
        if event_name == "SubagentStart":
            sub_agent_id = payload.get("agent_id", agent_id or "unknown")
            sub_agent_type = payload.get("agent_type", "unknown")
            # Determine parent — the main agent or whichever agent spawned this
            parent_pk = f"main:{session_id}"
            if agent_id and agent_id != sub_agent_id:
                # Event came from a subagent context — nested spawn
                parent_pk = f"sub:{session_id}:{agent_id}"

            machine = self.get_or_create_subagent(
                session_id=session_id,
                agent_id=sub_agent_id,
                agent_type=sub_agent_type,
                parent_agent_pk=parent_pk,
            )
            new_state = machine.apply(event_name, payload)

            # Also notify the parent that it spawned a child
            if agent_id is None:
                parent = self.get_or_create_main(session_id)
                parent.apply(event_name, payload)

            return machine, new_state

        if event_name == "SubagentStop":
            sub_agent_id = payload.get("agent_id", agent_id or "unknown")
            pk = f"sub:{session_id}:{sub_agent_id}"
            machine = self._machines.get(pk)
            if machine is None:
                # SubagentStop without prior SubagentStart — create retroactively
                machine = self.get_or_create_subagent(
                    session_id=session_id,
                    agent_id=sub_agent_id,
                    agent_type=payload.get("agent_type", "unknown"),
                )
            new_state = machine.apply(event_name, payload)
            return machine, new_state

        # Standard event routing
        if agent_id:
            machine = self.get_or_create_subagent(
                session_id=session_id,
                agent_id=agent_id,
            )
        else:
            machine = self.get_or_create_main(session_id)

        new_state = machine.apply(event_name, payload)
        return machine, new_state

    def get_active_agents(self) -> list[AgentStateMachine]:
        """Return all agents not in terminal states."""
        return [
            m for m in self._machines.values()
            if m.state not in (AgentState.FINISHED, AgentState.ORPHANED)
        ]

    def get_all_agents(self) -> list[AgentStateMachine]:
        """Return all tracked agents."""
        return list(self._machines.values())

    def get_agents_for_session(self, session_id: str) -> list[AgentStateMachine]:
        """Return all agents for a given session."""
        return [
            m for m in self._machines.values()
            if m.session_id == session_id
        ]
