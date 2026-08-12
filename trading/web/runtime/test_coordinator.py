"""
Tests for RuntimeCoordinator — the central mutation authority.

WHY: The coordinator is the most critical v2 component. These tests verify:
definition loading, revision incrementing, lock serialization, effective
config construction, event generation, and restart recovery.
"""

import asyncio
import json
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.persistence.repository import Repository
from web.runtime.coordinator import RuntimeCoordinator, BOOKS_DIR


# WHY one helper instead of a nested `with` per fetcher: a cycle now reaches
# nine outbound calls (four fast, four slow, plus the econ calendar), and a
# test that stubs eight of them makes a real HTTP request from the suite.
# Stubbing them in one place means adding a feed to the cycle cannot leave a
# hole here — and the slow-feed refresher still RUNS, it just gets a fetcher
# that resolves nothing, which is its documented degrade path.
_FAST_FETCHERS = (
    "fetch_prices", "fetch_polymarket",
    "fetch_ohlcv_for_derived", "compute_derived_indicators",
)
_SLOW_FETCHERS = ("fetch_treasury", "fetch_gdelt", "fetch_fred", "fetch_eia")


@contextmanager
def no_network():
    """Stub every outbound call a fetch cycle can make."""
    with ExitStack() as stack:
        # web.runtime.slow_feeds.thesisgraph is the same module object, so
        # one patch target covers both call sites.
        for name in _FAST_FETCHERS + _SLOW_FETCHERS:
            stack.enter_context(patch(f"web.runtime.coordinator.thesisgraph.{name}"))
        stack.enter_context(patch(
            "web.runtime.slow_feeds.econ_calendar.get_calendar",
            AsyncMock(return_value=[]),
        ))
        yield


@pytest.fixture
def repo():
    r = Repository(":memory:")
    r.initialize()
    return r


@pytest.fixture
def ws_mock():
    """Mock WebSocket manager."""
    m = MagicMock()
    m.broadcast_to_book_rooms = AsyncMock(return_value=0)
    return m


@pytest.fixture
def coordinator(repo, ws_mock):
    """Coordinator with real books and mocked WS."""
    return RuntimeCoordinator(repo=repo, ws_manager=ws_mock, tick_interval=9999)


# ═══════════════════════════════════════════════════════════════════════
# DEFINITION LOADING
# ═══════════════════════════════════════════════════════════════════════

class TestDefinitionLoading:
    def test_loads_thesis_configs(self, coordinator):
        """Coordinator loads thesis definitions from books/."""
        # _load_definitions is called by start(), but we can test directly
        coordinator._load_definitions()
        assert len(coordinator._definitions) >= 2
        assert "iran-hormuz-graph" in coordinator._definitions
        assert "trump-tariffs-graph" in coordinator._definitions

    def test_computes_definition_hashes(self, coordinator):
        """Each loaded thesis gets a SHA-256 hash."""
        coordinator._load_definitions()
        for tid in coordinator._definitions:
            assert tid in coordinator._definition_hashes
            assert coordinator._definition_hashes[tid].startswith("sha256:")

    def test_hash_deterministic(self, coordinator):
        """Same config produces same hash."""
        coordinator._load_definitions()
        h1 = coordinator._definition_hashes["iran-hormuz-graph"]
        coordinator._load_definitions()
        h2 = coordinator._definition_hashes["iran-hormuz-graph"]
        assert h1 == h2


# ═══════════════════════════════════════════════════════════════════════
# CYCLE EXECUTION
# ═══════════════════════════════════════════════════════════════════════

class TestCycleExecution:
    @pytest.mark.asyncio
    async def test_cycle_produces_snapshot(self, coordinator, repo):
        """A single cycle produces a committed snapshot with revision."""
        coordinator._load_definitions()
        coordinator._hydrate_from_db()

        # Patch fetch to avoid network calls
        with patch.object(coordinator, '_run_cycle', wraps=coordinator._run_cycle):
            with no_network():
                result = await coordinator._run_cycle("iran-hormuz-graph")

        assert result["revision"] == 1
        assert result["thesisId"] == "iran-hormuz-graph"
        assert "nodeStates" in result
        assert "definitionHash" in result

        # Verify persisted in DB
        db_snap = repo.get_latest_snapshot("iran-hormuz-graph")
        assert db_snap is not None
        assert db_snap["_revision"] == 1

    @pytest.mark.asyncio
    async def test_revision_increments(self, coordinator, repo):
        """Sequential cycles produce incrementing revisions."""
        coordinator._load_definitions()
        coordinator._hydrate_from_db()

        with no_network():
            r1 = await coordinator._run_cycle("iran-hormuz-graph")
            r2 = await coordinator._run_cycle("iran-hormuz-graph")

        assert r1["revision"] == 1
        assert r2["revision"] == 2
        assert repo.get_latest_revision("iran-hormuz-graph") == 2


# ═══════════════════════════════════════════════════════════════════════
# SUBMIT
# ═══════════════════════════════════════════════════════════════════════

class TestSubmit:
    @pytest.mark.asyncio
    async def test_submit_unknown_thesis(self, coordinator):
        """Submit for unknown thesis raises ValueError."""
        coordinator._load_definitions()
        with pytest.raises(ValueError, match="Unknown thesis"):
            await coordinator.submit("nonexistent", "fetch_prices")

    @pytest.mark.asyncio
    async def test_submit_unknown_op(self, coordinator):
        """Submit with unknown op raises ValueError."""
        coordinator._load_definitions()
        coordinator._hydrate_from_db()
        with pytest.raises(ValueError, match="Unknown op"):
            await coordinator.submit("iran-hormuz-graph", "explode")

    @pytest.mark.asyncio
    async def test_submit_fetch_prices(self, coordinator, repo):
        """submit(fetch_prices) runs a full cycle."""
        coordinator._load_definitions()
        coordinator._hydrate_from_db()

        with no_network():
            result = await coordinator.submit("iran-hormuz-graph", "fetch_prices")

        assert result["revision"] == 1


# ═══════════════════════════════════════════════════════════════════════
# LOCK BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════

class TestLocking:
    @pytest.mark.asyncio
    async def test_same_thesis_serializes(self, coordinator):
        """Two concurrent submits for same thesis serialize."""
        coordinator._load_definitions()
        coordinator._hydrate_from_db()

        order = []

        async def slow_cycle(thesis_id):
            order.append(f"start-{len(order)}")
            return await coordinator.submit(thesis_id, "fetch_prices")

        # WHY the stub context wraps BOTH tasks rather than living inside
        # slow_cycle: two overlapping `with patch(...)` blocks on the same
        # attribute unwind in the wrong order. The first task to exit puts
        # the REAL fetcher back while the second cycle is still running — so
        # the no-network guarantee lapsed mid-test (the second cycle made
        # live HTTP calls) and the module attribute was left holding the
        # other task's mock afterwards.
        with no_network():
            t1 = asyncio.create_task(slow_cycle("iran-hormuz-graph"))
            t2 = asyncio.create_task(slow_cycle("iran-hormuz-graph"))
            r1, r2 = await asyncio.gather(t1, t2)
        # Both complete, revisions are sequential
        assert {r1["revision"], r2["revision"]} == {1, 2}

    @pytest.mark.asyncio
    async def test_different_theses_parallel(self, coordinator):
        """Submits for different theses don't block each other."""
        coordinator._load_definitions()
        coordinator._hydrate_from_db()

        with no_network():
            t1 = asyncio.create_task(
                coordinator.submit("iran-hormuz-graph", "fetch_prices")
            )
            t2 = asyncio.create_task(
                coordinator.submit("trump-tariffs-graph", "fetch_prices")
            )
            r1, r2 = await asyncio.gather(t1, t2)

        assert r1["thesisId"] == "iran-hormuz-graph"
        assert r2["thesisId"] == "trump-tariffs-graph"


# ═══════════════════════════════════════════════════════════════════════
# EVENT GENERATION
# ═══════════════════════════════════════════════════════════════════════

class TestEvents:
    def test_first_snapshot_emits_recomputed(self, coordinator):
        """First snapshot generates a snapshot.recomputed event."""
        events = coordinator._compute_events("t", 1, None, {"nodeStates": {"a": "stable"}})
        assert len(events) == 1
        assert events[0]["event_type"] == "snapshot.recomputed"

    def test_state_change_event(self, coordinator):
        """Node state change generates node.state_changed event."""
        old = {"nodeStates": {"brent": "stable"}, "cascadePhase": {"number": 1}}
        new = {"nodeStates": {"brent": "fired"}, "cascadePhase": {"number": 1}}
        events = coordinator._compute_events("t", 2, old, new)
        state_events = [e for e in events if e["event_type"] == "node.state_changed"]
        assert len(state_events) == 1
        assert state_events[0]["old_value"] == "stable"
        assert state_events[0]["new_value"] == "fired"
        assert state_events[0]["severity"] == "critical"

    def test_phase_change_event(self, coordinator):
        """Phase change generates phase.changed event."""
        old = {"nodeStates": {}, "cascadePhase": {"number": 1}}
        new = {"nodeStates": {}, "cascadePhase": {"number": 2}}
        events = coordinator._compute_events("t", 2, old, new)
        phase_events = [e for e in events if e["event_type"] == "phase.changed"]
        assert len(phase_events) == 1
        assert phase_events[0]["severity"] == "critical"

    def test_no_change_no_events(self, coordinator):
        """No state changes → no events emitted."""
        snap = {"nodeStates": {"a": "stable"}, "cascadePhase": {"number": 1}}
        events = coordinator._compute_events("t", 2, snap, snap)
        assert events == []


# ═══════════════════════════════════════════════════════════════════════
# OVERRIDE APPLICATION
# ═══════════════════════════════════════════════════════════════════════

class TestOverrides:
    def test_node_override(self, coordinator):
        """Override patches node field in effective config."""
        cfg = {"nodes": [{"id": "brent", "current": 80.0}]}
        overrides = [{"target_type": "node", "target_id": "brent",
                       "field": "current", "value": 120.0}]
        coordinator._apply_overrides(cfg, overrides)
        assert cfg["nodes"][0]["current"] == 120.0

    def test_market_field_override(self, coordinator):
        """Override patches marketField value."""
        cfg = {"nodes": [], "marketFields": [{"key": "brent", "value": 80.0}]}
        overrides = [{"target_type": "marketField", "target_id": "brent",
                       "field": "value", "value": 120.0}]
        coordinator._apply_overrides(cfg, overrides)
        assert cfg["marketFields"][0]["value"] == 120.0

    def test_empty_overrides(self, coordinator):
        """No overrides → config unchanged."""
        cfg = {"nodes": [{"id": "a", "current": 1.0}]}
        coordinator._apply_overrides(cfg, [])
        assert cfg["nodes"][0]["current"] == 1.0


# ═══════════════════════════════════════════════════════════════════════
# RESTART RECOVERY
# ═══════════════════════════════════════════════════════════════════════

class TestRestartRecovery:
    @pytest.mark.asyncio
    async def test_hydrates_revision_from_db(self, coordinator, repo):
        """After a cycle, restart hydrates the correct revision."""
        coordinator._load_definitions()
        coordinator._hydrate_from_db()

        with no_network():
            await coordinator._run_cycle("iran-hormuz-graph")

        # Simulate restart: new coordinator, same DB
        coord2 = RuntimeCoordinator(repo=repo, ws_manager=MagicMock(), tick_interval=9999)
        coord2._load_definitions()
        coord2._hydrate_from_db()
        assert coord2._revisions["iran-hormuz-graph"] == 1
        assert coord2._latest_snapshots["iran-hormuz-graph"] is not None


# ═══════════════════════════════════════════════════════════════════════
# RUNTIME ADOPTION — the create-thesis path
# ═══════════════════════════════════════════════════════════════════════

MINIMAL_BOOK = {
    "meta": {"title": "Adopted", "type": "thesis-graph", "version": "1.0.0"},
    "nodes": [], "edges": [], "instruments": {}, "scenarios": [],
    "cascadePhases": {}, "rules": [], "provenance": [],
}


class TestRuntimeAdoption:
    """adopt_book must give a snapshotless book its first cycle NOW — the
    human who just created it is staring at an empty panel — while a book
    that already has a snapshot (builder re-saves) stays on the tick."""

    def _write_book(self, tmp_path, thesis_id="adopted-graph"):
        (tmp_path / f"{thesis_id}.json").write_text(json.dumps(MINIMAL_BOOK))
        return thesis_id

    @pytest.mark.asyncio
    async def test_new_book_gets_an_immediate_cycle(self, coordinator, tmp_path):
        thesis_id = self._write_book(tmp_path)
        coordinator._run_cycle = AsyncMock(return_value={})
        with patch("web.runtime.coordinator.BOOKS_DIR", tmp_path):
            assert coordinator.adopt_book(thesis_id) is True
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        coordinator._run_cycle.assert_awaited_once_with(thesis_id)

    @pytest.mark.asyncio
    async def test_resave_of_a_living_book_stays_on_the_tick(
        self, coordinator, tmp_path
    ):
        thesis_id = self._write_book(tmp_path)
        coordinator._latest_snapshots[thesis_id] = {"v": 2}
        coordinator._run_cycle = AsyncMock(return_value={})
        with patch("web.runtime.coordinator.BOOKS_DIR", tmp_path):
            assert coordinator.adopt_book(thesis_id) is True
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        coordinator._run_cycle.assert_not_awaited()

    def test_adoption_outside_a_loop_still_adopts(self, coordinator, tmp_path):
        """Sync contexts (scripts, tests) adopt without the rush cycle."""
        thesis_id = self._write_book(tmp_path)
        with patch("web.runtime.coordinator.BOOKS_DIR", tmp_path):
            assert coordinator.adopt_book(thesis_id) is True
        assert thesis_id in coordinator.definitions

    def test_missing_book_is_a_calm_false(self, coordinator, tmp_path):
        with patch("web.runtime.coordinator.BOOKS_DIR", tmp_path):
            assert coordinator.adopt_book("no-such-graph") is False
