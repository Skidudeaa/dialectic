"""
Async adapter around the econ calendar connector.

WHY: tools/data_fetch/econ_calendar.py is sync and stdlib-only. The webapp
needs an async surface plus a 1-hour TTL cache (calendar updates weekly at
most — re-pulling on every request is wasteful and adds 100-200ms of FRED
latency to interactive endpoints).

Public API:
    await get_calendar(lookahead_days=90) -> list[event]
    await for_book(book_id) -> dict[deadline_node_id, event]
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"

from tools.data_fetch import econ_calendar as _econ  # type: ignore[import-untyped]
from tools.thesis_graph import thesisgraph  # type: ignore[import-untyped]

# WHY 3600s: calendars publish on a weekly cadence at most. A 1-hour TTL keeps
# UI responses snappy without forcing operators to wait for cache eviction
# after a refresh. Same trade-off the thesis adapter makes for snapshots, just
# longer-lived.
_CACHE_TTL = 3600.0

# Single-key cache keyed by lookahead_days. Tuple = (timestamp, events).
_calendar_cache: Dict[int, Tuple[float, List[dict]]] = {}

# Per-book mapping cache. Same TTL — invalidated implicitly when the calendar
# cache rolls over since for_book reads the calendar through the cached path.
_book_cache: Dict[str, Tuple[float, Dict[str, dict]]] = {}


def _validate_book_id(book_id: str) -> None:
    """Reject book IDs that could traverse the filesystem."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", book_id):
        raise ValueError(f"Invalid book ID: {book_id}")


async def get_calendar(lookahead_days: int = 90) -> List[dict]:
    """Return upcoming macro/policy events.

    WHY 1h cache: see module docstring. The cache key is lookahead_days so
    callers asking for different windows don't trample each other.
    """
    if lookahead_days < 0:
        raise ValueError("lookahead_days must be non-negative")

    now = time.monotonic()
    cached = _calendar_cache.get(lookahead_days)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    # WHY to_thread: the underlying fetcher does sync HTTP + JSON parsing.
    # to_thread keeps the event loop unblocked under FRED slow-path latency.
    try:
        events = await asyncio.to_thread(
            _econ.fetch_upcoming_events, lookahead_days=lookahead_days
        )
    except Exception as exc:  # noqa: BLE001 — connector is best-effort here
        log.warning("econ_calendar fetch failed: %s", exc)
        events = []

    _calendar_cache[lookahead_days] = (now, events)
    return events


def invalidate_cache() -> None:
    """Clear all cached calendar + per-book mappings.

    WHY exposed: a future admin endpoint or scheduled refresh hook can call
    this to force a cold pull without restarting the process.
    """
    _calendar_cache.clear()
    _book_cache.clear()


def _deadline_nodes(cfg: dict) -> List[dict]:
    """Yield deadline-type nodes from a book config."""
    return [n for n in cfg.get("nodes", []) if n.get("type") == "deadline"]


def _query_for_node(node: dict) -> str:
    """Build a match query for a deadline node.

    WHY combine id + label + description: deadline nodes carry their hint in
    different fields across books — `id` is always present (kebab-case slug),
    `label` is human-readable, `context` may contain the canonical event name.
    Concatenating all three gives match_event the best signal.
    """
    parts = [
        str(node.get("id", "")),
        str(node.get("label", "")),
        str(node.get("context", "")),
    ]
    return " ".join(p for p in parts if p)


async def for_book(book_id: str, *, lookahead_days: int = 90) -> Dict[str, dict]:
    """Return {deadline_node_id: matched_event} for a book.

    For each deadline node:
      1. If the node has a `calendarFeed` block with an `event_id`, attempt
         exact match against the upcoming events list. If that event_id isn't
         in-window (already passed, beyond lookahead), fall through to fuzzy.
      2. Otherwise (or as fallback), call match_event with the node's id +
         label + description as the query.
      3. Nodes with no plausible match are omitted from the returned dict —
         callers should treat absence as "stay on hand-coded date".

    WHY return a sparse dict: keeps consumers simple — `mapping.get(node_id)`
    works whether or not we found a hit, no need to filter sentinel values.
    """
    _validate_book_id(book_id)

    now = time.monotonic()
    cached = _book_cache.get(book_id)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    path = BOOKS_DIR / f"{book_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Book not found: {book_id}")

    from web.adapters.thesis import load_book_config
    cfg = await asyncio.to_thread(load_book_config, path) or {}
    events = await get_calendar(lookahead_days=lookahead_days)
    by_id = {e.get("event_id"): e for e in events if e.get("event_id")}

    mapping: Dict[str, dict] = {}
    for node in _deadline_nodes(cfg):
        node_id = node.get("id")
        if not node_id:
            continue

        # 1. Direct calendarFeed pin
        feed = node.get("calendarFeed") or {}
        pinned = feed.get("event_id") if isinstance(feed, dict) else None
        if pinned and pinned in by_id:
            mapping[node_id] = by_id[pinned]
            continue

        # 2. Fuzzy fallback by id + label + description
        query = _query_for_node(node)
        hit = _econ.match_event(query, events)
        if hit is not None:
            mapping[node_id] = hit

    _book_cache[book_id] = (now, mapping)
    return mapping
