"""
Tests for v2 Pydantic schemas — snapshot, events, API, WebSocket.

WHY: These schemas are the data contracts that every downstream consumer
depends on. Round-trip validation ensures the schemas match real engine
output and catch shape drift early.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from web.schemas.snapshots import (
    ThesisSnapshot,
    CascadePhase,
    Countdown,
    HorizonEntry,
    NodeSummary,
    PortfolioSummary,
    QualityStatus,
    ScenarioImpact,
    SnapshotQuality,
    SnapshotSummary,
    TVIndicatorReading,
    Watermarks,
    ActiveOverride,
    snapshot_from_export,
)
from web.schemas.events import (
    AlertEvent,
    EventSeverity,
    EventType,
    default_severity,
    make_dedupe_key,
    severity_for_state_change,
)
from web.schemas.ws import (
    PROTOCOL_VERSION,
    BootstrapPayload,
    C2SType,
    ChatMessagePayload,
    ErrorPayload,
    PresenceChangedPayload,
    PresenceUser,
    S2CType,
    SnapshotDeltaPayload,
    WSEnvelope,
)
from web.schemas.api import (
    AlertListResponse,
    AlertSummary,
    BootstrapResponse,
    LiveResponse,
    OverrideCreateRequest,
    OverrideResponse,
    ReadyResponse,
    ScenarioEvalResponse,
    SystemStatus,
    ThesisCatalogEntry,
)


# ── Fixtures ────────────────────────────────────────────────────────────

BOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "books"
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "snapshots"


def _load_snapshot(name: str = "iran-hormuz-graph-latest.json") -> dict:
    """Load a real snapshot fixture from disk."""
    path = SNAPSHOTS_DIR / name
    if not path.exists():
        pytest.skip(f"Snapshot fixture not found: {path}")
    with open(path) as f:
        return json.load(f)


def _minimal_snapshot() -> dict:
    """Minimal valid snapshot dict for unit tests."""
    return {
        "v": 2,
        "timestamp": "2026-04-12T00:00:00Z",
        "title": "Test Thesis",
        "nodeStates": {"a": "stable", "b": "fired"},
        "confluenceScores": {"b": 1.5},
        "cascadePhase": {"number": 1, "key": "shock", "status": "ACTIVE"},
        "countdowns": [
            {"nodeId": "d", "label": "Deadline", "deadline": "2026-05-01", "daysRemaining": 19}
        ],
        "marketSnapshot": {"brent": 85.0},
        "scenarioImpacts": {
            "base": {"probability": 0.5, "netImpact": 3.2}
        },
        "portfolioSummary": {
            "monthlyBudget": 8000,
            "topPositions": ["XOP $1400/mo"],
            "sgovAvailable": 1200,
        },
        "horizonTrace": {
            "T+7d": {"states": {"a": "stable"}, "confluence": {"b": 1.0}}
        },
        "tvIndicators": {
            "brent": {"rsi14": 45.0, "atr14": 8.0, "sma50": 87.0,
                      "source": "derived_from_yahoo", "computedAt": "2026-04-12T00:00:00Z"}
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# SNAPSHOT SCHEMA
# ═══════════════════════════════════════════════════════════════════════

class TestThesisSnapshot:
    """ThesisSnapshot model validation."""

    def test_minimal_snapshot_validates(self):
        """Minimal snapshot dict validates successfully."""
        snap = ThesisSnapshot(**_minimal_snapshot())
        assert snap.v == 2
        assert snap.nodeStates["b"] == "fired"
        assert snap.cascadePhase.number == 1
        assert snap.countdowns[0].daysRemaining == 19

    def test_golden_snapshot_roundtrip(self):
        """Real iran-hormuz snapshot round-trips through the model."""
        raw = _load_snapshot()
        snap = snapshot_from_export(raw, thesis_id="iran-hormuz")
        assert snap.thesisId == "iran-hormuz"
        assert snap.v == 2
        assert isinstance(snap.nodeStates, dict)
        assert len(snap.nodeStates) > 0
        assert isinstance(snap.cascadePhase, CascadePhase)
        assert snap.cascadePhase.number > 0
        # Round-trip: serialize back to dict and compare key fields
        d = snap.model_dump()
        assert d["nodeStates"] == raw["nodeStates"]
        assert d["cascadePhase"]["key"] == raw["cascadePhase"]["key"]

    def test_trump_tariffs_snapshot_roundtrip(self):
        """Real trump-tariffs snapshot round-trips through the model."""
        raw = _load_snapshot("trump-tariffs-graph-latest.json")
        snap = snapshot_from_export(raw, thesis_id="trump-tariffs")
        assert snap.thesisId == "trump-tariffs"
        assert len(snap.nodeStates) > 0

    def test_snapshot_with_v2_fields(self):
        """Snapshot with v2 additions (thesisId, revision, quality) validates."""
        data = _minimal_snapshot()
        data["thesisId"] = "iran-hormuz"
        data["revision"] = 42
        data["definitionHash"] = "sha256:abc123"
        snap = ThesisSnapshot(**data)
        assert snap.thesisId == "iran-hormuz"
        assert snap.revision == 42
        assert snap.definitionHash == "sha256:abc123"

    def test_snapshot_missing_optional_fields(self):
        """Snapshot with no countdowns, scenarios, or horizonTrace validates."""
        data = {
            "v": 2,
            "timestamp": "2026-04-12T00:00:00Z",
            "nodeStates": {},
            "cascadePhase": {"number": 0, "key": "unknown", "status": "UNKNOWN"},
        }
        snap = ThesisSnapshot(**data)
        assert snap.countdowns == []
        assert snap.scenarioImpacts == {}
        assert snap.horizonTrace == {}
        assert snap.tvIndicators == {}

    def test_snapshot_quality_defaults_healthy(self):
        """Quality defaults to healthy status."""
        snap = ThesisSnapshot(**_minimal_snapshot())
        assert snap.quality.status == QualityStatus.healthy
        assert snap.quality.stale is False

    def test_snapshot_quality_degraded(self):
        """Quality can be set to degraded with issues."""
        data = _minimal_snapshot()
        snap = ThesisSnapshot(
            **data,
            quality=SnapshotQuality(
                status=QualityStatus.degraded,
                stale=True,
                issues=["Yahoo Finance timeout"],
            ),
        )
        assert snap.quality.status == QualityStatus.degraded
        assert snap.quality.stale is True
        assert "Yahoo Finance timeout" in snap.quality.issues

    def test_invalid_quality_status_rejects(self):
        """Invalid quality.status value is rejected."""
        with pytest.raises(Exception):
            SnapshotQuality(status="exploding")

    def test_scenario_probability_range(self):
        """ScenarioImpact validates probability in [0, 1]."""
        ScenarioImpact(probability=0.0, netImpact=0)
        ScenarioImpact(probability=1.0, netImpact=5.0)
        with pytest.raises(Exception):
            ScenarioImpact(probability=1.5, netImpact=0)
        with pytest.raises(Exception):
            ScenarioImpact(probability=-0.1, netImpact=0)

    def test_countdown_days_remaining_non_negative(self):
        """Countdown rejects negative daysRemaining."""
        Countdown(nodeId="x", label="X", deadline="2026-01-01", daysRemaining=0)
        with pytest.raises(Exception):
            Countdown(nodeId="x", label="X", deadline="2026-01-01", daysRemaining=-1)

    def test_snapshot_from_export_adapter(self):
        """snapshot_from_export wraps export_state output correctly."""
        raw = _minimal_snapshot()
        snap = snapshot_from_export(raw, thesis_id="test")
        assert snap.thesisId == "test"
        assert snap.title == "Test Thesis"
        assert snap.tvIndicators["brent"].rsi14 == 45.0

    def test_active_override_in_snapshot(self):
        """Snapshot with activeOverrides list validates."""
        data = _minimal_snapshot()
        data["activeOverrides"] = [{
            "overrideId": "ov-1",
            "targetType": "node",
            "targetId": "brent",
            "field": "current",
            "value": 120.0,
            "actor": "amo",
            "reason": "Manual price override",
            "createdAt": "2026-04-12T00:00:00Z",
            "expiresAt": "2026-04-12T02:00:00Z",
        }]
        snap = ThesisSnapshot(**data)
        assert len(snap.activeOverrides) == 1
        assert snap.activeOverrides[0].actor == "amo"


# ═══════════════════════════════════════════════════════════════════════
# EVENT SCHEMA
# ═══════════════════════════════════════════════════════════════════════

class TestAlertEvent:
    """AlertEvent model and helpers."""

    def test_valid_event(self):
        """Valid AlertEvent with all fields."""
        evt = AlertEvent(
            event_id=str(uuid.uuid4()),
            thesis_id="iran-hormuz",
            revision=42,
            event_type=EventType.node_state_changed,
            severity=EventSeverity.critical,
            node_id="brent",
            old_value="approaching",
            new_value="fired",
            occurred_at="2026-04-12T00:00:00Z",
            dedupe_key="iran-hormuz:node.state_changed:brent:42",
        )
        assert evt.event_type == EventType.node_state_changed
        assert evt.severity == EventSeverity.critical

    def test_invalid_event_type_rejects(self):
        """Unknown event_type is rejected."""
        with pytest.raises(Exception):
            AlertEvent(
                event_id="x",
                thesis_id="t",
                event_type="node.exploded",
                severity=EventSeverity.info,
                occurred_at="2026-04-12T00:00:00Z",
                dedupe_key="t:node.exploded::0",
            )

    def test_dedupe_key_format(self):
        """make_dedupe_key produces correct format."""
        key = make_dedupe_key("iran-hormuz", EventType.node_state_changed, "brent", 42)
        assert key == "iran-hormuz:node.state_changed:brent:42"

    def test_dedupe_key_no_node(self):
        """make_dedupe_key handles None node_id."""
        key = make_dedupe_key("iran-hormuz", EventType.phase_changed, None, 5)
        assert key == "iran-hormuz:phase.changed::5"

    def test_dedupe_key_no_revision(self):
        """make_dedupe_key handles None revision."""
        key = make_dedupe_key("iran-hormuz", EventType.journal_created, "brent", None)
        assert key == "iran-hormuz:journal.created:brent:"

    def test_severity_for_fired(self):
        """Node firing is critical."""
        assert severity_for_state_change("approaching", "fired") == EventSeverity.critical

    def test_severity_for_approaching(self):
        """Node approaching is warning."""
        assert severity_for_state_change("stable", "approaching") == EventSeverity.warning

    def test_severity_for_stable(self):
        """Node returning to stable is info."""
        assert severity_for_state_change("approaching", "stable") == EventSeverity.info

    def test_default_severity_mapping(self):
        """All event types have default severity mappings."""
        for et in EventType:
            sev = default_severity(et)
            assert isinstance(sev, EventSeverity)

    def test_phase_change_is_critical(self):
        """Phase changes default to critical."""
        assert default_severity(EventType.phase_changed) == EventSeverity.critical


# ═══════════════════════════════════════════════════════════════════════
# WEBSOCKET PROTOCOL
# ═══════════════════════════════════════════════════════════════════════

class TestWSProtocol:
    """WebSocket envelope and typed messages."""

    def test_envelope_defaults(self):
        """WSEnvelope has correct defaults."""
        env = WSEnvelope(type="ping", ts="2026-04-12T00:00:00Z")
        assert env.v == PROTOCOL_VERSION
        assert env.payload == {}
        assert env.seq is None

    def test_envelope_with_thesis_scope(self):
        """Envelope with thesis-scoped fields."""
        env = WSEnvelope(
            type=S2CType.snapshot_delta,
            ts="2026-04-12T00:00:00Z",
            thesisId="iran-hormuz",
            revision=42,
            seq=7,
            payload={"changedNodes": {"brent": "fired"}},
        )
        assert env.thesisId == "iran-hormuz"
        assert env.revision == 42
        assert env.seq == 7

    def test_bootstrap_payload(self):
        """BootstrapPayload validates with snapshot and catalog."""
        bp = BootstrapPayload(
            snapshot=_minimal_snapshot(),
            thesisCatalog=[{"thesisId": "iran-hormuz", "title": "Iran"}],
            seq=0,
        )
        assert bp.snapshot is not None
        assert len(bp.thesisCatalog) == 1

    def test_delta_payload_partial(self):
        """SnapshotDeltaPayload with only changed nodes."""
        dp = SnapshotDeltaPayload(
            changedNodes={"brent": "fired"},
            seq=5,
        )
        assert dp.changedNodes == {"brent": "fired"}
        assert dp.phaseChange is None

    def test_chat_message_payload(self):
        """ChatMessagePayload validates."""
        msg = ChatMessagePayload(
            id="msg-1", room_id="room-1", user="amo", content="hello"
        )
        assert msg.msg_type == "user"

    def test_error_payload(self):
        """ErrorPayload with message and code."""
        err = ErrorPayload(message="Rate limited", code="rate_limit")
        assert err.code == "rate_limit"

    def test_presence_changed_payload(self):
        """PresenceChangedPayload validates with human + agent rows."""
        payload = PresenceChangedPayload(
            users=[
                PresenceUser(
                    user_id="amo",
                    book_id="iran-hormuz",
                    last_activity="2026-04-24T12:00:00Z",
                    kind="human",
                ),
                PresenceUser(
                    user_id="agent",
                    book_id="iran-hormuz",
                    last_activity="2026-04-24T12:00:00Z",
                    kind="agent",
                    status="thinking",
                ),
            ],
            generated_at="2026-04-24T12:00:00Z",
        )
        assert len(payload.users) == 2
        assert payload.users[1].kind == "agent"
        assert payload.users[1].status == "thinking"

    def test_s2c_types_exhaustive(self):
        """All expected S2C types exist."""
        expected = {
            "bootstrap", "snapshot.full", "snapshot.delta",
            "alert.created", "override.changed", "runtime.status",
            "chat.message", "chat.typing", "chat.presence",
            "llm.chunk", "llm.done", "tv.alert",
            "price.tick",
            "presence.changed",
            "error", "ping", "pong",
        }
        actual = {t.value for t in S2CType}
        assert expected == actual

    def test_c2s_types_exhaustive(self):
        """All expected C2S types exist."""
        expected = {"send_message", "typing", "set_viewing", "subscribe", "pong", "ping"}
        actual = {t.value for t in C2SType}
        assert expected == actual


# ═══════════════════════════════════════════════════════════════════════
# API SCHEMAS
# ═══════════════════════════════════════════════════════════════════════

class TestAPISchemas:
    """REST API request/response models."""

    def test_bootstrap_response(self):
        """BootstrapResponse validates with full data."""
        resp = BootstrapResponse(
            theses=[ThesisCatalogEntry(thesisId="iran-hormuz", title="Iran", nodeCount=16)],
            snapshots={"iran-hormuz": _minimal_snapshot()},
            activeOverrides={"iran-hormuz": []},
            alertSummary=AlertSummary(critical=1, warning=2, info=5, total=8),
            system=SystemStatus(uptime_seconds=3600, scheduler_running=True, theses_loaded=2),
        )
        assert len(resp.theses) == 1
        assert resp.alertSummary.total == 8

    def test_override_create_request(self):
        """OverrideCreateRequest validates target types."""
        req = OverrideCreateRequest(
            thesisId="iran-hormuz",
            targetType="node",
            targetId="brent",
            field="current",
            value=120.0,
            reason="Testing override",
            expiresInMinutes=120,
        )
        assert req.expiresInMinutes == 120

    def test_override_create_invalid_target_type(self):
        """Invalid targetType rejected."""
        with pytest.raises(Exception):
            OverrideCreateRequest(
                thesisId="t", targetType="banana", targetId="x",
                field="f", value=1,
            )

    def test_scenario_eval_response(self):
        """ScenarioEvalResponse with revision binding."""
        resp = ScenarioEvalResponse(
            baseRevision=42,
            scenarioId="closed-may",
            label="Hormuz closed May",
            probability=0.45,
            changedNodes={"brent": {"old": "approaching", "new": "fired"}},
            portfolioImpact={"netPct": 12.8},
            explanation="Brent fires on closure probability increase",
        )
        assert resp.baseRevision == 42

    def test_health_live(self):
        """LiveResponse validates."""
        resp = LiveResponse(uptime_seconds=100.5)
        assert resp.status == "ok"

    def test_health_ready(self):
        """ReadyResponse with not-ready state."""
        resp = ReadyResponse(
            status="not_ready",
            db_writable=True,
            coordinator_initialized=True,
            first_tick_completed=False,
            detail="Waiting for first evaluation cycle",
        )
        assert resp.status == "not_ready"

    def test_alert_list_response(self):
        """AlertListResponse with pagination."""
        resp = AlertListResponse(events=[], total=0, hasMore=False)
        assert resp.total == 0
