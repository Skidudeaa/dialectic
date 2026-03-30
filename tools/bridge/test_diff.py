#!/usr/bin/env python3
"""
Tests for diff-snapshots.py

Runs with: pytest tools/bridge/test_diff.py -q
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).parent / "diff-snapshots.py")


# =========================================================================
# FIXTURES — reusable snapshot builders
# =========================================================================

def make_snapshot(**overrides) -> dict:
    """Build a minimal valid snapshot, with optional overrides."""
    base = {
        "v": 1,
        "timestamp": "2026-03-30T14:00:00Z",
        "title": "Test Snapshot",
        "nodeStates": {
            "hormuz": "fired",
            "brent": "approaching",
            "diesel": "fired",
            "fert-shortage": "approaching",
        },
        "confluenceScores": {
            "em-stress": 1.30,
        },
        "cascadePhase": {
            "number": 2,
            "key": "transmission",
            "status": "STARTING",
        },
        "countdowns": [
            {"nodeId": "planting-miss", "label": "Planting Cycle Miss", "deadline": "2026-04-15", "daysRemaining": 17},
        ],
        "marketSnapshot": {
            "brent": 112.57,
            "diesel": 5.38,
            "nolaFert": 683,
            "dxy": 100.18,
        },
        "scenarioImpacts": {
            "closed-may": {"probability": 0.45, "netImpact": 12.8},
        },
        "portfolioSummary": {
            "monthlyBudget": 8000,
            "topPositions": ["XOP $1400/mo", "XLE $1200/mo"],
            "sgovAvailable": 1200,
        },
    }
    base.update(overrides)
    return base


def write_snapshot(tmp_dir: Path, name: str, snap: dict) -> Path:
    """Write a snapshot dict to a JSON file and return its path."""
    p = tmp_dir / name
    p.write_text(json.dumps(snap, indent=2))
    return p


def run_diff(old_path: str, new_path: str) -> tuple[dict, int]:
    """Run diff-snapshots.py and return (parsed_output, exit_code)."""
    result = subprocess.run(
        [sys.executable, SCRIPT, str(old_path), str(new_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 2:
        return {"error": result.stderr.strip()}, 2
    output = json.loads(result.stdout) if result.stdout.strip() else {}
    return output, result.returncode


# =========================================================================
# TESTS — state changes
# =========================================================================

class TestStateChanges:
    """Two snapshots with node state transitions."""

    def test_single_state_transition(self, tmp_path):
        old = make_snapshot()
        new = make_snapshot(nodeStates={
            "hormuz": "fired",
            "brent": "fired",  # changed from approaching
            "diesel": "fired",
            "fert-shortage": "approaching",
        })
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert delta["hasChanges"] is True
        assert len(delta["stateChanges"]) == 1
        assert delta["stateChanges"][0] == {
            "nodeId": "brent",
            "from": "approaching",
            "to": "fired",
        }

    def test_multiple_state_transitions(self, tmp_path):
        old = make_snapshot()
        new = make_snapshot(nodeStates={
            "hormuz": "fired",
            "brent": "fired",
            "diesel": "approaching",  # changed
            "fert-shortage": "fired",  # changed
        })
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert len(delta["stateChanges"]) == 3
        node_ids = [c["nodeId"] for c in delta["stateChanges"]]
        assert "brent" in node_ids
        assert "diesel" in node_ids
        assert "fert-shortage" in node_ids


# =========================================================================
# TESTS — identical snapshots
# =========================================================================

class TestIdenticalSnapshots:
    """Identical snapshots produce empty delta."""

    def test_identical_snapshots_no_changes(self, tmp_path):
        snap = make_snapshot()
        old_p = write_snapshot(tmp_path, "old.json", snap)
        new_p = write_snapshot(tmp_path, "new.json", snap)

        delta, code = run_diff(old_p, new_p)

        assert code == 1
        assert delta["hasChanges"] is False
        assert delta["stateChanges"] == []
        assert delta["confluenceChanges"] == {}
        assert delta["countdownChanges"] == []
        assert delta["marketChanges"] == {}
        assert delta["newNodes"] == []
        assert delta["removedNodes"] == []


# =========================================================================
# TESTS — market changes
# =========================================================================

class TestMarketChanges:
    """Market price moves with correct pctChange."""

    def test_market_price_increase(self, tmp_path):
        old = make_snapshot()
        new = make_snapshot(marketSnapshot={
            "brent": 114.20,  # up from 112.57
            "diesel": 5.38,
            "nolaFert": 683,
            "dxy": 100.18,
        })
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert "brent" in delta["marketChanges"]
        brent = delta["marketChanges"]["brent"]
        assert brent["from"] == 112.57
        assert brent["to"] == 114.20
        # pctChange = (114.20 - 112.57) / 112.57 * 100 ≈ 1.45
        assert abs(brent["pctChange"] - 1.45) < 0.1

    def test_market_price_decrease(self, tmp_path):
        old = make_snapshot()
        new = make_snapshot(marketSnapshot={
            "brent": 112.57,
            "diesel": 4.90,  # down from 5.38
            "nolaFert": 683,
            "dxy": 100.18,
        })
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert "diesel" in delta["marketChanges"]
        diesel = delta["marketChanges"]["diesel"]
        assert diesel["from"] == 5.38
        assert diesel["to"] == 4.90
        assert diesel["pctChange"] < 0  # negative

    def test_multiple_market_moves(self, tmp_path):
        old = make_snapshot()
        new = make_snapshot(marketSnapshot={
            "brent": 115.00,
            "diesel": 5.50,
            "nolaFert": 700,
            "dxy": 100.18,  # unchanged
        })
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert len(delta["marketChanges"]) == 3
        assert "dxy" not in delta["marketChanges"]


# =========================================================================
# TESTS — confluence changes
# =========================================================================

class TestConfluenceChanges:
    """Confluence score movements with delta."""

    def test_confluence_score_increase(self, tmp_path):
        old = make_snapshot()
        new = make_snapshot(confluenceScores={"em-stress": 1.75})
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert "em-stress" in delta["confluenceChanges"]
        em = delta["confluenceChanges"]["em-stress"]
        assert em["from"] == 1.30
        assert em["to"] == 1.75
        assert abs(em["delta"] - 0.45) < 0.001


# =========================================================================
# TESTS — countdown changes
# =========================================================================

class TestCountdownChanges:
    """Countdown daysRemaining movements."""

    def test_countdown_decrement(self, tmp_path):
        old = make_snapshot()
        new = make_snapshot(countdowns=[
            {"nodeId": "planting-miss", "label": "Planting Cycle Miss", "deadline": "2026-04-15", "daysRemaining": 16},
        ])
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert len(delta["countdownChanges"]) == 1
        assert delta["countdownChanges"][0] == {
            "nodeId": "planting-miss",
            "from": 17,
            "to": 16,
        }


# =========================================================================
# TESTS — node addition / removal
# =========================================================================

class TestNodeAddedRemoved:
    """Nodes added or removed between snapshots."""

    def test_node_added(self, tmp_path):
        old = make_snapshot()
        new_states = dict(old["nodeStates"])
        new_states["freight"] = "fired"
        new = make_snapshot(nodeStates=new_states)
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert "freight" in delta["newNodes"]
        assert delta["removedNodes"] == []

    def test_node_removed(self, tmp_path):
        old = make_snapshot()
        new_states = dict(old["nodeStates"])
        del new_states["diesel"]
        new = make_snapshot(nodeStates=new_states)
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert "diesel" in delta["removedNodes"]
        assert delta["newNodes"] == []

    def test_node_added_and_removed(self, tmp_path):
        old = make_snapshot()
        new_states = dict(old["nodeStates"])
        del new_states["diesel"]
        new_states["freight"] = "approaching"
        new = make_snapshot(nodeStates=new_states)
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert "freight" in delta["newNodes"]
        assert "diesel" in delta["removedNodes"]


# =========================================================================
# TESTS — error paths
# =========================================================================

class TestErrorPaths:
    """Missing file and invalid JSON produce exit code 2."""

    def test_missing_old_file(self, tmp_path):
        new_p = write_snapshot(tmp_path, "new.json", make_snapshot())
        missing = tmp_path / "nonexistent.json"

        _, code = run_diff(missing, new_p)

        assert code == 2

    def test_missing_new_file(self, tmp_path):
        old_p = write_snapshot(tmp_path, "old.json", make_snapshot())
        missing = tmp_path / "nonexistent.json"

        _, code = run_diff(old_p, missing)

        assert code == 2

    def test_invalid_json(self, tmp_path):
        old_p = write_snapshot(tmp_path, "old.json", make_snapshot())
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{")

        _, code = run_diff(old_p, bad)

        assert code == 2

    def test_non_object_json(self, tmp_path):
        old_p = write_snapshot(tmp_path, "old.json", make_snapshot())
        arr = tmp_path / "arr.json"
        arr.write_text("[1, 2, 3]")

        _, code = run_diff(old_p, arr)

        assert code == 2


# =========================================================================
# TESTS — edge cases
# =========================================================================

class TestEdgeCases:
    """Empty sections, missing keys, zero values."""

    def test_empty_node_states(self, tmp_path):
        """Snapshots with no nodeStates still diff cleanly."""
        old = make_snapshot(nodeStates={})
        new = make_snapshot(nodeStates={})
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        # Other sections still have data, so there may be no changes in states
        assert delta["stateChanges"] == []
        assert delta["newNodes"] == []
        assert delta["removedNodes"] == []

    def test_missing_optional_sections(self, tmp_path):
        """Snapshots missing optional sections don't crash."""
        old = {"v": 1, "timestamp": "2026-03-30T14:00:00Z"}
        new = {"v": 1, "timestamp": "2026-03-30T14:00:00Z"}
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 1
        assert delta["hasChanges"] is False

    def test_new_market_key_added(self, tmp_path):
        """A new market data key in the new snapshot is detected."""
        old = make_snapshot(marketSnapshot={"brent": 112.57})
        new = make_snapshot(marketSnapshot={"brent": 112.57, "natgas": 3.50})
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert "natgas" in delta["marketChanges"]
        assert delta["marketChanges"]["natgas"]["pctChange"] is None

    def test_confluence_key_removed(self, tmp_path):
        """A confluence key present in old but missing in new is flagged."""
        old = make_snapshot(confluenceScores={"em-stress": 1.30})
        new = make_snapshot(confluenceScores={})
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert "em-stress" in delta["confluenceChanges"]
        assert delta["confluenceChanges"]["em-stress"]["from"] == 1.30
        assert delta["confluenceChanges"]["em-stress"]["to"] is None

    def test_countdown_added(self, tmp_path):
        """A new countdown in the new snapshot appears in changes."""
        old = make_snapshot(countdowns=[])
        new = make_snapshot(countdowns=[
            {"nodeId": "planting-miss", "label": "Planting Cycle Miss", "deadline": "2026-04-15", "daysRemaining": 17},
        ])
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert len(delta["countdownChanges"]) == 1
        assert delta["countdownChanges"][0]["nodeId"] == "planting-miss"
        assert "from" not in delta["countdownChanges"][0]
        assert delta["countdownChanges"][0]["to"] == 17

    def test_zero_price_old_value(self, tmp_path):
        """Zero old price avoids division by zero in pctChange."""
        old = make_snapshot(marketSnapshot={"weird": 0})
        new = make_snapshot(marketSnapshot={"weird": 5.0})
        old_p = write_snapshot(tmp_path, "old.json", old)
        new_p = write_snapshot(tmp_path, "new.json", new)

        delta, code = run_diff(old_p, new_p)

        assert code == 0
        assert delta["marketChanges"]["weird"]["pctChange"] is None
