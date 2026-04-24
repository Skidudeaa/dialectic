#!/usr/bin/env python3
"""
Tests for FRED macro series fetcher.

Runs with: python3 -m pytest tools/data_fetch/test_fred.py -q

WHY mock HTTP: these tests must work offline and deterministically. All
HTTP calls are mocked at the _make_request boundary so we test parsing,
error handling, and retry behavior without hitting the real FRED API.

WHY env-mocked api key: every test that doesn't specifically test the
missing-key path patches FRED_API_KEY into the environment via
monkeypatch.setenv so _get_api_key succeeds without operator setup.
"""

import json
import os
import re
import sys
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

# Add parent dir to path so we can import the module
sys.path.insert(0, os.path.dirname(__file__))
from fred import (  # noqa: E402
    FRED_API_BASE,
    FredAPIError,
    FredAuthError,
    FredError,
    FredNoDataError,
    _build_observations_url,
    _get_api_key,
    fetch_series_batch,
    fetch_series_latest,
)


# =========================================================================
# FIXTURES
# =========================================================================

def _api_response(value: str = "4.35", date: str = "2026-04-23") -> bytes:
    """Build a realistic FRED observations response."""
    return json.dumps({
        "realtime_start": "2026-04-24",
        "realtime_end": "2026-04-24",
        "observation_start": "1600-01-01",
        "observation_end": "9999-12-31",
        "units": "lin",
        "output_type": 1,
        "file_type": "json",
        "order_by": "observation_date",
        "sort_order": "desc",
        "count": 1,
        "offset": 0,
        "limit": 1,
        "observations": [
            {
                "realtime_start": "2026-04-24",
                "realtime_end": "2026-04-24",
                "date": date,
                "value": value,
            }
        ],
    }).encode()


@pytest.fixture(autouse=False)
def fred_key(monkeypatch):
    """Provide a valid-looking FRED_API_KEY for tests that need one."""
    monkeypatch.setenv("FRED_API_KEY", "test-key-abcdef0123456789abcdef0123456789")
    return "test-key-abcdef0123456789abcdef0123456789"


# =========================================================================
# Tests: _get_api_key
# =========================================================================

class TestApiKey:
    def test_returns_value(self, fred_key):
        assert _get_api_key() == fred_key

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        with pytest.raises(FredAuthError) as exc:
            _get_api_key()
        assert "FRED_API_KEY" in str(exc.value)

    def test_blank_raises(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "   ")
        with pytest.raises(FredAuthError):
            _get_api_key()


# =========================================================================
# Tests: _build_observations_url
# =========================================================================

class TestBuildUrl:
    def test_includes_series_and_key(self):
        url = _build_observations_url("DGS10", "abc123")
        assert url.startswith(FRED_API_BASE)
        assert "series_id=DGS10" in url
        assert "api_key=abc123" in url
        assert "file_type=json" in url
        assert "sort_order=desc" in url
        assert "limit=1" in url


# =========================================================================
# Tests: fetch_series_latest happy path + observation shape
# =========================================================================

class TestFetchHappyPath:
    @patch("fred._make_request")
    def test_returns_value_date_fetched_at(self, mock_req, fred_key):
        mock_req.return_value = _api_response(value="4.35", date="2026-04-23")
        obs = fetch_series_latest("DGS10")
        assert obs["value"] == pytest.approx(4.35)
        assert obs["observation_date"] == "2026-04-23"
        # ISO8601 UTC, e.g. 2026-04-24T16:30:00Z
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", obs["fetched_at"]
        )

    @patch("fred._make_request")
    def test_negative_value_parses(self, mock_req, fred_key):
        # FRED yields can be negative (e.g. early 2020s European rates).
        mock_req.return_value = _api_response(value="-0.25", date="2026-04-23")
        obs = fetch_series_latest("IRSTCI01JPM156N")
        assert obs["value"] == pytest.approx(-0.25)


# =========================================================================
# Tests: missing api key path
# =========================================================================

class TestMissingApiKey:
    def test_raises_fred_auth_error(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        with pytest.raises(FredAuthError):
            fetch_series_latest("DGS10")


# =========================================================================
# Tests: HTTP error handling
# =========================================================================

class TestHttpErrors:
    @patch("fred._make_request")
    def test_404_raises_api_error(self, mock_req, fred_key):
        mock_req.side_effect = HTTPError(
            url="x", code=404, msg="Not Found", hdrs=None, fp=None
        )
        with pytest.raises(FredAPIError) as exc:
            fetch_series_latest("BAD_SERIES", retries=0)
        assert "404" in str(exc.value)

    @patch("fred._make_request")
    def test_401_raises_auth_error(self, mock_req, fred_key):
        mock_req.side_effect = HTTPError(
            url="x", code=401, msg="Unauthorized", hdrs=None, fp=None
        )
        with pytest.raises(FredAuthError):
            fetch_series_latest("DGS10", retries=0)

    @patch("fred._make_request")
    def test_403_raises_auth_error(self, mock_req, fred_key):
        mock_req.side_effect = HTTPError(
            url="x", code=403, msg="Forbidden", hdrs=None, fp=None
        )
        with pytest.raises(FredAuthError):
            fetch_series_latest("DGS10", retries=0)

    @patch("fred._make_request")
    def test_400_does_not_retry(self, mock_req, fred_key):
        mock_req.side_effect = HTTPError(
            url="x", code=400, msg="Bad Request", hdrs=None, fp=None
        )
        with pytest.raises(FredAPIError):
            fetch_series_latest("DGS10", retries=3)
        # WHY 1 call: 4xx is permanent — must not retry.
        assert mock_req.call_count == 1


# =========================================================================
# Tests: missing observation / "." sentinel
# =========================================================================

class TestNoData:
    @patch("fred._make_request")
    def test_dot_sentinel_raises_no_data(self, mock_req, fred_key):
        mock_req.return_value = _api_response(value=".", date="2026-04-23")
        with pytest.raises(FredNoDataError):
            fetch_series_latest("DGS10")

    @patch("fred._make_request")
    def test_empty_observations_raises_no_data(self, mock_req, fred_key):
        mock_req.return_value = json.dumps({"observations": []}).encode()
        with pytest.raises(FredNoDataError):
            fetch_series_latest("DGS10")

    @patch("fred._make_request")
    def test_missing_observations_key_raises_no_data(self, mock_req, fred_key):
        mock_req.return_value = json.dumps({"count": 0}).encode()
        with pytest.raises(FredNoDataError):
            fetch_series_latest("DGS10")

    @patch("fred._make_request")
    def test_blank_value_raises_no_data(self, mock_req, fred_key):
        mock_req.return_value = _api_response(value="", date="2026-04-23")
        with pytest.raises(FredNoDataError):
            fetch_series_latest("DGS10")


# =========================================================================
# Tests: retry on 5xx
# =========================================================================

class TestRetries:
    @patch("fred.time.sleep", lambda *_a, **_k: None)
    @patch("fred._make_request")
    def test_5xx_then_success(self, mock_req, fred_key):
        # WHY two side effects: first attempt 503, second succeeds.
        mock_req.side_effect = [
            HTTPError(url="x", code=503, msg="Service Unavailable",
                      hdrs=None, fp=None),
            _api_response(value="4.35", date="2026-04-23"),
        ]
        obs = fetch_series_latest("DGS10", retries=2)
        assert obs["value"] == pytest.approx(4.35)
        assert mock_req.call_count == 2

    @patch("fred.time.sleep", lambda *_a, **_k: None)
    @patch("fred._make_request")
    def test_retry_exhaustion_raises(self, mock_req, fred_key):
        mock_req.side_effect = HTTPError(
            url="x", code=503, msg="Service Unavailable", hdrs=None, fp=None
        )
        with pytest.raises(FredAPIError):
            fetch_series_latest("DGS10", retries=2)
        # 1 initial + 2 retries = 3 calls
        assert mock_req.call_count == 3

    @patch("fred.time.sleep", lambda *_a, **_k: None)
    @patch("fred._make_request")
    def test_url_error_retries(self, mock_req, fred_key):
        mock_req.side_effect = [
            URLError("connection refused"),
            URLError("timeout"),
            _api_response(value="152.4", date="2026-04-23"),
        ]
        obs = fetch_series_latest("DEXJPUS", retries=2)
        assert obs["value"] == pytest.approx(152.4)
        assert mock_req.call_count == 3


# =========================================================================
# Tests: malformed JSON
# =========================================================================

class TestMalformed:
    @patch("fred._make_request")
    def test_non_json_response(self, mock_req, fred_key):
        mock_req.return_value = b"<html>Server Error</html>"
        with pytest.raises(FredAPIError):
            fetch_series_latest("DGS10", retries=0)

    @patch("fred._make_request")
    def test_value_not_numeric(self, mock_req, fred_key):
        mock_req.return_value = _api_response(value="abc", date="2026-04-23")
        with pytest.raises(FredAPIError):
            fetch_series_latest("DGS10", retries=0)


# =========================================================================
# Tests: fetch_series_batch
# =========================================================================

class TestBatch:
    @patch("fred.time.sleep", lambda *_a, **_k: None)
    @patch("fred.fetch_series_latest")
    def test_partial_success(self, mock_single, fred_key):
        # WHY side_effect mix: one valid obs, one FredNoDataError. Batch
        # must return only the successful one without crashing.
        mock_single.side_effect = [
            {
                "value": 4.35,
                "observation_date": "2026-04-23",
                "fetched_at": "2026-04-24T00:00:00Z",
            },
            FredNoDataError("bad series"),
        ]
        out = fetch_series_batch(["DGS10", "BOGUS"])
        assert "DGS10" in out
        assert out["DGS10"]["value"] == pytest.approx(4.35)
        assert "BOGUS" not in out

    @patch("fred.time.sleep", lambda *_a, **_k: None)
    @patch("fred.fetch_series_latest")
    def test_all_succeed(self, mock_single, fred_key):
        mock_single.side_effect = [
            {"value": 4.35, "observation_date": "2026-04-23",
             "fetched_at": "2026-04-24T00:00:00Z"},
            {"value": 152.4, "observation_date": "2026-04-23",
             "fetched_at": "2026-04-24T00:00:00Z"},
        ]
        out = fetch_series_batch(["DGS10", "DEXJPUS"])
        assert set(out.keys()) == {"DGS10", "DEXJPUS"}

    @patch("fred.fetch_series_latest")
    def test_empty_input(self, mock_single, fred_key):
        out = fetch_series_batch([])
        assert out == {}
        assert mock_single.call_count == 0

    def test_missing_key_raises_immediately(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        with pytest.raises(FredAuthError):
            fetch_series_batch(["DGS10"])

    @patch("fred.time.sleep", lambda *_a, **_k: None)
    @patch("fred.fetch_series_latest")
    def test_api_error_skipped(self, mock_single, fred_key):
        mock_single.side_effect = [
            FredAPIError("bang"),
            {"value": 7.34, "observation_date": "2026-04-23",
             "fetched_at": "2026-04-24T00:00:00Z"},
        ]
        out = fetch_series_batch(["BOOM", "DEXCHUS"])
        assert "BOOM" not in out
        assert "DEXCHUS" in out


# =========================================================================
# Live test (skipped unless FRED_API_KEY is in env AND opted in)
# =========================================================================

@pytest.mark.skipif(
    not os.environ.get("FRED_API_KEY") or
    os.environ.get("FRED_API_KEY", "").startswith("test-"),
    reason="FRED_API_KEY not set; skipping live network test",
)
def test_live_dgs10_round_trip():
    """Optional smoke test against real FRED — opt-in via real API key."""
    obs = fetch_series_latest("DGS10")
    assert obs["value"] > 0
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", obs["observation_date"])
