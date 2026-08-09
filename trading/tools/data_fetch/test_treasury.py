#!/usr/bin/env python3
"""
Tests for US Treasury daily yield curve fetcher.

Runs offline — _make_request is mocked at module boundary.
"""

import json
import os
import re
import sys
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from treasury import (  # noqa: E402
    CANONICAL_TENORS,
    TENOR_TO_XML,
    TREASURY_XML_BASE,
    TreasuryAPIError,
    TreasuryError,
    TreasuryNoDataError,
    YieldCurvePoint,
    _build_url,
    _parse_xml,
    compute_spread,
    fetch_latest,
    fetch_tenor_series,
    fetch_yield_curve,
)


# =========================================================================
# Helpers
# =========================================================================

def _xml_entry(date_iso: str, **tenors) -> str:
    """Build one ATOM entry for the test feed."""
    parts = [f"<d:NEW_DATE m:type=\"Edm.DateTime\">{date_iso}</d:NEW_DATE>"]
    for tenor_name, value in tenors.items():
        xml_name = TENOR_TO_XML[tenor_name]
        if value is None:
            parts.append(
                f"<d:{xml_name} m:type=\"Edm.Double\" m:null=\"true\" />"
            )
        else:
            parts.append(
                f"<d:{xml_name} m:type=\"Edm.Double\">{value}</d:{xml_name}>"
            )
    props = "".join(parts)
    return (
        "<entry>"
        "<content type=\"application/xml\">"
        f"<m:properties>{props}</m:properties>"
        "</content>"
        "</entry>"
    )


def _xml_feed(*entries) -> bytes:
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns:base="https://home.treasury.gov" '
        'xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        + "".join(entries) +
        "</feed>"
    )
    return body.encode()


# =========================================================================
# Tests: URL build
# =========================================================================

class TestBuildUrl:
    def test_default_url(self):
        url = _build_url(2026)
        assert url.startswith(TREASURY_XML_BASE)
        assert "data=daily_treasury_yield_curve" in url
        assert "field_tdr_date_value=2026" in url


# =========================================================================
# Tests: XML parsing
# =========================================================================

class TestParseXml:
    def test_single_entry_all_tenors(self):
        body = _xml_feed(_xml_entry(
            "2026-05-09T00:00:00",
            **{"1M": 4.50, "3M": 4.42, "1Y": 4.30,
               "2Y": 4.10, "5Y": 4.05, "10Y": 4.20,
               "30Y": 4.55},
        ))
        points = _parse_xml(body)
        assert len(points) == 1
        p = points[0]
        assert p.date == "2026-05-09"
        assert p.tenors["10Y"] == pytest.approx(4.20)
        assert p.tenors["2Y"] == pytest.approx(4.10)

    def test_multiple_entries_sorted_asc(self):
        body = _xml_feed(
            _xml_entry("2026-05-08T00:00:00", **{"10Y": 4.20}),
            _xml_entry("2026-05-06T00:00:00", **{"10Y": 4.18}),
            _xml_entry("2026-05-09T00:00:00", **{"10Y": 4.22}),
        )
        points = _parse_xml(body)
        assert [p.date for p in points] == [
            "2026-05-06", "2026-05-08", "2026-05-09"
        ]

    def test_missing_tenor_returns_none(self):
        # Old entries lack BC_30YEAR (early 2000s).
        body = _xml_feed(_xml_entry(
            "2026-05-09T00:00:00",
            **{"10Y": 4.20, "2Y": 4.10},
        ))
        points = _parse_xml(body)
        # Other tenors should be None, not missing
        assert points[0].tenors.get("30Y") is None
        assert points[0].tenors.get("1M") is None
        assert points[0].tenors["10Y"] == pytest.approx(4.20)

    def test_explicit_null_tenor(self):
        body = _xml_feed(_xml_entry(
            "2026-05-09T00:00:00",
            **{"10Y": 4.20, "30Y": None},
        ))
        points = _parse_xml(body)
        assert points[0].tenors["30Y"] is None
        assert points[0].tenors["10Y"] == pytest.approx(4.20)

    def test_empty_body_raises_no_data(self):
        with pytest.raises(TreasuryNoDataError):
            _parse_xml(b"")

    def test_empty_feed_raises_no_data(self):
        body = _xml_feed()
        with pytest.raises(TreasuryNoDataError):
            _parse_xml(body)

    def test_malformed_xml_raises_api_error(self):
        with pytest.raises(TreasuryAPIError):
            _parse_xml(b"<not>valid")

    def test_fetched_at_is_iso_utc(self):
        body = _xml_feed(_xml_entry(
            "2026-05-09T00:00:00", **{"10Y": 4.20}
        ))
        points = _parse_xml(body)
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", points[0].fetched_at
        )

    def test_canonical_tenors_constant_matches_map(self):
        assert set(CANONICAL_TENORS) == set(TENOR_TO_XML.keys())


# =========================================================================
# Tests: fetch + retry
# =========================================================================

class TestFetch:
    @patch("treasury._make_request")
    def test_fetch_latest_returns_max_date(self, mock_req):
        mock_req.return_value = _xml_feed(
            _xml_entry("2026-05-06T00:00:00", **{"10Y": 4.18}),
            _xml_entry("2026-05-09T00:00:00", **{"10Y": 4.22}),
        )
        latest = fetch_latest(2026)
        assert latest.date == "2026-05-09"
        assert latest.tenors["10Y"] == pytest.approx(4.22)

    @patch("treasury._make_request")
    def test_fetch_tenor_series_filters_one_tenor(self, mock_req):
        mock_req.return_value = _xml_feed(
            _xml_entry("2026-05-06T00:00:00", **{"10Y": 4.18, "2Y": 4.05}),
            _xml_entry("2026-05-08T00:00:00", **{"10Y": 4.22, "2Y": 4.10}),
        )
        series = fetch_tenor_series("2Y", 2026)
        assert series == [("2026-05-06", pytest.approx(4.05)),
                          ("2026-05-08", pytest.approx(4.10))]

    @patch("treasury._make_request")
    def test_fetch_tenor_series_skips_null(self, mock_req):
        mock_req.return_value = _xml_feed(
            _xml_entry("2026-05-06T00:00:00", **{"10Y": 4.18}),
            _xml_entry("2026-05-08T00:00:00", **{"10Y": 4.22, "30Y": None}),
        )
        series = fetch_tenor_series("30Y", 2026)
        assert series == []

    def test_invalid_tenor_raises_value_error(self):
        with pytest.raises(ValueError):
            fetch_tenor_series("99Y", 2026)

    @patch("treasury.time.sleep", lambda *_a, **_k: None)
    @patch("treasury._make_request")
    def test_5xx_then_success(self, mock_req):
        mock_req.side_effect = [
            HTTPError(url="x", code=503, msg="x", hdrs=None, fp=None),
            _xml_feed(_xml_entry("2026-05-09T00:00:00", **{"10Y": 4.22})),
        ]
        latest = fetch_latest(2026, retries=2)
        assert latest.tenors["10Y"] == pytest.approx(4.22)
        assert mock_req.call_count == 2

    @patch("treasury._make_request")
    def test_404_raises_no_retry(self, mock_req):
        mock_req.side_effect = HTTPError(
            url="x", code=404, msg="Not Found", hdrs=None, fp=None
        )
        with pytest.raises(TreasuryAPIError):
            fetch_yield_curve(1900, retries=3)
        assert mock_req.call_count == 1

    @patch("treasury.time.sleep", lambda *_a, **_k: None)
    @patch("treasury._make_request")
    def test_url_error_retries(self, mock_req):
        mock_req.side_effect = [
            URLError("dns"),
            _xml_feed(_xml_entry("2026-05-09T00:00:00", **{"10Y": 4.22})),
        ]
        latest = fetch_latest(2026, retries=2)
        assert latest.tenors["10Y"] == pytest.approx(4.22)


# =========================================================================
# Tests: spread computation
# =========================================================================

class TestComputeSpread:
    def test_positive_spread(self):
        p = YieldCurvePoint(
            date="2026-05-09",
            tenors={"10Y": 4.30, "2Y": 4.10},
        )
        bps = compute_spread(p, "10Y", "2Y")
        assert bps == pytest.approx(20.0)

    def test_negative_spread_inversion(self):
        p = YieldCurvePoint(
            date="2026-05-09",
            tenors={"10Y": 3.80, "2Y": 4.30},
        )
        bps = compute_spread(p, "10Y", "2Y")
        assert bps == pytest.approx(-50.0)

    def test_missing_long_returns_none(self):
        p = YieldCurvePoint(
            date="2026-05-09",
            tenors={"2Y": 4.10},
        )
        assert compute_spread(p, "10Y", "2Y") is None

    def test_missing_short_returns_none(self):
        p = YieldCurvePoint(
            date="2026-05-09",
            tenors={"10Y": 4.30},
        )
        assert compute_spread(p, "10Y", "2Y") is None

    def test_invalid_tenor_raises(self):
        p = YieldCurvePoint(date="2026-05-09", tenors={"10Y": 4.30})
        with pytest.raises(ValueError):
            compute_spread(p, "99Y", "2Y")


# =========================================================================
# Tests: YieldCurvePoint.to_dict
# =========================================================================

class TestPointDict:
    def test_to_dict_round_trip(self):
        p = YieldCurvePoint(
            date="2026-05-09",
            tenors={"10Y": 4.30, "2Y": 4.10},
            fetched_at="2026-05-09T18:00:00Z",
        )
        d = p.to_dict()
        assert d["date"] == "2026-05-09"
        assert d["tenors"]["10Y"] == pytest.approx(4.30)
        assert d["fetched_at"] == "2026-05-09T18:00:00Z"
        # Verify deep copy of tenors so mutations don't leak.
        d["tenors"]["10Y"] = 999
        assert p.tenors["10Y"] == pytest.approx(4.30)
