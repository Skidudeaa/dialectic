#!/usr/bin/env python3
"""
Tests for GDELT Doc 2.0 API fetcher.

Runs offline — _make_request is mocked at module boundary.
"""

import json
import os
import sys
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from gdelt import (  # noqa: E402
    GDELT_DOC_API,
    STANDARD_QUERIES,
    Article,
    GdeltAPIError,
    GdeltError,
    GdeltRateLimitError,
    _build_url,
    _parse_json,
    fetch_articles,
    fetch_volume_latest,
    fetch_volume_timeline,
    get_standard_query,
)


# =========================================================================
# Fixtures
# =========================================================================

def _volume_payload(*buckets):
    """Build a synthetic timelinevol JSON response."""
    return json.dumps({
        "timeline": [{
            "data": [
                {"date": d, "value": v} for d, v in buckets
            ],
        }],
    }).encode()


def _articles_payload(*articles):
    return json.dumps({
        "articles": list(articles),
    }).encode()


# =========================================================================
# Tests: URL build
# =========================================================================

class TestBuildUrl:
    def test_volume_url(self):
        url = _build_url("Hormuz", "timelinevol", timespan="1d")
        assert url.startswith(GDELT_DOC_API)
        assert "query=Hormuz" in url
        assert "mode=timelinevol" in url
        assert "format=json" in url
        assert "timespan=1d" in url

    def test_articles_url_with_max_records(self):
        url = _build_url("tariff", "artlist", timespan="7d", max_records=10)
        assert "mode=artlist" in url
        assert "maxrecords=10" in url
        assert "timespan=7d" in url

    def test_quoted_phrase_url_encoded(self):
        url = _build_url('"Country Garden" OR "Vanke"', "artlist")
        # Quoted phrase encoded as %22
        assert "%22Country+Garden%22" in url or "%22Country%20Garden%22" in url
        assert "OR" in url

    def test_start_end_datetime(self):
        url = _build_url(
            "x", "timelinevol",
            start="20260501000000", end="20260510235959",
        )
        assert "startdatetime=20260501000000" in url
        assert "enddatetime=20260510235959" in url


# =========================================================================
# Tests: JSON parsing
# =========================================================================

class TestParseJson:
    def test_valid_json(self):
        out = _parse_json(b'{"timeline": []}', "x")
        assert out == {"timeline": []}

    def test_empty_body_returns_empty_dict(self):
        # GDELT returns empty body on no-match queries.
        assert _parse_json(b"", "x") == {}
        assert _parse_json(b"   ", "x") == {}

    def test_non_json_raises_api_error(self):
        with pytest.raises(GdeltAPIError):
            _parse_json(b"<html>500 Internal</html>", "x")


# =========================================================================
# Tests: volume timeline
# =========================================================================

class TestVolumeTimeline:
    @patch("gdelt._make_request")
    def test_three_buckets_parse(self, mock_req):
        mock_req.return_value = _volume_payload(
            ("20260507T000000Z", 0.0023),
            ("20260508T000000Z", 0.0019),
            ("20260509T000000Z", 0.0034),
        )
        series = fetch_volume_timeline("Hormuz", timespan="3d")
        assert len(series) == 3
        assert series[0] == ("20260507T000000Z", pytest.approx(0.0023))
        assert series[-1][1] == pytest.approx(0.0034)

    @patch("gdelt._make_request")
    def test_empty_data_returns_empty_list(self, mock_req):
        mock_req.return_value = _volume_payload()
        series = fetch_volume_timeline("Hormuz", timespan="1d")
        assert series == []

    @patch("gdelt._make_request")
    def test_empty_body_returns_empty_list(self, mock_req):
        mock_req.return_value = b""
        series = fetch_volume_timeline("noresults", timespan="1d")
        assert series == []

    @patch("gdelt._make_request")
    def test_missing_timeline_key_returns_empty(self, mock_req):
        mock_req.return_value = b'{"other": []}'
        series = fetch_volume_timeline("Hormuz")
        assert series == []

    @patch("gdelt._make_request")
    def test_volume_latest_returns_last_bucket(self, mock_req):
        mock_req.return_value = _volume_payload(
            ("20260508T000000Z", 0.001),
            ("20260509T000000Z", 0.005),
        )
        v = fetch_volume_latest("Hormuz", timespan="1d")
        assert v == pytest.approx(0.005)

    @patch("gdelt._make_request")
    def test_volume_latest_returns_none_when_empty(self, mock_req):
        mock_req.return_value = _volume_payload()
        assert fetch_volume_latest("noresults") is None

    @patch("gdelt._make_request")
    def test_skips_malformed_rows(self, mock_req):
        # GDELT can return null/missing fields; parser must skip them.
        mock_req.return_value = json.dumps({
            "timeline": [{
                "data": [
                    {"date": "20260508T000000Z", "value": 0.001},
                    {"date": None, "value": 0.002},
                    {"date": "20260509T000000Z", "value": "not-a-number"},
                    {"date": "20260510T000000Z", "value": 0.003},
                ],
            }],
        }).encode()
        series = fetch_volume_timeline("x", timespan="3d")
        assert [d for d, _ in series] == [
            "20260508T000000Z", "20260510T000000Z",
        ]


# =========================================================================
# Tests: article list
# =========================================================================

class TestArticles:
    @patch("gdelt._make_request")
    def test_articles_parse(self, mock_req):
        mock_req.return_value = _articles_payload(
            {
                "url": "https://reuters.com/x",
                "title": "Iran threatens Hormuz",
                "seendate": "20260509T143000Z",
                "domain": "reuters.com",
                "language": "English",
                "sourcecountry": "US",
            },
        )
        arts = fetch_articles("Hormuz", max_records=10)
        assert len(arts) == 1
        assert isinstance(arts[0], Article)
        assert arts[0].domain == "reuters.com"
        assert arts[0].title == "Iran threatens Hormuz"

    @patch("gdelt._make_request")
    def test_minimal_article_fields(self, mock_req):
        # GDELT sometimes omits language/sourcecountry — must not crash.
        mock_req.return_value = json.dumps({
            "articles": [
                {"url": "https://example.com/x", "title": "test",
                 "seendate": "20260509T000000Z", "domain": "example.com"},
            ],
        }).encode()
        arts = fetch_articles("test")
        assert len(arts) == 1
        assert arts[0].language == ""
        assert arts[0].sourcecountry == ""

    @patch("gdelt._make_request")
    def test_no_articles_field_returns_empty(self, mock_req):
        mock_req.return_value = b'{"other": []}'
        arts = fetch_articles("Hormuz")
        assert arts == []


# =========================================================================
# Tests: rate limit handling
# =========================================================================

class TestRateLimit:
    @patch("gdelt.time.sleep", lambda *_a, **_k: None)
    @patch("gdelt._make_request")
    def test_429_then_success(self, mock_req):
        mock_req.side_effect = [
            HTTPError(url="x", code=429, msg="Too Many", hdrs=None, fp=None),
            _volume_payload(("20260509T000000Z", 0.003)),
        ]
        v = fetch_volume_latest("Hormuz")
        assert v == pytest.approx(0.003)
        assert mock_req.call_count == 2

    @patch("gdelt.time.sleep", lambda *_a, **_k: None)
    @patch("gdelt._make_request")
    def test_429_twice_raises(self, mock_req):
        mock_req.side_effect = [
            HTTPError(url="x", code=429, msg="Too Many", hdrs=None, fp=None),
            HTTPError(url="x", code=429, msg="Too Many", hdrs=None, fp=None),
        ]
        with pytest.raises(GdeltRateLimitError):
            fetch_volume_latest("Hormuz")


# =========================================================================
# Tests: error paths
# =========================================================================

class TestErrors:
    @patch("gdelt._make_request")
    def test_400_raises_api_error_no_retry(self, mock_req):
        mock_req.side_effect = HTTPError(
            url="x", code=400, msg="Bad Request", hdrs=None, fp=None
        )
        with pytest.raises(GdeltAPIError):
            fetch_volume_latest("malformed")
        assert mock_req.call_count == 1

    @patch("gdelt.time.sleep", lambda *_a, **_k: None)
    @patch("gdelt._make_request")
    def test_5xx_retries(self, mock_req):
        mock_req.side_effect = [
            HTTPError(url="x", code=503, msg="x", hdrs=None, fp=None),
            _volume_payload(("20260509T000000Z", 0.003)),
        ]
        v = fetch_volume_latest("Hormuz")
        assert v == pytest.approx(0.003)


# =========================================================================
# Tests: standard queries registry
# =========================================================================

class TestStandardQueries:
    def test_all_canonical_queries_present(self):
        expected = {
            "iran-hormuz-event",
            "trump-tariff-escalation",
            "china-property-default",
            "japan-rate-shock",
            "ai-capex-cut",
        }
        assert expected.issubset(set(STANDARD_QUERIES.keys()))

    def test_get_standard_query(self):
        q = get_standard_query("iran-hormuz-event")
        assert q is not None
        assert "Hormuz" in q

    def test_unknown_standard_query_returns_none(self):
        assert get_standard_query("not-a-thing") is None

    def test_all_queries_are_nonempty_strings(self):
        for name, q in STANDARD_QUERIES.items():
            assert isinstance(q, str) and q.strip(), name
