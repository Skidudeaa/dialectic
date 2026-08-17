#!/usr/bin/env python3
"""
Tests for Polymarket prediction market fetcher.

Runs with: python3 -m pytest tools/data_fetch/test_polymarket.py -q

WHY mock HTTP: these tests must work offline and deterministically.
All HTTP calls are mocked at the _make_request boundary so we test
parsing, matching, and error handling without hitting the real API.
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock
from urllib.error import URLError

import pytest

# Add parent dir to path so we can import the module
sys.path.insert(0, os.path.dirname(__file__))
from polymarket import (
    _parse_outcome_prices,
    _extract_probability_from_market,
    _match_market_in_results,
    _search_events,
    _search_markets,
    fetch_single_market,
    fetch_markets,
    PolymarketError,
    MarketNotFoundError,
    APIError,
    GAMMA_API_BASE,
)


# =========================================================================
# FIXTURES — reusable API response shapes
# =========================================================================

def make_market(**overrides) -> dict:
    """Build a realistic Polymarket market object.

    WHY: Polymarket's actual API response shape. Having a builder
    ensures tests stay in sync with the real format.
    """
    base = {
        "id": "12345",
        "question": "Will the US and Iran reach a deal by April 30?",
        "slug": "us-iran-april-30",
        "active": True,
        "closed": False,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.685", "0.315"]',
        "volume": "1234567.89",
        "liquidity": "56789.01",
    }
    base.update(overrides)
    return base


def make_event(**overrides) -> dict:
    """Build a realistic Polymarket event object containing markets."""
    base = {
        "id": "evt-001",
        "slug": "us-iran-conflict",
        "title": "US-Iran Conflict",
        "markets": [make_market()],
    }
    base.update(overrides)
    return base


# =========================================================================
# Tests: _parse_outcome_prices
# =========================================================================

class TestParseOutcomePrices:
    """Test extraction of Yes probability from raw outcome data."""

    def test_standard_yes_no(self):
        """Standard binary market: Yes/No with JSON string prices."""
        result = _parse_outcome_prices('["0.685", "0.315"]', ["Yes", "No"])
        assert result == pytest.approx(0.685)

    def test_reversed_order(self):
        """Yes isn't always first — must match by label, not position."""
        result = _parse_outcome_prices('["0.315", "0.685"]', ["No", "Yes"])
        assert result == pytest.approx(0.685)

    def test_pre_parsed_list(self):
        """Outcome prices already parsed as a list (not JSON string)."""
        result = _parse_outcome_prices(["0.45", "0.55"], ["Yes", "No"])
        assert result == pytest.approx(0.45)

    def test_case_insensitive(self):
        """Outcome labels may vary in casing."""
        result = _parse_outcome_prices('["0.72", "0.28"]', ["YES", "NO"])
        assert result == pytest.approx(0.72)

    def test_malformed_json(self):
        """Gracefully handle corrupt JSON in outcomePrices."""
        result = _parse_outcome_prices("not-json", ["Yes", "No"])
        assert result is None

    def test_empty_prices(self):
        """Empty prices array means no data."""
        result = _parse_outcome_prices("[]", ["Yes", "No"])
        assert result is None

    def test_none_prices(self):
        """None prices input."""
        result = _parse_outcome_prices(None, ["Yes", "No"])
        assert result is None

    def test_none_outcomes(self):
        """None outcomes input."""
        result = _parse_outcome_prices('["0.5", "0.5"]', None)
        assert result is None

    def test_no_yes_outcome(self):
        """Market with non-standard outcome labels (no 'Yes')."""
        result = _parse_outcome_prices('["0.6", "0.4"]', ["Trump", "Biden"])
        assert result is None

    def test_out_of_bounds_high(self):
        """Probability > 1.0 is invalid — reject it."""
        result = _parse_outcome_prices('["1.5", "-0.5"]', ["Yes", "No"])
        assert result is None

    def test_out_of_bounds_low(self):
        """Negative probability is invalid."""
        result = _parse_outcome_prices('["-0.1", "1.1"]', ["Yes", "No"])
        assert result is None

    def test_boundary_zero(self):
        """Probability of exactly 0.0 is valid (resolved No)."""
        result = _parse_outcome_prices('["0.0", "1.0"]', ["Yes", "No"])
        assert result == pytest.approx(0.0)

    def test_boundary_one(self):
        """Probability of exactly 1.0 is valid (resolved Yes)."""
        result = _parse_outcome_prices('["1.0", "0.0"]', ["Yes", "No"])
        assert result == pytest.approx(1.0)

    def test_mismatched_lengths(self):
        """More outcomes than prices — index out of range safety."""
        result = _parse_outcome_prices('["0.5"]', ["Yes", "No", "Maybe"])
        assert result == pytest.approx(0.5)

    def test_non_numeric_price(self):
        """Price string that can't be parsed as float."""
        result = _parse_outcome_prices('["abc", "0.5"]', ["Yes", "No"])
        assert result is None


# =========================================================================
# Tests: _extract_probability_from_market
# =========================================================================

class TestExtractProbability:
    """Test probability extraction from full market objects."""

    def test_standard_market(self):
        """Normal market object with outcomePrices + outcomes."""
        market = make_market()
        prob = _extract_probability_from_market(market)
        assert prob == pytest.approx(0.685)

    def test_pre_parsed_outcomes(self):
        """Outcomes field already a list (not JSON string)."""
        market = make_market(outcomes=["Yes", "No"])
        prob = _extract_probability_from_market(market)
        assert prob == pytest.approx(0.685)

    def test_fallback_to_best_bid(self):
        """When outcomePrices is missing, fall back to bestBid."""
        market = make_market(outcomePrices=None, outcomes=None, bestBid=0.72)
        prob = _extract_probability_from_market(market)
        assert prob == pytest.approx(0.72)

    def test_fallback_to_last_trade_price(self):
        """Fall back to lastTradePrice when others are missing."""
        market = make_market(
            outcomePrices=None, outcomes=None, lastTradePrice="0.55"
        )
        prob = _extract_probability_from_market(market)
        assert prob == pytest.approx(0.55)

    def test_empty_market_object(self):
        """Completely empty market — should return None gracefully."""
        prob = _extract_probability_from_market({})
        assert prob is None

    def test_corrupt_outcomes_string(self):
        """Outcomes is a string that isn't valid JSON."""
        market = make_market(outcomes="not-json-list")
        # WHY: outcomePrices can't be matched without valid outcomes
        # Should still try fallbacks but none are present in standard market
        prob = _extract_probability_from_market(market)
        assert prob is None


# =========================================================================
# Tests: _match_market_in_results
# =========================================================================

class TestMatchMarket:
    """Test slug matching logic against search results."""

    def test_exact_slug_match(self):
        """Exact slug match is preferred."""
        m1 = make_market(slug="us-iran-april-30")
        m2 = make_market(slug="us-iran-may-31")
        result = _match_market_in_results([m1, m2], "us-iran-april-30")
        assert result["slug"] == "us-iran-april-30"

    def test_case_insensitive_match(self):
        """Slug matching should be case-insensitive."""
        m = make_market(slug="US-Iran-April-30")
        result = _match_market_in_results([m], "us-iran-april-30")
        assert result is not None

    def test_substring_match(self):
        """Falls back to substring when no exact match."""
        m = make_market(slug="us-iran-conflict-april-30-2026")
        result = _match_market_in_results([m], "us-iran")
        assert result is not None

    def test_question_text_match(self):
        """Falls back to question text when slug doesn't match."""
        m = make_market(
            slug="completely-different-slug",
            question="Will the US strike Iran before April 30?"
        )
        result = _match_market_in_results([m], "us-iran-april")
        assert result is not None

    def test_no_match(self):
        """Returns None when nothing matches."""
        m = make_market(slug="bitcoin-100k", question="Will Bitcoin hit $100k?")
        result = _match_market_in_results([m], "us-iran-april-30")
        assert result is None

    def test_empty_results(self):
        """Empty result list returns None."""
        result = _match_market_in_results([], "anything")
        assert result is None


# =========================================================================
# Tests: fetch_single_market (mocked HTTP)
# =========================================================================

class TestFetchSingleMarket:
    """Test the full fetch flow with mocked HTTP."""

    @patch("polymarket._make_request")
    def test_found_via_events(self, mock_req):
        """Market found through the events endpoint."""
        event = make_event(markets=[make_market(slug="us-iran-april-30")])
        # WHY two responses: first call is events, second is markets
        mock_req.side_effect = [
            json.dumps([event]).encode(),
            json.dumps([]).encode(),  # markets endpoint (won't be called)
        ]
        slug, prob = fetch_single_market("us-iran-april-30", retries=1)
        assert slug == "us-iran-april-30"
        assert prob == pytest.approx(0.685)

    @patch("polymarket._make_request")
    def test_found_via_markets_fallback(self, mock_req):
        """Events empty, found through markets endpoint."""
        market = make_market(slug="us-iran-april-30")
        mock_req.side_effect = [
            json.dumps([]).encode(),  # events: nothing
            json.dumps([market]).encode(),  # markets: found it
        ]
        slug, prob = fetch_single_market("us-iran-april-30", retries=1)
        assert slug == "us-iran-april-30"
        assert prob == pytest.approx(0.685)

    @patch("polymarket._make_request")
    def test_not_found_anywhere(self, mock_req):
        """Market doesn't exist — returns None, no crash."""
        mock_req.side_effect = [
            json.dumps([]).encode(),  # events: nothing
            json.dumps([]).encode(),  # markets: nothing
        ]
        slug, prob = fetch_single_market("nonexistent-market", retries=1)
        assert slug == "nonexistent-market"
        assert prob is None

    @patch("polymarket._make_request")
    def test_valid_empty_responses_do_not_retry(self, mock_req):
        """Two empty endpoint responses are a completed no-data lookup."""
        mock_req.side_effect = [
            json.dumps([]).encode(),
            json.dumps([]).encode(),
        ]

        slug, prob = fetch_single_market("nonexistent-market", retries=2)

        assert (slug, prob) == ("nonexistent-market", None)
        assert mock_req.call_count == 2

    @patch("polymarket._make_request")
    def test_network_failure_retries(self, mock_req):
        """Network failure triggers retries, then returns None."""
        mock_req.side_effect = URLError("Connection refused")
        slug, prob = fetch_single_market("us-iran-april-30", retries=2)
        assert slug == "us-iran-april-30"
        assert prob is None
        # WHY 4 calls: 2 retries x 2 calls per attempt (events + markets)
        # Actually: each attempt calls events first, and if it fails,
        # that attempt is retried. So 2 attempts total.
        assert mock_req.call_count == 2

    @patch("polymarket._make_request")
    def test_strict_network_failure_raises(self, mock_req):
        """Bridge callers can distinguish an outage from a real no-match."""
        mock_req.side_effect = URLError("Connection refused")

        with pytest.raises(APIError, match="failed after 1 attempt"):
            fetch_single_market(
                "us-iran-april-30", retries=1, raise_on_error=True,
            )

    @patch("polymarket._make_request")
    def test_network_recovery_on_retry(self, mock_req):
        """First attempt fails, second succeeds."""
        event = make_event(markets=[make_market(slug="us-iran-april-30")])
        mock_req.side_effect = [
            URLError("timeout"),  # attempt 1: fail
            json.dumps([event]).encode(),  # attempt 2: success
        ]
        slug, prob = fetch_single_market("us-iran-april-30", retries=2)
        assert prob == pytest.approx(0.685)

    @patch("polymarket._make_request")
    def test_strict_retry_can_recover_to_valid_no_data(self, mock_req):
        mock_req.side_effect = [
            URLError("timeout"),
            json.dumps([]).encode(),
            json.dumps([]).encode(),
        ]

        result = fetch_single_market(
            "us-iran-april-30", retries=2, raise_on_error=True,
        )

        assert result == ("us-iran-april-30", None)
        assert mock_req.call_count == 3

    @patch("polymarket._make_request")
    def test_unexpected_exception(self, mock_req):
        """Unexpected error (e.g. API shape change) doesn't crash."""
        mock_req.side_effect = KeyError("unexpected_field")
        slug, prob = fetch_single_market("us-iran-april-30", retries=1)
        assert prob is None

    @patch("polymarket._make_request")
    def test_malformed_json_response(self, mock_req):
        """API returns non-JSON — should handle gracefully."""
        mock_req.return_value = b"<html>Server Error</html>"
        slug, prob = fetch_single_market("us-iran-april-30", retries=1)
        assert prob is None


# =========================================================================
# Tests: fetch_markets (batch fetching)
# =========================================================================

class TestFetchMarkets:
    """Test batch market fetching."""

    @patch("polymarket.fetch_single_market")
    def test_multiple_slugs(self, mock_fetch):
        """Fetches multiple markets and returns a combined dict."""
        mock_fetch.side_effect = [
            ("slug-a", 0.7),
            ("slug-b", 0.3),
        ]
        results = fetch_markets(["slug-a", "slug-b"])
        assert results == {"slug-a": 0.7, "slug-b": 0.3}
        assert mock_fetch.call_count == 2

    @patch("polymarket.fetch_single_market")
    def test_partial_failure(self, mock_fetch):
        """Some markets succeed, some fail — returns all results."""
        mock_fetch.side_effect = [
            ("slug-a", 0.7),
            ("slug-b", None),  # failed
        ]
        results = fetch_markets(["slug-a", "slug-b"])
        assert results["slug-a"] == 0.7
        assert results["slug-b"] is None

    @patch("polymarket.fetch_single_market")
    def test_empty_slug_list(self, mock_fetch):
        """No slugs requested — returns empty dict."""
        results = fetch_markets([])
        assert results == {}
        assert mock_fetch.call_count == 0

    @patch("polymarket.fetch_single_market")
    def test_strict_mode_is_forwarded_to_each_market(self, mock_fetch):
        mock_fetch.return_value = ("slug-a", 0.7)

        assert fetch_markets(["slug-a"], raise_on_error=True) == {"slug-a": 0.7}
        mock_fetch.assert_called_once_with(
            "slug-a", timeout=15, retries=2, raise_on_error=True,
        )

    @patch("polymarket.fetch_single_market")
    def test_parallel_mode_preserves_authored_order(self, mock_fetch):
        mock_fetch.side_effect = lambda slug, **_kwargs: (
            slug, {"slug-a": 0.7, "slug-b": 0.3}[slug],
        )

        results = fetch_markets(
            ["slug-a", "slug-b"], parallel=True, raise_on_error=True,
        )

        assert list(results) == ["slug-a", "slug-b"]
        assert results == {"slug-a": 0.7, "slug-b": 0.3}


# =========================================================================
# Tests: API response parsing edge cases
# =========================================================================

class TestAPIEdgeCases:
    """Test handling of various API response shapes."""

    @patch("polymarket._make_request")
    def test_events_returns_dict_not_list(self, mock_req):
        """Some API endpoints wrap results in an object."""
        mock_req.return_value = json.dumps({"data": "not a list"}).encode()
        events = _search_events("test")
        assert events == []

    @patch("polymarket._make_request")
    def test_markets_returns_single_object(self, mock_req):
        """Markets endpoint may return a single market, not a list."""
        market = make_market(slug="single-market")
        mock_req.return_value = json.dumps(market).encode()
        markets = _search_markets("single-market")
        assert len(markets) == 1
        assert markets[0]["slug"] == "single-market"

    @patch("polymarket._make_request")
    def test_markets_returns_data_wrapper(self, mock_req):
        """Markets endpoint wraps results in {data: [...]}."""
        market = make_market(slug="wrapped-market")
        mock_req.return_value = json.dumps({"data": [market]}).encode()
        markets = _search_markets("wrapped-market")
        assert len(markets) == 1

    @patch("polymarket._make_request")
    def test_event_with_no_markets_key(self, mock_req):
        """Event object missing 'markets' array."""
        event = {"id": "evt-001", "slug": "bare-event", "title": "No markets here"}
        mock_req.side_effect = [
            json.dumps([event]).encode(),  # events: event with no markets
            json.dumps([]).encode(),  # markets: nothing
        ]
        slug, prob = fetch_single_market("bare-event", retries=1)
        assert prob is None
