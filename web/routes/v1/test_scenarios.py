"""
Tests for POST /api/v1/theses/{thesis_id}/scenarios/{scenario_id}/evaluate.

WHY: Scenario evaluation must be read-only and revision-bound. These tests
verify the route returns structured results, respects againstRevision,
404s for missing entities, and never mutates committed state.
"""

import copy
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.deps import get_repo
from web.persistence.repository import Repository
from web.runtime.coordinator import RuntimeCoordinator


THESIS_ID = "iran-hormuz-graph"
SCENARIO_ID = "reopen-apr1"  # present in the real book
UNKNOWN_SCENARIO = "no-such-scenario"
UNKNOWN_THESIS = "no-such-thesis"


@pytest.fixture
def repo():
    r = Repository(":memory:")
    r.initialize()
    return r


@pytest.fixture
def ws_mock():
    m = MagicMock()
    m.broadcast_to_book_rooms = AsyncMock(return_value=0)
    return m


@pytest.fixture
def coordinator(repo, ws_mock):
    """Real coordinator with real book defs and an in-memory repo.

    WHY real books: the scenario route's value comes from exercising the
    engine end-to-end. A mock coordinator would pass but tell us nothing
    about the eval_scenario → propagate path.
    """
    c = RuntimeCoordinator(repo=repo, ws_manager=ws_mock, tick_interval=9999)
    c._load_definitions()
    # Seed a baseline snapshot at revision 1 so scenario eval has a base to
    # diff against. Uses the engine's own propagate → export pipeline so the
    # snapshot is well-formed (not a hand-crafted stub).
    from tools.thesis_graph import thesisgraph
    from datetime import date
    cfg = c._definitions[THESIS_ID]
    effective = copy.deepcopy(cfg)
    states = thesisgraph.propagate(effective)
    confluence = thesisgraph.score_confluence(effective, states)
    phase_num, phase_key = thesisgraph.get_current_phase(effective)
    export = thesisgraph.export_state(
        effective, states, confluence, phase_num, phase_key,
        scenarios_result=[], today=date.today(),
    )
    export["thesisId"] = THESIS_ID
    export["revision"] = 1
    export["definitionHash"] = c._definition_hashes.get(THESIS_ID)
    repo.save_snapshot(THESIS_ID, 1, json.dumps(export))
    c._revisions[THESIS_ID] = 1
    c._latest_snapshots[THESIS_ID] = export
    return c


@pytest.fixture(autouse=True)
def wire_app(repo, coordinator):
    app.dependency_overrides[get_repo] = lambda: repo
    app.state.repo = repo
    prior = getattr(app.state, "coordinator", None)
    app.state.coordinator = coordinator
    yield
    app.dependency_overrides.pop(get_repo, None)
    app.state.coordinator = prior


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


def _url(thesis_id=THESIS_ID, scenario_id=SCENARIO_ID):
    return f"/api/v1/theses/{thesis_id}/scenarios/{scenario_id}/evaluate"


class TestHappyPath:
    def test_returns_200(self, client, auth_headers):
        resp = client.post(_url(), headers=auth_headers)
        assert resp.status_code == 200, resp.text

    def test_response_shape(self, client, auth_headers):
        data = client.post(_url(), headers=auth_headers).json()
        assert data["scenarioId"] == SCENARIO_ID
        assert "baseRevision" in data
        assert "changedNodes" in data
        assert "portfolioImpact" in data
        assert "explanation" in data
        assert isinstance(data["probability"], (int, float))

    def test_baserevision_matches_latest_without_against(self, client, auth_headers, coordinator):
        data = client.post(_url(), headers=auth_headers).json()
        assert data["baseRevision"] == coordinator._revisions[THESIS_ID]

    def test_baserevision_matches_specified_against(self, client, auth_headers):
        resp = client.post(_url() + "?against_revision=1", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["baseRevision"] == 1

    def test_changed_nodes_have_old_and_new(self, client, auth_headers):
        data = client.post(_url(), headers=auth_headers).json()
        for node_id, diff in data["changedNodes"].items():
            assert "old" in diff
            assert "new" in diff
            assert diff["old"] != diff["new"]

    def test_idempotent(self, client, auth_headers):
        """Same request twice returns the same structured payload."""
        a = client.post(_url(), headers=auth_headers).json()
        b = client.post(_url(), headers=auth_headers).json()
        assert a == b


class TestNotFound:
    def test_unknown_thesis_404s(self, client, auth_headers):
        resp = client.post(
            _url(thesis_id=UNKNOWN_THESIS), headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "thesis_not_found"

    def test_unknown_scenario_404s(self, client, auth_headers):
        resp = client.post(
            _url(scenario_id=UNKNOWN_SCENARIO), headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "scenario_not_found"

    def test_unknown_revision_404s(self, client, auth_headers):
        resp = client.post(
            _url() + "?against_revision=99999", headers=auth_headers
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "revision_not_found"


class TestAuth:
    def test_requires_auth(self, client):
        resp = client.post(_url())
        assert resp.status_code in (401, 403)


class TestReadOnlyIntegration:
    """Scenario evaluation must never mutate committed state.

    WHY: This is the architectural guarantee of the endpoint. A scenario
    request is pure read — it must not bump revisions, insert alert
    events, or enqueue outbox rows.
    """

    def test_no_new_snapshot_committed(self, client, auth_headers, coordinator, repo):
        rev_before = coordinator._revisions[THESIS_ID]
        client.post(_url(), headers=auth_headers)
        # The in-memory revision counter did not move
        assert coordinator._revisions[THESIS_ID] == rev_before
        # And no higher revision exists in SQLite
        assert repo.get_latest_revision(THESIS_ID) == rev_before

    def test_no_alert_events_inserted(self, client, auth_headers, repo):
        before = len(repo.list_alert_events(thesis_id=THESIS_ID, limit=1000))
        client.post(_url(), headers=auth_headers)
        after = len(repo.list_alert_events(thesis_id=THESIS_ID, limit=1000))
        assert before == after

    def test_no_outbox_enqueued(self, client, auth_headers, repo):
        before = len(repo.get_pending_outbox(limit=1000))
        client.post(_url(), headers=auth_headers)
        after = len(repo.get_pending_outbox(limit=1000))
        assert before == after

    def test_latest_snapshot_unchanged_after_eval(self, client, auth_headers, coordinator):
        snap_before = copy.deepcopy(coordinator._latest_snapshots[THESIS_ID])
        client.post(_url(), headers=auth_headers)
        assert coordinator._latest_snapshots[THESIS_ID] == snap_before


class TestDeterminism:
    """Same inputs must produce same outputs."""

    def test_same_revision_same_result(self, client, auth_headers):
        a = client.post(_url() + "?against_revision=1", headers=auth_headers).json()
        b = client.post(_url() + "?against_revision=1", headers=auth_headers).json()
        assert a == b


class TestCoordinatorMissing:
    def test_503_when_coordinator_absent(self, client, auth_headers):
        """Route returns 503 rather than 500 if app startup hasn't set a coordinator."""
        prior = app.state.coordinator
        app.state.coordinator = None
        try:
            resp = client.post(_url(), headers=auth_headers)
            assert resp.status_code == 503
            assert resp.json()["detail"] == "coordinator_not_ready"
        finally:
            app.state.coordinator = prior
