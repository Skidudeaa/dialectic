"""
Tests for the service-token read endpoints on /api/bridge.

WHY these exist: Dialectic's scheduler pulls GET /api/bridge/snapshot/{book}
every 15 minutes to repair a room that missed a push, and its LLM tools read
GET /api/bridge/news/{book}. Both are machine callers with no JWT, gated by
the TD_SERVICE_TOKEN shared secret instead.

WHY content-type is asserted explicitly: this app answers unknown paths with
200 + index.html from the SPA catch-all, so Dialectic's reconcile job treats
"200 but not application/json" as endpoint-missing. A regression that shadowed
these routes would look like a passing 200 to a naive test.
"""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

# Same env-var trick as test_bridge.py — deterministic JWT secret per run.
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.deps import get_repo
from web.persistence.repository import Repository
from web.routes import bridge as bridge_mod


SERVICE_TOKEN = "test-service-token-abc123"
THESIS_ID = "iran-hormuz-graph"

SNAPSHOT_BODY = {
    "v": 2,
    "timestamp": "2026-08-09T05:07:15Z",
    "title": "Iran/Hormuz Thesis",
    "nodeStates": {"hormuz_closure": "approaching", "brent_spike": "stable"},
    "confluenceScores": {"oil_supply_shock": 0.61},
    "cascadePhase": {"number": 2, "key": "escalation", "status": "active"},
    "thesisId": THESIS_ID,
    "revision": 4211,
    "generatedAt": "2026-08-09T05:07:15.775368+00:00",
}


@pytest.fixture
def repo():
    """In-memory repository seeded with one committed snapshot."""
    r = Repository(":memory:")
    r.initialize()
    r.save_snapshot(
        THESIS_ID, 4211, json.dumps(SNAPSHOT_BODY),
        definition_hash="sha256:deadbeef",
    )
    return r


@pytest.fixture
def client(repo, monkeypatch):
    """TestClient with the repo dependency overridden and the secret set."""
    monkeypatch.setenv(bridge_mod.SERVICE_TOKEN_ENV, SERVICE_TOKEN)
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_repo, None)


@pytest.fixture(autouse=True)
def clear_news_cache():
    """The news TTL cache is module-global — never leak between tests."""
    bridge_mod._news_cache.clear()
    bridge_mod._news_rate_limit_streak.clear()
    yield
    bridge_mod._news_cache.clear()
    bridge_mod._news_rate_limit_streak.clear()


def svc_headers(token: str = SERVICE_TOKEN) -> dict:
    return {"X-Service-Token": token}


# =========================================================================
# SERVICE TOKEN AUTH
# =========================================================================


class TestServiceTokenAuth:
    def test_missing_header_is_401(self, client):
        resp = client.get(f"/api/bridge/snapshot/{THESIS_ID}")
        assert resp.status_code == 401

    def test_wrong_token_is_401(self, client):
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}",
            headers=svc_headers("not-the-token"),
        )
        assert resp.status_code == 401

    def test_empty_token_is_401(self, client):
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers(""),
        )
        assert resp.status_code == 401

    def test_correct_token_is_200(self, client):
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers(),
        )
        assert resp.status_code == 200

    def test_news_is_gated_too(self, client):
        """Both service endpoints share the gate — not just the snapshot one."""
        resp = client.get(f"/api/bridge/news/{THESIS_ID}")
        assert resp.status_code == 401

    def test_unconfigured_secret_is_503_not_401(self, client, monkeypatch):
        """An unset secret is a broken server, not a rejected caller.

        A 401 here would send Dialectic hunting for a bad token that does
        not exist; 503 says the fault is on this side.
        """
        monkeypatch.delenv(bridge_mod.SERVICE_TOKEN_ENV, raising=False)
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers(),
        )
        assert resp.status_code == 503
        assert bridge_mod.SERVICE_TOKEN_ENV in resp.json()["detail"]

    def test_blank_secret_is_503(self, client, monkeypatch):
        """Whitespace-only env value must not become a guessable secret."""
        monkeypatch.setenv(bridge_mod.SERVICE_TOKEN_ENV, "   ")
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers("   "),
        )
        assert resp.status_code == 503


# =========================================================================
# GET /api/bridge/snapshot/{thesis_id}
# =========================================================================


class TestSnapshotEndpoint:
    def test_content_type_is_json(self, client):
        """The SPA catch-all answers 200 + HTML; Dialectic reads content-type
        to tell a real endpoint from a shadowed one."""
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers(),
        )
        assert resp.headers["content-type"].startswith("application/json")

    def test_returns_v3_contract(self, client):
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers(),
        )
        body = resp.json()
        assert body["v"] == 3
        assert body["alertEvents"] == []
        assert body["thesisId"] == THESIS_ID
        assert body["revision"] == 4211
        assert body["generatedAt"] == SNAPSHOT_BODY["generatedAt"]

    def test_preserves_v2_fields(self, client):
        """v3 is additive — every v2 field survives untouched."""
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers(),
        )
        body = resp.json()
        assert body["timestamp"] == SNAPSHOT_BODY["timestamp"]
        assert body["title"] == SNAPSHOT_BODY["title"]
        assert body["nodeStates"] == SNAPSHOT_BODY["nodeStates"]
        assert body["confluenceScores"] == SNAPSHOT_BODY["confluenceScores"]
        assert body["cascadePhase"] == SNAPSHOT_BODY["cascadePhase"]

    def test_internal_revision_marker_not_leaked(self, client):
        """get_latest_snapshot stamps `_revision`; it must not reach the wire."""
        resp = client.get(
            f"/api/bridge/snapshot/{THESIS_ID}", headers=svc_headers(),
        )
        assert "_revision" not in resp.json()

    def test_revision_falls_back_to_row_when_body_lacks_it(self, client, repo):
        """Snapshots stored before the coordinator stamped `revision` inline
        still answer with a revision — read off the row."""
        legacy = {k: v for k, v in SNAPSHOT_BODY.items()
                  if k not in ("revision", "thesisId", "generatedAt")}
        repo.save_snapshot("legacy-book", 7, json.dumps(legacy))
        resp = client.get(
            "/api/bridge/snapshot/legacy-book", headers=svc_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["revision"] == 7

    def test_unknown_thesis_is_404(self, client):
        resp = client.get(
            "/api/bridge/snapshot/no-such-book", headers=svc_headers(),
        )
        assert resp.status_code == 404

    def test_unknown_thesis_404_beats_the_spa_catchall(self, client):
        """A 404 here must be this route's 404, not the SPA's HTML fallback."""
        resp = client.get(
            "/api/bridge/snapshot/no-such-book", headers=svc_headers(),
        )
        assert resp.headers["content-type"].startswith("application/json")
        assert "no-such-book" in resp.json()["detail"]


# =========================================================================
# GET /api/bridge/news/{thesis_id}
# =========================================================================


class TestBookPathContainment:
    """_book_path is the guard; test it where it lives.

    Going through HTTP cannot exercise it: Starlette's default path converter
    refuses to match `/` into a single segment, so an encoded `../../x` never
    reaches the handler at all — it falls through to the SPA catch-all and
    answers 200 + HTML. A route-level 'traversal' assertion would therefore
    pass without the guard existing.
    """

    def test_escaping_ids_resolve_to_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bridge_mod, "_BOOKS_DIR", tmp_path / "books")
        (tmp_path / "books").mkdir()
        (tmp_path / "secret.json").write_text('{"a": 1}')
        assert bridge_mod._book_path("../secret") is None
        assert bridge_mod._book_path("..") is None

    def test_real_book_resolves(self, tmp_path, monkeypatch):
        books = tmp_path / "books"
        books.mkdir()
        (books / "real.json").write_text('{"nodes": []}')
        monkeypatch.setattr(bridge_mod, "_BOOKS_DIR", books)
        assert bridge_mod._book_path("real") == (books / "real.json").resolve()

    def test_missing_book_resolves_to_none(self, tmp_path, monkeypatch):
        books = tmp_path / "books"
        books.mkdir()
        monkeypatch.setattr(bridge_mod, "_BOOKS_DIR", books)
        assert bridge_mod._book_path("absent") is None


class TestNewsEndpoint:
    def test_unknown_book_is_404(self, client):
        resp = client.get("/api/bridge/news/no-such-book", headers=svc_headers())
        assert resp.status_code == 404

    # WHY no route-level traversal test: neither an encoded nor a literal
    # `..` can reach this handler — httpx normalizes the literal form out of
    # the URL, and Starlette's path converter refuses to match `/` into one
    # segment, so both land on the SPA catch-all's 200 + HTML. Such a test
    # would pass with the guard deleted. See TestBookPathContainment.

    def test_returns_headlines_capped_at_15(self, client, monkeypatch):
        from tools.data_fetch import gdelt

        made = [
            gdelt.Article(
                url=f"https://example.test/{i}",
                title=f"Headline {i}",
                seendate="20260809T050000Z",
                domain="example.test",
                language="English",
                sourcecountry="US",
            )
            for i in range(30)
        ]
        monkeypatch.setattr(gdelt, "fetch_articles", lambda *a, **k: made)

        resp = client.get(
            f"/api/bridge/news/{THESIS_ID}", headers=svc_headers(),
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        articles = resp.json()["articles"]
        assert len(articles) == 15
        assert articles[0] == {
            "title": "Headline 0",
            "url": "https://example.test/0",
            "seendate": "20260809T050000Z",
            "domain": "example.test",
        }

    def test_book_query_is_resolved_from_standard_query(self, client, monkeypatch):
        """iran-hormuz-graph declares standardQuery 'iran-hormuz-event' — the
        fetcher must receive the RESOLVED query string, not the name."""
        from tools.data_fetch import gdelt

        seen = {}

        def _capture(query, **kwargs):
            seen["query"] = query
            return []

        monkeypatch.setattr(gdelt, "fetch_articles", _capture)
        client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        assert seen["query"] == gdelt.get_standard_query("iran-hormuz-event")
        assert "Hormuz" in seen["query"]

    def test_book_without_gdelt_feed_returns_note(self, client, monkeypatch, tmp_path):
        book = tmp_path / "quiet-book.json"
        book.write_text(json.dumps({"meta": {}, "nodes": [{"id": "a"}]}))
        monkeypatch.setattr(bridge_mod, "_BOOKS_DIR", tmp_path)

        resp = client.get("/api/bridge/news/quiet-book", headers=svc_headers())
        assert resp.status_code == 200
        assert resp.json() == {"articles": [], "note": "no gdelt config"}

    def test_gdelt_failure_is_not_a_500(self, client, monkeypatch):
        """A dark upstream feed degrades to an empty list with a note."""
        from tools.data_fetch import gdelt

        def _boom(*a, **k):
            raise gdelt.GdeltRateLimitError("429")

        monkeypatch.setattr(gdelt, "fetch_articles", _boom)
        resp = client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["articles"] == []
        assert "gdelt unavailable" in body["note"]

    def test_consecutive_rate_limits_back_off(self, client, monkeypatch):
        """A 429 is the upstream saying we ask too often — hold the miss longer.

        WHY this is not the same as any other failure: on the flat 120s error
        TTL, five books re-attempt roughly every 24s between them, which is
        what keeps a per-IP throttle warm. Observed 2026-08-10: four of five
        books sat rate-limited for hours and the retries were the reason.
        """
        from tools.data_fetch import gdelt

        def _boom(*a, **k):
            raise gdelt.GdeltRateLimitError("429")

        monkeypatch.setattr(gdelt, "fetch_articles", _boom)

        holds = []
        for _ in range(4):
            client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
            expires_at, _payload = bridge_mod._news_cache[THESIS_ID]
            holds.append(round(expires_at - time.monotonic()))
            bridge_mod._news_cache.clear()  # simulate the hold elapsing

        assert holds == [120, 240, 480, 900]
        assert max(holds) <= bridge_mod.NEWS_TTL_SECONDS, \
            "a throttled feed must never be polled harder than a healthy one"

    def test_a_non_rate_limit_error_keeps_the_short_ttl(self, client, monkeypatch):
        """Only a 429 earns the long hold — other errors are still guesses."""
        from tools.data_fetch import gdelt

        def _boom(*a, **k):
            raise gdelt.GdeltAPIError("malformed body")

        monkeypatch.setattr(gdelt, "fetch_articles", _boom)
        for _ in range(3):
            client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
            expires_at, _payload = bridge_mod._news_cache[THESIS_ID]
            assert round(expires_at - time.monotonic()) == 120
            bridge_mod._news_cache.clear()

    def test_one_good_fetch_clears_the_streak(self, client, monkeypatch):
        from tools.data_fetch import gdelt

        def _boom(*a, **k):
            raise gdelt.GdeltRateLimitError("429")

        monkeypatch.setattr(gdelt, "fetch_articles", _boom)
        for _ in range(3):
            client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
            bridge_mod._news_cache.clear()
        assert bridge_mod._news_rate_limit_streak[THESIS_ID] == 3

        monkeypatch.setattr(gdelt, "fetch_articles", lambda *a, **k: [])
        client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        assert THESIS_ID not in bridge_mod._news_rate_limit_streak

        bridge_mod._news_cache.clear()
        monkeypatch.setattr(gdelt, "fetch_articles", _boom)
        client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        expires_at, _payload = bridge_mod._news_cache[THESIS_ID]
        assert round(expires_at - time.monotonic()) == 120, "back to the base hold"

    def test_second_request_is_served_from_cache(self, client, monkeypatch):
        """GDELT asks for ~1 req/sec; a chatty room must not hammer it."""
        from tools.data_fetch import gdelt

        calls = []

        def _count(query, **kwargs):
            calls.append(query)
            return []

        monkeypatch.setattr(gdelt, "fetch_articles", _count)
        client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        assert len(calls) == 1

    def test_expired_cache_refetches(self, client, monkeypatch):
        from tools.data_fetch import gdelt

        calls = []

        def _count(query, **kwargs):
            calls.append(query)
            return []

        monkeypatch.setattr(gdelt, "fetch_articles", _count)
        client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        # Expire the entry rather than sleeping 15 minutes.
        expires, payload = bridge_mod._news_cache[THESIS_ID]
        bridge_mod._news_cache[THESIS_ID] = (0.0, payload)
        client.get(f"/api/bridge/news/{THESIS_ID}", headers=svc_headers())
        assert len(calls) == 2


# =========================================================================
# ROOM TOKEN REGISTRATION
# =========================================================================


class TestRoomTokenRegistration:
    """POST /api/bridge/room-token — the one write on the bridge.

    It exists so a thesis created from Dialectic can start pushing without
    a desk restart; the token lands in the runtime file, never in a book.
    """

    ROOM = "0f9b8f9c-1111-4222-8333-444455556666"

    @pytest.fixture(autouse=True)
    def tokens_file(self, tmp_path, monkeypatch):
        from tools.bridge.room_tokens import ENV_ROOM_TOKENS_FILE
        path = tmp_path / "room-tokens.env"
        monkeypatch.setenv(ENV_ROOM_TOKENS_FILE, str(path))
        return path

    def test_gated_by_service_token(self, client):
        resp = client.post(
            "/api/bridge/room-token",
            json={"room_id": self.ROOM, "token": "tok"},
        )
        assert resp.status_code == 401

    def test_registers_and_resolves(self, client, tokens_file):
        from tools.bridge.room_tokens import resolve_room_token
        resp = client.post(
            "/api/bridge/room-token",
            json={"room_id": self.ROOM, "token": "tok-new"},
            headers=svc_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert tokens_file.exists()
        assert resolve_room_token({"dialecticRoomId": self.ROOM}) == "tok-new"

    def test_non_uuid_room_is_422(self, client):
        resp = client.post(
            "/api/bridge/room-token",
            json={"room_id": "not-a-uuid", "token": "tok"},
            headers=svc_headers(),
        )
        assert resp.status_code == 422

    def test_empty_token_is_422(self, client):
        resp = client.post(
            "/api/bridge/room-token",
            json={"room_id": self.ROOM, "token": "  "},
            headers=svc_headers(),
        )
        assert resp.status_code == 422


# =========================================================================
# ROOM UNBIND — the retire flow's td half
# =========================================================================


class TestRoomUnbind:
    """The book survives retirement: it loses its room claim and its push
    path, nothing else."""

    ROOM = "0f9b8f9c-1111-4222-8333-444455556666"

    @pytest.fixture(autouse=True)
    def tokens_file(self, tmp_path, monkeypatch):
        from tools.bridge.room_tokens import ENV_ROOM_TOKENS_FILE
        monkeypatch.setenv(ENV_ROOM_TOKENS_FILE, str(tmp_path / "tokens.env"))

    @pytest.fixture
    def books_dir(self, tmp_path, monkeypatch):
        books = tmp_path / "books"
        books.mkdir()
        book = {
            "meta": {"title": "Bound", "type": "thesis-graph",
                     "dialecticRoomId": self.ROOM},
            "nodes": [{"id": "a", "label": "A", "type": "event", "phase": 1,
                       "state": "monitoring"}],
            "edges": [],
        }
        (books / "bound-graph.json").write_text(json.dumps(book))
        other = {"meta": {"title": "Other", "type": "thesis-graph"},
                 "nodes": [], "edges": []}
        (books / "other-graph.json").write_text(json.dumps(other))
        monkeypatch.setattr(bridge_mod, "_BOOKS_DIR", books)
        return books

    def test_gated_by_service_token(self, client, books_dir):
        resp = client.post("/api/bridge/room-unbind",
                           json={"room_id": self.ROOM})
        assert resp.status_code == 401

    def test_unbind_strips_the_claim_and_the_token(self, client, books_dir):
        from tools.bridge.room_tokens import (
            load_file_tokens, register_room_token,
        )
        register_room_token(self.ROOM, "tok")
        resp = client.post("/api/bridge/room-unbind",
                           json={"room_id": self.ROOM},
                           headers=svc_headers())
        assert resp.status_code == 200
        assert resp.json()["unbound"] == ["bound-graph"]
        saved = json.loads((books_dir / "bound-graph.json").read_text())
        assert "dialecticRoomId" not in saved["meta"]
        # The book itself survives, nodes intact.
        assert saved["nodes"][0]["id"] == "a"
        # The other book was never touched.
        other = json.loads((books_dir / "other-graph.json").read_text())
        assert other["meta"]["title"] == "Other"
        assert load_file_tokens() == {}

    def test_unbind_readopts_into_the_runtime(self, client, books_dir):
        adopted = []
        app.state.coordinator = type(
            "Stub", (), {"adopt_book": lambda self, b: adopted.append(b)}
        )()
        try:
            client.post("/api/bridge/room-unbind",
                        json={"room_id": self.ROOM}, headers=svc_headers())
        finally:
            del app.state.coordinator
        assert adopted == ["bound-graph"]

    def test_unbinding_an_unclaimed_room_is_calm(self, client, books_dir):
        resp = client.post(
            "/api/bridge/room-unbind",
            json={"room_id": "99999999-9999-4999-8999-999999999999"},
            headers=svc_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["unbound"] == []

    def test_non_uuid_room_is_422(self, client, books_dir):
        resp = client.post("/api/bridge/room-unbind",
                           json={"room_id": "nope"}, headers=svc_headers())
        assert resp.status_code == 422


class TestCorruptBookSurvival:
    """One corrupt book file must not sys.exit the web process — load_config
    is a CLI helper whose exits no `except Exception` catches. The safe
    loader converts them to None and every surface skips."""

    def test_load_book_config_returns_none_on_corrupt(self, tmp_path):
        from web.adapters.thesis import load_book_config
        bad = tmp_path / "corrupt-graph.json"
        bad.write_text("{not json")
        assert load_book_config(bad) is None
        assert load_book_config(tmp_path / "missing-graph.json") is None

    def test_list_books_skips_the_corrupt_one(self, tmp_path, monkeypatch):
        import web.adapters.thesis as thesis_mod
        good = {"meta": {"title": "Good"}, "nodes": [], "edges": []}
        (tmp_path / "good-graph.json").write_text(json.dumps(good))
        (tmp_path / "corrupt-graph.json").write_text("{not json")
        monkeypatch.setattr(thesis_mod, "BOOKS_DIR", tmp_path)
        books = thesis_mod.list_books()
        assert [b["id"] for b in books] == ["good-graph"]

    def test_definition_scan_survives_a_corrupt_book(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        import web.runtime.coordinator as coord_mod
        from web.persistence.repository import Repository
        good = {"meta": {"title": "Good"}, "nodes": [], "edges": []}
        (tmp_path / "good-graph.json").write_text(json.dumps(good))
        (tmp_path / "corrupt-graph.json").write_text("{not json")
        monkeypatch.setattr(coord_mod, "BOOKS_DIR", tmp_path)
        r = Repository(":memory:")
        r.initialize()
        c = coord_mod.RuntimeCoordinator(repo=r, ws_manager=MagicMock(),
                                         tick_interval=9999)
        c._load_definitions()  # would previously sys.exit here
        assert set(c.definitions) == {"good-graph"}
