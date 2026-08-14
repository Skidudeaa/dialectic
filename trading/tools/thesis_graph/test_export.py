"""Tests for --export-state functionality in thesisgraph.py."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# WHY: Package import via pip install -e . (pyproject.toml).
from tools.thesis_graph.thesisgraph import (
    compute_derived_indicators,
    eval_node_state,
    export_state,
    load_config,
    propagate,
    score_confluence,
    get_current_phase,
    eval_scenario,
)

GRAPH_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "books", "iran-hormuz-graph.json")
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "thesisgraph.py")

# Required top-level keys per INTEGRATION.md snapshot schema
REQUIRED_KEYS = {
    "v", "timestamp", "title", "nodeStates", "confluenceScores",
    "cascadePhase", "countdowns", "marketSnapshot", "scenarioImpacts",
    "portfolioSummary", "horizonTrace", "tvIndicators", "feedFreshness",
}


@pytest.fixture
def cfg():
    """Load the Iran/Hormuz graph config."""
    return load_config(GRAPH_PATH)


@pytest.fixture
def evaluated(cfg):
    """Run full evaluation pipeline, return all components."""
    states = propagate(cfg)
    confluence = score_confluence(cfg, states)
    phase_num, phase_key = get_current_phase(cfg)
    scenarios_result = []
    for scenario in cfg.get("scenarios", []):
        new_states, impact = eval_scenario(cfg, scenario)
        scenarios_result.append((scenario, new_states, impact))
    return states, confluence, phase_num, phase_key, scenarios_result


# =========================================================================
# Unit tests for export_state()
# =========================================================================

class TestExportStateFunction:
    """Test the export_state() function directly."""

    def test_produces_valid_json_with_all_required_keys(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        # All required keys present
        assert REQUIRED_KEYS == set(snapshot.keys()), (
            f"Missing: {REQUIRED_KEYS - set(snapshot.keys())}, "
            f"Extra: {set(snapshot.keys()) - REQUIRED_KEYS}"
        )

    def test_json_serializable(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        # Must serialize without error
        result = json.dumps(snapshot, indent=2, ensure_ascii=False)
        # Must round-trip
        parsed = json.loads(result)
        assert parsed["v"] == 2
        assert isinstance(parsed["nodeStates"], dict)

    def test_version_is_1(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        assert snapshot["v"] == 2

    def test_timestamp_is_utc_iso(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        ts = snapshot["timestamp"]
        assert ts.endswith("Z")
        # Must parse as valid datetime
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")

    def test_title_from_config(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        assert snapshot["title"] == cfg["meta"]["title"]

    def test_node_states_all_present(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        # Every node in the config should appear in nodeStates
        for node in cfg["nodes"]:
            assert node["id"] in snapshot["nodeStates"]

    def test_cascade_phase_structure(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        cp = snapshot["cascadePhase"]
        assert "number" in cp
        assert "key" in cp
        assert "status" in cp
        assert isinstance(cp["number"], int)

    def test_countdowns_for_deadline_nodes(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        # Use a fixed date so the test is deterministic
        fixed_today = date(2026, 3, 29)
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result, today=fixed_today)
        countdowns = snapshot["countdowns"]
        assert len(countdowns) > 0
        cd = countdowns[0]
        assert cd["nodeId"] == "planting-miss"
        assert cd["deadline"] == "2026-04-15"
        # 2026-04-15 minus 2026-03-29 = 17 days
        assert cd["daysRemaining"] == 17

    def test_countdown_past_deadline_shows_zero(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        # Use a date after the deadline
        far_future = date(2026, 6, 1)
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result, today=far_future)
        countdowns = snapshot["countdowns"]
        for cd in countdowns:
            assert cd["daysRemaining"] == 0, (
                f"Past-deadline node {cd['nodeId']} should show 0, got {cd['daysRemaining']}"
            )

    def test_market_snapshot_from_market_fields(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        ms = snapshot["marketSnapshot"]
        assert "brent" in ms
        # WHY: Value comes from marketFields[].value, which may be updated by
        # live price fetches. Assert it matches the config's own marketField.
        brent_mf = next((mf for mf in cfg.get("marketFields", []) if mf.get("key") == "brent"), None)
        assert brent_mf is not None
        assert ms["brent"] == brent_mf["value"]
        # Gold spot should be from marketFields value, not dxy-stress node current
        gold_mf = next((mf for mf in cfg.get("marketFields", []) if mf.get("key") == "goldSpot"), None)
        assert gold_mf is not None
        assert ms["goldSpot"] == gold_mf["value"]

    def test_scenario_impacts_all_scenarios(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        si = snapshot["scenarioImpacts"]
        scenario_ids = [s.get("id") for s in cfg["scenarios"]]
        for sid in scenario_ids:
            assert sid in si, f"Scenario {sid} missing from scenarioImpacts"
            assert "probability" in si[sid]
            assert "netImpact" in si[sid]

    def test_portfolio_summary_structure(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        ps = snapshot["portfolioSummary"]
        assert ps["monthlyBudget"] == 8000
        assert isinstance(ps["topPositions"], list)
        assert len(ps["topPositions"]) > 0
        # Each position should be "TICKER $X/mo" format
        for pos in ps["topPositions"]:
            assert "/mo" in pos
            assert "$" in pos
        assert ps["sgovAvailable"] == 1200


class TestExportStateEdgeCases:
    """Test edge cases for export_state()."""

    def test_empty_graph_produces_valid_json(self):
        """A minimal graph with no fired nodes still produces valid JSON."""
        minimal_cfg = {
            "meta": {"title": "Minimal"},
            "nodes": [
                {"id": "a", "label": "A", "type": "indicator"},
                {"id": "b", "label": "B", "type": "indicator"},
            ],
            "edges": [{"from": "a", "to": "b", "strength": 0.5}],
        }
        states = propagate(minimal_cfg)
        confluence = score_confluence(minimal_cfg, states)
        phase_num, phase_key = get_current_phase(minimal_cfg)
        snapshot = export_state(minimal_cfg, states, confluence, phase_num, phase_key, [])

        assert REQUIRED_KEYS == set(snapshot.keys())
        assert snapshot["v"] == 2
        # No fired nodes
        fired = [nid for nid, s in snapshot["nodeStates"].items() if s == "fired"]
        assert len(fired) == 0
        # Valid JSON
        json.dumps(snapshot)

    def test_no_scenarios_produces_empty_impacts(self):
        """Graph with no scenarios produces empty scenarioImpacts."""
        cfg = {
            "meta": {"title": "No Scenarios"},
            "nodes": [{"id": "x", "label": "X", "type": "event", "state": "active"}],
            "edges": [],
        }
        states = propagate(cfg)
        confluence = score_confluence(cfg, states)
        snapshot = export_state(cfg, states, confluence, 1, "shock", [])
        assert snapshot["scenarioImpacts"] == {}

    def test_no_instruments_produces_empty_portfolio(self):
        """Graph with no instruments produces sensible portfolio summary."""
        cfg = {
            "meta": {"title": "No Instruments"},
            "nodes": [{"id": "x", "label": "X", "type": "event", "state": "active"}],
            "edges": [],
        }
        states = propagate(cfg)
        confluence = score_confluence(cfg, states)
        snapshot = export_state(cfg, states, confluence, 1, "shock", [])
        assert snapshot["portfolioSummary"]["monthlyBudget"] == 0
        assert snapshot["portfolioSummary"]["topPositions"] == []
        assert snapshot["portfolioSummary"]["sgovAvailable"] == 0

    def test_no_deadline_nodes_produces_empty_countdowns(self):
        """Graph with no deadline nodes produces empty countdowns."""
        cfg = {
            "meta": {"title": "No Deadlines"},
            "nodes": [
                {"id": "a", "label": "A", "type": "price", "current": 100, "thresholds": [{"level": 90}]},
            ],
            "edges": [],
        }
        states = propagate(cfg)
        confluence = score_confluence(cfg, states)
        snapshot = export_state(cfg, states, confluence, 1, "shock", [])
        assert snapshot["countdowns"] == []


# =========================================================================
# CLI integration tests
# =========================================================================

class TestCLIExportState:
    """Test --export-state via the actual CLI."""

    def test_export_to_file_produces_valid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        try:
            result = subprocess.run(
                [sys.executable, SCRIPT_PATH, GRAPH_PATH, "--export-state", out_path],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            with open(out_path) as f:
                snapshot = json.load(f)
            assert REQUIRED_KEYS == set(snapshot.keys())
        finally:
            os.unlink(out_path)

    def test_export_to_stdout_produces_valid_json(self):
        result = subprocess.run(
            [sys.executable, SCRIPT_PATH, GRAPH_PATH, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # stdout should be valid JSON
        snapshot = json.loads(result.stdout)
        assert REQUIRED_KEYS == set(snapshot.keys())

    def test_stdout_mode_no_status_in_stdout(self):
        """When --export-state -, stdout must be clean JSON with no status messages."""
        result = subprocess.run(
            [sys.executable, SCRIPT_PATH, GRAPH_PATH, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        # stdout must start with { (JSON)
        stdout = result.stdout.strip()
        assert stdout.startswith("{"), f"stdout starts with: {stdout[:50]!r}"
        assert stdout.endswith("}")
        # Status messages should be in stderr
        assert "Loading:" in result.stderr
        assert "Title:" in result.stderr

    def test_export_with_output_generates_both(self):
        """--export-state with -o generates both JSON and HTML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "snap.json")
            html_path = os.path.join(tmpdir, "graph.html")
            result = subprocess.run(
                [sys.executable, SCRIPT_PATH, GRAPH_PATH,
                 "--export-state", json_path, "-o", html_path, "--force"],
                capture_output=True, text=True, timeout=60,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            # Both files should exist
            assert os.path.isfile(json_path), "JSON file not created"
            assert os.path.isfile(html_path), "HTML file not created"
            # JSON should be valid
            with open(json_path) as f:
                snapshot = json.load(f)
            assert snapshot["v"] == 2
            # HTML should be non-trivial
            assert os.path.getsize(html_path) > 10000

    def test_export_without_output_skips_html(self):
        """--export-state without -o should not generate HTML."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name
        try:
            result = subprocess.run(
                [sys.executable, SCRIPT_PATH, GRAPH_PATH,
                 "--export-state", json_path],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            # Should mention export, not HTML generation
            combined = result.stdout + result.stderr
            assert "Generating HTML" not in combined
        finally:
            os.unlink(json_path)

    def test_creates_parent_directories(self):
        """--export-state should create parent dirs if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            deep_path = os.path.join(tmpdir, "a", "b", "c", "snap.json")
            result = subprocess.run(
                [sys.executable, SCRIPT_PATH, GRAPH_PATH,
                 "--export-state", deep_path],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            assert os.path.isfile(deep_path)
            with open(deep_path) as f:
                json.load(f)  # Must be valid JSON


# =========================================================================
# Unit tests for eval_node_state()
# =========================================================================

class TestEvalNodeState:
    """Direct unit tests for eval_node_state across all 8 node types."""

    # --- Event nodes ---

    def test_event_active_fires(self):
        node = {"id": "e1", "type": "event", "state": "active"}
        assert eval_node_state(node, {}, []) == "fired"

    def test_event_fired_state_fires(self):
        node = {"id": "e1", "type": "event", "state": "fired"}
        assert eval_node_state(node, {}, []) == "fired"

    def test_event_partial_approaching(self):
        node = {"id": "e1", "type": "event", "state": "partial"}
        assert eval_node_state(node, {}, []) == "approaching"

    def test_event_resolved_stable(self):
        node = {"id": "e1", "type": "event", "state": "resolved"}
        assert eval_node_state(node, {}, []) == "stable"

    def test_event_no_state_monitoring(self):
        node = {"id": "e1", "type": "event"}
        assert eval_node_state(node, {}, []) == "monitoring"

    def test_event_unknown_state_monitoring(self):
        node = {"id": "e1", "type": "event", "state": "dormant"}
        assert eval_node_state(node, {}, []) == "monitoring"

    # --- Price nodes ---

    def test_price_above_threshold_fires(self):
        node = {"id": "p1", "type": "price", "current": 120,
                "thresholds": [{"level": 100}]}
        assert eval_node_state(node, {}, []) == "fired"

    def test_price_exactly_at_threshold_fires(self):
        node = {"id": "p1", "type": "price", "current": 100,
                "thresholds": [{"level": 100}]}
        assert eval_node_state(node, {}, []) == "fired"

    def test_price_closes_required_positive_approaching(self):
        """closesRequired > 0 gates firing -- returns approaching instead."""
        node = {"id": "p1", "type": "price", "current": 120,
                "thresholds": [{"level": 100, "closesRequired": 3}]}
        assert eval_node_state(node, {}, []) == "approaching"

    def test_price_closes_required_zero_fires(self):
        """closesRequired: 0 is no gating -- should fire normally."""
        node = {"id": "p1", "type": "price", "current": 120,
                "thresholds": [{"level": 100, "closesRequired": 0}]}
        assert eval_node_state(node, {}, []) == "fired"

    def test_price_closes_required_absent_fires(self):
        """No closesRequired key at all -- should fire normally."""
        node = {"id": "p1", "type": "price", "current": 120,
                "thresholds": [{"level": 100}]}
        assert eval_node_state(node, {}, []) == "fired"

    def test_price_within_5pct_of_lowest_approaching(self):
        """Current within 5% of the lowest threshold => approaching."""
        node = {"id": "p1", "type": "price", "current": 96,
                "thresholds": [{"level": 100}]}
        # 96/100 = 0.96 >= 0.95 => approaching
        assert eval_node_state(node, {}, []) == "approaching"

    def test_price_well_below_stable(self):
        node = {"id": "p1", "type": "price", "current": 50,
                "thresholds": [{"level": 100}]}
        assert eval_node_state(node, {}, []) == "stable"

    def test_price_no_current_monitoring(self):
        node = {"id": "p1", "type": "price",
                "thresholds": [{"level": 100}]}
        assert eval_node_state(node, {}, []) == "monitoring"

    def test_price_no_thresholds_monitoring(self):
        node = {"id": "p1", "type": "price", "current": 120,
                "thresholds": []}
        assert eval_node_state(node, {}, []) == "monitoring"

    def test_price_multiple_thresholds_highest_match(self):
        """With multiple thresholds, fires at the highest breached level."""
        node = {"id": "p1", "type": "price", "current": 115,
                "thresholds": [{"level": 100}, {"level": 110}, {"level": 130}]}
        # Sorted descending: 130, 110, 100. current < 130, >= 110 => fired at 110
        assert eval_node_state(node, {}, []) == "fired"

    def test_price_multiple_thresholds_highest_has_closes_required(self):
        """Highest breached threshold has closesRequired -- approaching."""
        node = {"id": "p1", "type": "price", "current": 115,
                "thresholds": [{"level": 100}, {"level": 110, "closesRequired": 5}]}
        assert eval_node_state(node, {}, []) == "approaching"

    # --- Indicator nodes ---

    def test_indicator_all_upstream_fired(self):
        edges = [{"from": "a", "to": "ind1", "strength": 0.5},
                 {"from": "b", "to": "ind1", "strength": 0.5}]
        states = {"a": "fired", "b": "fired"}
        node = {"id": "ind1", "type": "indicator"}
        assert eval_node_state(node, states, edges) == "fired"

    def test_indicator_half_fired_fires(self):
        """50% fired threshold met => fired."""
        edges = [{"from": "a", "to": "ind1", "strength": 0.5},
                 {"from": "b", "to": "ind1", "strength": 0.5}]
        states = {"a": "fired", "b": "stable"}
        node = {"id": "ind1", "type": "indicator"}
        assert eval_node_state(node, states, edges) == "fired"

    def test_indicator_minority_fired_approaching(self):
        """Less than 50% fired => approaching."""
        edges = [{"from": "a", "to": "ind1", "strength": 0.5},
                 {"from": "b", "to": "ind1", "strength": 0.5},
                 {"from": "c", "to": "ind1", "strength": 0.5}]
        states = {"a": "fired", "b": "stable", "c": "stable"}
        node = {"id": "ind1", "type": "indicator"}
        # 1 fired / 3 incoming = 0.33 < 0.5 => approaching
        assert eval_node_state(node, states, edges) == "approaching"

    def test_indicator_upstream_approaching_only(self):
        edges = [{"from": "a", "to": "ind1", "strength": 0.5}]
        states = {"a": "approaching"}
        node = {"id": "ind1", "type": "indicator"}
        assert eval_node_state(node, states, edges) == "approaching"

    def test_indicator_all_upstream_stable(self):
        edges = [{"from": "a", "to": "ind1", "strength": 0.5},
                 {"from": "b", "to": "ind1", "strength": 0.5}]
        states = {"a": "stable", "b": "stable"}
        node = {"id": "ind1", "type": "indicator"}
        assert eval_node_state(node, states, edges) == "stable"

    def test_indicator_no_incoming_edges_monitoring(self):
        node = {"id": "ind1", "type": "indicator"}
        assert eval_node_state(node, {}, []) == "monitoring"

    def test_indicator_ignores_outgoing_edges(self):
        """Only incoming edges count for indicator evaluation."""
        edges = [{"from": "ind1", "to": "downstream", "strength": 0.5}]
        states = {"downstream": "fired"}
        node = {"id": "ind1", "type": "indicator"}
        assert eval_node_state(node, states, edges) == "monitoring"

    # --- Deadline nodes ---

    def test_deadline_past_fires(self):
        yesterday = str(date.today().replace(day=date.today().day) +
                        __import__("datetime").timedelta(days=-1))
        node = {"id": "d1", "type": "deadline", "deadline": yesterday}
        assert eval_node_state(node, {}, []) == "fired"

    def test_deadline_within_7_days_approaching(self):
        in_5_days = str(date.today() + __import__("datetime").timedelta(days=5))
        node = {"id": "d1", "type": "deadline", "deadline": in_5_days}
        assert eval_node_state(node, {}, []) == "approaching"

    def test_deadline_within_14_days_upstream_approaching(self):
        """8-14 days out with upstream approaching => approaching."""
        in_10_days = str(date.today() + __import__("datetime").timedelta(days=10))
        node = {"id": "d1", "type": "deadline", "deadline": in_10_days,
                "conditions": ["upstream1.fired"]}
        states = {"upstream1": "approaching"}
        assert eval_node_state(node, states, []) == "approaching"

    def test_deadline_within_14_days_no_upstream_gated(self):
        """8-14 days out with no upstream signal => gated."""
        in_10_days = str(date.today() + __import__("datetime").timedelta(days=10))
        node = {"id": "d1", "type": "deadline", "deadline": in_10_days,
                "conditions": ["upstream1.fired"]}
        states = {"upstream1": "stable"}
        assert eval_node_state(node, states, []) == "gated"

    def test_deadline_far_future_gated(self):
        in_60_days = str(date.today() + __import__("datetime").timedelta(days=60))
        node = {"id": "d1", "type": "deadline", "deadline": in_60_days}
        assert eval_node_state(node, {}, []) == "gated"

    def test_deadline_no_date_gated(self):
        node = {"id": "d1", "type": "deadline"}
        assert eval_node_state(node, {}, []) == "gated"

    # --- Gate nodes ---

    def test_gate_always_monitoring(self):
        node = {"id": "g1", "type": "gate", "condition": "manual-check"}
        assert eval_node_state(node, {}, []) == "monitoring"

    def test_gate_with_current_still_monitoring(self):
        node = {"id": "g1", "type": "gate", "condition": "manual-check", "current": True}
        assert eval_node_state(node, {}, []) == "monitoring"

    def test_gate_empty_monitoring(self):
        node = {"id": "g1", "type": "gate"}
        assert eval_node_state(node, {}, []) == "monitoring"

    # --- Constraint nodes ---

    def test_constraint_above_threshold_constrained(self):
        node = {"id": "c1", "type": "constraint", "current": 110, "threshold": 100}
        assert eval_node_state(node, {}, []) == "constrained"

    def test_constraint_at_threshold_stable(self):
        """current == threshold => not > threshold => stable."""
        node = {"id": "c1", "type": "constraint", "current": 100, "threshold": 100}
        assert eval_node_state(node, {}, []) == "stable"

    def test_constraint_below_threshold_stable(self):
        node = {"id": "c1", "type": "constraint", "current": 80, "threshold": 100}
        assert eval_node_state(node, {}, []) == "stable"

    def test_constraint_no_current_stable(self):
        node = {"id": "c1", "type": "constraint", "threshold": 100}
        assert eval_node_state(node, {}, []) == "stable"

    def test_constraint_no_threshold_stable(self):
        node = {"id": "c1", "type": "constraint", "current": 110}
        assert eval_node_state(node, {}, []) == "stable"

    # --- Conditional nodes ---

    def test_conditional_gate_not_fired_gated(self):
        node = {"id": "cond1", "type": "conditional", "gatedBy": ["g1"]}
        states = {"g1": "monitoring"}
        assert eval_node_state(node, states, []) == "gated"

    def test_conditional_gate_fired_approaching(self):
        node = {"id": "cond1", "type": "conditional", "gatedBy": ["g1"]}
        states = {"g1": "fired"}
        assert eval_node_state(node, states, []) == "approaching"

    def test_conditional_constrained_by_active_constraint(self):
        node = {"id": "cond1", "type": "conditional",
                "gatedBy": ["g1"], "constrainedBy": ["c1"]}
        states = {"g1": "fired", "c1": "constrained"}
        assert eval_node_state(node, states, []) == "constrained"

    def test_conditional_constraint_checked_before_gate(self):
        """Constraint takes priority over gate check."""
        node = {"id": "cond1", "type": "conditional",
                "gatedBy": ["g1"], "constrainedBy": ["c1"]}
        states = {"g1": "monitoring", "c1": "constrained"}
        assert eval_node_state(node, states, []) == "constrained"

    def test_conditional_constraint_not_active_checks_gate(self):
        node = {"id": "cond1", "type": "conditional",
                "gatedBy": ["g1"], "constrainedBy": ["c1"]}
        states = {"g1": "monitoring", "c1": "stable"}
        assert eval_node_state(node, states, []) == "gated"

    def test_conditional_no_gates_no_constraints_approaching(self):
        """Empty gatedBy + constrainedBy => all gates vacuously open => approaching."""
        node = {"id": "cond1", "type": "conditional"}
        assert eval_node_state(node, {}, []) == "approaching"

    def test_conditional_multiple_gates_all_must_fire(self):
        node = {"id": "cond1", "type": "conditional", "gatedBy": ["g1", "g2"]}
        states = {"g1": "fired", "g2": "monitoring"}
        assert eval_node_state(node, states, []) == "gated"

    # --- Reversal nodes ---

    def test_reversal_below_threshold_fires(self):
        node = {"id": "r1", "type": "reversal", "current": 80, "threshold": 100}
        assert eval_node_state(node, {}, []) == "fired"

    def test_reversal_at_threshold_fires(self):
        node = {"id": "r1", "type": "reversal", "current": 100, "threshold": 100}
        assert eval_node_state(node, {}, []) == "fired"

    def test_reversal_closes_required_positive_approaching(self):
        """closesRequired > 0 gates firing -- returns approaching."""
        node = {"id": "r1", "type": "reversal", "current": 80,
                "threshold": 100, "closesRequired": 5}
        assert eval_node_state(node, {}, []) == "approaching"

    def test_reversal_closes_required_zero_fires(self):
        """closesRequired: 0 is no gating -- should fire."""
        node = {"id": "r1", "type": "reversal", "current": 80,
                "threshold": 100, "closesRequired": 0}
        assert eval_node_state(node, {}, []) == "fired"

    def test_reversal_closes_required_absent_fires(self):
        """No closesRequired key -- should fire."""
        node = {"id": "r1", "type": "reversal", "current": 80, "threshold": 100}
        assert eval_node_state(node, {}, []) == "fired"

    def test_reversal_near_threshold_approaching(self):
        """Within 12% above threshold => approaching."""
        node = {"id": "r1", "type": "reversal", "current": 108, "threshold": 100}
        # 108/100 = 1.08 < 1.12 => approaching
        assert eval_node_state(node, {}, []) == "approaching"

    def test_reversal_far_above_stable(self):
        node = {"id": "r1", "type": "reversal", "current": 200, "threshold": 100}
        # 200/100 = 2.0 >= 1.12 => stable
        assert eval_node_state(node, {}, []) == "stable"

    def test_reversal_no_data_stable(self):
        node = {"id": "r1", "type": "reversal"}
        assert eval_node_state(node, {}, []) == "stable"

    def test_reversal_no_threshold_stable(self):
        node = {"id": "r1", "type": "reversal", "current": 80}
        assert eval_node_state(node, {}, []) == "stable"


# =========================================================================
# Phase 1 TradingView integration: derived indicators + closesObserved
# =========================================================================

class TestDerivedIndicatorsFlow:
    """Seven tests covering the Phase 1 engine enrichment:
    tvIndicators top-level key, compute_derived_indicators mutation, and the
    closesObserved -> eval_node_state promotion path.
    """

    def _make_cfg_with_derived(self, level: int = 115,
                               closes_required: int = 3) -> dict:
        """Build a minimal cfg with one price node and pre-populated OHLCV."""
        # 30 closes, final 4 above 115 consecutively
        closes = [100 + i * 0.5 for i in range(26)] + [115.5, 116, 117, 118]
        # Synthetic market dates aligned 1:1 with the close series so Unit 11's
        # close_observations pipeline can key its PK off them.
        base = date(2026, 3, 1)
        dates = [(base.toordinal() + i) for i in range(len(closes))]
        iso_dates = [date.fromordinal(d).isoformat() for d in dates]
        return {
            "meta": {"title": "Unit Test Book"},
            "nodes": [
                {
                    "id": "brent",
                    "label": "Brent",
                    "type": "price",
                    "current": 116.0,
                    "thresholds": [
                        {"level": level, "label": "persistence",
                         "closesRequired": closes_required}
                    ],
                    "derivedIndicators": [
                        {"kind": "rsi", "period": 14, "symbol": "BZ=F",
                         "overlay": True},
                    ],
                },
            ],
            "edges": [],
            # Pre-populated OHLCV stash — bypasses fetch_ohlcv_for_derived.
            "_ohlcv": {
                "BZ=F": {
                    "closes": closes,
                    "highs": [],
                    "lows": [],
                    "dates": iso_dates,
                },
            },
        }

    def test_tv_indicators_top_level_key_present(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        assert "tvIndicators" in snapshot
        assert isinstance(snapshot["tvIndicators"], dict)

    def test_tv_indicators_empty_when_no_derived_specs(self):
        """A book with zero derivedIndicators specs still gets a top-level
        tvIndicators key — it's just an empty dict, NOT a missing field.

        WHY a synthetic cfg: the shipping iran-hormuz-graph has derivedIndicators
        on four nodes and those readings are persisted to disk on every fetch
        (see compute_derived_indicators → update_config_file in the main flow).
        Using the live cfg here would make this test flap based on when the
        last fetch ran.
        """
        synthetic = {
            "meta": {"title": "Synthetic"},
            "nodes": [
                {"id": "a", "label": "A", "type": "price", "current": 100,
                 "thresholds": [{"level": 110}]},
                {"id": "b", "label": "B", "type": "indicator"},
            ],
            "edges": [],
        }
        states = propagate(synthetic)
        confluence = score_confluence(synthetic, states)
        phase_num, phase_key = get_current_phase(synthetic)
        snapshot = export_state(synthetic, states, confluence, phase_num,
                                phase_key, [])
        assert snapshot["tvIndicators"] == {}

    def test_compute_derived_populates_tv_indicators(self):
        cfg = self._make_cfg_with_derived()
        compute_derived_indicators(cfg)
        brent = cfg["nodes"][0]
        assert "tvIndicators" in brent
        assert "rsi14" in brent["tvIndicators"]
        assert brent["tvIndicators"]["source"] == "derived_from_yahoo"
        assert "computedAt" in brent["tvIndicators"]

    def test_compute_derived_strips_transient_ohlcv(self):
        cfg = self._make_cfg_with_derived()
        compute_derived_indicators(cfg)
        # Transient stash must be gone — it never leaks to disk via
        # update_config_file(), which is what prevents book-JSON bloat.
        assert "_ohlcv" not in cfg

    def test_compute_derived_emits_close_events_without_mutating_closes_observed(self):
        """Unit 11: the engine stops mutating closesObserved and instead
        emits a `_close_events` list on the cfg for the coordinator to drain
        into the close_observations SQLite table.
        """
        cfg = self._make_cfg_with_derived(level=115, closes_required=3)
        brent = cfg["nodes"][0]
        assert brent.get("closesObserved", 0) == 0
        compute_derived_indicators(cfg)
        # No mutation of the node field — that is now the coordinator's job.
        assert brent.get("closesObserved", 0) == 0
        # One event per (close, threshold-with-closesRequired) pair.
        events = cfg.get("_close_events") or []
        assert len(events) == 30
        # Exactly 4 qualifying events at the tail of the series (>= 115).
        qualifying = [e for e in events if e["qualifies"]]
        assert len(qualifying) == 4
        # Each event carries the fields the coordinator needs.
        for e in events:
            assert set(e.keys()) >= {
                "node_id", "threshold_key", "threshold_level",
                "market_date", "close_value", "qualifies",
            }
            assert e["node_id"] == "brent"
            assert e["threshold_key"] == "115"

    def test_closes_observed_meets_required_promotes_to_fired(self):
        """eval_node_state must promote to fired when the counter is satisfied."""
        node = {
            "id": "brent",
            "type": "price",
            "current": 116.0,
            "thresholds": [
                {"level": 115, "label": "persistence", "closesRequired": 3}
            ],
            "closesObserved": 3,  # exactly matches
        }
        assert eval_node_state(node, {}, []) == "fired"

    def test_closes_observed_below_required_stays_approaching(self):
        """Without enough observed closes, the gate holds at approaching."""
        node = {
            "id": "brent",
            "type": "price",
            "current": 116.0,
            "thresholds": [
                {"level": 115, "label": "persistence", "closesRequired": 3}
            ],
            "closesObserved": 2,  # one short
        }
        assert eval_node_state(node, {}, []) == "approaching"


class TestPropagateAtHorizonCumulative:
    """Cumulative path-lag horizon propagation (v2 Unit 15).

    WHY: The prior implementation filtered each edge by its own lag only, so
    a two-hop chain A -(7d)-> B -(7d)-> C fired C at T+7 instead of T+14. The
    fix walks the graph to compute each node's earliest arrival time from any
    self-firing source, then keeps only edges whose cumulative arrival is
    within the horizon.
    """

    def test_two_hop_chain_does_not_fire_at_half_horizon(self):
        from tools.thesis_graph.thesisgraph import propagate_at_horizon
        cfg = {
            "meta": {"title": "two-hop"},
            "nodes": [
                {"id": "A", "label": "A", "type": "event", "state": "fired"},
                {"id": "B", "label": "B", "type": "indicator"},
                {"id": "C", "label": "C", "type": "indicator"},
            ],
            "edges": [
                {"from": "A", "to": "B", "strength": 0.9, "lag": "1 week"},
                {"from": "B", "to": "C", "strength": 0.9, "lag": "1 week"},
            ],
        }
        result = propagate_at_horizon(cfg, 7, ref_date=date(2026, 4, 5))
        assert result["states"]["B"] == "fired"
        # C's cumulative arrival is 14 days; at horizon 7, signal hasn't reached.
        assert result["states"]["C"] == "monitoring"

    def test_two_hop_chain_fires_at_full_horizon(self):
        from tools.thesis_graph.thesisgraph import propagate_at_horizon
        cfg = {
            "meta": {"title": "two-hop"},
            "nodes": [
                {"id": "A", "label": "A", "type": "event", "state": "fired"},
                {"id": "B", "label": "B", "type": "indicator"},
                {"id": "C", "label": "C", "type": "indicator"},
            ],
            "edges": [
                {"from": "A", "to": "B", "strength": 0.9, "lag": "1 week"},
                {"from": "B", "to": "C", "strength": 0.9, "lag": "1 week"},
            ],
        }
        result = propagate_at_horizon(cfg, 14, ref_date=date(2026, 4, 5))
        assert result["states"]["C"] == "fired"

    def test_single_edge_fires_at_shorter_horizon(self):
        from tools.thesis_graph.thesisgraph import propagate_at_horizon
        cfg = {
            "meta": {"title": "single-hop"},
            "nodes": [
                {"id": "A", "label": "A", "type": "event", "state": "fired"},
                {"id": "B", "label": "B", "type": "indicator"},
            ],
            "edges": [
                {"from": "A", "to": "B", "strength": 0.9, "lag": "5 days"},
            ],
        }
        result = propagate_at_horizon(cfg, 7, ref_date=date(2026, 4, 5))
        assert result["states"]["B"] == "fired"

    def test_parallel_paths_shortest_wins(self):
        """Two paths from A to D with cumulative 15d vs 10d — D arrives at 10d."""
        from tools.thesis_graph.thesisgraph import propagate_at_horizon
        cfg = {
            "meta": {"title": "parallel"},
            "nodes": [
                {"id": "A", "label": "A", "type": "event", "state": "fired"},
                {"id": "B", "label": "B", "type": "indicator"},
                {"id": "C", "label": "C", "type": "indicator"},
                {"id": "D", "label": "D", "type": "indicator"},
            ],
            "edges": [
                {"from": "A", "to": "B", "strength": 0.9, "lag": "10 days"},
                {"from": "A", "to": "C", "strength": 0.9, "lag": "5 days"},
                {"from": "B", "to": "D", "strength": 0.9, "lag": "5 days"},
                {"from": "C", "to": "D", "strength": 0.9, "lag": "5 days"},
            ],
        }
        # At T+9: C reached at 5d, D via C reached at 10d > 9 → not yet
        result_9 = propagate_at_horizon(cfg, 9, ref_date=date(2026, 4, 5))
        assert result_9["states"]["C"] == "fired"
        assert result_9["states"]["D"] == "monitoring"
        # At T+10: D via C reaches exactly
        result_10 = propagate_at_horizon(cfg, 10, ref_date=date(2026, 4, 5))
        assert result_10["states"]["D"] == "fired"

    def test_diamond_uses_shortest_arrival(self):
        """Diamond graph — downstream arrival is the shorter of two paths."""
        from tools.thesis_graph.thesisgraph import compute_arrival_times
        cfg = {
            "nodes": [
                {"id": "A", "label": "A", "type": "event", "state": "fired"},
                {"id": "B", "label": "B", "type": "indicator"},
                {"id": "C", "label": "C", "type": "indicator"},
                {"id": "D", "label": "D", "type": "indicator"},
            ],
            "edges": [
                {"from": "A", "to": "B", "lag": "2 weeks"},
                {"from": "A", "to": "C", "lag": "1 week"},
                {"from": "B", "to": "D", "lag": "1 week"},
                {"from": "C", "to": "D", "lag": "2 weeks"},
            ],
        }
        arrival = compute_arrival_times(cfg, ref_date=date(2026, 4, 5))
        assert arrival["A"] == 0
        assert arrival["B"] == 14
        assert arrival["C"] == 7
        # D via B: 14+7=21; D via C: 7+14=21. Tie here — either shortest path.
        assert arrival["D"] == 21

    def test_unreachable_node_stays_default(self):
        """A node whose only upstream never fires gets no signal at any horizon."""
        from tools.thesis_graph.thesisgraph import propagate_at_horizon
        cfg = {
            "meta": {"title": "unreachable"},
            "nodes": [
                {"id": "dormant", "label": "D", "type": "event", "state": "monitoring"},
                {"id": "child", "label": "C", "type": "indicator"},
            ],
            "edges": [
                {"from": "dormant", "to": "child", "strength": 0.9, "lag": "1 day"},
            ],
        }
        result = propagate_at_horizon(cfg, 365, ref_date=date(2026, 4, 5))
        assert result["states"]["child"] == "monitoring"


class TestValidateConfigStructured:
    """Hardened validate_config — returns structured issues, never raises (v2 Unit 15)."""

    def _errors(self, issues):
        return [i for i in issues if i["severity"] == "error"]

    def _warnings(self, issues):
        return [i for i in issues if i["severity"] == "warning"]

    def test_returns_list_of_issue_dicts(self):
        from tools.thesis_graph.thesisgraph import validate_config
        issues = validate_config({"meta": {"title": "t"}, "nodes": [], "edges": []})
        assert isinstance(issues, list)
        for issue in issues:
            assert set(issue.keys()) >= {"field", "message", "severity"}
            assert issue["severity"] in {"error", "warning"}

    def test_non_dict_input_does_not_raise(self):
        from tools.thesis_graph.thesisgraph import validate_config
        issues = validate_config("not a dict")  # type: ignore[arg-type]
        errors = self._errors(issues)
        assert any("must be a dict" in e["message"] for e in errors)

    def test_threshold_level_as_string_is_error(self):
        """'0.7' as a string level — reject, don't coerce."""
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [
                {"id": "p", "label": "P", "type": "price",
                 "thresholds": [{"level": "115", "label": "persistence"}]},
            ],
            "edges": [],
        }
        errors = self._errors(validate_config(cfg))
        assert any("thresholds[0].level" in e["field"] for e in errors)

    def test_invalid_gated_by_reference_is_error(self):
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [
                {"id": "n", "label": "N", "type": "conditional", "gatedBy": ["ghost"]},
            ],
            "edges": [],
        }
        errors = self._errors(validate_config(cfg))
        assert any("gatedBy" in e["field"] and "ghost" in e["message"] for e in errors)

    def test_scenario_probability_above_one_is_error(self):
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [], "edges": [],
            "scenarios": [{"id": "s", "probability": 1.7, "overrides": {}}],
        }
        errors = self._errors(validate_config(cfg))
        assert any("probability" in e["field"] and "[0,1]" in e["message"] for e in errors)

    def test_scenario_probability_wrong_type_is_error(self):
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [], "edges": [],
            "scenarios": [{"id": "s", "probability": "0.5", "overrides": {}}],
        }
        errors = self._errors(validate_config(cfg))
        assert any("probability" in e["field"] for e in errors)

    def test_duplicate_instrument_id_is_error(self):
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [{"id": "n", "label": "N", "type": "indicator"}],
            "edges": [],
            "instruments": {
                "n": [{"id": "XOP"}, {"id": "XOP"}],
            },
        }
        errors = self._errors(validate_config(cfg))
        assert any("duplicate instrument id" in e["message"] for e in errors)

    def test_unparseable_lag_is_warning(self):
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [
                {"id": "a", "label": "A", "type": "event", "state": "fired"},
                {"id": "b", "label": "B", "type": "indicator"},
            ],
            "edges": [{"from": "a", "to": "b", "strength": 0.5, "lag": "sometime"}],
        }
        warnings = self._warnings(validate_config(cfg))
        assert any("lag" in w["field"] for w in warnings)

    def test_all_books_validate_clean(self):
        """Every active book must validate with zero errors."""
        from tools.thesis_graph.thesisgraph import validate_config
        import glob
        books_dir = os.path.join(os.path.dirname(__file__), "..", "..", "books")
        for path in sorted(glob.glob(os.path.join(books_dir, "*.json"))):
            cfg = load_config(path)
            issues = validate_config(cfg)
            errors = self._errors(issues)
            assert not errors, f"{path} has validation errors: {errors}"

    def test_malformed_edge_does_not_crash_topo(self):
        """A missing 'to' field would KeyError in topo_sort — surface as issue, not crash."""
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [{"id": "a", "label": "A", "type": "event"}],
            "edges": [{"from": "a", "strength": 0.5}],  # missing 'to'
        }
        issues = validate_config(cfg)  # must not raise
        assert any(i["severity"] == "error" for i in issues)


class TestFeedFreshness:
    """Cockpit Unit 5: per-source freshness flows from provider → snapshot."""

    def test_fresh_unstamped_snapshot_has_empty_freshness(self, cfg, evaluated):
        """Baseline: no provider ran, snapshot carries an empty dict."""
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        assert snapshot["feedFreshness"] == {}

    def test_stamp_promotes_to_snapshot(self, cfg, evaluated):
        """A stamped source in cfg["_feed_freshness"] surfaces on the snapshot."""
        from tools.thesis_graph.thesisgraph import _stamp_feed_freshness
        _stamp_feed_freshness(cfg, source="yahoo", ttl_seconds=300,
                              detail="5/5 symbols")
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        entry = snapshot["feedFreshness"]["yahoo"]
        assert entry["source"] == "yahoo"
        assert entry["ttlSeconds"] == 300
        assert entry["detail"] == "5/5 symbols"
        # fetchedAt is ISO8601 Z — parseable
        datetime.strptime(entry["fetchedAt"], "%Y-%m-%dT%H:%M:%SZ")

    def test_multiple_sources_coexist(self, cfg, evaluated):
        """yahoo + polymarket + derived can each stamp independently."""
        from tools.thesis_graph.thesisgraph import _stamp_feed_freshness
        _stamp_feed_freshness(cfg, source="yahoo", ttl_seconds=300)
        _stamp_feed_freshness(cfg, source="polymarket", ttl_seconds=900)
        _stamp_feed_freshness(cfg, source="derived", ttl_seconds=86400)
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        assert set(snapshot["feedFreshness"].keys()) == {"yahoo", "polymarket", "derived"}
        assert snapshot["feedFreshness"]["polymarket"]["ttlSeconds"] == 900
        assert snapshot["feedFreshness"]["derived"]["ttlSeconds"] == 86400

    def test_restamp_same_source_overwrites(self, cfg, evaluated):
        """A second stamp for the same source replaces the first."""
        from tools.thesis_graph.thesisgraph import _stamp_feed_freshness
        _stamp_feed_freshness(cfg, source="yahoo", ttl_seconds=300, detail="first")
        _stamp_feed_freshness(cfg, source="yahoo", ttl_seconds=60, detail="second")
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        assert snapshot["feedFreshness"]["yahoo"]["ttlSeconds"] == 60
        assert snapshot["feedFreshness"]["yahoo"]["detail"] == "second"

    def test_schema_validates_freshness_block(self, cfg, evaluated):
        """ThesisSnapshot Pydantic model accepts the stamped dict."""
        from tools.thesis_graph.thesisgraph import _stamp_feed_freshness
        from web.schemas.snapshots import snapshot_from_export
        _stamp_feed_freshness(cfg, source="yahoo", ttl_seconds=300)
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        model = snapshot_from_export(snapshot)
        assert "yahoo" in model.feedFreshness
        assert model.feedFreshness["yahoo"].ttlSeconds == 300


class TestLagParsing:
    """Lag forms the books actually use.

    WHY these exist: 18 of the 84 edges across the four newer books declared
    their lag in quarters or as "immediate to N", both of which fell through
    to the 30d fallback. Lag drives arrival times, so china-property's
    `lgfv-default` was propagating at 30 days against a book that says two
    quarters — 6x too imminent, in the direction that gets a trade
    front-run. The validator's warning was correct and nobody read it.
    """

    @pytest.mark.parametrize("text,expected", [
        ("1 quarter", 91),
        ("2 quarters", 182),
        ("1-2 quarters", 136),
        ("3-6 quarters", 409),
        ("immediate to 1 week", 3),
        ("immediate to 2 weeks", 7),
        ("immediate to 1 month", 15),
    ])
    def test_forms_that_used_to_fall_back_to_30d(self, text, expected):
        from tools.thesis_graph.thesisgraph import parse_lag_days
        assert parse_lag_days(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("immediate", 1),
        ("1-2 weeks", 10),
        ("3 months", 90),
        ("5 days", 5),
        ("1-4 weeks (tit-for-tat)", 17),
    ])
    def test_previously_working_forms_are_unchanged(self, text, expected):
        from tools.thesis_graph.thesisgraph import parse_lag_days
        assert parse_lag_days(text) == expected

    def test_genuinely_unparseable_still_falls_back(self):
        from tools.thesis_graph.thesisgraph import parse_lag_days
        assert parse_lag_days("whenever Beijing blinks") == 30

    def test_no_shipped_book_silently_defaults(self):
        """Every declared lag must be one the parser really understands."""
        import glob
        from tools.thesis_graph.thesisgraph import parse_lag_days
        books_dir = os.path.join(os.path.dirname(__file__), "..", "..", "books")
        for path in sorted(glob.glob(os.path.join(books_dir, "*.json"))):
            book = json.loads(Path(path).read_text())
            for i, edge in enumerate(book.get("edges", [])):
                lag = edge.get("lag")
                if not isinstance(lag, str) or not lag.strip():
                    continue
                if parse_lag_days(lag) == 30 and "month" not in lag.lower():
                    pytest.fail(
                        f"{os.path.basename(path)} edges[{i}] lag {lag!r} hits the "
                        f"30d fallback — the graph propagates on a number nobody chose"
                    )


class TestFeedValidation:
    """The feed validator reads the key the books actually write.

    WHY: until 2026-08-10 this block read the SINGULAR `feed`, while all 71
    feed-bearing nodes across five books use the PLURAL `feeds`. It had
    therefore validated nothing, ever, and four permanently-dark feeds sat
    in iran-hormuz looking live in the UI.
    """

    def _issues(self, feed, severity):
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [{"id": "n", "label": "N", "type": "price", "feeds": [feed]}],
            "edges": [],
        }
        return [i for i in validate_config(cfg) if i["severity"] == severity]

    def test_a_malformed_feed_in_the_plural_list_is_caught(self):
        """The regression itself: this used to pass because nothing looked."""
        errors = self._issues({"source": "fred"}, "error")
        assert any("fred feed requires 'series'" in e["message"] for e in errors)

    def test_a_source_with_no_fetcher_warns(self):
        warnings = self._issues(
            {"source": "bls", "series": "CES0000000001"}, "warning")
        assert any("bls" in w["message"] and "dark" in w["message"]
                   for w in warnings)

    def test_plural_yahoo_symbols_warns_because_no_fetcher_reads_it(self):
        warnings = self._issues(
            {"source": "yahoo", "symbols": ["BZV26.NYM", "BZJ27.NYM"]}, "warning")
        assert any("plural 'symbols'" in w["message"] for w in warnings)

    def test_manual_is_always_accepted(self):
        """`manual` is the honest way to say a human maintains the value."""
        assert self._issues({"source": "manual", "label": "Baker Hughes"},
                            "warning") == []
        assert self._issues({"source": "manual", "label": "Baker Hughes"},
                            "error") == []

    def test_a_well_formed_feed_is_silent(self):
        assert self._issues({"source": "yahoo", "symbol": "BZ=F"}, "error") == []
        assert self._issues({"source": "yahoo", "symbol": "BZ=F"}, "warning") == []

    def test_a_parenthetical_lag_is_not_flagged(self):
        """The parser reads it fine; warning about it teaches operators to
        ignore the channel that carries the 18 real findings."""
        from tools.thesis_graph.thesisgraph import validate_config
        cfg = {
            "meta": {"title": "t"},
            "nodes": [{"id": "a", "label": "A", "type": "event"},
                      {"id": "b", "label": "B", "type": "event"}],
            "edges": [{"from": "a", "to": "b", "lag": "1-4 weeks (tit-for-tat)"}],
        }
        assert [i for i in validate_config(cfg) if "lag" in i["field"]] == []

    def test_no_shipped_book_hard_errors(self):
        """Turning the validator on must not block generation of a live book."""
        import glob
        from tools.thesis_graph.thesisgraph import validate_config
        books_dir = os.path.join(os.path.dirname(__file__), "..", "..", "books")
        for path in sorted(glob.glob(os.path.join(books_dir, "*.json"))):
            book = json.loads(Path(path).read_text())
            errors = [i for i in validate_config(book) if i["severity"] == "error"]
            assert errors == [], f"{os.path.basename(path)}: {errors}"


class TestFredUnitsWiring:
    """A percent-calibrated node must receive a percent.

    WHY: enabling the FRED key on 2026-08-09 wrote CPIAUCSL's raw index
    level (332.568) into `retail-prices`, whose thresholds are 2.5 / 3.0 /
    3.5 because they mean CPI inflation. No node state flipped — 2.7 was
    already over 2.5 — but the number an operator reads, and the number the
    LLM would quote, was off by two orders of magnitude.
    """

    def test_the_books_ask_for_pc1_on_every_index_series(self):
        """Pins the audit: these three are index levels, the rest are not."""
        import glob
        needs_pc1 = {"CPIAUCSL", "PCEPILFE", "PPIACO"}
        books_dir = os.path.join(os.path.dirname(__file__), "..", "..", "books")
        found = set()
        for path in sorted(glob.glob(os.path.join(books_dir, "*.json"))):
            for node in json.loads(Path(path).read_text()).get("nodes", []):
                for feed in (node.get("feeds") or []):
                    if not isinstance(feed, dict) or feed.get("source") != "fred":
                        continue
                    sid = feed.get("series")
                    if sid in needs_pc1:
                        found.add(sid)
                        assert feed.get("units") == "pc1", (
                            f"{sid} is an index level; without units=pc1 it lands "
                            f"in {node['id']} two orders of magnitude off"
                        )
        assert found == needs_pc1, f"missing from the books: {needs_pc1 - found}"

    def test_units_reach_the_fetcher(self, monkeypatch):
        """Drive the real fetch_fred and read what it asked FRED for."""
        import types
        from tools.thesis_graph import thesisgraph as tg

        asked = {}
        fake = types.ModuleType("fred")
        fake.FredAuthError = type("FredAuthError", (Exception,), {})

        def fetch_series_batch(series_ids, units_by_series=None, **kw):
            asked.update(units_by_series or {})
            return {s: {"value": 3.46, "observation_date": "2026-06-01"}
                    for s in series_ids}

        fake.fetch_series_batch = fetch_series_batch
        monkeypatch.setitem(sys.modules, "fred", fake)

        cfg = {"nodes": [
            {"id": "cpi", "type": "price", "current": 2.7,
             "feeds": [{"source": "fred", "series": "CPIAUCSL", "units": "pc1"}]},
            {"id": "yields", "type": "price", "current": 4.6,
             "feeds": [{"source": "fred", "series": "DGS10"}]},
        ]}
        tg.fetch_fred(cfg)

        assert asked == {"CPIAUCSL": "pc1"}, "a level series must not be transformed"


class TestGdeltFetchPlanning:
    """A watch-only GDELT node must not spend a request.

    WHY this is worth a test: `fetch_gdelt` has always refused to WRITE into
    a node with no `current` key, but it used to FETCH for one anyway and
    throw the answer away. That was invisible — the log line read
    "updated 0 node(s) from 1/1 queries", which looks like a quiet news day
    rather than a wasted call. It stopped being invisible on 2026-08-09,
    when all five books gained a watch-only rhetoric node so the news bridge
    could serve headlines: five discarded fetches per tick against GDELT's
    per-IP throttle kept the throttle warm and starved the bridge itself.
    """

    @staticmethod
    def _stub_gdelt(monkeypatch, queries):
        """Install a fake gdelt module that records every query it is asked for."""
        import types
        from tools.thesis_graph import thesisgraph as tg

        fake = types.ModuleType("gdelt")
        fake.GdeltError = type("GdeltError", (Exception,), {})
        fake.GdeltRateLimitError = type("GdeltRateLimitError", (fake.GdeltError,), {})
        fake.get_standard_query = lambda name: f"resolved:{name}"

        def fetch_volume_latest(query, timespan="1d"):
            queries.append((query, timespan))
            return 42.0

        fake.fetch_volume_latest = fetch_volume_latest
        monkeypatch.setitem(sys.modules, "gdelt", fake)
        return tg

    def test_watch_only_node_costs_no_request(self, monkeypatch):
        queries = []
        tg = self._stub_gdelt(monkeypatch, queries)
        cfg = {"nodes": [{
            "id": "rhetoric", "type": "indicator",
            "feeds": [{"source": "gdelt", "standardQuery": "iran-hormuz-event"}],
        }]}

        tg.fetch_gdelt(cfg)

        assert queries == [], "a node with no `current` must not be fetched for"

    def test_a_node_that_declares_current_is_still_fetched(self, monkeypatch):
        """The reverse direction — the guard must not mute the whole source."""
        queries = []
        tg = self._stub_gdelt(monkeypatch, queries)
        cfg = {"nodes": [{
            "id": "rhetoric", "type": "indicator", "current": 0,
            "feeds": [{"source": "gdelt", "standardQuery": "iran-hormuz-event"}],
        }]}

        tg.fetch_gdelt(cfg)

        assert queries == [("resolved:iran-hormuz-event", "1d")]
        assert cfg["nodes"][0]["current"] == 42.0

    def test_a_mixed_query_still_runs_for_the_consumer(self, monkeypatch):
        """One watch-only node must not suppress a sibling that wants the value."""
        queries = []
        tg = self._stub_gdelt(monkeypatch, queries)
        cfg = {"nodes": [
            {"id": "watch", "type": "indicator",
             "feeds": [{"source": "gdelt", "standardQuery": "shared"}]},
            {"id": "consumer", "type": "indicator", "current": 1,
             "feeds": [{"source": "gdelt", "standardQuery": "shared"}]},
        ]}

        tg.fetch_gdelt(cfg)

        assert queries == [("resolved:shared", "1d")]
        assert cfg["nodes"][0].get("current") is None
        assert cfg["nodes"][1]["current"] == 42.0

    def test_every_shipped_book_is_watch_only_today(self):
        """The books as shipped must cost GDELT nothing on the coordinator tick.

        Pins the wiring decision from 2026-08-09: the rhetoric nodes exist to
        light up `/api/bridge/news/{book}`, not to feed volume into the graph.
        Adding `current` to one is a deliberate calibration step, and this
        test is where that decision gets re-read.
        """
        import glob
        books_dir = os.path.join(os.path.dirname(__file__), "..", "..", "books")
        checked = 0
        for path in sorted(glob.glob(os.path.join(books_dir, "*.json"))):
            book = json.loads(Path(path).read_text())
            for node in book.get("nodes", []):
                if any(f.get("source") == "gdelt"
                       for f in (node.get("feeds") or []) if isinstance(f, dict)):
                    checked += 1
                    assert "current" not in node, (
                        f"{os.path.basename(path)}:{node['id']} opted into GDELT "
                        f"volume — intended? it now costs a request every tick"
                    )
        assert checked == 5, f"expected 5 gdelt nodes across the books, found {checked}"



class TestDerivedFetchWindow:
    """The fetch window is sized per symbol from the specs declared against it.

    Regression: `range=3mo` was hardcoded (63 daily bars), so ai-capex-unwind's
    `sma200` on semis-breakdown returned None on every run and was dropped
    without a word. Verified absent from the live snapshot 2026-08-14.
    """

    @staticmethod
    def _fake_chart(n_closes: int):
        """A Yahoo v8 chart payload with `n_closes` daily bars."""
        base = int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp())
        return {
            "chart": {
                "result": [{
                    "timestamp": [base + i * 86400 for i in range(n_closes)],
                    "indicators": {"quote": [{
                        "close": [100.0 + i for i in range(n_closes)],
                        "high": [101.0 + i for i in range(n_closes)],
                        "low": [99.0 + i for i in range(n_closes)],
                    }]},
                }]
            }
        }

    def _capture_urls(self, cfg, monkeypatch, n_closes=300):
        """Run the fetch against a stubbed Yahoo, return the URLs requested."""
        import tools.thesis_graph.thesisgraph as tg

        urls = []
        payload = json.dumps(self._fake_chart(n_closes)).encode()

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return payload

        def _fake_urlopen(req, timeout=None):
            urls.append(req.full_url)
            return _Resp()

        monkeypatch.setattr(tg, "urlopen", _fake_urlopen)
        monkeypatch.setattr(tg.time, "sleep", lambda *_: None)
        tg.fetch_ohlcv_for_derived(cfg)
        return urls

    def test_range_for_bars_picks_the_smallest_covering_window(self):
        from tools.thesis_graph.thesisgraph import _range_for_bars
        assert _range_for_bars(15) == "3mo"
        assert _range_for_bars(63) == "3mo"
        assert _range_for_bars(64) == "6mo"
        assert _range_for_bars(200) == "1y"
        assert _range_for_bars(252) == "1y"
        assert _range_for_bars(253) == "2y"
        assert _range_for_bars(99999) == "max"

    def test_sma200_symbol_gets_a_year_not_three_months(self, monkeypatch):
        cfg = {
            "nodes": [{
                "id": "semis-breakdown", "type": "price",
                "derivedIndicators": [
                    {"kind": "rsi", "period": 14, "symbol": "SOXX",
                     "overlay": True},
                    {"kind": "sma", "period": 200, "symbol": "SOXX",
                     "overlay": True},
                ],
            }],
        }
        urls = self._capture_urls(cfg, monkeypatch)
        assert len(urls) == 1
        assert "range=1y" in urls[0], urls[0]

    def test_an_rsi_only_symbol_keeps_its_existing_three_month_window(
            self, monkeypatch):
        """Blast radius: Wilder smoothing has a long memory tail, so a longer
        series shifts published RSI values. Symbols that never needed more
        history must keep the exact window they had, even when a SIBLING
        symbol in the same book asks for 200 bars.
        """
        cfg = {
            "nodes": [
                {"id": "a", "type": "price", "derivedIndicators": [
                    {"kind": "sma", "period": 200, "symbol": "SOXX",
                     "overlay": True}]},
                {"id": "b", "type": "price", "derivedIndicators": [
                    {"kind": "rsi", "period": 14, "symbol": "TSM",
                     "overlay": True}]},
            ],
        }
        urls = sorted(self._capture_urls(cfg, monkeypatch))
        assert any("SOXX?range=1y" in u for u in urls), urls
        assert any("TSM?range=3mo" in u for u in urls), urls

    def test_the_declared_indicator_actually_lands_end_to_end(self, monkeypatch):
        """The originating symptom: sma200 declared, snapshot silent. Drive
        fetch -> compute and assert the key is present.
        """
        import tools.thesis_graph.thesisgraph as tg
        cfg = {
            "nodes": [{
                "id": "semis-breakdown", "type": "indicator",
                "derivedIndicators": [
                    {"kind": "sma", "period": 200, "symbol": "SOXX",
                     "overlay": True},
                ],
            }],
        }
        self._capture_urls(cfg, monkeypatch)
        tg.compute_derived_indicators(cfg)
        tv = cfg["nodes"][0].get("tvIndicators") or {}
        assert "sma200" in tv, tv

    def test_short_series_reports_the_miss_instead_of_swallowing_it(
            self, monkeypatch, capsys):
        """A thin or newly-listed symbol can still under-deliver. That must be
        loud — silence is what hid the original defect.
        """
        import tools.thesis_graph.thesisgraph as tg
        cfg = {
            "nodes": [{
                "id": "semis-breakdown", "type": "indicator",
                "derivedIndicators": [
                    {"kind": "sma", "period": 200, "symbol": "SOXX",
                     "overlay": True},
                ],
            }],
        }
        self._capture_urls(cfg, monkeypatch, n_closes=40)
        tg.compute_derived_indicators(cfg)
        err = capsys.readouterr().err
        assert "semis-breakdown.sma200 not computed" in err, err
        assert "have 40" in err, err


class TestCloseEventVolume:
    """Close events are emitted per close per threshold, so the window growing
    must not multiply the SQLite upserts the coordinator performs each cycle.
    """

    @staticmethod
    def _cfg(n_closes: int) -> dict:
        base = date(2026, 1, 1)
        return {
            "nodes": [{
                "id": "brent", "type": "price", "current": 120.0,
                "thresholds": [{"level": 115, "closesRequired": 3}],
                "derivedIndicators": [
                    {"kind": "rsi", "period": 14, "symbol": "BZ=F",
                     "overlay": True}],
            }],
            "_ohlcv": {"BZ=F": {
                "closes": [100.0 + i for i in range(n_closes)],
                "highs": [], "lows": [],
                "dates": [date.fromordinal(base.toordinal() + i).isoformat()
                          for i in range(n_closes)],
            }},
        }

    def test_a_long_series_is_capped_to_the_recent_tail(self):
        from tools.thesis_graph.thesisgraph import (
            compute_derived_indicators, _CLOSE_EVENT_WINDOW)
        cfg = self._cfg(300)
        compute_derived_indicators(cfg)
        assert len(cfg["_close_events"]) == _CLOSE_EVENT_WINDOW

    def test_the_cap_never_shrinks_what_the_old_window_emitted(self):
        """63 bars was the old fixed fetch. The cap must sit above it, or this
        change would quietly starve the closesRequired streak gate.
        """
        from tools.thesis_graph.thesisgraph import _CLOSE_EVENT_WINDOW
        assert _CLOSE_EVENT_WINDOW >= 63
        cfg = self._cfg(63)
        from tools.thesis_graph.thesisgraph import compute_derived_indicators
        compute_derived_indicators(cfg)
        assert len(cfg["_close_events"]) == 63

    def test_dates_stay_aligned_after_the_tail_slice(self):
        """The slice offsets the index into dates[]. A misalignment would key
        close_observations rows to the wrong market_date — silent, and it
        would corrupt the streak the XOP gate fires on.
        """
        from tools.thesis_graph.thesisgraph import compute_derived_indicators
        cfg = self._cfg(300)
        expected_last = cfg["_ohlcv"]["BZ=F"]["dates"][-1]
        expected_last_close = cfg["_ohlcv"]["BZ=F"]["closes"][-1]
        compute_derived_indicators(cfg)
        last = cfg["_close_events"][-1]
        assert last["market_date"] == expected_last
        assert last["close_value"] == expected_last_close

    def test_repeat_specs_on_one_symbol_emit_events_once(self):
        """rsi + atr + sma on the same symbol share one close series. Emitting
        per spec meant 3x identical events per close every cycle — dedup'd by
        the close_observations PK, but paid for on every run.
        """
        from tools.thesis_graph.thesisgraph import compute_derived_indicators
        cfg = self._cfg(120)
        cfg["nodes"][0]["derivedIndicators"] = [
            {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
            {"kind": "atr", "period": 14, "symbol": "BZ=F", "overlay": True},
            {"kind": "sma", "period": 50, "symbol": "BZ=F", "overlay": True},
        ]
        compute_derived_indicators(cfg)
        events = cfg["_close_events"]
        assert len(events) == 90
        keys = {(e["node_id"], e["market_date"], e["threshold_key"])
                for e in events}
        assert len(keys) == len(events), "duplicate (node, date, threshold)"




if __name__ == "__main__":
    pytest.main([__file__, "-v"])
