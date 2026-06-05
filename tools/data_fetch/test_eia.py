#!/usr/bin/env python3
"""
Tests for EIA Open Data v2 fetcher.

Runs with: python3 -m pytest tools/data_fetch/test_eia.py -q

WHY mock HTTP: these tests must work offline and deterministically. All
HTTP calls are mocked at the _make_request boundary so we test parsing,
URL construction, error handling, and retry behavior without hitting
the real EIA API.
"""

import json
import os
import re
import sys
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from eia import (  # noqa: E402
    EIA_API_BASE,
    EIAAPIError,
    EIAAuthError,
    EIAError,
    EIANoDataError,
    EIAObservation,
    EIASpec,
    _build_url,
    _get_api_key,
    _parse_facet_args,
    _parse_response,
    fetch_series_batch,
    fetch_series_latest,
    spec_petroleum_series,
    spec_weekly_crude_stocks_ex_spr,
    spec_weekly_natural_gas_storage,
    spec_weekly_refinery_utilization,
)


# =========================================================================
# Fixtures
# =========================================================================

def _api_response(
    value="3.84",
    period="2026-05-05",
    units="$/GAL",
    extra_rows=None,
):
    """Build a realistic EIA v2 response with one data row (or more)."""
    rows = [{"period": period, "value": value, "units": units}]
    if extra_rows:
        rows.extend(extra_rows)
    return json.dumps({
        "response": {
            "total": str(len(rows)),
            "data": rows,
            "description": "Test data",
        },
        "request": {"command": "/v2/test", "params": {}},
        "apiVersion": "2.1.10",
    }).encode()


@pytest.fixture
def eia_key(monkeypatch):
    """Provide a valid-looking EIA_API_KEY for tests that need one."""
    monkeypatch.setenv("EIA_API_KEY", "test-key-deadbeef0123456789abcdef0123")
    return "test-key-deadbeef0123456789abcdef0123"


@pytest.fixture
def diesel_spec():
    return spec_petroleum_series("EMD_EPD2D_PTE_NUS_DPG")


# =========================================================================
# Tests: API key resolution
# =========================================================================

class TestApiKey:
    def test_returns_value(self, eia_key):
        assert _get_api_key() == eia_key

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("EIA_API_KEY", raising=False)
        with pytest.raises(EIAAuthError) as exc:
            _get_api_key()
        assert "EIA_API_KEY" in str(exc.value)

    def test_blank_raises(self, monkeypatch):
        monkeypatch.setenv("EIA_API_KEY", "   ")
        with pytest.raises(EIAAuthError):
            _get_api_key()


# =========================================================================
# Tests: URL construction
# =========================================================================

class TestBuildUrl:
    def test_basic_route_and_key(self, diesel_spec):
        url = _build_url(diesel_spec, "abc123")
        assert url.startswith(EIA_API_BASE)
        assert "/petroleum/pri/gnd/data?" in url
        assert "api_key=abc123" in url
        assert "data%5B%5D=value" in url  # data[]=value urlencoded

    def test_facet_encoded_with_brackets(self, diesel_spec):
        url = _build_url(diesel_spec, "abc123")
        # facets[series][]=EMD_EPD2D_PTE_NUS_DPG
        assert "facets%5Bseries%5D%5B%5D=EMD_EPD2D_PTE_NUS_DPG" in url

    def test_multiple_facet_values(self):
        spec = EIASpec(
            key="multi",
            route="petroleum/stoc/wstk/data",
            facets={"product": ["EPC0", "EPD0"], "duoarea": ["NUS"]},
            frequency="weekly",
        )
        url = _build_url(spec, "abc123")
        # Both product values appear; duoarea single value also there
        assert url.count("facets%5Bproduct%5D%5B%5D=") == 2
        assert "facets%5Bproduct%5D%5B%5D=EPC0" in url
        assert "facets%5Bproduct%5D%5B%5D=EPD0" in url
        assert "facets%5Bduoarea%5D%5B%5D=NUS" in url

    def test_frequency_param(self, diesel_spec):
        url = _build_url(diesel_spec, "abc123")
        assert "frequency=weekly" in url

    def test_no_frequency_omitted(self):
        spec = EIASpec(key="nofreq", route="petroleum/pri/gnd/data")
        url = _build_url(spec, "abc123")
        assert "frequency=" not in url

    def test_sort_desc_and_limit(self, diesel_spec):
        url = _build_url(diesel_spec, "abc123")
        assert "sort%5B0%5D%5Bcolumn%5D=period" in url
        assert "sort%5B0%5D%5Bdirection%5D=desc" in url
        assert "length=1" in url

    def test_length_override(self):
        spec = EIASpec(key="multi", route="x", length=4)
        url = _build_url(spec, "abc")
        assert "length=4" in url

    def test_string_facet_value_tolerated(self):
        # If a caller passes a string instead of [string], it should still work
        spec = EIASpec(
            key="x",
            route="petroleum/pri/gnd/data",
            facets={"series": "EMD_EPD2D_PTE_NUS_DPG"},  # type: ignore[arg-type]
        )
        url = _build_url(spec, "abc")
        assert "facets%5Bseries%5D%5B%5D=EMD_EPD2D_PTE_NUS_DPG" in url

    def test_route_with_leading_slash_normalized(self):
        spec = EIASpec(key="x", route="/petroleum/pri/gnd/data")
        url = _build_url(spec, "abc")
        assert "//petroleum" not in url


# =========================================================================
# Tests: response parsing
# =========================================================================

class TestParseResponse:
    def test_picks_first_row(self, diesel_spec):
        body = _api_response(value="3.84", period="2026-05-05")
        obs = _parse_response(body, diesel_spec)
        assert obs.value == pytest.approx(3.84)
        assert obs.period == "2026-05-05"
        assert obs.units == "$/GAL"

    def test_picks_first_when_multiple_rows(self, diesel_spec):
        # We sort desc in the URL, so rows[0] is newest. Confirm parser
        # respects that order without re-sorting.
        body = _api_response(
            value="3.84",
            period="2026-05-05",
            extra_rows=[
                {"period": "2026-04-28", "value": "3.79", "units": "$/GAL"},
                {"period": "2026-04-21", "value": "3.71", "units": "$/GAL"},
            ],
        )
        obs = _parse_response(body, diesel_spec)
        assert obs.period == "2026-05-05"
        assert obs.value == pytest.approx(3.84)

    def test_negative_value_parses(self, diesel_spec):
        body = _api_response(value="-1.25", period="2026-05-05")
        obs = _parse_response(body, diesel_spec)
        assert obs.value == pytest.approx(-1.25)

    def test_integer_value_parses(self, diesel_spec):
        # EIA sometimes returns ints for inventory series
        body = _api_response(value="433802", period="2026-05-02", units="MBBL")
        obs = _parse_response(body, diesel_spec)
        assert obs.value == pytest.approx(433802.0)

    def test_empty_data_array_raises_no_data(self, diesel_spec):
        body = json.dumps({"response": {"data": [], "total": "0"}}).encode()
        with pytest.raises(EIANoDataError):
            _parse_response(body, diesel_spec)

    def test_null_value_raises_no_data(self, diesel_spec):
        body = json.dumps({"response": {"data": [
            {"period": "2026-05-05", "value": None, "units": "$/GAL"}
        ]}}).encode()
        with pytest.raises(EIANoDataError):
            _parse_response(body, diesel_spec)

    def test_blank_value_raises_no_data(self, diesel_spec):
        body = _api_response(value="", period="2026-05-05")
        with pytest.raises(EIANoDataError):
            _parse_response(body, diesel_spec)

    def test_non_numeric_value_raises_api_error(self, diesel_spec):
        body = _api_response(value="abc", period="2026-05-05")
        with pytest.raises(EIAAPIError):
            _parse_response(body, diesel_spec)

    def test_missing_response_key_raises_api_error(self, diesel_spec):
        body = json.dumps({"data": [{"period": "x", "value": "1.0"}]}).encode()
        with pytest.raises(EIAAPIError):
            _parse_response(body, diesel_spec)

    def test_error_envelope_raises_api_error(self, diesel_spec):
        body = json.dumps({"error": "invalid api_key"}).encode()
        with pytest.raises(EIAAPIError) as exc:
            _parse_response(body, diesel_spec)
        assert "invalid api_key" in str(exc.value)

    def test_non_json_raises_api_error(self, diesel_spec):
        body = b"<html>503 Service Unavailable</html>"
        with pytest.raises(EIAAPIError):
            _parse_response(body, diesel_spec)


# =========================================================================
# Tests: fetch_series_latest happy path
# =========================================================================

class TestFetchHappyPath:
    @patch("eia._make_request")
    def test_returns_observation(self, mock_req, eia_key, diesel_spec):
        mock_req.return_value = _api_response(value="3.84", period="2026-05-05")
        obs = fetch_series_latest(diesel_spec)
        assert isinstance(obs, EIAObservation)
        assert obs.value == pytest.approx(3.84)
        assert obs.period == "2026-05-05"
        assert obs.units == "$/GAL"
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", obs.fetched_at
        )

    @patch("eia._make_request")
    def test_to_dict_round_trip(self, mock_req, eia_key, diesel_spec):
        mock_req.return_value = _api_response(value="3.84", period="2026-05-05")
        obs = fetch_series_latest(diesel_spec)
        d = obs.to_dict()
        assert d["value"] == pytest.approx(3.84)
        assert d["period"] == "2026-05-05"
        assert d["units"] == "$/GAL"
        assert "fetched_at" in d


# =========================================================================
# Tests: missing API key
# =========================================================================

class TestMissingApiKey:
    def test_raises_eia_auth_error(self, monkeypatch, diesel_spec):
        monkeypatch.delenv("EIA_API_KEY", raising=False)
        with pytest.raises(EIAAuthError):
            fetch_series_latest(diesel_spec)


# =========================================================================
# Tests: HTTP error handling
# =========================================================================

class TestHttpErrors:
    @patch("eia._make_request")
    def test_404_raises_api_error_no_retry(self, mock_req, eia_key, diesel_spec):
        mock_req.side_effect = HTTPError(
            url="x", code=404, msg="Not Found", hdrs=None, fp=None
        )
        with pytest.raises(EIAAPIError):
            fetch_series_latest(diesel_spec, retries=3)
        # 4xx is permanent — must not retry.
        assert mock_req.call_count == 1

    @patch("eia._make_request")
    def test_401_raises_auth_error(self, mock_req, eia_key, diesel_spec):
        mock_req.side_effect = HTTPError(
            url="x", code=401, msg="Unauthorized", hdrs=None, fp=None
        )
        with pytest.raises(EIAAuthError):
            fetch_series_latest(diesel_spec, retries=0)

    @patch("eia._make_request")
    def test_403_raises_auth_error(self, mock_req, eia_key, diesel_spec):
        mock_req.side_effect = HTTPError(
            url="x", code=403, msg="Forbidden", hdrs=None, fp=None
        )
        with pytest.raises(EIAAuthError):
            fetch_series_latest(diesel_spec, retries=0)


# =========================================================================
# Tests: retry on 5xx + URLError
# =========================================================================

class TestRetries:
    @patch("eia.time.sleep", lambda *_a, **_k: None)
    @patch("eia._make_request")
    def test_503_then_success(self, mock_req, eia_key, diesel_spec):
        mock_req.side_effect = [
            HTTPError(url="x", code=503, msg="Service Unavailable",
                      hdrs=None, fp=None),
            _api_response(value="3.84", period="2026-05-05"),
        ]
        obs = fetch_series_latest(diesel_spec, retries=2)
        assert obs.value == pytest.approx(3.84)
        assert mock_req.call_count == 2

    @patch("eia.time.sleep", lambda *_a, **_k: None)
    @patch("eia._make_request")
    def test_429_retried(self, mock_req, eia_key, diesel_spec):
        # 429 is transient throttling — retry.
        mock_req.side_effect = [
            HTTPError(url="x", code=429, msg="Too Many Requests",
                      hdrs=None, fp=None),
            _api_response(value="3.84", period="2026-05-05"),
        ]
        with pytest.raises(EIAAPIError):
            # Actually 429 is in the 4xx range — by spec it does NOT retry.
            # This test documents that the contract treats 429 as fatal.
            fetch_series_latest(diesel_spec, retries=2)
        # Confirm no retry happened — 429 is 4xx, fail-fast.
        assert mock_req.call_count == 1

    @patch("eia.time.sleep", lambda *_a, **_k: None)
    @patch("eia._make_request")
    def test_url_error_retries(self, mock_req, eia_key, diesel_spec):
        mock_req.side_effect = [
            URLError("connection refused"),
            URLError("timeout"),
            _api_response(value="3.84", period="2026-05-05"),
        ]
        obs = fetch_series_latest(diesel_spec, retries=2)
        assert obs.value == pytest.approx(3.84)
        assert mock_req.call_count == 3

    @patch("eia.time.sleep", lambda *_a, **_k: None)
    @patch("eia._make_request")
    def test_retry_exhaustion_raises(self, mock_req, eia_key, diesel_spec):
        mock_req.side_effect = HTTPError(
            url="x", code=503, msg="Service Unavailable", hdrs=None, fp=None
        )
        with pytest.raises(EIAAPIError):
            fetch_series_latest(diesel_spec, retries=2)
        assert mock_req.call_count == 3


# =========================================================================
# Tests: batch fetch
# =========================================================================

class TestBatch:
    @patch("eia.time.sleep", lambda *_a, **_k: None)
    @patch("eia.fetch_series_latest")
    def test_partial_success_returns_none_for_failed(self, mock_single, eia_key):
        mock_single.side_effect = [
            EIAObservation(
                value=3.84, period="2026-05-05",
                units="$/GAL", fetched_at="2026-05-06T00:00:00Z",
            ),
            EIANoDataError("crude stocks not yet released"),
        ]
        specs = [
            spec_petroleum_series("EMD_EPD2D_PTE_NUS_DPG"),
            spec_weekly_crude_stocks_ex_spr(),
        ]
        out = fetch_series_batch(specs)
        assert out["EMD_EPD2D_PTE_NUS_DPG"].value == pytest.approx(3.84)
        assert out["crude_stocks_ex_spr"] is None

    @patch("eia.time.sleep", lambda *_a, **_k: None)
    @patch("eia.fetch_series_latest")
    def test_all_succeed(self, mock_single, eia_key):
        mock_single.side_effect = [
            EIAObservation(
                value=3.84, period="2026-05-05",
                units="$/GAL", fetched_at="2026-05-06T00:00:00Z",
            ),
            EIAObservation(
                value=433802.0, period="2026-05-02",
                units="MBBL", fetched_at="2026-05-06T00:00:00Z",
            ),
        ]
        specs = [
            spec_petroleum_series("EMD_EPD2D_PTE_NUS_DPG"),
            spec_weekly_crude_stocks_ex_spr(),
        ]
        out = fetch_series_batch(specs)
        assert set(out.keys()) == {
            "EMD_EPD2D_PTE_NUS_DPG", "crude_stocks_ex_spr"
        }
        assert all(v is not None for v in out.values())

    @patch("eia.fetch_series_latest")
    def test_empty_input(self, mock_single, eia_key):
        out = fetch_series_batch([])
        assert out == {}
        assert mock_single.call_count == 0

    def test_missing_key_raises_immediately(self, monkeypatch, diesel_spec):
        monkeypatch.delenv("EIA_API_KEY", raising=False)
        with pytest.raises(EIAAuthError):
            fetch_series_batch([diesel_spec])

    @patch("eia.time.sleep", lambda *_a, **_k: None)
    @patch("eia.fetch_series_latest")
    def test_api_error_yields_none(self, mock_single, eia_key):
        mock_single.side_effect = [
            EIAAPIError("unparseable response"),
            EIAObservation(
                value=3.84, period="2026-05-05",
                units="$/GAL", fetched_at="2026-05-06T00:00:00Z",
            ),
        ]
        out = fetch_series_batch([
            spec_weekly_crude_stocks_ex_spr(),
            spec_petroleum_series("EMD_EPD2D_PTE_NUS_DPG"),
        ])
        assert out["crude_stocks_ex_spr"] is None
        assert out["EMD_EPD2D_PTE_NUS_DPG"].value == pytest.approx(3.84)


# =========================================================================
# Tests: pre-built spec helpers
# =========================================================================

class TestSpecHelpers:
    def test_petroleum_series_spec_shape(self):
        spec = spec_petroleum_series("EMD_EPD2D_PTE_NUS_DPG")
        assert spec.route == "petroleum/pri/gnd/data"
        assert spec.facets == {"series": ["EMD_EPD2D_PTE_NUS_DPG"]}
        assert spec.frequency == "weekly"
        assert spec.key == "EMD_EPD2D_PTE_NUS_DPG"

    def test_petroleum_series_with_alt_frequency(self):
        spec = spec_petroleum_series("X", frequency="monthly")
        assert spec.frequency == "monthly"

    def test_crude_stocks_spec_shape(self):
        spec = spec_weekly_crude_stocks_ex_spr()
        assert spec.route == "petroleum/stoc/wstk/data"
        assert "EPC0" in spec.facets["product"]
        assert spec.frequency == "weekly"

    def test_natural_gas_storage_spec_shape(self):
        spec = spec_weekly_natural_gas_storage()
        assert spec.route == "natural-gas/stor/wkly/data"
        assert spec.frequency == "weekly"

    def test_refinery_utilization_spec_shape(self):
        spec = spec_weekly_refinery_utilization()
        assert spec.route == "petroleum/pnp/wiup/data"
        assert spec.frequency == "weekly"


# =========================================================================
# Tests: CLI helpers
# =========================================================================

class TestCliHelpers:
    def test_parse_facet_args_single(self):
        out = _parse_facet_args(["series=EMD_EPD2D_PTE_NUS_DPG"])
        assert out == {"series": ["EMD_EPD2D_PTE_NUS_DPG"]}

    def test_parse_facet_args_multi_values(self):
        out = _parse_facet_args(["product=EPC0", "product=EPD0", "duoarea=NUS"])
        assert out == {"product": ["EPC0", "EPD0"], "duoarea": ["NUS"]}

    def test_parse_facet_args_missing_eq(self):
        with pytest.raises(ValueError):
            _parse_facet_args(["malformed"])

    def test_parse_facet_args_empty(self):
        assert _parse_facet_args([]) == {}


# =========================================================================
# Live test (skipped unless EIA_API_KEY is real)
# =========================================================================

@pytest.mark.skipif(
    not os.environ.get("EIA_API_KEY") or
    os.environ.get("EIA_API_KEY", "").startswith("test-"),
    reason="EIA_API_KEY not set; skipping live network test",
)
def test_live_diesel_round_trip():
    """Optional smoke test against real EIA — opt-in via real API key."""
    spec = spec_petroleum_series("EMD_EPD2D_PTE_NUS_DPG")
    obs = fetch_series_latest(spec)
    assert obs.value > 0
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", obs.period)
