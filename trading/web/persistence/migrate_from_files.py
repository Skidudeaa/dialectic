"""
One-time migration: web/data/ JSON/JSONL files → SQLite.

WHY: The v2 persistence layer uses SQLite. Existing production data on the
DO droplet lives in web/data/ as JSON + JSONL files. This script reads those
files and populates the SQLite tables, preserving IDs and timestamps.

Usage:
    python -m web.persistence.migrate_from_files
    python -m web.persistence.migrate_from_files --db-path /path/to/tradingdesk.db
    python -m web.persistence.migrate_from_files --dry-run

TRADEOFF: Old files are left in place after migration. Archival is a manual
operator step after verification (per CLAUDE.md: "persist the new store to
disk before removing/renaming the old file").
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

from web.persistence.connection import DEFAULT_DB_PATH
from web.persistence.repository import Repository

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _read_json(path: Path, default=None):
    """Read a JSON file, returning default if missing or malformed."""
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Cannot read %s: %s", path, e)
        return default


def _read_jsonl(path: Path) -> List[dict]:
    """Read JSONL, skipping malformed lines (matching web/state.py behavior)."""
    if not path.exists():
        return []
    records = []
    skipped = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                skipped += 1
    if skipped:
        log.warning("Skipped %d malformed lines in %s", skipped, path)
    return records


def migrate(repo: Repository, data_dir: Path, dry_run: bool = False) -> dict:
    """Migrate all file-based state to SQLite.

    Returns summary dict with counts per entity type.
    """
    summary = {
        "rooms": 0,
        "messages": 0,
        "pins": 0,
        "journal_entries": 0,
        "predictions": 0,
        "tv_events": 0,
        "skipped": 0,
        "errors": 0,
    }

    # ── Rooms ───────────────────────────────────────────────────────
    rooms_file = data_dir / "rooms.json"
    rooms = _read_json(rooms_file, default=[])
    for room in rooms:
        room_id = room.get("id")
        if not room_id:
            summary["skipped"] += 1
            continue
        # Check if already migrated (idempotent)
        if not dry_run and repo.get_room(room_id) is not None:
            log.info("Room %s already exists, skipping", room_id[:8])
            summary["skipped"] += 1
            continue
        if not dry_run:
            try:
                from web.persistence.connection import get_connection
                conn = repo._conn()
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO rooms
                           (id, name, topic, linked_book_id, participants, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (room_id, room.get("name", ""),
                         room.get("topic", ""),
                         room.get("linked_book_id"),
                         json.dumps(room.get("participants", [])),
                         room.get("created_at", "")),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                log.error("Failed to migrate room %s: %s", room_id[:8], e)
                summary["errors"] += 1
                continue
        summary["rooms"] += 1

        # ── Messages for this room ──────────────────────────────────
        messages_path = data_dir / "rooms" / room_id / "messages.jsonl"
        messages = _read_jsonl(messages_path)
        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id:
                summary["skipped"] += 1
                continue
            if not dry_run:
                try:
                    conn = repo._conn()
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO messages
                               (id, room_id, user, content, msg_type, model, ts)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (msg_id, room_id, msg.get("user", ""),
                             msg.get("content", ""), msg.get("msg_type", "user"),
                             msg.get("model"), msg.get("ts", "")),
                        )
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as e:
                    log.error("Failed to migrate message %s: %s", msg_id[:8], e)
                    summary["errors"] += 1
                    continue
            summary["messages"] += 1

        # ── Pins for this room ──────────────────────────────────────
        pins_path = data_dir / "rooms" / room_id / "pins.json"
        pins = _read_json(pins_path, default=[])
        for pin in pins:
            pin_id = pin.get("id")
            if not pin_id:
                summary["skipped"] += 1
                continue
            if not dry_run:
                try:
                    conn = repo._conn()
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO pins
                               (id, room_id, user, content, msg_type, model, ts)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (pin_id, room_id, pin.get("user", ""),
                             pin.get("content", ""), pin.get("msg_type", "user"),
                             pin.get("model"), pin.get("ts", "")),
                        )
                        conn.commit()
                    finally:
                        conn.close()
                except Exception as e:
                    log.error("Failed to migrate pin %s: %s", pin_id[:8], e)
                    summary["errors"] += 1
                    continue
            summary["pins"] += 1

    # ── Journal entries ─────────────────────────────────────────────
    journal_path = data_dir / "journal.jsonl"
    for entry in _read_jsonl(journal_path):
        entry_id = entry.get("id")
        if not entry_id:
            summary["skipped"] += 1
            continue
        if not dry_run:
            try:
                conn = repo._conn()
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO journal_entries
                           (id, user, thesis, instrument, direction, entry_price,
                            exit_price, pnl, tags, linked_book_id, notes,
                            created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (entry_id, entry.get("user", ""),
                         entry.get("thesis", ""), entry.get("instrument", ""),
                         entry.get("direction", ""),
                         entry.get("entry_price"), entry.get("exit_price"),
                         entry.get("pnl"),
                         json.dumps(entry.get("tags", [])),
                         entry.get("linked_book_id"),
                         entry.get("notes", ""),
                         entry.get("created_at", ""),
                         entry.get("updated_at")),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                log.error("Failed to migrate journal entry %s: %s", entry_id[:8], e)
                summary["errors"] += 1
                continue
        summary["journal_entries"] += 1

    # ── Predictions ─────────────────────────────────────────────────
    predictions_path = data_dir / "predictions.jsonl"
    for pred in _read_jsonl(predictions_path):
        pred_id = pred.get("id")
        if not pred_id:
            summary["skipped"] += 1
            continue
        if not dry_run:
            try:
                conn = repo._conn()
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO predictions
                           (id, user, statement, confidence, deadline,
                            resolution, resolved_at, linked_book_id, tags,
                            created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (pred_id, pred.get("user", ""),
                         pred.get("statement", ""),
                         pred.get("confidence", 0),
                         pred.get("deadline", ""),
                         pred.get("resolution"),
                         pred.get("resolved_at"),
                         pred.get("linked_book_id"),
                         json.dumps(pred.get("tags", [])),
                         pred.get("created_at", "")),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                log.error("Failed to migrate prediction %s: %s", pred_id[:8], e)
                summary["errors"] += 1
                continue
        summary["predictions"] += 1

    # ── TradingView events ──────────────────────────────────────────
    tv_path = data_dir / "tradingview-events.jsonl"
    for evt in _read_jsonl(tv_path):
        if not dry_run:
            try:
                conn = repo._conn()
                try:
                    new_value = evt.get("newValue")
                    conn.execute(
                        """INSERT INTO tv_events
                           (ts, result, book_id, binding_id, node_id, op,
                            new_value, detail, source_ip)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (evt.get("ts", ""), evt.get("result", ""),
                         evt.get("bookId"), evt.get("bindingId"),
                         evt.get("nodeId"), evt.get("op"),
                         json.dumps(new_value) if new_value is not None else None,
                         evt.get("detail"), evt.get("sourceIP")),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                log.error("Failed to migrate TV event: %s", e)
                summary["errors"] += 1
                continue
        summary["tv_events"] += 1

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Migrate web/data/ file-based state to SQLite"
    )
    parser.add_argument(
        "--db-path", default=str(DEFAULT_DB_PATH),
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--data-dir", default=str(DATA_DIR),
        help=f"Source data directory (default: {DATA_DIR})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count records without writing to database",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    repo = Repository(args.db_path)
    if not args.dry_run:
        applied = repo.initialize()
        log.info("Migrations applied: %d", applied)

    summary = migrate(repo, data_dir, dry_run=args.dry_run)

    mode = "DRY RUN" if args.dry_run else "MIGRATED"
    print(f"\n{'='*50}")
    print(f"  {mode} — web/data/ → SQLite")
    print(f"{'='*50}")
    print(f"  Rooms:           {summary['rooms']}")
    print(f"  Messages:        {summary['messages']}")
    print(f"  Pins:            {summary['pins']}")
    print(f"  Journal entries: {summary['journal_entries']}")
    print(f"  Predictions:     {summary['predictions']}")
    print(f"  TV events:       {summary['tv_events']}")
    print(f"  Skipped:         {summary['skipped']}")
    print(f"  Errors:          {summary['errors']}")
    print(f"{'='*50}")

    if not args.dry_run:
        print(f"\n  Database: {args.db_path}")
        print(f"  Old files left in place — archive manually after verification.")
        print(f"\n  Verification queries:")
        print(f"    sqlite3 {args.db_path} 'SELECT COUNT(*) FROM rooms;'")
        print(f"    sqlite3 {args.db_path} 'SELECT COUNT(*) FROM messages;'")
        print(f"    sqlite3 {args.db_path} 'SELECT COUNT(*) FROM predictions;'")

    if summary["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
