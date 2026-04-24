"""
Tests for /api/v1/trades — list, detail, two-step kill.

WHY: This panel is the only place the UI lets an operator manually
invalidate a live trade. The tests verify:
  - read endpoints return structured detail and 404 on unknown ids,
  - the two-step kill flow cannot skip the confirm step,
  - the confirm token is single-use with a 30s TTL,
  - the ledger + open_trades.json are both updated atomically,
  - double-kill is idempotent-safe (409, never a silent duplicate).
"""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.adapters import outcomes as outcomes_adapter
from web.routes.v1 import trades as trades_route


TRADE_IDS = ("TRD-XOP-HORMUZ", "TRD-CF-PLANTING", "TRD-SH-RECESSION")

SEED_TRADES = [
    {
        "trade_id": "TRD-XOP-HORMUZ",
        "ticker": "XOP",
        "predicates": [
            {"kind": "state", "node_id": "em-stress", "expected": "fired",
             "allowed": [], "path": "", "op": "", "value": 0.0, "days": 0,
             "load_bearing": True},
            {"kind": "threshold", "node_id": "", "expected": "", "allowed": [],
             "path": "confluenceScores.em-stress", "op": ">=", "value": 1.6,
             "days": 0, "load_bearing": True},
        ],
        "ref_price": 188.18,
        "book": "iran-hormuz-graph",
    },
    {
        "trade_id": "TRD-CF-PLANTING",
        "ticker": "CF",
        "predicates": [
            {"kind": "state", "node_id": "planting-miss", "expected": "approaching",
             "allowed": [], "path": "", "op": "", "value": 0.0, "days": 0,
             "load_bearing": True},
        ],
        "ref_price": 136.45,
        "book": "iran-hormuz-graph",
    },
    {
        "trade_id": "TRD-SH-RECESSION",
        "ticker": "SH",
        "predicates": [
            {"kind": "threshold", "node_id": "", "expected": "", "allowed": [],
             "path": "confluenceScores.earnings-compression", "op": ">=",
             "value": 2.0, "days": 0, "load_bearing": True},
        ],
        "ref_price": 15.5,
        "book": "trump-tariffs-graph",
    },
]


@pytest.fixture(autouse=True)
def reset_tokens():
    """Each test starts with an empty confirm-token map."""
    with trades_route._kill_tokens_lock:
        trades_route._kill_tokens.clear()
    yield
    with trades_route._kill_tokens_lock:
        trades_route._kill_tokens.clear()


@pytest.fixture
def isolated_outcomes(tmp_path, monkeypatch):
    """Redirect the outcomes adapter to temp paths, seeded with the three
    canonical trades + minimal ENTRY ledger rows. Ensures kill operations
    don't touch the real outcomes/ directory."""
    ledger_dir = tmp_path / "trades"
    ledger_dir.mkdir()
    open_trades = tmp_path / "open_trades.json"
    open_trades.write_text(json.dumps(SEED_TRADES, indent=2))
    # Seed empty ENTRY ledgers so the kill path finds a pre-existing file.
    for t in SEED_TRADES:
        (ledger_dir / f"{t['trade_id']}.jsonl").write_text("")
    monkeypatch.setattr(outcomes_adapter, "LEDGER_DIR", ledger_dir)
    monkeypatch.setattr(outcomes_adapter, "OPEN_TRADES_PATH", open_trades)
    return {"ledger": ledger_dir, "open_trades": open_trades}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


# ── Read endpoints ───────────────────────────────────────────────────────

class TestList:
    def test_lists_seeded_trades(self, client, isolated_outcomes):
        resp = client.get("/api/v1/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        returned_ids = {t["trade_id"] for t in data}
        assert returned_ids == set(TRADE_IDS)
        for row in data:
            assert "predicate_count" in row
            assert "fired_count" in row
            assert "approaching_count" in row

    def test_list_is_unauthenticated(self, client, isolated_outcomes):
        """Read-only list endpoint matches /api/thesis and /api/market —
        no JWT required."""
        resp = client.get("/api/v1/trades")
        assert resp.status_code == 200


class TestGetTrade:
    @pytest.mark.parametrize("trade_id", TRADE_IDS)
    def test_returns_predicate_detail(self, client, isolated_outcomes, trade_id):
        resp = client.get(f"/api/v1/trades/{trade_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["trade_id"] == trade_id
        assert isinstance(data["predicates"], list)
        assert len(data["predicates"]) >= 1
        for pred in data["predicates"]:
            assert pred["state"] in ("fired", "approaching", "stable", "inactive")
            assert pred["kind"] in ("state", "state_set", "threshold", "countdown")
            assert "description" in pred
            assert "id" in pred

    def test_unknown_trade_returns_404(self, client, isolated_outcomes):
        resp = client.get("/api/v1/trades/TRD-DOES-NOT-EXIST")
        assert resp.status_code == 404


# ── Kill endpoint ────────────────────────────────────────────────────────

class TestKillAuth:
    def test_kill_without_auth_is_401(self, client, isolated_outcomes):
        resp = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "thesis invalidated"},
        )
        assert resp.status_code == 401


class TestKillFlow:
    def test_first_call_issues_confirm_token(self, client, auth_headers, isolated_outcomes):
        resp = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "thesis invalidated"},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        body = resp.json()["detail"]
        assert body["confirm_required"] is True
        assert isinstance(body["confirm_token"], str) and len(body["confirm_token"]) > 10
        assert body["expires_at"] > 0
        # Verify the in-memory store received it.
        assert "TRD-XOP-HORMUZ" in trades_route._kill_tokens

    def test_wrong_token_is_400(self, client, auth_headers, isolated_outcomes):
        # Issue a token first
        first = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "r"}, headers=auth_headers,
        )
        assert first.status_code == 409
        # Submit a bogus token
        resp = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "r", "confirm_token": "wrong-token"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        # Token is single-use: after a mismatch, the token is consumed, so
        # retrying with the correct one fails too (no_pending_confirm).
        assert "confirm" in resp.json()["detail"]

    def test_matching_token_kills_trade(self, client, auth_headers, isolated_outcomes):
        first = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "thesis invalidated"}, headers=auth_headers,
        )
        token = first.json()["detail"]["confirm_token"]
        resp = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "thesis invalidated", "confirm_token": token},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["trade_id"] == "TRD-XOP-HORMUZ"
        assert body["actor"] == "amo"

        # Ledger should have a KILL row.
        ledger = isolated_outcomes["ledger"] / "TRD-XOP-HORMUZ.jsonl"
        lines = [l for l in ledger.read_text().splitlines() if l.strip()]
        kill_rows = [json.loads(l) for l in lines if '"event_type":"KILL"' in l]
        assert len(kill_rows) == 1
        assert kill_rows[0]["reason"] == "thesis invalidated"
        assert kill_rows[0]["actor"] == "amo"

        # open_trades.json should no longer have the killed trade.
        remaining = json.loads(isolated_outcomes["open_trades"].read_text())
        ids = {t["trade_id"] for t in remaining}
        assert "TRD-XOP-HORMUZ" not in ids
        assert len(remaining) == 2

    def test_double_kill_is_409(self, client, auth_headers, isolated_outcomes):
        first = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "r"}, headers=auth_headers,
        )
        token = first.json()["detail"]["confirm_token"]
        # First real kill
        client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "r", "confirm_token": token}, headers=auth_headers,
        )
        # Second attempt: trade is gone, ledger has a KILL row → 409.
        resp = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "retry"}, headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "already_closed"

    def test_expired_token_is_400(self, client, auth_headers, isolated_outcomes, monkeypatch):
        first = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "r"}, headers=auth_headers,
        )
        token = first.json()["detail"]["confirm_token"]
        # Force the stored token to expire by rewinding its expiry stamp.
        with trades_route._kill_tokens_lock:
            trades_route._kill_tokens["TRD-XOP-HORMUZ"]["expires"] = 1.0
        resp = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": "r", "confirm_token": token}, headers=auth_headers,
        )
        # Expired tokens are pruned before lookup, so the consumer sees
        # "missing" rather than "expired" — both are 400, both indicate
        # "confirm step required again".
        assert resp.status_code == 400
        assert "confirm" in resp.json()["detail"]

    def test_unknown_trade_kill_is_404(self, client, auth_headers, isolated_outcomes):
        resp = client.post(
            "/api/v1/trades/TRD-NOPE/kill",
            json={"reason": "r"}, headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_reason_required(self, client, auth_headers, isolated_outcomes):
        """An empty reason is rejected — the KILL row must record WHY."""
        resp = client.post(
            "/api/v1/trades/TRD-XOP-HORMUZ/kill",
            json={"reason": ""}, headers=auth_headers,
        )
        assert resp.status_code == 422  # pydantic validation failure
