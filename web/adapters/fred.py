"""
FRED adapter — async wrapper around the stdlib fetcher.

WHY: the coordinator's tick loop is async-first and must not block the
event loop on synchronous urllib calls. This module wraps tools/data_fetch/
fred.py via asyncio.to_thread so the live system stays responsive even
when FRED is slow or retrying.

Mirrors the pattern of web/adapters/market.py (Yahoo + Polymarket).

Usage from a coordinator route:
    from web.adapters import fred as fred_adapter
    obs = await fred_adapter.fetch_series("DGS10")
    by_book = await fred_adapter.fetch_book_series("japan-rate-shock")
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"

from tools.thesis_graph import thesisgraph  # type: ignore[import-untyped]
from tools.data_fetch import fred as fred_mod  # type: ignore[import-untyped]


async def fetch_series(series_id: str) -> Dict[str, Any]:
    """Fetch the latest observation for a single FRED series.

    Returns the raw fred_mod.fetch_series_latest dict:
        {"value": float, "observation_date": str, "fetched_at": str}

    Propagates FredAuthError / FredNoDataError / FredAPIError so callers
    can distinguish config problems from publishing gaps.
    """
    return await asyncio.to_thread(fred_mod.fetch_series_latest, series_id)


def _collect_book_series(book_id: str) -> Dict[str, list[str]]:
    """Scan one book for FRED feeds and return series_id -> [node_ids].

    WHY return the node-mapping: callers (coordinator, status endpoints)
    often want to know which nodes a series feeds, not just the values.
    Keeps the door open for that without a second pass over the book.
    """
    # WHY validate book_id: same regex shape used elsewhere — alphanumeric
    # plus hyphens. Refuses path traversal / unexpected characters.
    if not book_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"invalid book_id: {book_id!r}")

    path = BOOKS_DIR / f"{book_id}-graph.json"
    if not path.is_file():
        # fall back to exact match (book_id may already include -graph)
        path = BOOKS_DIR / f"{book_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"book not found: {book_id}")

    cfg = thesisgraph.load_config(str(path))
    series_to_nodes: Dict[str, list[str]] = {}
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []) or []:
            if feed.get("source") == "fred" and feed.get("series"):
                sid = feed["series"]
                series_to_nodes.setdefault(sid, []).append(node["id"])
    return series_to_nodes


async def fetch_book_series(book_id: str) -> Dict[str, Dict[str, Any]]:
    """Fetch every FRED series referenced by a book's node feeds.

    Returns:
        {series_id: {"value": ..., "observation_date": ...,
                     "fetched_at": ..., "node_ids": [...]}}

    Failed series are *omitted* (matching fetch_series_batch semantics)
    so callers can iterate over what succeeded without sentinel checks.

    WHY this signature: keeps the partial-failure pattern consistent with
    the underlying batch fetcher. The added node_ids field gives the
    coordinator enough metadata to push values back into thesis state
    without re-walking the book.
    """
    # Run the (sync) book scan + batch fetch in a worker thread so the
    # event loop stays free.
    series_to_nodes = await asyncio.to_thread(_collect_book_series, book_id)
    if not series_to_nodes:
        return {}

    series_ids = list(series_to_nodes.keys())
    try:
        raw = await asyncio.to_thread(fred_mod.fetch_series_batch, series_ids)
    except fred_mod.FredAuthError as e:
        # WHY re-raise as-is: callers (routes / coordinator) need to know
        # this is a config problem, not a "FRED is down" problem.
        log.warning("FRED auth error for book %s: %s", book_id, e)
        raise

    enriched: Dict[str, Dict[str, Any]] = {}
    for sid, obs in raw.items():
        if not isinstance(obs, dict):
            continue
        enriched[sid] = {
            **obs,
            "node_ids": list(series_to_nodes.get(sid, [])),
        }
    return enriched
