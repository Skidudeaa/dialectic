"""Tests for llm/trading_curator.py — TradingCuratorEngine."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from llm.trading_curator import (
    TradingCuratorEngine,
    TRADING_CURATOR_IDENTITY,
    _format_snapshot_for_prompt,
)
from models import SpeakerType
from tests.conftest import ROOM_ID, THREAD_ID


# ============================================================
# FIXTURES
# ============================================================


def make_snapshot_dict(**overrides) -> dict:
    """Create a valid snapshot dict for curator tests."""
    defaults = dict(
        v=1,
        timestamp="2026-03-29T14:00:00Z",
        title="Iran\u2013Hormuz Cascade",
        nodeStates={
            "sanctions_reimposed": "fired",
            "hormuz_closure": "approaching",
            "brent_spike": "gated",
        },
        confluenceScores={
            "oil_supply_shock": 0.78,
        },
        cascadePhase={
            "number": 2,
            "key": "escalation",
            "status": "active",
        },
        countdowns=[
            {"nodeId": "hormuz_closure", "daysRemaining": 14, "deadline": "2026-04-12"},
        ],
        marketSnapshot={"BZ=F": 82.50},
        scenarioImpacts={
            "full_closure": {"probability": 0.25, "netImpact": 15000},
        },
    )
    defaults.update(overrides)
    return defaults


def make_mock_db():
    """Create a mock DB connection with async methods."""
    db = AsyncMock()
    db.fetchval = AsyncMock(return_value=0)
    db.fetchrow = AsyncMock(return_value={"sequence": 1})
    db.fetch = AsyncMock(return_value=[])
    db.execute = AsyncMock()
    return db


def make_mock_memory():
    """Create a mock MemoryManager."""
    return AsyncMock()


# ============================================================
# TRADING_CURATOR_IDENTITY
# ============================================================


class TestTradingCuratorIdentity:
    def test_identity_is_well_formed(self):
        """Identity prompt should be a non-empty string with key sections."""
        assert isinstance(TRADING_CURATOR_IDENTITY, str)
        assert len(TRADING_CURATOR_IDENTITY) > 100

    def test_identity_contains_signal_section(self):
        """Identity prompt should instruct the curator to flag signals."""
        assert "SIGNAL" in TRADING_CURATOR_IDENTITY

    def test_identity_contains_countdown_section(self):
        """Identity prompt should instruct the curator to highlight deadlines."""
        assert "COUNTDOWN" in TRADING_CURATOR_IDENTITY

    def test_identity_contains_risk_section(self):
        """Identity prompt should instruct the curator to note risks."""
        assert "RISK" in TRADING_CURATOR_IDENTITY

    def test_identity_contains_action_section(self):
        """Identity prompt should instruct the curator to suggest actions."""
        assert "ACTION" in TRADING_CURATOR_IDENTITY

    def test_identity_contains_disagree_section(self):
        """Identity prompt should instruct the curator to flag contradictions."""
        assert "DISAGREE" in TRADING_CURATOR_IDENTITY

    def test_identity_instructs_brevity(self):
        """Identity prompt should instruct brief responses."""
        assert "brief" in TRADING_CURATOR_IDENTITY.lower() or "paragraph" in TRADING_CURATOR_IDENTITY.lower()


# ============================================================
# should_alert
# ============================================================


class TestShouldAlert:
    @pytest.mark.asyncio
    async def test_returns_true_when_user_offline(self):
        """should_alert() returns True when at least one member is offline."""
        db = make_mock_db()
        # 1 offline member
        db.fetchval = AsyncMock(return_value=1)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        result = await curator.should_alert(ROOM_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_all_online(self):
        """should_alert() returns False when no members are offline."""
        db = make_mock_db()
        # 0 offline members
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        result = await curator.should_alert(ROOM_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_both_offline(self):
        """should_alert() returns True when all members are offline."""
        db = make_mock_db()
        # 2 offline members
        db.fetchval = AsyncMock(return_value=2)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        result = await curator.should_alert(ROOM_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_queries_correct_table(self):
        """should_alert() should query room_memberships and user_presence."""
        db = make_mock_db()
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        await curator.should_alert(ROOM_ID)

        # Verify the query was called with correct args
        db.fetchval.assert_called_once()
        call_args = db.fetchval.call_args
        assert "room_memberships" in call_args[0][0]
        assert "user_presence" in call_args[0][0]
        assert call_args[0][1] == ROOM_ID


# ============================================================
# is_duplicate
# ============================================================


class TestIsDuplicate:
    @pytest.mark.asyncio
    async def test_returns_true_when_recent_alert_exists(self):
        """is_duplicate() returns True when a recent trading alert exists."""
        db = make_mock_db()
        # 1 recent alert found
        db.fetchval = AsyncMock(return_value=1)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        result = await curator.is_duplicate(ROOM_ID, THREAD_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_recent_alert(self):
        """is_duplicate() returns False when no recent trading alert exists."""
        db = make_mock_db()
        # 0 recent alerts
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        result = await curator.is_duplicate(ROOM_ID, THREAD_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_queries_messages_with_correct_params(self):
        """is_duplicate() should query messages table for LLM_ANNOTATOR type."""
        db = make_mock_db()
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        await curator.is_duplicate(ROOM_ID, THREAD_ID, window_minutes=10)

        db.fetchval.assert_called_once()
        call_args = db.fetchval.call_args
        query = call_args[0][0]
        assert "messages" in query
        assert "speaker_type" in query
        assert call_args[0][1] == THREAD_ID
        assert call_args[0][2] == SpeakerType.LLM_ANNOTATOR.value

    @pytest.mark.asyncio
    async def test_dedup_uses_metadata_source_filter(self):
        """is_duplicate() must filter on metadata->>'source' = 'trading_curator',
        NOT the old 'content LIKE %Trading%' predicate."""
        db = make_mock_db()
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        await curator.is_duplicate(ROOM_ID, THREAD_ID)

        query = db.fetchval.call_args[0][0]
        assert "metadata" in query
        assert "trading_curator" in query
        # Old fragile predicate must be gone
        assert "LIKE" not in query
        assert "Trading%" not in query


# ============================================================
# metadata tagging on insert + dedup behavior
# ============================================================


class TestCuratorMetadataTagging:
    """Verifies the curator writes metadata.source='trading_curator' on insert
    and that the new dedup filter only catches curator messages, not regular
    user messages that happen to mention 'Trading'."""

    @pytest.mark.asyncio
    async def test_dedup_returns_true_for_curator_message_in_window(self):
        """A prior curator message inside the dedup window is a duplicate."""
        db = make_mock_db()
        # Simulates: SQL count of metadata.source='trading_curator' messages
        db.fetchval = AsyncMock(return_value=1)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        assert await curator.is_duplicate(ROOM_ID, THREAD_ID) is True

    @pytest.mark.asyncio
    async def test_dedup_returns_false_for_user_message_mentioning_trading(self):
        """A regular user message containing 'Trading' must NOT be a duplicate.

        Under the old LIKE '%Trading%' predicate this would have falsely
        matched. With the metadata-source filter, the SQL count returns 0
        because the user message has no metadata.source tag.
        """
        db = make_mock_db()
        # The metadata-filtered query returns 0 even though a user message
        # with 'Trading' exists in the thread.
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        assert await curator.is_duplicate(ROOM_ID, THREAD_ID) is False

    @pytest.mark.asyncio
    async def test_generate_alert_inserts_metadata_source(self):
        """generate_alert must include metadata={'source': 'trading_curator', ...}
        in the INSERT call so future dedup checks find it."""
        from unittest.mock import patch
        from llm.trading_curator import TradingCuratorEngine

        db = make_mock_db()
        # should_alert → 1 offline; is_duplicate → 0 → not duplicate
        db.fetchval = AsyncMock(side_effect=[1, 0])
        db.fetchrow = AsyncMock(return_value={"sequence": 7})

        # Mock provider + thread messages
        fake_response = MagicMock()
        fake_response.content = "Brent spike confirmed; hormuz approaching."

        fake_provider = MagicMock()
        fake_provider.complete = AsyncMock(return_value=fake_response)

        with patch("llm.providers.get_provider", return_value=fake_provider), \
             patch("operations.get_thread_messages", new=AsyncMock(return_value=[])):
            curator = TradingCuratorEngine(db, make_mock_memory(), None)
            snapshot = make_snapshot_dict()
            result = await curator.generate_alert(ROOM_ID, THREAD_ID, snapshot)

        assert result is not None
        # Inspect the INSERT call: positional args end with the metadata dict
        insert_call = db.fetchrow.call_args
        query = insert_call[0][0]
        assert "metadata" in query
        # metadata is the last positional argument ($7)
        metadata_arg = insert_call[0][-1]
        assert isinstance(metadata_arg, dict)
        assert metadata_arg["source"] == "trading_curator"
        assert metadata_arg["snapshot_timestamp"] == snapshot["timestamp"]
        assert metadata_arg["snapshot_v"] == 1

    @pytest.mark.asyncio
    async def test_custom_window_minutes(self):
        """is_duplicate() respects the window_minutes parameter."""
        db = make_mock_db()
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        await curator.is_duplicate(ROOM_ID, THREAD_ID, window_minutes=15)

        call_args = db.fetchval.call_args
        # The cutoff datetime should be passed as the 4th positional arg (index 3)
        cutoff = call_args[0][3]
        now = datetime.now(timezone.utc)
        # Cutoff should be approximately 15 minutes ago
        expected_cutoff = now - timedelta(minutes=15)
        assert abs((cutoff - expected_cutoff).total_seconds()) < 5


# ============================================================
# generate_alert
# ============================================================


class TestGenerateAlert:
    @pytest.mark.asyncio
    async def test_returns_none_when_all_online(self):
        """generate_alert() returns None when no one is offline."""
        db = make_mock_db()
        # should_alert will return False (0 offline)
        db.fetchval = AsyncMock(return_value=0)

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        result = await curator.generate_alert(ROOM_ID, THREAD_ID, make_snapshot_dict())
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_duplicate(self):
        """generate_alert() returns None when a recent alert exists."""
        db = make_mock_db()
        # First call: should_alert (1 offline) → True
        # Second call: is_duplicate (1 recent) → True
        db.fetchval = AsyncMock(side_effect=[1, 1])

        curator = TradingCuratorEngine(db, make_mock_memory(), None)
        result = await curator.generate_alert(ROOM_ID, THREAD_ID, make_snapshot_dict())
        assert result is None


# ============================================================
# _format_snapshot_for_prompt
# ============================================================


class TestFormatSnapshotForPrompt:
    def test_includes_title(self):
        """Snapshot title should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "Iran" in text

    def test_includes_timestamp(self):
        """Snapshot timestamp should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "2026-03-29T14:00:00Z" in text

    def test_includes_fired_nodes(self):
        """Fired nodes should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "sanctions_reimposed" in text
        assert "Fired" in text

    def test_includes_approaching_nodes(self):
        """Approaching nodes should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "hormuz_closure" in text
        assert "Approaching" in text

    def test_excludes_gated_from_active(self):
        """Gated nodes should not appear in fired/approaching lines."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        fired_line = [l for l in text.split("\n") if "Fired" in l]
        approaching_line = [l for l in text.split("\n") if "Approaching" in l]
        all_active_text = " ".join(fired_line + approaching_line)
        assert "brent_spike" not in all_active_text

    def test_no_active_signals(self):
        """When all nodes are gated/stable, show 'No active signals'."""
        snapshot = make_snapshot_dict(nodeStates={"a": "stable", "b": "gated"})
        text = _format_snapshot_for_prompt(snapshot)
        assert "No active signals" in text

    def test_includes_countdowns(self):
        """Countdowns should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "14 days" in text
        assert "hormuz_closure" in text

    def test_includes_confluence(self):
        """Confluence scores should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "oil_supply_shock" in text
        assert "0.78" in text

    def test_includes_market_snapshot(self):
        """Market prices should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "BZ=F" in text
        assert "82.5" in text

    def test_includes_scenarios(self):
        """Scenario impacts should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "full_closure" in text
        assert "0.25" in text

    def test_includes_phase(self):
        """Cascade phase should appear in formatted output."""
        snapshot = make_snapshot_dict()
        text = _format_snapshot_for_prompt(snapshot)
        assert "escalation" in text

    def test_minimal_snapshot(self):
        """A snapshot with only required fields produces valid output."""
        snapshot = {"v": 1, "timestamp": "2026-01-01T00:00:00Z", "nodeStates": {"a": "fired"}}
        text = _format_snapshot_for_prompt(snapshot)
        assert "2026-01-01T00:00:00Z" in text
        assert "Fired" in text
        assert "a" in text
