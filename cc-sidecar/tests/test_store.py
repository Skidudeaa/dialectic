"""
Tests for the SQLite store layer.

Covers schema creation, WAL mode, query functions, dedup,
concurrent reads, and retention cleanup.
"""
from __future__ import annotations

import time

import pytest
import pytest_asyncio

from cc_sidecar.store import queries
from cc_sidecar.store.database import (
    apply_schema,
    get_schema_version,
    run_incremental_vacuum,
)


class TestSchemaApplication:
    """Verify schema setup."""

    async def test_wal_mode_enabled(self, db):
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row[0] == "wal"

    async def test_schema_idempotent(self, db):
        """Applying schema twice should not error."""
        await apply_schema(db)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        )
        row = await cursor.fetchone()
        assert row[0] >= 9  # raw_events, sessions, agents, tool_calls, tasks, files, alerts, dead_events, schema_meta

    async def test_schema_version_set(self, db):
        version = await get_schema_version(db)
        assert version == 1

    async def test_all_tables_exist(self, db):
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        names = [r[0] for r in rows]
        for expected in [
            "agents", "alerts", "dead_events", "files",
            "raw_events", "schema_meta", "sessions", "tasks", "tool_calls",
        ]:
            assert expected in names, f"Missing table: {expected}"

    async def test_all_indexes_exist(self, db):
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        rows = await cursor.fetchall()
        names = [r[0] for r in rows]
        for expected in [
            "idx_re_session_time", "idx_re_session_event",
            "idx_agents_session",
            "idx_tc_agent", "idx_tc_session",
            "idx_tasks_session",
            "idx_files_session",
            "idx_alerts_active",
        ]:
            assert expected in names, f"Missing index: {expected}"


class TestRawEventQueries:
    """Test raw event insertion and dedup."""

    async def test_insert_returns_id(self, db):
        row_id = await queries.insert_raw_event(
            db,
            received_at_ms=1000,
            mono_seq=1,
            session_id="s1",
            agent_id=None,
            source_kind="hook",
            event_name="SessionStart",
            payload_json='{"test": true}',
            payload_size=14,
            dedup_hash="hash-001",
            emitter_version="test/1.0",
        )
        await db.commit()
        assert row_id is not None
        assert row_id > 0

    async def test_dedup_by_hash(self, db):
        """Duplicate dedup_hash should be silently ignored."""
        kwargs = dict(
            received_at_ms=1000,
            mono_seq=1,
            session_id="s1",
            agent_id=None,
            source_kind="hook",
            event_name="SessionStart",
            payload_json='{"test": true}',
            payload_size=14,
            dedup_hash="hash-dedup-test",
            emitter_version="test/1.0",
        )
        first = await queries.insert_raw_event(db, **kwargs)
        await db.commit()
        assert first is not None

        # Same hash, different received_at
        kwargs["received_at_ms"] = 2000
        kwargs["mono_seq"] = 2
        second = await queries.insert_raw_event(db, **kwargs)
        await db.commit()
        assert second is None  # Deduplicated

    async def test_get_recent_events(self, db):
        for i in range(10):
            await queries.insert_raw_event(
                db,
                received_at_ms=1000 + i,
                mono_seq=i,
                session_id="s1",
                agent_id=None,
                source_kind="hook",
                event_name=f"Event{i}",
                payload_json="{}",
                payload_size=2,
                dedup_hash=f"hash-recent-{i}",
                emitter_version="test/1.0",
            )
        await db.commit()

        recent = await queries.get_recent_events(db, "s1", limit=5)
        assert len(recent) == 5
        # Should be newest first
        assert recent[0]["event_name"] == "Event9"
        assert recent[4]["event_name"] == "Event5"


class TestSessionQueries:
    """Test session CRUD."""

    async def test_upsert_creates(self, db):
        await queries.upsert_session(
            db, session_id="s1", source="startup", model="opus"
        )
        await db.commit()

        session = await queries.get_session(db, "s1")
        assert session is not None
        assert session["source"] == "startup"
        assert session["model"] == "opus"

    async def test_upsert_preserves_existing(self, db):
        await queries.upsert_session(
            db, session_id="s1", source="startup", model="opus", cwd="/a"
        )
        await db.commit()

        # Second upsert with different model, no cwd
        await queries.upsert_session(
            db, session_id="s1", model="sonnet"
        )
        await db.commit()

        session = await queries.get_session(db, "s1")
        assert session["model"] == "sonnet"
        assert session["cwd"] == "/a"  # Preserved from first upsert

    async def test_end_session(self, db):
        await queries.upsert_session(db, session_id="s1")
        await db.commit()

        await queries.end_session(db, session_id="s1", end_reason="user_quit")
        await db.commit()

        session = await queries.get_session(db, "s1")
        assert session["ended_at_ms"] is not None
        assert session["end_reason"] == "user_quit"

    async def test_increment_compaction(self, db):
        await queries.upsert_session(db, session_id="s1")
        await db.commit()

        await queries.increment_compaction(db, "s1")
        await db.commit()
        await queries.increment_compaction(db, "s1")
        await db.commit()

        session = await queries.get_session(db, "s1")
        assert session["compaction_count"] == 2
        assert session["last_compacted_at_ms"] is not None

    async def test_statusline_update(self, db):
        await queries.upsert_session(db, session_id="s1")
        await db.commit()

        await queries.update_session_statusline(
            db,
            session_id="s1",
            context_used_pct=42.5,
            total_cost_usd=1.23,
            model="claude-opus-4-6",
        )
        await db.commit()

        session = await queries.get_session(db, "s1")
        assert session["context_used_pct"] == 42.5
        assert session["total_cost_usd"] == 1.23
        assert session["model"] == "claude-opus-4-6"

    async def test_get_active_sessions(self, db):
        await queries.upsert_session(db, session_id="active1")
        await queries.upsert_session(db, session_id="active2")
        await queries.upsert_session(db, session_id="ended1")
        await queries.end_session(db, session_id="ended1")
        await db.commit()

        active = await queries.get_active_sessions(db)
        ids = [s["session_id"] for s in active]
        assert "active1" in ids
        assert "active2" in ids
        assert "ended1" not in ids


class TestToolCallQueries:
    """Test tool call tracking."""

    async def test_insert_and_complete(self, db):
        await queries.insert_tool_call(
            db,
            tool_use_id="tc1",
            session_id="s1",
            agent_pk="main:s1",
            tool_name="Read",
            input_summary="src/main.py:1-50",
        )
        await db.commit()

        await queries.complete_tool_call(db, tool_use_id="tc1", status="success")
        await db.commit()

        cursor = await db.execute(
            "SELECT status, ended_at_ms FROM tool_calls WHERE tool_use_id='tc1'"
        )
        row = await cursor.fetchone()
        assert row["status"] == "success"
        assert row["ended_at_ms"] is not None

    async def test_complete_idempotent(self, db):
        """Completing an already-completed tool call should not change it."""
        await queries.insert_tool_call(
            db,
            tool_use_id="tc2",
            session_id="s1",
            agent_pk="main:s1",
            tool_name="Read",
        )
        await db.commit()

        await queries.complete_tool_call(db, tool_use_id="tc2", status="success")
        await db.commit()

        # Try to complete again with failure — should NOT change
        await queries.complete_tool_call(
            db, tool_use_id="tc2", status="failure", error="late error"
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT status, error FROM tool_calls WHERE tool_use_id='tc2'"
        )
        row = await cursor.fetchone()
        assert row["status"] == "success"
        assert row["error"] is None

    async def test_insert_idempotent(self, db):
        """INSERT OR IGNORE should not fail on replay."""
        await queries.insert_tool_call(
            db,
            tool_use_id="tc3",
            session_id="s1",
            agent_pk="main:s1",
            tool_name="Read",
            input_summary="first",
        )
        await db.commit()

        # Insert again (replay) — should be silently ignored
        await queries.insert_tool_call(
            db,
            tool_use_id="tc3",
            session_id="s1",
            agent_pk="main:s1",
            tool_name="Read",
            input_summary="second",
        )
        await db.commit()

        cursor = await db.execute(
            "SELECT input_summary FROM tool_calls WHERE tool_use_id='tc3'"
        )
        row = await cursor.fetchone()
        assert row["input_summary"] == "first"  # Original preserved


class TestAlertQueries:

    async def test_insert_and_resolve(self, db):
        alert_id = await queries.insert_alert(
            db, session_id="s1", severity="warn", kind="stuck", message="test"
        )
        await db.commit()
        assert alert_id > 0

        active = await queries.get_active_alerts(db, "s1")
        assert len(active) == 1

        await queries.resolve_alert(db, alert_id)
        await db.commit()

        active = await queries.get_active_alerts(db, "s1")
        assert len(active) == 0


class TestRetention:

    async def test_delete_old_events(self, db):
        now_ms = int(time.time() * 1000)
        old_ms = now_ms - (8 * 86400 * 1000)  # 8 days ago

        await queries.insert_raw_event(
            db,
            received_at_ms=old_ms,
            mono_seq=1,
            session_id="s1",
            agent_id=None,
            source_kind="hook",
            event_name="Old",
            payload_json="{}",
            payload_size=2,
            dedup_hash="hash-old",
            emitter_version="test",
        )
        await queries.insert_raw_event(
            db,
            received_at_ms=now_ms,
            mono_seq=2,
            session_id="s1",
            agent_id=None,
            source_kind="hook",
            event_name="New",
            payload_json="{}",
            payload_size=2,
            dedup_hash="hash-new",
            emitter_version="test",
        )
        await db.commit()

        cutoff = now_ms - (7 * 86400 * 1000)
        deleted = await queries.delete_old_events(db, cutoff)
        assert deleted == 1

        recent = await queries.get_recent_events(db, "s1")
        assert len(recent) == 1
        assert recent[0]["event_name"] == "New"

    async def test_incremental_vacuum(self, db):
        """Vacuum should not crash on empty or populated DB."""
        await run_incremental_vacuum(db)


class TestDeadEvents:

    async def test_insert_dead_event(self, db):
        await queries.insert_dead_event(
            db, raw_payload="not json {{{", parse_error="invalid JSON"
        )
        await db.commit()

        cursor = await db.execute("SELECT COUNT(*) FROM dead_events")
        row = await cursor.fetchone()
        assert row[0] == 1
