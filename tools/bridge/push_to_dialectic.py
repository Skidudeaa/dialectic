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
import json
import os
import sys
import time
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

def push_snapshot(dialectic_url: str, room_id: str, token: str, payload: bytes,
                  max_attempts: int = 3) -> None:
    """
    POST the snapshot JSON to the Dialectic trading snapshot endpoint.
    Retries on transient failures (5xx, connection errors) with exponential backoff.
    Prints response on success, error details on failure.
    Sets exit code via sys.exit().

    WHY: The push is the final pipeline step — a transient Dialectic blip should
    not silently drop a snapshot. 4xx errors are not retried (client error).
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
                try:
                    parsed = json.loads(body)
                    print(json.dumps(parsed, indent=2, ensure_ascii=False))
                except json.JSONDecodeError:
                    print(body)
                sys.exit(0)
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if e.code < 500:
                # 4xx — client error, not retryable
                print(f"HTTP {e.code}: {e.reason}", file=sys.stderr)
                if body:
                    print(body, file=sys.stderr)
                sys.exit(1)
            # 5xx — server error, retryable
            if attempt < max_attempts:
                wait = 2 ** (attempt - 1)  # 1s, 2s
                print(f"HTTP {e.code} (attempt {attempt}/{max_attempts}), "
                      f"retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"HTTP {e.code}: {e.reason} (failed after {max_attempts} attempts)",
                  file=sys.stderr)
            if body:
                print(body, file=sys.stderr)
            sys.exit(1)
        except (URLError, TimeoutError, OSError) as e:
            if attempt < max_attempts:
                wait = 2 ** (attempt - 1)
                print(f"Connection error (attempt {attempt}/{max_attempts}): {e}, "
                      f"retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"Connection error: {e} (failed after {max_attempts} attempts)",
                  file=sys.stderr)
            sys.exit(2)


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
