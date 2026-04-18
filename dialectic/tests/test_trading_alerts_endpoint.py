"""Tests for the /rooms/{id}/trading/alerts endpoint and the tightened /health.

Strategy: stub out get_db + extract_room_token + verify_room_token via FastAPI
dependency overrides + monkeypatching. No live Postgres required.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from models import SpeakerType, MessageType, Room


ROOM_ID = UUID("00000000-0000-0000-0000-000000000099")


def _row(content: str, metadata: dict | None, minutes_ago: int = 0) -> dict:
    """Build a fake DB row that Message(**dict(row)) can consume."""
    return {
        "id": uuid4(),
        "thread_id": uuid4(),
        "sequence": 1,
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        "speaker_type": SpeakerType.LLM_ANNOTATOR.value
        if metadata and metadata.get("source") == "trading_curator"
        else SpeakerType.HUMAN.value,
        "user_id": None,
        "message_type": MessageType.TEXT.value,
        "content": content,
        "references_message_id": None,
        "references_memory_id": None,
        "model_used": None,
        "prompt_hash": None,
        "token_count": None,
        "is_deleted": False,
        "metadata": metadata,
    }


@pytest.fixture
def client_with_stubs():
    """TestClient with auth + db stubbed; yields (client, fake_db)."""

    fake_db = AsyncMock()
    # Default: empty result
    fake_db.fetch = AsyncMock(return_value=[])
    fake_db.fetchrow = AsyncMock(return_value=None)
    fake_db.fetchval = AsyncMock(return_value=None)

    async def _fake_db_dep():
        yield fake_db

    main_mod.app.dependency_overrides[main_mod.get_db] = _fake_db_dep
    main_mod.app.dependency_overrides[main_mod.extract_room_token] = lambda: "tok"

    # Patch verify_room_token to short-circuit auth
    fake_room = Room(
        id=ROOM_ID,
        created_at=datetime.now(timezone.utc),
        token="tok",
        name="Test",
    )

    with patch.object(main_mod, "verify_room_token", new=AsyncMock(return_value=fake_room)):
        client = TestClient(main_mod.app)
        yield client, fake_db

    main_mod.app.dependency_overrides.clear()


class TestTradingAlertsEndpoint:
    def test_returns_only_curator_messages_filtered_by_metadata(self, client_with_stubs):
        """Endpoint must return only messages with metadata.source='trading_curator'.

        We seed 2 curator messages and 1 user message in the mocked rows. The
        endpoint passes a SQL filter to the DB; we assert the query includes
        the metadata predicate, and that only curator rows come back.
        """
        client, fake_db = client_with_stubs
        curator_rows = [
            _row("Brent above 115", {"source": "trading_curator"}, minutes_ago=20),
            _row("Hormuz approaching", {"source": "trading_curator"}, minutes_ago=10),
        ]
        # Mocked DB only returns what matches the WHERE clause; simulate that
        # by having .fetch return the two curator rows in ascending order.
        fake_db.fetch = AsyncMock(return_value=curator_rows)

        resp = client.get(f"/rooms/{ROOM_ID}/trading/alerts")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        # Ascending by created_at
        assert "Brent above 115" in body[0]["content"]
        assert "Hormuz approaching" in body[1]["content"]
        # All returned messages carry the curator metadata tag
        for msg in body:
            assert msg["metadata"]["source"] == "trading_curator"

        # Verify the SQL filtered on metadata server-side
        query = fake_db.fetch.call_args[0][0]
        assert "metadata->>'source'" in query
        assert "trading_curator" in query
        assert "ORDER BY m.created_at ASC" in query

    def test_since_parameter_passed_to_query(self, client_with_stubs):
        """The since= ISO8601 parameter must be parsed and applied as cutoff."""
        client, fake_db = client_with_stubs
        fake_db.fetch = AsyncMock(return_value=[])

        cutoff_iso = "2026-04-15T00:00:00Z"
        resp = client.get(f"/rooms/{ROOM_ID}/trading/alerts?since={cutoff_iso}")
        assert resp.status_code == 200

        # Cutoff is positional arg 2 (room_id is 1, cutoff is 2, limit is 3)
        cutoff_arg = fake_db.fetch.call_args[0][2]
        assert isinstance(cutoff_arg, datetime)
        assert cutoff_arg.year == 2026 and cutoff_arg.month == 4 and cutoff_arg.day == 15

    def test_invalid_since_returns_400(self, client_with_stubs):
        client, _ = client_with_stubs
        resp = client.get(f"/rooms/{ROOM_ID}/trading/alerts?since=not-a-date")
        assert resp.status_code == 400
        assert "ISO8601" in resp.json()["detail"]

    def test_default_since_is_24h_ago(self, client_with_stubs):
        """Without since=, cutoff defaults to ~24h ago."""
        client, fake_db = client_with_stubs
        fake_db.fetch = AsyncMock(return_value=[])

        resp = client.get(f"/rooms/{ROOM_ID}/trading/alerts")
        assert resp.status_code == 200

        cutoff_arg = fake_db.fetch.call_args[0][2]
        delta = datetime.now(timezone.utc) - cutoff_arg
        # Within a few seconds of 24h
        assert abs(delta.total_seconds() - 24 * 3600) < 10


class TestHealthEndpoint:
    def test_health_returns_503_when_no_db_pool(self):
        """When db_pool is None, /health returns 503 + status='degraded'."""
        # Force pool to None
        with patch.object(main_mod, "db_pool", None):
            client = TestClient(main_mod.app)
            resp = client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["checks"]["db"] == "down"

    def test_health_returns_503_when_select_one_fails(self):
        """When SELECT 1 raises, /health returns 503 + status='degraded'."""

        # Build a fake pool whose acquire().__aenter__() returns a conn whose
        # fetchval raises.
        class _FakeConn:
            async def fetchval(self, *_a, **_k):
                raise RuntimeError("connection refused")

        class _AcquireCtx:
            async def __aenter__(self_inner):
                return _FakeConn()

            async def __aexit__(self_inner, *a):
                return False

        class _FakePool:
            def acquire(self_inner):
                return _AcquireCtx()

        with patch.object(main_mod, "db_pool", _FakePool()):
            client = TestClient(main_mod.app)
            resp = client.get("/health")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["checks"]["db"] == "down"
        assert "connection refused" in body["checks"].get("db_error", "")
