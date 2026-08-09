"""
Tests for file-based → SQLite data migration.

WHY: The migration script handles production data. These tests verify:
idempotency (running twice doesn't duplicate), malformed line handling,
missing directory handling, and correct field mapping.
"""

import json
import os
from pathlib import Path

import pytest

from web.persistence.migrate_from_files import migrate
from web.persistence.repository import Repository


@pytest.fixture
def repo():
    """Fresh in-memory SQLite database per test."""
    r = Repository(":memory:")
    r.initialize()
    return r


@pytest.fixture
def data_dir(tmp_path):
    """Create a minimal file-based data directory matching web/data/ shape."""
    d = tmp_path / "data"
    d.mkdir()

    # rooms.json
    rooms = [
        {
            "id": "room-1",
            "name": "Iran Desk",
            "topic": "Oil thesis",
            "linked_book_id": "iran-hormuz-graph",
            "participants": ["amo", "dan"],
            "created_at": "2026-04-01T00:00:00Z",
        },
        {
            "id": "room-2",
            "name": "General",
            "topic": "",
            "linked_book_id": None,
            "participants": [],
            "created_at": "2026-04-02T00:00:00Z",
        },
    ]
    (d / "rooms.json").write_text(json.dumps(rooms))

    # Room 1: messages + pins
    room1_dir = d / "rooms" / "room-1"
    room1_dir.mkdir(parents=True)
    msgs = [
        {"id": "msg-1", "room_id": "room-1", "user": "amo",
         "content": "hello", "msg_type": "user", "model": None,
         "ts": "2026-04-01T10:00:00Z"},
        {"id": "msg-2", "room_id": "room-1", "user": "dan",
         "content": "hi there", "msg_type": "user", "model": None,
         "ts": "2026-04-01T10:01:00Z"},
    ]
    with open(room1_dir / "messages.jsonl", "w") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")

    pins = [
        {"id": "msg-1", "room_id": "room-1", "user": "amo",
         "content": "hello", "msg_type": "user", "ts": "2026-04-01T10:00:00Z"},
    ]
    (room1_dir / "pins.json").write_text(json.dumps(pins))

    # Room 2: empty (no messages dir)
    (d / "rooms" / "room-2").mkdir(parents=True)

    # journal.jsonl
    journal = [
        {"id": "j-1", "user": "amo", "thesis": "Iran",
         "instrument": "XOP", "direction": "long", "entry_price": 45.0,
         "tags": ["oil"], "linked_book_id": "iran-hormuz-graph",
         "notes": "Opening position", "created_at": "2026-04-01T00:00:00Z"},
    ]
    with open(d / "journal.jsonl", "w") as f:
        for j in journal:
            f.write(json.dumps(j) + "\n")

    # predictions.jsonl
    preds = [
        {"id": "p-1", "user": "amo", "statement": "Brent above 100",
         "confidence": 0.7, "deadline": "2026-05-01",
         "resolution": None, "resolved_at": None,
         "tags": ["oil"], "created_at": "2026-04-01T00:00:00Z"},
        {"id": "p-2", "user": "dan", "statement": "SPY below 400",
         "confidence": 0.3, "deadline": "2026-06-01",
         "resolution": "incorrect", "resolved_at": "2026-05-15T00:00:00Z",
         "tags": [], "created_at": "2026-04-02T00:00:00Z"},
    ]
    with open(d / "predictions.jsonl", "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")

    # tradingview-events.jsonl
    tv_events = [
        {"ts": "2026-04-10T00:00:00Z", "result": "ok",
         "bookId": "iran-hormuz-graph", "bindingId": "b1",
         "nodeId": "brent", "op": "setCurrent", "newValue": 85.0,
         "detail": None, "sourceIP": "1.2.3.4"},
    ]
    with open(d / "tradingview-events.jsonl", "w") as f:
        for e in tv_events:
            f.write(json.dumps(e) + "\n")

    return d


class TestMigration:
    def test_full_migration(self, repo, data_dir):
        """All data types migrate correctly."""
        summary = migrate(repo, data_dir)
        assert summary["rooms"] == 2
        assert summary["messages"] == 2
        assert summary["pins"] == 1
        assert summary["journal_entries"] == 1
        assert summary["predictions"] == 2
        assert summary["tv_events"] == 1
        assert summary["errors"] == 0

        # Verify data integrity
        rooms = repo.list_rooms()
        assert len(rooms) == 2
        assert rooms[0]["name"] == "Iran Desk"
        assert rooms[0]["participants"] == ["amo", "dan"]

        msgs = repo.list_messages("room-1")
        assert len(msgs) == 2
        assert msgs[0]["content"] == "hello"

        pins = repo.list_pins("room-1")
        assert len(pins) == 1

        journal = repo.list_journal_entries()
        assert len(journal) == 1
        assert journal[0]["tags"] == ["oil"]

        preds = repo.list_predictions()
        assert len(preds) == 2
        resolved = [p for p in preds if p["resolution"] is not None]
        assert len(resolved) == 1
        assert resolved[0]["resolution"] == "incorrect"

        tv = repo.list_tv_events()
        assert len(tv) == 1
        assert tv[0]["newValue"] == 85.0

    def test_idempotent(self, repo, data_dir):
        """Running migration twice does not duplicate data."""
        migrate(repo, data_dir)
        summary2 = migrate(repo, data_dir)
        # Rooms should be skipped (already exist)
        assert summary2["skipped"] >= 2
        # Total room count should still be 2
        assert len(repo.list_rooms()) == 2

    def test_dry_run(self, repo, data_dir):
        """Dry run counts records without writing."""
        summary = migrate(repo, data_dir, dry_run=True)
        assert summary["rooms"] == 2
        assert summary["messages"] == 2
        # Database should be empty
        assert repo.list_rooms() == []

    def test_missing_data_dir(self, repo, tmp_path):
        """Missing data directory produces empty summary."""
        summary = migrate(repo, tmp_path / "nonexistent")
        assert summary["rooms"] == 0
        assert summary["errors"] == 0

    def test_malformed_jsonl(self, repo, data_dir):
        """Malformed JSONL lines are skipped without crashing."""
        # Append bad line to journal
        with open(data_dir / "journal.jsonl", "a") as f:
            f.write("not valid json\n")
        summary = migrate(repo, data_dir)
        assert summary["journal_entries"] == 1  # valid line still migrated

    def test_message_ordering_preserved(self, repo, data_dir):
        """Message timestamps preserved correctly for pagination."""
        migrate(repo, data_dir)
        msgs = repo.list_messages("room-1")
        assert msgs[0]["ts"] < msgs[1]["ts"]  # oldest first

    def test_linked_book_id_preserved(self, repo, data_dir):
        """Room linked_book_id and journal linked_book_id both migrate."""
        migrate(repo, data_dir)
        room = repo.get_room("room-1")
        assert room["linked_book_id"] == "iran-hormuz-graph"
        journal = repo.list_journal_entries()
        assert journal[0]["linked_book_id"] == "iran-hormuz-graph"

    def test_resolved_prediction_preserves_state(self, repo, data_dir):
        """Pre-resolved predictions keep their resolution and resolved_at."""
        migrate(repo, data_dir)
        preds = repo.list_predictions()
        resolved = [p for p in preds if p["id"] == "p-2"]
        assert len(resolved) == 1
        assert resolved[0]["resolution"] == "incorrect"
        assert resolved[0]["resolved_at"] == "2026-05-15T00:00:00Z"


class TestMigrationAgainstRealData:
    """Migration tests against actual web/data/ on disk."""

    def test_real_data_dry_run(self, repo):
        """Dry run against real web/data/ counts records without errors."""
        real_data = Path(__file__).resolve().parent.parent / "data"
        if not real_data.exists():
            pytest.skip("No web/data/ directory found")
        summary = migrate(repo, real_data, dry_run=True)
        assert summary["errors"] == 0
        assert summary["rooms"] > 0
        print(f"\nReal data dry-run: {summary}")
