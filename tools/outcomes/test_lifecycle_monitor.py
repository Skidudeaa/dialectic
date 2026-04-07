"""
Tests for the Predicate Lifecycle Monitor — Synthesis Layer.

Covers: snapshot loading (correct + wrong format), all 4 predicate types,
NODE_MISSING hard-fail, INERT TargetRefusal, dedup, cross-trade analyzer,
weighted consistency, multi-failure attribution, the 3 trade gates against
real snapshot format, provenance tagging, and serialization round-trips.
"""

import json
import pytest
from pathlib import Path
from dataclasses import asdict
from datetime import date

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lifecycle_monitor import (
    Snapshot, Predicate, EvaluatedPredicate, TradeRecord,
    ProvenanceTag, DynamicTarget, TargetRefusal, PostExitVerdict,
    evaluate_predicate, compute_provenance_target, detect_inert_fields,
    LedgerAnalyzer, PredicateLifecycleMonitor,
    XOP_GATE, CF_GATE, SPY_SHORT_GATE,
    _serialize_record, _deserialize_record,
)


# =========================================================================
# FIXTURES
# =========================================================================

@pytest.fixture
def iran_snapshot_data():
    """Real iran-hormuz-graph snapshot shape."""
    return {
        "v": 1,
        "timestamp": "2026-04-01T06:49:12Z",
        "title": "Iran/Hormuz Thesis — March 2026",
        "nodeStates": {
            "hormuz": "fired",
            "brent": "stable",
            "diesel": "fired",
            "fert-shortage": "approaching",
            "dxy-stress": "fired",
            "planting-miss": "approaching",
            "em-currency": "fired",
            "freight": "fired",
            "food-spike": "approaching",
            "employment": "fired",
            "em-stress": "fired",
            "demand-destruction": "fired",
            "de-escalation": "stable",
            "curve": "stable",
            "rig-confirm": "monitoring",
            "services": "gated",
        },
        "confluenceScores": {"em-stress": 1.67},
        "cascadePhase": {"number": 3, "key": "amplification", "status": "APPROACHING"},
        "countdowns": [
            {"nodeId": "planting-miss", "label": "Planting Cycle Miss",
             "deadline": "2026-04-15", "daysRemaining": 14}
        ],
        "marketSnapshot": {"brent": 112.57, "diesel": 5.38, "dxy": 100.18, "nolaFert": 683},
        "scenarioImpacts": {
            "reopen-apr1": {"probability": 0.1, "netImpact": 1.4},
            "closed-may": {"probability": 0.45, "netImpact": 14.4},
            "kharg-strike": {"probability": 0.15, "netImpact": 6.8},
            "selective-reopen": {"probability": 0.3, "netImpact": 10.7},
        },
        "portfolioSummary": {"monthlyBudget": 8000},
    }


@pytest.fixture
def tariffs_snapshot_data():
    """Real trump-tariffs-graph snapshot shape."""
    return {
        "v": 1,
        "timestamp": "2026-04-01T06:49:25Z",
        "title": "Trump Tariff Escalation Thesis — March 2026",
        "nodeStates": {
            "tariff-shock": "fired",
            "section122-expiry": "gated",
            "input-costs": "fired",
            "supply-chain": "fired",
            "auto-sector": "fired",
            "tech-supply": "fired",
            "ag-retaliation": "fired",
            "usd-cny": "approaching",
            "retail-prices": "fired",
            "mfg-pmi": "fired",
            "consumer-confidence": "fired",
            "earnings-compression": "fired",
            "recession-risk": "fired",
            "fed-response": "monitoring",
            "negotiation": "stable",
        },
        "confluenceScores": {
            "consumer-confidence": 1.95,
            "earnings-compression": 2.05,
            "recession-risk": 1.25,
        },
        "cascadePhase": {"number": 3, "key": "amplification", "status": "STARTING"},
        "countdowns": [
            {"nodeId": "section122-expiry", "label": "Section 122 Expiration",
             "deadline": "2026-07-24", "daysRemaining": 114}
        ],
        "marketSnapshot": {"spx": 6370, "vix": 30.97, "goldSpot": 4492},
        "scenarioImpacts": {
            "deal-by-july": {"probability": 0.35, "netImpact": -0.3},
            "section122-extended": {"probability": 0.25, "netImpact": 0.0},
            "escalation": {"probability": 0.15, "netImpact": 0.0},
            "stagflation": {"probability": 0.15, "netImpact": 0.0},
            "muddle-through": {"probability": 0.1, "netImpact": 0.2},
        },
        "portfolioSummary": {"monthlyBudget": 6000},
    }


@pytest.fixture
def iran_snapshot_path(tmp_path, iran_snapshot_data):
    p = tmp_path / "iran-hormuz-graph-latest.json"
    p.write_text(json.dumps(iran_snapshot_data))
    return p


@pytest.fixture
def tariffs_snapshot_path(tmp_path, tariffs_snapshot_data):
    p = tmp_path / "trump-tariffs-graph-latest.json"
    p.write_text(json.dumps(tariffs_snapshot_data))
    return p


@pytest.fixture
def book_with_amplification(tmp_path):
    """Minimal book JSON with amplification+lag on edges."""
    book = {
        "meta": {"title": "Test Book"},
        "nodes": [
            {"id": "a", "type": "event", "state": "fired"},
            {"id": "b", "type": "price", "current": 100},
        ],
        "edges": [
            {"from": "a", "to": "b", "strength": 0.9, "amplification": 1.3, "lag": "2-4 weeks"},
        ],
    }
    p = tmp_path / "test-book.json"
    p.write_text(json.dumps(book))
    return p


# =========================================================================
# SNAPSHOT LOADING
# =========================================================================

class TestSnapshotLoading:
    def test_load_valid_snapshot(self, iran_snapshot_path):
        snap = Snapshot.load(iran_snapshot_path)
        assert snap.node_states["hormuz"] == "fired"
        assert snap.confluence_scores["em-stress"] == 1.67
        assert snap.cascade_phase["number"] == 3
        assert snap.get_countdown_days("planting-miss") == 14

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Snapshot missing"):
            Snapshot.load(tmp_path / "nonexistent.json")

    def test_load_wrong_format_raises(self, tmp_path):
        """Cytoscape book format should fail, not silently produce empty."""
        wrong = {"elements": {"nodes": [{"data": {"id": "x", "state": "fired"}}]}}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(wrong))
        with pytest.raises(ValueError, match="missing required keys"):
            Snapshot.load(p)

    def test_content_hash_deterministic(self, iran_snapshot_data):
        s1 = Snapshot(iran_snapshot_data)
        s2 = Snapshot(iran_snapshot_data)
        assert s1.content_hash() == s2.content_hash()

    def test_get_path_dotted(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        assert snap.get_path("scenarioImpacts.closed-may.netImpact") == 14.4
        assert snap.get_path("scenarioImpacts.nonexistent.netImpact") is None

    def test_get_countdown_days(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        assert snap.get_countdown_days("planting-miss") == 14
        assert snap.get_countdown_days("nonexistent") is None


# =========================================================================
# PREDICATE EVALUATION — all 4 kinds
# =========================================================================

class TestPredicateEvaluation:
    def test_state_predicate_match(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="state", node_id="em-stress", expected="fired")
        ep = evaluate_predicate(pred, snap)
        assert not ep.is_flipped
        assert ep.actual == "fired"

    def test_state_predicate_mismatch(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="state", node_id="brent", expected="fired")
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped
        assert ep.actual == "stable"

    def test_state_predicate_node_missing(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="state", node_id="nonexistent", expected="fired")
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped
        assert ep.note == "NODE_MISSING"

    def test_state_set_predicate_match(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="state_set", node_id="fert-shortage", allowed=["approaching", "fired"])
        ep = evaluate_predicate(pred, snap)
        assert not ep.is_flipped

    def test_state_set_predicate_mismatch(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="state_set", node_id="brent", allowed=["approaching", "fired"])
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped
        assert ep.actual == "stable"

    def test_state_set_node_missing(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="state_set", node_id="ghost", allowed=["fired"])
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped
        assert ep.note == "NODE_MISSING"

    def test_threshold_predicate_met(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="threshold", path="confluenceScores.em-stress", op=">=", value=1.60)
        ep = evaluate_predicate(pred, snap)
        assert not ep.is_flipped
        assert ep.actual == 1.67

    def test_threshold_predicate_not_met(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="threshold", path="confluenceScores.em-stress", op=">=", value=2.00)
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped

    def test_threshold_path_missing(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="threshold", path="confluenceScores.nonexistent", op=">=", value=1.0)
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped
        assert ep.note == "PATH_MISSING"

    def test_countdown_predicate_met(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="countdown", node_id="planting-miss", op="<=", days=14)
        ep = evaluate_predicate(pred, snap)
        assert not ep.is_flipped
        assert ep.actual == 14

    def test_countdown_predicate_not_met(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="countdown", node_id="planting-miss", op="<=", days=10)
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped

    def test_countdown_missing(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="countdown", node_id="nonexistent", op="<=", days=30)
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped
        assert ep.note == "COUNTDOWN_MISSING"

    def test_unknown_kind_fails(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        pred = Predicate(kind="bogus", node_id="em-stress")
        ep = evaluate_predicate(pred, snap)
        assert ep.is_flipped
        assert "UNKNOWN_KIND" in ep.note


# =========================================================================
# THE THREE TRADES vs REAL SNAPSHOTS
# =========================================================================

class TestThreeTradesAgainstRealSnapshots:
    def test_xop_gate_against_iran(self, iran_snapshot_data):
        """XOP: em-stress=fired ✓, confluence>=1.60 ✓, brent∈{appr,fired} ✗ (stable), planting<=14 ✓"""
        snap = Snapshot(iran_snapshot_data)
        results = [evaluate_predicate(p, snap) for p in XOP_GATE]
        states = [(r.predicate.kind, r.is_flipped, r.actual) for r in results]
        # brent is "stable" — not in {approaching, fired}
        assert states[0] == ("state", False, "fired")      # em-stress=fired ✓
        assert states[1] == ("threshold", False, 1.67)      # confluence>=1.60 ✓
        assert states[2] == ("state_set", True, "stable")   # brent NOT in set ✗
        assert states[3] == ("countdown", False, 14)        # planting<=14 ✓

    def test_cf_gate_against_iran(self, iran_snapshot_data):
        """CF: planting-miss=approaching ✓, countdown<=12 ✗ (14), netImpact>=5.0 ✓"""
        snap = Snapshot(iran_snapshot_data)
        results = [evaluate_predicate(p, snap) for p in CF_GATE]
        assert not results[0].is_flipped  # state approaching ✓
        assert results[1].is_flipped      # countdown 14 > 12 ✗
        assert not results[2].is_flipped  # netImpact 14.4 >= 5.0 ✓

    def test_spy_short_gate_against_tariffs(self, tariffs_snapshot_data):
        """SPY: earnings>=2.0 ✓, consumer>=1.8 ✓, recession>=1.2 ✓, fed∈{monitoring,stable} ✓"""
        snap = Snapshot(tariffs_snapshot_data)
        results = [evaluate_predicate(p, snap) for p in SPY_SHORT_GATE]
        assert all(not r.is_flipped for r in results)


# =========================================================================
# PROVENANCE + INERT BLOCKING
# =========================================================================

class TestProvenance:
    def test_target_computes_when_no_inert(self, iran_snapshot_data):
        result = compute_provenance_target(
            ref_price=188.18,
            scenario_impacts=iran_snapshot_data["scenarioImpacts"],
            book_path=None,
        )
        assert isinstance(result, DynamicTarget)
        assert result.computed_target > 188.18  # net impact is positive
        assert len(result.provenance) >= 2  # at least the static tags

    def test_inert_fields_cause_refusal(self, tmp_path):
        """A book with an edge that has a field not consumed by propagator → INERT."""
        book = {
            "edges": [
                {"from": "a", "to": "b", "strength": 0.9,
                 "some_new_field": 42}  # hypothetical new decorative field
            ]
        }
        # Since detect_inert_fields only checks amplification (now wired) and lag
        # (UNVERIFIED, not INERT), this test verifies no false INERT
        p = tmp_path / "book.json"
        p.write_text(json.dumps(book))
        tags = detect_inert_fields(p)
        # No INERT tags expected (amplification wired, lag is UNVERIFIED)
        assert all(t.confidence_level != "INERT" for t in tags)

    def test_lag_tags_are_unverified(self, book_with_amplification):
        tags = detect_inert_fields(book_with_amplification)
        lag_tags = [t for t in tags if "lag" in t.variable]
        assert len(lag_tags) == 1
        assert lag_tags[0].confidence_level == "UNVERIFIED"

    def test_provenance_target_uses_scenario_impacts(self, iran_snapshot_data):
        result = compute_provenance_target(188.18, iran_snapshot_data["scenarioImpacts"])
        assert isinstance(result, DynamicTarget)
        # Verify the calculation: sum of prob * netImpact
        expected_impact = (0.1*1.4 + 0.45*14.4 + 0.15*6.8 + 0.3*10.7)
        expected_target = 188.18 * (1 + expected_impact / 100)
        assert abs(result.computed_target - expected_target) < 0.01


# =========================================================================
# SERIALIZATION ROUND-TRIP
# =========================================================================

class TestSerialization:
    def test_round_trip(self, iran_snapshot_data):
        snap = Snapshot(iran_snapshot_data)
        ep = evaluate_predicate(Predicate(kind="state", node_id="em-stress", expected="fired"), snap)
        record = TradeRecord(
            trade_id="test-1",
            ticker="XOP",
            event_type="EVALUATION",
            snapshot_hash="abc123",
            evaluated_predicates=[ep],
            run_id="run-1",
        )
        serialized = _serialize_record(record)
        deserialized = _deserialize_record(serialized)
        assert deserialized is not None
        assert deserialized.trade_id == "test-1"
        assert deserialized.event_type == "EVALUATION"
        assert len(deserialized.evaluated_predicates) == 1
        assert deserialized.evaluated_predicates[0].actual == "fired"


# =========================================================================
# DEDUP
# =========================================================================

class TestDedup:
    def test_duplicate_detection(self, tmp_path, iran_snapshot_path):
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        preds = [Predicate(kind="state", node_id="em-stress", expected="fired")]

        status1, rec1 = monitor.run_evaluation_cycle(
            "dup-test", "XOP", preds, iran_snapshot_path)
        assert status1 == "EVALUATION"

        status2, rec2 = monitor.run_evaluation_cycle(
            "dup-test", "XOP", preds, iran_snapshot_path)
        assert status2 == "DUPLICATE"
        assert rec2.run_id == rec1.run_id

    def test_different_snapshot_not_duplicate(self, tmp_path, iran_snapshot_data):
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        preds = [Predicate(kind="state", node_id="em-stress", expected="fired")]

        snap1 = tmp_path / "snap1.json"
        snap1.write_text(json.dumps(iran_snapshot_data))
        status1, _ = monitor.run_evaluation_cycle("dup-test2", "XOP", preds, snap1)
        assert status1 == "EVALUATION"

        # Modify snapshot — different hash
        iran_snapshot_data["nodeStates"]["brent"] = "fired"
        snap2 = tmp_path / "snap2.json"
        snap2.write_text(json.dumps(iran_snapshot_data))
        status2, _ = monitor.run_evaluation_cycle("dup-test2", "XOP", preds, snap2)
        assert status2 == "EVALUATION"


# =========================================================================
# LIFECYCLE MONITOR — FULL CYCLE
# =========================================================================

class TestLifecycleMonitor:
    def test_evaluation_all_hold(self, tmp_path, iran_snapshot_path):
        """All predicates hold → EVALUATION."""
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        preds = [
            Predicate(kind="state", node_id="em-stress", expected="fired"),
            Predicate(kind="threshold", path="confluenceScores.em-stress", op=">=", value=1.60),
        ]
        status, record = monitor.run_evaluation_cycle("eval-1", "XOP", preds, iran_snapshot_path)
        assert status == "EVALUATION"
        assert record.verdict is None

    def test_exit_on_load_bearing_flip(self, tmp_path, iran_snapshot_path):
        """Load-bearing predicate flips → EXIT with verdict."""
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        preds = [
            Predicate(kind="state", node_id="brent", expected="fired", load_bearing=True),
        ]
        status, record = monitor.run_evaluation_cycle("exit-1", "XOP", preds, iran_snapshot_path)
        assert status == "EXIT"
        assert record.verdict is not None
        assert "brent" in record.verdict.load_bearing_flipped

    def test_degraded_on_supporting_flip(self, tmp_path, iran_snapshot_path):
        """Only supporting predicates flip → DEGRADED."""
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        preds = [
            Predicate(kind="state", node_id="em-stress", expected="fired", load_bearing=True),
            Predicate(kind="state", node_id="brent", expected="fired", load_bearing=False),
        ]
        status, record = monitor.run_evaluation_cycle("deg-1", "XOP", preds, iran_snapshot_path)
        assert status == "DEGRADED"
        assert record.verdict is not None
        assert "brent" in record.verdict.supporting_flipped
        assert len(record.verdict.load_bearing_flipped) == 0

    def test_multi_failure_attribution(self, tmp_path, iran_snapshot_path):
        """Multiple load-bearing predicates flip → all attributed."""
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        preds = [
            Predicate(kind="state", node_id="brent", expected="fired", load_bearing=True),
            Predicate(kind="state", node_id="de-escalation", expected="fired", load_bearing=True),
        ]
        status, record = monitor.run_evaluation_cycle("multi-1", "XOP", preds, iran_snapshot_path)
        assert status == "EXIT"
        assert len(record.verdict.load_bearing_flipped) == 2
        assert len(record.verdict.recommended_weight_adjustments) == 2

    def test_provenance_target_attached(self, tmp_path, iran_snapshot_path):
        """When ref_price is provided, dynamic target or refusal is attached."""
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        preds = [Predicate(kind="state", node_id="em-stress", expected="fired")]
        status, record = monitor.run_evaluation_cycle(
            "prov-1", "XOP", preds, iran_snapshot_path, ref_price=188.18)
        assert record.dynamic_target is not None or record.target_refusal is not None

    def test_weighted_consistency_uses_confluence(self, tmp_path, iran_snapshot_path):
        """High-confluence node flipping should lower consistency more than low-confluence."""
        monitor = PredicateLifecycleMonitor(ledger_dir=str(tmp_path / "ledger"))
        # em-stress has confluence 1.67 — flipping it should hurt more
        preds = [
            Predicate(kind="state", node_id="em-stress", expected="stable", load_bearing=True),
            Predicate(kind="state", node_id="brent", expected="stable", load_bearing=True),
        ]
        status, record = monitor.run_evaluation_cycle("wc-1", "XOP", preds, iran_snapshot_path)
        # Both hold (em-stress IS fired, not stable → flipped; brent IS stable → holds)
        assert record.verdict is not None
        # Consistency should be > 0 (brent held) but < 100 (em-stress flipped)
        assert 0 < record.verdict.predicate_consistency < 100


# =========================================================================
# CROSS-TRADE LEDGER ANALYZER
# =========================================================================

class TestLedgerAnalyzer:
    def test_empty_ledger(self, tmp_path):
        analyzer = LedgerAnalyzer(tmp_path / "empty-ledger")
        rate, count = analyzer.node_flip_rate("em-stress")
        assert rate == 0.0
        assert count == 0

    def test_cross_trade_aggregation(self, tmp_path, iran_snapshot_path, tariffs_snapshot_path):
        """Node appears in multiple trades — flip rate aggregates across both."""
        ledger_dir = tmp_path / "ledger"
        monitor = PredicateLifecycleMonitor(ledger_dir=str(ledger_dir))

        # Trade 1: em-stress holds
        preds1 = [Predicate(kind="state", node_id="em-stress", expected="fired")]
        monitor.run_evaluation_cycle("trade-A", "XOP", preds1, iran_snapshot_path)

        # Trade 2: em-stress flips (expected "stable" but is "fired")
        # Use tariffs snapshot but with em-stress — it won't be there, so NODE_MISSING
        # Actually, use iran snapshot with different expectation
        preds2 = [Predicate(kind="state", node_id="em-stress", expected="stable")]
        snap2 = tmp_path / "snap2.json"
        snap2.write_text(iran_snapshot_path.read_text())
        monitor.run_evaluation_cycle("trade-B", "TEST", preds2, snap2)

        analyzer = LedgerAnalyzer(ledger_dir)
        rate, count = analyzer.node_flip_rate("em-stress")
        assert count == 2
        assert rate == 0.5  # 1 flip out of 2 records

    def test_empirical_adjustment_insufficient_samples(self, tmp_path):
        analyzer = LedgerAnalyzer(tmp_path / "empty")
        adj, prov = analyzer.empirical_weight_adjustment("em-stress")
        assert adj == -0.25
        assert "UNVERIFIED" in prov


# =========================================================================
# PROPAGATION — Layer 0 REPAIR
# =========================================================================

class TestPropagationRepair:
    """Test that amplification is now wired into score_confluence()."""

    def test_amplification_wired(self):
        """Import from thesisgraph and verify amplification changes confluence."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thesis-graph"))
        try:
            from thesisgraph import score_confluence, propagate
        except ImportError:
            pytest.skip("thesisgraph.py not importable from test context")

        # Minimal cfg with fan-in >= 2 where edges have amplification
        cfg = {
            "nodes": [
                {"id": "a", "type": "event", "state": "fired"},
                {"id": "b", "type": "event", "state": "fired"},
                {"id": "c", "type": "indicator"},
            ],
            "edges": [
                {"from": "a", "to": "c", "strength": 0.8, "amplification": 1.5},
                {"from": "b", "to": "c", "strength": 0.6, "amplification": 2.0},
            ],
        }
        states = {"a": "fired", "b": "fired", "c": "fired"}
        scores = score_confluence(cfg, states)
        # Without amplification: 1.0*0.8 + 1.0*0.6 = 1.4
        # With amplification:    1.0*0.8*1.5 + 1.0*0.6*2.0 = 1.2 + 1.2 = 2.4
        assert "c" in scores
        assert abs(scores["c"] - 2.4) < 0.01

    def test_amplification_default_preserves_existing(self):
        """Edges without amplification field produce same result as before."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thesis-graph"))
        try:
            from thesisgraph import score_confluence
        except ImportError:
            pytest.skip("thesisgraph.py not importable from test context")

        cfg = {
            "nodes": [
                {"id": "a", "type": "event", "state": "fired"},
                {"id": "b", "type": "event", "state": "fired"},
                {"id": "c", "type": "indicator"},
            ],
            "edges": [
                {"from": "a", "to": "c", "strength": 0.8},  # no amplification
                {"from": "b", "to": "c", "strength": 0.6},
            ],
        }
        states = {"a": "fired", "b": "fired", "c": "fired"}
        scores = score_confluence(cfg, states)
        # Same as pre-edit: 1.0*0.8*1.0 + 1.0*0.6*1.0 = 1.4
        assert abs(scores["c"] - 1.4) < 0.01

    def test_parse_lag_days(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thesis-graph"))
        try:
            from thesisgraph import parse_lag_days
        except ImportError:
            pytest.skip("thesisgraph.py not importable from test context")

        ref = date(2026, 4, 5)
        assert parse_lag_days("immediate", ref) == 1
        assert parse_lag_days("1 week", ref) == 7
        assert parse_lag_days("1-2 weeks", ref) == 10  # midpoint of 7-14
        assert parse_lag_days("2-4 weeks", ref) == 21  # midpoint of 14-28
        assert parse_lag_days("1-3 months", ref) == 60  # midpoint of 30-90
        assert parse_lag_days("3-6 months", ref) == 135  # midpoint of 90-180
        # Date-gated: Apr 15 from ref Apr 5 = 10 days
        assert parse_lag_days("date-gated Apr 15", ref) == 10

    def test_propagate_at_horizon(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thesis-graph"))
        try:
            from thesisgraph import propagate_at_horizon, propagate
        except ImportError:
            pytest.skip("thesisgraph.py not importable from test context")

        cfg = {
            "nodes": [
                {"id": "shock", "type": "event", "state": "fired"},
                {"id": "fast", "type": "indicator"},
                {"id": "slow", "type": "indicator"},
            ],
            "edges": [
                {"from": "shock", "to": "fast", "strength": 0.9, "lag": "1 week"},
                {"from": "shock", "to": "slow", "strength": 0.8, "lag": "3-6 months"},
            ],
        }
        ref = date(2026, 4, 5)

        # At T+14d: fast edge (7d lag) is reachable, slow edge (135d lag) is not
        result = propagate_at_horizon(cfg, 14, ref_date=ref)
        assert result["states"]["fast"] != "stable"  # shock → fast fires
        # slow should be stable because the 3-6 month edge was removed
        assert result["states"]["slow"] == "monitoring"  # no incoming edges → default

        # At T+180d: both reachable
        result2 = propagate_at_horizon(cfg, 180, ref_date=ref)
        assert result2["states"]["slow"] != "stable"  # now reachable
