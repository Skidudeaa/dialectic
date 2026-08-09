#!/usr/bin/env python3
"""
Push to Dialectic -- bridge script that POSTs a thesis graph snapshot
to a Dialectic trading room endpoint.

Reads a snapshot JSON (from thesisgraph.py --export-state) and pushes it
to a Dialectic trading room via the REST API. The room token is read from
the DIALECTIC_ROOM_TOKEN environment variable (not a CLI argument, for
security -- treat it as a secret that grants full room access: read/write
messages, memories, analytics).

Usage:
    # Push a snapshot file
    python3 push-to-dialectic.py --snapshot snap.json --room-id <uuid>

    # Push from stdin (piped from thesisgraph.py)
    thesisgraph.py --fetch --export-state - | \
        python3 push-to-dialectic.py --snapshot - --room-id <uuid>

    # Custom Dialectic URL
    python3 push-to-dialectic.py --snapshot snap.json --room-id <uuid> \
        --dialectic-url https://dialectic.example.com

Exit codes:
    0 -- success (prints response JSON to stdout)
    1 -- HTTP error (prints status code + response body)
    2 -- connection error or missing configuration
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# =========================================================================
# SECURITY CHECKS
# =========================================================================

def get_room_token() -> str:
    """Read DIALECTIC_ROOM_TOKEN from environment. Exit 2 if missing."""
    token = os.environ.get("DIALECTIC_ROOM_TOKEN", "").strip()
    if not token:
        print(
            "Error: DIALECTIC_ROOM_TOKEN environment variable is not set.\n"
            "Set it with: export DIALECTIC_ROOM_TOKEN=<your-room-token>\n"
            "This token grants full room access -- treat it as a secret.",
            file=sys.stderr,
        )
        sys.exit(2)
    return token


def check_transport_security(url: str) -> None:
    """Warn if transmitting token over unencrypted HTTP to a remote host."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    scheme = (parsed.scheme or "").lower()

    is_local = hostname in ("localhost", "127.0.0.1", "::1")
    is_https = scheme == "https"

    if not is_local and not is_https:
        print(
            f"WARNING: Transmitting room token over unencrypted HTTP to {hostname}.\n"
            "The DIALECTIC_ROOM_TOKEN will be visible to network observers.\n"
            "Use --dialectic-url with an https:// URL for remote servers.",
            file=sys.stderr,
        )


# =========================================================================
# SNAPSHOT LOADING
# =========================================================================

def load_snapshot(source: str) -> bytes:
    """
    Load snapshot JSON from a file path or stdin ('-').
    Returns raw bytes suitable for POST body.
    Validates that the content is parseable JSON.
    """
    if source == "-":
        raw = sys.stdin.buffer.read()
    else:
        try:
            with open(source, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            print(f"Error: snapshot file not found: {source}", file=sys.stderr)
            sys.exit(2)
        except OSError as e:
            print(f"Error: cannot read snapshot file: {e}", file=sys.stderr)
            sys.exit(2)

    if not raw.strip():
        print("Error: snapshot is empty.", file=sys.stderr)
        sys.exit(2)

    # Validate JSON before sending
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: snapshot is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)

    return raw


# =========================================================================
# HTTP POST
# =========================================================================

# =========================================================================
# OUTBOX (durable retry across cron invocations)
#
# WHY: The 3-attempt in-process retry handles 1-2s blips. It does NOT handle
# a 30-minute Dialectic outage during a cron run. Without an outbox, that
# snapshot is permanently lost (next cron is hours/days away). The outbox
# pattern: on failure, spool the payload to disk; on the next push for the
# same room, replay everything in the spool (oldest first) before sending
# the new payload. Idempotent on the dialectic side (memory upserts by
# stable key, snapshots dedupe by content hash).
# =========================================================================

OUTBOX_DIR = Path(__file__).resolve().parent.parent.parent / "snapshots" / "outbox"

# WHY: 500 is the sweet spot — large enough to drain a multi-day outage in one
# pass (10 books × 3 cron runs/day × ~16 days), small enough to prevent a
# single run from monopolizing the dialectic API after a really bad incident.
# Override via env if your topology shifts. Unlimited is intentionally not
# offered — backstop matters; a runaway replay should fail loud, not silent.
DEFAULT_REPLAY_CAP = 500


def _resolve_replay_cap(explicit: Optional[int] = None) -> int:
    """Resolve the per-run replay cap.

    Precedence: explicit kwarg > $BRIDGE_OUTBOX_REPLAY_CAP > DEFAULT_REPLAY_CAP.
    Invalid env values fall back to the default with a stderr warning rather
    than crashing — replay should never be the thing that breaks a cron run.
    """
    if explicit is not None:
        return explicit
    raw = os.environ.get("BRIDGE_OUTBOX_REPLAY_CAP", "").strip()
    if not raw:
        return DEFAULT_REPLAY_CAP
    try:
        val = int(raw)
        if val <= 0:
            raise ValueError("must be positive")
        return val
    except ValueError as e:
        print(f"[outbox] invalid BRIDGE_OUTBOX_REPLAY_CAP={raw!r} ({e}); "
              f"using default {DEFAULT_REPLAY_CAP}", file=sys.stderr)
        return DEFAULT_REPLAY_CAP


# WHY: Filename convention is {timestamp}__{room_id}__{hash}.json. The
# timestamp uses the format `%Y%m%dT%H%M%S` + 6-digit microseconds + 'Z'.
# Centralized here so the web/routes/bridge.py status endpoint can DRY-import
# the parser instead of duplicating the regex.
_OUTBOX_FILENAME_RE = re.compile(
    r"^(?P<ts>\d{8}T\d{6}\d{6}Z)__(?P<room>.+?)__(?P<hash>[0-9a-f]+)\.json$"
)


def parse_outbox_filename(name: str) -> Optional[dict]:
    """Parse a spool filename into {ts, room, hash} or None if non-matching.

    `ts` is returned as an ISO-8601 UTC string (e.g. "2026-04-17T12:34:56.789012Z")
    so callers can sort or display it without re-parsing the compact form.
    """
    m = _OUTBOX_FILENAME_RE.match(name)
    if not m:
        return None
    raw_ts = m.group("ts")  # 20260417T123456789012Z
    # Reformat compact ts -> ISO 8601 with microseconds.
    try:
        date_part = raw_ts[0:8]   # 20260417
        time_part = raw_ts[9:15]  # 123456
        usec = raw_ts[15:21]      # 789012
        iso = (f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}T"
               f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}.{usec}Z")
    except IndexError:
        return None
    return {"ts": iso, "room": m.group("room"), "hash": m.group("hash")}


def _outbox_path() -> Path:
    """Resolve outbox dir at call-time (tests can monkeypatch OUTBOX_DIR)."""
    return OUTBOX_DIR


def _payload_hash(payload: bytes) -> str:
    """Short stable digest for outbox filename + dedupe."""
    return hashlib.sha256(payload).hexdigest()[:16]


def spool_to_outbox(room_id: str, payload: bytes,
                    reason: str = "push-failed") -> Optional[Path]:
    """
    Persist a failed push to the outbox so a later run can retry it.

    Filename: {timestamp}__{room_id}__{hash}.json -- chronological sort gives
    natural FIFO replay order, hash collapses duplicate spools (same payload
    spooled twice during a long outage = one file).

    Returns the spool path on success, None if the outbox can't be written
    (then the caller still surfaces the original error and exits non-zero).
    """
    outbox = _outbox_path()
    try:
        outbox.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[outbox] cannot create {outbox}: {e}", file=sys.stderr)
        return None

    digest = _payload_hash(payload)
    # Look for an existing spool with the same room+hash — collapse duplicates.
    for existing in outbox.glob(f"*__{room_id}__{digest}.json"):
        print(f"[outbox] duplicate spool already queued: {existing.name}",
              file=sys.stderr)
        return existing

    # WHY microsecond suffix: two spools issued in the same second (test
    # bursts, rapid retry storms) need stable FIFO ordering. The microsecond
    # tick keeps lexical sort = chronological sort even under sub-second bursts.
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond:06d}Z"
    path = outbox / f"{ts}__{room_id}__{digest}.json"
    try:
        path.write_bytes(payload)
        print(f"[outbox] spooled {path.name} ({reason})", file=sys.stderr)
        return path
    except OSError as e:
        print(f"[outbox] cannot write {path}: {e}", file=sys.stderr)
        return None


def list_outbox(room_id: Optional[str] = None) -> list[Path]:
    """Return outbox spools (optionally filtered by room) in FIFO order."""
    outbox = _outbox_path()
    if not outbox.is_dir():
        return []
    if room_id:
        spools = list(outbox.glob(f"*__{room_id}__*.json"))
    else:
        spools = list(outbox.glob("*.json"))
    return sorted(spools)  # filename is timestamp-prefixed -> chronological


def replay_outbox(dialectic_url: str, room_id: str, token: str,
                  max_per_run: Optional[int] = None) -> tuple[int, int]:
    """
    Replay queued spools for this room. Stops on first failure to preserve
    ordering -- a transient blip during replay leaves the rest queued for
    the next run instead of partially draining.

    `max_per_run` defaults to $BRIDGE_OUTBOX_REPLAY_CAP (or 500 if unset).
    Pass an explicit int to override for a single call (tests, manual drain).

    Returns (success_count, failure_count). Caller decides how to handle
    failures (typically: log, then proceed with the fresh payload).
    """
    cap = _resolve_replay_cap(max_per_run)
    spools = list_outbox(room_id)[:cap]
    if not spools:
        return (0, 0)

    print(f"[outbox] replaying {len(spools)} queued snapshot(s) for room "
          f"{room_id}", file=sys.stderr)
    successes = 0
    for spool in spools:
        try:
            payload = spool.read_bytes()
        except OSError as e:
            print(f"[outbox] cannot read {spool.name}: {e}", file=sys.stderr)
            return (successes, 1)
        rc = _attempt_push(dialectic_url, room_id, token, payload,
                           max_attempts=2, label=f"replay {spool.name}")
        if rc != 0:
            print(f"[outbox] replay halted at {spool.name} (rc={rc}); "
                  "remaining spools stay queued", file=sys.stderr)
            return (successes, 1)
        try:
            spool.unlink()
        except OSError:
            pass
        successes += 1
    return (successes, 0)


# =========================================================================
# HTTP POST
# =========================================================================

def _attempt_push(dialectic_url: str, room_id: str, token: str, payload: bytes,
                  max_attempts: int = 3, label: str = "push") -> int:
    """
    Single push attempt loop. Returns 0 on success, 1 on 4xx, 1 on 5xx after
    retries exhausted, 2 on connection error after retries exhausted.

    WHY split out from push_snapshot: replay_outbox calls this without
    sys.exit so partial failure doesn't kill the whole run.
    """
    url = f"{dialectic_url.rstrip('/')}/rooms/{room_id}/trading/snapshot"

    for attempt in range(1, max_attempts + 1):
        req = Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "tradingDesk-bridge/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if label == "push":
                    try:
                        parsed = json.loads(body)
                        print(json.dumps(parsed, indent=2, ensure_ascii=False))
                    except json.JSONDecodeError:
                        print(body)
                else:
                    print(f"[outbox] {label}: ok", file=sys.stderr)
                return 0
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if e.code < 500:
                print(f"[{label}] HTTP {e.code}: {e.reason}", file=sys.stderr)
                if body:
                    print(body, file=sys.stderr)
                return 1
            if attempt < max_attempts:
                wait = 2 ** (attempt - 1)
                print(f"[{label}] HTTP {e.code} (attempt {attempt}/{max_attempts}), "
                      f"retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[{label}] HTTP {e.code}: {e.reason} (failed after "
                  f"{max_attempts} attempts)", file=sys.stderr)
            if body:
                print(body, file=sys.stderr)
            return 1
        except (URLError, TimeoutError, OSError) as e:
            if attempt < max_attempts:
                wait = 2 ** (attempt - 1)
                print(f"[{label}] connection error (attempt {attempt}/{max_attempts}): "
                      f"{e}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[{label}] connection error: {e} (failed after "
                  f"{max_attempts} attempts)", file=sys.stderr)
            return 2
    return 2


def push_snapshot(dialectic_url: str, room_id: str, token: str, payload: bytes,
                  max_attempts: int = 3) -> None:
    """
    POST the snapshot JSON to the Dialectic trading snapshot endpoint.
    Retries on transient failures (5xx, connection errors) with exponential
    backoff. On terminal failure, spools to OUTBOX_DIR for the next run.
    Sets exit code via sys.exit().

    WHY outbox: a 30-min Dialectic outage during cron must not lose data.
    The next push for this room replays the spool before sending fresh.
    """
    # Replay any spooled snapshots first (FIFO), so chronological ordering
    # in dialectic's events table reflects when the data actually arrived.
    replay_outbox(dialectic_url, room_id, token)

    rc = _attempt_push(dialectic_url, room_id, token, payload, max_attempts)
    if rc == 0:
        sys.exit(0)
    # Push failed terminally — spool for retry on next run.
    spool_to_outbox(room_id, payload,
                    reason=f"push exit {rc} after {max_attempts} attempts")
    sys.exit(rc)


# =========================================================================
# CLI
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated for testability."""
    parser = argparse.ArgumentParser(
        description="Push a thesis graph snapshot to a Dialectic trading room.",
        epilog=(
            "Exit codes: 0 = success, 1 = HTTP error, 2 = connection/config error.\n"
            "The room token is read from DIALECTIC_ROOM_TOKEN env var (not a CLI arg)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--snapshot",
        required=True,
        metavar="FILE",
        help="Path to the snapshot JSON file, or '-' to read from stdin",
    )
    parser.add_argument(
        "--room-id",
        required=True,
        metavar="UUID",
        help="Dialectic room ID (UUID)",
    )
    parser.add_argument(
        "--dialectic-url",
        default="http://localhost:8002",
        metavar="URL",
        help="Dialectic server URL (default: http://localhost:8002)",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 1. Get token from environment
    token = get_room_token()

    # 2. Check transport security
    check_transport_security(args.dialectic_url)

    # 3. Load and validate snapshot
    payload = load_snapshot(args.snapshot)

    # 4. Push to Dialectic
    push_snapshot(args.dialectic_url, args.room_id, token, payload)


if __name__ == "__main__":
    main()
