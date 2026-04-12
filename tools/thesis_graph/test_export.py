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
    "portfolioSummary", "horizonTrace", "tvIndicators",
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
                    # 30 closes, final 4 above 115 consecutively
                    "closes": [100 + i * 0.5 for i in range(26)] + [115.5, 116, 117, 118],
                    "highs": [],
                    "lows": [],
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

    def test_compute_derived_bumps_closes_observed(self):
        cfg = self._make_cfg_with_derived(level=115, closes_required=3)
        brent = cfg["nodes"][0]
        assert brent.get("closesObserved", 0) == 0
        compute_derived_indicators(cfg)
        # The fixture ends in 4 consecutive closes >= 115 → counter = 4
        assert brent.get("closesObserved") == 4

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
