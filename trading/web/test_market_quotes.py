"""Regression tests for web/adapters/market.py fetch_quotes.

WHY this file exists: /api/market/quotes had NEVER returned a quote —
fetch_prices returns the mutated cfg (not a {symbol: price} dict), and the
old adapter iterated the cfg's top-level keys. Found by the Dialectic
tool-loop build (2026-08-09) tracing values, then latency-measured at 18.5s
per call on the healthy path. These tests pin the extraction and the cache.
"""

import pytest

from web.adapters import market


@pytest.fixture(autouse=True)
def clear_cache():
    market._QUOTES_CACHE["at"] = 0.0
    market._QUOTES_CACHE["data"] = None
    yield
    market._QUOTES_CACHE["at"] = 0.0
    market._QUOTES_CACHE["data"] = None


def _mutated_cfg():
    """A cfg AS thesisgraph.fetch_prices leaves it: prices written into
    node['current'] (yahoo-feed nodes) and inst['ref'] (instruments)."""
    return {
        "meta": {"id": "test-graph"},
        "nodes": [
            {"id": "brent", "current": 99.78,
             "feeds": [{"source": "yahoo", "symbol": "BZ=F"}]},
            {"id": "polymarket-node", "current": 0.26,
             "feeds": [{"source": "polymarket", "slug": "x"}]},
            {"id": "no-price", "current": None,
             "feeds": [{"source": "yahoo", "symbol": "DEAD"}]},
        ],
        "edges": [],
        "instruments": {
            "brent": [{"id": "XOP", "role": "primary", "ref": 141.2}],
            "other": [{"id": "NOREF", "role": "x"}],
        },
    }


class TestExtraction:
    def test_extracts_node_and_instrument_prices(self):
        quotes = market._extract_quotes_from_cfg(_mutated_cfg())
        by_symbol = {q["symbol"]: q["price"] for q in quotes}
        assert by_symbol["BZ=F"] == 99.78
        assert by_symbol["XOP"] == 141.2

    def test_ignores_non_yahoo_feeds_and_missing_prices(self):
        quotes = market._extract_quotes_from_cfg(_mutated_cfg())
        symbols = {q["symbol"] for q in quotes}
        assert "DEAD" not in symbols       # current is None
        assert "NOREF" not in symbols      # no ref written
        assert "x" not in symbols          # polymarket feed is not a quote

    def test_top_level_cfg_keys_are_not_quotes(self):
        """The original bug shape: cfg keys must never be emitted as symbols."""
        quotes = market._extract_quotes_from_cfg(_mutated_cfg())
        symbols = {q["symbol"] for q in quotes}
        assert not symbols & {"meta", "nodes", "edges", "instruments"}


class TestFetchQuotes:
    def test_returns_extracted_quotes(self, monkeypatch):
        monkeypatch.setattr(
            market, "_collect_symbols_from_books", lambda: ({"BZ=F"}, [])
        )
        cfg = _mutated_cfg()
        monkeypatch.setattr(market.thesisgraph, "load_config", lambda p: cfg)
        monkeypatch.setattr(market.thesisgraph, "fetch_prices", lambda c: c)
        # one book only
        monkeypatch.setattr(
            market, "BOOKS_DIR", type(market.BOOKS_DIR)(str(market.BOOKS_DIR))
        )
        quotes = market.fetch_quotes(force_refresh=True)
        prices = {q["symbol"]: q["price"] for q in quotes}
        assert prices.get("BZ=F") == 99.78

    def test_cache_serves_warm_calls_without_refetch(self, monkeypatch):
        calls = {"n": 0}

        def fake_fetch(cfg):
            calls["n"] += 1
            return cfg

        monkeypatch.setattr(
            market, "_collect_symbols_from_books", lambda: ({"BZ=F"}, [])
        )
        monkeypatch.setattr(market.thesisgraph, "load_config",
                            lambda p: _mutated_cfg())
        monkeypatch.setattr(market.thesisgraph, "fetch_prices", fake_fetch)

        first = market.fetch_quotes()
        n_after_first = calls["n"]
        second = market.fetch_quotes()
        assert n_after_first > 0
        assert calls["n"] == n_after_first  # no new fetches on the warm call
        assert second == first

    def test_empty_results_are_not_cached(self, monkeypatch):
        """A failed fetch must not poison the cache with []."""
        monkeypatch.setattr(
            market, "_collect_symbols_from_books", lambda: ({"BZ=F"}, [])
        )
        monkeypatch.setattr(market.thesisgraph, "load_config",
                            lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        assert market.fetch_quotes() == []
        assert market._QUOTES_CACHE["data"] is None


class TestPolymarketCollection:
    def test_market_is_canonical_and_slug_is_legacy(self):
        cfg = {"nodes": [{"feeds": [
            {"source": "polymarket", "market": "canonical", "slug": "legacy"},
            {"source": "polymarket", "slug": "legacy-only"},
            {"source": "polymarket", "market": "canonical"},
            {"source": "yahoo", "symbol": "SPY"},
        ]}]}

        assert market.polymarket_markets_from_book(cfg) == [
            "canonical", "legacy-only",
        ]

    def test_checked_in_books_expose_four_markets(self):
        _symbols, market_ids = market._collect_symbols_from_books()

        assert market_ids == [
            "us-iran-april-30",
            "us-tariff-rate-china-march-31",
            "trump-visit-china-by-june-30",
            "us-recession-by-end-of-2026",
        ]

    def test_fetch_omits_markets_without_a_probability(self, monkeypatch):
        seen = {}

        def fetch(market_ids, **kwargs):
            seen.update(kwargs)
            return {market_ids[0]: 0.42, market_ids[1]: None}

        monkeypatch.setattr(
            market.polymarket_mod,
            "fetch_markets",
            fetch,
        )

        assert market.fetch_polymarket_probs(["priced", "missing"]) == [
            {"slug": "priced", "probability": 0.42},
        ]
        assert seen == {
            "timeout": 5,
            "retries": 2,
            "raise_on_error": True,
            "parallel": True,
        }

    def test_fetch_failure_is_not_an_empty_success(self, monkeypatch):
        def fail(_market_ids, **_kwargs):
            raise RuntimeError("upstream broke")

        monkeypatch.setattr(market.polymarket_mod, "fetch_markets", fail)

        with pytest.raises(RuntimeError, match="upstream broke"):
            market.fetch_polymarket_probs(["configured"])

    def test_global_fetch_preserves_null_membership_and_client_defaults(
        self, monkeypatch,
    ):
        seen = {}

        def fetch(market_ids, **kwargs):
            seen["market_ids"] = market_ids
            seen["kwargs"] = kwargs
            return {"priced": 0.42, "missing": None}

        monkeypatch.setattr(
            market, "_collect_symbols_from_books",
            lambda: (set(), ["priced", "missing"]),
        )
        monkeypatch.setattr(market.polymarket_mod, "fetch_markets", fetch)

        assert market.fetch_polymarket_probs() == [
            {"slug": "priced", "probability": 0.42},
            {"slug": "missing", "probability": None},
        ]
        assert seen == {
            "market_ids": ["priced", "missing"],
            "kwargs": {},
        }
