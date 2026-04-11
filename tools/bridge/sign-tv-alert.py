#!/usr/bin/env python3
"""
Sign a TradingView webhook body and print curl-ready headers.

WHY this exists: the web/api/tradingview/webhook endpoint expects
HMAC-SHA256 signed requests. Pine Script on TradingView cannot compute
HMAC in-language, so operators use this helper to pre-compute signature +
timestamp + nonce for specific alert bodies. Output is a ready-to-paste
curl invocation you can use to test bindings or drive programmatic
integrations (a local relay, a cron watcher, a CI smoke test).

Usage:
    # Read body from stdin
    echo '{"book":"iran-hormuz-graph","bindingId":"brent-persistence-close-above-115"}' | \\
        python3 tools/bridge/sign-tv-alert.py

    # Read body from a file
    python3 tools/bridge/sign-tv-alert.py --body alert.json

    # Inline body + custom URL
    python3 tools/bridge/sign-tv-alert.py \\
        --book iran-hormuz-graph \\
        --binding brent-persistence-close-above-115 \\
        --url https://tradingdesk.internal/api/tradingview/webhook

Environment:
    TV_WEBHOOK_SECRET — required, must match the webapp's env var.

Stdlib only. No pip deps.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from typing import Any


def _read_body(args: argparse.Namespace) -> bytes:
    """Build the request body bytes from CLI args or stdin."""
    if args.body:
        return open(args.body, "rb").read().strip()
    if args.book and args.binding:
        payload: dict[str, Any] = {
            "book": args.book,
            "bindingId": args.binding,
        }
        if args.value is not None:
            payload["value"] = args.value
        if args.pine_alert_name:
            payload["pineAlertName"] = args.pine_alert_name
        if args.chart_symbol:
            payload["chartSymbol"] = args.chart_symbol
        return json.dumps(payload, separators=(",", ":")).encode()
    # Fall back to stdin
    if sys.stdin.isatty():
        print(
            "Error: no body on stdin and no --body / --book+--binding flags",
            file=sys.stderr,
        )
        sys.exit(2)
    return sys.stdin.read().strip().encode()


def _sign(body: bytes, secret: str) -> str:
    import hashlib
    import hmac

    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sign a TradingView webhook body and print curl-ready headers. "
            "Reads TV_WEBHOOK_SECRET from the environment."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes: 0 = signed ok, 2 = bad input, 3 = secret missing"
        ),
    )
    parser.add_argument("--body", help="Path to a JSON file containing the body")
    parser.add_argument("--book", help="Book id (e.g. iran-hormuz-graph)")
    parser.add_argument("--binding", help="Binding id (e.g. brent-persistence-close-above-115)")
    parser.add_argument("--value", type=float,
                        help="Numeric value (for setProbability / setCurrent bindings)")
    parser.add_argument("--pine-alert-name", help="Optional pineAlertName field")
    parser.add_argument("--chart-symbol", help="Optional chartSymbol field")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/tradingview/webhook",
                        help="Target webhook URL (default localhost:8000)")
    parser.add_argument("--timestamp", type=int, default=None,
                        help="Unix seconds. Defaults to now.")
    parser.add_argument("--nonce", default=None,
                        help="Nonce string (>= 8 chars). Defaults to a fresh 16-byte random.")
    parser.add_argument("--format", choices=("curl", "headers", "json"), default="curl",
                        help="Output format: 'curl' prints a ready-to-paste command, "
                             "'headers' prints one header per line, 'json' prints a "
                             "machine-readable dict. Default: curl.")
    args = parser.parse_args()

    secret = os.environ.get("TV_WEBHOOK_SECRET")
    if not secret:
        print("Error: TV_WEBHOOK_SECRET is not set", file=sys.stderr)
        return 3

    body = _read_body(args)
    if not body:
        print("Error: empty body", file=sys.stderr)
        return 2

    timestamp = args.timestamp if args.timestamp is not None else int(time.time())
    nonce = args.nonce or secrets.token_hex(16)  # 32 hex chars

    signature = _sign(body, secret)

    if args.format == "json":
        out = {
            "url": args.url,
            "body": body.decode(),
            "headers": {
                "Content-Type": "application/json",
                "X-TV-Signature": signature,
                "X-TV-Timestamp": str(timestamp),
                "X-TV-Nonce": nonce,
            },
        }
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.format == "headers":
        print(f"Content-Type: application/json")
        print(f"X-TV-Signature: {signature}")
        print(f"X-TV-Timestamp: {timestamp}")
        print(f"X-TV-Nonce: {nonce}")
        return 0

    # Default: curl invocation
    body_str = body.decode()
    # Single-quote the body for shell safety; escape any single quotes inside
    body_escaped = body_str.replace("'", "'\\''")
    print(
        f"curl -X POST {args.url} \\\n"
        f'  -H "Content-Type: application/json" \\\n'
        f'  -H "X-TV-Signature: {signature}" \\\n'
        f'  -H "X-TV-Timestamp: {timestamp}" \\\n'
        f'  -H "X-TV-Nonce: {nonce}" \\\n'
        f"  -d '{body_escaped}'"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
