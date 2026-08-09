#!/usr/bin/env python3
"""
EIA (US Energy Information Administration) data fetcher.

Queries the EIA Open Data v2 API (https://api.eia.gov/v2/) for the latest
observation of a given series — weekly crude stocks, distillate retail
prices, natural gas storage, refinery utilization. Returns
{value: float, period: str, units: str, fetched_at: str}.

WHY this exists: iran-hormuz-graph.json wires diesel and crude-stocks nodes
to `source: "eia"` feeds, but no fetcher existed to resolve them. This
closes that gap. EIA is the primary publisher for US petroleum data —
more authoritative than Yahoo Finance for these series, and covers the
diesel cracks and weekly inventory draws the Hormuz cascade depends on.

Usage as library:
    from eia import EIASpec, fetch_series_latest, fetch_series_batch
    spec = EIASpec(
        key="diesel_retail",
        route="petroleum/pri/gnd/data",
        facets={"series": ["EMD_EPD2D_PTE_NUS_DPG"]},
        frequency="weekly",
    )
    obs = fetch_series_latest(spec)
    # {"value": 3.84, "period": "2026-05-05", "units": "$/GAL", ...}

Usage standalone:
    EIA_API_KEY=<key> python3 eia.py petroleum/pri/gnd/data \\
        --facet series=EMD_EPD2D_PTE_NUS_DPG --frequency weekly

Pattern modeled on tools/data_fetch/fred.py — stdlib urllib only, clear
error class hierarchy, source-stamped freshness, polite inter-batch
sleep, retries on transient 5xx.
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# WHY v2: EIA's Open Data v2 (rolled out 2022) uses route-based JSON with
# typed facets. The legacy v1 series-ID format still works under /v1/series/
# but is deprecated; v2 is the documented path forward.
EIA_API_BASE = "https://api.eia.gov/v2"

# WHY 20s: EIA's geospatial routes can be slow on cold cache; 20s is the
# documented soft timeout. Daily queries for petroleum series complete in
# under 2s typically.
DEFAULT_TIMEOUT = 20

# WHY 2 retries: EIA occasionally returns 502/503 during their nightly
# refresh windows (Wednesdays for petroleum series).
DEFAULT_RETRIES = 2

# WHY 0.5s base / exponential: EIA does not publish a hard rate limit but
# documents "automatic temporary suspension" on abuse. Conservative.
RETRY_BASE_DELAY = 0.5

# WHY 0.25s between batch fetches: matches fred.py and stays well under
# any reasonable rate limit interpretation.
BATCH_INTER_DELAY = 0.25

# WHY descriptive UA: same reasoning as fred.py — friendlier to EIA's logs.
_HEADERS = {"User-Agent": "Mozilla/5.0 (tradingDesk/eia-fetcher)"}


# =========================================================================
# Spec + Result types
# =========================================================================

@dataclass(frozen=True)
class EIASpec:
    """Identifies one EIA v2 query.

    Attributes:
        key: caller-chosen identifier (used as dict key in batch results).
        route: EIA v2 path segment, e.g. "petroleum/pri/gnd/data".
        facets: dict mapping facet name to list of facet values, e.g.
            {"series": ["EMD_EPD2D_PTE_NUS_DPG"]}. Multi-valued facets are
            encoded with repeated facets[k][]=v query params.
        frequency: optional EIA frequency string ("weekly", "monthly",
            "daily", "annual"). Routes have a default; specifying narrows.
        length: how many recent observations to fetch (default 1 — latest).
    """
    key: str
    route: str
    facets: Dict[str, List[str]] = field(default_factory=dict)
    frequency: Optional[str] = None
    length: int = 1


@dataclass
class EIAObservation:
    """A single EIA observation result."""
    value: float
    period: str
    units: str
    fetched_at: str

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "period": self.period,
            "units": self.units,
            "fetched_at": self.fetched_at,
        }


# =========================================================================
# Error hierarchy
# =========================================================================

class EIAError(Exception):
    """Base exception for EIA fetcher errors."""
    pass


class EIAAuthError(EIAError):
    """Raised when EIA_API_KEY is missing or rejected."""
    pass


class EIANoDataError(EIAError):
    """Raised when an EIA query returns an empty data array.

    WHY: Common on Mondays for weekly series (release is Wednesday) or on
    routes that have not yet been refreshed for the latest period. Treat
    as no-data so callers can fall back to a previous snapshot or surface
    a freshness amber instead of crashing the tick.
    """
    pass


class EIAAPIError(EIAError):
    """Raised on unexpected EIA responses (non-2xx, malformed JSON)."""
    pass


# =========================================================================
# Helpers
# =========================================================================

def _get_api_key() -> str:
    """Resolve the EIA API key from env, or raise.

    WHY explicit raise: silent skipping would hide misconfiguration in the
    coordinator tick loop. We want operators to see this error once and
    drop the key in .env, not chase ghost amber badges for weeks.
    """
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        raise EIAAuthError(
            "EIA_API_KEY is not set. Get a free key at "
            "https://www.eia.gov/opendata/register.php and export "
            "EIA_API_KEY=<key> before running --fetch."
        )
    return key


def _make_request(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """Make an HTTP GET request and return the response body.

    Isolated so tests can mock at a single point (mirrors fred.py).
    """
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _build_url(spec: EIASpec, api_key: str) -> str:
    """Build the EIA v2 query URL for a spec.

    WHY tuple list for params: EIA expects repeated facets[k][]=v keys for
    multi-valued facets. urlencode with a list-of-tuples + doseq=True
    produces the right shape; a flat dict would only allow one value
    per facet.

    WHY sort by period desc + length: combined, these give us the latest
    observation in one round-trip without scanning history.
    """
    # Base params
    params: List[tuple] = [
        ("api_key", api_key),
        ("data[]", "value"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
        ("length", str(spec.length)),
    ]

    if spec.frequency:
        params.append(("frequency", spec.frequency))

    # Facets — EIA expects facets[name][]=value, repeated for each value
    for facet_name, values in spec.facets.items():
        if not isinstance(values, (list, tuple)):
            # Tolerate a single string passed through; wrap it
            values = [values]
        for v in values:
            params.append((f"facets[{facet_name}][]", str(v)))

    # Strip leading slash on route to avoid double-slash in URL
    route = spec.route.lstrip("/")
    return f"{EIA_API_BASE}/{route}?{urlencode(params, doseq=False)}"


def _parse_response(body: bytes, spec: EIASpec) -> EIAObservation:
    """Parse an EIA v2 JSON response into an EIAObservation.

    EIA v2 response shape:
        {"response": {"data": [
            {"period": "2026-05-02", "value": "433802", "units": "MBBL", ...}
        ]}}

    WHY tolerant value parse: EIA returns numeric values as strings in
    JSON for legacy v1 compatibility. Some routes return null for
    suppressed/unavailable points — treat those as no-data.
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError) as e:
        raise EIAAPIError(
            f"EIA returned non-JSON for {spec.key} ({spec.route}): {e}"
        ) from e

    response = data.get("response")
    if not isinstance(response, dict):
        # Some error envelopes put "error" at top level
        err = data.get("error") or data.get("message")
        if err:
            raise EIAAPIError(
                f"EIA error for {spec.key}: {err}"
            )
        raise EIAAPIError(
            f"EIA response missing 'response' object for {spec.key}: {data!r}"
        )

    rows = response.get("data")
    if not isinstance(rows, list) or not rows:
        raise EIANoDataError(
            f"EIA returned no data for {spec.key} (route={spec.route}, "
            f"facets={spec.facets!r})"
        )

    # Latest observation is rows[0] because we sort by period desc
    row = rows[0]
    raw_value = row.get("value")
    period = row.get("period", "")
    units = row.get("units", "") or ""

    if raw_value is None or raw_value == "":
        raise EIANoDataError(
            f"EIA series {spec.key} has no value for period {period} "
            "(suppressed or not yet published)"
        )

    try:
        value = float(raw_value)
    except (TypeError, ValueError) as e:
        raise EIAAPIError(
            f"EIA series {spec.key} value {raw_value!r} is not a number: {e}"
        ) from e

    return EIAObservation(
        value=value,
        period=period,
        units=units,
        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# =========================================================================
# Public fetch functions
# =========================================================================

def fetch_series_latest(
    spec: EIASpec, *, retries: int = DEFAULT_RETRIES
) -> EIAObservation:
    """Fetch the most recent observation for a single EIA spec.

    Raises:
        EIAAuthError: EIA_API_KEY missing or rejected.
        EIANoDataError: route returns empty data array, or value is null.
        EIAAPIError: unexpected response (non-2xx after retries, malformed
            JSON, missing 'response' object).

    WHY no graceful None fallback: callers in the coordinator tick loop
    want to know *why* a series didn't resolve so they can mark feed
    freshness amber with the right reason code. fetch_series_batch
    handles partial-failure case.
    """
    api_key = _get_api_key()
    url = _build_url(spec, api_key)

    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            raw = _make_request(url)
            return _parse_response(raw, spec)

        except HTTPError as e:
            # 4xx is permanent — don't retry. 5xx is transient — retry.
            if 400 <= e.code < 500:
                if e.code in (401, 403):
                    raise EIAAuthError(
                        f"EIA rejected API key (HTTP {e.code}) for "
                        f"{spec.key}. Verify EIA_API_KEY is correct."
                    ) from e
                raise EIAAPIError(
                    f"EIA returned HTTP {e.code} for {spec.key} "
                    f"({spec.route}): {e.reason}"
                ) from e
            last_error = e
        except (URLError, TimeoutError, OSError) as e:
            last_error = e
        except EIANoDataError:
            raise
        except EIAAPIError:
            raise

        if attempt < retries:
            sleep_for = RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"  eia: retry {attempt + 1}/{retries} for {spec.key} "
                f"after {last_error!r}, sleeping {sleep_for:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)

    raise EIAAPIError(
        f"EIA fetch failed for {spec.key} after {retries + 1} attempts: "
        f"{last_error!r}"
    )


def fetch_series_batch(
    specs: List[EIASpec], *, retries: int = DEFAULT_RETRIES
) -> Dict[str, Optional[EIAObservation]]:
    """Fetch the latest observation for multiple EIA specs.

    Returns a dict mapping spec.key -> EIAObservation (or None on failure).
    Failed fetches yield None values and are logged to stderr; the batch
    never crashes on a single bad spec.

    WHY return None vs omit (differs from fred.py): EIA specs are richer
    than series IDs — the caller often wants to surface "I asked for X
    and it failed" rather than discover via dict-membership. None is
    explicit. Callers iterate `for k, v in results.items() if v is not None`.
    """
    if not specs:
        return {}

    # Validate auth up front so we fail loud once if FRED_API_KEY is missing.
    _get_api_key()

    results: Dict[str, Optional[EIAObservation]] = {}

    for i, spec in enumerate(specs):
        try:
            results[spec.key] = fetch_series_latest(spec, retries=retries)
        except EIANoDataError as e:
            print(f"  eia: {spec.key} -> no data ({e})", file=sys.stderr)
            results[spec.key] = None
        except EIAAPIError as e:
            print(f"  eia: {spec.key} -> api error ({e})", file=sys.stderr)
            results[spec.key] = None
        except EIAError as e:
            print(f"  eia: {spec.key} -> {e}", file=sys.stderr)
            results[spec.key] = None

        if i < len(specs) - 1:
            time.sleep(BATCH_INTER_DELAY)

    return results


# =========================================================================
# Standard specs — pre-built for common thesis-graph nodes
# =========================================================================

# WHY pre-built specs: book JSON references abstract sources like
# `{"source": "eia", "series": "EMD_EPD2D_PTE_NUS_DPG"}`. The thesisgraph
# --fetch dispatcher uses these helpers (or builds an EIASpec inline) to
# turn that into a concrete v2 query. Maintained here so series additions
# require touching only one file.

def spec_petroleum_series(series_id: str, frequency: str = "weekly") -> EIASpec:
    """Build a spec for EIA's petroleum 'series' facet.

    Used for diesel retail (EMD_EPD2D_PTE_NUS_DPG), gasoline retail, etc.
    """
    return EIASpec(
        key=series_id,
        route="petroleum/pri/gnd/data",
        facets={"series": [series_id]},
        frequency=frequency,
    )


def spec_weekly_crude_stocks_ex_spr() -> EIASpec:
    """Weekly US crude oil stocks excluding SPR, in thousand barrels."""
    return EIASpec(
        key="crude_stocks_ex_spr",
        route="petroleum/stoc/wstk/data",
        facets={"product": ["EPC0"], "duoarea": ["NUS"]},
        frequency="weekly",
    )


def spec_weekly_natural_gas_storage() -> EIASpec:
    """Weekly US natural gas underground storage, in BCF."""
    return EIASpec(
        key="ng_storage",
        route="natural-gas/stor/wkly/data",
        facets={"duoarea": ["NUS"]},
        frequency="weekly",
    )


def spec_weekly_refinery_utilization() -> EIASpec:
    """Weekly US refinery utilization rate, percent."""
    return EIASpec(
        key="refinery_utilization",
        route="petroleum/pnp/wiup/data",
        facets={"duoarea": ["NUS"]},
        frequency="weekly",
    )


# =========================================================================
# CLI — standalone usage for debugging / manual checks
# =========================================================================

def _parse_facet_args(facet_args: List[str]) -> Dict[str, List[str]]:
    """Parse --facet key=value flags into a facets dict.

    Multi-valued facets are expressed by repeating --facet, e.g.
    `--facet product=EPC0 --facet product=EPD0`.
    """
    facets: Dict[str, List[str]] = {}
    for arg in facet_args:
        if "=" not in arg:
            raise ValueError(f"--facet expects key=value, got {arg!r}")
        k, v = arg.split("=", 1)
        facets.setdefault(k, []).append(v)
    return facets


def main() -> None:
    """Fetch and print latest observation for a given EIA route + facets."""
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: EIA_API_KEY=<key> eia.py <route> "
            "[--facet key=value]... [--frequency weekly] [--length N] [--json]",
            file=sys.stderr,
        )
        print(
            "Routes: petroleum/pri/gnd/data, petroleum/stoc/wstk/data, "
            "natural-gas/stor/wkly/data, petroleum/pnp/wiup/data",
            file=sys.stderr,
        )
        print(
            "Example: eia.py petroleum/pri/gnd/data "
            "--facet series=EMD_EPD2D_PTE_NUS_DPG --frequency weekly",
            file=sys.stderr,
        )
        sys.exit(0 if args and args[0] in ("-h", "--help") else 1)

    route = args[0]
    facet_args: List[str] = []
    frequency: Optional[str] = None
    length = 1
    output_json = False

    i = 1
    while i < len(args):
        a = args[i]
        if a == "--facet" and i + 1 < len(args):
            facet_args.append(args[i + 1])
            i += 2
        elif a == "--frequency" and i + 1 < len(args):
            frequency = args[i + 1]
            i += 2
        elif a == "--length" and i + 1 < len(args):
            length = int(args[i + 1])
            i += 2
        elif a == "--json":
            output_json = True
            i += 1
        else:
            print(f"  ERROR: unknown arg {a!r}", file=sys.stderr)
            sys.exit(1)

    try:
        facets = _parse_facet_args(facet_args)
    except ValueError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    spec = EIASpec(
        key=route,
        route=route,
        facets=facets,
        frequency=frequency,
        length=length,
    )

    try:
        obs = fetch_series_latest(spec)
    except EIAAuthError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except EIANoDataError as e:
        print(f"  NO DATA: {e}", file=sys.stderr)
        sys.exit(1)
    except EIAAPIError as e:
        print(f"  API ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if output_json:
        print(json.dumps(obs.to_dict(), indent=2))
    else:
        print(
            f"  {route}: {obs.value} {obs.units} "
            f"({obs.period}, fetched {obs.fetched_at})"
        )


if __name__ == "__main__":
    main()
