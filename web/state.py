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
    """Write a JSON file with exclusive lock."""
    _ensure_dir(path.parent)
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
            f.write("\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


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
    for room in list_rooms():
        if room["id"] == room_id:
            return room
    return None


def create_room(name: str, topic: str = "", linked_book_id: Optional[str] = None) -> dict:
    """Create and persist a new room."""
    rooms = list_rooms()
    room = {
        "id": _gen_id(),
        "name": name,
        "topic": topic,
        "linked_book_id": linked_book_id,
        "participants": [],
        "created_at": _now_iso(),
    }
    rooms.append(room)
    write_json(ROOMS_FILE, rooms)
    return room


def update_room(room_id: str, updates: dict) -> Optional[dict]:
    """Update room fields. Returns updated room or None if not found."""
    rooms = list_rooms()
    for i, room in enumerate(rooms):
        if room["id"] == room_id:
            room.update(updates)
            rooms[i] = room
            write_json(ROOMS_FILE, rooms)
            return room
    return None


# ── Message persistence ──────────────────────────────────────────────────

def _messages_path(room_id: str) -> Path:
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
    from datetime import datetime
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


def resolve_prediction(prediction_id: str, resolution: str) -> Optional[dict]:
    """Resolve a prediction. Rewrites the JSONL file with the updated record."""
    predictions = list_predictions()
    target = None
    for p in predictions:
        if p["id"] == prediction_id:
            p["resolution"] = resolution
            p["resolved_at"] = _now_iso()
            target = p
    if target is None:
        return None
    # WHY: JSONL rewrite — predictions list is small (dozens, not thousands).
    _ensure_dir(PREDICTIONS_FILE.parent)
    with open(PREDICTIONS_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            for p in predictions:
                f.write(json.dumps(p, separators=(",", ":")) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return target
