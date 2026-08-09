#!/usr/bin/env python3
"""
US Treasury daily yield curve fetcher.

Pulls the official Treasury XML feed for the daily Treasury yield curve
("CMT" rates) and extracts per-tenor yields plus curve spreads.

Source: https://home.treasury.gov/resource-center/data-chart-center/
        interest-rates/pages/xml?data=daily_treasury_yield_curve
        &field_tdr_date_value={year}

WHY this exists: japan-rate-shock + trump-tariffs + china-property-cascade
all reference recession-risk through Treasury curve dynamics. FRED carries
the underlying tenors but with daily lag; Treasury's own XML is updated by
~6pm ET the same day. Curve spreads (10Y-2Y, 10Y-3M) are direct inputs to
the recession-risk nodes.

Usage as library:
    from treasury import fetch_yield_curve, fetch_latest, compute_spread
    points = fetch_yield_curve(2026)
    latest = fetch_latest()
    spread_bps = compute_spread(latest, "10Y", "2Y")  # basis points

Usage standalone:
    python3 treasury.py --latest
    python3 treasury.py --year 2026 --tenor 10Y
"""

import json
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TREASURY_XML_BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml"
)

DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 2
RETRY_BASE_DELAY = 0.5

_HEADERS = {"User-Agent": "Mozilla/5.0 (tradingDesk/treasury-fetcher)"}

# WHY namespaces dict: ATOM XML uses two namespaces — Microsoft's ADO
# dataservices for the field elements (`d:`) and metadata (`m:`). ET's
# findall needs the URI form for namespaced lookups.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
}

# Canonical tenor names → XML element local names (without `d:` prefix).
# WHY explicit map: keeps the public API ("10Y", "2Y") stable even if
# Treasury renames XML elements. 1.5M is excluded — it's the rare 6-week
# bill added Feb 2025 and not present in older points.
TENOR_TO_XML: Dict[str, str] = {
    "1M": "BC_1MONTH",
    "2M": "BC_2MONTH",
    "3M": "BC_3MONTH",
    "4M": "BC_4MONTH",
    "6M": "BC_6MONTH",
    "1Y": "BC_1YEAR",
    "2Y": "BC_2YEAR",
    "3Y": "BC_3YEAR",
    "5Y": "BC_5YEAR",
    "7Y": "BC_7YEAR",
    "10Y": "BC_10YEAR",
    "20Y": "BC_20YEAR",
    "30Y": "BC_30YEAR",
}

CANONICAL_TENORS: Tuple[str, ...] = tuple(TENOR_TO_XML.keys())


# =========================================================================
# Types
# =========================================================================

@dataclass
class YieldCurvePoint:
    """One Treasury yield curve observation (one trading day)."""
    date: str  # YYYY-MM-DD
    tenors: Dict[str, Optional[float]] = field(default_factory=dict)
    fetched_at: str = ""

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "tenors": dict(self.tenors),
            "fetched_at": self.fetched_at,
        }


# =========================================================================
# Errors
# =========================================================================

class TreasuryError(Exception):
    """Base exception for Treasury fetcher errors."""
    pass


class TreasuryNoDataError(TreasuryError):
    """Raised when the XML feed contains no entries (year not yet started)."""
    pass


class TreasuryAPIError(TreasuryError):
    """Raised on unexpected Treasury responses (non-2xx, malformed XML)."""
    pass


# =========================================================================
# HTTP + parsing
# =========================================================================

def _make_request(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _build_url(year: int) -> str:
    """Build Treasury XML feed URL for a given year."""
    params = {
        "data": "daily_treasury_yield_curve",
        "field_tdr_date_value": str(year),
    }
    return f"{TREASURY_XML_BASE}?{urlencode(params)}"


def _parse_xml(body: bytes) -> List[YieldCurvePoint]:
    """Parse Treasury ATOM XML feed into a list of YieldCurvePoint, asc.

    WHY date asc: callers (compute_spread, fetch_latest) prefer chronological
    order. The feed itself is asc in practice but we sort defensively.
    """
    if not body or not body.strip():
        raise TreasuryNoDataError("Treasury XML feed returned empty body")

    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise TreasuryAPIError(
            f"Treasury XML parse error: {e}"
        ) from e

    # Each entry contains <m:properties> with <d:NEW_DATE> + <d:BC_*>.
    # The properties live inside content/m:properties.
    points: List[YieldCurvePoint] = []
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for entry in root.findall("atom:entry", _NS):
        props = entry.find("atom:content/m:properties", _NS)
        if props is None:
            continue

        date_el = props.find("d:NEW_DATE", _NS)
        if date_el is None or not (date_el.text or "").strip():
            continue
        # NEW_DATE is e.g. "2026-05-09T00:00:00" — keep just the date part.
        date_str = date_el.text.strip().split("T")[0]

        tenors: Dict[str, Optional[float]] = {}
        for tenor_name, xml_name in TENOR_TO_XML.items():
            el = props.find(f"d:{xml_name}", _NS)
            if el is None or el.text is None or not el.text.strip():
                tenors[tenor_name] = None
                continue
            try:
                tenors[tenor_name] = float(el.text.strip())
            except (TypeError, ValueError):
                tenors[tenor_name] = None

        points.append(YieldCurvePoint(
            date=date_str, tenors=tenors, fetched_at=fetched_at,
        ))

    if not points:
        raise TreasuryNoDataError(
            "Treasury XML feed contained no parseable entries"
        )

    points.sort(key=lambda p: p.date)
    return points


def _fetch_with_retry(
    year: int, *, retries: int = DEFAULT_RETRIES
) -> List[YieldCurvePoint]:
    url = _build_url(year)
    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            raw = _make_request(url)
            return _parse_xml(raw)
        except HTTPError as e:
            if 400 <= e.code < 500:
                raise TreasuryAPIError(
                    f"Treasury returned HTTP {e.code} for year {year}: "
                    f"{e.reason}"
                ) from e
            last_error = e
        except (URLError, TimeoutError, OSError) as e:
            last_error = e
        except (TreasuryNoDataError, TreasuryAPIError):
            raise

        if attempt < retries:
            sleep_for = RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"  treasury: retry {attempt + 1}/{retries} for year {year} "
                f"after {last_error!r}, sleeping {sleep_for:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)

    raise TreasuryAPIError(
        f"Treasury fetch failed for year {year} after {retries + 1} "
        f"attempts: {last_error!r}"
    )


# =========================================================================
# Public API
# =========================================================================

def fetch_yield_curve(
    year: Optional[int] = None, *, retries: int = DEFAULT_RETRIES
) -> List[YieldCurvePoint]:
    """Fetch all daily Treasury yield curve points for a year.

    Args:
        year: 4-digit year. Defaults to current year (UTC).
        retries: number of retries on transient failures.

    Returns:
        List of YieldCurvePoint sorted by date ascending.
    """
    if year is None:
        year = datetime.now(timezone.utc).year
    return _fetch_with_retry(year, retries=retries)


def fetch_latest(
    year: Optional[int] = None, *, retries: int = DEFAULT_RETRIES
) -> YieldCurvePoint:
    """Fetch the most recent yield curve point for the given year."""
    points = fetch_yield_curve(year, retries=retries)
    if not points:
        raise TreasuryNoDataError("No yield curve points available")
    return points[-1]


def fetch_tenor_series(
    tenor: str, year: Optional[int] = None,
    *, retries: int = DEFAULT_RETRIES,
) -> List[Tuple[str, float]]:
    """Extract one tenor's daily series for a year.

    Args:
        tenor: canonical tenor name like "10Y" or "2Y".
        year: 4-digit year. Default current year.

    Returns:
        List of (date_str, value) tuples for dates where the tenor has a
        non-null value, sorted by date asc.

    Raises:
        ValueError: if tenor is not a canonical name.
    """
    if tenor not in TENOR_TO_XML:
        raise ValueError(
            f"Invalid tenor {tenor!r}; must be one of {CANONICAL_TENORS}"
        )
    points = fetch_yield_curve(year, retries=retries)
    series: List[Tuple[str, float]] = []
    for p in points:
        v = p.tenors.get(tenor)
        if v is not None:
            series.append((p.date, v))
    return series


def compute_spread(
    point: YieldCurvePoint, long_tenor: str, short_tenor: str,
) -> Optional[float]:
    """Compute curve spread (long - short) in basis points.

    Returns None if either tenor is missing for the point.

    WHY basis points: the recession-risk nodes use bps thresholds (e.g.
    "T10Y2Y < -50bps fires inversion"). Returning percentage points
    would force every caller to multiply by 100.
    """
    if long_tenor not in TENOR_TO_XML or short_tenor not in TENOR_TO_XML:
        raise ValueError(
            f"Invalid tenor; must be one of {CANONICAL_TENORS}"
        )
    long_val = point.tenors.get(long_tenor)
    short_val = point.tenors.get(short_tenor)
    if long_val is None or short_val is None:
        return None
    return (long_val - short_val) * 100.0


# =========================================================================
# CLI
# =========================================================================

def _print_curve(point: YieldCurvePoint, output_json: bool) -> None:
    if output_json:
        print(json.dumps(point.to_dict(), indent=2))
        return
    print(f"  Treasury yield curve {point.date} (fetched {point.fetched_at})")
    for tenor in CANONICAL_TENORS:
        v = point.tenors.get(tenor)
        if v is None:
            print(f"    {tenor}: --")
        else:
            print(f"    {tenor}: {v:.2f}%")


def _print_series(
    tenor: str, series: List[Tuple[str, float]], output_json: bool,
) -> None:
    if output_json:
        print(json.dumps([
            {"date": d, "value": v} for d, v in series
        ], indent=2))
        return
    print(f"  Treasury {tenor} daily series ({len(series)} points)")
    for date_str, value in series[-20:]:
        print(f"    {date_str}: {value:.2f}%")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(
            "Usage: treasury.py [--year YYYY] [--latest | --tenor 10Y] "
            "[--spread 10Y,2Y] [--json]",
            file=sys.stderr,
        )
        print("  --latest   fetch latest curve point (default)", file=sys.stderr)
        print("  --tenor T  fetch single tenor's full year series", file=sys.stderr)
        print("  --spread A,B  print A-B spread in bps from latest point",
              file=sys.stderr)
        sys.exit(0)

    year: Optional[int] = None
    tenor: Optional[str] = None
    spread: Optional[str] = None
    show_latest = False
    output_json = "--json" in args

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--year" and i + 1 < len(args):
            year = int(args[i + 1])
            i += 2
        elif a == "--tenor" and i + 1 < len(args):
            tenor = args[i + 1]
            i += 2
        elif a == "--spread" and i + 1 < len(args):
            spread = args[i + 1]
            i += 2
        elif a == "--latest":
            show_latest = True
            i += 1
        elif a == "--json":
            i += 1
        else:
            print(f"  ERROR: unknown arg {a!r}", file=sys.stderr)
            sys.exit(1)

    try:
        if tenor:
            series = fetch_tenor_series(tenor, year)
            _print_series(tenor, series, output_json)
        elif spread:
            try:
                long_t, short_t = spread.split(",")
            except ValueError:
                print(
                    "  ERROR: --spread expects 'LONG,SHORT' (e.g. 10Y,2Y)",
                    file=sys.stderr,
                )
                sys.exit(1)
            point = fetch_latest(year)
            bps = compute_spread(point, long_t.strip(), short_t.strip())
            if output_json:
                print(json.dumps({
                    "date": point.date,
                    "spread": f"{long_t}-{short_t}",
                    "bps": bps,
                }, indent=2))
            else:
                if bps is None:
                    print(f"  {long_t}-{short_t}: -- (missing tenor)")
                else:
                    print(
                        f"  {long_t}-{short_t} on {point.date}: {bps:+.1f} bps"
                    )
        else:
            # Default: latest curve.
            point = fetch_latest(year)
            _print_curve(point, output_json)
    except TreasuryNoDataError as e:
        print(f"  NO DATA: {e}", file=sys.stderr)
        sys.exit(1)
    except TreasuryAPIError as e:
        print(f"  API ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
