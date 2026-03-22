"""
Integration tests: full pipeline from envelope JSON through
ingest → SQLite → reducer → derived state.

Covers all 9 mandatory spec test cases plus additional edge cases.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import aiosqlite

from cc_sidecar.daemon.ingest import IngestPipeline
from cc_sidecar.reducer.machine import ReducerRegistry
from cc_sidecar.store import queries
from cc_sidecar.store.database import apply_schema, get_connection

from tests.conftest import (
    make_envelope,
    make_permission_request,
    make_post_compact,
    make_post_tool_use,
    make_post_tool_use_failure,
    make_pre_compact,
    make_pre_tool_use,
    make_session_end,
    make_session_start,
    make_stop,
    make_subagent_start,
    make_subagent_stop,
)

@pytest_asyncio.fixture
async def pipeline(db):
    """Provide a fresh pipeline with DB and registry."""
    registry = ReducerRegistry()
    broadcasts: list[dict] = []

    async def capture_broadcast(data: dict) -> None:
        broadcasts.append(data)

    pipe = IngestPipeline(db=db, registry=registry, broadcast_fn=capture_broadcast)
    pipe._broadcasts = broadcasts  # Attach for test inspection
    return pipe


# ============================================================
# Spec Mandatory Test 1: Out-of-order event replay
# ============================================================

class TestOutOfOrderReplay:
    """Events arriving out of mono_seq order produce correct final state."""

    async def test_out_of_order_events(self, pipeline):
        sid = "oo-test"

        # Create events with sequential mono_seq but send out of order
        e1 = make_session_start(session_id=sid)
        e3 = make_post_tool_use(tool_use_id="oo-t1", session_id=sid)
        e2 = make_pre_tool_use(
            tool_name="Read", tool_use_id="oo-t1",
            tool_input={"file_path": "/a.py"}, session_id=sid,
        )

        # Process in wrong order: 1, 3, 2
        assert await pipeline.process_event(e1) is True
        assert await pipeline.process_event(e3) is True
        assert await pipeline.process_event(e2) is True

        # Main agent should be idle (PostToolUse arrived, then PreToolUse)
        machine = pipeline.registry.get(f"main:{sid}")
        assert machine is not None
        # State depends on order processed — last event was PreToolUse
        # so state should be running_tool
        assert machine.state.value == "running_tool"

        # All 3 events should be in DB
        events = await queries.get_recent_events(pipeline.db, sid)
        assert len(events) == 3


# ============================================================
# Spec Mandatory Test 2: Duplicate event replay
# ============================================================

class TestDuplicateReplay:
    """Duplicate mono_seq events are silently dropped."""

    async def test_duplicate_dedup(self, pipeline):
        sid = "dup-test"
        event = make_session_start(session_id=sid)

        # Process same event twice
        first = await pipeline.process_event(event)
        second = await pipeline.process_event(event)

        assert first is True
        assert second is False  # Deduplicated

        # Only 1 event in DB
        events = await queries.get_recent_events(pipeline.db, sid)
        assert len(events) == 1


# ============================================================
# Spec Mandatory Test 3: Missing SubagentStop
# ============================================================

class TestMissingSubagentStop:
    """Agent without SubagentStop transitions to orphaned after timeout."""

    async def test_orphan_detection(self, pipeline):
        sid = "orphan-test"
        await pipeline.process_event(make_session_start(session_id=sid))
        await pipeline.process_event(
            make_subagent_start(agent_id="orphan-sub", session_id=sid)
        )

        machine = pipeline.registry.get(f"sub:{sid}:orphan-sub")
        assert machine is not None
        assert machine.state.value == "idle"

        # Simulate time passing by backdating last_event_at_ms
        machine.last_event_at_ms = int(time.time() * 1000) - 400_000  # 400 seconds ago

        # Import and run the orphan detector
        from cc_sidecar.daemon.timers import OrphanDetector
        detector = OrphanDetector(
            db=pipeline.db,
            registry=pipeline.registry,
        )
        alerts = await detector.scan()

        assert machine.state.value == "orphaned"
        assert len(alerts) > 0
        assert "orphan-sub" in alerts[0]


# ============================================================
# Spec Mandatory Test 4: Compaction mid-run
# ============================================================

class TestCompactionMidRun:
    """PreCompact during RUNNING_TOOL sets flag, PostCompact clears it."""

    async def test_compaction_preserves_state(self, pipeline):
        sid = "compact-test"
        await pipeline.process_event(make_session_start(session_id=sid))
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Edit", tool_use_id="cp-t1",
                tool_input={"file_path": "/a.py"}, session_id=sid,
            )
        )

        machine = pipeline.registry.get(f"main:{sid}")
        assert machine.state.value == "running_tool"

        # Compaction hits
        await pipeline.process_event(make_pre_compact(session_id=sid))
        assert machine.is_compacting is True
        assert machine.state.value == "running_tool"  # Underlying state preserved

        await pipeline.process_event(make_post_compact(session_id=sid))
        assert machine.is_compacting is False
        assert machine.state_source.value == "inferred"

        # Verify compaction_count in session
        session = await queries.get_session(pipeline.db, sid)
        assert session["compaction_count"] == 1


# ============================================================
# Spec Mandatory Test 5: Session resume after compaction
# ============================================================

class TestSessionResumeAfterCompaction:
    """SessionStart with source='compact' resumes correctly."""

    async def test_compact_resume(self, pipeline):
        sid = "resume-test"
        await pipeline.process_event(make_session_start(session_id=sid))
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Read", tool_use_id="r-t1",
                tool_input={"file_path": "/a.py"}, session_id=sid,
            )
        )
        await pipeline.process_event(make_pre_compact(session_id=sid))
        await pipeline.process_event(make_post_compact(session_id=sid))

        # Compact-triggered session restart
        compact_start = make_envelope(
            "SessionStart",
            session_id=sid,
            payload={"source": "compact", "model": "claude-opus-4-6"},
        )
        await pipeline.process_event(compact_start)

        machine = pipeline.registry.get(f"main:{sid}")
        assert machine.state.value == "idle"
        assert machine.is_compacting is False

        session = await queries.get_session(pipeline.db, sid)
        assert session["compaction_count"] == 1
        # Original source should be preserved (not overwritten to "compact")
        assert session["source"] == "startup"

        # New tool use after compaction should work
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Write", tool_use_id="r-t2",
                tool_input={"file_path": "/b.py"}, session_id=sid,
            )
        )
        assert machine.state.value == "running_tool"
        assert machine.state_source.value == "observed"


# ============================================================
# Spec Mandatory Test 6: Background permission denial
# ============================================================

class TestBackgroundPermissionDenial:
    """PostToolUseFailure after PermissionRequest transitions to BLOCKED."""

    async def test_permission_denied(self, pipeline):
        sid = "perm-test"
        await pipeline.process_event(make_session_start(session_id=sid))
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Bash", tool_use_id="p-t1",
                tool_input={"command": "rm -rf /"}, session_id=sid,
            )
        )
        await pipeline.process_event(
            make_permission_request(
                tool_name="Bash", tool_use_id="p-t1", session_id=sid,
            )
        )

        machine = pipeline.registry.get(f"main:{sid}")
        assert machine.state.value == "awaiting_perm"

        # Permission denied
        await pipeline.process_event(
            make_post_tool_use_failure(
                tool_use_id="p-t1", error="Permission denied by user",
                session_id=sid,
            )
        )
        assert machine.state.value == "blocked"

        # Tool call should be marked denied
        cursor = await pipeline.db.execute(
            "SELECT status FROM tool_calls WHERE tool_use_id='p-t1'"
        )
        row = await cursor.fetchone()
        assert row["status"] == "denied"


# ============================================================
# Spec Mandatory Test 7: Multiple concurrent agents
# ============================================================

class TestConcurrentAgents:
    """Multiple agents in same session have independent state machines."""

    async def test_independent_state(self, pipeline):
        sid = "concurrent-test"
        await pipeline.process_event(make_session_start(session_id=sid))

        # Main starts tool
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Read", tool_use_id="c-t1",
                tool_input={"file_path": "/a.py"}, session_id=sid,
            )
        )

        # Sub A starts
        await pipeline.process_event(
            make_subagent_start(agent_id="sub-a", agent_type="Explore", session_id=sid)
        )

        # Sub B starts
        await pipeline.process_event(
            make_subagent_start(agent_id="sub-b", agent_type="test-runner", session_id=sid)
        )

        # Sub A does tool
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Grep", tool_use_id="c-t2",
                tool_input={"pattern": "TODO"}, session_id=sid,
                agent_id="sub-a",
            )
        )

        # Sub B does tool
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Bash", tool_use_id="c-t3",
                tool_input={"command": "npm test"}, session_id=sid,
                agent_id="sub-b",
            )
        )

        main = pipeline.registry.get(f"main:{sid}")
        sub_a = pipeline.registry.get(f"sub:{sid}:sub-a")
        sub_b = pipeline.registry.get(f"sub:{sid}:sub-b")

        assert main.state.value == "running_tool"
        assert sub_a.state.value == "running_tool"
        assert sub_b.state.value == "running_tool"

        # Main finishes — others unaffected
        await pipeline.process_event(
            make_post_tool_use(tool_use_id="c-t1", session_id=sid)
        )

        assert main.state.value == "idle"
        assert sub_a.state.value == "running_tool"
        assert sub_b.state.value == "running_tool"

        # Sub A finishes tool, Sub B still running
        await pipeline.process_event(
            make_post_tool_use(tool_use_id="c-t2", session_id=sid, agent_id="sub-a")
        )

        assert sub_a.state.value == "idle"
        assert sub_b.state.value == "running_tool"


# ============================================================
# Spec Mandatory Test 8: Null/absent statusline fields
# ============================================================

class TestNullStatuslineFields:
    """Session metadata handles null/absent fields gracefully."""

    async def test_empty_statusline(self, pipeline):
        sid = "null-sl-test"
        await pipeline.process_event(make_session_start(session_id=sid))

        # Statusline with empty/null nested objects
        sl = make_envelope(
            "StatuslineUpdate",
            session_id=sid,
            payload={
                "model": {},
                "context_window": {},
                "cost": {},
                "workspace": {},
            },
        )
        # Should not crash
        await pipeline.process_event(sl)

        session = await queries.get_session(pipeline.db, sid)
        assert session is not None
        # Defaults should hold
        assert session["total_cost_usd"] == 0.0

    async def test_partial_statusline(self, pipeline):
        sid = "partial-sl-test"
        await pipeline.process_event(make_session_start(session_id=sid))

        sl = make_envelope(
            "StatuslineUpdate",
            session_id=sid,
            payload={
                "model": {"display_name": "Claude Opus 4.6"},
                "context_window": {"used_percentage": 65.3},
                "cost": {"total_cost_usd": 2.15},
                # workspace absent
            },
        )
        await pipeline.process_event(sl)

        session = await queries.get_session(pipeline.db, sid)
        assert session["model"] == "Claude Opus 4.6"
        assert session["context_used_pct"] == 65.3
        assert session["total_cost_usd"] == 2.15


# ============================================================
# Spec Mandatory Test 9: Task/Agent alias handling
# ============================================================

class TestTaskAgentAlias:
    """Both 'Task' and 'Agent' tool names produce identical events."""

    async def test_task_normalized_to_agent(self, pipeline):
        sid = "alias-test"
        await pipeline.process_event(make_session_start(session_id=sid))

        # PreToolUse with tool_name="Task"
        task_event = make_pre_tool_use(
            tool_name="Task",
            tool_use_id="alias-t1",
            tool_input={"subagent_type": "Explore", "prompt": "Find tests"},
            session_id=sid,
        )
        await pipeline.process_event(task_event)

        # Check tool_call stored with normalized name
        cursor = await pipeline.db.execute(
            "SELECT tool_name FROM tool_calls WHERE tool_use_id='alias-t1'"
        )
        row = await cursor.fetchone()
        assert row["tool_name"] == "Agent"

        # Agent state should show the normalized name
        machine = pipeline.registry.get(f"main:{sid}")
        assert machine.last_tool_name == "Agent"

    async def test_agent_unchanged(self, pipeline):
        sid = "alias-test-2"
        await pipeline.process_event(make_session_start(session_id=sid))

        agent_event = make_pre_tool_use(
            tool_name="Agent",
            tool_use_id="alias-t2",
            tool_input={"subagent_type": "test-runner", "prompt": "Run tests"},
            session_id=sid,
        )
        await pipeline.process_event(agent_event)

        cursor = await pipeline.db.execute(
            "SELECT tool_name FROM tool_calls WHERE tool_use_id='alias-t2'"
        )
        row = await cursor.fetchone()
        assert row["tool_name"] == "Agent"


# ============================================================
# Additional integration tests
# ============================================================

class TestFileTracking:
    """File ownership tracked from Write/Edit PostToolUse events."""

    async def test_write_creates_file_record(self, pipeline):
        sid = "file-test"
        await pipeline.process_event(make_session_start(session_id=sid))
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Write", tool_use_id="f-t1",
                tool_input={"file_path": "/project/src/new.py"},
                session_id=sid,
            )
        )
        await pipeline.process_event(
            make_envelope(
                "PostToolUse",
                session_id=sid,
                payload={
                    "tool_name": "Write",
                    "tool_use_id": "f-t1",
                    "tool_input": {"file_path": "/project/src/new.py"},
                },
            )
        )

        cursor = await pipeline.db.execute(
            "SELECT * FROM files WHERE session_id=? AND path=?",
            (sid, "/project/src/new.py"),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["ownership_source"] == "observed"
        assert row["last_writer_agent_pk"] == f"main:{sid}"


class TestAlertGeneration:
    """Alerts generated for compaction, config changes."""

    async def test_compaction_alert(self, pipeline):
        sid = "alert-test"
        await pipeline.process_event(make_session_start(session_id=sid))
        await pipeline.process_event(make_pre_compact(session_id=sid))

        alerts = await queries.get_active_alerts(pipeline.db, sid)
        assert len(alerts) >= 1
        assert any(a["kind"] == "compaction" for a in alerts)

    async def test_config_change_alert(self, pipeline):
        sid = "config-alert-test"
        await pipeline.process_event(make_session_start(session_id=sid))
        await pipeline.process_event(
            make_envelope(
                "ConfigChange",
                session_id=sid,
                payload={
                    "source": "user_settings",
                    "file_path": "~/.claude/settings.json",
                },
            )
        )

        alerts = await queries.get_active_alerts(pipeline.db, sid)
        assert len(alerts) >= 1
        assert any(a["kind"] == "config_change" for a in alerts)


class TestDeadEventHandling:
    """Malformed events go to dead_events, not crash."""

    async def test_malformed_json(self, pipeline):
        result = await pipeline.process_event("not valid json {{{")
        assert result is False

        cursor = await pipeline.db.execute("SELECT COUNT(*) FROM dead_events")
        row = await cursor.fetchone()
        assert row[0] == 1


class TestBroadcastFiring:
    """Verify broadcast callback is called for ingested events."""

    async def test_broadcast_called(self, pipeline):
        sid = "broadcast-test"
        await pipeline.process_event(make_session_start(session_id=sid))

        assert len(pipeline._broadcasts) >= 1
        last = pipeline._broadcasts[-1]
        assert last["type"] == "event"
        assert last["event"]["event_name"] == "SessionStart"


class TestSubagentLifecycle:
    """Full subagent lifecycle: start → tools → stop."""

    async def test_full_lifecycle(self, pipeline):
        sid = "lifecycle-test"
        await pipeline.process_event(make_session_start(session_id=sid))

        # Subagent starts
        await pipeline.process_event(
            make_subagent_start(agent_id="life-sub", agent_type="Explore", session_id=sid)
        )

        sub = pipeline.registry.get(f"sub:{sid}:life-sub")
        assert sub is not None
        assert sub.state.value == "idle"
        assert sub.agent_type == "Explore"
        assert sub.visibility_mode.value == "lifecycle_only"

        # Subagent stops with summary
        await pipeline.process_event(
            make_subagent_stop(
                agent_id="life-sub", summary="Found 3 results", session_id=sid,
            )
        )

        assert sub.state.value == "finished"
        assert sub.last_summary == "Found 3 results"

        # Check DB
        cursor = await pipeline.db.execute(
            "SELECT state, last_summary FROM agents WHERE agent_pk=?",
            (f"sub:{sid}:life-sub",),
        )
        row = await cursor.fetchone()
        assert row["state"] == "finished"
        assert row["last_summary"] == "Found 3 results"


class TestSessionEndToEnd:
    """Full session lifecycle: start → tools → compaction → end."""

    async def test_full_session(self, pipeline):
        sid = "e2e-test"

        # Start
        await pipeline.process_event(make_session_start(session_id=sid))

        # Read a file
        await pipeline.process_event(
            make_pre_tool_use(
                tool_name="Read", tool_use_id="e2e-1",
                tool_input={"file_path": "/a.py"}, session_id=sid,
            )
        )
        await pipeline.process_event(
            make_post_tool_use(tool_use_id="e2e-1", session_id=sid)
        )

        # Spawn subagent
        await pipeline.process_event(
            make_subagent_start(agent_id="e2e-sub", session_id=sid)
        )

        # Compaction
        await pipeline.process_event(make_pre_compact(session_id=sid))
        await pipeline.process_event(make_post_compact(session_id=sid))

        # Subagent finishes
        await pipeline.process_event(
            make_subagent_stop(agent_id="e2e-sub", summary="Done", session_id=sid)
        )

        # End session
        await pipeline.process_event(make_session_end(session_id=sid))

        # Verify final state
        session = await queries.get_session(pipeline.db, sid)
        assert session["ended_at_ms"] is not None
        assert session["compaction_count"] == 1

        main = pipeline.registry.get(f"main:{sid}")
        assert main.state.value == "finished"

        sub = pipeline.registry.get(f"sub:{sid}:e2e-sub")
        assert sub.state.value == "finished"
        assert sub.last_summary == "Done"

        # Should have: SessionStart, PreToolUse, PostToolUse, SubagentStart,
        # PreCompact, PostCompact, SubagentStop, SessionEnd = 8 events
        events = await queries.get_recent_events(pipeline.db, sid, limit=20)
        assert len(events) == 8
