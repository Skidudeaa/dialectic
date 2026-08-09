"""Unit 11 tests — close-observation table + coordinator streak patching.

WHY: The engine stops mutating `closesObserved`. The table is the canonical
source; the coordinator inserts events from derived indicators and TV webhook
mutations, then patches effective cfg from streak queries before propagate.
These tests cover the coordinator wiring and repository behavior end to end.
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from web.persistence.repository import Repository
from web.runtime.coordinator import RuntimeCoordinator


@pytest.fixture
def repo():
    r = Repository(":memory:")
    r.initialize()
    return r


@pytest.fixture
def coordinator(repo):
    ws = MagicMock()
    ws.broadcast_to_book_rooms = AsyncMock(return_value=0)
    return RuntimeCoordinator(repo=repo, ws_manager=ws, tick_interval=9999)


# ═══════════════════════════════════════════════════════════════════════
# REPOSITORY BEHAVIOUR (streak calculation + PK dedup)
# ═══════════════════════════════════════════════════════════════════════


class TestCloseObservationRepo:
    def test_streak_counts_only_consecutive_qualifying_tail(self, repo):
        # 2 qualifying, 1 break, 3 qualifying — streak should be 3, not 5.
        for i, qual in enumerate([True, True, False, True, True, True]):
            repo.insert_close_observation(
                thesis_id="t", node_id="brent",
                market_date=f"2026-04-{10+i:02d}",
                threshold_key="115",
                close_value=116.0 if qual else 114.0,
                qualifies=qual,
            )
        assert repo.get_close_streak("t", "brent", "115") == 3

    def test_streak_zero_with_no_observations(self, repo):
        assert repo.get_close_streak("t", "brent", "115") == 0

    def test_pk_dedups_same_thesis_node_date_threshold(self, repo):
        repo.insert_close_observation(
            thesis_id="t", node_id="brent", market_date="2026-04-15",
            threshold_key="115", close_value=116.0, qualifies=True,
        )
        # Second insert with same PK should be ignored (INSERT OR IGNORE).
        repo.insert_close_observation(
            thesis_id="t", node_id="brent", market_date="2026-04-15",
            threshold_key="115", close_value=117.5, qualifies=True,
        )
        assert repo.get_close_streak("t", "brent", "115") == 1

    def test_streak_isolates_by_threshold_key(self, repo):
        """Different threshold_keys on the same node track independently."""
        repo.insert_close_observation(
            "t", "brent", "2026-04-15", "115", 116.0, True,
        )
        repo.insert_close_observation(
            "t", "brent", "2026-04-15", "120", 116.0, False,
        )
        assert repo.get_close_streak("t", "brent", "115") == 1
        assert repo.get_close_streak("t", "brent", "120") == 0


# ═══════════════════════════════════════════════════════════════════════
# COORDINATOR: _persist_close_events (engine → table mapper)
# ═══════════════════════════════════════════════════════════════════════


class TestPersistCloseEvents:
    def test_drains_close_events_into_table(self, coordinator, repo):
        cfg = {
            "_close_events": [
                {"node_id": "brent", "threshold_key": "115",
                 "threshold_level": 115.0,
                 "market_date": "2026-04-10",
                 "close_value": 116.0, "qualifies": True},
                {"node_id": "brent", "threshold_key": "115",
                 "threshold_level": 115.0,
                 "market_date": "2026-04-11",
                 "close_value": 117.0, "qualifies": True},
            ]
        }
        coordinator._persist_close_events("test-thesis", cfg)
        # Events dict key is popped so the coordinator doesn't re-drain it.
        assert "_close_events" not in cfg
        assert repo.get_close_streak("test-thesis", "brent", "115") == 2

    def test_missing_events_key_is_a_noop(self, coordinator, repo):
        coordinator._persist_close_events("test-thesis", {})
        # No rows inserted.
        assert repo.get_close_streak("test-thesis", "brent", "115") == 0

    def test_malformed_event_logs_and_continues(self, coordinator, repo):
        """One bad event must not abort the whole batch."""
        cfg = {
            "_close_events": [
                {"node_id": "brent"},  # missing required keys
                {"node_id": "brent", "threshold_key": "115",
                 "threshold_level": 115.0,
                 "market_date": "2026-04-11",
                 "close_value": 116.0, "qualifies": True},
            ]
        }
        coordinator._persist_close_events("t", cfg)
        # Second event landed.
        assert repo.get_close_streak("t", "brent", "115") == 1


# ═══════════════════════════════════════════════════════════════════════
# COORDINATOR: _patch_closes_observed (table → effective cfg)
# ═══════════════════════════════════════════════════════════════════════


class TestPatchClosesObserved:
    def _seed_streak(self, repo, thesis_id, node_id, threshold_key,
                     qualifying_count: int):
        for i in range(qualifying_count):
            repo.insert_close_observation(
                thesis_id=thesis_id, node_id=node_id,
                market_date=f"2026-04-{10+i:02d}",
                threshold_key=threshold_key,
                close_value=116.0, qualifies=True,
            )

    def test_patches_from_streak_for_price_node(self, coordinator, repo):
        self._seed_streak(repo, "t", "brent", "115", 2)
        cfg = {
            "nodes": [{
                "id": "brent", "type": "price", "current": 116.0,
                "thresholds": [{"level": 115, "closesRequired": 3}],
            }],
        }
        coordinator._patch_closes_observed("t", cfg)
        assert cfg["nodes"][0]["closesObserved"] == 2

    def test_picks_highest_qualifying_threshold(self, coordinator, repo):
        """When the node has multiple thresholds, the coordinator uses the
        highest one where current >= level (matches eval_node_state's walk)."""
        self._seed_streak(repo, "t", "brent", "115", 5)
        self._seed_streak(repo, "t", "brent", "110", 10)
        cfg = {
            "nodes": [{
                "id": "brent", "type": "price", "current": 116.0,
                "thresholds": [
                    {"level": 110, "closesRequired": 1},
                    {"level": 115, "closesRequired": 3},
                ],
            }],
        }
        coordinator._patch_closes_observed("t", cfg)
        assert cfg["nodes"][0]["closesObserved"] == 5  # the 115 streak

    def test_zero_when_current_below_all_thresholds(self, coordinator, repo):
        self._seed_streak(repo, "t", "brent", "115", 5)
        cfg = {
            "nodes": [{
                "id": "brent", "type": "price", "current": 100.0,
                "thresholds": [{"level": 115, "closesRequired": 3}],
            }],
        }
        coordinator._patch_closes_observed("t", cfg)
        assert cfg["nodes"][0]["closesObserved"] == 0

    def test_ignores_nodes_without_closesrequired_threshold(self, coordinator, repo):
        """Price nodes without any closesRequired threshold are not patched."""
        cfg = {
            "nodes": [{
                "id": "brent", "type": "price", "current": 116.0,
                "thresholds": [{"level": 115}],  # no closesRequired
            }],
        }
        coordinator._patch_closes_observed("t", cfg)
        assert "closesObserved" not in cfg["nodes"][0]

    def test_ignores_non_price_reversal_nodes(self, coordinator, repo):
        cfg = {
            "nodes": [
                {"id": "ind", "type": "indicator", "current": 100.0,
                 "thresholds": [{"level": 50, "closesRequired": 3}]},
            ],
        }
        coordinator._patch_closes_observed("t", cfg)
        # Indicator type isn't in the set — left untouched.
        assert "closesObserved" not in cfg["nodes"][0]


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION: derived-events + table + patch round-trip
# ═══════════════════════════════════════════════════════════════════════


class TestDerivedEventIntegration:
    def test_same_close_from_derived_and_webhook_dedups_on_pk(self, coordinator, repo):
        """Both sources writing the same (node, date, threshold_key) result
        in one row; streak counts the close once."""
        # Derived-source insert
        repo.insert_close_observation(
            thesis_id="t", node_id="brent", market_date="2026-04-15",
            threshold_key="115", close_value=116.0, qualifies=True,
            source="derived",
        )
        # Webhook-source insert on the same PK — must be absorbed by dedup
        repo.insert_close_observation(
            thesis_id="t", node_id="brent", market_date="2026-04-15",
            threshold_key="115", close_value=116.5, qualifies=True,
            source="tv_webhook",
        )
        assert repo.get_close_streak("t", "brent", "115") == 1
