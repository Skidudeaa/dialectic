#!/usr/bin/env python3
"""
Polymarket prediction market data fetcher.

Queries the Polymarket Gamma API (no auth required for reads) to fetch
outcome probabilities for prediction markets. Returns probabilities as
floats (0-1) keyed by market slug.

WHY this exists: The thesis graph engine needs live prediction market
probabilities to update event nodes (e.g. Hormuz closure probability).
Yahoo Finance handles price feeds; this module handles probability feeds.

Usage as library:
    from polymarket import fetch_markets, fetch_single_market
    probs = fetch_markets(["us-iran-april-30", "trump-tariffs-q2"])

Usage standalone:
    python3 polymarket.py us-iran-april-30 trump-tariffs-q2
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# WHY gamma-api: This is Polymarket's public read API. No auth needed.
# The CLOB API also works but is paginated and heavier — gamma-api gives
# us everything we need (slug lookup, outcomePrices) in fewer calls.
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# WHY 15s: prediction market prices don't move fast enough to need
# aggressive timeouts, but we don't want to block the graph generator
# for minutes if Polymarket is down.
DEFAULT_TIMEOUT = 15

# WHY 2 retries: transient failures (CDN blips, rate limits) are common
# with public APIs. Two retries with backoff handles most cases without
# being obnoxious.
DEFAULT_RETRIES = 2

# WHY 1.5s: stay well under any rate limit. Polymarket doesn't publish
# rate limits for gamma-api, so we're conservative. This matches the
# Yahoo fetcher's inter-batch delay.
RETRY_DELAY = 1.5

# WHY User-Agent: some CDNs/WAFs reject requests with no User-Agent
# or with Python's default "Python-urllib/3.x". A browser-like UA
# avoids silent 403s.
_HEADERS = {"User-Agent": "Mozilla/5.0 (tradingDesk/polymarket-fetcher)"}


class PolymarketError(Exception):
    """Base exception for Polymarket fetcher errors."""
    pass


class MarketNotFoundError(PolymarketError):
    """Raised when a market slug matches nothing in the API."""
    pass


class APIError(PolymarketError):
    """Raised when the API returns an unexpected response."""
    pass


def _make_request(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """Make an HTTP GET request and return the response body.

    WHY separate function: isolates the HTTP plumbing so tests can mock
    at a single point. Also centralizes User-Agent and timeout handling.
    """
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_outcome_prices(raw_prices: str, outcomes: list) -> Optional[float]:
    """Extract the 'Yes' outcome probability from Polymarket's response.

    WHY: Polymarket stores outcome prices as a JSON-encoded string array
    like '["0.685", "0.315"]' paired with an outcomes array like
    '["Yes", "No"]'. We want the probability of the 'Yes' outcome,
    which is how prediction markets express event likelihood.

    Returns None if parsing fails (malformed data, missing Yes outcome).
    """
    try:
        prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(prices, list) or not isinstance(outcomes, list):
        return None

    # WHY case-insensitive: API data isn't always consistent with casing
    for i, outcome in enumerate(outcomes):
        if isinstance(outcome, str) and outcome.lower() == "yes" and i < len(prices):
            try:
                prob = float(prices[i])
                # WHY bounds check: probabilities must be 0-1. If the API
                # returns something outside this range, the data is corrupt.
                if 0.0 <= prob <= 1.0:
                    return prob
                return None
            except (ValueError, TypeError):
                return None

    return None


def _search_events(query: str, timeout: int = DEFAULT_TIMEOUT) -> list:
    """Search Polymarket events by slug or keyword.

    WHY events endpoint: events group related markets (e.g. "US Iran
    Conflict" contains sub-markets for different dates). Searching
    events first gives us better context than going straight to markets.
    """
    # WHY slug param: the gamma-api supports direct slug lookup which is
    # exact-match and fast. We try this first before falling back to
    # broader search.
    from urllib.parse import quote
    url = f"{GAMMA_API_BASE}/events?slug={quote(query, safe='')}"
    data = _make_request(url, timeout=timeout)
    results = json.loads(data)

    # WHY: gamma-api returns a list for slug queries. If empty, the slug
    # didn't match — caller should try the markets endpoint directly.
    if isinstance(results, list):
        return results
    return []


def _search_markets(query: str, timeout: int = DEFAULT_TIMEOUT) -> list:
    """Search Polymarket markets directly by slug.

    WHY separate from events: some markets exist standalone without an
    event wrapper. Also, the market slug namespace is different from the
    event slug namespace — a user might have either.
    """
    from urllib.parse import quote
    url = f"{GAMMA_API_BASE}/markets?slug={quote(query, safe='')}&active=true&closed=false"
    data = _make_request(url, timeout=timeout)
    results = json.loads(data)

    if isinstance(results, list):
        return results
    # WHY: some API responses wrap results in a dict with a key like
    # "data" or return a single market object instead of a list.
    if isinstance(results, dict):
        if "data" in results:
            return results["data"] if isinstance(results["data"], list) else [results["data"]]
        # Single market object returned
        if "slug" in results or "question" in results:
            return [results]
    return []


def _extract_probability_from_market(market: dict) -> Optional[float]:
    """Extract Yes probability from a single market object.

    WHY: market objects can carry probability in several fields depending
    on the API version and market type. We check them in priority order.
    """
    # Primary: outcomePrices paired with outcomes
    outcome_prices = market.get("outcomePrices")
    outcomes = market.get("outcomes")
    if outcome_prices and outcomes:
        # WHY: outcomes may be a JSON string or already a list
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except (json.JSONDecodeError, TypeError):
                outcomes = None
        if outcomes:
            prob = _parse_outcome_prices(outcome_prices, outcomes)
            if prob is not None:
                return prob

    # Fallback: some market objects have a direct 'outcomePrices' as
    # pre-parsed floats, or a 'bestBid' / 'lastTradePrice' field
    for fallback_key in ("bestBid", "lastTradePrice", "lastPrice"):
        val = market.get(fallback_key)
        if val is not None:
            try:
                prob = float(val)
                if 0.0 <= prob <= 1.0:
                    return prob
            except (ValueError, TypeError):
                continue

    return None


def _match_market_in_results(results: list, slug: str) -> Optional[dict]:
    """Find the best matching market from search results.

    WHY: search results may contain multiple markets. We prefer exact
    slug matches, then fall back to substring matching on the question
    text. This handles cases where the user's slug is close but not
    exact (e.g. "us-iran" matching "us-iran-april-30").
    """
    # WHY: normalize slug for comparison — strip whitespace, lowercase
    slug_lower = slug.lower().strip()

    # Pass 1: exact slug match
    for market in results:
        market_slug = market.get("slug", "")
        if isinstance(market_slug, str) and market_slug.lower() == slug_lower:
            return market

    # Pass 2: slug contains our query (broader match)
    for market in results:
        market_slug = market.get("slug", "")
        if isinstance(market_slug, str) and slug_lower in market_slug.lower():
            return market

    # Pass 3: question text contains our query terms
    # WHY: users may search by concept ("iran") not exact slug
    query_terms = slug_lower.replace("-", " ").split()
    for market in results:
        question = market.get("question", "").lower()
        if all(term in question for term in query_terms):
            return market

    return None


def fetch_single_market(
    slug: str,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    raise_on_error: bool = False,
) -> Tuple[str, Optional[float]]:
    """Fetch probability for a single market by slug.

    Returns (slug, probability) where probability is None on failure. Existing
    batch callers keep the best-effort behavior; service callers may request
    APIError so an outage cannot be mislabeled as a genuine empty result.

    WHY tuple return: the caller needs to know which slug this result
    is for, especially when fetching multiple markets in parallel.
    """
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            matched_invalid = False
            # Strategy 1: search events (markets grouped under events)
            events = _search_events(slug, timeout=timeout)
            for event in events:
                # WHY: events contain nested markets in a 'markets' array
                sub_markets = event.get("markets", [])
                matched = _match_market_in_results(sub_markets, slug)
                if matched:
                    prob = _extract_probability_from_market(matched)
                    if prob is not None:
                        return (slug, prob)
                    matched_invalid = True

            # Strategy 2: search markets directly
            markets = _search_markets(slug, timeout=timeout)
            matched = _match_market_in_results(markets, slug)
            if matched:
                prob = _extract_probability_from_market(matched)
                if prob is not None:
                    return (slug, prob)
                matched_invalid = True

            if raise_on_error and matched_invalid:
                raise ValueError(f"matched market '{slug}' has no valid probability")

            # Both API calls completed, so empty lists are a valid no-data
            # answer too. Only transport failures reach another attempt.
            print(
                f"  polymarket: no match for slug '{slug}' "
                f"(searched {len(events)} events, {len(markets)} markets)",
                file=sys.stderr,
            )
            return (slug, None)

        except (URLError, TimeoutError, OSError) as e:
            last_error = e
            if attempt < retries:
                print(
                    f"  polymarket: retry {attempt}/{retries} for '{slug}': {e}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY)
            else:
                print(
                    f"  polymarket: failed after {retries} attempts for '{slug}': {e}",
                    file=sys.stderr,
                )
        except Exception as e:
            # WHY broad catch: API changes (new response shapes, field
            # renames) shouldn't crash the graph generator. Log and move on.
            print(f"  polymarket: unexpected error for '{slug}': {e}", file=sys.stderr)
            if raise_on_error:
                last_error = e
                if attempt < retries:
                    time.sleep(RETRY_DELAY)
                    continue
                break
            return (slug, None)

    if raise_on_error and last_error is not None:
        if not isinstance(last_error, (URLError, TimeoutError, OSError)):
            raise APIError(
                f"Polymarket returned invalid data for '{slug}' after "
                f"{retries} attempts"
            ) from last_error
        unit = "attempt" if retries == 1 else "attempts"
        raise APIError(
            f"Polymarket fetch for '{slug}' failed after {retries} {unit}"
        ) from last_error
    return (slug, None)


def fetch_markets(
    slugs: List[str],
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    raise_on_error: bool = False,
    parallel: bool = False,
) -> Dict[str, Optional[float]]:
    """Fetch probabilities for multiple markets.

    Returns a dict mapping each slug to its Yes probability (0-1),
    or None if the market wasn't found or the fetch failed.

    WHY dict return: the thesis graph engine needs to look up probability
    by the market identifier stored in the node's feed config. A dict
    keyed by slug makes this O(1).
    """
    results: Dict[str, Optional[float]] = {}

    if parallel and slugs:
        def fetch_one(slug: str) -> Tuple[str, Optional[float]]:
            return fetch_single_market(
                slug,
                timeout=timeout,
                retries=retries,
                raise_on_error=raise_on_error,
            )

        # WHY bounded parallelism: interactive book verification has a 60s
        # whole-turn budget. Sequential retry ceilings exceed it, while the
        # checked-in books need at most three independent public API reads.
        with ThreadPoolExecutor(max_workers=min(len(slugs), 8)) as pool:
            for slug_result, prob in pool.map(fetch_one, slugs):
                results[slug_result] = prob
        return results

    for i, slug in enumerate(slugs):
        slug_result, prob = fetch_single_market(
            slug,
            timeout=timeout,
            retries=retries,
            raise_on_error=raise_on_error,
        )
        results[slug_result] = prob

        # WHY delay between requests: be polite to the API. Skip delay
        # after the last request since there's nothing to wait for.
        if i < len(slugs) - 1:
            time.sleep(RETRY_DELAY)

    return results


# =========================================================================
# CLI — standalone usage for debugging / manual checks
# =========================================================================

def main() -> None:
    """Fetch and print probabilities for given market slugs."""
    if len(sys.argv) < 2:
        print("Usage: polymarket.py <slug> [slug2 ...] [--json]", file=sys.stderr)
        print("Example: polymarket.py us-iran-april-30", file=sys.stderr)
        sys.exit(1)

    # WHY --json flag: structured output for piping into other tools
    output_json = "--json" in sys.argv
    slugs = [s for s in sys.argv[1:] if not s.startswith("--")]

    results = fetch_markets(slugs)

    if output_json:
        print(json.dumps(results, indent=2))
    else:
        for slug, prob in results.items():
            if prob is not None:
                # WHY percentage: humans read "68.5%" faster than "0.685"
                print(f"  {slug}: {prob:.1%}")
            else:
                print(f"  {slug}: FAILED (no data)")

    # WHY exit code: scripts chaining this can detect failure
    if all(v is None for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
