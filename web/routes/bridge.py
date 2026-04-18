"""
Bridge / outbox status + replay endpoints.

WHY: When the dialectic push pipeline can't reach the server (outage,
auth blip, network), snapshots spool to `snapshots/outbox/` and replay
on the next run. Operators need a way to see "is anything stuck?" without
shelling into the droplet — the dashboard surfaces this via a top-bar
badge backed by GET /api/bridge/outbox, and a "drain now" button backed
by POST /api/bridge/outbox/replay so they don't have to wait for cron
once dialectic recovers.

Filename parsing is delegated to push_to_dialectic.parse_outbox_filename
so the format lives in one place.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from web.auth import get_current_user
from web.models import User


router = APIRouter(prefix="/api/bridge", tags=["bridge"])


# WHY: push_to_dialectic.py uses a hyphen-free filename and is a CLI tool
# in tools/bridge/, not a package. Load it once at import time so the
# endpoint doesn't pay subprocess/import overhead on every request.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PUSH_PATH = _REPO_ROOT / "tools" / "bridge" / "push_to_dialectic.py"


def _load_push_module():
    """Import tools/bridge/push_to_dialectic.py as a module.

    WHY a helper: tests can monkeypatch this to inject a stub, and we keep
    the side-effecting importlib dance out of module top-level so a missing
    file at import time doesn't break the whole web app.
    """
    if "push_to_dialectic" in sys.modules:
        return sys.modules["push_to_dialectic"]
    spec = importlib.util.spec_from_file_location(
        "push_to_dialectic", str(_PUSH_PATH),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_PUSH_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["push_to_dialectic"] = mod
    spec.loader.exec_module(mod)
    return mod


class OutboxStatus(BaseModel):
    """Aggregate state of the snapshot retry queue."""
    queued: int
    byRoom: dict[str, int]
    oldest: Optional[str]   # ISO 8601 UTC, or null if empty
    newest: Optional[str]
    totalBytes: int
    replayCap: int


def _scan_outbox_sync() -> OutboxStatus:
    """Blocking scan of the outbox directory. Wrapped by the route handler."""
    push_mod = _load_push_module()
    outbox: Path = push_mod._outbox_path()
    cap: int = push_mod._resolve_replay_cap()

    if not outbox.is_dir():
        return OutboxStatus(
            queued=0, byRoom={}, oldest=None, newest=None,
            totalBytes=0, replayCap=cap,
        )

    by_room: dict[str, int] = {}
    timestamps: list[str] = []
    total_bytes = 0
    queued = 0

    for path in outbox.glob("*.json"):
        parsed = push_mod.parse_outbox_filename(path.name)
        if not parsed:
            # WHY: silently skip files that don't match the convention --
            # could be a stale temp file, a manual paste, etc. Surfacing them
            # would noise up the badge without operator action.
            continue
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
        room = parsed["room"]
        by_room[room] = by_room.get(room, 0) + 1
        timestamps.append(parsed["ts"])
        queued += 1

    timestamps.sort()
    return OutboxStatus(
        queued=queued,
        byRoom=by_room,
        oldest=timestamps[0] if timestamps else None,
        newest=timestamps[-1] if timestamps else None,
        totalBytes=total_bytes,
        replayCap=cap,
    )


@router.get("/outbox", response_model=OutboxStatus)
async def get_outbox_status(
    _user: User = Depends(get_current_user),
) -> OutboxStatus:
    """Return outbox queue summary.

    Empty outbox returns `{queued: 0, byRoom: {}, oldest: null, newest: null,
    totalBytes: 0, replayCap: <cap>}` -- never 404; the badge code distinguishes
    between "loaded and empty" and "failed to load".
    """
    return await asyncio.to_thread(_scan_outbox_sync)


# =========================================================================
# DRAIN NOW — manual outbox replay
#
# WHY: The cron-driven `run-all.py` tick replays the outbox before each
# fresh push, but operators frequently know dialectic has just recovered
# and don't want to wait for the next tick (default Mon/Wed/Fri 08:00).
# This endpoint exposes the same replay machinery via a button on the
# OutboxBadge popover. The endpoint is JWT-gated since it both consumes
# the room token and triggers outbound network IO.
# =========================================================================


_BOOKS_DIR = _REPO_ROOT / "books"


class ReplayRequest(BaseModel):
    """Optional body for the replay endpoint.

    `roomId` omitted -> drain every room with queued spools. Provided ->
    drain only that one room (no error if it has nothing queued).
    """
    roomId: Optional[str] = None


class PerRoomResult(BaseModel):
    roomId: str
    replayed: int
    remaining: int
    errors: list[str]


class ReplayResponse(BaseModel):
    replayed: int
    remaining: int
    perRoom: list[PerRoomResult]
    dialecticUrl: str
    durationMs: int


def _resolve_dialectic_url() -> str:
    """Reuse the same env knob run-all.py already honors, default localhost."""
    return os.environ.get("DIALECTIC_URL", "http://localhost:8002").strip() \
        or "http://localhost:8002"


def _load_book_tokens() -> dict[str, str]:
    """Map dialecticRoomId -> dialecticRoomToken from books/*.json.

    WHY lazy + per-call: there are only 2 books today and operators rarely
    drain (this fires on a button click, not in a hot loop). Caching would
    add stale-token risk for negligible payoff.
    """
    tokens: dict[str, str] = {}
    if not _BOOKS_DIR.is_dir():
        return tokens
    for path in _BOOKS_DIR.glob("*.json"):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta", {}) or {}
        room_id = meta.get("dialecticRoomId")
        room_tok = meta.get("dialecticRoomToken")
        if room_id and room_tok:
            tokens[room_id] = room_tok
    return tokens


def _discover_queued_rooms() -> list[str]:
    """Scan the outbox dir and return the unique set of room IDs with spools."""
    push_mod = _load_push_module()
    outbox: Path = push_mod._outbox_path()
    if not outbox.is_dir():
        return []
    rooms: set[str] = set()
    for p in outbox.glob("*.json"):
        parsed = push_mod.parse_outbox_filename(p.name)
        if parsed:
            rooms.add(parsed["room"])
    # Stable ordering -> deterministic per-room result list for the UI.
    return sorted(rooms)


def _count_remaining(room_id: str) -> int:
    """Count spools still queued for a room after a replay attempt."""
    push_mod = _load_push_module()
    return len(push_mod.list_outbox(room_id))


def _replay_sync(room_filter: Optional[str]) -> ReplayResponse:
    """Blocking drain. Wrapped in to_thread by the route handler.

    Per-room loop:
      1. Resolve token (book meta -> env fallback).
      2. Call push_mod.replay_outbox(url, room, token).
      3. Re-count remaining spools to surface partial-failure state.

    Errors don't bubble out — they land in the per-room `errors` list and
    the response is still 200, because the operator deserves to see which
    rooms drained vs. which are still stuck.
    """
    push_mod = _load_push_module()
    dialectic_url = _resolve_dialectic_url()
    cap = push_mod._resolve_replay_cap()
    book_tokens = _load_book_tokens()
    env_token = os.environ.get("DIALECTIC_ROOM_TOKEN", "").strip()

    if room_filter:
        target_rooms = [room_filter]
    else:
        target_rooms = _discover_queued_rooms()

    started = time.monotonic()
    per_room: list[PerRoomResult] = []
    total_replayed = 0

    for room in target_rooms:
        errors: list[str] = []
        token = book_tokens.get(room) or env_token
        replayed = 0
        if not token:
            # WHY no token: the spools stay queued; the operator sees a clear
            # error in the UI rather than a 500. Common cause: rotating env
            # without restarting the FastAPI process.
            errors.append("no DIALECTIC_ROOM_TOKEN configured for this room")
        else:
            try:
                # replay_outbox returns (success_count, failure_count).
                # failure_count is 0 or 1 (replay halts on first failure to
                # preserve ordering). Anything halted stays in the spool dir
                # and shows up in the remaining count below.
                replayed, failures = push_mod.replay_outbox(
                    dialectic_url, room, token, max_per_run=cap,
                )
                if failures:
                    errors.append(
                        "replay halted on a queued spool — dialectic likely "
                        "unreachable; remaining spools stay queued for the "
                        "next attempt"
                    )
            except Exception as exc:  # noqa: BLE001 -- surface any fault
                errors.append(f"{type(exc).__name__}: {exc}")

        remaining = _count_remaining(room)
        total_replayed += replayed
        per_room.append(PerRoomResult(
            roomId=room,
            replayed=replayed,
            remaining=remaining,
            errors=errors,
        ))

    total_remaining = sum(r.remaining for r in per_room)
    duration_ms = int((time.monotonic() - started) * 1000)
    return ReplayResponse(
        replayed=total_replayed,
        remaining=total_remaining,
        perRoom=per_room,
        dialecticUrl=dialectic_url,
        durationMs=duration_ms,
    )


@router.post("/outbox/replay", response_model=ReplayResponse)
async def replay_outbox_endpoint(
    body: Optional[ReplayRequest] = None,
    _user: User = Depends(get_current_user),
) -> ReplayResponse:
    """Manually drain queued snapshots from the dialectic outbox.

    Empty outbox returns 200 with zeros (idempotent).
    Dialectic unreachable returns 200 with `errors` populated and
    `remaining > 0` -- the operator sees the partial result instead of
    a generic 5xx.
    """
    room_filter = body.roomId if body else None
    return await asyncio.to_thread(_replay_sync, room_filter)
