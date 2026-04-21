"""Tests for v2 Unit 14 — split health endpoints + structured logging."""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from web.main import app
from web.persistence.repository import Repository
from web.deps import get_repo
from web.observability import (
    JsonFormatter,
    configure_structured_logging,
    thesis_context,
)


@pytest.fixture(autouse=True)
def isolate_state():
    repo = Repository(":memory:")
    repo.initialize()
    app.dependency_overrides[get_repo] = lambda: repo
    app.state.repo = repo
    yield repo
    app.dependency_overrides.pop(get_repo, None)
    # Coordinator may be set by some tests; drop it between.
    if hasattr(app.state, "coordinator"):
        delattr(app.state, "coordinator")


client = TestClient(app)


class TestLivenessProbe:
    def test_live_returns_200_with_uptime(self):
        resp = client.get("/api/v1/health/live")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "alive"
        assert isinstance(body["uptime_seconds"], (int, float))

    def test_live_never_fails_on_missing_coordinator(self):
        """Liveness must NOT 503 just because readiness components aren't up.
        That's what the /ready endpoint is for."""
        if hasattr(app.state, "coordinator"):
            delattr(app.state, "coordinator")
        resp = client.get("/api/v1/health/live")
        assert resp.status_code == 200


class TestReadinessProbe:
    def test_ready_503_without_coordinator(self):
        if hasattr(app.state, "coordinator"):
            delattr(app.state, "coordinator")
        resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"
        assert body["detail"]["coordinator_initialized"] is False

    def test_ready_503_without_first_tick(self):
        """Coordinator present but _first_tick_done is False → still 503."""
        from types import SimpleNamespace
        app.state.coordinator = SimpleNamespace(is_ready=False)
        resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["coordinator_initialized"] is True
        assert body["detail"]["first_tick_done"] is False

    def test_ready_200_all_dependencies_up(self):
        """DB writable + coordinator + first tick done → 200."""
        from types import SimpleNamespace
        app.state.coordinator = SimpleNamespace(is_ready=True)
        resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["detail"]["db_writable"] is True
        assert body["detail"]["coordinator_initialized"] is True
        assert body["detail"]["first_tick_done"] is True


class TestRepositoryPing:
    def test_ping_returns_true_on_healthy_db(self, isolate_state):
        assert isolate_state.ping() is True

    def test_ping_cleans_up_temp_table(self, isolate_state):
        """Repeated ping() calls must not accumulate state."""
        for _ in range(3):
            assert isolate_state.ping() is True


class TestJsonFormatter:
    def _capture(self, fn):
        """Run fn inside a captured log stream, return the JSON record emitted."""
        import io
        logger = logging.getLogger(f"test.{id(fn)}")
        logger.setLevel(logging.INFO)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        try:
            fn(logger)
        finally:
            logger.removeHandler(handler)
        lines = [L for L in stream.getvalue().strip().split("\n") if L]
        return [json.loads(L) for L in lines]

    def test_formats_as_jsonl_with_core_fields(self):
        records = self._capture(lambda log: log.info("hello"))
        assert len(records) == 1
        r = records[0]
        assert r["level"] == "INFO"
        assert r["message"] == "hello"
        assert "ts" in r
        assert "thesisId" not in r  # No context set → field omitted

    def test_injects_thesis_context_when_set(self):
        def emit(log):
            with thesis_context("iran-hormuz-graph", revision=42, run_id=317):
                log.info("tick complete")

        records = self._capture(emit)
        assert records[0]["thesisId"] == "iran-hormuz-graph"
        assert records[0]["revision"] == 42
        assert records[0]["runId"] == 317

    def test_context_vars_cleared_after_block(self):
        def emit(log):
            with thesis_context("inner"):
                log.info("inside")
            log.info("outside")

        records = self._capture(emit)
        assert records[0]["thesisId"] == "inner"
        assert "thesisId" not in records[1]

    def test_extras_merged_into_record(self):
        def emit(log):
            log.info("done", extra={"durationMs": 184, "status": "ok"})

        records = self._capture(emit)
        assert records[0]["durationMs"] == 184
        assert records[0]["status"] == "ok"

    def test_non_serializable_extra_is_coerced_not_dropped(self):
        """A badly-typed extra must not break the log pipeline — coerce to repr."""
        class NotJsonable:
            def __repr__(self) -> str:
                return "<NotJsonable>"

        def emit(log):
            log.info("msg", extra={"weird": NotJsonable()})

        records = self._capture(emit)
        assert records[0]["weird"] == "<NotJsonable>"

    def test_exception_info_included(self):
        def emit(log):
            try:
                raise ValueError("boom")
            except ValueError:
                log.exception("fail")

        records = self._capture(emit)
        assert "exc" in records[0]
        assert "ValueError" in records[0]["exc"]


class TestConfigureStructuredLogging:
    def test_idempotent(self):
        """Calling twice leaves one handler attached, not two."""
        configure_structured_logging()
        before = len(logging.getLogger().handlers)
        configure_structured_logging()
        after = len(logging.getLogger().handlers)
        assert before == after == 1
        # Cleanup so other tests see the default format.
        logging.getLogger().handlers.clear()
        logging.basicConfig(level=logging.INFO)
