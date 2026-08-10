"""
Tests for the slow-feed refresher.

WHY these are the tests that matter: the refresher's whole job is to make a
value fetched once an hour look continuous across twelve 300s ticks. Every
failure mode is silent — a missing patch reverts a node to its book default,
a re-stamped freshness entry makes a six-hour-old calendar read as live, and
an ungated key burns an API call on every tick of every book. None of those
raise, none of them show up in a snapshot's shape, and all of them look
exactly like working code from the outside.
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.persistence.repository import Repository
from web.runtime import slow_feeds
from web.runtime.coordinator import RuntimeCoordinator
from web.runtime.slow_feeds import (
    ECON_CALENDAR,
    FAILURE_COOLDOWN_BASE_SECONDS,
    SlowFeedRefresher,
    SourceSpec,
    declared_sources,
    is_stale_deadline,
    nodes_with_source,
)


class FakeClock:
    """Monotonic clock the test drives by hand."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_cfg(source: str = "treasury", *, current: float = 1.0) -> dict:
    """A minimal book: one node fed by `source`, one node fed by nothing."""
    return {
        "nodes": [
            {
                "id": "yields",
                "type": "price",
                "current": current,
                "feeds": [{"source": source, "tenor": "10Y"}],
            },
            {"id": "unrelated", "type": "event", "current": 99.0},
        ],
    }


def make_fetcher(source: str, value: float, *, node_id: str = "yields"):
    """A stand-in for a thesisgraph fetcher: writes `current`, stamps freshness.

    Mirrors the real contract exactly — the ONLY success signal a fetcher
    gives is the `_feed_freshness[source]` entry it leaves behind.
    """
    calls = []

    def fetcher(cfg: dict) -> dict:
        calls.append(cfg)
        for node in cfg.get("nodes", []):
            if node.get("id") == node_id:
                node["current"] = value
        cfg.setdefault("_feed_freshness", {})[source] = {
            "source": source,
            "fetchedAt": "2026-08-09T04:00:00Z",
            "ttlSeconds": 3600,
            "detail": f"{len(calls)} call(s)",
        }
        return cfg

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


def failing_fetcher(_cfg: dict) -> dict:
    """A fetcher that resolves nothing — the shape every real failure takes.

    The engine fetchers swallow their own errors (missing key, HTTP 5xx,
    zero series resolved) and return cfg untouched. They do NOT raise.
    """
    return _cfg


@pytest.fixture
def clock():
    return FakeClock()


def refresher(spec: SourceSpec, clock: FakeClock, env=None) -> SlowFeedRefresher:
    return SlowFeedRefresher([spec], env=env if env is not None else {}, clock=clock)


TREASURY = SourceSpec("treasury", 3600.0)


# =========================================================================
# BOOK SCANNING
# =========================================================================

class TestDeclaredSources:
    def test_finds_feed_sources(self):
        assert "treasury" in declared_sources(make_cfg("treasury"))
        assert "gdelt" in declared_sources(make_cfg("gdelt"))

    def test_deadline_node_declares_the_calendar(self):
        cfg = {"nodes": [{"id": "boj", "type": "deadline", "deadline": "2026-05-01"}]}
        assert declared_sources(cfg) == {ECON_CALENDAR}

    def test_book_without_deadline_nodes_does_not(self):
        assert ECON_CALENDAR not in declared_sources(make_cfg("treasury"))

    def test_real_books_declare_what_we_expect(self):
        """Guards the wiring against a book edit that silently drops a feed."""
        import json
        from web.runtime.coordinator import BOOKS_DIR

        iran = json.loads((BOOKS_DIR / "iran-hormuz-graph.json").read_text())
        found = declared_sources(iran)
        assert {"treasury", "fred", "eia", ECON_CALENDAR} <= found
        # gdelt is deliberately absent: iran's only gdelt node is the
        # watch-only rhetoric node, which has no `current` for a value to
        # land in. Its feed exists so the news bridge can serve headlines
        # for this book, and the coordinator must spend no request on it.
        assert "gdelt" not in found

    def test_a_watch_only_node_does_not_declare_its_source(self):
        cfg = {"nodes": [{"id": "watch", "type": "indicator",
                          "feeds": [{"source": "gdelt", "query": "x"}]}]}
        assert declared_sources(cfg) == set()

    def test_the_same_node_declares_it_once_it_can_receive_a_value(self):
        """Reverse direction — opting in with `current` turns the source on."""
        cfg = {"nodes": [{"id": "watch", "type": "indicator", "current": 0,
                          "feeds": [{"source": "gdelt", "query": "x"}]}]}
        assert declared_sources(cfg) == {"gdelt"}

    def test_nodes_with_source_ignores_other_feeds(self):
        cfg = make_cfg("treasury")
        assert [n["id"] for n in nodes_with_source(cfg, "treasury")] == ["yields"]
        assert list(nodes_with_source(cfg, "gdelt")) == []


# =========================================================================
# TTL CACHE
# =========================================================================

class TestTTLCache:
    @pytest.mark.asyncio
    async def test_fetches_once_within_ttl(self, clock):
        """Twelve 300s ticks inside one 3600s TTL = exactly one pull."""
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        outcomes = []
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            for _ in range(12):
                outcomes.append((await r.refresh("book", make_cfg()))["treasury"])
                clock.advance(300)

        assert outcomes[0] == "fetched"
        assert set(outcomes[1:]) == {"cached"}
        assert len(fetcher.calls) == 1

    @pytest.mark.asyncio
    async def test_refetches_after_ttl(self, clock):
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            first = await r.refresh("book", make_cfg())
            clock.advance(3599)
            mid = await r.refresh("book", make_cfg())
            clock.advance(2)
            after = await r.refresh("book", make_cfg())

        assert first == {"treasury": "fetched"}
        assert mid == {"treasury": "cached"}
        assert after == {"treasury": "fetched"}
        assert len(fetcher.calls) == 2

    @pytest.mark.asyncio
    async def test_cache_is_per_thesis(self, clock):
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            await r.refresh("book-a", make_cfg())
            await r.refresh("book-b", make_cfg())

        assert len(fetcher.calls) == 2

    @pytest.mark.asyncio
    async def test_skips_sources_the_book_does_not_declare(self, clock):
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            outcome = await r.refresh("book", make_cfg("gdelt"))

        assert outcome == {}
        assert fetcher.calls == []


# =========================================================================
# THE PATCH PATH — the whole reason the cache exists
# =========================================================================

class TestCachedPatch:
    @pytest.mark.asyncio
    async def test_cached_values_land_in_a_fresh_cfg(self, clock):
        """A tick that skips the fetch must NOT revert the node to its default."""
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            await r.refresh("book", make_cfg(current=1.0))
            clock.advance(300)
            # A brand-new deep copy, exactly as the coordinator builds it.
            fresh = make_cfg(current=1.0)
            outcome = await r.refresh("book", fresh)

        assert outcome == {"treasury": "cached"}
        node = next(n for n in fresh["nodes"] if n["id"] == "yields")
        assert node["current"] == 4.65, "skipped tick reverted the node to its book default"

    @pytest.mark.asyncio
    async def test_patch_does_not_touch_unrelated_nodes(self, clock):
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            await r.refresh("book", make_cfg())
            clock.advance(300)
            fresh = make_cfg()
            await r.refresh("book", fresh)

        assert next(n for n in fresh["nodes"] if n["id"] == "unrelated")["current"] == 99.0

    @pytest.mark.asyncio
    async def test_freshness_carries_the_original_fetch_time(self, clock):
        """The patch path must re-stamp with the REAL pull time.

        Stamping "now" would make a 59-minute-old treasury curve read as
        fetched-this-tick, which turns the entire freshness surface — the
        thing the operator uses to decide whether a number is trustworthy —
        into decoration.
        """
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            first = make_cfg()
            await r.refresh("book", first)
            original = dict(first["_feed_freshness"]["treasury"])

            clock.advance(3000)
            later = make_cfg()
            await r.refresh("book", later)

        assert later["_feed_freshness"]["treasury"] == original
        assert later["_feed_freshness"]["treasury"]["fetchedAt"] == "2026-08-09T04:00:00Z"

    @pytest.mark.asyncio
    async def test_patch_copies_the_freshness_entry(self, clock):
        """Two ticks must not share one mutable dict."""
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            await r.refresh("book", make_cfg())
            clock.advance(300)
            a = make_cfg()
            await r.refresh("book", a)
            b = make_cfg()
            await r.refresh("book", b)

        a["_feed_freshness"]["treasury"]["detail"] = "mutated"
        assert b["_feed_freshness"]["treasury"]["detail"] != "mutated"


# =========================================================================
# KEY GATING
# =========================================================================

class TestKeyGating:
    @pytest.mark.asyncio
    async def test_keyless_source_is_never_invoked(self, clock):
        fred = SourceSpec("fred", 3600.0, env_key="FRED_API_KEY")
        fetcher = make_fetcher("fred", 4.2)
        r = SlowFeedRefresher([fred], env={}, clock=clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_fred", fetcher):
            outcome = await r.refresh("book", make_cfg("fred"))

        assert outcome == {"fred": "no-key"}
        assert fetcher.calls == [], "burned an API attempt with no key configured"

    @pytest.mark.asyncio
    async def test_whitespace_only_key_counts_as_missing(self, clock):
        fred = SourceSpec("fred", 3600.0, env_key="FRED_API_KEY")
        fetcher = make_fetcher("fred", 4.2)
        r = SlowFeedRefresher([fred], env={"FRED_API_KEY": "   "}, clock=clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_fred", fetcher):
            outcome = await r.refresh("book", make_cfg("fred"))

        assert outcome == {"fred": "no-key"}
        assert fetcher.calls == []

    @pytest.mark.asyncio
    async def test_present_key_lights_the_source(self, clock):
        fred = SourceSpec("fred", 3600.0, env_key="FRED_API_KEY")
        fetcher = make_fetcher("fred", 4.2)
        r = SlowFeedRefresher([fred], env={"FRED_API_KEY": "abc123"}, clock=clock)

        cfg = make_cfg("fred")
        with patch.object(slow_feeds.thesisgraph, "fetch_fred", fetcher):
            outcome = await r.refresh("book", cfg)

        assert outcome == {"fred": "fetched"}
        assert len(fetcher.calls) == 1
        assert next(n for n in cfg["nodes"] if n["id"] == "yields")["current"] == 4.2

    @pytest.mark.asyncio
    async def test_keyless_source_leaves_no_freshness_claim(self, clock):
        """No key means nobody has fetched it — the UI must not be told otherwise."""
        fred = SourceSpec("fred", 3600.0, env_key="FRED_API_KEY")
        r = SlowFeedRefresher([fred], env={}, clock=clock)
        cfg = make_cfg("fred")

        with patch.object(slow_feeds.thesisgraph, "fetch_fred", make_fetcher("fred", 1.0)):
            await r.refresh("book", cfg)

        assert "fred" not in (cfg.get("_feed_freshness") or {})


# =========================================================================
# FAILURE DEGRADATION
# =========================================================================

class TestFailureDegradation:
    @pytest.mark.asyncio
    async def test_silent_failure_is_detected(self, clock):
        """A fetcher that resolves nothing must not be recorded as success."""
        r = refresher(TREASURY, clock)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            outcome = await r.refresh("book", make_cfg())

        assert outcome == {"treasury": "defaults"}
        assert r.cached("book", "treasury") is None

    @pytest.mark.asyncio
    async def test_failure_serves_cache_inside_the_grace_window(self, clock):
        r = refresher(TREASURY, clock)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury",
                          make_fetcher("treasury", 4.65)):
            await r.refresh("book", make_cfg())

        clock.advance(3600 * 2)  # TTL expired, well inside TTL*3
        fresh = make_cfg(current=1.0)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            outcome = await r.refresh("book", fresh)

        assert outcome == {"treasury": "stale-cached"}
        assert next(n for n in fresh["nodes"] if n["id"] == "yields")["current"] == 4.65

    @pytest.mark.asyncio
    async def test_failure_falls_back_to_defaults_past_the_grace_window(self, clock):
        r = refresher(TREASURY, clock)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury",
                          make_fetcher("treasury", 4.65)):
            await r.refresh("book", make_cfg())

        clock.advance(3600 * 3 + 1)  # past TTL*3
        fresh = make_cfg(current=1.0)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            outcome = await r.refresh("book", fresh)

        assert outcome == {"treasury": "defaults"}
        assert next(n for n in fresh["nodes"] if n["id"] == "yields")["current"] == 1.0
        assert "treasury" not in (fresh.get("_feed_freshness") or {})
        assert r.cached("book", "treasury") is None, "stale entry must be evicted"

    @pytest.mark.asyncio
    async def test_raising_fetcher_is_treated_as_failure(self, clock):
        def boom(_cfg):
            raise RuntimeError("connection reset")

        r = refresher(TREASURY, clock)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", boom):
            outcome = await r.refresh("book", make_cfg())

        assert outcome == {"treasury": "defaults"}

    @pytest.mark.asyncio
    async def test_refresh_never_raises_on_a_malformed_book(self, clock):
        r = refresher(TREASURY, clock)
        assert await r.refresh("book", {"nodes": "not-a-list"}) == {}
        assert await r.refresh("book", {}) == {}

    @pytest.mark.asyncio
    async def test_defaults_strip_any_freshness_claim(self, clock):
        """Falling back to book defaults must not leave a green badge behind.

        Nothing to serve means nothing to claim — a stamp surviving here is
        the UI telling the operator a number is live while it sits on the
        value someone typed into the book months ago.
        """
        r = refresher(TREASURY, clock)
        cfg = make_cfg()
        cfg["_feed_freshness"] = {
            "treasury": {"source": "treasury", "fetchedAt": "2020-01-01T00:00:00Z",
                         "ttlSeconds": 3600},
        }
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            outcome = await r.refresh("book", cfg)

        assert outcome == {"treasury": "defaults"}
        assert "treasury" not in cfg["_feed_freshness"]


# =========================================================================
# FAILURE BACKOFF
#
# Every test above drives exactly ONE failing refresh, which is why the real
# defect hid here for so long: a failing source was re-attempted on EVERY
# tick while a healthy one was left alone until its TTL expired, so failure
# made the desk poll 3x-72x harder than success. Live consequence on
# 2026-08-09: five books' GDELT nodes retried every 300s tick against a
# per-IP throttle, which kept the throttle warm and starved the news bridge.
# These tests all take at least TWO ticks, in both directions.
# =========================================================================

def counting_failing_fetcher():
    """Resolves nothing, and remembers how many times it was actually run."""
    calls = []

    def fetcher(cfg: dict) -> dict:
        calls.append(cfg)
        return cfg

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


class TestFailureBackoff:
    @pytest.mark.asyncio
    async def test_second_tick_inside_cooldown_does_not_call_the_fetcher(self, clock):
        """The whole point: a failing source is not re-attempted next tick."""
        r = refresher(TREASURY, clock)
        fetcher = counting_failing_fetcher()

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            assert await r.refresh("book", make_cfg()) == {"treasury": "defaults"}
            assert len(fetcher.calls) == 1

            clock.advance(300.0)  # one coordinator tick — inside the cooldown
            assert await r.refresh("book", make_cfg()) == {"treasury": "defaults"}

        assert len(fetcher.calls) == 1, "cooldown must suppress the second attempt"

    @pytest.mark.asyncio
    async def test_attempt_resumes_once_the_cooldown_expires(self, clock):
        """Backoff must delay the retry, never cancel it."""
        r = refresher(TREASURY, clock)
        fetcher = counting_failing_fetcher()

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            await r.refresh("book", make_cfg())
            clock.advance(FAILURE_COOLDOWN_BASE_SECONDS)
            await r.refresh("book", make_cfg())

        assert len(fetcher.calls) == 2

    @pytest.mark.asyncio
    async def test_backoff_doubles_per_consecutive_failure(self, clock):
        r = refresher(TREASURY, clock)
        seen = []

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            for _ in range(3):
                await r.refresh("book", make_cfg())
                retry_at, streak = r.cooldown("book", "treasury")
                seen.append((streak, retry_at - clock.now))
                clock.advance(retry_at - clock.now)  # wait exactly the cooldown

        assert seen == [(1, 600.0), (2, 1200.0), (3, 2400.0)]

    @pytest.mark.asyncio
    async def test_cooldown_never_exceeds_the_source_ttl(self, clock):
        """A broken source must never be polled harder than a working one."""
        gdelt = SourceSpec("gdelt", 900.0)
        r = refresher(gdelt, clock)
        delays = []

        with patch.object(slow_feeds.thesisgraph, "fetch_gdelt", failing_fetcher):
            for _ in range(5):
                await r.refresh("book", make_cfg("gdelt"))
                retry_at, _streak = r.cooldown("book", "gdelt")
                delays.append(retry_at - clock.now)
                clock.advance(retry_at - clock.now)

        assert delays == [600.0, 900.0, 900.0, 900.0, 900.0]
        assert max(delays) <= gdelt.ttl_seconds

    @pytest.mark.asyncio
    async def test_a_good_pull_clears_the_streak(self, clock):
        """Recovery must reset the backoff, not inherit an old one."""
        r = refresher(TREASURY, clock)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            await r.refresh("book", make_cfg())
        assert r.cooldown("book", "treasury")[1] == 1

        clock.advance(FAILURE_COOLDOWN_BASE_SECONDS)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury",
                          make_fetcher("treasury", 4.65)):
            assert await r.refresh("book", make_cfg()) == {"treasury": "fetched"}
        assert r.cooldown("book", "treasury") is None

        clock.advance(3601.0)  # TTL expired, so the next tick really fetches
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            await r.refresh("book", make_cfg())

        retry_at, streak = r.cooldown("book", "treasury")
        assert (streak, retry_at - clock.now) == (1, FAILURE_COOLDOWN_BASE_SECONDS)

    @pytest.mark.asyncio
    async def test_a_marathon_outage_does_not_overflow_the_delay(self, clock):
        """2 ** streak is an int, and a long enough outage blows the multiply.

        WHY the streak is seeded rather than looped up to: the overflow only
        bites past ~1015 consecutive failures, so a loop long enough to reach
        it would hide the guard behind its own runtime — and a shorter loop
        proves nothing, because the TTL cap returns a correct answer either
        way. Seeding removes exactly that shadow, and the refresh below is
        still the real public path.
        """
        r = refresher(TREASURY, clock)
        r._cooldowns[("book", "treasury")] = (clock.now, 5_000)

        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", failing_fetcher):
            await r.refresh("book", make_cfg())

        retry_at, streak = r.cooldown("book", "treasury")
        assert streak == 5_001, "the arm must have completed, not raised"
        assert retry_at - clock.now == TREASURY.ttl_seconds

    @pytest.mark.asyncio
    async def test_cooldown_still_serves_the_last_good_value(self, clock):
        """Backoff must cost upstream requests, never the operator's number."""
        r = refresher(TREASURY, clock)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury",
                          make_fetcher("treasury", 4.65)):
            await r.refresh("book", make_cfg())

        clock.advance(3600 * 2)  # TTL expired, inside the grace window
        fetcher = counting_failing_fetcher()
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            assert await r.refresh("book", make_cfg(current=1.0)) == {
                "treasury": "stale-cached"}

            clock.advance(60.0)  # inside cooldown
            cfg = make_cfg(current=1.0)
            assert await r.refresh("book", cfg) == {"treasury": "stale-cached"}

        assert len(fetcher.calls) == 1, "cooldown must suppress the second attempt"
        assert next(n for n in cfg["nodes"] if n["id"] == "yields")["current"] == 4.65


# =========================================================================
# LOCK-HOLD BUDGET
#
# The refresh runs inside the fetch cycle, which holds the per-thesis lock.
# Every fetcher retries behind a 20s socket timeout, so without a ceiling of
# our own the lock hold is whatever the slowest endpoint decides.
# =========================================================================

class TestTimeoutBudget:
    SLOW = SourceSpec("treasury", 3600.0, timeout_seconds=0.05)

    @staticmethod
    def blocking_fetcher(cfg):
        import time as _t
        _t.sleep(1.0)
        cfg.setdefault("_feed_freshness", {})["treasury"] = {
            "source": "treasury", "fetchedAt": "late", "ttlSeconds": 3600}
        for node in cfg.get("nodes", []):
            if node.get("id") == "yields":
                node["current"] = 999.0
        return cfg

    @pytest.mark.asyncio
    async def test_overrunning_fetch_is_abandoned(self, clock):
        r = SlowFeedRefresher([self.SLOW], env={}, clock=clock)
        cfg = make_cfg(current=1.0)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", self.blocking_fetcher):
            outcome = await r.refresh("book", cfg)

        assert outcome == {"treasury": "defaults"}
        assert next(n for n in cfg["nodes"] if n["id"] == "yields")["current"] == 1.0

    @pytest.mark.asyncio
    async def test_the_abandoned_thread_cannot_reach_the_live_cfg(self, clock):
        """wait_for cancels the await, not the thread. The straggler must only
        ever be able to write to a cfg nobody will read again — otherwise it
        mutates node values while propagate() is walking them."""
        r = SlowFeedRefresher([self.SLOW], env={}, clock=clock)
        cfg = make_cfg(current=1.0)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", self.blocking_fetcher):
            await r.refresh("book", cfg)
            # Outlive the abandoned thread and re-check the live cfg.
            await asyncio.sleep(1.3)

        assert next(n for n in cfg["nodes"] if n["id"] == "yields")["current"] == 1.0
        assert "treasury" not in (cfg.get("_feed_freshness") or {})

    @pytest.mark.asyncio
    async def test_timeout_still_serves_cache_inside_the_grace_window(self, clock):
        r = SlowFeedRefresher([self.SLOW], env={}, clock=clock)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury",
                          make_fetcher("treasury", 4.65)):
            await r.refresh("book", make_cfg())

        clock.advance(3600 * 2)
        fresh = make_cfg(current=1.0)
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", self.blocking_fetcher):
            outcome = await r.refresh("book", fresh)

        assert outcome == {"treasury": "stale-cached"}
        assert next(n for n in fresh["nodes"] if n["id"] == "yields")["current"] == 4.65

    @pytest.mark.asyncio
    async def test_fetcher_is_handed_a_copy_not_the_live_cfg(self, clock):
        fetcher = make_fetcher("treasury", 4.65)
        r = refresher(TREASURY, clock)
        cfg = make_cfg()
        with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
            await r.refresh("book", cfg)

        assert fetcher.calls[0] is not cfg
        # The harvested value still reaches the live cfg via the patch path.
        assert next(n for n in cfg["nodes"] if n["id"] == "yields")["current"] == 4.65

    def test_shipped_budgets_are_bounded(self):
        for spec in slow_feeds.SOURCE_SPECS:
            assert 0 < spec.timeout_seconds <= 60, spec.name
        # Worst case for one book is the sum — it must stay under a tick.
        assert sum(s.timeout_seconds for s in slow_feeds.SOURCE_SPECS) < 300


# =========================================================================
# ECON CALENDAR
# =========================================================================

class TestIsStaleDeadline:
    TODAY = date(2026, 8, 9)

    def test_passed_deadline_yields_to_a_future_event(self):
        assert is_stale_deadline("2026-05-01", "2026-09-18", self.TODAY) is True

    def test_future_deadline_is_left_alone(self):
        """A book author who typed a future date knows more than a fuzzy match."""
        assert is_stale_deadline("2026-12-01", "2026-09-18", self.TODAY) is False

    def test_todays_deadline_is_not_stale(self):
        assert is_stale_deadline("2026-08-09", "2026-09-18", self.TODAY) is False

    def test_missing_deadline_takes_the_event(self):
        assert is_stale_deadline(None, "2026-09-18", self.TODAY) is True

    def test_never_patches_in_a_passed_event(self):
        assert is_stale_deadline("2026-05-01", "2026-07-01", self.TODAY) is False

    def test_no_candidate_is_never_stale(self):
        assert is_stale_deadline("2026-05-01", None, self.TODAY) is False

    def test_garbage_candidate_is_rejected(self):
        assert is_stale_deadline("2026-05-01", "next tuesday", self.TODAY) is False

    def test_garbage_current_yields_to_a_valid_event(self):
        assert is_stale_deadline("TBD", "2026-09-18", self.TODAY) is True


class TestEconCalendar:
    @staticmethod
    def _cfg(deadline):
        return {"nodes": [{"id": "boj-decision", "type": "deadline",
                           "label": "BoJ Policy Decision", "deadline": deadline}]}

    @staticmethod
    def _patches(events, mapping):
        return (
            patch.object(slow_feeds.econ_calendar, "get_calendar",
                         AsyncMock(return_value=events)),
            patch.object(slow_feeds.econ_calendar, "for_book",
                         AsyncMock(return_value=mapping)),
        )

    @pytest.mark.asyncio
    async def test_repoints_a_passed_deadline(self, clock):
        future = (date.today() + timedelta(days=40)).isoformat()
        past = (date.today() - timedelta(days=40)).isoformat()
        events = [{"event_id": "boj-2026-09", "date": future}]
        cal, book = self._patches(events, {"boj-decision": events[0]})

        r = SlowFeedRefresher([SourceSpec(ECON_CALENDAR, 21600.0)], env={}, clock=clock)
        cfg = self._cfg(past)
        with cal, book:
            outcome = await r.refresh("japan-rate-shock-graph", cfg)

        assert outcome == {ECON_CALENDAR: "fetched"}
        assert cfg["nodes"][0]["deadline"] == future

    @pytest.mark.asyncio
    async def test_leaves_a_live_deadline_alone(self, clock):
        near = (date.today() + timedelta(days=10)).isoformat()
        far = (date.today() + timedelta(days=40)).isoformat()
        events = [{"event_id": "boj-2026-09", "date": far}]
        cal, book = self._patches(events, {"boj-decision": events[0]})

        r = SlowFeedRefresher([SourceSpec(ECON_CALENDAR, 21600.0)], env={}, clock=clock)
        cfg = self._cfg(near)
        with cal, book:
            await r.refresh("japan-rate-shock-graph", cfg)

        assert cfg["nodes"][0]["deadline"] == near

    @pytest.mark.asyncio
    async def test_unreachable_calendar_is_a_failure_not_an_empty_success(self, clock):
        """for_book() returns {} both when the calendar is down and when
        nothing matched. Conflating them would stamp freshness on an outage
        and then hold the 6h TTL over it."""
        r = SlowFeedRefresher([SourceSpec(ECON_CALENDAR, 21600.0)], env={}, clock=clock)
        cfg = self._cfg("2026-05-01")
        cal, book = self._patches([], {})
        with cal, book:
            outcome = await r.refresh("japan-rate-shock-graph", cfg)

        assert outcome == {ECON_CALENDAR: "defaults"}
        assert ECON_CALENDAR not in (cfg.get("_feed_freshness") or {})

    @pytest.mark.asyncio
    async def test_no_match_still_holds_the_ttl(self, clock):
        """A successful pull that matched nothing must not re-poll every tick."""
        events = [{"event_id": "cpi-2026-09", "date":
                   (date.today() + timedelta(days=20)).isoformat()}]
        cal = patch.object(slow_feeds.econ_calendar, "get_calendar",
                           AsyncMock(return_value=events))
        book = patch.object(slow_feeds.econ_calendar, "for_book",
                            AsyncMock(return_value={}))

        r = SlowFeedRefresher([SourceSpec(ECON_CALENDAR, 21600.0)], env={}, clock=clock)
        with cal, book:
            first = await r.refresh("japan-rate-shock-graph", self._cfg("2026-05-01"))
            clock.advance(300)
            second = await r.refresh("japan-rate-shock-graph", self._cfg("2026-05-01"))

        assert first == {ECON_CALENDAR: "fetched"}
        assert second == {ECON_CALENDAR: "cached"}

    @pytest.mark.asyncio
    async def test_calendar_stamps_freshness_in_the_engine_shape(self, clock):
        future = (date.today() + timedelta(days=40)).isoformat()
        events = [{"event_id": "boj-2026-09", "date": future}]
        cal, book = self._patches(events, {"boj-decision": events[0]})

        r = SlowFeedRefresher([SourceSpec(ECON_CALENDAR, 21600.0)], env={}, clock=clock)
        cfg = self._cfg((date.today() - timedelta(days=5)).isoformat())
        with cal, book:
            await r.refresh("japan-rate-shock-graph", cfg)

        stamp = cfg["_feed_freshness"][ECON_CALENDAR]
        assert stamp["source"] == ECON_CALENDAR
        assert stamp["ttlSeconds"] == 21600
        assert stamp["fetchedAt"].endswith("Z")

    @pytest.mark.asyncio
    async def test_cached_deadline_survives_a_skipped_tick(self, clock):
        future = (date.today() + timedelta(days=40)).isoformat()
        past = (date.today() - timedelta(days=40)).isoformat()
        events = [{"event_id": "boj-2026-09", "date": future}]
        cal, book = self._patches(events, {"boj-decision": events[0]})

        r = SlowFeedRefresher([SourceSpec(ECON_CALENDAR, 21600.0)], env={}, clock=clock)
        with cal, book:
            await r.refresh("japan-rate-shock-graph", self._cfg(past))
            clock.advance(300)
            fresh = self._cfg(past)
            await r.refresh("japan-rate-shock-graph", fresh)

        assert fresh["nodes"][0]["deadline"] == future


# =========================================================================
# COORDINATOR INTEGRATION — does any of this reach a snapshot?
# =========================================================================

class TestCoordinatorIntegration:
    @pytest.mark.asyncio
    async def test_slow_values_reach_the_committed_snapshot(self):
        """The end the whole task exists for: a treasury value in a snapshot.

        Drives the real cycle, real propagate(), real save_snapshot — only
        the outbound calls are stubbed.
        """
        repo = Repository(":memory:")
        repo.initialize()
        ws = MagicMock()
        ws.broadcast_to_book_rooms = AsyncMock(return_value=0)

        clock = FakeClock()
        refresh = SlowFeedRefresher([TREASURY], env={}, clock=clock)
        coord = RuntimeCoordinator(repo=repo, ws_manager=ws, tick_interval=9999,
                                   slow_feeds=refresh)
        coord._load_definitions()
        coord._hydrate_from_db()

        fetcher = make_fetcher("treasury", 4.65, node_id="rates-term-premium")

        from web.runtime.test_coordinator import no_network
        with no_network():
            with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
                snap = await coord._run_cycle("iran-hormuz-graph")

        assert len(fetcher.calls) == 1
        assert snap["feedFreshness"]["treasury"]["fetchedAt"] == "2026-08-09T04:00:00Z"

        stored = repo.get_latest_snapshot("iran-hormuz-graph")
        assert stored["feedFreshness"]["treasury"]["ttlSeconds"] == 3600

    @pytest.mark.asyncio
    async def test_slow_values_are_recorded_for_restart_recovery(self):
        """Slow values must ride into fetch_runs — otherwise a restart inside
        a TTL window brings the node back at its book default."""
        repo = Repository(":memory:")
        repo.initialize()
        ws = MagicMock()
        ws.broadcast_to_book_rooms = AsyncMock(return_value=0)

        refresh = SlowFeedRefresher([TREASURY], env={}, clock=FakeClock())
        coord = RuntimeCoordinator(repo=repo, ws_manager=ws, tick_interval=9999,
                                   slow_feeds=refresh)
        coord._load_definitions()
        coord._hydrate_from_db()

        fetcher = make_fetcher("treasury", 4.65, node_id="rates-term-premium")

        from web.runtime.test_coordinator import no_network
        with no_network():
            with patch.object(slow_feeds.thesisgraph, "fetch_treasury", fetcher):
                await coord._run_cycle("iran-hormuz-graph")

        values = repo.get_latest_provider_values("iran-hormuz-graph")
        assert values["rates-term-premium"] == 4.65

    @pytest.mark.asyncio
    async def test_a_broken_slow_feed_does_not_fail_the_cycle(self):
        repo = Repository(":memory:")
        repo.initialize()
        ws = MagicMock()
        ws.broadcast_to_book_rooms = AsyncMock(return_value=0)

        broken = MagicMock()
        broken.refresh = AsyncMock(side_effect=RuntimeError("everything is on fire"))
        coord = RuntimeCoordinator(repo=repo, ws_manager=ws, tick_interval=9999,
                                   slow_feeds=broken)
        coord._load_definitions()
        coord._hydrate_from_db()

        from web.runtime.test_coordinator import no_network
        with no_network():
            snap = await coord._run_cycle("iran-hormuz-graph")

        # The refresher's own contract is never-raise. This pins the second
        # belt: if a future edit breaks that contract, the cycle still
        # commits a snapshot instead of the desk going dark.
        assert broken.refresh.await_count == 1
        assert snap["revision"] == 1
        assert repo.get_latest_snapshot("iran-hormuz-graph") is not None

    def test_coordinator_builds_a_refresher_by_default(self):
        repo = Repository(":memory:")
        repo.initialize()
        coord = RuntimeCoordinator(repo=repo, ws_manager=MagicMock())
        assert isinstance(coord._slow_feeds, SlowFeedRefresher)

    def test_shipped_specs_cover_every_dormant_source(self):
        names = {s.name for s in slow_feeds.SOURCE_SPECS}
        assert names == {"treasury", "gdelt", "fred", "eia", ECON_CALENDAR}
        by_name = {s.name: s for s in slow_feeds.SOURCE_SPECS}
        assert by_name["treasury"].ttl_seconds == 3600
        assert by_name["gdelt"].ttl_seconds == 900
        assert by_name[ECON_CALENDAR].ttl_seconds == 21600
        assert by_name["fred"].env_key == "FRED_API_KEY"
        assert by_name["eia"].env_key == "EIA_API_KEY"
        assert by_name["treasury"].env_key is None
        assert by_name["gdelt"].env_key is None
