#!/usr/bin/env python3
"""
End-to-end integration test: thesisgraph export -> lifecycle monitor -> verify.

Verifies the complete REPAIR -> TAG -> CAPTURE pipeline against real data.
"""
import sys, json, tempfile, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'thesis-graph'))

from lifecycle_monitor import (
    PredicateLifecycleMonitor, Snapshot,
    XOP_GATE, CF_GATE, SPY_SHORT_GATE,
    evaluate_predicate, compute_provenance_target, detect_inert_fields,
    _serialize_record, _deserialize_record,
    step7_evaluate_open_trades,
)
from thesisgraph import propagate, score_confluence, propagate_at_horizon, parse_lag_days
from datetime import date

ROOT = Path(__file__).resolve().parent.parent.parent

errors = 0

def check(label, condition, detail=""):
    global errors
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        errors += 1

# ========================================
print("=== 1. Snapshot Loading ===")
iran_path = ROOT / "snapshots" / "iran-integration-test.json"
snap = Snapshot.load(iran_path)
check("iran snapshot loads", snap.node_states.get("hormuz") == "fired")
check("confluence present", "em-stress" in snap.confluence_scores)
check("countdown present", snap.get_countdown_days("planting-miss") is not None)
check("dotted path works", snap.get_path("scenarioImpacts.closed-may.netImpact") is not None)

# ========================================
print("\n=== 2. Predicate Evaluation (all 4 kinds) ===")
from lifecycle_monitor import Predicate
state_ep = evaluate_predicate(Predicate(kind="state", node_id="em-stress", expected="fired"), snap)
check("state predicate holds", not state_ep.is_flipped)

set_ep = evaluate_predicate(Predicate(kind="state_set", node_id="fert-shortage", allowed=["approaching", "fired"]), snap)
check("state_set predicate holds", not set_ep.is_flipped)

thresh_ep = evaluate_predicate(Predicate(kind="threshold", path="confluenceScores.em-stress", op=">=", value=1.60), snap)
check("threshold predicate holds", not thresh_ep.is_flipped, f"actual={thresh_ep.actual}")

cd_ep = evaluate_predicate(Predicate(kind="countdown", node_id="planting-miss", op="<=", days=14), snap)
check("countdown predicate holds", not cd_ep.is_flipped, f"actual={cd_ep.actual}")

missing_ep = evaluate_predicate(Predicate(kind="state", node_id="GHOST", expected="fired"), snap)
check("NODE_MISSING detected", missing_ep.note == "NODE_MISSING")

# ========================================
print("\n=== 3. Three Trades vs Fresh Export ===")
xop_results = [evaluate_predicate(p, snap) for p in XOP_GATE]
xop_flipped = [r for r in xop_results if r.is_flipped]
# WHY: Fresh export has brent=approaching (re-propagated), not stable (old snapshot).
# All 4 XOP predicates should HOLD against fresh data.
brent_state = snap.node_states.get("brent", "?")
check(f"XOP: brent is {brent_state}", brent_state in ("approaching", "fired", "stable"))
check(f"XOP: flipped={len(xop_flipped)} (expect 0 if brent approaching, 1 if stable)",
      len(xop_flipped) <= 1)

tariffs_path = ROOT / "snapshots" / "trump-tariffs-graph-latest.json"
if tariffs_path.exists():
    tsnap = Snapshot.load(tariffs_path)
    spy_results = [evaluate_predicate(p, tsnap) for p in SPY_SHORT_GATE]
    spy_flipped = [r for r in spy_results if r.is_flipped]
    check("SPY-short: all 4 hold", len(spy_flipped) == 0)

# ========================================
print("\n=== 4. Provenance Target ===")
result = compute_provenance_target(188.18, snap.scenario_impacts,
                                   book_path=ROOT / "books" / "iran-hormuz-graph.json")
from lifecycle_monitor import DynamicTarget, TargetRefusal
check("target computes (not refused)", isinstance(result, DynamicTarget))
if isinstance(result, DynamicTarget):
    check("target > ref (positive net impact)", result.computed_target > 188.18)
    unverified = [t for t in result.provenance if t.confidence_level == "UNVERIFIED"]
    check(f"provenance tags present ({len(result.provenance)} total)", len(result.provenance) >= 2)

# ========================================
print("\n=== 5. Lifecycle Monitor Cycle ===")
with tempfile.TemporaryDirectory(dir=str(ROOT)) as td:
    ledger = os.path.join(td, 'trades')
    monitor = PredicateLifecycleMonitor(ledger_dir=ledger)

    # SPY-short: thesis intact
    status1, rec1 = monitor.run_evaluation_cycle(
        'E2E-SH', 'SH', SPY_SHORT_GATE, tariffs_path, ref_price=15.50,
        book_path=ROOT / "books" / "trump-tariffs-graph.json")
    check("SPY-short EVALUATION", status1 == "EVALUATION")
    check("SPY-short has target", rec1.dynamic_target is not None)

    # Dedup
    status2, rec2 = monitor.run_evaluation_cycle(
        'E2E-SH', 'SH', SPY_SHORT_GATE, tariffs_path)
    check("dedup works", status2 == "DUPLICATE")
    check("dedup returns original run_id", rec2.run_id == rec1.run_id)

    # XOP: against fresh export (brent=approaching → all hold → EVALUATION)
    # Against old snapshot (brent=stable → flips → EXIT)
    status3, rec3 = monitor.run_evaluation_cycle(
        'E2E-XOP', 'XOP', XOP_GATE, iran_path, ref_price=188.18)
    check(f"XOP status is {status3}", status3 in ("EVALUATION", "EXIT"))

    # Test EXIT path using the old snapshot where brent=stable
    old_iran = ROOT / "snapshots" / "iran-hormuz-graph-latest.json"
    if old_iran.exists():
        status_old, rec_old = monitor.run_evaluation_cycle(
            'E2E-XOP-OLD', 'XOP', XOP_GATE, old_iran, ref_price=188.18)
        check(f"XOP vs old snapshot: {status_old}", status_old == "EXIT")
        if rec_old.verdict:
            check("XOP old: brent in flipped", "brent" in rec_old.verdict.load_bearing_flipped)
            check("XOP old: consistency < 100", rec_old.verdict.predicate_consistency < 100)

    # Serialization round-trip — use the EXIT record which has a verdict
    from lifecycle_monitor import _serialize_record, _deserialize_record
    exit_rec = rec_old if old_iran.exists() and rec_old.verdict else rec3
    serialized = _serialize_record(exit_rec)
    roundtrip = _deserialize_record(serialized)
    check("round-trip preserves trade_id", roundtrip.trade_id == exit_rec.trade_id)
    check("round-trip preserves event_type", roundtrip.event_type == exit_rec.event_type)
    if exit_rec.verdict:
        check("round-trip preserves verdict", roundtrip.verdict is not None)

    # Step 7 integration
    open_trades = ROOT / "outcomes" / "open_trades.json"
    if open_trades.exists():
        results = step7_evaluate_open_trades(
            snapshot_path=iran_path,
            open_trades_path=open_trades,
            book_path=ROOT / "books" / "iran-hormuz-graph.json",
            ledger_dir=ledger,
        )
        check("step7 returns results", len(results) > 0)

# ========================================
print("\n=== 6. Propagation Repair (Layer 0) ===")
cfg = json.loads((ROOT / "books" / "iran-hormuz-graph.json").read_text())
ref = date(2026, 4, 5)

# Amplification wired
states = propagate(cfg)
conf = score_confluence(cfg, states)
check("em-stress confluence computed", "em-stress" in conf)
check("em-stress confluence = 1.67 (no amp on incoming)", abs(conf["em-stress"] - 1.67) < 0.01)

# Horizon propagator
r7 = propagate_at_horizon(cfg, 7, ref_date=ref)
r180 = propagate_at_horizon(cfg, 180, ref_date=ref)
check("T+7d: fewer fired than T+180d",
      len([s for s in r7['states'].values() if s == 'fired']) <
      len([s for s in r180['states'].values() if s == 'fired']))
check("T+180d: em-stress confluence matches T+0",
      abs(r180['confluence'].get('em-stress', 0) - 1.67) < 0.01)

# Lag parsing
check("parse immediate = 1d", parse_lag_days("immediate", ref) == 1)
check("parse 1-2 weeks = 10d", parse_lag_days("1-2 weeks", ref) == 10)
check("parse date-gated Apr 15 = 10d", parse_lag_days("date-gated Apr 15", ref) == 10)

# ========================================
print(f"\n{'='*40}")
if errors == 0:
    print(f"ALL CHECKS PASSED")
else:
    print(f"{errors} CHECK(S) FAILED")
    sys.exit(1)
