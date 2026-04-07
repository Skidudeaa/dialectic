"""
Thin adapter around thesisgraph.py functions.

WHY: thesisgraph.py was designed as a CLI tool. This adapter handles Path
resolution, exception catching, and returns typed dicts suitable for REST
responses. Does NOT duplicate any logic — every call goes through to the
original functions.
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"
SNAPSHOTS_DIR = _ROOT / "snapshots"

# WHY: Import from thesisgraph.py — sys.path is configured in web/main.py.
import thesisgraph  # type: ignore[import-untyped]


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
            })
        except Exception as e:
            log.warning("Skipping %s: %s", path.name, e)
    return books


def _load_cfg(book_id: str) -> dict:
    """Load and validate a book config by ID."""
    path = BOOKS_DIR / f"{book_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Book not found: {book_id}")
    return thesisgraph.load_config(str(path))


def get_state(book_id: str) -> Dict[str, Any]:
    """Run propagate + score_confluence + export_state, return evaluated state."""
    cfg = _load_cfg(book_id)
    states = thesisgraph.propagate(cfg)
    confluence = thesisgraph.score_confluence(cfg, states)
    phase_num, phase_key = thesisgraph.get_current_phase(cfg)

    # Evaluate all scenarios
    scenarios_result: List[Tuple[dict, dict, dict]] = []
    for scenario in cfg.get("scenarios", []):
        overrides, impacts = thesisgraph.eval_scenario(cfg, scenario, states)
        scenarios_result.append((scenario, overrides, impacts))

    state = thesisgraph.export_state(
        cfg, states, confluence, phase_num, phase_key,
        scenarios_result, today=date.today(),
    )
    return state


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
    """Trigger live price fetch for a book. Returns price data."""
    cfg = _load_cfg(book_id)
    prices = thesisgraph.fetch_prices(cfg)
    poly_prices = thesisgraph.fetch_polymarket(cfg)
    return {"yahoo": prices, "polymarket": poly_prices}


def export_snapshot(book_id: str) -> Dict[str, Any]:
    """Generate and save a snapshot to snapshots/ directory."""
    state = get_state(book_id)
    snapshot_path = SNAPSHOTS_DIR / f"{book_id}-latest.json"
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w") as f:
        json.dump(state, f, indent=2)
    return state
