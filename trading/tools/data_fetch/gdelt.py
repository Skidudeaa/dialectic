#!/usr/bin/env python3
"""
GDELT Doc 2.0 API fetcher — geopolitical event volume + article lists.

Pulls article-volume time series and article lists from the GDELT Doc 2.0
public API (no auth, updated every 15 minutes).

Source: https://api.gdeltproject.org/api/v2/doc/doc

WHY this exists: thesis nodes that fire on geopolitical events (Hormuz
blockade chatter, tariff escalation rhetoric, China property defaults) have
no quantifiable feed today. GDELT's `mode=timelinevol` returns the share
of all global wire articles matching a query, refreshed every 15 minutes —
a usable signal for trigger-volume amber-flagging.

Usage as library:
    from gdelt import fetch_volume_timeline, fetch_volume_latest, fetch_articles
    series = fetch_volume_timeline(
        query='Hormuz AND ("blockade" OR "tanker")', timespan="7d"
    )
    latest_pct = fetch_volume_latest('"Country Garden" OR "LGFV"')
    articles = fetch_articles('tariff AND China', max_records=10)

Usage standalone:
    python3 gdelt.py "Hormuz AND blockade" --mode volume --timespan 1d
    python3 gdelt.py "tariff AND China" --mode articles --max-records 10
"""

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

DEFAULT_TIMEOUT = 20

# WHY 1s polite pacing: GDELT does not publish a hard rate limit but its
# documentation strongly recommends ~1 req/sec. We don't enforce inter-call
# sleep here (callers do, or just call once); we use 1s only to back off
# after a 429.
RATE_LIMIT_BACKOFF = 5.0

DEFAULT_RETRIES = 2
RETRY_BASE_DELAY = 0.5

_HEADERS = {"User-Agent": "Mozilla/5.0 (tradingDesk/gdelt-fetcher)"}


# =========================================================================
# Types
# =========================================================================

@dataclass
class Article:
    """One GDELT article hit (artlist mode)."""
    url: str
    title: str
    seendate: str
    domain: str
    language: str
    sourcecountry: str

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "seendate": self.seendate,
            "domain": self.domain,
            "language": self.language,
            "sourcecountry": self.sourcecountry,
        }


# =========================================================================
# Errors
# =========================================================================

class GdeltError(Exception):
    """Base exception for GDELT fetcher errors."""
    pass


class GdeltRateLimitError(GdeltError):
    """Raised when GDELT exhausts the caller's 429 attempt budget."""
    pass


class GdeltAPIError(GdeltError):
    """Raised on unexpected GDELT responses (non-2xx, malformed JSON)."""
    pass


# =========================================================================
# Helpers
# =========================================================================

def _make_request(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _build_url(
    query: str, mode: str,
    *,
    timespan: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_records: Optional[int] = None,
) -> str:
    """Build a GDELT Doc API URL.

    WHY explicit params: GDELT supports many modes (artlist, timelinevol,
    timelinetone, toneonly, etc.). We expose timelinevol + artlist —
    others are easy to add later.
    """
    params: List[Tuple[str, str]] = [
        ("query", query),
        ("mode", mode),
        ("format", "json"),
    ]
    if timespan:
        params.append(("timespan", timespan))
    if start:
        params.append(("startdatetime", start))
    if end:
        params.append(("enddatetime", end))
    if max_records is not None:
        params.append(("maxrecords", str(max_records)))
    return f"{GDELT_DOC_API}?{urlencode(params)}"


def _parse_json(body: bytes, query: str) -> dict:
    """Parse GDELT JSON, with helpful errors on the empty / non-JSON cases.

    WHY tolerant: GDELT sometimes returns an empty body or HTML on bad
    queries (no 4xx code) — caller wants a clear error, not a JSONDecodeError.
    """
    if not body or not body.strip():
        # GDELT often returns empty body when the query has no matches in
        # the timespan. Treat as "no data" — empty list at upper layer.
        return {}
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError) as e:
        raise GdeltAPIError(
            f"GDELT returned non-JSON for query {query!r}: "
            f"{body[:200]!r} ({e})"
        ) from e


def _fetch_with_retry(
    url: str, query: str, *, retries: int = DEFAULT_RETRIES,
) -> dict:
    """Make request with retry + dedicated 429 handling.

    WHY 429 is special: GDELT 429 means "you're going too fast". Batch callers
    retain one polite delayed retry; an interactive caller with retries=0 gets
    the first 429 immediately so its source-wide cooldown can take over.
    """
    last_error: Optional[Exception] = None
    rate_limit_hits = 0

    for attempt in range(retries + 1):
        try:
            raw = _make_request(url)
            return _parse_json(raw, query)
        except HTTPError as e:
            if e.code == 429:
                rate_limit_hits += 1
                if retries == 0 or rate_limit_hits >= 2 or attempt >= retries:
                    raise GdeltRateLimitError(
                        f"GDELT rate-limited for query {query!r}; "
                        "back off polling cadence"
                    ) from e
                print(
                    f"  gdelt: 429 for {query!r}, sleeping "
                    f"{RATE_LIMIT_BACKOFF:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(RATE_LIMIT_BACKOFF)
                # Don't count 429 against the regular retries counter.
                continue
            if 400 <= e.code < 500:
                raise GdeltAPIError(
                    f"GDELT returned HTTP {e.code} for query {query!r}: "
                    f"{e.reason}"
                ) from e
            last_error = e
        except (URLError, TimeoutError, OSError) as e:
            last_error = e
        except (GdeltAPIError, GdeltRateLimitError):
            raise

        if attempt < retries:
            sleep_for = RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"  gdelt: retry {attempt + 1}/{retries} for {query!r} "
                f"after {last_error!r}, sleeping {sleep_for:.1f}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)

    raise GdeltAPIError(
        f"GDELT fetch failed for query {query!r} after {retries + 1} "
        f"attempts: {last_error!r}"
    )


# =========================================================================
# Public API
# =========================================================================

def fetch_volume_timeline(
    query: str,
    *,
    timespan: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    retries: int = DEFAULT_RETRIES,
) -> List[Tuple[str, float]]:
    """Fetch article-volume time series for a query.

    Args:
        query: GDELT query string (supports AND/OR/quoted-phrase/sourcelang:).
        timespan: shortcut like "1d", "7d", "1m" (mutually exclusive with
            start/end).
        start: ISO datetime "YYYYMMDDHHMMSS" (UTC).
        end: ISO datetime "YYYYMMDDHHMMSS" (UTC).

    Returns:
        List of (date_str, volume_pct) tuples sorted by date ascending.
        volume_pct is share-of-all-articles (0..1+ scale; commonly tiny).
        Returns [] when GDELT returns no data.
    """
    url = _build_url(
        query, "timelinevol",
        timespan=timespan, start=start, end=end,
    )
    payload = _fetch_with_retry(url, query, retries=retries)
    if not payload:
        return []

    timeline = payload.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        return []

    # GDELT's timelinevol payload is shaped:
    #   {"timeline": [{"data": [{"date": "20260501T000000Z", "value": 0.0234}, ...]}]}
    # The outer list contains one series per query (we send one query, so [0]).
    first = timeline[0]
    rows = first.get("data") if isinstance(first, dict) else None
    if not isinstance(rows, list):
        return []

    out: List[Tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_str = row.get("date")
        value = row.get("value")
        if date_str is None or value is None:
            continue
        try:
            out.append((str(date_str), float(value)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda r: r[0])
    return out


def fetch_volume_latest(
    query: str, *, timespan: str = "1d",
    retries: int = DEFAULT_RETRIES,
) -> Optional[float]:
    """Fetch the most recent volume bucket only.

    Returns None if GDELT returned no data for the query in the timespan.
    """
    series = fetch_volume_timeline(query, timespan=timespan, retries=retries)
    if not series:
        return None
    return series[-1][1]


def fetch_articles(
    query: str,
    *,
    max_records: int = 25,
    timespan: str = "1d",
    retries: int = DEFAULT_RETRIES,
) -> List[Article]:
    """Fetch a list of recent articles matching a query."""
    url = _build_url(
        query, "artlist",
        timespan=timespan, max_records=max_records,
    )
    payload = _fetch_with_retry(url, query, retries=retries)
    if not payload:
        return []

    rows = payload.get("articles")
    if not isinstance(rows, list):
        return []

    out: List[Article] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(Article(
            url=str(row.get("url", "")),
            title=str(row.get("title", "")),
            seendate=str(row.get("seendate", "")),
            domain=str(row.get("domain", "")),
            language=str(row.get("language", "")),
            sourcecountry=str(row.get("sourcecountry", "")),
        ))
    return out


# =========================================================================
# Standard queries — pre-built for canonical thesis-graph nodes
# =========================================================================

# WHY a registry: book JSON references abstract queries; this catalog
# keeps them in one place. Adding a new geopolitical signal node only
# needs an entry here + a feed reference in the book.
STANDARD_QUERIES: dict = {
    "iran-hormuz-event": (
        '"Hormuz" AND ("blockade" OR "closure" OR "tanker") '
        'AND sourcelang:eng'
    ),
    "trump-tariff-escalation": (
        '"tariff" AND ("China" OR "Section 122" OR "IEEPA") '
        'AND sourcelang:eng'
    ),
    "china-property-default": (
        '("Vanke" OR "Country Garden" OR "Evergrande" '
        'OR "local government financing") '
        'AND ("default" OR "restructuring") AND sourcelang:eng'
    ),
    # WHY no "BOJ"/"JGB"/"LGFV": GDELT rejects quoted terms under 5 chars
    # ("The specified phrase is too short." — observed live: "IEEPA" passes,
    # "LGFV" fails). Acronyms shorter than that must be spelled out.
    "japan-rate-shock": (
        '"Bank of Japan" AND ("yield" OR "rate hike" OR "government bond") '
        'AND sourcelang:eng'
    ),
    "ai-capex-cut": (
        '("NVIDIA" OR "Taiwan Semiconductor" OR "datacenter") AND '
        '("capex" OR "guidance cut" OR "demand") AND sourcelang:eng'
    ),
}


def get_standard_query(name: str) -> Optional[str]:
    """Look up a pre-built query string by canonical name."""
    return STANDARD_QUERIES.get(name)


# =========================================================================
# CLI
# =========================================================================

def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(
            'Usage: gdelt.py "<query>" [--mode volume|articles|latest] '
            "[--timespan 1d] [--max-records 25] [--json]",
            file=sys.stderr,
        )
        print(
            "       gdelt.py --list  (list pre-built standard queries)",
            file=sys.stderr,
        )
        sys.exit(0 if args and args[0] in ("-h", "--help") else 1)

    if args[0] == "--list":
        for name, q in STANDARD_QUERIES.items():
            print(f"  {name}:\n    {q}")
        return

    query = args[0]
    mode = "volume"
    timespan = "1d"
    max_records = 25
    output_json = False

    i = 1
    while i < len(args):
        a = args[i]
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif a == "--timespan" and i + 1 < len(args):
            timespan = args[i + 1]
            i += 2
        elif a == "--max-records" and i + 1 < len(args):
            max_records = int(args[i + 1])
            i += 2
        elif a == "--json":
            output_json = True
            i += 1
        else:
            print(f"  ERROR: unknown arg {a!r}", file=sys.stderr)
            sys.exit(1)

    try:
        if mode == "volume":
            series = fetch_volume_timeline(query, timespan=timespan)
            if output_json:
                print(json.dumps([
                    {"date": d, "value": v} for d, v in series
                ], indent=2))
            elif not series:
                print(f"  {query}: no volume data in timespan {timespan}")
            else:
                print(
                    f"  {query} — {len(series)} buckets over {timespan}"
                )
                for d, v in series[-20:]:
                    print(f"    {d}: {v:.4f}")
        elif mode == "latest":
            v = fetch_volume_latest(query, timespan=timespan)
            if output_json:
                print(json.dumps({"query": query, "value": v}, indent=2))
            else:
                print(f"  {query}: latest volume = {v}")
        elif mode == "articles":
            arts = fetch_articles(
                query, max_records=max_records, timespan=timespan,
            )
            if output_json:
                print(json.dumps([a.to_dict() for a in arts], indent=2))
            else:
                print(f"  {query} — {len(arts)} articles")
                for a in arts:
                    print(f"    [{a.seendate}] {a.domain}: {a.title}")
        else:
            print(f"  ERROR: unknown mode {mode!r}", file=sys.stderr)
            sys.exit(1)
    except GdeltRateLimitError as e:
        print(f"  RATE LIMITED: {e}", file=sys.stderr)
        sys.exit(2)
    except GdeltAPIError as e:
        print(f"  API ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
