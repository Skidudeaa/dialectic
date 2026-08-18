"""
Paper portfolio route tests — the fill door and the valuation read.

WHY every price here is stubbed: the route's contract is that td computes
quantity from ITS quote feed and values positions off the same feed with a
documented fallback chain. All of that is arithmetic over fetch_quotes /
equity_marks output, so the tests pin the arithmetic with hand-computed
numbers and never touch Yahoo.
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-ci")
os.environ.setdefault("DEV_USER_PASSWORD", "testpass")

from web.main import app
from web.auth import create_access_token
from web.deps import get_repo
from web.persistence.repository import Repository
import web.adapters.market as market

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_state():
    """Fresh in-memory SQLite per test via dependency override."""
    repo = Repository(":memory:")
    repo.initialize()
    app.dependency_overrides[get_repo] = lambda: repo
    app.state.repo = repo
    yield repo
    app.dependency_overrides.pop(get_repo, None)


@pytest.fixture
def auth_headers():
    token = create_access_token("amo", "Amo")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def quotes(monkeypatch):
    """Stub the desk quote feed; tests mutate the dict to move prices."""
    table = {"XOP": 100.0, "SPY": 500.0}
    monkeypatch.setattr(
        market, "fetch_quotes",
        lambda force_refresh=False: [
            {"symbol": s, "price": p, "source": "yahoo"}
            for s, p in table.items()
        ],
    )
    return table


def seed_dated_deposit(repo, created_at, dollars, book="iran-hormuz-graph"):
    """Insert a deposit fill with a controlled created_at.

    WHY raw SQL: record_fill_once stamps created_at with now, so there is no
    supported way to build a fixture spanning days — and the benchmark's
    flow-windowing rule is defined in terms of that column (same rationale
    as test_maintenance.seed_snapshots)."""
    import uuid
    conn = repo._conn()
    try:
        conn.execute(
            """INSERT INTO paper_fills
               (id, book_id, user, kind, symbol, side, quantity, price,
                rationale, created_at)
               VALUES (?, ?, 'amo', 'deposit', 'CASH', 'buy', ?, 1.0, '', ?)""",
            (str(uuid.uuid4()), book, dollars, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def deposit(headers, book="iran-hormuz-graph", dollars=10_000.0, **extra):
    body = {"book_id": book, "kind": "deposit", "dollars": dollars}
    body.update(extra)
    return client.post("/api/portfolio/fills", json=body, headers=headers)


def trade(headers, book="iran-hormuz-graph", symbol="XOP", side="buy",
          dollars=2_000.0, **extra):
    body = {"book_id": book, "kind": "trade", "symbol": symbol,
            "side": side, "dollars": dollars}
    body.update(extra)
    return client.post("/api/portfolio/fills", json=body, headers=headers)


class TestAuth:
    def test_fills_requires_auth(self):
        assert client.post("/api/portfolio/fills", json={}).status_code in (401, 403)

    def test_portfolio_requires_auth(self):
        assert client.get("/api/portfolio").status_code in (401, 403)


class TestCreateFill:
    def test_deposit_seeds_cash_at_par(self, auth_headers, quotes):
        resp = deposit(auth_headers, dollars=2_500.0)
        assert resp.status_code == 200
        fill = resp.json()
        assert fill["kind"] == "deposit"
        assert fill["symbol"] == "CASH"
        assert fill["quantity"] == 2_500.0
        assert fill["price"] == 1.0
        assert fill["user"] == "amo"

    def test_deposit_never_422s_on_an_empty_quote_feed(self, auth_headers,
                                                       monkeypatch):
        monkeypatch.setattr(market, "fetch_quotes",
                            lambda force_refresh=False: [])
        assert deposit(auth_headers).status_code == 200

    def test_trade_quantity_is_dollars_over_live_quote(self, auth_headers, quotes):
        quotes["XOP"] = 25.0
        resp = trade(auth_headers, dollars=100.0)
        assert resp.status_code == 200
        fill = resp.json()
        assert fill["quantity"] == 4.0  # 100 / 25
        assert fill["price"] == 25.0    # the desk's price, not the client's

    def test_unquoted_trade_symbol_is_422(self, auth_headers, quotes):
        resp = trade(auth_headers, symbol="NOPE")
        assert resp.status_code == 422
        assert "NOPE" in resp.json()["detail"]

    def test_trading_the_cash_sentinel_is_422(self, auth_headers, quotes):
        assert trade(auth_headers, symbol="CASH").status_code == 422

    def test_non_positive_dollars_is_422(self, auth_headers, quotes):
        assert trade(auth_headers, dollars=0).status_code == 422
        assert deposit(auth_headers, dollars=-50).status_code == 422

    def test_sell_past_flat_is_422_long_only(self, auth_headers, quotes):
        deposit(auth_headers, dollars=10_000)
        trade(auth_headers, dollars=2_000)                    # 20 XOP @ 100
        resp = trade(auth_headers, side="sell", dollars=2_500)  # 25 > 20 held
        assert resp.status_code == 422
        assert "long-only" in resp.json()["detail"]

    def test_sell_with_no_position_is_422(self, auth_headers, quotes):
        deposit(auth_headers, dollars=10_000)
        resp = trade(auth_headers, side="sell", dollars=100)
        assert resp.status_code == 422

    def test_exact_flat_sell_is_allowed(self, auth_headers, quotes):
        deposit(auth_headers, dollars=10_000)
        trade(auth_headers, dollars=2_000)                    # 20 XOP @ 100
        quotes["XOP"] = 110.0
        resp = trade(auth_headers, side="sell", dollars=2_200)  # exactly 20
        assert resp.status_code == 200
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        assert book["positions"] == []
        assert book["cash"] == 10_000 - 2_000 + 2_200

    def test_source_key_replay_returns_the_same_fill(self, auth_headers, quotes):
        first = trade(auth_headers, source_key="trade:m1:trade_proposal").json()
        second = trade(auth_headers, source_key="trade:m1:trade_proposal").json()
        assert second["id"] == first["id"]
        assert "source_key" not in first  # internal coordinate stays internal

    def test_provenance_rides_the_fill(self, auth_headers, quotes):
        fill = trade(auth_headers, rationale="hormuz risk",
                     node_id="brent", prediction_id="pred-1").json()
        assert fill["rationale"] == "hormuz risk"
        assert fill["node_id"] == "brent"
        assert fill["prediction_id"] == "pred-1"


class TestGetPortfolio:
    def test_empty_book_map(self, auth_headers, quotes):
        resp = client.get("/api/portfolio", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"books": {}}

    def test_valuation_off_the_live_quote(self, auth_headers, quotes):
        deposit(auth_headers, dollars=10_000)
        trade(auth_headers, dollars=2_000)          # 20 XOP @ 100
        quotes["XOP"] = 110.0                       # then the market moves
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        assert book["cash"] == 8_000.0
        [pos] = book["positions"]
        assert pos == {"symbol": "XOP", "qty": 20.0, "avg_cost": 100.0,
                       "price": 110.0, "value": 2_200.0, "unrealized": 200.0}
        assert book["equity"] == 10_200.0
        assert book["inception"] is not None

    def test_missing_quote_falls_back_to_latest_mark_close(
            self, auth_headers, quotes, isolate_state):
        deposit(auth_headers, dollars=10_000)
        trade(auth_headers, dollars=2_000)          # 20 XOP @ 100
        del quotes["XOP"]                           # feed loses the symbol
        isolate_state.save_equity_mark(
            "iran-hormuz-graph", "2026-08-01", equity=10_800, cash=8_000,
            spy_close=500.0, positions={"XOP": {"qty": 20.0, "close": 140.0}},
        )
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        [pos] = book["positions"]
        assert pos["price"] == 140.0                # ponytail fallback
        assert book["equity"] == 8_000 + 20 * 140.0

    def test_no_quote_and_no_marks_marks_at_cost(self, auth_headers, quotes):
        deposit(auth_headers, dollars=10_000)
        trade(auth_headers, dollars=2_000)
        del quotes["XOP"]
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        [pos] = book["positions"]
        assert pos["price"] == 100.0
        assert pos["unrealized"] == 0.0
        assert book["equity"] == 10_000.0

    def test_spy_baseline_is_unitized_across_multiple_deposits(
            self, auth_headers, quotes, isolate_state):
        """Two-deposit fixture, hand-computed:
          10,000 before mark1 (SPY 500)  -> 20 units, value 10,000
          +5,500 in (mark1, mark2] (550) -> +10 units = 30, value 16,500
          mark3 (495)                    -> 30 x 495 = 14,850
        The naive single-deposit formula (10,000 x 550/500) would say
        11,000 at mark2 — the unitized series must diverge from it."""
        seed_dated_deposit(isolate_state, "2026-07-30T12:00:00+00:00", 10_000)
        seed_dated_deposit(isolate_state, "2026-08-02T05:00:00+00:00", 5_500)
        for date, spy in [("2026-08-01", 500.0), ("2026-08-02", 550.0),
                          ("2026-08-03", 495.0)]:
            isolate_state.save_equity_mark(
                "iran-hormuz-graph", date, equity=15_500, cash=15_500,
                spy_close=spy,
            )
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        assert book["spy_baseline"] == [
            {"mark_date": "2026-08-01", "value": 10_000.0},
            {"mark_date": "2026-08-02", "value": 16_500.0},
            {"mark_date": "2026-08-03", "value": 14_850.0},
        ]
        assert book["price_return_only"] is True
        # Intraday: 30 units x live SPY quote (500 in the fixture).
        assert book["spy_baseline_now"] == 15_000.0
        assert book["flows"] == [
            {"date": "2026-07-30", "amount": 10_000.0},
            {"date": "2026-08-02", "amount": 5_500.0},
        ]

    def test_benchmark_now_falls_back_to_last_mark_without_a_spy_quote(
            self, auth_headers, quotes, isolate_state):
        del quotes["SPY"]
        seed_dated_deposit(isolate_state, "2026-07-30T12:00:00+00:00", 10_000)
        isolate_state.save_equity_mark(
            "iran-hormuz-graph", "2026-08-01", equity=10_000, cash=10_000,
            spy_close=500.0,
        )
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        assert book["spy_baseline_now"] == 10_000.0  # last mark's value

    def test_deposit_after_the_last_mark_waits_for_the_next_mark(
            self, auth_headers, quotes, isolate_state):
        """The documented one-day fuzz: a deposit unitizes at the NEXT
        mark's close, so one landing after the last mark is in flows but
        not yet in the benchmark."""
        seed_dated_deposit(isolate_state, "2026-07-30T12:00:00+00:00", 10_000)
        seed_dated_deposit(isolate_state, "2026-08-05T12:00:00+00:00", 5_000)
        isolate_state.save_equity_mark(
            "iran-hormuz-graph", "2026-08-01", equity=10_000, cash=10_000,
            spy_close=500.0,
        )
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        assert book["spy_baseline"] == [
            {"mark_date": "2026-08-01", "value": 10_000.0},
        ]
        assert book["spy_baseline_now"] == 10_000.0  # 20 units x SPY 500
        assert len(book["flows"]) == 2

    def test_no_marks_means_empty_series_not_a_crash(self, auth_headers, quotes):
        deposit(auth_headers, dollars=1_000)
        book = client.get("/api/portfolio", headers=auth_headers).json()[
            "books"]["iran-hormuz-graph"]
        assert book["marks"] == []
        assert book["spy_baseline"] == []
        assert book["spy_baseline_now"] is None
        assert book["price_return_only"] is True
        [flow] = book["flows"]
        assert flow["amount"] == 1_000.0

    def test_books_are_reported_independently(self, auth_headers, quotes):
        deposit(auth_headers, book="book-a", dollars=100)
        deposit(auth_headers, book="book-b", dollars=900)
        books = client.get("/api/portfolio", headers=auth_headers).json()["books"]
        assert books["book-a"]["equity"] == 100.0
        assert books["book-b"]["equity"] == 900.0
