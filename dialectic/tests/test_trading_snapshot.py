"""Tests for trading snapshot endpoint — model validation and summary formatting."""

import pytest
from pydantic import ValidationError

from models import TradingSnapshotRequest
from api.trading import format_thesis_summary


# ============================================================
# SNAPSHOT FIXTURES
# ============================================================


def make_snapshot(**overrides) -> dict:
    """Create a valid TradingSnapshotRequest dict with sensible defaults."""
    defaults = dict(
        v=1,
        timestamp="2026-03-29T14:00:00Z",
        title="Iran–Hormuz Cascade",
        nodeStates={
            "sanctions_reimposed": "fired",
            "hormuz_closure": "approaching",
            "brent_spike": "gated",
            "tanker_reroute": "stable",
        },
        confluenceScores={
            "oil_supply_shock": 0.78,
            "shipping_disruption": 0.45,
        },
        cascadePhase={
            "number": 2,
            "key": "escalation",
            "status": "active",
        },
        countdowns=[
            {"nodeId": "hormuz_closure", "daysRemaining": 14, "deadline": "2026-04-12"},
            {"nodeId": "sanctions_review", "daysRemaining": 45, "deadline": "2026-05-13"},
        ],
        marketSnapshot={
            "BZ=F": 82.50,
            "CL=F": 78.30,
        },
        scenarioImpacts={
            "full_closure": {"probability": 0.25, "netImpact": 15000},
            "partial_disruption": {"probability": 0.55, "netImpact": 4200},
        },
        portfolioSummary={
            "monthlyBudget": 10000,
            "allocated": 7500,
            "sgov_available": 2500,
        },
    )
    defaults.update(overrides)
    return defaults


# ============================================================
# TradingSnapshotRequest VALIDATION
# ============================================================


class TestTradingSnapshotValidation:
    def test_valid_snapshot_passes(self):
        """A well-formed snapshot dict should parse without error."""
        data = make_snapshot()
        snap = TradingSnapshotRequest(**data)
        assert snap.v == 1
        assert snap.timestamp == "2026-03-29T14:00:00Z"
        assert "sanctions_reimposed" in snap.nodeStates

    def test_missing_v_field_fails(self):
        """The 'v' field is required — omitting it should raise ValidationError."""
        data = make_snapshot()
        del data["v"]
        with pytest.raises(ValidationError) as exc_info:
            TradingSnapshotRequest(**data)
        assert "v" in str(exc_info.value)

    def test_missing_timestamp_fails(self):
        """The 'timestamp' field is required."""
        data = make_snapshot()
        del data["timestamp"]
        with pytest.raises(ValidationError):
            TradingSnapshotRequest(**data)

    def test_missing_nodeStates_fails(self):
        """The 'nodeStates' field is required."""
        data = make_snapshot()
        del data["nodeStates"]
        with pytest.raises(ValidationError):
            TradingSnapshotRequest(**data)

    def test_oversized_node_id_fails(self):
        """Node IDs longer than 50 characters should be rejected."""
        long_key = "x" * 51
        data = make_snapshot(nodeStates={long_key: "fired"})
        with pytest.raises(ValidationError) as exc_info:
            TradingSnapshotRequest(**data)
        assert "50 characters" in str(exc_info.value)

    def test_node_id_at_limit_passes(self):
        """A 50-character node ID should be accepted."""
        key_50 = "a" * 50
        data = make_snapshot(nodeStates={key_50: "approaching"})
        snap = TradingSnapshotRequest(**data)
        assert key_50 in snap.nodeStates

    def test_oversized_title_fails(self):
        """Titles longer than 200 characters should be rejected."""
        data = make_snapshot(title="T" * 201)
        with pytest.raises(ValidationError) as exc_info:
            TradingSnapshotRequest(**data)
        assert "200 characters" in str(exc_info.value)

    def test_newlines_stripped_from_node_keys_and_values(self):
        """Newlines in nodeStates keys and values should be replaced with spaces."""
        data = make_snapshot(nodeStates={"line\none": "fir\ned"})
        snap = TradingSnapshotRequest(**data)
        assert "line one" in snap.nodeStates
        assert snap.nodeStates["line one"] == "fir ed"

    def test_optional_fields_default_to_none(self):
        """Omitting optional fields should produce None, not errors."""
        data = dict(v=1, timestamp="2026-01-01T00:00:00Z", nodeStates={"a": "stable"})
        snap = TradingSnapshotRequest(**data)
        assert snap.confluenceScores is None
        assert snap.cascadePhase is None
        assert snap.countdowns is None
        assert snap.marketSnapshot is None
        assert snap.scenarioImpacts is None
        assert snap.portfolioSummary is None
        assert snap.title is None

    def test_v2_accepted_at_model_layer(self):
        """v=2 is the current shape (added tvIndicators overlay block).
        Both v=1 and v=2 must validate; only other values fail."""
        data = make_snapshot(v=2)
        snap = TradingSnapshotRequest(**data)
        assert snap.v == 2

    def test_v3_rejected_at_model_layer(self):
        """v=3 (or any unknown future value) should fail Literal[1, 2] validation."""
        data = make_snapshot(v=3)
        with pytest.raises(ValidationError) as exc_info:
            TradingSnapshotRequest(**data)
        assert "v" in str(exc_info.value).lower() or "literal" in str(exc_info.value).lower()


class TestSnapshotEndpointVersioning:
    """Endpoint-level test that v not in {1, 2} returns HTTP 400 with spec message.

    NOTE: Uses a thin TestClient that monkeypatches verify_room_token + db so
    no live Postgres is required.
    """

    def test_v3_returns_400_from_endpoint(self):
        """Unknown future version → 400 with the 'expected 1 or 2' message."""
        from fastapi.testclient import TestClient
        import api.main as main_mod

        app = main_mod.app

        # Stub out the auth + db dependencies so we exercise the version check
        # before any DB call.
        async def _fake_db():
            yield object()

        app.dependency_overrides[main_mod.get_db] = _fake_db
        app.dependency_overrides[main_mod.extract_room_token] = lambda: "dummy-token"

        try:
            client = TestClient(app)
            payload = make_snapshot(v=3)
            response = client.post(
                "/rooms/00000000-0000-0000-0000-000000000001/trading/snapshot",
                json=payload,
                headers={"X-Room-Token": "dummy-token"},
            )
            assert response.status_code == 400
            body = response.json()
            assert "Unsupported snapshot version" in body["detail"]
            assert "expected 1 or 2" in body["detail"]
        finally:
            app.dependency_overrides.clear()


# ============================================================
# format_thesis_summary
# ============================================================


class TestFormatThesisSummary:
    def test_includes_timestamp(self):
        """Summary should include the snapshot timestamp."""
        snap = TradingSnapshotRequest(**make_snapshot())
        summary = format_thesis_summary(snap)
        assert "2026-03-29T14:00:00Z" in summary

    def test_includes_phase(self):
        """Summary should include cascade phase info."""
        snap = TradingSnapshotRequest(**make_snapshot())
        summary = format_thesis_summary(snap)
        assert "Phase: 2" in summary
        assert "escalation" in summary
        assert "active" in summary

    def test_includes_fired_and_approaching_nodes(self):
        """Summary should list fired and approaching nodes as 'Active'."""
        snap = TradingSnapshotRequest(**make_snapshot())
        summary = format_thesis_summary(snap)
        assert "Fired: sanctions_reimposed" in summary
        assert "Approaching: hormuz_closure" in summary

    def test_excludes_stable_and_gated_from_active(self):
        """Stable and gated nodes should not appear in the Active line."""
        snap = TradingSnapshotRequest(**make_snapshot())
        summary = format_thesis_summary(snap)
        # The active line should not contain gated or stable nodes
        active_line = [l for l in summary.split("\n") if l.startswith("Active:")][0]
        assert "brent_spike" not in active_line
        assert "tanker_reroute" not in active_line

    def test_no_active_signals(self):
        """When all nodes are stable/gated, summary shows 'No active signals'."""
        snap = TradingSnapshotRequest(**make_snapshot(
            nodeStates={"a": "stable", "b": "gated"}
        ))
        summary = format_thesis_summary(snap)
        assert "No active signals" in summary

    def test_includes_confluence_scores(self):
        """Summary should include confluence scores."""
        snap = TradingSnapshotRequest(**make_snapshot())
        summary = format_thesis_summary(snap)
        assert "Confluence:" in summary
        assert "oil_supply_shock: 0.78" in summary
        assert "shipping_disruption: 0.45" in summary

    def test_includes_countdowns(self):
        """Summary should include countdown info."""
        snap = TradingSnapshotRequest(**make_snapshot())
        summary = format_thesis_summary(snap)
        assert "Countdowns:" in summary
        assert "hormuz_closure: 14d remaining" in summary
        assert "sanctions_review: 45d remaining" in summary

    def test_no_phase_omits_phase_line(self):
        """When cascadePhase is None, the Phase line should be absent."""
        snap = TradingSnapshotRequest(**make_snapshot(cascadePhase=None))
        summary = format_thesis_summary(snap)
        assert "Phase:" not in summary

    def test_no_confluence_omits_confluence_line(self):
        """When confluenceScores is None, the Confluence line should be absent."""
        snap = TradingSnapshotRequest(**make_snapshot(confluenceScores=None))
        summary = format_thesis_summary(snap)
        assert "Confluence:" not in summary

    def test_no_countdowns_omits_countdowns_line(self):
        """When countdowns is None, the Countdowns line should be absent."""
        snap = TradingSnapshotRequest(**make_snapshot(countdowns=None))
        summary = format_thesis_summary(snap)
        assert "Countdowns:" not in summary

    def test_minimal_snapshot_produces_valid_summary(self):
        """A snapshot with only required fields should produce a coherent summary."""
        snap = TradingSnapshotRequest(
            v=1,
            timestamp="2026-01-01T00:00:00Z",
            nodeStates={"trigger_a": "fired"},
        )
        summary = format_thesis_summary(snap)
        assert "Thesis Graph State (2026-01-01T00:00:00Z)" in summary
        assert "Fired: trigger_a" in summary
        # No Phase, Confluence, or Countdowns lines
        assert "Phase:" not in summary
        assert "Confluence:" not in summary
        assert "Countdowns:" not in summary
