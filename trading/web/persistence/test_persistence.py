"""
Tests for SQLite persistence layer — migration runner + repository.

WHY: The persistence layer replaces web/state.py. Every operation in the
old file-based system needs a SQLite equivalent with matching semantics.
These tests verify: schema creation, CRUD correctness, cursor pagination,
PK dedup, cascade deletes, atomic transactions, and streak counting.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest

from web.persistence.repository import PredictionResolutionConflict, Repository


@pytest.fixture
def repo():
    """Fresh in-memory SQLite database per test."""
    r = Repository(":memory:")
    r.initialize()
    return r


# ═══════════════════════════════════════════════════════════════════════
# MIGRATION RUNNER
# ═══════════════════════════════════════════════════════════════════════

class TestMigrations:
    def test_creates_all_tables(self, repo):
        """Initial migration creates all expected tables."""
        from web.persistence.connection import get_connection
        conn = get_connection(":memory:")
        from web.persistence.migrations import run_migrations
        count = run_migrations(conn)
        # 001 (initial schema) + 002 (audit_log + confirm_tokens) + 003
        # (message kind+meta) + 004 (drop outbox) + 005 (maintenance_state)
        # + 006 (Dialectic prediction idempotency keys).
        # Bump this when a new numbered migration lands in
        # web/persistence/sql/.
        assert count == 6
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        expected = {
            "schema_migrations", "rooms", "messages", "pins",
            "journal_entries", "predictions", "tv_events",
            "thesis_snapshots", "alert_events", "manual_overrides",
            "close_observations", "fetch_runs",
            "audit_log", "confirm_tokens", "maintenance_state",
        }
        assert expected.issubset(tables)
        conn.close()

    def test_idempotent(self, repo):
        """Running migrations twice applies nothing the second time."""
        count = repo.initialize()
        assert count == 0  # already applied in fixture


# ═══════════════════════════════════════════════════════════════════════
# ROOMS
# ═══════════════════════════════════════════════════════════════════════

class TestRooms:
    def test_create_and_list(self, repo):
        room = repo.create_room("General", topic="Trading discussion")
        rooms = repo.list_rooms()
        assert len(rooms) == 1
        assert rooms[0]["name"] == "General"
        assert rooms[0]["id"] == room["id"]

    def test_get_room(self, repo):
        room = repo.create_room("General")
        found = repo.get_room(room["id"])
        assert found is not None
        assert found["name"] == "General"

    def test_get_room_missing(self, repo):
        assert repo.get_room("nonexistent") is None

    def test_update_room(self, repo):
        room = repo.create_room("Old Name")
        updated = repo.update_room(room["id"], {"name": "New Name"})
        assert updated["name"] == "New Name"

    def test_update_room_missing(self, repo):
        assert repo.update_room("nonexistent", {"name": "X"}) is None

    def test_delete_room_cascades(self, repo):
        room = repo.create_room("Temp")
        repo.save_message(room["id"], "amo", "hello")
        repo.add_pin(room["id"], {"id": "pin-1", "user": "amo",
                                   "content": "pinned", "ts": "2026-01-01"})
        repo.delete_room(room["id"])
        assert repo.get_room(room["id"]) is None
        assert repo.list_messages(room["id"]) == []
        assert repo.list_pins(room["id"]) == []

    def test_linked_book_id(self, repo):
        room = repo.create_room("Iran Room", linked_book_id="iran-hormuz-graph")
        assert room["linked_book_id"] == "iran-hormuz-graph"

    def test_participants_json(self, repo):
        room = repo.create_room("Team", participants=["amo", "dan"])
        found = repo.get_room(room["id"])
        assert found["participants"] == ["amo", "dan"]


# ═══════════════════════════════════════════════════════════════════════
# MESSAGES
# ═══════════════════════════════════════════════════════════════════════

class TestMessages:
    def test_save_and_list(self, repo):
        room = repo.create_room("Chat")
        repo.save_message(room["id"], "amo", "hello")
        repo.save_message(room["id"], "dan", "hi")
        msgs = repo.list_messages(room["id"])
        assert len(msgs) == 2
        assert msgs[0]["content"] == "hello"  # oldest first
        assert msgs[1]["content"] == "hi"

    def test_cursor_pagination(self, repo):
        room = repo.create_room("Chat")
        for i in range(5):
            repo.save_message(room["id"], "amo", f"msg-{i}")
        all_msgs = repo.list_messages(room["id"], limit=10)
        assert len(all_msgs) == 5
        # Get messages before the 4th message's timestamp
        before_ts = all_msgs[3]["ts"]
        older = repo.list_messages(room["id"], limit=10, before=before_ts)
        assert len(older) == 3  # msg-0, msg-1, msg-2

    def test_limit(self, repo):
        room = repo.create_room("Chat")
        for i in range(10):
            repo.save_message(room["id"], "amo", f"msg-{i}")
        msgs = repo.list_messages(room["id"], limit=3)
        assert len(msgs) == 3
        # Should be the 3 most recent (oldest first within the window)
        assert msgs[-1]["content"] == "msg-9"

    def test_empty_room(self, repo):
        room = repo.create_room("Empty")
        assert repo.list_messages(room["id"]) == []

    def test_llm_message_with_model(self, repo):
        room = repo.create_room("LLM")
        msg = repo.save_message(room["id"], "system", "response",
                                msg_type="llm", model="claude-sonnet-4.6")
        assert msg["model"] == "claude-sonnet-4.6"


# ═══════════════════════════════════════════════════════════════════════
# PINS
# ═══════════════════════════════════════════════════════════════════════

class TestPins:
    def test_add_and_list(self, repo):
        room = repo.create_room("Chat")
        msg = repo.save_message(room["id"], "amo", "important")
        pins = repo.add_pin(room["id"], msg)
        assert len(pins) == 1
        assert pins[0]["content"] == "important"

    def test_dedup(self, repo):
        room = repo.create_room("Chat")
        msg = repo.save_message(room["id"], "amo", "important")
        repo.add_pin(room["id"], msg)
        pins = repo.add_pin(room["id"], msg)  # duplicate
        assert len(pins) == 1  # not 2

    def test_remove(self, repo):
        room = repo.create_room("Chat")
        msg = repo.save_message(room["id"], "amo", "temp pin")
        repo.add_pin(room["id"], msg)
        pins = repo.remove_pin(room["id"], msg["id"])
        assert len(pins) == 0


# ═══════════════════════════════════════════════════════════════════════
# JOURNAL
# ═══════════════════════════════════════════════════════════════════════

class TestJournal:
    def test_create_and_list(self, repo):
        entry = repo.save_journal_entry("amo", {
            "thesis": "Iran/Hormuz",
            "instrument": "XOP",
            "direction": "long",
            "entry_price": 45.0,
            "tags": ["oil", "geopolitical"],
        })
        entries = repo.list_journal_entries()
        assert len(entries) == 1
        assert entries[0]["instrument"] == "XOP"
        assert entries[0]["tags"] == ["oil", "geopolitical"]

    def test_update_entry(self, repo):
        entry = repo.save_journal_entry("amo", {
            "thesis": "Test",
            "instrument": "SPY",
            "direction": "short",
            "entry_price": 500.0,
        })
        updated = repo.update_journal_entry(entry["id"], {
            "exit_price": 480.0,
            "pnl": 20.0,
            "notes": "Good trade",
        })
        assert updated["exit_price"] == 480.0
        assert updated["pnl"] == 20.0

    def test_update_missing(self, repo):
        assert repo.update_journal_entry("nonexistent", {"pnl": 0}) is None


# ═══════════════════════════════════════════════════════════════════════
# PREDICTIONS
# ═══════════════════════════════════════════════════════════════════════

class TestPredictions:
    def test_create_and_list(self, repo):
        pred = repo.save_prediction("amo", {
            "statement": "Brent above $100 by May",
            "confidence": 0.7,
            "deadline": "2026-05-01",
        })
        preds = repo.list_predictions()
        assert len(preds) == 1
        assert preds[0]["confidence"] == 0.7
        assert preds[0]["resolution"] is None

    def test_resolve(self, repo):
        pred = repo.save_prediction("amo", {
            "statement": "Test",
            "confidence": 0.5,
            "deadline": "2026-06-01",
        })
        resolved = repo.resolve_prediction(pred["id"], "correct")
        assert resolved["resolution"] == "correct"
        assert resolved["resolved_at"] is not None

    def test_resolve_missing(self, repo):
        assert repo.resolve_prediction("nonexistent", "correct") is None

    def test_same_prediction_source_returns_one_public_row(self, repo):
        payload = {
            "statement": "Brent over 90",
            "confidence": 0.7,
            "deadline": "2026-09-30",
            "source_key": "dialectic:m1:proposal",
        }
        first, first_created = repo.save_prediction_once("amo", payload)
        second, second_created = repo.save_prediction_once("amo", payload)

        assert first_created is True
        assert second_created is False
        assert second["id"] == first["id"]
        assert len(repo.list_predictions()) == 1
        assert "source_key" not in first
        assert "resolution_source_key" not in first

    def test_same_resolution_source_is_a_no_op(self, repo):
        prediction, _ = repo.save_prediction_once("amo", {
            "statement": "Brent over 90",
            "confidence": 0.7,
            "deadline": "2026-09-30",
        })
        first, first_changed = repo.resolve_prediction_once(
            prediction["id"],
            "correct",
            "dialectic:resolve:p1",
        )
        second, second_changed = repo.resolve_prediction_once(
            prediction["id"],
            "correct",
            "dialectic:resolve:p1",
        )

        assert first_changed is True
        assert second_changed is False
        assert second["resolved_at"] == first["resolved_at"]
        assert "source_key" not in second
        assert "resolution_source_key" not in second

    def test_conflicting_second_resolution_is_rejected(self, repo):
        prediction, _ = repo.save_prediction_once("amo", {
            "statement": "Brent over 90",
            "confidence": 0.7,
            "deadline": "2026-09-30",
        })
        repo.resolve_prediction_once(
            prediction["id"],
            "correct",
            "dialectic:resolve:p1",
        )
        with pytest.raises(PredictionResolutionConflict):
            repo.resolve_prediction_once(
                prediction["id"],
                "incorrect",
                "dialectic:resolve:p2",
            )


# ═══════════════════════════════════════════════════════════════════════
# TV EVENTS
# ═══════════════════════════════════════════════════════════════════════

class TestTVEvents:
    def test_save_and_list(self, repo):
        repo.save_tv_event(result="ok", book_id="iran-hormuz-graph",
                           node_id="brent", op="setCurrent", new_value=85.0)
        events = repo.list_tv_events()
        assert len(events) == 1
        assert events[0]["newValue"] == 85.0
        assert events[0]["bookId"] == "iran-hormuz-graph"

    def test_filter_by_book(self, repo):
        repo.save_tv_event(result="ok", book_id="iran-hormuz-graph")
        repo.save_tv_event(result="ok", book_id="trump-tariffs-graph")
        events = repo.list_tv_events(book_id="iran-hormuz-graph")
        assert len(events) == 1

    def test_newest_first(self, repo):
        repo.save_tv_event(result="ok", book_id="b", detail="first")
        repo.save_tv_event(result="ok", book_id="b", detail="second")
        events = repo.list_tv_events()
        assert events[0]["detail"] == "second"  # newest first


# ═══════════════════════════════════════════════════════════════════════
# SNAPSHOTS (v2)
# ═══════════════════════════════════════════════════════════════════════

class TestSnapshots:
    def test_save_and_get(self, repo):
        snap = {"v": 2, "nodeStates": {"a": "fired"}}
        repo.save_snapshot("iran-hormuz", 1, json.dumps(snap))
        latest = repo.get_latest_snapshot("iran-hormuz")
        assert latest is not None
        assert latest["nodeStates"]["a"] == "fired"
        assert latest["_revision"] == 1

    def test_latest_revision(self, repo):
        repo.save_snapshot("t", 1, json.dumps({"v": 2}))
        repo.save_snapshot("t", 2, json.dumps({"v": 2}))
        assert repo.get_latest_revision("t") == 2

    def test_latest_revision_empty(self, repo):
        assert repo.get_latest_revision("nonexistent") == 0

    def test_save_snapshot_is_the_only_commit_path(self, repo):
        """Snapshots commit via save_snapshot alone — no queue side-effect.

        Regression guard for the outbox kill: the coordinator used to branch
        to save_snapshot_and_enqueue for Dialectic-linked books, writing a
        row nothing ever read.
        """
        snap = json.dumps({"v": 2, "nodeStates": {"a": "fired"}})
        repo.save_snapshot("t", 1, snap)
        latest = repo.get_latest_snapshot("t")
        assert latest is not None
        assert latest["nodeStates"]["a"] == "fired"


# ═══════════════════════════════════════════════════════════════════════
# ALERT EVENTS (v2)
# ═══════════════════════════════════════════════════════════════════════

class TestAlertEvents:
    def test_insert_and_list(self, repo):
        evt = {
            "event_id": str(uuid.uuid4()),
            "thesis_id": "iran-hormuz",
            "revision": 1,
            "event_type": "node.state_changed",
            "severity": "critical",
            "node_id": "brent",
            "old_value": "approaching",
            "new_value": "fired",
            "occurred_at": "2026-04-12T00:00:00Z",
            "dedupe_key": "iran-hormuz:node.state_changed:brent:1",
        }
        count = repo.insert_alert_events([evt])
        events = repo.list_alert_events(thesis_id="iran-hormuz")
        assert len(events) == 1
        assert events[0]["node_id"] == "brent"

    def test_dedupe(self, repo):
        evt = {
            "event_id": str(uuid.uuid4()),
            "thesis_id": "t",
            "event_type": "node.state_changed",
            "severity": "info",
            "occurred_at": "2026-04-12T00:00:00Z",
            "dedupe_key": "t:node.state_changed::1",
        }
        repo.insert_alert_events([evt])
        evt2 = dict(evt)
        evt2["event_id"] = str(uuid.uuid4())  # different id, same dedupe_key
        repo.insert_alert_events([evt2])
        events = repo.list_alert_events()
        assert len(events) == 1  # deduped

    def test_filter_by_type(self, repo):
        for i, et in enumerate(["node.state_changed", "phase.changed", "node.state_changed"]):
            repo.insert_alert_events([{
                "event_id": str(uuid.uuid4()),
                "thesis_id": "t",
                "event_type": et,
                "severity": "info",
                "occurred_at": f"2026-04-12T0{i}:00:00Z",
                "dedupe_key": f"t:{et}::{i}",
            }])
        events = repo.list_alert_events(event_type="phase.changed")
        assert len(events) == 1


# ═══════════════════════════════════════════════════════════════════════
# OVERRIDES (v2)
# ═══════════════════════════════════════════════════════════════════════

class TestOverrides:
    def test_create_and_list(self, repo):
        ov = repo.create_override("iran-hormuz", "node", "brent",
                                   "current", 120.0, actor="amo",
                                   reason="Testing override")
        active = repo.list_active_overrides("iran-hormuz")
        assert len(active) == 1
        assert active[0]["value"] == 120.0

    def test_clear(self, repo):
        ov = repo.create_override("t", "node", "n", "f", 1.0)
        cleared = repo.clear_override(ov["override_id"])
        assert cleared["status"] == "cleared"
        assert repo.list_active_overrides("t") == []

    def test_expire(self, repo):
        # Create override that already expired
        ov = repo.create_override("t", "node", "n", "f", 1.0,
                                   expires_at="2020-01-01T00:00:00Z")
        count = repo.expire_overrides()
        assert count == 1
        assert repo.list_active_overrides("t") == []


# ═══════════════════════════════════════════════════════════════════════
# CLOSE OBSERVATIONS (v2)
# ═══════════════════════════════════════════════════════════════════════

class TestCloseObservations:
    def test_insert_and_streak(self, repo):
        for d in ["2026-04-01", "2026-04-02", "2026-04-03"]:
            repo.insert_close_observation("t", "brent", d, "115", 116.0)
        assert repo.get_close_streak("t", "brent", "115") == 3

    def test_streak_resets_on_non_qualifying(self, repo):
        """2 qualifying, 1 non-qualifying, 1 qualifying → streak = 1."""
        repo.insert_close_observation("t", "n", "2026-04-01", "k", 120.0, qualifies=True)
        repo.insert_close_observation("t", "n", "2026-04-02", "k", 120.0, qualifies=True)
        repo.insert_close_observation("t", "n", "2026-04-03", "k", 100.0, qualifies=False)
        repo.insert_close_observation("t", "n", "2026-04-04", "k", 120.0, qualifies=True)
        assert repo.get_close_streak("t", "n", "k") == 1  # not 3

    def test_pk_dedup(self, repo):
        repo.insert_close_observation("t", "n", "2026-04-01", "k", 120.0)
        repo.insert_close_observation("t", "n", "2026-04-01", "k", 125.0)  # same PK
        assert repo.get_close_streak("t", "n", "k") == 1

    def test_empty_streak(self, repo):
        assert repo.get_close_streak("t", "n", "k") == 0


# ═══════════════════════════════════════════════════════════════════════
# FETCH RUNS (v2)
# ═══════════════════════════════════════════════════════════════════════

class TestFetchRuns:
    def test_insert_and_complete(self, repo):
        run_id = repo.insert_fetch_run("iran-hormuz",
                                        provider_values={"brent": 85.0})
        repo.complete_fetch_run(run_id, status="success", revision=1)
        values = repo.get_latest_provider_values("iran-hormuz")
        assert values == {"brent": 85.0}

    def test_no_provider_values(self, repo):
        assert repo.get_latest_provider_values("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════
# OUTBOX (v2) — REMOVED IN MIGRATION 004
# ═══════════════════════════════════════════════════════════════════════

class TestOutboxRemoved:
    """The SQLite outbox was a write-only queue with no drainer.

    These guard the removal, not the removal's paperwork: the table check
    queries a really-migrated database, and the method check interrogates a
    real Repository object.
    """

    def test_table_is_dropped_by_migrations(self, repo):
        from web.persistence.connection import get_connection
        from web.persistence.migrations import run_migrations
        conn = get_connection(":memory:")
        run_migrations(conn)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "outbox" not in tables
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        assert "idx_outbox_pending" not in indexes
        conn.close()

    @pytest.mark.parametrize("name", [
        "save_snapshot_and_enqueue",
        "get_pending_outbox",
        "mark_outbox_sent",
        "increment_outbox_attempt",
        "mark_outbox_failed",
    ])
    def test_repository_method_is_gone(self, repo, name):
        assert not hasattr(repo, name)


# ═══════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════

class TestExport:
    def test_room_markdown(self, repo):
        room = repo.create_room("Export Test")
        repo.save_message(room["id"], "amo", "first message")
        repo.save_message(room["id"], "dan", "second message")
        md = repo.export_room_markdown(room["id"])
        assert "# Export Test" in md
        assert "first message" in md
        assert "second message" in md
