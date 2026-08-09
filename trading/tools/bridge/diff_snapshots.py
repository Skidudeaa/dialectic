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


# WHY a noise floor: confluence scores are floats multiplied through node
# weights + amplification factors. Yahoo spark returns float32-rounded prices
# whose last-decimal jitter (90.38 → 90.380000000001) flowed into confluence
# and produced `hasChanges=True` on quiet-market runs, spamming Dialectic with
# "0.0% change" deltas. A floor of 0.005 suppresses sub-half-a-percent confluence
# drift while keeping every meaningful move (a 0.01 shift on a 1.30 score is a
# ~0.8% move — still visible).
_CONFLUENCE_NOISE_FLOOR = 0.005


def diff_confluence(old: dict, new: dict) -> dict:
    """Compare confluenceScores dicts. Returns {nodeId: {from, to, delta}}.

    Drift below ``_CONFLUENCE_NOISE_FLOOR`` is suppressed to avoid float-noise
    push spam. Appearances / disappearances are always reported.
    """
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
        delta = new_val - old_val
        if abs(delta) < _CONFLUENCE_NOISE_FLOOR:
            continue
        changes[key] = {
            "from": old_val,
            "to": new_val,
            "delta": round(delta, 6),
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


# WHY 0.01%: float-round-trips through snapshot JSON produced spurious 0.0-pct
# "market changed" entries. A 0.01% floor catches Yahoo's native tick precision
# (4 decimals) without dropping anything a trader would care about — the
# smallest legitimate daily move on any watched asset is several basis points.
_MARKET_NOISE_FLOOR_PCT = 0.01


def diff_markets(old: dict, new: dict) -> dict:
    """Compare marketSnapshot dicts. Returns {key: {from, to, pctChange}}.

    Drift below ``_MARKET_NOISE_FLOOR_PCT`` is suppressed to avoid float-noise
    spam. Appearances / disappearances always reported.
    """
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
        if old_val == new_val:
            continue
        if old_val != 0:
            pct = (new_val - old_val) / old_val * 100
            if abs(pct) < _MARKET_NOISE_FLOOR_PCT:
                continue
            pct = round(pct, 2)
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


# WHY 5%: scenario netImpact and probability are outputs of scenario evaluation;
# a meaningful thesis shift is "probability of closed-may moved from 0.45 to 0.52"
# (0.07) or "netImpact swung from +12.8 to -18.2" (31 units). Sub-5% swings on
# either dimension are typically propagation noise when nothing else changed.
_SCENARIO_PROB_NOISE_FLOOR = 0.01
_SCENARIO_IMPACT_NOISE_FLOOR_PCT = 5.0


def diff_cascade_phase(old: dict, new: dict) -> dict | None:
    """Compare top-level cascadePhase. Returns {from, to} on change, else None.

    Phase transitions (e.g., 2→3 "transmission" → "amplification") are the
    headline events of the whole system and MUST reach Dialectic. Prior to
    this addition they were silently dropped unless a nodeState change
    coincidentally piggybacked them.
    """
    old_phase = old.get("cascadePhase") or {}
    new_phase = new.get("cascadePhase") or {}
    # Compare by the canonical triplet; status flips (STARTING → ACTIVE) are
    # meaningful enough to surface even when number + key stay constant.
    old_sig = (old_phase.get("number"), old_phase.get("key"), old_phase.get("status"))
    new_sig = (new_phase.get("number"), new_phase.get("key"), new_phase.get("status"))
    if old_sig == new_sig:
        return None
    return {"from": old_phase or None, "to": new_phase or None}


def diff_scenarios(old: dict, new: dict) -> dict:
    """Compare scenarioImpacts. Returns {scenarioId: {probability?, netImpact?}}.

    Reports probability drift above ``_SCENARIO_PROB_NOISE_FLOOR`` OR netImpact
    drift above ``_SCENARIO_IMPACT_NOISE_FLOOR_PCT``. Appeared / removed scenarios
    always reported.
    """
    old_sc = old.get("scenarioImpacts", {}) or {}
    new_sc = new.get("scenarioImpacts", {}) or {}
    if not isinstance(old_sc, dict) or not isinstance(new_sc, dict):
        return {}

    changes: dict = {}
    all_keys = sorted(old_sc.keys() | new_sc.keys())
    for key in all_keys:
        old_entry = old_sc.get(key)
        new_entry = new_sc.get(key)
        if old_entry is None and new_entry is not None:
            changes[key] = {"from": None, "to": new_entry}
            continue
        if new_entry is None and old_entry is not None:
            changes[key] = {"from": old_entry, "to": None}
            continue
        if not isinstance(old_entry, dict) or not isinstance(new_entry, dict):
            continue

        entry_changes: dict = {}
        old_prob = old_entry.get("probability")
        new_prob = new_entry.get("probability")
        if isinstance(old_prob, (int, float)) and isinstance(new_prob, (int, float)):
            if abs(new_prob - old_prob) >= _SCENARIO_PROB_NOISE_FLOOR:
                entry_changes["probability"] = {
                    "from": old_prob,
                    "to": new_prob,
                    "delta": round(new_prob - old_prob, 4),
                }

        old_imp = old_entry.get("netImpact")
        new_imp = new_entry.get("netImpact")
        if isinstance(old_imp, (int, float)) and isinstance(new_imp, (int, float)):
            if old_imp != new_imp:
                pct = _pct_change(float(old_imp), float(new_imp))
                # Absolute swing in magnitude units — surface when |pct| crosses
                # the floor OR when the sign flips (thesis inversion).
                sign_flip = (old_imp > 0) != (new_imp > 0) and old_imp != 0 and new_imp != 0
                crosses_floor = pct is not None and abs(pct) >= _SCENARIO_IMPACT_NOISE_FLOOR_PCT
                if sign_flip or crosses_floor:
                    entry_changes["netImpact"] = {
                        "from": old_imp,
                        "to": new_imp,
                        "delta": round(float(new_imp) - float(old_imp), 4),
                        "pctChange": pct,
                        "signFlip": sign_flip,
                    }

        if entry_changes:
            changes[key] = entry_changes

    return changes


def diff_portfolio(old: dict, new: dict) -> dict:
    """Compare portfolioSummary. Returns change dict or {} when unchanged.

    Reports monthlyBudget, sgovAvailable, and topPositions list membership.
    """
    old_p = old.get("portfolioSummary") or {}
    new_p = new.get("portfolioSummary") or {}
    if not isinstance(old_p, dict) or not isinstance(new_p, dict):
        return {}

    changes: dict = {}
    for scalar_key in ("monthlyBudget", "sgovAvailable"):
        old_val = old_p.get(scalar_key)
        new_val = new_p.get(scalar_key)
        if old_val != new_val:
            changes[scalar_key] = {"from": old_val, "to": new_val}

    old_pos = list(old_p.get("topPositions") or [])
    new_pos = list(new_p.get("topPositions") or [])
    if old_pos != new_pos:
        old_set = set(old_pos)
        new_set = set(new_pos)
        changes["topPositions"] = {
            "added": sorted(new_set - old_set),
            "removed": sorted(old_set - new_set),
            "from": old_pos,
            "to": new_pos,
        }

    return changes


def build_delta(old: dict, new: dict) -> dict:
    """Build the full structured delta between two snapshots.

    Covers all consequential fields from thesisgraph.py export_state: node
    states, confluence, countdowns, markets, cascade phase, scenarios,
    portfolio, and non-causal tvIndicators overlays. Every field is in the
    hasChanges gate EXCEPT tvIndicators — see diff_tv_indicators docstring.
    """
    state_changes, new_nodes, removed_nodes = diff_node_states(old, new)
    confluence_changes = diff_confluence(old, new)
    countdown_changes = diff_countdowns(old, new)
    market_changes = diff_markets(old, new)
    cascade_phase_change = diff_cascade_phase(old, new)
    scenario_changes = diff_scenarios(old, new)
    portfolio_changes = diff_portfolio(old, new)
    tv_indicator_shifts = diff_tv_indicators(old, new)

    has_changes = bool(
        state_changes
        or confluence_changes
        or countdown_changes
        or market_changes
        or cascade_phase_change
        or scenario_changes
        or portfolio_changes
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
        "cascadePhaseChange": cascade_phase_change,
        "scenarioChanges": scenario_changes,
        "portfolioChanges": portfolio_changes,
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
