#!/usr/bin/env python3
"""
Diff Snapshots — structured delta between two thesis graph snapshots.

Compares two snapshot JSONs (produced by thesisgraph.py --export-state) and
outputs a structured delta showing what changed. Used by the bridge script
to decide whether to push to Dialectic and to format curator alert context.

Usage:
    python3 diff-snapshots.py old.json new.json
    python3 diff-snapshots.py snapshots/2026-03-29.json snapshots/2026-03-30.json

Exit codes:
    0 — changes found (hasChanges: true)
    1 — no changes (hasChanges: false)
    2 — error (file not found, invalid JSON, etc.)

Output (stdout):
    Structured delta JSON — see INTEGRATION.md for the full shape.
"""

import argparse
import json
import sys
from pathlib import Path


# =========================================================================
# SNAPSHOT LOADING
# =========================================================================

def load_snapshot(path: str) -> dict:
    """Load and minimally validate a snapshot JSON file."""
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(p) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"Error: snapshot must be a JSON object, got {type(data).__name__}", file=sys.stderr)
        sys.exit(2)
    return data


# =========================================================================
# DIFF LOGIC
# =========================================================================

def diff_node_states(old: dict, new: dict) -> tuple[list, list, list]:
    """Compare nodeStates dicts. Returns (stateChanges, newNodes, removedNodes)."""
    old_states = old.get("nodeStates", {})
    new_states = new.get("nodeStates", {})

    state_changes = []
    for node_id in sorted(old_states.keys() & new_states.keys()):
        old_val = old_states[node_id]
        new_val = new_states[node_id]
        if old_val != new_val:
            state_changes.append({
                "nodeId": node_id,
                "from": old_val,
                "to": new_val,
            })

    new_nodes = sorted(new_states.keys() - old_states.keys())
    removed_nodes = sorted(old_states.keys() - new_states.keys())

    return state_changes, new_nodes, removed_nodes


def diff_confluence(old: dict, new: dict) -> dict:
    """Compare confluenceScores dicts. Returns {nodeId: {from, to, delta}}."""
    old_scores = old.get("confluenceScores", {})
    new_scores = new.get("confluenceScores", {})

    changes = {}
    all_keys = sorted(old_scores.keys() | new_scores.keys())
    for key in all_keys:
        old_val = old_scores.get(key)
        new_val = new_scores.get(key)
        if old_val is None or new_val is None:
            # Node appeared or disappeared — captured by node diff, skip here
            if old_val is not None and new_val is None:
                changes[key] = {"from": old_val, "to": None, "delta": None}
            elif old_val is None and new_val is not None:
                changes[key] = {"from": None, "to": new_val, "delta": None}
            continue
        if old_val != new_val:
            changes[key] = {
                "from": old_val,
                "to": new_val,
                "delta": round(new_val - old_val, 6),
            }

    return changes


def diff_countdowns(old: dict, new: dict) -> list:
    """Compare countdown arrays by nodeId. Returns [{nodeId, from, to}]."""
    old_countdowns = {c["nodeId"]: c["daysRemaining"] for c in old.get("countdowns", []) if "nodeId" in c}
    new_countdowns = {c["nodeId"]: c["daysRemaining"] for c in new.get("countdowns", []) if "nodeId" in c}

    changes = []
    for node_id in sorted(old_countdowns.keys() | new_countdowns.keys()):
        old_val = old_countdowns.get(node_id)
        new_val = new_countdowns.get(node_id)
        if old_val != new_val:
            change = {"nodeId": node_id}
            if old_val is not None:
                change["from"] = old_val
            if new_val is not None:
                change["to"] = new_val
            changes.append(change)

    return changes


def diff_markets(old: dict, new: dict) -> dict:
    """Compare marketSnapshot dicts. Returns {key: {from, to, pctChange}}."""
    old_market = old.get("marketSnapshot", {})
    new_market = new.get("marketSnapshot", {})

    changes = {}
    all_keys = sorted(old_market.keys() | new_market.keys())
    for key in all_keys:
        old_val = old_market.get(key)
        new_val = new_market.get(key)
        if old_val is None or new_val is None:
            if old_val != new_val:
                entry = {}
                if old_val is not None:
                    entry["from"] = old_val
                if new_val is not None:
                    entry["to"] = new_val
                entry["pctChange"] = None
                changes[key] = entry
            continue
        if old_val != new_val:
            if old_val != 0:
                pct = round((new_val - old_val) / old_val * 100, 2)
            else:
                pct = None
            changes[key] = {
                "from": old_val,
                "to": new_val,
                "pctChange": pct,
            }

    return changes


# WHY these thresholds: we want to surface material TV-indicator moves as
# informational context for the operator, not every tick of noise. 8 RSI
# points is a full zone transition (e.g. 62 → 70 crosses into overbought);
# 15% ATR delta is large enough to indicate a regime shift in realized vol;
# 8% SMA delta corresponds to a decisive trend change. Non-material drift
# stays out of the diff so the push stream remains signal-heavy.
_RSI_DIFF_THRESHOLD = 8.0
_ATR_PCT_THRESHOLD = 15.0
_SMA_PCT_THRESHOLD = 8.0

# Tags on tvIndicators that are metadata, not numeric values to diff.
_TV_METADATA_KEYS = {"source", "computedAt"}


def _pct_change(old_val: float, new_val: float) -> float | None:
    """Percent change from old to new. Returns None when old is zero."""
    if old_val == 0:
        return None
    return round((new_val - old_val) / abs(old_val) * 100, 2)


def _is_material_shift(field: str, old_val: float, new_val: float) -> bool:
    """Decide whether a single indicator value change is worth surfacing."""
    if field.startswith("rsi"):
        return abs(new_val - old_val) >= _RSI_DIFF_THRESHOLD
    if field.startswith("atr"):
        pct = _pct_change(old_val, new_val)
        return pct is not None and abs(pct) >= _ATR_PCT_THRESHOLD
    if field.startswith("sma"):
        pct = _pct_change(old_val, new_val)
        return pct is not None and abs(pct) >= _SMA_PCT_THRESHOLD
    # Unknown field — surface any change, let the operator decide
    return old_val != new_val


def diff_tv_indicators(old: dict, new: dict) -> dict:
    """Compare tvIndicators dicts. Returns {nodeId: [{field, from, to, delta, pctChange}]}.

    tvIndicators are NON-CAUSAL snapshot overlays (local RSI/ATR/SMA from
    Yahoo OHLCV). Shifts above material thresholds are reported so the
    operator sees regime transitions; smaller drift is suppressed to keep
    the delta payload signal-heavy. This function never changes the
    hasChanges decision in a way that would trigger a Dialectic push on
    pure-overlay movement — see build_delta for the has_changes gate.
    """
    old_tv = old.get("tvIndicators", {}) or {}
    new_tv = new.get("tvIndicators", {}) or {}
    if not isinstance(old_tv, dict) or not isinstance(new_tv, dict):
        return {}

    shifts: dict = {}
    for node_id in sorted(old_tv.keys() | new_tv.keys()):
        old_entry = old_tv.get(node_id) or {}
        new_entry = new_tv.get(node_id) or {}
        if not isinstance(old_entry, dict) or not isinstance(new_entry, dict):
            continue

        node_shifts = []
        fields = (set(old_entry.keys()) | set(new_entry.keys())) - _TV_METADATA_KEYS
        for field in sorted(fields):
            old_val = old_entry.get(field)
            new_val = new_entry.get(field)
            if not isinstance(old_val, (int, float)):
                if isinstance(new_val, (int, float)):
                    # Field appeared this run
                    node_shifts.append({
                        "field": field,
                        "from": None,
                        "to": new_val,
                        "delta": None,
                        "pctChange": None,
                    })
                continue
            if not isinstance(new_val, (int, float)):
                # Field disappeared this run
                node_shifts.append({
                    "field": field,
                    "from": old_val,
                    "to": None,
                    "delta": None,
                    "pctChange": None,
                })
                continue
            if not _is_material_shift(field, float(old_val), float(new_val)):
                continue
            node_shifts.append({
                "field": field,
                "from": old_val,
                "to": new_val,
                "delta": round(float(new_val) - float(old_val), 4),
                "pctChange": _pct_change(float(old_val), float(new_val)),
            })

        if node_shifts:
            shifts[node_id] = node_shifts

    return shifts


def build_delta(old: dict, new: dict) -> dict:
    """Build the full structured delta between two snapshots."""
    state_changes, new_nodes, removed_nodes = diff_node_states(old, new)
    confluence_changes = diff_confluence(old, new)
    countdown_changes = diff_countdowns(old, new)
    market_changes = diff_markets(old, new)
    tv_indicator_shifts = diff_tv_indicators(old, new)

    has_changes = bool(
        state_changes
        or confluence_changes
        or countdown_changes
        or market_changes
        or new_nodes
        or removed_nodes
        or tv_indicator_shifts
    )

    return {
        "hasChanges": has_changes,
        "stateChanges": state_changes,
        "confluenceChanges": confluence_changes,
        "countdownChanges": countdown_changes,
        "marketChanges": market_changes,
        "newNodes": new_nodes,
        "removedNodes": removed_nodes,
        "tvIndicatorShifts": tv_indicator_shifts,
    }


# =========================================================================
# CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compare two thesis graph snapshots and output a structured delta.",
        epilog="Exit codes: 0 = changes found, 1 = no changes, 2 = error",
    )
    parser.add_argument("old", help="Path to the older snapshot JSON")
    parser.add_argument("new", help="Path to the newer snapshot JSON")
    args = parser.parse_args()

    old = load_snapshot(args.old)
    new = load_snapshot(args.new)

    delta = build_delta(old, new)
    print(json.dumps(delta, indent=2, ensure_ascii=False))

    sys.exit(0 if delta["hasChanges"] else 1)


if __name__ == "__main__":
    main()
