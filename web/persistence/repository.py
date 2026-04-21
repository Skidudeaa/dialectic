"""
Data access layer — SQLite repository replacing web/state.py.

WHY: Every method opens/closes its own connection. asyncio.to_thread runs
callables in a thread pool; sharing a sqlite3.Connection across threads
triggers 'ProgrammingError: SQLite objects created in a thread can only
be used in that same thread.' One connection per call is cheap for SQLite
(<1ms setup) and sidesteps this entirely.

All methods are synchronous. Callers wrap in asyncio.to_thread().
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from web.persistence.connection import get_connection
from web.persistence.migrations import run_migrations

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return str(uuid.uuid4())


def _validate_id(value: str, label: str = "ID") -> None:
    """Reject IDs that could traverse the filesystem or cause SQL issues."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
        raise ValueError(f"Invalid {label}: {value}")


class Repository:
    """Synchronous data access layer backed by SQLite.

    WHY a class: holds the db_path so each method can open its own
    connection with consistent configuration. Not a singleton — tests
    create fresh instances with :memory: databases.

    TRADEOFF: For :memory: databases, each connection sees different data.
    We use a shared-cache URI (file::memory:?cache=shared) so all connections
    to the same Repository instance share one in-memory database. For file-
    backed databases, per-operation connections are fine (WAL mode handles
    concurrency).
    """

    _instance_counter = 0

    def __init__(self, db_path: str | Path = ":memory:"):
        raw = str(db_path)
        if raw == ":memory:":
            # WHY: Shared-cache URI lets multiple connections see the same
            # in-memory database. Each Repository instance gets a unique name
            # so tests stay isolated. Monotonic counter avoids id() reuse.
            Repository._instance_counter += 1
            self._db_path = f"file:memdb_{Repository._instance_counter}?mode=memory&cache=shared"
            self._is_memory = True
        else:
            self._db_path = raw
            self._is_memory = False
        # WHY: Keep one connection alive for :memory: databases. If ALL
        # connections to a shared-cache in-memory DB close, the DB is deleted.
        # This sentinel connection keeps the DB alive for the Repository's lifetime.
        if self._is_memory:
            import sqlite3
            self._sentinel = sqlite3.connect(self._db_path, uri=True)

    def _conn(self):
        if self._is_memory:
            import sqlite3
            conn = sqlite3.connect(self._db_path, uri=True, timeout=10.0)
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            return conn
        return get_connection(self._db_path)

    def initialize(self) -> int:
        """Run pending migrations. Returns count applied."""
        conn = self._conn()
        try:
            return run_migrations(conn)
        finally:
            conn.close()

    def ping(self) -> bool:
        """Cheap writability probe for readiness checks.

        Opens a connection, runs a trivial write-path query (CREATE TEMP
        TABLE) and closes. Returns True on success; raises on failure so
        callers get the real exception instead of a silent False.
        """
        conn = self._conn()
        try:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS _ping (x INTEGER)")
            conn.execute("INSERT INTO _ping (x) VALUES (1)")
            conn.execute("DROP TABLE _ping")
            conn.commit()
            return True
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════════
    # ROOMS
    # ════════════════════════════════════════════════════════════════

    def list_rooms(self) -> List[dict]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM rooms ORDER BY created_at").fetchall()
            return [self._room_from_row(r) for r in rows]
        finally:
            conn.close()

    def get_room(self, room_id: str) -> Optional[dict]:
        _validate_id(room_id, "room_id")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
            return self._room_from_row(row) if row else None
        finally:
            conn.close()

    def create_room(self, name: str, topic: str = "",
                    linked_book_id: Optional[str] = None,
                    participants: Optional[List[str]] = None) -> dict:
        room = {
            "id": _gen_id(),
            "name": name,
            "topic": topic,
            "linked_book_id": linked_book_id,
            "participants": participants or [],
            "created_at": _now_iso(),
        }
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO rooms (id, name, topic, linked_book_id, participants, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (room["id"], name, topic, linked_book_id,
                 json.dumps(room["participants"]), room["created_at"]),
            )
            conn.commit()
            return room
        finally:
            conn.close()

    def update_room(self, room_id: str, updates: dict) -> Optional[dict]:
        _validate_id(room_id, "room_id")
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
            if not row:
                return None
            room = self._room_from_row(row)
            room.update(updates)
            conn.execute(
                """UPDATE rooms SET name=?, topic=?, linked_book_id=?, participants=?
                   WHERE id=?""",
                (room["name"], room["topic"], room.get("linked_book_id"),
                 json.dumps(room.get("participants", [])), room_id),
            )
            conn.commit()
            return room
        finally:
            conn.close()

    def delete_room(self, room_id: str) -> None:
        _validate_id(room_id, "room_id")
        conn = self._conn()
        try:
            # WHY: CASCADE on messages and pins handles cleanup.
            conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _room_from_row(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "topic": row["topic"],
            "linked_book_id": row["linked_book_id"],
            "participants": json.loads(row["participants"]) if row["participants"] else [],
            "created_at": row["created_at"],
        }

    # ════════════════════════════════════════════════════════════════
    # MESSAGES
    # ════════════════════════════════════════════════════════════════

    def list_messages(self, room_id: str, limit: int = 50,
                      before: Optional[str] = None) -> List[dict]:
        _validate_id(room_id, "room_id")
        conn = self._conn()
        try:
            if before:
                rows = conn.execute(
                    """SELECT * FROM messages WHERE room_id = ? AND ts < ?
                       ORDER BY ts DESC LIMIT ?""",
                    (room_id, before, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM messages WHERE room_id = ?
                       ORDER BY ts DESC LIMIT ?""",
                    (room_id, limit),
                ).fetchall()
            # WHY reverse: return oldest-first for display (same as file-based version)
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()

    def save_message(self, room_id: str, user: str, content: str,
                     msg_type: str = "user",
                     model: Optional[str] = None) -> dict:
        msg = {
            "id": _gen_id(),
            "room_id": room_id,
            "user": user,
            "content": content,
            "msg_type": msg_type,
            "model": model,
            "ts": _now_iso(),
        }
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO messages (id, room_id, user, content, msg_type, model, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (msg["id"], room_id, user, content, msg_type, model, msg["ts"]),
            )
            conn.commit()
            return msg
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════════
    # PINS
    # ════════════════════════════════════════════════════════════════

    def list_pins(self, room_id: str) -> List[dict]:
        _validate_id(room_id, "room_id")
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM pins WHERE room_id = ? ORDER BY ts", (room_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_pin(self, room_id: str, message: dict) -> List[dict]:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO pins (id, room_id, user, content, msg_type, model, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (message["id"], room_id, message.get("user", ""),
                 message.get("content", ""), message.get("msg_type", "user"),
                 message.get("model"), message.get("ts", _now_iso())),
            )
            conn.commit()
            return self.list_pins(room_id)
        finally:
            conn.close()

    def remove_pin(self, room_id: str, message_id: str) -> List[dict]:
        conn = self._conn()
        try:
            conn.execute("DELETE FROM pins WHERE id = ? AND room_id = ?",
                         (message_id, room_id))
            conn.commit()
            return self.list_pins(room_id)
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════════
    # JOURNAL
    # ════════════════════════════════════════════════════════════════

    def list_journal_entries(self) -> List[dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM journal_entries ORDER BY created_at"
            ).fetchall()
            return [self._journal_from_row(r) for r in rows]
        finally:
            conn.close()

    def save_journal_entry(self, user: str, entry: dict) -> dict:
        record = {
            "id": _gen_id(),
            "user": user,
            "thesis": entry.get("thesis", ""),
            "instrument": entry.get("instrument", ""),
            "direction": entry.get("direction", ""),
            "entry_price": entry.get("entry_price"),
            "exit_price": entry.get("exit_price"),
            "pnl": entry.get("pnl"),
            "tags": entry.get("tags", []),
            "linked_book_id": entry.get("linked_book_id"),
            "notes": entry.get("notes", ""),
            "created_at": _now_iso(),
        }
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO journal_entries
                   (id, user, thesis, instrument, direction, entry_price,
                    exit_price, pnl, tags, linked_book_id, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record["id"], user, record["thesis"], record["instrument"],
                 record["direction"], record["entry_price"], record["exit_price"],
                 record["pnl"], json.dumps(record["tags"]),
                 record["linked_book_id"], record["notes"], record["created_at"]),
            )
            conn.commit()
            return record
        finally:
            conn.close()

    def update_journal_entry(self, entry_id: str, updates: dict) -> Optional[dict]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if not row:
                return None
            record = self._journal_from_row(row)
            record.update(updates)
            record["updated_at"] = _now_iso()
            if "tags" in updates:
                record["tags"] = updates["tags"]
            conn.execute(
                """UPDATE journal_entries SET exit_price=?, pnl=?, notes=?,
                   tags=?, updated_at=? WHERE id=?""",
                (record.get("exit_price"), record.get("pnl"),
                 record.get("notes", ""), json.dumps(record.get("tags", [])),
                 record["updated_at"], entry_id),
            )
            conn.commit()
            return record
        finally:
            conn.close()

    @staticmethod
    def _journal_from_row(row) -> dict:
        d = dict(row)
        d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        return d

    # ════════════════════════════════════════════════════════════════
    # PREDICTIONS
    # ════════════════════════════════════════════════════════════════

    def list_predictions(self) -> List[dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM predictions ORDER BY created_at"
            ).fetchall()
            return [self._prediction_from_row(r) for r in rows]
        finally:
            conn.close()

    def save_prediction(self, user: str, prediction: dict) -> dict:
        record = {
            "id": _gen_id(),
            "user": user,
            "statement": prediction["statement"],
            "confidence": prediction["confidence"],
            "deadline": prediction["deadline"],
            "resolution": None,
            "resolved_at": None,
            "linked_book_id": prediction.get("linked_book_id"),
            "tags": prediction.get("tags", []),
            "created_at": _now_iso(),
        }
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO predictions
                   (id, user, statement, confidence, deadline, resolution,
                    resolved_at, linked_book_id, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record["id"], user, record["statement"], record["confidence"],
                 record["deadline"], None, None, record["linked_book_id"],
                 json.dumps(record["tags"]), record["created_at"]),
            )
            conn.commit()
            return record
        finally:
            conn.close()

    def resolve_prediction(self, prediction_id: str, resolution: str) -> Optional[dict]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM predictions WHERE id = ?", (prediction_id,)
            ).fetchone()
            if not row:
                return None
            now = _now_iso()
            conn.execute(
                "UPDATE predictions SET resolution=?, resolved_at=? WHERE id=?",
                (resolution, now, prediction_id),
            )
            conn.commit()
            record = self._prediction_from_row(row)
            record["resolution"] = resolution
            record["resolved_at"] = now
            return record
        finally:
            conn.close()

    @staticmethod
    def _prediction_from_row(row) -> dict:
        d = dict(row)
        d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        return d

    # ════════════════════════════════════════════════════════════════
    # TRADINGVIEW EVENTS
    # ════════════════════════════════════════════════════════════════

    def save_tv_event(self, *, result: str, book_id: Optional[str] = None,
                      binding_id: Optional[str] = None,
                      node_id: Optional[str] = None,
                      op: Optional[str] = None,
                      new_value: Any = None,
                      detail: Optional[str] = None,
                      source_ip: Optional[str] = None) -> dict:
        record = {
            "ts": _now_iso(),
            "result": result,
            "bookId": book_id,
            "bindingId": binding_id,
            "nodeId": node_id,
            "op": op,
            "newValue": new_value,
            "detail": detail,
            "sourceIP": source_ip,
        }
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO tv_events (ts, result, book_id, binding_id,
                   node_id, op, new_value, detail, source_ip)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record["ts"], result, book_id, binding_id, node_id, op,
                 json.dumps(new_value) if new_value is not None else None,
                 detail, source_ip),
            )
            conn.commit()
            return record
        finally:
            conn.close()

    def list_tv_events(self, *, limit: int = 50,
                       book_id: Optional[str] = None) -> List[dict]:
        conn = self._conn()
        try:
            if book_id:
                rows = conn.execute(
                    """SELECT * FROM tv_events WHERE book_id = ?
                       ORDER BY ts DESC LIMIT ?""",
                    (book_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tv_events ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._tv_event_from_row(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _tv_event_from_row(row) -> dict:
        """Convert DB row to API-compatible dict with camelCase keys."""
        return {
            "ts": row["ts"],
            "result": row["result"],
            "bookId": row["book_id"],
            "bindingId": row["binding_id"],
            "nodeId": row["node_id"],
            "op": row["op"],
            "newValue": json.loads(row["new_value"]) if row["new_value"] else None,
            "detail": row["detail"],
            "sourceIP": row["source_ip"],
        }

    # ════════════════════════════════════════════════════════════════
    # CHAT EXPORT (mirrors web/state.py export_room_markdown)
    # ════════════════════════════════════════════════════════════════

    def export_room_markdown(self, room_id: str) -> str:
        room = self.get_room(room_id)
        name = room["name"] if room else room_id
        messages = self.list_messages(room_id, limit=10000)
        lines = [f"# {name}", f"Exported: {_now_iso()}", ""]
        for msg in messages:
            ts = msg.get("ts", "")[:19].replace("T", " ")
            user = msg.get("user", "?")
            content = msg.get("content", "")
            mtype = msg.get("msg_type", "user")
            model = msg.get("model", "")
            if mtype == "system":
                lines.append(f"*[{ts}] {content}*")
            elif mtype == "llm":
                lines.append(f"**{model or 'AI'}** ({ts}):\n{content}")
            else:
                lines.append(f"**{user}** ({ts}): {content}")
            lines.append("")
        return "\n".join(lines)

    # ════════════════════════════════════════════════════════════════
    # THESIS SNAPSHOTS (v2)
    # ════════════════════════════════════════════════════════════════

    def save_snapshot(self, thesis_id: str, revision: int,
                      snapshot_json: str, definition_hash: Optional[str] = None,
                      quality_status: str = "healthy") -> None:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO thesis_snapshots
                   (thesis_id, revision, generated_at, definition_hash,
                    quality_status, snapshot_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (thesis_id, revision, _now_iso(), definition_hash,
                 quality_status, snapshot_json),
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest_snapshot(self, thesis_id: str) -> Optional[dict]:
        conn = self._conn()
        try:
            row = conn.execute(
                """SELECT snapshot_json, revision FROM thesis_snapshots
                   WHERE thesis_id = ? ORDER BY revision DESC LIMIT 1""",
                (thesis_id,),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["snapshot_json"])
            data["_revision"] = row["revision"]
            return data
        finally:
            conn.close()

    def get_latest_revision(self, thesis_id: str) -> int:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT MAX(revision) as rev FROM thesis_snapshots WHERE thesis_id = ?",
                (thesis_id,),
            ).fetchone()
            return row["rev"] if row and row["rev"] is not None else 0
        finally:
            conn.close()

    def save_snapshot_and_enqueue(self, thesis_id: str, revision: int,
                                  snapshot_json: str,
                                  definition_hash: Optional[str] = None,
                                  quality_status: str = "healthy") -> Tuple[int, int]:
        """Atomic: save snapshot + enqueue outbox in one transaction.

        WHY: If the process crashes between save_snapshot and enqueue as
        separate calls, the Dialectic push is lost. A single transaction
        makes it all-or-nothing.
        """
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO thesis_snapshots
                   (thesis_id, revision, generated_at, definition_hash,
                    quality_status, snapshot_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (thesis_id, revision, _now_iso(), definition_hash,
                 quality_status, snapshot_json),
            )
            cur = conn.execute(
                """INSERT INTO outbox (kind, thesis_id, payload_json, status, created_at)
                   VALUES ('dialectic', ?, ?, 'pending', ?)""",
                (thesis_id, snapshot_json, _now_iso()),
            )
            conn.commit()
            return revision, cur.lastrowid
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════════
    # ALERT EVENTS (v2)
    # ════════════════════════════════════════════════════════════════

    def insert_alert_events(self, events: List[dict]) -> int:
        """Insert alert events with dedupe. Returns count inserted."""
        if not events:
            return 0
        conn = self._conn()
        try:
            count = 0
            for evt in events:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO alert_events
                           (event_id, thesis_id, revision, event_type, severity,
                            node_id, old_value_json, new_value_json, occurred_at,
                            dedupe_key)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (evt["event_id"], evt["thesis_id"], evt.get("revision"),
                         evt["event_type"], evt["severity"],
                         evt.get("node_id"),
                         json.dumps(evt.get("old_value")) if evt.get("old_value") is not None else None,
                         json.dumps(evt.get("new_value")) if evt.get("new_value") is not None else None,
                         evt["occurred_at"], evt["dedupe_key"]),
                    )
                    count += conn.total_changes  # only counts if not IGNORE'd
                except Exception:
                    log.warning("Failed to insert event %s", evt.get("event_id"))
            conn.commit()
            return count
        finally:
            conn.close()

    def list_alert_events(self, *, thesis_id: Optional[str] = None,
                          event_type: Optional[str] = None,
                          limit: int = 50) -> List[dict]:
        conn = self._conn()
        try:
            conditions = []
            params: list = []
            if thesis_id:
                conditions.append("thesis_id = ?")
                params.append(thesis_id)
            if event_type:
                conditions.append("event_type = ?")
                params.append(event_type)
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM alert_events {where} ORDER BY occurred_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return [self._alert_from_row(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _alert_from_row(row) -> dict:
        return {
            "event_id": row["event_id"],
            "thesis_id": row["thesis_id"],
            "revision": row["revision"],
            "event_type": row["event_type"],
            "severity": row["severity"],
            "node_id": row["node_id"],
            "old_value": json.loads(row["old_value_json"]) if row["old_value_json"] else None,
            "new_value": json.loads(row["new_value_json"]) if row["new_value_json"] else None,
            "occurred_at": row["occurred_at"],
            "dedupe_key": row["dedupe_key"],
        }

    # ════════════════════════════════════════════════════════════════
    # MANUAL OVERRIDES (v2)
    # ════════════════════════════════════════════════════════════════

    def create_override(self, thesis_id: str, target_type: str,
                        target_id: str, field: str, value: Any,
                        actor: Optional[str] = None, reason: str = "",
                        expires_at: Optional[str] = None) -> dict:
        override = {
            "override_id": _gen_id(),
            "thesis_id": thesis_id,
            "target_type": target_type,
            "target_id": target_id,
            "field": field,
            "value": value,
            "actor": actor,
            "reason": reason,
            "created_at": _now_iso(),
            "expires_at": expires_at,
            "cleared_at": None,
            "status": "active",
        }
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO manual_overrides
                   (override_id, thesis_id, target_type, target_id, field,
                    value_json, actor, reason, created_at, expires_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                (override["override_id"], thesis_id, target_type, target_id,
                 field, json.dumps(value), actor, reason,
                 override["created_at"], expires_at),
            )
            conn.commit()
            return override
        finally:
            conn.close()

    def list_active_overrides(self, thesis_id: Optional[str] = None) -> List[dict]:
        conn = self._conn()
        try:
            if thesis_id:
                rows = conn.execute(
                    "SELECT * FROM manual_overrides WHERE thesis_id = ? AND status = 'active'",
                    (thesis_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM manual_overrides WHERE status = 'active'"
                ).fetchall()
            return [self._override_from_row(r) for r in rows]
        finally:
            conn.close()

    def clear_override(self, override_id: str) -> Optional[dict]:
        conn = self._conn()
        try:
            now = _now_iso()
            conn.execute(
                "UPDATE manual_overrides SET status='cleared', cleared_at=? WHERE override_id=?",
                (now, override_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM manual_overrides WHERE override_id = ?",
                (override_id,),
            ).fetchone()
            return self._override_from_row(row) if row else None
        finally:
            conn.close()

    def expire_overrides(self) -> int:
        """Mark expired overrides. Returns count expired."""
        conn = self._conn()
        try:
            now = _now_iso()
            cur = conn.execute(
                """UPDATE manual_overrides SET status='expired'
                   WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= ?""",
                (now,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    @staticmethod
    def _override_from_row(row) -> dict:
        return {
            "override_id": row["override_id"],
            "thesis_id": row["thesis_id"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "field": row["field"],
            "value": json.loads(row["value_json"]),
            "actor": row["actor"],
            "reason": row["reason"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "cleared_at": row["cleared_at"],
            "status": row["status"],
        }

    # ════════════════════════════════════════════════════════════════
    # CLOSE OBSERVATIONS (v2)
    # ════════════════════════════════════════════════════════════════

    def insert_close_observation(self, thesis_id: str, node_id: str,
                                  market_date: str, threshold_key: str,
                                  close_value: float, qualifies: bool = True,
                                  source: str = "derived") -> None:
        """Insert or ignore (PK dedup) a close observation."""
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO close_observations
                   (thesis_id, node_id, market_date, threshold_key,
                    close_value, qualifies, captured_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (thesis_id, node_id, market_date, threshold_key,
                 close_value, 1 if qualifies else 0, _now_iso(), source),
            )
            conn.commit()
        finally:
            conn.close()

    def get_close_streak(self, thesis_id: str, node_id: str,
                         threshold_key: str) -> int:
        """Count consecutive qualifying closes (contiguous tail-run).

        WHY: The engine's closesRequired gate requires CONSECUTIVE closes
        above threshold. A bare COUNT(*) would over-count across streak
        breaks. This query finds the most recent non-qualifying close and
        counts only qualifying rows after it.
        """
        conn = self._conn()
        try:
            # Find the most recent non-qualifying date
            row = conn.execute(
                """SELECT MAX(market_date) as break_date
                   FROM close_observations
                   WHERE thesis_id = ? AND node_id = ? AND threshold_key = ?
                     AND qualifies = 0""",
                (thesis_id, node_id, threshold_key),
            ).fetchone()
            break_date = row["break_date"] if row else None

            # Count qualifying rows after the break (or all if no break)
            if break_date:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM close_observations
                       WHERE thesis_id = ? AND node_id = ? AND threshold_key = ?
                         AND qualifies = 1 AND market_date > ?""",
                    (thesis_id, node_id, threshold_key, break_date),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM close_observations
                       WHERE thesis_id = ? AND node_id = ? AND threshold_key = ?
                         AND qualifies = 1""",
                    (thesis_id, node_id, threshold_key),
                ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════════
    # FETCH RUNS (v2)
    # ════════════════════════════════════════════════════════════════

    def insert_fetch_run(self, thesis_id: str,
                         provider_values: Optional[dict] = None) -> int:
        """Start a fetch run. Returns run_id."""
        conn = self._conn()
        try:
            cur = conn.execute(
                """INSERT INTO fetch_runs (thesis_id, started_at, status, provider_values_json)
                   VALUES (?, ?, 'running', ?)""",
                (thesis_id, _now_iso(),
                 json.dumps(provider_values) if provider_values else None),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def complete_fetch_run(self, run_id: int, status: str = "success",
                           revision: Optional[int] = None,
                           provider_values: Optional[dict] = None,
                           diagnostics: Optional[dict] = None) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """UPDATE fetch_runs SET finished_at=?, status=?, revision=?,
                   provider_values_json=COALESCE(?, provider_values_json),
                   diagnostics_json=? WHERE run_id=?""",
                (_now_iso(), status, revision,
                 json.dumps(provider_values) if provider_values else None,
                 json.dumps(diagnostics) if diagnostics else None,
                 run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest_provider_values(self, thesis_id: str) -> Optional[dict]:
        """Get provider values from most recent successful fetch run.

        WHY: On coordinator restart, these values hydrate the effective
        config so the first snapshot uses real prices, not stale book defaults.
        """
        conn = self._conn()
        try:
            row = conn.execute(
                """SELECT provider_values_json FROM fetch_runs
                   WHERE thesis_id = ? AND status = 'success'
                     AND provider_values_json IS NOT NULL
                   ORDER BY run_id DESC LIMIT 1""",
                (thesis_id,),
            ).fetchone()
            return json.loads(row["provider_values_json"]) if row else None
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════════
    # OUTBOX (v2)
    # ════════════════════════════════════════════════════════════════

    def get_pending_outbox(self, limit: int = 10) -> List[dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT * FROM outbox
                   WHERE status = 'pending' AND attempts < 5
                   ORDER BY created_at LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_outbox_sent(self, outbox_id: int) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE outbox SET status='sent', attempts=attempts+1 WHERE outbox_id=?",
                (outbox_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def increment_outbox_attempt(self, outbox_id: int, error: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE outbox SET attempts=attempts+1, last_error=? WHERE outbox_id=?",
                (error, outbox_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_outbox_failed(self, outbox_id: int, error: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE outbox SET status='failed', last_error=? WHERE outbox_id=?",
                (error, outbox_id),
            )
            conn.commit()
        finally:
            conn.close()
