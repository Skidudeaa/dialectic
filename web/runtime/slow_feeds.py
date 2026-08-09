"""
Slow-feed refresh for the runtime coordinator.

WHY this module exists: fetch_fred, fetch_eia, fetch_treasury, fetch_gdelt
and the econ-calendar adapter were all written and tested, then wired only
to the CLI (`thesisgraph.py --fetch`). The desk's live loop never called
them, so every node whose only feed was fred/eia/treasury/gdelt sat on the
book's hand-typed default forever while the UI rendered it as a live node.

ARCHITECTURE: The coordinator deep-copies the immutable book definition on
every tick, so the cfg itself cannot remember when a source was last pulled.
This refresher holds that memory as coordinator-lifetime state keyed by
(thesis_id, source), and does one of two things per source per tick:

  - TTL expired  -> run the blocking fetcher in a thread, then harvest the
    node values it wrote plus the freshness stamp it left behind.
  - TTL not expired -> patch the CACHED values into the fresh deep copy
    BEFORE propagate() runs. Skipping this is NOT a no-op: it would silently
    revert every slow-fed node to the book default on the skipped ticks —
    11 ticks out of 12 for treasury, 71 out of 72 for the calendar.

TRADEOFF: a source that fails keeps serving its last good values for
TTL * 3, then goes quiet and lets the book's own defaults stand. Serving a
known-stale number forever is worse than falling back to a documented
default, and the freshness stamp says which one the UI is looking at —
cached patches carry the ORIGINAL fetch time, never the patch time.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Set, Tuple

from tools.thesis_graph import thesisgraph  # type: ignore[import-untyped]

from web.adapters import econ_calendar

log = logging.getLogger(__name__)

# WHY a pseudo-source name: the calendar is not a node `feeds[].source` —
# it patches `deadline` on deadline-type nodes. It still wants the same TTL
# bookkeeping and the same freshness surface, so it rides the same machinery
# under a name that cannot collide with a real feed source.
ECON_CALENDAR = "econ-calendar"

# WHY 3x: one failed pull is noise (a 502, a mid-publish window). Three
# consecutive TTLs of failure is an outage, and at that point a number the
# desk keeps presenting as live is a lie the operator cannot see.
STALE_GRACE_MULTIPLIER = 3.0

ECON_CALENDAR_LOOKAHEAD_DAYS = 90

# WHY the caller needs its own ceiling: every fetcher sets a 20s socket
# timeout and then retries, so the worst case the CALLER sees is 20s times a
# retry count it cannot read, plus backoff. This whole refresh happens inside
# the fetch cycle, which holds the per-thesis lock — that is what makes a tick
# skip and a TradingView webhook (10s submit timeout) collide. Measured happy
# path is 10-32s per source, so 45s is a ceiling on a bad day rather than a
# cap on a normal one. Four sources at their ceiling is 180s against a 300s
# tick; in practice fred/eia are key-gated off and the calendar is instant.
DEFAULT_SOURCE_TIMEOUT = 45.0


@dataclass(frozen=True)
class SourceSpec:
    """One slow source: how often to pull it, and what gates the pull.

    env_key is the environment variable that must be non-empty before we
    invoke the fetcher at all. The fetchers already no-op without their key
    (FredAuthError / EIAAuthError are caught internally), but "no-op" still
    costs an import, a cfg scan and a stderr line per book per tick.
    """

    name: str
    ttl_seconds: float
    env_key: Optional[str] = None
    timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT


SOURCE_SPECS: Tuple[SourceSpec, ...] = (
    # Daily curve, published once per business day.
    SourceSpec("treasury", 3600.0),
    # GDELT re-slices its volume buckets every ~15 minutes. Its own API is
    # the slowest of the four — measured at 31s and 32s on two live pulls of
    # a single query — so 45s would clip it on any bad day and serve cache
    # far more often than the failure rate warrants.
    SourceSpec("gdelt", 900.0, timeout_seconds=60.0),
    # FRED publishes most daily series once, around 16:00 ET.
    SourceSpec("fred", 3600.0, env_key="FRED_API_KEY"),
    # EIA series are weekly; an hourly poll is already generous.
    SourceSpec("eia", 3600.0, env_key="EIA_API_KEY"),
    # Release calendars move on a weekly cadence at most; the connector
    # falls back to a static table, so it never touches the network without
    # a FRED key and does not need the full budget.
    SourceSpec(ECON_CALENDAR, 21600.0, timeout_seconds=30.0),
)

# Resolved by name at call time (never bound at import) so the fetchers stay
# patchable as module attributes, the way the fast fetches already are.
_FETCHER_NAMES: Mapping[str, str] = {
    "treasury": "fetch_treasury",
    "gdelt": "fetch_gdelt",
    "fred": "fetch_fred",
    "eia": "fetch_eia",
}


@dataclass
class CacheEntry:
    """Last good result for one (thesis_id, source).

    fetched_at is a MONOTONIC timestamp — it only ever feeds elapsed-time
    compares, and a wall-clock step must not be able to pin a source stale
    for hours or stampede every source at once.

    freshness is the fetcher's own `_feed_freshness[source]` entry, kept
    verbatim so the patch path can re-stamp with the real fetch time.
    """

    fetched_at: float
    field_name: str
    values: Dict[str, Any]
    freshness: Optional[dict] = None

    def age(self, now: float) -> float:
        return now - self.fetched_at


def declared_sources(cfg: dict) -> Set[str]:
    """Return the slow sources this book actually declares.

    WHY scan rather than try-them-all: four of the five books declare no
    treasury feed and none declares gdelt except iran-hormuz. Invoking a
    fetcher for a book with nothing to fetch is a wasted thread hop and a
    misleading log line.
    """
    found: Set[str] = set()
    for node in cfg.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "deadline":
            found.add(ECON_CALENDAR)
        for feed in node.get("feeds", []) or []:
            if isinstance(feed, dict) and feed.get("source"):
                found.add(str(feed["source"]))
    return found


def nodes_with_source(cfg: dict, source: str) -> Iterable[dict]:
    """Yield nodes declaring at least one feed from `source`."""
    for node in cfg.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        for feed in node.get("feeds", []) or []:
            if isinstance(feed, dict) and feed.get("source") == source:
                yield node
                break


def is_stale_deadline(current: Optional[str], candidate: Optional[str],
                      today: date) -> bool:
    """True when a book's hand-typed deadline should yield to the calendar.

    WHY not simply take the calendar date: the match is fuzzy (token overlap
    across the node's id + label + context), and an author who typed a FUTURE
    date knows something the matcher does not. We only overwrite a deadline
    that has already passed — the case where the book is provably wrong and
    the desk's countdown reads "PASSED (34d ago)" for a recurring event that
    has since been re-scheduled.
    """
    if not candidate:
        return False
    try:
        cand_d = date.fromisoformat(str(candidate))
    except (TypeError, ValueError):
        return False
    if cand_d <= today:
        # Never trade one passed date for another.
        return False
    if not current:
        return True
    try:
        cur_d = date.fromisoformat(str(current))
    except (TypeError, ValueError):
        return True
    return cur_d < today


def _stamp(source: str, ttl_seconds: float, detail: str) -> dict:
    """Build a freshness entry in the engine's own shape.

    Mirrors thesisgraph._stamp_feed_freshness so a calendar entry is
    indistinguishable, to the snapshot schema and the UI, from a fetcher's.
    """
    return {
        "source": source,
        "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttlSeconds": int(ttl_seconds),
        "detail": detail,
    }


class SlowFeedRefresher:
    """Per-source TTL cache over the dormant fetchers.

    Owned by the coordinator for its whole lifetime — the cache is the only
    place a slow source's last value survives between ticks.
    """

    def __init__(
        self,
        specs: Iterable[SourceSpec] = SOURCE_SPECS,
        *,
        env: Optional[Mapping[str, str]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._specs: Tuple[SourceSpec, ...] = tuple(specs)
        self._cache: Dict[Tuple[str, str], CacheEntry] = {}
        # WHY injectable: tests need to prove a keyless source is never
        # invoked without mutating the process environment mid-suite.
        self._env: Mapping[str, str] = env if env is not None else os.environ
        # WHY injectable, and why monotonic: TTL expiry is the whole contract
        # here, and a test that had to sleep an hour to check a 3600s TTL
        # would never be written. Patching time.monotonic globally instead
        # would reach every other module in the process.
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic

    # ── introspection (tests + future ops endpoint) ──────────────────

    def cached(self, thesis_id: str, source: str) -> Optional[CacheEntry]:
        return self._cache.get((thesis_id, source))

    # ── main entry point ─────────────────────────────────────────────

    async def refresh(self, thesis_id: str, cfg: dict) -> Dict[str, str]:
        """Bring every declared slow source up to date on `cfg`.

        Mutates cfg in place the way the fast fetchers do (node `current` /
        `deadline` plus `_feed_freshness`). Returns {source: outcome} for
        logging and tests; outcomes are one of:
            fetched | cached | stale-cached | defaults | no-key

        NEVER raises. This runs inside the fetch cycle, which holds the
        per-thesis lock; a dormant feed's bad day must not be able to stop
        the desk from pricing.
        """
        try:
            declared = declared_sources(cfg)
        except Exception:  # noqa: BLE001 — malformed book must not kill a tick
            log.warning("slow_feeds: could not scan %s", thesis_id, exc_info=True)
            return {}

        outcomes: Dict[str, str] = {}
        for spec in self._specs:
            if spec.name not in declared:
                continue
            try:
                outcomes[spec.name] = await self._refresh_source(thesis_id, cfg, spec)
            except Exception:  # noqa: BLE001 — one source never sinks the tick
                log.warning(
                    "slow_feeds: %s refresh failed for %s",
                    spec.name, thesis_id, exc_info=True,
                )
                outcomes[spec.name] = "defaults"
        if outcomes:
            log.debug("slow_feeds %s: %s", thesis_id, outcomes)
        return outcomes

    # ── per-source state machine ─────────────────────────────────────

    async def _refresh_source(
        self, thesis_id: str, cfg: dict, spec: SourceSpec,
    ) -> str:
        key = (thesis_id, spec.name)
        entry = self._cache.get(key)
        now = self._clock()

        if spec.env_key and not str(self._env.get(spec.env_key) or "").strip():
            # Keyless: do not invoke, do not patch, do not stamp. The node
            # keeps the book default and the UI shows no freshness for the
            # source, which is the truth — nobody has ever fetched it.
            return "no-key"

        if entry is not None and entry.age(now) < spec.ttl_seconds:
            self._apply(cfg, spec.name, entry)
            return "cached"

        try:
            fresh = await asyncio.wait_for(
                self._fetch(thesis_id, cfg, spec, now), spec.timeout_seconds,
            )
        except asyncio.TimeoutError:
            # The worker thread keeps running to completion in the executor —
            # wait_for cancels the AWAIT, not the thread. That is exactly why
            # the fetch runs against a scratch copy: the abandoned thread can
            # only ever mutate a cfg nobody will read again, never the one
            # propagate() is about to walk.
            log.warning(
                "slow_feeds: %s exceeded its %.0fs budget for %s",
                spec.name, spec.timeout_seconds, thesis_id,
            )
            fresh = None
        except Exception:  # noqa: BLE001 — treated exactly like "no data"
            log.warning(
                "slow_feeds: %s fetch raised for %s", spec.name, thesis_id,
                exc_info=True,
            )
            fresh = None

        if fresh is not None:
            self._cache[key] = fresh
            self._apply(cfg, spec.name, fresh)
            return "fetched"

        if entry is not None and entry.age(now) < spec.ttl_seconds * STALE_GRACE_MULTIPLIER:
            self._apply(cfg, spec.name, entry)
            log.warning(
                "slow_feeds: %s unavailable for %s — serving cache (age %.0fs)",
                spec.name, thesis_id, entry.age(now),
            )
            return "stale-cached"

        if entry is not None:
            log.warning(
                "slow_feeds: %s stale beyond grace for %s (age %.0fs) — "
                "falling back to book defaults",
                spec.name, thesis_id, entry.age(now),
            )
        self._cache.pop(key, None)
        # Nothing to serve means nothing to claim. Strip any freshness entry
        # for this source so the UI cannot show a green badge over a node
        # that is sitting on its book default.
        freshness = cfg.get("_feed_freshness")
        if isinstance(freshness, dict):
            freshness.pop(spec.name, None)
        return "defaults"

    # ── fetch paths ──────────────────────────────────────────────────

    async def _fetch(
        self, thesis_id: str, cfg: dict, spec: SourceSpec, now: float,
    ) -> Optional[CacheEntry]:
        if spec.name == ECON_CALENDAR:
            return await self._fetch_econ_calendar(thesis_id, cfg, spec, now)
        return await self._fetch_engine_source(cfg, spec, now)

    async def _fetch_engine_source(
        self, cfg: dict, spec: SourceSpec, now: float,
    ) -> Optional[CacheEntry]:
        """Run one thesisgraph fetcher on a scratch cfg and harvest the result.

        WHY a scratch copy rather than the live cfg: the fetcher runs in a
        worker thread under a timeout, and a timed-out thread is abandoned,
        not killed. Handing it the live cfg would let a straggler write node
        values while propagate() is walking them. It also makes the success
        check exact — the scratch starts with no freshness at all.

        WHY the freshness stamp IS the success signal: these fetchers return
        no status. Every failure path — missing key, import error, HTTP error,
        zero series resolved — prints to stderr and returns cfg untouched. The
        one thing they do only on success is stamp `_feed_freshness[source]`.
        """
        fetcher = getattr(thesisgraph, _FETCHER_NAMES[spec.name], None)
        if fetcher is None:  # pragma: no cover — engine contract change
            log.warning("slow_feeds: engine has no fetcher for %s", spec.name)
            return None

        scratch = copy.deepcopy(cfg)
        scratch.pop("_feed_freshness", None)

        await asyncio.to_thread(fetcher, scratch)

        stamp = (scratch.get("_feed_freshness") or {}).get(spec.name)
        if not stamp:
            return None

        values: Dict[str, Any] = {}
        for node in nodes_with_source(scratch, spec.name):
            if "current" in node:
                values[node["id"]] = node["current"]

        return CacheEntry(
            fetched_at=now,
            field_name="current",
            values=values,
            freshness=copy.deepcopy(stamp),
        )

    async def _fetch_econ_calendar(
        self, thesis_id: str, cfg: dict, spec: SourceSpec, now: float,
    ) -> Optional[CacheEntry]:
        """Pull the release calendar and patch stale deadline nodes.

        WHY get_calendar() first: for_book() returns an empty mapping both
        when the calendar is unreachable and when nothing matched. Asking for
        the events separately lets us tell "no calendar" (a failure — no
        stamp, retry next tick) from "calendar says nothing about this book"
        (a success — stamp it and hold the TTL).
        """
        events = await econ_calendar.get_calendar(
            lookahead_days=ECON_CALENDAR_LOOKAHEAD_DAYS
        )
        if not events:
            return None

        mapping = await econ_calendar.for_book(
            thesis_id, lookahead_days=ECON_CALENDAR_LOOKAHEAD_DAYS
        )

        today = datetime.now(timezone.utc).date()
        values: Dict[str, Any] = {}
        for node in cfg.get("nodes", []) or []:
            if not isinstance(node, dict) or node.get("type") != "deadline":
                continue
            event = mapping.get(node.get("id")) or {}
            candidate = event.get("date")
            if is_stale_deadline(node.get("deadline"), candidate, today):
                values[node["id"]] = candidate

        return CacheEntry(
            fetched_at=now,
            field_name="deadline",
            values=values,
            freshness=_stamp(
                ECON_CALENDAR, spec.ttl_seconds,
                f"{len(values)} deadline(s) repointed, {len(events)} event(s)",
            ),
        )

    # ── patch path ───────────────────────────────────────────────────

    @staticmethod
    def _apply(cfg: dict, source: str, entry: CacheEntry) -> None:
        """Write cached values into a freshly deep-copied cfg."""
        node_map = {
            n["id"]: n for n in cfg.get("nodes", []) or []
            if isinstance(n, dict) and "id" in n
        }
        for node_id, value in entry.values.items():
            node = node_map.get(node_id)
            if node is None:
                continue
            node[entry.field_name] = value

        if entry.freshness:
            # Verbatim copy. fetchedAt MUST stay the time of the real pull —
            # re-stamping here would make a 5h50m-old calendar read as
            # fetched-this-tick and turn the whole freshness surface into
            # decoration.
            cfg.setdefault("_feed_freshness", {})[source] = dict(entry.freshness)
