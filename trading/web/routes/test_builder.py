"""
Builder route tests — CRUD for thesis books, format conversion, validation.
"""
import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")
from web.main import app
from web.auth import create_access_token
from web.deps import get_repo
from web.persistence.repository import Repository
from web.routes.builder import (
    _engine_to_builder_format,
    _book_to_engine_format,
    _sanitize_id,
    BOOKS_DIR,
    SaveBookRequest,
)
client = TestClient(app)
@pytest.fixture(autouse=True)
def isolate_state():
    """Inject fresh in-memory SQLite per test."""
    repo = Repository(":memory:")
    repo.initialize()
    app.dependency_overrides[get_repo] = lambda: repo
    app.state.repo = repo
    from web.ws import manager
    manager.set_repo(repo)
    yield repo
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tmp_books_dir(tmp_path, monkeypatch):
    """Redirect BOOKS_DIR to a temp directory for isolation."""
    import web.routes.builder as builder_mod
    monkeypatch.setattr(builder_mod, "BOOKS_DIR", tmp_path)
    return tmp_path
@pytest.fixture
def sample_book_payload():
    """Minimal valid book payload for creation."""
    return {
        "meta": {
            "title": "Test Thesis — Unit Test",
            "claim": "Testing causes confidence",
            "monthlyBudget": 3000,
            "asOf": "2026-04-17",
        },
        "nodes": [
            {
                "id": "event-a",
                "label": "Event A",
                "type": "event",
                "phase": 1,
                "state": "monitoring",
                "context": "Root cause event",
                "x": 100, "y": 60,
                "probability": 0.5,
                "current": None,
                "feeds": [{"source": "polymarket", "market": "test-market"}],
                "thresholds": [],
                "indicators": [],
                "countdown": False,
                "deadline": None,
                "irreversible": False,
                "gatedBy": [],
                "logic": None,
            },
            {
                "id": "price-b",
                "label": "Price B",
                "type": "price",
                "phase": 2,
                "state": "monitoring",
                "context": "Downstream price impact",
                "x": 380, "y": 60,
                "probability": None,
                "current": 100.0,
                "feeds": [{"source": "yahoo", "symbol": "SPY"}],
                "thresholds": [{"level": 110, "label": "breakout"}],
                "indicators": [],
                "countdown": False,
                "deadline": None,
                "irreversible": False,
                "gatedBy": [],
                "logic": None,
            },
            {
                "id": "gate-c",
                "label": "Gate C",
                "type": "gate",
                "phase": 2,
                "state": "monitoring",
                "context": "Gated by Event A",
                "x": 380, "y": 180,
                "probability": None,
                "current": None,
                "feeds": [],
                "thresholds": [],
                "indicators": [{"label": "Manual check", "feed": "manual", "value": "pending", "status": "grey"}],
                "countdown": True,
                "deadline": "2026-05-01",
                "irreversible": True,
                "gatedBy": ["event-a"],
                "logic": "all",
            },
        ],
        "edges": [
            {"source": "event-a", "target": "price-b", "mechanism": "Direct transmission", "lag": "immediate", "strength": 0.9},
            {"source": "event-a", "target": "gate-c", "mechanism": "Prerequisite check", "lag": "1 week", "strength": 0.7},
        ],
        "instruments": {
            "price-b": [
                {"id": "SPY", "monthly": 1000, "role": "index proxy", "beta": 1.0, "ref": 500.0, "targetLow": 520, "targetHigh": 540, "stop": 480},
            ]
        },
        "scenarios": [
            {"id": "base", "name": "Base case", "probability": 0.6, "notes": "Most likely", "overrides": {"event-a": "active"}, "portfolioImpact": {}},
            {"id": "bull", "name": "Bull case", "probability": 0.4, "notes": "Risk-on", "overrides": {"price-b": 130}, "portfolioImpact": {}},
        ],
        "cascadePhases": {},
        "rules": ["Max 10% per position", "Review weekly"],
    }


# ── Unit Tests: Helpers ───────────────────────────────────────────────────

class TestSanitizeId:
    def test_simple_title(self):
        assert _sanitize_id("Iran Hormuz") == "iran-hormuz"

    def test_special_characters(self):
        assert _sanitize_id("Trump/Tariffs — 2026!!") == "trump-tariffs-2026"

    def test_long_title_truncated(self):
        result = _sanitize_id("A" * 100)
        assert len(result) <= 60

    def test_empty_title_gets_fallback(self):
        result = _sanitize_id("")
        assert result.startswith("thesis-")


# ── Unit Tests: Format Conversion ─────────────────────────────────────────

class TestFormatConversion:
    def test_engine_to_builder_preserves_nodes(self):
        with open(BOOKS_DIR / "iran-hormuz-graph.json") as f:
            cfg = json.load(f)
        builder = _engine_to_builder_format(cfg, "iran-hormuz-graph")
        assert len(builder["nodes"]) == len(cfg["nodes"])
        assert builder["nodes"][0]["id"] == cfg["nodes"][0]["id"]
        # Builder format should have x, y
        assert "x" in builder["nodes"][0]
        assert "y" in builder["nodes"][0]

    def test_engine_to_builder_preserves_edges(self):
        with open(BOOKS_DIR / "iran-hormuz-graph.json") as f:
            cfg = json.load(f)
        builder = _engine_to_builder_format(cfg, "iran-hormuz-graph")
        assert len(builder["edges"]) == len(cfg["edges"])
        # Edges use source/target, not from/to
        edge = builder["edges"][0]
        assert "source" in edge
        assert "target" in edge
        assert edge["source"] == cfg["edges"][0]["from"]
        assert edge["target"] == cfg["edges"][0]["to"]

    def test_engine_to_builder_preserves_meta(self):
        with open(BOOKS_DIR / "iran-hormuz-graph.json") as f:
            cfg = json.load(f)
        builder = _engine_to_builder_format(cfg, "iran-hormuz-graph")
        assert builder["meta"]["title"] == cfg["meta"]["title"]
        assert builder["meta"]["monthlyBudget"] == cfg["meta"]["monthlyBudget"]

    def test_builder_to_engine_converts_edges(self, sample_book_payload):
        req = SaveBookRequest(**sample_book_payload)
        cfg = _book_to_engine_format(req, "test")
        # Engine format uses from/to
        assert cfg["edges"][0]["from"] == "event-a"
        assert cfg["edges"][0]["to"] == "price-b"

    def test_builder_to_engine_strips_builder_fields(self, sample_book_payload):
        req = SaveBookRequest(**sample_book_payload)
        cfg = _book_to_engine_format(req, "test")
        # Engine nodes should NOT have x, y
        for node in cfg["nodes"]:
            assert "x" not in node
            assert "y" not in node

    def test_builder_to_engine_preserves_node_properties(self, sample_book_payload):
        req = SaveBookRequest(**sample_book_payload)
        cfg = _book_to_engine_format(req, "test")
        gate = next(n for n in cfg["nodes"] if n["id"] == "gate-c")
        assert gate["countdown"] is True
        assert gate["deadline"] == "2026-05-01"
        assert gate["irreversible"] is True
        assert gate["gatedBy"] == ["event-a"]
        assert gate["logic"] == "all"

    def test_builder_to_engine_preserves_feeds(self, sample_book_payload):
        req = SaveBookRequest(**sample_book_payload)
        cfg = _book_to_engine_format(req, "test")
        event = next(n for n in cfg["nodes"] if n["id"] == "event-a")
        assert len(event["feeds"]) == 1
        assert event["feeds"][0]["source"] == "polymarket"

    def test_roundtrip_iran_book(self):
        """Load iran book → convert to builder → convert back → verify structural match."""
        with open(BOOKS_DIR / "iran-hormuz-graph.json") as f:
            original = json.load(f)
        builder = _engine_to_builder_format(original, "iran-hormuz-graph")
        req = SaveBookRequest(**builder)
        roundtripped = _book_to_engine_format(req, "iran-hormuz-graph")
        assert len(roundtripped["nodes"]) == len(original["nodes"])
        assert len(roundtripped["edges"]) == len(original["edges"])
        orig_ids = {n["id"] for n in original["nodes"]}
        rt_ids = {n["id"] for n in roundtripped["nodes"]}
        assert orig_ids == rt_ids
        for orig_edge, rt_edge in zip(original["edges"], roundtripped["edges"]):
            assert orig_edge["from"] == rt_edge["from"]
            assert orig_edge["to"] == rt_edge["to"]

    def test_roundtrip_tariffs_book(self):
        """Load tariffs book → convert to builder → convert back → verify."""
        with open(BOOKS_DIR / "trump-tariffs-graph.json") as f:
            original = json.load(f)
        builder = _engine_to_builder_format(original, "trump-tariffs-graph")
        req = SaveBookRequest(**builder)
        roundtripped = _book_to_engine_format(req, "trump-tariffs-graph")
        assert len(roundtripped["nodes"]) == len(original["nodes"])
        assert len(roundtripped["edges"]) == len(original["edges"])


# ── API Tests: CRUD ───────────────────────────────────────────────────────

class TestBuilderAPI:
    def test_create_book(self, auth_headers, tmp_books_dir, sample_book_payload):
        resp = client.post(
            "/api/thesis/builder/books",
            json=sample_book_payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["id"] == "test-thesis-unit-test"
        # File was created on disk
        assert (tmp_books_dir / f"{data['id']}.json").exists()

    def test_create_book_writes_valid_engine_json(self, auth_headers, tmp_books_dir, sample_book_payload):
        resp = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        book_id = resp.json()["id"]
        with open(tmp_books_dir / f"{book_id}.json") as f:
            cfg = json.load(f)
        # Engine format checks
        assert cfg["meta"]["type"] == "thesis-graph"
        assert cfg["edges"][0]["from"] == "event-a"
        assert len(cfg["nodes"]) == 3
        # Builder positions preserved for round-tripping
        assert cfg["nodes"][0]["_builderX"] == 100
        assert cfg["nodes"][0]["_builderY"] == 60

    def test_create_avoids_overwrite(self, auth_headers, tmp_books_dir, sample_book_payload):
        """Creating two books with the same title gets different IDs."""
        resp1 = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        resp2 = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        assert resp1.json()["id"] != resp2.json()["id"]
    def test_get_book(self, auth_headers, tmp_books_dir, sample_book_payload):
        resp = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        book_id = resp.json()["id"]
        resp2 = client.get(f"/api/thesis/builder/books/{book_id}", headers=auth_headers)
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["meta"]["title"] == "Test Thesis — Unit Test"
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2
        assert data["edges"][0]["source"] == "event-a"
    def test_get_nonexistent_book(self, auth_headers, tmp_books_dir):
        resp = client.get("/api/thesis/builder/books/does-not-exist", headers=auth_headers)
        assert resp.status_code == 404
    def test_update_book(self, auth_headers, tmp_books_dir, sample_book_payload):
        resp = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        book_id = resp.json()["id"]
        sample_book_payload["meta"]["title"] = "Updated Thesis Title"
        sample_book_payload["nodes"].append({
            "id": "new-node",
            "label": "New Node",
            "type": "indicator",
            "phase": 3,
            "state": "monitoring",
            "context": "Added via update",
            "x": 660, "y": 60,
            "probability": None, "current": None,
            "feeds": [], "thresholds": [], "indicators": [],
            "countdown": False, "deadline": None, "irreversible": False,
            "gatedBy": [], "logic": None,
        })
        resp2 = client.put(f"/api/thesis/builder/books/{book_id}", json=sample_book_payload, headers=auth_headers)
        assert resp2.status_code == 200
        with open(tmp_books_dir / f"{book_id}.json") as f:
            cfg = json.load(f)
        assert cfg["meta"]["title"] == "Updated Thesis Title"
        assert len(cfg["nodes"]) == 4
    def test_update_preserves_dialectic_tokens(self, auth_headers, tmp_books_dir, sample_book_payload):
        """Update must NOT lose engine-only fields like dialecticRoomToken."""
        # Create with engine-only fields injected manually
        resp = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        book_id = resp.json()["id"]
        # Inject dialectic fields into the on-disk file
        config_path = tmp_books_dir / f"{book_id}.json"
        with open(config_path) as f:
            cfg = json.load(f)
        cfg["meta"]["dialecticRoomId"] = "test-room-uuid"
        cfg["meta"]["dialecticRoomToken"] = "secret-token-123"
        cfg["fetchSymbols"] = ["BZ=F", "DX-Y.NYB"]
        with open(config_path, "w") as f:
            json.dump(cfg, f)
        # Now update via builder API
        resp2 = client.put(f"/api/thesis/builder/books/{book_id}", json=sample_book_payload, headers=auth_headers)
        assert resp2.status_code == 200
        # Verify preserved
        with open(config_path) as f:
            updated = json.load(f)
        assert updated["meta"]["dialecticRoomId"] == "test-room-uuid"
        assert updated["meta"]["dialecticRoomToken"] == "secret-token-123"
        assert updated["fetchSymbols"] == ["BZ=F", "DX-Y.NYB"]


    def test_update_preserves_engine_node_fields(self, auth_headers, tmp_books_dir, sample_book_payload):
        """Update must NOT lose engine-only node fields like tvAlertBindings, derivedIndicators."""
        resp = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        book_id = resp.json()["id"]
        config_path = tmp_books_dir / f"{book_id}.json"
        with open(config_path) as f:
            cfg = json.load(f)
        for node in cfg["nodes"]:
            if node["id"] == "event-a":
                node["tvAlertBindings"] = [{"bindingId": "test-binding", "nodeId": "event-a", "op": "setProbability"}]
                node["derivedIndicators"] = [{"kind": "rsi", "period": 14, "symbol": "SPY"}]
                node["closesRequired"] = 3
                node["conditions"] = ["some-condition"]
                node["regimes"] = {"bull": {"threshold": 0.8}}
            if node["id"] == "price-b":
                node["tvIndicators"] = {"rsi14": 55.2, "source": "derived"}
        for edge in cfg["edges"]:
            if edge["from"] == "event-a" and edge["to"] == "price-b":
                edge["amplification"] = 1.5
        with open(config_path, "w") as f:
            json.dump(cfg, f)
        sample_book_payload["meta"]["title"] = "Updated but preserved"
        resp2 = client.put(f"/api/thesis/builder/books/{book_id}", json=sample_book_payload, headers=auth_headers)
        assert resp2.status_code == 200
        with open(config_path) as f:
            updated = json.load(f)
        event_a = next(n for n in updated["nodes"] if n["id"] == "event-a")
        assert event_a["tvAlertBindings"] == [{"bindingId": "test-binding", "nodeId": "event-a", "op": "setProbability"}]
        assert event_a["derivedIndicators"] == [{"kind": "rsi", "period": 14, "symbol": "SPY"}]
        assert event_a["closesRequired"] == 3
        assert event_a["conditions"] == ["some-condition"]
        assert event_a["regimes"] == {"bull": {"threshold": 0.8}}
        price_b = next(n for n in updated["nodes"] if n["id"] == "price-b")
        assert price_b["tvIndicators"]["rsi14"] == 55.2
        edge = next(e for e in updated["edges"] if e["from"] == "event-a" and e["to"] == "price-b")
        assert edge["amplification"] == 1.5
        assert updated["meta"]["title"] == "Updated but preserved"

    def test_update_nonexistent_book(self, auth_headers, tmp_books_dir, sample_book_payload):
        resp = client.put("/api/thesis/builder/books/ghost", json=sample_book_payload, headers=auth_headers)
        assert resp.status_code == 404

    def test_delete_book(self, auth_headers, tmp_books_dir, sample_book_payload):
        # Create
        resp = client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        book_id = resp.json()["id"]
        assert (tmp_books_dir / f"{book_id}.json").exists()
        # Delete
        resp2 = client.delete(f"/api/thesis/builder/books/{book_id}", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["deleted"] == book_id
        # File gone
        assert not (tmp_books_dir / f"{book_id}.json").exists()

    def test_delete_nonexistent_book(self, auth_headers, tmp_books_dir):
        resp = client.delete("/api/thesis/builder/books/ghost", headers=auth_headers)
        assert resp.status_code == 404

    def test_unauthenticated_rejected(self, tmp_books_dir):
        resp = client.get("/api/thesis/builder/books/test")
        assert resp.status_code in (401, 403)

    def test_path_traversal_rejected(self, auth_headers, tmp_books_dir):
        # _validate_book_id regex rejects anything not [a-z0-9][a-z0-9_-]*
        resp = client.get("/api/thesis/builder/books/..etc..passwd", headers=auth_headers)
        assert resp.status_code == 422
        resp2 = client.get("/api/thesis/builder/books/_leading-underscore", headers=auth_headers)
        assert resp2.status_code == 422
        resp3 = client.get("/api/thesis/builder/books/-leading-dash", headers=auth_headers)
        assert resp3.status_code == 422
    
    def test_invalid_book_id_rejected(self, auth_headers, tmp_books_dir):
        """Book IDs with uppercase, spaces, or special chars are rejected."""
        resp = client.get("/api/thesis/builder/books/INVALID", headers=auth_headers)
        assert resp.status_code in (404, 422)
        resp2 = client.get("/api/thesis/builder/books/has spaces", headers=auth_headers)
        assert resp2.status_code in (404, 422)

    def test_get_existing_iran_book(self, auth_headers):
        """Load the real iran book through the builder API (no tmp_books_dir — uses real books/)."""
        resp = client.get("/api/thesis/builder/books/iran-hormuz-graph", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["title"].startswith("Iran")
        assert len(data["nodes"]) > 10
        assert len(data["edges"]) > 10
        assert "source" in data["edges"][0]
        assert "x" in data["nodes"][0]
    def test_get_existing_tariffs_book(self, auth_headers):
        resp = client.get("/api/thesis/builder/books/trump-tariffs-graph", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "tariff" in data["meta"]["title"].lower() or "trump" in data["meta"]["title"].lower()


# ── List endpoint tests ────────────────────────────────────────────────────

class TestBuilderListEndpoint:
    def test_list_empty(self, auth_headers, tmp_books_dir):
        resp = client.get("/api/thesis/builder/books", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self, auth_headers, tmp_books_dir, sample_book_payload):
        client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        resp = client.get("/api/thesis/builder/books", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "test-thesis-unit-test"
        assert data[0]["title"] == "Test Thesis — Unit Test"
        assert data[0]["nodes"] == 3
        assert data[0]["edges"] == 2
        # meta projection
        assert data[0]["monthlyBudget"] == 3000
        assert data[0]["asOf"] == "2026-04-17"

    def test_list_includes_non_graph_suffix(self, auth_headers, tmp_books_dir, sample_book_payload):
        """Builder may create books like 'test.json' (no -graph suffix);
        the canonical thesis listing only matches *-graph.json, but the
        builder list must show every editable book."""
        client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        resp = client.get("/api/thesis/builder/books", headers=auth_headers)
        # Verify the just-created file (which won't end in -graph.json) appears
        ids = [b["id"] for b in resp.json()]
        assert "test-thesis-unit-test" in ids

    def test_list_skips_corrupt_files(self, auth_headers, tmp_books_dir, sample_book_payload):
        client.post("/api/thesis/builder/books", json=sample_book_payload, headers=auth_headers)
        # Drop a malformed file alongside
        (tmp_books_dir / "broken.json").write_text("{ this is not json")
        resp = client.get("/api/thesis/builder/books", headers=auth_headers)
        assert resp.status_code == 200
        ids = [b["id"] for b in resp.json()]
        assert "test-thesis-unit-test" in ids
        assert "broken" not in ids

    def test_list_unauthenticated(self, tmp_books_dir):
        resp = client.get("/api/thesis/builder/books")
        assert resp.status_code in (401, 403)

class TestBuilderEdgeCases:
    def test_empty_book(self, auth_headers, tmp_books_dir):
        """A book with no nodes or edges should still save."""
        payload = {
            "meta": {"title": "Empty", "claim": "", "monthlyBudget": 0, "asOf": "2026-01-01"},
            "nodes": [],
            "edges": [],
            "instruments": {},
            "scenarios": [],
            "cascadePhases": {},
            "rules": [],
        }
        resp = client.post("/api/thesis/builder/books", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        book_id = resp.json()["id"]
        # Load it back
        resp2 = client.get(f"/api/thesis/builder/books/{book_id}", headers=auth_headers)
        assert resp2.status_code == 200
        assert len(resp2.json()["nodes"]) == 0

    def test_large_book(self, auth_headers, tmp_books_dir):
        """Create a book with many nodes and edges."""
        nodes = []
        for i in range(50):
            nodes.append({
                "id": f"node-{i}", "label": f"Node {i}", "type": "indicator",
                "phase": (i % 5) + 1, "state": "monitoring", "context": f"Node {i}",
                "x": (i % 5) * 280 + 100, "y": (i // 5) * 120 + 60,
                "probability": None, "current": None,
                "feeds": [], "thresholds": [], "indicators": [],
                "countdown": False, "deadline": None, "irreversible": False,
                "gatedBy": [], "logic": None,
            })
        edges = []
        for i in range(49):
            edges.append({
                "source": f"node-{i}", "target": f"node-{i+1}",
                "mechanism": "chain", "lag": "1 week", "strength": 0.8,
            })
        payload = {
            "meta": {"title": "Stress Test", "claim": "Many nodes", "monthlyBudget": 10000, "asOf": "2026-01-01"},
            "nodes": nodes, "edges": edges,
            "instruments": {}, "scenarios": [], "cascadePhases": {}, "rules": [],
        }
        resp = client.post("/api/thesis/builder/books", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        resp2 = client.get(f"/api/thesis/builder/books/{resp.json()['id']}", headers=auth_headers)
        assert len(resp2.json()["nodes"]) == 50
        assert len(resp2.json()["edges"]) == 49
    def test_special_characters_in_context(self, auth_headers, tmp_books_dir):
        """Unicode and special chars should survive round-trip."""
        payload = {
            "meta": {"title": "Emoji Test 🚀", "claim": "日本語テスト — dashes & <html>", "monthlyBudget": 0, "asOf": "2026-01-01"},
            "nodes": [{
                "id": "test", "label": "Test — «quotes»", "type": "event",
                "phase": 1, "state": "monitoring", "context": "Context with émojis 🎯 and 中文",
                "x": 100, "y": 60, "probability": None, "current": None,
                "feeds": [], "thresholds": [], "indicators": [],
                "countdown": False, "deadline": None, "irreversible": False,
                "gatedBy": [], "logic": None,
            }],
            "edges": [], "instruments": {}, "scenarios": [],
            "cascadePhases": {}, "rules": [],
        }
        resp = client.post("/api/thesis/builder/books", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        resp2 = client.get(f"/api/thesis/builder/books/{resp.json()['id']}", headers=auth_headers)
        assert "émojis 🎯" in resp2.json()["nodes"][0]["context"]
        assert "日本語テスト" in resp2.json()["meta"]["claim"]


class TestDialecticRoomBinding:
    """meta.dialecticRoomId — how a Dialectic-created thesis is born bound."""

    ROOM = "0f9b8f9c-1111-4222-8333-444455556666"

    def test_create_with_room_id_lands_in_meta(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        sample_book_payload["meta"]["dialecticRoomId"] = self.ROOM
        resp = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        book_id = resp.json()["id"]
        saved = json.loads((tmp_books_dir / f"{book_id}.json").read_text())
        assert saved["meta"]["dialecticRoomId"] == self.ROOM
        # And never the token — that lives in the environment/runtime file.
        assert "dialecticRoomToken" not in saved["meta"]

    def test_create_without_room_id_omits_the_key(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        resp = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        book_id = resp.json()["id"]
        saved = json.loads((tmp_books_dir / f"{book_id}.json").read_text())
        assert "dialecticRoomId" not in saved["meta"]

    def test_get_round_trips_the_binding(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        sample_book_payload["meta"]["dialecticRoomId"] = self.ROOM
        created = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        ).json()
        got = client.get(
            f"/api/thesis/builder/books/{created['id']}", headers=auth_headers,
        )
        assert got.status_code == 200
        assert got.json()["meta"]["dialecticRoomId"] == self.ROOM

    def test_bound_books_join_the_graph_naming_convention(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        """The dashboard list and the room→book join glob *-graph.json —
        a room-bound book outside that pattern would be invisible to both."""
        sample_book_payload["meta"]["dialecticRoomId"] = self.ROOM
        resp = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        )
        assert resp.json()["id"] == "test-thesis-unit-test-graph"

    def test_repeated_bound_create_returns_the_same_book(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        sample_book_payload["meta"]["dialecticRoomId"] = self.ROOM
        first = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        ).json()["id"]
        second = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        ).json()["id"]
        assert second == first == "test-thesis-unit-test-graph"
        assert len(list(tmp_books_dir.glob("*-graph.json"))) == 1

    def test_concurrent_bound_create_writes_one_book(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        sample_book_payload["meta"]["dialecticRoomId"] = self.ROOM

        def create(_: int):
            return client.post(
                "/api/thesis/builder/books",
                json=sample_book_payload,
                headers=auth_headers,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(create, range(2)))

        assert [response.status_code for response in responses] == [200, 200]
        assert len({response.json()["id"] for response in responses}) == 1
        assert len(list(tmp_books_dir.glob("*-graph.json"))) == 1

    def test_same_title_bound_to_different_rooms_keeps_collision_suffix(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        sample_book_payload["meta"]["dialecticRoomId"] = self.ROOM
        first = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        ).json()["id"]
        sample_book_payload["meta"]["dialecticRoomId"] = "another-room"
        second = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        ).json()["id"]

        assert first == "test-thesis-unit-test-graph"
        assert second == "test-thesis-unit-test-1-graph"

    def test_unbound_ids_are_unchanged(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        """The desk's own builder keeps its historical naming."""
        resp = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        )
        assert resp.json()["id"] == "test-thesis-unit-test"


class TestRuntimeAdoption:
    """A book saved while the desk runs must reach the live cycle set."""

    class _StubCoordinator:
        def __init__(self):
            self.adopted = []

        def adopt_book(self, book_id):
            self.adopted.append(book_id)
            return True

    @pytest.fixture
    def stub_coordinator(self):
        stub = self._StubCoordinator()
        app.state.coordinator = stub
        yield stub
        del app.state.coordinator

    def test_create_adopts_into_runtime(
        self, auth_headers, tmp_books_dir, sample_book_payload, stub_coordinator
    ):
        resp = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        )
        assert stub_coordinator.adopted == [resp.json()["id"]]

    def test_update_adopts_into_runtime(
        self, auth_headers, tmp_books_dir, sample_book_payload, stub_coordinator
    ):
        book_id = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        ).json()["id"]
        client.put(
            f"/api/thesis/builder/books/{book_id}", json=sample_book_payload,
            headers=auth_headers,
        )
        assert stub_coordinator.adopted == [book_id, book_id]

    def test_no_coordinator_is_fine(
        self, auth_headers, tmp_books_dir, sample_book_payload
    ):
        """Lifespan-less contexts (tests, scripts) must not 500."""
        resp = client.post(
            "/api/thesis/builder/books", json=sample_book_payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
