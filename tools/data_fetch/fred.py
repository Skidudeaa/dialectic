#!/usr/bin/env python3
"""
FRED (Federal Reserve Economic Data) macro series fetcher.

Queries the FRED API (https://api.stlouisfed.org/fred) for the latest
observation of a given series (e.g. DGS10 for US 10Y Treasury). Returns
{value: float, observation_date: str, fetched_at: str}.

WHY this exists: the thesis graph engine seeds japan-rate-shock and
china-property-cascade books with hand-typed Treasury yields / FX rates /
policy-rate proxies. Those theses can't resolve their own gates without a
live macro feed. FRED gives free stdlib-only access to ~800k macro series
once the operator drops a free API key into FRED_API_KEY.

Usage as library:
    from fred import fetch_series_latest, fetch_series_batch
    obs = fetch_series_latest("DGS10")
    # {"value": 4.35, "observation_date": "2026-04-23",
    #  "fetched_at": "2026-04-24T..."}

    batch = fetch_series_batch(["DGS10", "DEXJPUS"])
    # {"DGS10": {...}, "DEXJPUS": {...}}

Usage standalone:
    FRED_API_KEY=<key> python3 fred.py DGS10 DEXJPUS

Pattern modeled on tools/data_fetch/polymarket.py — stdlib urllib only,
clear error class hierarchy, source-stamped freshness, polite inter-batch
sleep, retries on transient 5xx.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# WHY observations endpoint: FRED's /fred/series/observations endpoint with
# sort_order=desc + limit=1 gives us the most recent observation in one
# round-trip without parsing a full series. We never need history at this
# layer — derived_indicators handles the OHLCV story for nodes that need it.
FRED_API_BASE = "https://api.stlouisfed.org/fred"

# WHY 15s: macro series don't move fast enough to need aggressive timeouts,
# but we don't want to block the graph generator for minutes if FRED is down.
DEFAULT_TIMEOUT = 15

# WHY 2 retries: transient 5xx (FRED occasionally bounces during their
# nightly refresh windows). Two retries with backoff handles most cases.
DEFAULT_RETRIES = 2

# WHY 0.5s base / exponential: FRED publishes a soft 120 req/min quota for
# free keys. 0.5s base × 2^attempt keeps us comfortably under that even
# under retry pressure.
RETRY_BASE_DELAY = 0.5

# WHY 0.25s between batch fetches: matches the prompt requirement and stays
# polite under FRED's 120/min quota. fetch_series_batch is the only batch
# entrypoint, so this is where we throttle.
BATCH_INTER_DELAY = 0.25

# WHY User-Agent: FRED accepts the default Python urllib UA but downstream
# proxies (Cloudflare in front of api.stlouisfed.org) sometimes flag it.
# A descriptive UA is friendlier to FRED's logs and easier to debug.
_HEADERS = {"User-Agent": "Mozilla/5.0 (tradingDesk/fred-fetcher)"}


class FredError(Exception):
    """Base exception for FRED fetcher errors."""
    pass


class FredAuthError(FredError):
    """Raised when FRED_API_KEY is missing or invalid."""
    pass


class FredNoDataError(FredError):
    """Raised when a series has no observation, or only a '.' sentinel.

    WHY: FRED uses the literal string "." in the value field to indicate a
    missing observation (banking holidays, weekends for daily series, data
    not yet published). Treat this as no-data so callers can decide whether
    to fall back, skip, or surface a freshness amber.
    """
    pass


class FredAPIError(FredError):
    """Raised on unexpected FRED responses (non-2xx, malformed JSON)."""
    pass


def _get_api_key() -> str:
    """Resolve the FRED API key from env, or raise.

    WHY explicit raise: silent skipping would hide misconfiguration in the
    coordinator tick loop. We want operators to see this error once and
    drop the key in .env, not chase ghost amber badges for weeks.
    """
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise FredAuthError(
            "FRED_API_KEY is not set. Get a free key at "
            "https://fred.stlouisfed.org/docs/api/api_key.html and export "
            "FRED_API_KEY=<key> before running --fetch."
        )
    return key


def _make_request(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """Make an HTTP GET request and return the response body.

    WHY separate function: isolates the HTTP plumbing so tests can mock at
    a single point. Mirrors the polymarket.py pattern.
    """
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _build_observations_url(series_id: str, api_key: str) -> str:
    """Build the FRED observations URL for the latest data point.

    WHY query params: FRED uses standard query strings. urlencode handles
    escaping for series IDs that contain unusual characters (rare but
    possible — some international series IDs have parentheses).
    """
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": "1",
    }
    return f"{FRED_API_BASE}/series/observations?{urlencode(params)}"


def fetch_series_latest(series_id: str, *, retries: int = DEFAULT_RETRIES) -> dict:
    """Fetch the most recent observation for a single FRED series.

    Returns:
        {
            "value": float,
            "observation_date": "YYYY-MM-DD",
            "fetched_at": "YYYY-MM-DDTHH:MM:SSZ",
        }

    Raises:
        FredAuthError: FRED_API_KEY missing.
        FredNoDataError: series has no observation, or value is the FRED
            "." sentinel (no data published yet).
        FredAPIError: unexpected response (non-2xx after retries, malformed
            JSON, missing observations array).

    WHY no graceful None fallback (unlike polymarket.fetch_single_market):
    callers in the coordinator tick loop want to know *why* a series didn't
    resolve so they can mark feed-freshness amber with the right reason
    code. fetch_series_batch handles the partial-failure case.
    """
    api_key = _get_api_key()
    url = _build_observations_url(series_id, api_key)

    last_error: Optional[Exception] = None

    # WHY attempt loop: total attempts = retries + 1 (initial + retries).
    # We retry only on transient network / 5xx errors. 4xx (auth, bad
    # series ID) is permanent — fail fast.
    for attempt in range(retries + 1):
        try:
            raw = _make_request(url)
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as e:
                raise FredAPIError(
                    f"FRED returned non-JSON for {series_id}: {e}"
                ) from e

            observations = data.get("observations")
            if not isinstance(observations, list) or not observations:
                raise FredNoDataError(
                    f"FRED returned no observations for {series_id}"
                )

            obs = observations[0]
            raw_value = obs.get("value")
            obs_date = obs.get("date", "")

            # WHY "." sentinel: FRED encodes "no value yet" as the literal
            # string ".". This is documented behavior — ignore-on-sight, do
            # NOT attempt to float() it (would raise ValueError but with
            # less helpful wording).
            if raw_value == "." or raw_value is None or raw_value == "":
                raise FredNoDataError(
                    f"FRED series {series_id} has no value for {obs_date} "
                    "(probably weekend / holiday / not-yet-published)"
                )

            try:
                value = float(raw_value)
            except (TypeError, ValueError) as e:
                raise FredAPIError(
                    f"FRED series {series_id} value {raw_value!r} is not a "
                    f"number: {e}"
                ) from e

            return {
                "value": value,
                "observation_date": obs_date,
                "fetched_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }

        except HTTPError as e:
            # WHY 4xx vs 5xx: 4xx is a permanent failure (bad key, bad
            # series, malformed query) — retrying won't help, raise now.
            # 5xx is transient (FRED maintenance, gateway hiccup) — retry.
            if 400 <= e.code < 500:
                if e.code in (401, 403):
                    raise FredAuthError(
                        f"FRED rejected API key (HTTP {e.code}) for "
                        f"{series_id}. Verify FRED_API_KEY is correct."
                    ) from e
                raise FredAPIError(
                    f"FRED returned HTTP {e.code} for {series_id}: {e.reason}"
                ) from e
            last_error = e
        except (URLError, TimeoutError, OSError) as e:
            last_error = e
        except FredNoDataError:
            # Permanent — don't retry, just propagate.
            raise
        except FredAPIError:
            raise

        # If we reach here, we have a transient failure to retry.
        if attempt < retries:
            sleep_for = RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"  fred: retry {attempt + 1}/{retries} for {series_id} "
                f"after {last_error!r}, sleeping {sleep_for:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)

    # WHY: all retries exhausted on transient failure
    raise FredAPIError(
        f"FRED fetch failed for {series_id} after {retries + 1} attempts: "
        f"{last_error!r}"
    )


def fetch_series_batch(
    series_ids: List[str], *, retries: int = DEFAULT_RETRIES
) -> Dict[str, dict]:
    """Fetch the latest observation for multiple FRED series.

    Returns a dict mapping series_id -> observation dict. Failed fetches
    are *omitted* from the returned dict (and logged to stderr) so callers
    can iterate over what succeeded without sentinel-checking.

    WHY skip-on-failure (unlike fetch_series_latest's raise behavior): the
    batch wrapper is the coordinator's tick-loop entrypoint. One bad series
    ID in a 12-series book shouldn't take down the whole tick. The single
    fetcher raises so unit tests / direct callers get the real reason; the
    batch fetcher logs and continues so the live system stays alive.

    Sleeps BATCH_INTER_DELAY between fetches to stay polite under the
    120/min quota.
    """
    results: Dict[str, dict] = {}

    # WHY validate up front: if FRED_API_KEY is missing, fail loud once
    # rather than once per series. Calls _get_api_key() so the auth check
    # happens before any HTTP request.
    try:
        _get_api_key()
    except FredAuthError:
        # Re-raise — this is a config problem, not a per-series problem.
        raise

    for i, series_id in enumerate(series_ids):
        try:
            results[series_id] = fetch_series_latest(series_id, retries=retries)
        except FredNoDataError as e:
            print(f"  fred: {series_id} -> no data ({e})", file=sys.stderr)
        except FredAPIError as e:
            print(f"  fred: {series_id} -> api error ({e})", file=sys.stderr)
        except FredError as e:
            print(f"  fred: {series_id} -> {e}", file=sys.stderr)

        # WHY skip last sleep: nothing waits after the final fetch.
        if i < len(series_ids) - 1:
            time.sleep(BATCH_INTER_DELAY)

    return results


# =========================================================================
# CLI — standalone usage for debugging / manual checks
# =========================================================================

def main() -> None:
    """Fetch and print latest observations for given series IDs."""
    if len(sys.argv) < 2:
        print(
            "Usage: FRED_API_KEY=<key> fred.py <series_id> [series_id...] "
            "[--json]",
            file=sys.stderr,
        )
        print("Example: fred.py DGS10 DEXJPUS", file=sys.stderr)
        sys.exit(1)

    output_json = "--json" in sys.argv
    series_ids = [s for s in sys.argv[1:] if not s.startswith("--")]

    try:
        results = fetch_series_batch(series_ids)
    except FredAuthError as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    if output_json:
        print(json.dumps(results, indent=2))
    else:
        for sid in series_ids:
            obs = results.get(sid)
            if obs is None:
                print(f"  {sid}: FAILED (no data)")
            else:
                print(
                    f"  {sid}: {obs['value']} "
                    f"({obs['observation_date']}, fetched {obs['fetched_at']})"
                )

    if not results:
        sys.exit(1)


if __name__ == "__main__":
    main()
