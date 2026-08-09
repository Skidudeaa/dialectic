#!/usr/bin/env python3
"""
Dialectic Client -- read-side companion to push_to_dialectic.py.

WHY: tradingDesk pushes snapshots to Dialectic (write side). Dialectic's
TradingCuratorEngine generates rich LLM_ANNOTATOR alerts when Amo is offline
("Brent crossed $115 — persistence trigger approaching, 17 days to planting
deadline"). Today those alerts are invisible to tradingDesk -- they sit in
Dialectic's thread, and the workspace where the trade is being managed has
no idea they exist. This module pulls them back so the morning brief, room
chat, and dashboards can surface them in the place the trader actually works.

Stdlib only -- urllib.request + json, no httpx/requests dependency.

Usage:
    # CLI: dump curator alerts for a room since a timestamp
    python3 tools/bridge/dialectic_client.py \\
        --room-id 56ba2f1e-... \\
        --since 2026-04-15T00:00:00Z

Programmatic:
    from tools.bridge.dialectic_client import DialecticClient
    client = DialecticClient("http://localhost:8002", token="...")
    alerts = client.fetch_curator_alerts(room_id, since_iso="2026-04-15T00:00:00Z")
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# WHY: Dialectic's SpeakerType.LLM_ANNOTATOR is the speaker_type of curator
# alerts (and human-message annotations). For trading-desk surfacing we want
# both -- they're the LLM's contextual commentary on the room. We do NOT pull
# `human` or `llm_primary` because those are conversational, not alerts.
ANNOTATOR_SPEAKER_TYPES = {"llm_annotator"}


@dataclass
class CuratorAlert:
    """One LLM-generated alert pulled from a Dialectic room."""

    message_id: str
    thread_id: str
    sequence: int
    created_at: str  # ISO 8601 string
    content: str
    speaker_type: str

    def to_dict(self) -> dict:
        return asdict(self)


class DialecticClient:
    """
    Read-only client for the Dialectic API.

    WHY only-read: writes happen via push_to_dialectic.py which is hardened
    against transport failures. This client is for the converse path --
    polling alerts back into tradingDesk surfaces.
    """

    def __init__(self, base_url: str, token: Optional[str] = None,
                 timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        # WHY: token is the ROOM token (same one push uses). Per-book token
        # in book.meta.dialecticRoomToken takes precedence; falls back to the
        # DIALECTIC_ROOM_TOKEN env var so single-room setups need no JSON.
        self.token = token or os.environ.get("DIALECTIC_ROOM_TOKEN", "").strip()
        self.timeout = timeout

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _get(self, path: str, query: Optional[dict] = None) -> dict | list:
        """
        GET {base_url}{path}?{query}. Returns parsed JSON. Raises on non-2xx.

        Uses the room token in the Authorization header. Dialectic's
        extract_room_token accepts either query param or Authorization
        header -- header is cleaner (no token-in-URL leakage to access logs).
        """
        url = f"{self.base_url}{path}"
        if query:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(query)}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "tradingDesk-dialectic-client/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise DialecticAPIError(
                f"HTTP {e.code} {e.reason} on GET {path}: {body[:200]}"
            ) from e
        except (URLError, TimeoutError, OSError) as e:
            raise DialecticAPIError(
                f"connection error on GET {path}: {e}"
            ) from e
        except json.JSONDecodeError as e:
            raise DialecticAPIError(
                f"non-JSON response on GET {path}: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """GET /health. Returns {'status': 'ok'|'degraded', 'checks': {...}}."""
        return self._get("/health")  # type: ignore[return-value]

    def list_threads(self, room_id: str) -> list[dict]:
        """GET /rooms/{room_id}/threads. Returns list of {id, title, ...}."""
        result = self._get(f"/rooms/{room_id}/threads")
        return result if isinstance(result, list) else []

    def get_messages(self, thread_id: str, limit: int = 50,
                     after_sequence: Optional[int] = None) -> dict:
        """
        GET /threads/{thread_id}/messages.

        Returns {'messages': [...], 'has_more': bool, ...}. include_ancestry
        is left at the dialectic default (true) so we get full conversation
        context, not just the leaf thread.
        """
        query: dict = {"limit": limit}
        if after_sequence is not None:
            query["after_sequence"] = after_sequence
        result = self._get(f"/threads/{thread_id}/messages", query=query)
        # Dialectic returns PaginatedMessagesResponse (a dict). Defensive cast.
        return result if isinstance(result, dict) else {"messages": []}

    def fetch_curator_alerts(self, room_id: str,
                             since_iso: Optional[str] = None,
                             limit_per_thread: int = 50) -> list[CuratorAlert]:
        """
        Pull curator alert messages from a room, optionally filtered to
        messages newer than `since_iso`.

        Primary path: GET /rooms/{room_id}/trading/alerts?since=<iso> --
        server-side filter on metadata.source = 'trading_curator', already
        ordered ascending. One round-trip, no per-thread fan-out.

        Fallback path: walk /threads + /messages and filter client-side.
        Used only when the dialectic deploy predates the alerts endpoint
        (HTTP 404 on the new path).

        `limit_per_thread` is preserved for fallback compatibility; the
        primary path uses it as a soft cap on total messages returned.

        Returns a list of CuratorAlert sorted by created_at ascending.
        """
        try:
            return self._fetch_alerts_via_endpoint(room_id, since_iso, limit_per_thread)
        except DialecticAPIError as e:
            # WHY only fall back on 404: any other error (auth, network, 5xx)
            # should surface to the caller. 404 specifically means the
            # dialectic deploy is older than the new endpoint.
            if "HTTP 404" not in str(e):
                raise
            print(
                f"[dialectic-client] /trading/alerts returned 404 for room "
                f"{room_id}; falling back to threads-walk",
                file=sys.stderr,
            )
            return self._fetch_alerts_via_threads(room_id, since_iso, limit_per_thread)

    def _fetch_alerts_via_endpoint(self, room_id: str,
                                   since_iso: Optional[str],
                                   limit: int) -> list[CuratorAlert]:
        """Primary path: server-side filter via the trading/alerts endpoint."""
        query: dict = {"limit": min(max(limit, 1), 1000)}
        if since_iso:
            query["since"] = since_iso
        resp = self._get(f"/rooms/{room_id}/trading/alerts", query=query)
        # Endpoint returns either {"messages": [...]} or a bare list depending
        # on dialectic version; handle both.
        messages = (
            resp.get("messages") if isinstance(resp, dict) else resp
        ) or []
        alerts: list[CuratorAlert] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            speaker = (msg.get("speaker_type") or "").lower()
            alerts.append(CuratorAlert(
                message_id=str(msg.get("id") or ""),
                thread_id=str(msg.get("thread_id") or ""),
                sequence=int(msg.get("sequence") or 0),
                created_at=str(msg.get("created_at") or ""),
                content=str(msg.get("content") or ""),
                speaker_type=speaker or "llm_annotator",
            ))
        # Server orders ascending; preserve.
        return alerts

    def _fetch_alerts_via_threads(self, room_id: str,
                                  since_iso: Optional[str],
                                  limit_per_thread: int) -> list[CuratorAlert]:
        """Fallback path: walk threads + messages and filter client-side."""
        threads = self.list_threads(room_id)
        if not threads:
            return []

        cutoff = _parse_iso(since_iso) if since_iso else None
        seen_ids: set[str] = set()
        alerts: list[CuratorAlert] = []
        for thread in threads:
            tid = thread.get("id")
            if not tid:
                continue
            try:
                resp = self.get_messages(str(tid), limit=limit_per_thread)
            except DialecticAPIError as e:
                # WHY swallow per-thread: one bad thread shouldn't sink the
                # whole pull. Print to stderr so cron logs surface it.
                print(f"[dialectic-client] thread {tid}: {e}", file=sys.stderr)
                continue
            for msg in resp.get("messages", []):
                speaker = (msg.get("speaker_type") or "").lower()
                if speaker not in ANNOTATOR_SPEAKER_TYPES:
                    continue
                created_at = msg.get("created_at") or ""
                if cutoff is not None:
                    created_dt = _parse_iso(created_at)
                    if created_dt is None or created_dt < cutoff:
                        continue
                mid = str(msg.get("id") or "")
                # WHY dedupe: include_ancestry can return the same message
                # via two threads if a fork happened.
                if mid and mid in seen_ids:
                    continue
                seen_ids.add(mid)
                alerts.append(CuratorAlert(
                    message_id=mid,
                    thread_id=str(msg.get("thread_id") or tid),
                    sequence=int(msg.get("sequence") or 0),
                    created_at=created_at,
                    content=str(msg.get("content") or ""),
                    speaker_type=speaker,
                ))

        alerts.sort(key=lambda a: (a.created_at, a.sequence))
        return alerts


class DialecticAPIError(Exception):
    """Raised when the Dialectic API returns a non-2xx or unparseable response."""


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, treating naive datetimes as UTC."""
    if not s:
        return None
    try:
        # Handle the 'Z' suffix that fromisoformat() rejects in 3.10 (3.11+ ok).
        cleaned = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(cleaned)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# =========================================================================
# CLI
# =========================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull LLM_ANNOTATOR alerts from a Dialectic room.",
        epilog=(
            "DIALECTIC_ROOM_TOKEN env var must be set (or pass --token).\n"
            "Output: JSON array of {message_id, thread_id, sequence, "
            "created_at, content}."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--room-id", required=True, metavar="UUID")
    parser.add_argument("--dialectic-url", default="http://localhost:8002")
    parser.add_argument("--token", default=None,
                        help="Room token (default: DIALECTIC_ROOM_TOKEN env)")
    parser.add_argument("--since", default=None, metavar="ISO_TIMESTAMP",
                        help="Only return alerts newer than this timestamp")
    parser.add_argument("--limit-per-thread", type=int, default=50)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    client = DialecticClient(args.dialectic_url, token=args.token)
    try:
        alerts = client.fetch_curator_alerts(
            args.room_id, since_iso=args.since,
            limit_per_thread=args.limit_per_thread,
        )
    except DialecticAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps([a.to_dict() for a in alerts], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
