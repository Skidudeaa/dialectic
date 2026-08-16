"""Regression tests for Polymarket market-id resolution in web/adapters/market.py.

WHY this file exists: /api/market/polymarket had NEVER contacted Polymarket.
Both read sites in the adapter took `feed["slug"]`, while every book on disk
authors `feed["market"]` and none writes `slug` — so `_collect_symbols_from_books`
returned an empty list, `fetch_polymarket_probs` short-circuited on
`if not poly_markets`, and the endpoint answered `[]` forever. Downstream that
reached the room as "Polymarket is empty", an operational failure reported as a
fact about the world.

The project's own validator (tools/thesis_graph/thesisgraph.py:158) had accepted
`slug or market` all along, so the adapter was the piece out of step, not the
books.

The REAL-CORPUS test below is the one that matters. Every hand-written fixture
in this file would have passed against the old code if it had used `slug`; only
reading the actual books/ directory shows the mismatch, because the defect was a
disagreement between two files about a key name, not a logic error inside either.
"""

import json
from pathlib import Path

import pytest

from web.adapters import market


# ── the helper ────────────────────────────────────────────────────────────

def test_market_key_is_read():
    assert market._polymarket_feed_id({"market": "us-iran-april-30"}) == "us-iran-april-30"


def test_legacy_slug_key_still_works():
    """Nothing on disk uses it, but the validator accepts it, so we do too."""
    assert market._polymarket_feed_id({"slug": "legacy-market"}) == "legacy-market"


def test_market_wins_a_conflict():
    """Design §3.1: `market` is what current books author and the engine reads."""
    assert market._polymarket_feed_id(
        {"market": "authored", "slug": "stale"}
    ) == "authored"


@pytest.mark.parametrize("feed", [
    {},
    {"market": ""},
    {"slug": ""},
    {"market": "   "},
    {"market": None},
    {"market": 42},
])
def test_empty_and_malformed_values_are_ignored(feed):
    assert market._polymarket_feed_id(feed) == ""


def test_a_blank_market_falls_through_to_slug():
    """'Empty values are ignored' has to mean ignored, not 'wins and blanks'."""
    assert market._polymarket_feed_id({"market": "  ", "slug": "real"}) == "real"


# ── the real corpus ───────────────────────────────────────────────────────

def _books_with_polymarket_feeds():
    found = {}
    for path in sorted(market.BOOKS_DIR.glob("*-graph.json")):
        ids = []
        cfg = json.loads(path.read_text())
        for node in cfg.get("nodes", []):
            for feed in node.get("feeds", []):
                if feed.get("source") == "polymarket":
                    ids.append(market._polymarket_feed_id(feed))
        if ids:
            found[path.name] = ids
    return found


def test_the_shipped_books_declare_polymarket_feeds():
    """Guards the premise. If this goes empty the test below is vacuous."""
    books = _books_with_polymarket_feeds()
    assert books, "no book declares a polymarket feed — the corpus test is blind"
    assert all(all(i for i in ids) for ids in books.values()), books


def test_collector_finds_the_real_books_markets():
    """THE regression: this returned [] against the shipped corpus.

    Not mocked on purpose — the defect was the adapter and the books
    disagreeing about a key name, which no fixture of my own authorship can
    reproduce honestly.
    """
    _, poly_markets = market._collect_symbols_from_books()

    expected = {i for ids in _books_with_polymarket_feeds().values() for i in ids}
    assert poly_markets, "collector found zero markets against the real books"
    assert set(poly_markets) == expected
    # Ordered, de-duplicated, no blanks.
    assert len(poly_markets) == len(set(poly_markets))
    assert all(poly_markets)


def test_watchlist_carries_the_markets_too():
    """The second read site, which drifted the same way and independently."""
    symbols = {i["symbol"] for i in market.get_watchlist() if i["source"] == "polymarket"}
    expected = {i for ids in _books_with_polymarket_feeds().values() for i in ids}
    assert symbols == expected


# ── failure is no longer laundered into an empty list ─────────────────────

def test_upstream_failure_raises_instead_of_returning_empty(monkeypatch):
    """Design §3.1: a real fetch failure must reach FastAPI as an error.

    Returning [] here is what made "Polymarket is down" and "no markets are
    configured" the same observable, which is the whole complaint.
    """
    def boom(_markets):
        raise RuntimeError("gamma-api unreachable")

    monkeypatch.setattr(market.polymarket_mod, "fetch_markets", boom)
    with pytest.raises(RuntimeError):
        market.fetch_polymarket_probs()


def test_no_configured_markets_is_still_an_honest_empty(monkeypatch):
    """The one empty that IS a fact about the world, not about the fetch."""
    monkeypatch.setattr(market, "_collect_symbols_from_books", lambda: (set(), []))

    def never(_markets):  # pragma: no cover - must not be reached
        raise AssertionError("must not contact Polymarket with nothing configured")

    monkeypatch.setattr(market.polymarket_mod, "fetch_markets", never)
    assert market.fetch_polymarket_probs() == []


def test_probabilities_pass_through_on_the_slug_wire_key(monkeypatch):
    """Only the BOOK-side key was ambiguous; the response contract is unchanged."""
    monkeypatch.setattr(
        market, "_collect_symbols_from_books", lambda: (set(), ["us-iran-april-30"])
    )
    monkeypatch.setattr(
        market.polymarket_mod, "fetch_markets", lambda ids: {"us-iran-april-30": 0.42}
    )
    assert market.fetch_polymarket_probs() == [
        {"slug": "us-iran-april-30", "probability": 0.42}
    ]
