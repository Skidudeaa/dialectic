"""
Tests for cross-book confluence scanner and morning brief generator.
"""

import json
import pytest
from pathlib import Path
from datetime import date

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cross_book import scan_cross_book, CrossBookReport, CrossBookFlag, save_cross_book_flags
from morning_brief import generate_brief
from lifecycle_monitor import Snapshot


@pytest.fixture
def iran_data():
    return {
        "v": 1, "timestamp": "2026-04-01T06:49:12Z",
        "title": "Iran/Hormuz Thesis",
        "nodeStates": {"hormuz": "fired", "em-stress": "fired", "demand-destruction": "fired",
                       "brent": "approaching", "planting-miss": "approaching"},
        "confluenceScores": {"em-stress": 1.67},
        "cascadePhase": {"number": 3, "key": "amplification", "status": "APPROACHING"},
        "countdowns": [{"nodeId": "planting-miss", "label": "Planting Miss", "deadline": "2026-04-15", "daysRemaining": 10}],
        "marketSnapshot": {"brent": 112.57, "goldSpot": 4492},
        "scenarioImpacts": {"closed-may": {"probability": 0.45, "netImpact": 14.4}},
        "portfolioSummary": {"monthlyBudget": 8000},
    }


@pytest.fixture
def tariffs_data():
    return {
        "v": 1, "timestamp": "2026-04-01T06:49:25Z",
        "title": "Trump Tariffs Thesis",
        "nodeStates": {"tariff-shock": "fired", "recession-risk": "fired",
                       "earnings-compression": "fired", "consumer-confidence": "fired",
                       "fed-response": "monitoring"},
        "confluenceScores": {"earnings-compression": 2.05, "consumer-confidence": 1.95, "recession-risk": 1.25},
        "cascadePhase": {"number": 3, "key": "amplification", "status": "STARTING"},
        "countdowns": [{"nodeId": "section122-expiry", "label": "Section 122", "deadline": "2026-07-24", "daysRemaining": 114}],
        "marketSnapshot": {"spx": 6370, "goldSpot": 4492, "vix": 30.97},
        "scenarioImpacts": {"deal-by-july": {"probability": 0.35, "netImpact": -0.3}},
        "portfolioSummary": {"monthlyBudget": 6000},
    }


@pytest.fixture
def snapshots_dir(tmp_path, iran_data, tariffs_data):
    d = tmp_path / "snapshots"
    d.mkdir()
    (d / "iran-hormuz-graph-latest.json").write_text(json.dumps(iran_data))
    (d / "trump-tariffs-graph-latest.json").write_text(json.dumps(tariffs_data))
    return d


# =========================================================================
# CROSS-BOOK SCANNER
# =========================================================================

class TestCrossBookScanner:
    def test_phase_alignment_detected(self, snapshots_dir):
        report = scan_cross_book(snapshots_dir)
        assert len(report.books_analyzed) == 2
        phase_flags = [f for f in report.flags if f.flag_type == "phase_alignment"]
        assert len(phase_flags) >= 1
        assert phase_flags[0].severity == "HIGH"

    def test_compound_recession_detected(self, snapshots_dir):
        report = scan_cross_book(snapshots_dir)
        recession_flags = [f for f in report.flags if f.flag_type == "compound_recession"]
        assert len(recession_flags) == 1
        assert recession_flags[0].severity in ("HIGH", "MEDIUM")
        assert "total_confluence" in recession_flags[0].data

    def test_shared_markets_detected(self, snapshots_dir):
        report = scan_cross_book(snapshots_dir)
        market_flags = [f for f in report.flags if f.flag_type == "shared_market"]
        assert len(market_flags) == 1
        assert "goldSpot" in market_flags[0].data

    def test_countdown_pressure_needs_multiple(self, snapshots_dir):
        """Only 1 countdown under 30d (planting-miss=10d). Section122=114d doesn't qualify."""
        report = scan_cross_book(snapshots_dir)
        cd_flags = [f for f in report.flags if f.flag_type == "countdown_pressure"]
        assert len(cd_flags) == 0  # need 2+ urgent countdowns

    def test_countdown_pressure_fires_with_two(self, tmp_path, iran_data, tariffs_data):
        """Both countdowns under 30d → flag fires."""
        tariffs_data["countdowns"][0]["daysRemaining"] = 20
        d = tmp_path / "urgent"
        d.mkdir()
        (d / "iran-hormuz-graph-latest.json").write_text(json.dumps(iran_data))
        (d / "trump-tariffs-graph-latest.json").write_text(json.dumps(tariffs_data))
        report = scan_cross_book(d)
        cd_flags = [f for f in report.flags if f.flag_type == "countdown_pressure"]
        assert len(cd_flags) == 1

    def test_single_book_no_flags(self, tmp_path, iran_data):
        d = tmp_path / "single"
        d.mkdir()
        (d / "iran-hormuz-graph-latest.json").write_text(json.dumps(iran_data))
        report = scan_cross_book(d)
        assert len(report.flags) == 0

    def test_save_and_load_report(self, tmp_path, snapshots_dir):
        report = scan_cross_book(snapshots_dir)
        out = tmp_path / "flags.json"
        save_cross_book_flags(report, out)
        loaded = json.loads(out.read_text())
        assert loaded["books_analyzed"] == report.books_analyzed
        assert len(loaded["flags"]) == len(report.flags)

    def test_filter_by_book_ids(self, snapshots_dir, iran_data):
        # Only analyze iran — single book, no cross-book flags
        report = scan_cross_book(snapshots_dir, book_ids=["iran-hormuz-graph"])
        assert len(report.flags) == 0

    def test_phase_divergence_detected(self, tmp_path, iran_data, tariffs_data):
        """One book at Phase 4, other at Phase 3 → divergence flag."""
        tariffs_data["cascadePhase"]["number"] = 4
        d = tmp_path / "diverge"
        d.mkdir()
        (d / "iran-hormuz-graph-latest.json").write_text(json.dumps(iran_data))
        (d / "trump-tariffs-graph-latest.json").write_text(json.dumps(tariffs_data))
        report = scan_cross_book(d)
        phase_flags = [f for f in report.flags if f.flag_type == "phase_alignment"]
        assert any("divergence" in f.detail.lower() for f in phase_flags)

    def test_compound_recession_severity(self, snapshots_dir):
        """Total confluence >= 3.0 → HIGH severity."""
        report = scan_cross_book(snapshots_dir)
        recession_flags = [f for f in report.flags if f.flag_type == "compound_recession"]
        assert len(recession_flags) == 1
        total = recession_flags[0].data.get("total_confluence", 0)
        # em-stress 1.67 + earnings-compression 2.05 + consumer-confidence 1.95 + recession-risk 1.25 = 6.92
        assert total >= 3.0
        assert recession_flags[0].severity == "HIGH"


# =========================================================================
# MORNING BRIEF
# =========================================================================

class TestMorningBrief:
    def test_generates_output(self, snapshots_dir, tmp_path):
        ledger = tmp_path / "trades"
        ledger.mkdir()
        brief = generate_brief(snapshots_dir, ledger)
        assert "MORNING BRIEF" in brief
        assert "IRAN/HORMUZ" in brief.upper() or "IRAN" in brief.upper()
        assert "TRUMP" in brief.upper() or "TARIFF" in brief.upper()

    def test_includes_hot_nodes(self, snapshots_dir, tmp_path):
        brief = generate_brief(snapshots_dir, tmp_path / "trades")
        assert "em-stress" in brief
        assert "earnings-compression" in brief

    def test_includes_countdowns(self, snapshots_dir, tmp_path):
        brief = generate_brief(snapshots_dir, tmp_path / "trades")
        assert "Planting Miss" in brief
        assert "Section 122" in brief

    def test_includes_cross_book(self, snapshots_dir, tmp_path):
        brief = generate_brief(snapshots_dir, tmp_path / "trades")
        assert "CROSS-BOOK" in brief
        assert "compound_recession" in brief or "phase_alignment" in brief

    def test_includes_scenarios(self, snapshots_dir, tmp_path):
        brief = generate_brief(snapshots_dir, tmp_path / "trades")
        assert "closed-may" in brief
        assert "deal-by-july" in brief

    def test_includes_lifecycle_events(self, tmp_path, snapshots_dir):
        """Seed a ledger entry and verify it appears in the brief."""
        ledger = tmp_path / "trades"
        ledger.mkdir()
        entry = {
            "trade_id": "TRD-XOP-TEST", "ticker": "XOP", "event_type": "ENTRY",
            "snapshot_hash": "abc", "evaluated_predicates": [], "run_id": "test-1",
            "timestamp": "2026-04-06T00:00:00Z",
        }
        (ledger / "TRD-XOP-TEST.jsonl").write_text(json.dumps(entry) + "\n")
        brief = generate_brief(snapshots_dir, ledger)
        assert "TRD-XOP-TEST" in brief

    def test_horizon_trace_in_brief(self, tmp_path):
        """v:2 snapshot with horizonTrace should show forward projection."""
        d = tmp_path / "snap"
        d.mkdir()
        data = {
            "v": 2, "timestamp": "2026-04-06T00:00:00Z", "title": "Test Book",
            "nodeStates": {"a": "fired", "b": "monitoring"},
            "confluenceScores": {},
            "cascadePhase": {"number": 2, "key": "transmission", "status": "ACTIVE"},
            "countdowns": [],
            "marketSnapshot": {},
            "scenarioImpacts": {},
            "portfolioSummary": {},
            "horizonTrace": {
                "T+7d": {"states": {"a": "fired", "b": "fired"}, "confluence": {}},
                "T+28d": {"states": {"a": "fired", "b": "fired"}, "confluence": {}},
            },
        }
        (d / "test-book-latest.json").write_text(json.dumps(data))
        brief = generate_brief(d, tmp_path / "trades")
        assert "FORWARD PROJECTION" in brief
        assert "T+7d" in brief


# =========================================================================
# SNAPSHOT V:2 — horizonTrace in lifecycle monitor
# =========================================================================

class TestSnapshotV2:
    def test_horizon_trace_accessible(self, tmp_path):
        data = {
            "v": 2, "timestamp": "T", "title": "Test",
            "nodeStates": {"a": "fired"},
            "confluenceScores": {"a": 1.5},
            "cascadePhase": {"number": 1},
            "countdowns": [],
            "marketSnapshot": {"x": 100},
            "horizonTrace": {"T+7d": {"states": {"a": "fired"}, "confluence": {}}},
        }
        snap = Snapshot(data)
        assert snap.horizon_trace["T+7d"]["states"]["a"] == "fired"
        assert snap.v == 2
