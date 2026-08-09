#!/usr/bin/env python3
"""
Econ calendar connector — feeds deadline-node countdowns from a calendar source.

WHY this exists: Trading Desk has deadline-type nodes that today carry hand-coded
dates (`capex-guide`, `boj-decision`, `section122-expiry`). They rot. This module
returns upcoming macro/policy events (FOMC, CPI, payrolls, BoJ MPM, ECB) so the
deadline-node countdown math can stay current without manual edits.

Two providers in priority order:
  1. PRIMARY: FRED Releases calendar — when FRED_API_KEY is set in the env. FRED
     hangs its own freshness contract and we trust its uptime.
  2. FALLBACK: An embedded static dictionary of known recurring events (FOMC
     meeting dates 2026, BoJ MPM, CPI release calendar). The fallback is the
     deterministic path so the connector NEVER returns nothing in tests/offline.

Usage as library:
    from tools.data_fetch.econ_calendar import fetch_upcoming_events, match_event
    events = fetch_upcoming_events(lookahead_days=90)
    hit = match_event("boj-decision", events)

Each event dict:
    {
        "event_id": "boj-2026-05",       # stable slug
        "label": "BoJ MPM (Apr 30 – May 1)",
        "source": "fred" | "static",
        "date": "2026-05-01",            # ISO8601 date
        "days_remaining": 7,             # int relative to today
    }
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Re-use the FRED base URL if Unit 2 has shipped fred.py; otherwise
# define our own. Reading is fine — we never write to it.
try:  # pragma: no cover - opportunistic import; tested via fallback path
    from tools.data_fetch.fred import _FRED_BASE_URL  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 — any import failure means use our default
    _FRED_BASE_URL = "https://api.stlouisfed.org/fred"

DEFAULT_TIMEOUT = 10  # seconds
DEFAULT_LOOKAHEAD_DAYS = 90

_HEADERS = {"User-Agent": "Mozilla/5.0 (tradingDesk/econ-calendar)"}


# =============================================================================
# Static fallback dictionary
# =============================================================================
#
# WHY hand-curated: a tiny, deterministic set of high-signal macro/policy
# events. Stays accurate for ~90 days from 2026-04-24. Refresh quarterly.
# Extending this list is cheap; an entry's job is just to ensure deadline
# nodes always have *something* to count down to.
#
# The selection covers:
#   - BoJ MPM 2026 (April 30 – May 1, June 16–17, July 30–31, September 18–19)
#   - FOMC 2026 (May 5–6, June 16–17, July 28–29)
#   - US CPI release dates (May 13, June 11, July 15)
#   - ECB Governing Council (June 4, July 23)
#   - US Nonfarm Payrolls (May 2, June 6, July 4-ish — Independence Day shifts)
#
# Dates are best-known plausible recurrences; production deployments should
# reconcile against the issuing institution's own calendar.

_STATIC_EVENTS: List[dict] = [
    # BoJ MPM dates — calendar published annually, dates known
    {"event_id": "boj-2026-05", "label": "BoJ MPM (Apr 30 – May 1)",
     "source": "static", "date": "2026-05-01",
     "keywords": ["boj", "bank of japan", "mpm", "japan rate"]},
    {"event_id": "boj-2026-06", "label": "BoJ MPM (Jun 16 – 17)",
     "source": "static", "date": "2026-06-17",
     "keywords": ["boj", "bank of japan", "mpm", "japan rate"]},
    {"event_id": "boj-2026-07", "label": "BoJ MPM (Jul 30 – 31)",
     "source": "static", "date": "2026-07-31",
     "keywords": ["boj", "bank of japan", "mpm", "japan rate"]},
    # FOMC meetings — released annually
    {"event_id": "fomc-2026-05", "label": "FOMC Meeting (May 5 – 6)",
     "source": "static", "date": "2026-05-06",
     "keywords": ["fomc", "fed", "federal reserve", "powell", "rate decision"]},
    {"event_id": "fomc-2026-06", "label": "FOMC Meeting (Jun 16 – 17)",
     "source": "static", "date": "2026-06-17",
     "keywords": ["fomc", "fed", "federal reserve", "powell", "rate decision"]},
    {"event_id": "fomc-2026-07", "label": "FOMC Meeting (Jul 28 – 29)",
     "source": "static", "date": "2026-07-29",
     "keywords": ["fomc", "fed", "federal reserve", "powell", "rate decision"]},
    # US CPI release dates (BLS publishes ~2nd week each month)
    {"event_id": "cpi-2026-05", "label": "US CPI (May release)",
     "source": "static", "date": "2026-05-13",
     "keywords": ["cpi", "inflation", "bls", "consumer price"]},
    {"event_id": "cpi-2026-06", "label": "US CPI (Jun release)",
     "source": "static", "date": "2026-06-11",
     "keywords": ["cpi", "inflation", "bls", "consumer price"]},
    {"event_id": "cpi-2026-07", "label": "US CPI (Jul release)",
     "source": "static", "date": "2026-07-15",
     "keywords": ["cpi", "inflation", "bls", "consumer price"]},
    # ECB Governing Council
    {"event_id": "ecb-2026-06", "label": "ECB Rate Decision (Jun 4)",
     "source": "static", "date": "2026-06-04",
     "keywords": ["ecb", "european central bank", "lagarde", "euro rate"]},
    {"event_id": "ecb-2026-07", "label": "ECB Rate Decision (Jul 23)",
     "source": "static", "date": "2026-07-23",
     "keywords": ["ecb", "european central bank", "lagarde", "euro rate"]},
    # US Nonfarm Payrolls
    {"event_id": "nfp-2026-05", "label": "US Nonfarm Payrolls (May)",
     "source": "static", "date": "2026-05-01",
     "keywords": ["nfp", "payrolls", "employment", "jobs report", "bls"]},
    {"event_id": "nfp-2026-06", "label": "US Nonfarm Payrolls (Jun)",
     "source": "static", "date": "2026-06-05",
     "keywords": ["nfp", "payrolls", "employment", "jobs report", "bls"]},
    {"event_id": "nfp-2026-07", "label": "US Nonfarm Payrolls (Jul)",
     "source": "static", "date": "2026-07-02",
     "keywords": ["nfp", "payrolls", "employment", "jobs report", "bls"]},
]


def _today() -> date:
    """Return today's date.

    WHY a wrapper: tests can monkeypatch this without freezing the system clock.
    """
    return datetime.now(timezone.utc).date()


def _parse_iso_date(value: str) -> Optional[date]:
    """Parse an ISO8601 date (YYYY-MM-DD) to a `date`. Return None on failure."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _emit_event(
    *,
    event_id: str,
    label: str,
    source: str,
    event_date: date,
    today: date,
    keywords: Optional[List[str]] = None,
) -> dict:
    """Produce a stable-shape event dict.

    WHY: every code path that builds an event must return the same keys in the
    same order — downstream comparison/cache keying depends on it.
    """
    out = {
        "event_id": event_id,
        "label": label,
        "source": source,
        "date": event_date.isoformat(),
        "days_remaining": (event_date - today).days,
    }
    if keywords:
        # WHY copy: callers should not be able to mutate the static dict.
        out["keywords"] = list(keywords)
    return out


# =============================================================================
# FRED primary path
# =============================================================================

def _fred_get(path: str, params: dict, *, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Make a GET request to the FRED API.

    WHY local helper: Unit 2's fred.py may not exist yet. We define a minimal
    helper here that mirrors the same shape (`_FRED_BASE_URL` + JSON response)
    so we can be cut over to the shared helper later.
    """
    qs = urlencode({**params, "file_type": "json"})
    url = f"{_FRED_BASE_URL}{path}?{qs}"
    req = Request(url, headers=_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body)


def _fetch_fred_events(api_key: str, *, today: date, lookahead_days: int) -> List[dict]:
    """Pull upcoming release dates from FRED's `releases/dates` endpoint.

    WHY: FRED publishes a "release dates" feed listing every scheduled release
    for every series it tracks (CPI, PPI, NFP, FOMC minutes, etc.). We filter
    by date window and synthesize a stable event_id from `release_id` + ISO
    date.

    Errors propagate to the caller so the wrapper can fall back to static.
    """
    end = today + timedelta(days=lookahead_days)
    raw = _fred_get(
        "/releases/dates",
        {
            "api_key": api_key,
            "realtime_start": today.isoformat(),
            "realtime_end": end.isoformat(),
            "include_release_dates_with_no_data": "false",
            "limit": 1000,
        },
    )

    out: List[dict] = []
    for entry in raw.get("release_dates", []) or []:
        rdate = _parse_iso_date(entry.get("date", ""))
        if rdate is None:
            continue
        if rdate < today or rdate > end:
            continue
        rel_id = entry.get("release_id")
        rel_name = entry.get("release_name") or f"FRED release {rel_id}"
        if rel_id is None:
            continue
        eid = f"fred-{rel_id}-{rdate.isoformat()}"
        out.append(
            _emit_event(
                event_id=eid,
                label=str(rel_name),
                source="fred",
                event_date=rdate,
                today=today,
                keywords=[str(rel_name).lower()],
            )
        )
    return out


# =============================================================================
# Public API
# =============================================================================

def _filter_static(*, today: date, lookahead_days: int) -> List[dict]:
    """Materialize the static dictionary into the public event shape.

    WHY: static entries store the calendar date but `days_remaining` must be
    computed against `today` and the lookahead window applied.
    """
    horizon = today + timedelta(days=lookahead_days)
    out: List[dict] = []
    for entry in _STATIC_EVENTS:
        edate = _parse_iso_date(entry.get("date", ""))
        if edate is None:
            continue
        if edate < today or edate > horizon:
            continue
        out.append(
            _emit_event(
                event_id=entry["event_id"],
                label=entry["label"],
                source="static",
                event_date=edate,
                today=today,
                keywords=entry.get("keywords"),
            )
        )
    return out


def fetch_upcoming_events(
    *,
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
    api_key: Optional[str] = None,
    today: Optional[date] = None,
) -> List[dict]:
    """Return upcoming macro/policy events within the lookahead window.

    Order of precedence:
      1. FRED if `api_key` (or `FRED_API_KEY` env var) is available AND the
         request succeeds.
      2. Static fallback dictionary otherwise.

    WHY guard the FRED path with try/except: the connector MUST NEVER return
    an empty list when the static fallback has matching events. A FRED 5xx,
    timeout, or schema drift triggers the fallback transparently.

    Returns a list sorted by `days_remaining` ascending.
    """
    if lookahead_days < 0:
        raise ValueError("lookahead_days must be non-negative")
    today_d = today or _today()
    key = api_key or os.environ.get("FRED_API_KEY")

    events: List[dict] = []
    if key:
        try:
            events = _fetch_fred_events(
                key, today=today_d, lookahead_days=lookahead_days
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
            # WHY broad: any FRED failure (5xx, schema, network) -> fallback.
            print(
                f"  econ_calendar: FRED fetch failed ({exc}); using static fallback",
                file=sys.stderr,
            )
            events = []

    if not events:
        events = _filter_static(today=today_d, lookahead_days=lookahead_days)

    events.sort(key=lambda e: (e.get("days_remaining", 1 << 30), e.get("event_id", "")))
    return events


# =============================================================================
# Matching
# =============================================================================

# WHY tokenize on non-alphanum: deadline node IDs use kebab-case ("boj-decision"),
# event_ids use kebab-case+date ("boj-2026-05"), and free-text descriptions
# contain spaces, punctuation, em-dashes. A single tokenizer normalizes all of
# them.
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [t for t in _TOKEN_RE.split(text.lower()) if t]


def _score_match(query_tokens: List[str], event: dict) -> int:
    """Score how well an event matches a tokenized query.

    Higher = better. 0 = no match. Tie-break by earliest date in the caller.

    WHY token length floor: short fragments ("no", "of", "to") trigger spurious
    substring hits across the keyword universe. Requiring length >= 3 keeps the
    scorer honest. Numeric fragments (year/month parts) are also dropped — the
    date column is the source of truth for dates, not the slug.
    """
    score = 0
    eid = (event.get("event_id") or "").lower()
    label = (event.get("label") or "").lower()
    keywords = [str(k).lower() for k in (event.get("keywords") or [])]

    # WHY: exact event_id match is the strongest possible signal — caller
    # passed us the slug they care about.
    raw_query = "-".join(query_tokens)
    if raw_query and raw_query == eid:
        return 10_000

    # WHY substring on event_id: short slugs ("boj") inside ids ("boj-2026-05")
    # are usually intended. The 3-char floor + skip-pure-digit filter prevents
    # noise from "of", "no", "to" and from year-parts like "2026" or month
    # numbers leaking into matches.
    for tok in query_tokens:
        if not tok or len(tok) < 3 or tok.isdigit():
            continue
        if tok in eid:
            score += 5
        if tok in label:
            score += 3
        for kw in keywords:
            # WHY only token-in-keyword: matching when the keyword is a
            # substring of the token gives "no" matching keyword "nfp"
            # backwards — kill that asymmetry.
            if tok == kw or tok in kw:
                score += 4
                break
    return score


def match_event(query: str, events: List[dict]) -> Optional[dict]:
    """Return the best-scoring event for `query`, or None if no signal found.

    WHY: deadline nodes attach to events through fuzzy hints (the node's id +
    description). We tokenize and score; the highest score wins, ties broken
    by soonest date. A score of zero returns None — better to leave the node
    on its hand-coded date than wire it to an unrelated event.

    Special-case: if `query` is exactly a known event_id, that wins outright
    (score 10,000) so callers can pin a node to a specific event reliably.
    """
    if not query or not isinstance(query, str):
        return None
    if not events:
        return None

    tokens = _tokenize(query)
    if not tokens:
        return None

    best: Optional[dict] = None
    best_score = 0
    best_date: Optional[date] = None

    for ev in events:
        s = _score_match(tokens, ev)
        if s <= 0:
            continue
        ev_date = _parse_iso_date(ev.get("date", "")) or date.max
        if (
            s > best_score
            or (s == best_score and best_date is not None and ev_date < best_date)
        ):
            best = ev
            best_score = s
            best_date = ev_date

    return best


# =============================================================================
# CLI — quick manual probe
# =============================================================================

def main() -> None:
    """Print upcoming events as JSON to stdout."""
    lookahead = 90
    if len(sys.argv) > 1:
        try:
            lookahead = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [lookahead_days]", file=sys.stderr)
            sys.exit(2)
    events = fetch_upcoming_events(lookahead_days=lookahead)
    print(json.dumps(events, indent=2))


if __name__ == "__main__":
    main()
