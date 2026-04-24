"""
Tests for the TradingView webapp integration.

Coverage:
- web/tv_webhook.py (pure verification functions + NonceStore)
- web/adapters/tradingview.py (binding resolution + op contract + atomic mutation)
- web/routes/tradingview.py (webhook endpoint + status + events + binding CRUD)

Fixture strategy:
- Each test uses an isolated books dir monkey-patched into the adapter
  module. No test ever writes to the real books/ directory.
- The nonce store + rate limiter are module-level singletons; autouse
  fixtures reset them between cases.
- State file I/O is redirected through an isolate_state fixture that
  repoints DATA_DIR / TV_EVENTS_FILE / etc. at tmp_path.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Set env before import — matches web/test_web.py pattern
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")
os.environ["TV_WEBHOOK_SECRET"] = "tv-test-secret"
os.environ["TV_WEBHOOK_RATE_LIMIT_PER_MIN"] = "1000"  # generous for tests

from web.main import app  # noqa: E402
from web.adapters import tradingview as tv_adapter  # noqa: E402
from web.deps import get_repo  # noqa: E402
from web.persistence.repository import Repository  # noqa: E402
from web.adapters import thesis as thesis_adapter  # noqa: E402
from web.auth import create_access_token  # noqa: E402
from web.routes import tradingview as tv_routes  # noqa: E402
from web.tv_webhook import (  # noqa: E402
    DEFAULT_CLOCK_SKEW_SECONDS,
    NonceStore,
    VerificationContext,
    VerifyResult,
    nonce_store,
    sign_body,
    sign_canonical,
    verify_request,
    verify_signature,
    verify_timestamp,
)

client = TestClient(app)

TV_SECRET = "tv-test-secret"


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def auth_headers() -> dict:
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def reset_modules():
    """Clear shared singletons between tests."""
    nonce_store.clear()
    tv_routes.rate_limiter.reset()
    # Clear thesis cache
    thesis_adapter._state_cache.clear()
    yield
    nonce_store.clear()
    tv_routes.rate_limiter.reset()


@pytest.fixture(autouse=True)
def isolate_state():
    """Inject fresh in-memory SQLite per test via dependency override."""
    repo = Repository(":memory:")
    repo.initialize()
    app.dependency_overrides[get_repo] = lambda: repo
    app.state.repo = repo
    from web.ws import manager
    manager.set_repo(repo)
    yield repo
    app.dependency_overrides.pop(get_repo, None)


@pytest.fixture
def temp_books(tmp_path: Path):
    """Create an isolated books/ dir with one thesis book, monkey-patch the
    adapter's BOOKS_DIR to point at it, and return the dir path."""
    books_dir = tmp_path / "books"
    books_dir.mkdir()
    book = {
        "meta": {"title": "Test Thesis", "version": "1.0", "type": "thesis-graph"},
        "nodes": [
            {
                "id": "brent",
                "label": "Brent",
                "type": "price",
                "current": 116.0,
                "thresholds": [
                    {"level": 115, "label": "persistence", "closesRequired": 3}
                ],
                "closesObserved": 0,
                "tvAlertBindings": [
                    {
                        "bindingId": "brent-persistence-close-above-115",
                        "nodeId": "brent",
                        "op": "incrementClosesObserved",
                        "thresholdLevel": 115,
                        "expectedSymbol": "BZ=F",
                        "expectedPineAlertName": "brent_persistence_close_115",
                        "description": "Pine alert on brent close above $115",
                        "fireCount": 0,
                        "lastFiredAt": None,
                    },
                ],
            },
            {
                "id": "hormuz",
                "label": "Hormuz",
                "type": "event",
                "state": "monitoring",
                "probability": 0.5,
                "tvAlertBindings": [
                    {
                        "bindingId": "hormuz-reopen-announced",
                        "nodeId": "hormuz",
                        "op": "setNodeState",
                        "targetState": "resolved",
                        "description": "Manual Pine alert when reopen announced",
                        "fireCount": 0,
                        "lastFiredAt": None,
                    },
                    {
                        "bindingId": "hormuz-prob-bump",
                        "nodeId": "hormuz",
                        "op": "setProbability",
                        "description": "Bump hormuz probability",
                        "fireCount": 0,
                        "lastFiredAt": None,
                    },
                ],
            },
            {
                "id": "diesel",
                "label": "Diesel",
                "type": "price",
                "current": 5.38,
                "thresholds": [],
                "tvAlertBindings": [
                    {
                        "bindingId": "diesel-set",
                        "nodeId": "diesel",
                        "op": "setCurrent",
                        "description": "Direct price override",
                        "fireCount": 0,
                        "lastFiredAt": None,
                    },
                ],
            },
        ],
        "edges": [],
    }
    (books_dir / "test-book.json").write_text(json.dumps(book, indent=2))

    original_books = tv_adapter.BOOKS_DIR
    original_thesis_books = thesis_adapter.BOOKS_DIR
    import web.runtime.coordinator as coord_mod
    original_coord_books = coord_mod.BOOKS_DIR
    tv_adapter.BOOKS_DIR = books_dir
    thesis_adapter.BOOKS_DIR = books_dir
    coord_mod.BOOKS_DIR = books_dir

    # Unit 11b: TV webhooks route through the coordinator. Spin up a fresh
    # coordinator scoped to the temp books dir and the test's in-memory repo.
    # We don't call start() — the tick loop isn't needed for webhook tests —
    # just load definitions so `submit()` accepts the test-book thesis id.
    from web.runtime.coordinator import RuntimeCoordinator
    from web.ws import manager as ws_manager
    coordinator = RuntimeCoordinator(
        repo=app.state.repo, ws_manager=ws_manager, tick_interval=9999,
    )
    coordinator._load_definitions()
    app.state.coordinator = coordinator

    yield books_dir

    tv_adapter.BOOKS_DIR = original_books
    thesis_adapter.BOOKS_DIR = original_thesis_books
    coord_mod.BOOKS_DIR = original_coord_books
    if hasattr(app.state, "coordinator"):
        delattr(app.state, "coordinator")


def _signed_webhook_headers(body: bytes, *, ts: int | None = None,
                            nonce: str = "abc123def456nonce") -> dict:
    if ts is None:
        ts = int(time.time())
    return {
        "X-TV-Signature": sign_canonical(str(ts), nonce, body, TV_SECRET),
        "X-TV-Timestamp": str(ts),
        "X-TV-Nonce": nonce,
        "Content-Type": "application/json",
    }


def _post_webhook(payload: dict, *, ts: int | None = None,
                  nonce: str | None = None, headers: dict | None = None):
    body = json.dumps(payload).encode()
    hdrs = _signed_webhook_headers(
        body,
        ts=ts,
        nonce=nonce if nonce is not None else f"nonce-{int(time.time()*1000)}-{id(payload)}",
    )
    if headers:
        hdrs.update(headers)
    return client.post("/api/tradingview/webhook", content=body, headers=hdrs)


# ═════════════════════════════════════════════════════════════════════════
# Pure verification functions
# ═════════════════════════════════════════════════════════════════════════

class TestPureVerification:
    def test_verify_signature_valid(self):
        body = b'{"a":1}'
        sig = sign_body(body, "secret")
        assert verify_signature(body, sig, b"secret") is True

    def test_verify_signature_wrong_secret(self):
        body = b'{"a":1}'
        sig = sign_body(body, "real-secret")
        assert verify_signature(body, sig, b"wrong-secret") is False

    def test_verify_signature_missing_prefix(self):
        # A raw hex without "sha256=" must be rejected
        import hmac, hashlib
        body = b'{"a":1}'
        bad = hmac.new(b"secret", body, hashlib.sha256).hexdigest()  # no prefix
        assert verify_signature(body, bad, b"secret") is False

    def test_verify_signature_empty(self):
        assert verify_signature(b'{}', "", b"secret") is False

    def test_verify_signature_none_header(self):
        assert verify_signature(b'{}', None, b"secret") is False  # type: ignore[arg-type]

    def test_verify_timestamp_valid(self):
        now = time.time()
        assert verify_timestamp(str(int(now)), now) is True

    def test_verify_timestamp_expired(self):
        now = time.time()
        past = int(now - 1000)
        assert verify_timestamp(str(past), now) is False

    def test_verify_timestamp_future(self):
        now = time.time()
        future = int(now + 1000)
        assert verify_timestamp(str(future), now) is False

    def test_verify_timestamp_non_numeric(self):
        assert verify_timestamp("not-a-number", time.time()) is False

    def test_verify_timestamp_empty(self):
        assert verify_timestamp("", time.time()) is False

    def test_verify_timestamp_at_edge_in(self):
        # Exactly at the skew edge is accepted. Use fixed now to avoid
        # float rounding drift on time.time().
        now = 1_700_000_000.0
        at_edge = int(now) - DEFAULT_CLOCK_SKEW_SECONDS
        assert verify_timestamp(str(at_edge), now) is True

    def test_verify_timestamp_past_edge(self):
        now = 1_700_000_000.0
        past_edge = int(now) - DEFAULT_CLOCK_SKEW_SECONDS - 1
        assert verify_timestamp(str(past_edge), now) is False


class TestNonceStore:
    def test_first_use_not_seen(self):
        store = NonceStore(ttl_seconds=60)
        assert store.seen("nonce-1") is False

    def test_second_use_is_replay(self):
        store = NonceStore(ttl_seconds=60)
        store.seen("nonce-1")
        assert store.seen("nonce-1") is True

    def test_different_nonces_independent(self):
        store = NonceStore(ttl_seconds=60)
        store.seen("nonce-1")
        assert store.seen("nonce-2") is False

    def test_ttl_pruning_releases_nonce(self):
        store = NonceStore(ttl_seconds=10)
        t0 = 1_700_000_000.0
        store.seen("nonce-1", now=t0)
        # Same nonce within TTL → replay
        assert store.seen("nonce-1", now=t0 + 5) is True
        # Well after TTL → pruned, first-use again
        assert store.seen("nonce-1", now=t0 + 100) is False

    def test_clear_empties_store(self):
        store = NonceStore()
        store.seen("n1")
        store.seen("n2")
        assert len(store) == 2
        store.clear()
        assert len(store) == 0


class TestVerifyRequest:
    def test_no_secret_returns_no_secret(self):
        body = b'{}'
        ctx = VerificationContext(
            body=body,
            signature_header=sign_body(body, "x"),
            timestamp_header=str(int(time.time())),
            nonce_header="nonce12345",
            secret=None,
        )
        assert verify_request(ctx) == VerifyResult.NO_SECRET

    def test_happy_path_returns_ok(self):
        nonce_store.clear()
        body = b'{"a":1}'
        ts = str(int(time.time()))
        nonce = "happy-path-nonce"
        ctx = VerificationContext(
            body=body,
            signature_header=sign_canonical(ts, nonce, body, TV_SECRET),
            timestamp_header=ts,
            nonce_header=nonce,
            secret=TV_SECRET,
        )
        assert verify_request(ctx) == VerifyResult.OK

    def test_bad_timestamp_returns_bad_timestamp(self):
        body = b'{}'
        ctx = VerificationContext(
            body=body,
            signature_header=sign_body(body, TV_SECRET),
            timestamp_header="garbage",
            nonce_header="nonce12345",
            secret=TV_SECRET,
        )
        assert verify_request(ctx) == VerifyResult.BAD_TIMESTAMP

    def test_short_nonce_returns_bad_nonce(self):
        body = b'{}'
        ctx = VerificationContext(
            body=body,
            signature_header=sign_body(body, TV_SECRET),
            timestamp_header=str(int(time.time())),
            nonce_header="short",  # <8 chars
            secret=TV_SECRET,
        )
        assert verify_request(ctx) == VerifyResult.BAD_NONCE

    def test_bad_signature_returns_bad_signature(self):
        body = b'{}'
        ctx = VerificationContext(
            body=body,
            signature_header="sha256=deadbeef",
            timestamp_header=str(int(time.time())),
            nonce_header="nonce12345",
            secret=TV_SECRET,
        )
        assert verify_request(ctx) == VerifyResult.BAD_SIGNATURE

    def test_replay_returns_nonce_replay(self):
        nonce_store.clear()
        body = b'{}'
        nonce = "replay-test-nonce"
        ts1 = str(int(time.time()))
        ctx1 = VerificationContext(
            body=body,
            signature_header=sign_canonical(ts1, nonce, body, TV_SECRET),
            timestamp_header=ts1,
            nonce_header=nonce,
            secret=TV_SECRET,
        )
        assert verify_request(ctx1) == VerifyResult.OK
        ts2 = str(int(time.time()))
        ctx2 = VerificationContext(
            body=body,
            signature_header=sign_canonical(ts2, nonce, body, TV_SECRET),
            timestamp_header=ts2,
            nonce_header=nonce,
            secret=TV_SECRET,
        )
        assert verify_request(ctx2) == VerifyResult.NONCE_REPLAY

    def test_captured_signature_cannot_be_replayed_with_fresh_headers(self):
        """Regression: audit found HMAC covered body only, so an attacker
        who captured one signed request could replay (body, signature)
        forever with fresh ts+nonce headers. Since the fix, signature is
        bound to the specific ts+nonce it was minted with."""
        nonce_store.clear()
        body = b'{"book":"iran-hormuz-graph","bindingId":"hormuz-reopen-announced"}'
        captured_ts = str(int(time.time()) - 120)
        captured_nonce = "captured-original-nonce"
        captured_sig = sign_canonical(captured_ts, captured_nonce, body, TV_SECRET)

        # Attacker swaps ts + nonce (both fresh, both pass their own checks)
        # but reuses the captured signature. Must fail at HMAC.
        fresh_ts = str(int(time.time()))
        fresh_nonce = "attacker-fresh-nonce"
        ctx = VerificationContext(
            body=body,
            signature_header=captured_sig,
            timestamp_header=fresh_ts,
            nonce_header=fresh_nonce,
            secret=TV_SECRET,
        )
        assert verify_request(ctx) == VerifyResult.BAD_SIGNATURE

    def test_canonical_signature_is_not_body_only(self):
        """Defense-in-depth: body-only signatures (pre-fix shape) must not
        accidentally pass verify_request. If this test ever flips to OK, the
        canonical wiring has been undone."""
        nonce_store.clear()
        body = b'{}'
        ts = str(int(time.time()))
        nonce = "twelve-char-nonce"
        # Old-style signature over body alone:
        body_only_sig = sign_body(body, TV_SECRET)
        ctx = VerificationContext(
            body=body,
            signature_header=body_only_sig,
            timestamp_header=ts,
            nonce_header=nonce,
            secret=TV_SECRET,
        )
        assert verify_request(ctx) == VerifyResult.BAD_SIGNATURE


# ═════════════════════════════════════════════════════════════════════════
# Webhook HTTP — authentication / validation failures
# ═════════════════════════════════════════════════════════════════════════

class TestWebhookAuth:
    def test_valid_signed_webhook_returns_200(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["nodeId"] == "brent"
        assert data["op"] == "incrementClosesObserved"
        assert data["newValue"] == 1

    def test_bad_signature_returns_401(self, temp_books):
        body = json.dumps({"book": "test-book", "bindingId": "x"}).encode()
        resp = client.post(
            "/api/tradingview/webhook",
            content=body,
            headers={
                "X-TV-Signature": "sha256=deadbeef",
                "X-TV-Timestamp": str(int(time.time())),
                "X-TV-Nonce": "nonce12345abc",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "bad_signature"

    def test_missing_signature_header_returns_401(self, temp_books):
        body = json.dumps({"book": "test-book", "bindingId": "x"}).encode()
        resp = client.post(
            "/api/tradingview/webhook",
            content=body,
            headers={
                "X-TV-Timestamp": str(int(time.time())),
                "X-TV-Nonce": "nonce12345abc",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_expired_timestamp_returns_410(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
        }, ts=int(time.time() - 9999))
        assert resp.status_code == 410

    def test_future_timestamp_returns_410(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
        }, ts=int(time.time() + 9999))
        assert resp.status_code == 410

    def test_non_numeric_timestamp_returns_410(self, temp_books):
        body = json.dumps({"book": "test-book", "bindingId": "x"}).encode()
        resp = client.post(
            "/api/tradingview/webhook",
            content=body,
            headers={
                "X-TV-Signature": sign_body(body, TV_SECRET),
                "X-TV-Timestamp": "not-a-number",
                "X-TV-Nonce": "nonce12345abc",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 410

    def test_missing_nonce_returns_400(self, temp_books):
        body = json.dumps({"book": "test-book", "bindingId": "x"}).encode()
        resp = client.post(
            "/api/tradingview/webhook",
            content=body,
            headers={
                "X-TV-Signature": sign_body(body, TV_SECRET),
                "X-TV-Timestamp": str(int(time.time())),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400

    def test_short_nonce_returns_400(self, temp_books):
        body = json.dumps({"book": "test-book", "bindingId": "x"}).encode()
        resp = client.post(
            "/api/tradingview/webhook",
            content=body,
            headers={
                "X-TV-Signature": sign_body(body, TV_SECRET),
                "X-TV-Timestamp": str(int(time.time())),
                "X-TV-Nonce": "short",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400

    def test_nonce_replay_returns_409(self, temp_books):
        # First POST succeeds
        resp1 = _post_webhook(
            {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
            nonce="replay-test-nonce",
        )
        assert resp1.status_code == 200
        # Second POST with the same nonce → 409
        resp2 = _post_webhook(
            {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
            nonce="replay-test-nonce",
        )
        assert resp2.status_code == 409

    def test_empty_body_returns_400(self, temp_books):
        resp = client.post(
            "/api/tradingview/webhook",
            content=b"",
            headers={
                "X-TV-Signature": "sha256=x",
                "X-TV-Timestamp": str(int(time.time())),
                "X-TV-Nonce": "nonce12345abc",
            },
        )
        assert resp.status_code == 400

    def test_body_too_large_returns_400(self, temp_books):
        # 9 KiB payload — over the 8 KiB cap
        huge = {"book": "test-book", "bindingId": "x", "pad": "x" * 9000}
        resp = _post_webhook(huge)
        assert resp.status_code == 400

    def test_malformed_json_returns_400(self, temp_books):
        body = b"not json at all"
        resp = client.post(
            "/api/tradingview/webhook",
            content=body,
            headers=_signed_webhook_headers(body),
        )
        assert resp.status_code == 400

    def test_no_secret_returns_500(self, temp_books):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TV_WEBHOOK_SECRET", None)
            resp = _post_webhook({
                "book": "test-book",
                "bindingId": "brent-persistence-close-above-115",
            })
        os.environ["TV_WEBHOOK_SECRET"] = TV_SECRET
        assert resp.status_code == 500

    def test_bad_book_regex_returns_400(self, temp_books):
        # Pydantic rejects via regex
        resp = _post_webhook({
            "book": "../etc/passwd",
            "bindingId": "brent-persistence-close-above-115",
        })
        assert resp.status_code == 400

    def test_bad_binding_id_regex_returns_400(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "../../../etc",
        })
        assert resp.status_code == 400

    def test_unknown_book_returns_404(self, temp_books):
        resp = _post_webhook({
            "book": "nonexistent-book",
            "bindingId": "brent-persistence-close-above-115",
        })
        assert resp.status_code == 404

    def test_unknown_binding_returns_404(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "no-such-binding-id",
        })
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════
# Webhook application — four ops + contract enforcement
# ═════════════════════════════════════════════════════════════════════════

class TestWebhookApply:
    def test_increment_closes_observed_inserts_table_row(self, temp_books, isolate_state):
        """Unit 11: incrementClosesObserved inserts into close_observations.

        WHY the book JSON is no longer mutated: closesObserved is a derived
        field computed from the SQLite streak. The webhook's job is to
        register the close event; the coordinator (and apply_webhook's local
        patch) projects it back onto the cfg before propagate.
        """
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
            "value": 116.5,  # above threshold 115
        })
        assert resp.status_code == 200
        repo = isolate_state
        # Streak is 1 after the first qualifying close.
        assert repo.get_close_streak(
            thesis_id="test-book", node_id="brent", threshold_key="115",
        ) == 1
        # The API echoes the streak as newValue.
        assert resp.json()["newValue"] == 1
        # Book JSON's closesObserved is NOT touched — no longer canonical.
        book = json.loads((temp_books / "test-book.json").read_text())
        brent = next(n for n in book["nodes"] if n["id"] == "brent")
        assert brent.get("closesObserved", 0) == 0

    def test_three_increments_promote_state_to_fired(self, temp_books, isolate_state):
        """Three qualifying closes (one per market date) take the streak to 3.

        The adapter uses today's date as market_date, which would dedup three
        same-day inserts down to 1. To simulate three distinct market dates
        we patch the adapter's date.today() for this test.
        """
        from unittest.mock import patch as mock_patch
        from datetime import date as real_date
        fake_dates = [
            real_date(2026, 4, 15), real_date(2026, 4, 16), real_date(2026, 4, 17),
        ]

        class _FakeDate(real_date):
            _seq = iter(fake_dates)

            @classmethod
            def today(cls) -> real_date:
                return next(cls._seq)

        with mock_patch("web.adapters.tradingview.date", _FakeDate):
            responses = []
            for i in range(3):
                r = _post_webhook(
                    {"book": "test-book",
                     "bindingId": "brent-persistence-close-above-115",
                     "value": 116.0 + i},
                    nonce=f"nonce-{i}-abc123",
                )
                assert r.status_code == 200
                responses.append(r)
        repo = isolate_state
        assert repo.get_close_streak(
            thesis_id="test-book", node_id="brent", threshold_key="115",
        ) == 3
        # Third response echoes the final streak count.
        assert responses[-1].json()["newValue"] == 3

    def test_set_node_state_on_event_node(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "hormuz-reopen-announced",
        })
        assert resp.status_code == 200
        assert resp.json()["newValue"] == "resolved"
        book = json.loads((temp_books / "test-book.json").read_text())
        hormuz = next(n for n in book["nodes"] if n["id"] == "hormuz")
        assert hormuz["state"] == "resolved"

    def test_set_probability_valid_value(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "hormuz-prob-bump",
            "value": 0.85,
        })
        assert resp.status_code == 200
        assert resp.json()["newValue"] == 0.85
        book = json.loads((temp_books / "test-book.json").read_text())
        hormuz = next(n for n in book["nodes"] if n["id"] == "hormuz")
        assert hormuz["probability"] == 0.85

    def test_set_probability_out_of_range_high(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "hormuz-prob-bump",
            "value": 1.5,
        })
        assert resp.status_code == 422

    def test_set_probability_out_of_range_low(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "hormuz-prob-bump",
            "value": -0.1,
        })
        assert resp.status_code == 422

    def test_set_probability_missing_value(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "hormuz-prob-bump",
            # no value
        })
        assert resp.status_code == 422

    def test_set_current_on_price_node(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "diesel-set",
            "value": 6.42,
        })
        assert resp.status_code == 200
        assert resp.json()["newValue"] == 6.42
        book = json.loads((temp_books / "test-book.json").read_text())
        diesel = next(n for n in book["nodes"] if n["id"] == "diesel")
        assert diesel["current"] == 6.42

    def test_set_current_missing_value(self, temp_books):
        resp = _post_webhook({
            "book": "test-book",
            "bindingId": "diesel-set",
        })
        assert resp.status_code == 422

    def test_binding_fire_count_increments(self, temp_books):
        _post_webhook(
            {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
            nonce="fc-nonce-1",
        )
        _post_webhook(
            {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
            nonce="fc-nonce-2",
        )
        book = json.loads((temp_books / "test-book.json").read_text())
        brent = next(n for n in book["nodes"] if n["id"] == "brent")
        binding = brent["tvAlertBindings"][0]
        assert binding["fireCount"] == 2
        assert binding["lastFiredAt"] is not None

    def test_audit_event_appended_on_success(self, temp_books, tmp_path):
        _post_webhook({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
        })
        repo = app.state.repo
        events = repo.list_tv_events()
        assert len(events) >= 1
        latest = events[0]
        assert latest["result"] == "ok"
        assert latest["bookId"] == "test-book"
        assert latest["nodeId"] == "brent"
        assert latest["op"] == "incrementClosesObserved"

    def test_audit_event_appended_on_auth_failure(self, temp_books):
        body = json.dumps({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
        }).encode()
        client.post(
            "/api/tradingview/webhook",
            content=body,
            headers={
                "X-TV-Signature": "sha256=deadbeef",
                "X-TV-Timestamp": str(int(time.time())),
                "X-TV-Nonce": "nonce12345abc",
                "Content-Type": "application/json",
            },
        )
        repo = app.state.repo
        events = repo.list_tv_events()
        assert any(e["result"] == "bad_signature" for e in events)

    def test_cache_invalidated_after_mutation(self, temp_books):
        # Warm the cache
        first = thesis_adapter.get_state("test-book")
        assert first is not None
        # Cache should be populated
        assert "test-book" in thesis_adapter._state_cache
        # Apply a mutation
        _post_webhook({
            "book": "test-book",
            "bindingId": "hormuz-reopen-announced",
        })
        # Cache should now be empty for this book
        assert "test-book" not in thesis_adapter._state_cache


# ═════════════════════════════════════════════════════════════════════════
# Adapter unit tests (without HTTP)
# ═════════════════════════════════════════════════════════════════════════

class TestAdapterUnits:
    def test_validate_book_id_rejects_traversal(self):
        with pytest.raises(ValueError):
            tv_adapter.validate_book_id("../etc/passwd")

    def test_validate_book_id_rejects_uppercase(self):
        with pytest.raises(ValueError):
            tv_adapter.validate_book_id("Foo-Bar")

    def test_validate_book_id_rejects_dot_file(self):
        with pytest.raises(ValueError):
            tv_adapter.validate_book_id(".hidden")

    def test_validate_book_id_accepts_kebab(self):
        tv_adapter.validate_book_id("iran-hormuz-graph")

    def test_resolve_book_path_stays_in_dir(self, temp_books):
        path = tv_adapter.resolve_book_path("test-book")
        assert str(path).endswith("test-book.json")
        assert tv_adapter.BOOKS_DIR in path.parents

    def test_find_binding_found(self, temp_books):
        cfg = tv_adapter.load_book("test-book")
        match = tv_adapter.find_binding(cfg, "hormuz-reopen-announced")
        assert match is not None
        assert match.node["id"] == "hormuz"
        assert match.binding["op"] == "setNodeState"

    def test_find_binding_missing(self, temp_books):
        cfg = tv_adapter.load_book("test-book")
        assert tv_adapter.find_binding(cfg, "does-not-exist") is None

    def test_apply_op_type_mismatch_raises(self, temp_books):
        # incrementClosesObserved on an event node is illegal
        cfg = tv_adapter.load_book("test-book")
        hormuz = next(n for n in cfg["nodes"] if n["id"] == "hormuz")
        bad_binding = {"op": "incrementClosesObserved"}
        with pytest.raises(tv_adapter.MutationError):
            tv_adapter.apply_op(hormuz, bad_binding, None)

    def test_apply_op_unknown_op_raises(self, temp_books):
        cfg = tv_adapter.load_book("test-book")
        brent = next(n for n in cfg["nodes"] if n["id"] == "brent")
        with pytest.raises(tv_adapter.MutationError):
            tv_adapter.apply_op(brent, {"op": "deleteEverything"}, None)

    def test_apply_op_bad_target_state_raises(self, temp_books):
        cfg = tv_adapter.load_book("test-book")
        hormuz = next(n for n in cfg["nodes"] if n["id"] == "hormuz")
        with pytest.raises(tv_adapter.MutationError):
            tv_adapter.apply_op(
                hormuz, {"op": "setNodeState", "targetState": "invalid"}, None,
            )

    def test_list_bindings_populated(self, temp_books):
        bindings = tv_adapter.list_bindings("test-book")
        assert len(bindings) == 4
        ids = {b["bindingId"] for b in bindings}
        assert "brent-persistence-close-above-115" in ids
        assert "hormuz-reopen-announced" in ids

    def test_create_binding_appends(self, temp_books):
        new_binding = {
            "bindingId": "brent-level-120",
            "nodeId": "brent",
            "op": "incrementClosesObserved",
            "thresholdLevel": 120,
            "description": "Next level up",
        }
        result = tv_adapter.create_binding("test-book", new_binding)
        assert result["bindingId"] == "brent-level-120"
        bindings = tv_adapter.list_bindings("test-book")
        assert any(b["bindingId"] == "brent-level-120" for b in bindings)

    def test_create_binding_duplicate_raises(self, temp_books):
        dup = {
            "bindingId": "brent-persistence-close-above-115",  # already exists
            "nodeId": "brent",
            "op": "incrementClosesObserved",
            "thresholdLevel": 120,
        }
        with pytest.raises(ValueError, match="already exists"):
            tv_adapter.create_binding("test-book", dup)

    def test_create_binding_unknown_node_raises(self, temp_books):
        b = {
            "bindingId": "new-one",
            "nodeId": "doesnt-exist",
            "op": "setCurrent",
        }
        with pytest.raises(LookupError):
            tv_adapter.create_binding("test-book", b)

    def test_create_binding_op_type_mismatch_raises(self, temp_books):
        b = {
            "bindingId": "wrong-op",
            "nodeId": "brent",  # price type
            "op": "setNodeState",  # only for events
            "targetState": "fired",
        }
        with pytest.raises(ValueError, match="not allowed on node type"):
            tv_adapter.create_binding("test-book", b)

    def test_delete_binding_removes(self, temp_books):
        assert tv_adapter.delete_binding(
            "test-book", "brent-persistence-close-above-115"
        ) is True
        bindings = tv_adapter.list_bindings("test-book")
        assert not any(
            b["bindingId"] == "brent-persistence-close-above-115" for b in bindings
        )

    def test_delete_binding_missing_returns_false(self, temp_books):
        assert tv_adapter.delete_binding("test-book", "no-such") is False

    def test_get_tv_indicators_empty_by_default(self, temp_books):
        assert tv_adapter.get_tv_indicators("test-book") == {}

    def test_get_tv_indicators_populated(self, temp_books):
        # Manually stuff tvIndicators into the book
        book_path = temp_books / "test-book.json"
        cfg = json.loads(book_path.read_text())
        brent = next(n for n in cfg["nodes"] if n["id"] == "brent")
        brent["tvIndicators"] = {"rsi14": 65.3, "atr14": 3.2, "source": "test"}
        book_path.write_text(json.dumps(cfg))
        result = tv_adapter.get_tv_indicators("test-book")
        assert "brent" in result
        assert result["brent"]["rsi14"] == 65.3


# ═════════════════════════════════════════════════════════════════════════
# Management routes — status / events / indicators
# ═════════════════════════════════════════════════════════════════════════

class TestManagementRoutes:
    def test_status_requires_jwt(self, temp_books):
        resp = client.get("/api/tradingview/status")
        assert resp.status_code == 401

    def test_status_returns_config(self, temp_books, auth_headers):
        resp = client.get("/api/tradingview/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["secretConfigured"] is True
        assert data["rateLimitPerMin"] >= 1
        assert "webhookUrl" in data

    def test_status_reflects_missing_secret(self, temp_books, auth_headers):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TV_WEBHOOK_SECRET", None)
            resp = client.get("/api/tradingview/status", headers=auth_headers)
        os.environ["TV_WEBHOOK_SECRET"] = TV_SECRET
        assert resp.status_code == 200
        assert resp.json()["secretConfigured"] is False

    def test_events_requires_jwt(self, temp_books):
        resp = client.get("/api/tradingview/events")
        assert resp.status_code == 401

    def test_events_empty(self, temp_books, auth_headers):
        resp = client.get("/api/tradingview/events", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_events_populated_after_webhook(self, temp_books, auth_headers):
        _post_webhook({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
        })
        resp = client.get("/api/tradingview/events", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["result"] == "ok"

    def test_events_filtered_by_book(self, temp_books, auth_headers):
        _post_webhook({
            "book": "test-book",
            "bindingId": "brent-persistence-close-above-115",
        })
        resp = client.get(
            "/api/tradingview/events/test-book", headers=auth_headers
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_events_limit_cap(self, temp_books, auth_headers):
        resp = client.get(
            "/api/tradingview/events?limit=99999", headers=auth_headers
        )
        assert resp.status_code == 200  # capped server-side to 500

    def test_events_invalid_book_id_rejected(self, temp_books, auth_headers):
        # Starlette normalises ../ in URLs, so an attacker can't reach the
        # handler via path traversal. Test the adapter-level rejection on a
        # book id with a character outside the regex alphabet.
        resp = client.get(
            "/api/tradingview/events/BAD-UPPERCASE", headers=auth_headers
        )
        assert resp.status_code == 400

    def test_indicators_empty(self, temp_books, auth_headers):
        resp = client.get(
            "/api/tradingview/indicators/test-book", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_indicators_populated(self, temp_books, auth_headers):
        # Stuff tvIndicators into the book
        book_path = temp_books / "test-book.json"
        cfg = json.loads(book_path.read_text())
        brent = next(n for n in cfg["nodes"] if n["id"] == "brent")
        brent["tvIndicators"] = {"rsi14": 64.3, "source": "derived_from_yahoo"}
        book_path.write_text(json.dumps(cfg))
        resp = client.get(
            "/api/tradingview/indicators/test-book", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "brent" in data
        assert data["brent"]["rsi14"] == 64.3

    def test_indicators_unknown_book_returns_404(self, temp_books, auth_headers):
        resp = client.get(
            "/api/tradingview/indicators/no-such-book", headers=auth_headers
        )
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════
# Binding CRUD routes
# ═════════════════════════════════════════════════════════════════════════

class TestBindingRoutes:
    def test_list_bindings_requires_jwt(self, temp_books):
        resp = client.get("/api/thesis/test-book/tv-bindings")
        assert resp.status_code == 401

    def test_list_bindings_returns_seed_data(self, temp_books, auth_headers):
        resp = client.get(
            "/api/thesis/test-book/tv-bindings", headers=auth_headers
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 4

    def test_list_bindings_unknown_book(self, temp_books, auth_headers):
        resp = client.get(
            "/api/thesis/no-such/tv-bindings", headers=auth_headers
        )
        assert resp.status_code == 404

    def test_create_binding_requires_jwt(self, temp_books):
        resp = client.post(
            "/api/thesis/test-book/tv-bindings",
            json={
                "bindingId": "new-one",
                "nodeId": "brent",
                "op": "incrementClosesObserved",
                "thresholdLevel": 120,
            },
        )
        assert resp.status_code == 401

    def test_create_binding_success(self, temp_books, auth_headers):
        resp = client.post(
            "/api/thesis/test-book/tv-bindings",
            headers=auth_headers,
            json={
                "bindingId": "brent-level-120",
                "nodeId": "brent",
                "op": "incrementClosesObserved",
                "thresholdLevel": 120,
                "description": "Higher level",
            },
        )
        assert resp.status_code == 200
        # List it back
        listing = client.get(
            "/api/thesis/test-book/tv-bindings", headers=auth_headers
        ).json()
        assert any(b["bindingId"] == "brent-level-120" for b in listing)

    def test_create_binding_duplicate_returns_422(self, temp_books, auth_headers):
        resp = client.post(
            "/api/thesis/test-book/tv-bindings",
            headers=auth_headers,
            json={
                "bindingId": "brent-persistence-close-above-115",
                "nodeId": "brent",
                "op": "incrementClosesObserved",
                "thresholdLevel": 115,
            },
        )
        assert resp.status_code == 422

    def test_create_binding_unknown_node_returns_404(self, temp_books, auth_headers):
        resp = client.post(
            "/api/thesis/test-book/tv-bindings",
            headers=auth_headers,
            json={
                "bindingId": "new-orphan",
                "nodeId": "ghost",
                "op": "setCurrent",
            },
        )
        assert resp.status_code == 404

    def test_create_binding_op_type_mismatch_returns_422(self, temp_books, auth_headers):
        resp = client.post(
            "/api/thesis/test-book/tv-bindings",
            headers=auth_headers,
            json={
                "bindingId": "bad-op",
                "nodeId": "brent",  # price
                "op": "setNodeState",  # event only
                "targetState": "fired",
            },
        )
        assert resp.status_code == 422

    def test_create_binding_bad_regex_returns_422(self, temp_books, auth_headers):
        resp = client.post(
            "/api/thesis/test-book/tv-bindings",
            headers=auth_headers,
            json={
                "bindingId": "UPPER-CASE-ID",  # fails regex ^[a-z0-9]...
                "nodeId": "brent",
                "op": "incrementClosesObserved",
                "thresholdLevel": 120,
            },
        )
        assert resp.status_code == 422

    def test_create_incrementcloses_without_threshold_returns_422(self, temp_books, auth_headers):
        resp = client.post(
            "/api/thesis/test-book/tv-bindings",
            headers=auth_headers,
            json={
                "bindingId": "brent-no-threshold",
                "nodeId": "brent",
                "op": "incrementClosesObserved",
                # no thresholdLevel
            },
        )
        assert resp.status_code == 422

    def test_delete_binding_requires_jwt(self, temp_books):
        resp = client.delete(
            "/api/thesis/test-book/tv-bindings/brent-persistence-close-above-115"
        )
        assert resp.status_code == 401

    def test_delete_binding_success(self, temp_books, auth_headers):
        resp = client.delete(
            "/api/thesis/test-book/tv-bindings/brent-persistence-close-above-115",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_binding_missing_returns_404(self, temp_books, auth_headers):
        resp = client.delete(
            "/api/thesis/test-book/tv-bindings/no-such", headers=auth_headers
        )
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════
# Rate limiting
# ═════════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    def test_burst_under_limit_all_succeed(self, temp_books):
        # Default rate limit is 1000/min for tests — easy to stay under
        for i in range(5):
            r = _post_webhook(
                {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
                nonce=f"rl-nonce-{i}",
            )
            assert r.status_code == 200

    def test_exceeding_limit_returns_429(self, temp_books):
        # Lower the cap for this test
        original = tv_routes.rate_limiter.per_minute
        tv_routes.rate_limiter.per_minute = 2
        try:
            ok1 = _post_webhook(
                {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
                nonce="rl-test-1",
            )
            ok2 = _post_webhook(
                {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
                nonce="rl-test-2",
            )
            blocked = _post_webhook(
                {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
                nonce="rl-test-3",
            )
            assert ok1.status_code == 200
            assert ok2.status_code == 200
            assert blocked.status_code == 429
        finally:
            tv_routes.rate_limiter.per_minute = original
            tv_routes.rate_limiter.reset()

    def test_rate_limit_resets_between_ips(self, temp_books):
        # Call reset directly to simulate new window
        tv_routes.rate_limiter.reset()
        # Now a single call should work regardless
        resp = _post_webhook(
            {"book": "test-book", "bindingId": "brent-persistence-close-above-115"},
            nonce="reset-test-nonce",
        )
        assert resp.status_code == 200
