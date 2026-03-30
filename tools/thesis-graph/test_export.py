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

# Add parent dir to path so we can import the module
sys.path.insert(0, os.path.dirname(__file__))
from thesisgraph import (
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
    "portfolioSummary",
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
        assert parsed["v"] == 1
        assert isinstance(parsed["nodeStates"], dict)

    def test_version_is_1(self, cfg, evaluated):
        states, confluence, phase_num, phase_key, scenarios_result = evaluated
        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        assert snapshot["v"] == 1

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
        assert ms["brent"] == 112.57
        # Gold spot should be from marketFields value, not dxy-stress node current
        assert ms["goldSpot"] == 4492

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
        assert snapshot["v"] == 1
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
            assert snapshot["v"] == 1
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
