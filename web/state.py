"""
File-based state manager for the web layer.

WHY: Follows the existing JSONL/JSON patterns in outcomes/trades/.
No database — state lives in web/data/ as JSON (objects) and JSONL (append logs).
File locking via fcntl for concurrent access safety.
"""

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

log = logging.getLogger(__name__)

# WHY: State directory lives alongside the web package, not in the project root,
# to keep generated web state separate from thesis configs and snapshots.
DATA_DIR = Path(__file__).resolve().parent / "data"


def _ensure_dir(path: Path) -> None:
    """Create directory and parents if needed."""
    path.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return str(uuid.uuid4())


def _validate_id(value: str, label: str = "ID") -> None:
    """Reject IDs that could traverse the filesystem."""
    import re
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
        raise ValueError(f"Invalid {label}: {value}")


# ── JSON (single-object) read/write ──────────────────────────────────────

def read_json(path: Path, default: Any = None) -> Any:
    """Read a JSON file with shared lock. Returns default if missing."""
    if not path.exists():
        return default
    with open(path, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def write_json(path: Path, data: Any) -> None:
    """Write a JSON file atomically — write to temp, fsync, then rename."""
    _ensure_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(str(tmp), str(path))


# ── JSONL (append-log) read/write ────────────────────────────────────────

def read_jsonl(path: Path) -> List[dict]:
    """Read all lines from a JSONL file. Returns [] if missing."""
    if not path.exists():
        return []
    lines = []
    with open(path, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning("Skipping malformed JSONL line in %s: %r", path, line)
                        continue
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return lines


def append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record to a JSONL file with exclusive lock."""
    _ensure_dir(path.parent)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ── Room persistence ─────────────────────────────────────────────────────

ROOMS_FILE = DATA_DIR / "rooms.json"


def list_rooms() -> List[dict]:
    """Return all rooms."""
    return read_json(ROOMS_FILE, default=[])


def get_room(room_id: str) -> Optional[dict]:
    """Return a single room by ID."""
    _validate_id(room_id, "room_id")
    for room in list_rooms():
        if room["id"] == room_id:
            return room
    return None


def create_room(name: str, topic: str = "", linked_book_id: Optional[str] = None,
                participants: Optional[List[str]] = None) -> dict:
    """Create and persist a new room."""
    rooms = list_rooms()
    room = {
        "id": _gen_id(),
        "name": name,
        "topic": topic,
        "linked_book_id": linked_book_id,
        "participants": participants or [],
        "created_at": _now_iso(),
    }
    rooms.append(room)
    write_json(ROOMS_FILE, rooms)
    return room


def update_room(room_id: str, updates: dict) -> Optional[dict]:
    """Update room fields. Returns updated room or None if not found."""
    _validate_id(room_id, "room_id")
    rooms = list_rooms()
    for i, room in enumerate(rooms):
        if room["id"] == room_id:
            room.update(updates)
            rooms[i] = room
            write_json(ROOMS_FILE, rooms)
            return room
    return None


def delete_room(room_id: str) -> None:
    """Delete a room and its message/pin data."""
    _validate_id(room_id, "room_id")
    rooms = [r for r in list_rooms() if r["id"] != room_id]
    write_json(ROOMS_FILE, rooms)
    # Clean up room data directory
    room_dir = DATA_DIR / "rooms" / room_id
    if room_dir.exists():
        import shutil
        shutil.rmtree(room_dir)


# ── Message persistence ──────────────────────────────────────────────────

def _messages_path(room_id: str) -> Path:
    _validate_id(room_id, "room_id")
    return DATA_DIR / "rooms" / room_id / "messages.jsonl"


def list_messages(room_id: str, limit: int = 50, before: Optional[str] = None) -> List[dict]:
    """Return messages for a room, newest last. Supports cursor pagination."""
    messages = read_jsonl(_messages_path(room_id))
    if before:
        # Filter to messages before the cursor timestamp
        messages = [m for m in messages if m.get("ts", "") < before]
    # Return last N messages (oldest first for display)
    return messages[-limit:]


def save_message(room_id: str, user: str, content: str, msg_type: str = "user",
                 model: Optional[str] = None) -> dict:
    """Append a message to the room's JSONL log."""
    msg = {
        "id": _gen_id(),
        "room_id": room_id,
        "user": user,
        "content": content,
        "msg_type": msg_type,
        "model": model,
        "ts": _now_iso(),
    }
    append_jsonl(_messages_path(room_id), msg)
    return msg


# ── Pin persistence ──────────────────────────────────────────────────────

def _pins_path(room_id: str) -> Path:
    _validate_id(room_id, "room_id")
    return DATA_DIR / "rooms" / room_id / "pins.json"


def list_pins(room_id: str) -> List[dict]:
    """Return pinned message IDs and content for a room."""
    return read_json(_pins_path(room_id), default=[])


def add_pin(room_id: str, message: dict) -> List[dict]:
    """Pin a message. Stores the full message object."""
    pins = list_pins(room_id)
    if any(p["id"] == message["id"] for p in pins):
        return pins
    pins.append(message)
    write_json(_pins_path(room_id), pins)
    return pins


def remove_pin(room_id: str, message_id: str) -> List[dict]:
    """Unpin a message."""
    pins = [p for p in list_pins(room_id) if p["id"] != message_id]
    write_json(_pins_path(room_id), pins)
    return pins


def export_room_markdown(room_id: str) -> str:
    """Export room chat history as markdown."""
    room = get_room(room_id)
    name = room["name"] if room else room_id
    messages = read_jsonl(_messages_path(room_id))
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


# ── Journal persistence ──────────────────────────────────────────────────

JOURNAL_FILE = DATA_DIR / "journal.jsonl"


def list_journal_entries() -> List[dict]:
    """Return all journal entries."""
    return read_jsonl(JOURNAL_FILE)


def save_journal_entry(user: str, entry: dict) -> dict:
    """Save a new journal entry."""
    record = {
        "id": _gen_id(),
        "user": user,
        **entry,
        "created_at": _now_iso(),
    }
    append_jsonl(JOURNAL_FILE, record)
    return record


def update_journal_entry(entry_id: str, updates: dict) -> Optional[dict]:
    """Update a journal entry. Rewrites JSONL atomically."""
    entries = list_journal_entries()
    target = None
    for entry in entries:
        if entry.get("id") == entry_id:
            entry.update(updates)
            entry["updated_at"] = _now_iso()
            target = entry
    if target is None:
        return None
    _ensure_dir(JOURNAL_FILE.parent)
    tmp = JOURNAL_FILE.with_suffix(".tmp")
    with open(JOURNAL_FILE, "r") as rf:
        fcntl.flock(rf, fcntl.LOCK_EX)
        try:
            with open(tmp, "w") as wf:
                for entry in entries:
                    wf.write(json.dumps(entry, separators=(",", ":")) + "\n")
                wf.flush()
                os.fsync(wf.fileno())
            os.replace(str(tmp), str(JOURNAL_FILE))
        finally:
            fcntl.flock(rf, fcntl.LOCK_UN)
    return target


# ── Prediction persistence ───────────────────────────────────────────────

PREDICTIONS_FILE = DATA_DIR / "predictions.jsonl"


def list_predictions() -> List[dict]:
    """Return all predictions."""
    return read_jsonl(PREDICTIONS_FILE)


def save_prediction(user: str, prediction: dict) -> dict:
    """Save a new prediction."""
    record = {
        "id": _gen_id(),
        "user": user,
        **prediction,
        "resolution": None,
        "resolved_at": None,
        "created_at": _now_iso(),
    }
    append_jsonl(PREDICTIONS_FILE, record)
    return record


# ── TradingView event log ────────────────────────────────────────────────

TV_EVENTS_FILE = DATA_DIR / "tradingview-events.jsonl"


def save_tv_event(
    *,
    result: str,
    book_id: Optional[str] = None,
    binding_id: Optional[str] = None,
    node_id: Optional[str] = None,
    op: Optional[str] = None,
    new_value: Any = None,
    detail: Optional[str] = None,
    source_ip: Optional[str] = None,
) -> dict:
    """Append a single TradingView webhook event to the audit log.

    WHY jsonl: matches the project-wide append-log convention (predictions,
    journal, messages). Every webhook call — success, auth failure, rate
    limit — lands here, so an operator can reconstruct the full sequence
    from a single file. `result` is the VerifyResult enum value or "ok".
    """
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
    append_jsonl(TV_EVENTS_FILE, record)
    return record


def list_tv_events(*, limit: int = 50,
                   book_id: Optional[str] = None) -> List[dict]:
    """Return the most recent TradingView events, newest first.

    Optional book_id filter narrows the feed to a single thesis.
    """
    events = read_jsonl(TV_EVENTS_FILE)
    if book_id:
        events = [e for e in events if e.get("bookId") == book_id]
    # Newest first — file is append-only so tail is newest
    return list(reversed(events[-limit:]))


def resolve_prediction(prediction_id: str, resolution: str) -> Optional[dict]:
    """Resolve a prediction. Atomic read-modify-write under exclusive lock."""
    _ensure_dir(PREDICTIONS_FILE.parent)
    if not PREDICTIONS_FILE.exists():
        return None
    tmp = PREDICTIONS_FILE.with_suffix(".tmp")
    target = None
    # WHY: Single exclusive lock covers both read and write to prevent
    # concurrent appends from being lost between the two operations.
    with open(PREDICTIONS_FILE, "r") as rf:
        fcntl.flock(rf, fcntl.LOCK_EX)
        try:
            predictions = []
            for line in rf:
                line = line.strip()
                if line:
                    try:
                        predictions.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning("Skipping malformed prediction line: %r", line)
            for p in predictions:
                if p.get("id") == prediction_id:
                    p["resolution"] = resolution
                    p["resolved_at"] = _now_iso()
                    target = p
            if target is None:
                return None
            with open(tmp, "w") as wf:
                for p in predictions:
                    wf.write(json.dumps(p, separators=(",", ":")) + "\n")
                wf.flush()
                os.fsync(wf.fileno())
            os.replace(str(tmp), str(PREDICTIONS_FILE))
        finally:
            fcntl.flock(rf, fcntl.LOCK_UN)
    return target
