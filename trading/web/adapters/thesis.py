"""
Thin adapter around thesisgraph.py functions.

WHY: thesisgraph.py was designed as a CLI tool. This adapter handles Path
resolution, exception catching, and returns typed dicts suitable for REST
responses. Does NOT duplicate any logic — every call goes through to the
original functions.
"""

import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# WHY: Thesis state only changes when the pipeline runs (Mon/Wed/Fri at 08:00)
# or when prices are fetched. A 60-second TTL eliminates redundant graph
# evaluations from auto-refresh and LLM context builds.
_state_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 60.0  # seconds

# Per-book feed freshness record, survives cache invalidation (which reloads
# cfg from disk and drops the in-memory _feed_freshness stamp). Keyed by
# book_id, value is the `snapshot["feedFreshness"]` dict stamped on the last
# successful fetch. Overlayed onto every snapshot returned by get_state().
_freshness_by_book: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _validate_book_id(book_id: str) -> None:
    """Reject book IDs that could traverse the filesystem."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", book_id):
        raise ValueError(f"Invalid book ID: {book_id}")


_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"
SNAPSHOTS_DIR = _ROOT / "snapshots"

# WHY: Package import via pip install -e . (pyproject.toml).
from tools.thesis_graph import thesisgraph  # type: ignore[import-untyped]


def list_books() -> List[Dict[str, Any]]:
    """List available thesis-graph book configs."""
    books: List[Dict[str, Any]] = []
    if not BOOKS_DIR.exists():
        return books
    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = thesisgraph.load_config(str(path))
            meta = cfg.get("meta", {})
            books.append({
                "id": path.stem,
                "filename": path.name,
                "title": meta.get("title", path.stem),
                "nodes": len(cfg.get("nodes", [])),
                "edges": len(cfg.get("edges", [])),
                # WHY exposed: this is the join key between a Dialectic room and
                # the book it discusses. Dialectic's "Open Full Dashboard" link
                # carries its room id, and the desk resolves it to THIS book so
                # you land on the case you were just arguing about.
                #
                # SECURITY: the id ONLY. meta also holds dialecticRoomToken,
                # which is a room credential and must never reach a client.
                "dialecticRoomId": meta.get("dialecticRoomId"),
            })
        except Exception as e:
            log.warning("Skipping %s: %s", path.name, e)
    return books


def _load_cfg(book_id: str) -> dict:
    """Load and validate a book config by ID."""
    _validate_book_id(book_id)
    path = BOOKS_DIR / f"{book_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Book not found: {book_id}")
    return thesisgraph.load_config(str(path))


def get_state(book_id: str) -> Dict[str, Any]:
    """Run propagate + score_confluence + export_state, return evaluated state.

    WHY: Results are cached for 60 seconds. The thesis graph only changes when
    the pipeline runs or prices are fetched — sub-minute staleness is acceptable.
    """
    _validate_book_id(book_id)
    now = time.monotonic()
    cached = _state_cache.get(book_id)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    cfg = _load_cfg(book_id)
    states = thesisgraph.propagate(cfg)
    confluence = thesisgraph.score_confluence(cfg, states)
    phase_num, phase_key = thesisgraph.get_current_phase(cfg)

    scenarios_result: List[Tuple[dict, dict, dict]] = []
    for scenario in cfg.get("scenarios", []):
        overrides, impacts = thesisgraph.eval_scenario(cfg, scenario, states)
        scenarios_result.append((scenario, overrides, impacts))

    result = thesisgraph.export_state(
        cfg, states, confluence, phase_num, phase_key,
        scenarios_result, today=date.today(),
    )
    # Overlay any freshness stamped by the last fetch so the UI can age it
    # even while the cached snapshot is reused for ~60s.
    remembered = _freshness_by_book.get(book_id)
    if remembered:
        result["feedFreshness"] = dict(remembered)
    _state_cache[book_id] = (now, result)
    return result


def invalidate_cache(book_id: str) -> None:
    """Clear cached state for a book — call after price fetch or config change."""
    _state_cache.pop(book_id, None)


def get_scenarios(book_id: str) -> List[Dict[str, Any]]:
    """Evaluate all scenarios, return impacts."""
    cfg = _load_cfg(book_id)
    states = thesisgraph.propagate(cfg)
    results: List[Dict[str, Any]] = []
    for scenario in cfg.get("scenarios", []):
        overrides, impacts = thesisgraph.eval_scenario(cfg, scenario, states)
        results.append({
            "scenario_id": scenario.get("id", ""),
            "label": scenario.get("label", ""),
            "probability": scenario.get("probability", 0),
            "net_impact": impacts.get("netImpact", 0),
            "overrides": overrides,
            "instrument_impacts": impacts,
        })
    return results


def run_horizon(book_id: str, horizon_days: int) -> Dict[str, Any]:
    """Run propagate_at_horizon with requested horizon."""
    cfg = _load_cfg(book_id)
    return thesisgraph.propagate_at_horizon(cfg, horizon_days, ref_date=date.today())


def fetch_prices_for_book(book_id: str) -> Dict[str, Any]:
    """Trigger live price fetch, persist to config, return price data.

    WHY: fetch_prices() and fetch_polymarket() mutate cfg in memory —
    updating node.current and node.probability with live values. We must
    also sync marketFields[].value (which export_state reads for the
    snapshot's marketSnapshot) and save the config back to disk so that
    the next get_state() / propagate() call uses live data, not stale
    hand-entered values. This is the ROOT CAUSE fix for stale snapshots.
    """
    _validate_book_id(book_id)
    config_path = BOOKS_DIR / f"{book_id}.json"
    cfg = thesisgraph.load_config(str(config_path))

    # Fetch live prices — mutates cfg.nodes[].current and cfg.instruments[].ref
    thesisgraph.fetch_prices(cfg)
    # Fetch live probabilities — mutates cfg.nodes[].probability
    thesisgraph.fetch_polymarket(cfg)
    # WHY: the CLI --fetch path runs derived indicators here too (see
    # thesisgraph.main()). The web fetch-prices endpoint must match that
    # behaviour or the dashboard's tvIndicators badges stay empty forever
    # despite Phase 1 shipping the derivation code. Wrapped in try/except
    # because derivation is a best-effort overlay — a failure here should
    # not poison the primary price update.
    try:
        thesisgraph.fetch_ohlcv_for_derived(cfg)
        thesisgraph.compute_derived_indicators(cfg)
    except Exception as e:
        log.warning("derived_indicators failed for %s: %s", book_id, e)

    # WHY: Sync marketFields[].value from live-fetched prices. Two strategies:
    # 1. If the marketField key matches a Yahoo symbol we just fetched, use that
    # 2. If the marketField's nodeId has a single yahoo feed whose symbol maps
    #    to the same concept, use the node's updated current value
    # We do NOT blindly copy node.current into marketField.value because some
    # marketFields (e.g. goldSpot) are mapped to nodes that track a different
    # instrument (e.g. dxy-stress tracks DXY, not gold).
    node_map = {n["id"]: n for n in cfg.get("nodes", [])}
    # Build a map of yahoo symbols to their fetched prices from node.current
    sym_to_price: Dict[str, float] = {}
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "yahoo" and "symbol" in feed:
                if "current" in node:
                    sym_to_price[feed["symbol"]] = node["current"]

    for mf in cfg.get("marketFields", []):
        node_id = mf.get("nodeId")
        mf_key = mf.get("key", "")
        if not node_id or node_id not in node_map:
            continue
        node = node_map[node_id]
        # Only sync if this node's primary feed matches the marketField's concept.
        # Check: does the node have exactly one yahoo feed, and does the node ID
        # match the marketField key? This prevents goldSpot from getting DXY's value.
        yahoo_feeds = [f for f in node.get("feeds", []) if f.get("source") == "yahoo"]
        if node_id == mf_key and "current" in node:
            # Direct match: node "brent" → marketField "brent"
            mf["value"] = node["current"]
        elif len(yahoo_feeds) == 1 and node_id == mf_key:
            # Single-feed node matching the key
            if "current" in node:
                mf["value"] = node["current"]

    # Capture freshness stamped by the fetch providers BEFORE the disk write
    # (update_config_file strips `_`-prefixed keys, so the stamp would be gone
    # after the write). Keep it in _freshness_by_book so get_state overlays it
    # onto the next snapshot — UI shows accurate "fetched 3s ago" even though
    # the reloaded cfg has no stamp.
    stamped = cfg.get("_feed_freshness")
    if stamped:
        _freshness_by_book[book_id] = dict(stamped)

    # Save the updated config back to disk so propagation uses live data
    thesisgraph.update_config_file(str(config_path), cfg)

    invalidate_cache(book_id)

    # Build a clean summary of what was fetched
    prices_summary: Dict[str, Any] = {}
    for node in cfg.get("nodes", []):
        if "current" in node:
            prices_summary[node["id"]] = node["current"]
        if "probability" in node:
            prices_summary[node["id"] + "_prob"] = node["probability"]

    return prices_summary


def export_snapshot(book_id: str) -> Dict[str, Any]:
    """Generate and save a snapshot to snapshots/ directory atomically."""
    # WHY: Rename 'state' to 'snapshot' to avoid shadowing the web.state module name.
    snapshot = get_state(book_id)
    snapshot_path = SNAPSHOTS_DIR / f"{book_id}-latest.json"
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = snapshot_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(snapshot, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(snapshot_path))
    return snapshot
