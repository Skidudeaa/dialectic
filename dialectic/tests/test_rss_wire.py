"""
Tests for llm/rss_wire.py — the watchlist's first reader.

WHY this file exists: the RSS wire speaks through the SAME interjection
budget as the GDELT wire — that sharing is load-bearing (the 2026-08-15
volume lesson: every separately-budgeted speaker compounds into noise), so
it is pinned here three ways: by identity (rss_wire posts through wire's
own functions), by the ledger query's bind args (reason =
'wire_interjection'), and by behavior (a capped room declines before any
model call). The rest mirrors tests/test_wire.py: feed parse defensive,
dedup, cooldowns, thin gate — plus the per-source floor override that only
a tagged social feed earns.

The thin-floor mutation fences live here too (this file owns them): the
global 80-word floor is asserted BEHAVIORALLY, so lowering
THIN_CONTENT_MIN_WORDS — or widening SOURCE_THIN_FLOORS' reach — goes red.
"""

from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from scheduler import Scheduler, SchedulerContext
from llm import reading, rss_wire, wire


ROOM_ID = uuid4()
BOOK = "iran-war"
FEED_URL = "https://example.com/feed.xml"

RSS2_FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example Wire</title>
  <item>
    <title>Story One</title>
    <link>https://example.com/one</link>
    <pubDate>Mon, 17 Aug 2026 12:00:00 GMT</pubDate>
    <guid>https://example.com/one</guid>
  </item>
  <item>
    <title>Story Two</title>
    <link>https://example.com/two</link>
  </item>
  <item>
    <title>No link, guid is a URL</title>
    <guid>https://example.com/three</guid>
  </item>
  <item>
    <title>No link at all</title>
    <guid isPermaLink="false">tag:example,2026:broken</guid>
  </item>
</channel></rss>
"""

def make_flood_feed(host: str, n: int) -> bytes:
    """An RSS 2.0 feed of n items, all on one host — the domain-cap fixture."""
    items = "".join(
        f"<item><title>S{i}</title><link>https://{host}/p{i}</link></item>"
        for i in range(1, n + 1)
    )
    return (f'<?xml version="1.0"?><rss version="2.0"><channel>'
            f"{items}</channel></rss>").encode()


ATOM_FEED = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Wire</title>
  <entry>
    <title>Atom Story</title>
    <link rel="alternate" href="https://example.com/atom-1"/>
    <link rel="self" href="https://example.com/feed.atom"/>
    <id>tag:example,2026:a1</id>
    <published>2026-08-17T12:00:00Z</published>
  </entry>
  <entry>
    <title>Bare link counts as alternate</title>
    <link href="https://example.com/atom-2"/>
    <updated>2026-08-17T13:00:00Z</updated>
  </entry>
  <entry>
    <title>Only an id, and it is a URL</title>
    <id>https://example.com/atom-3</id>
  </entry>
</feed>
"""


# =========================================================================
# Feed parsing — defensive, stdlib-only
# =========================================================================


class TestParseFeed:
    def test_rss2_items(self):
        items = rss_wire._parse_feed(RSS2_FEED)
        assert [i["url"] for i in items] == [
            "https://example.com/one",
            "https://example.com/two",
            "https://example.com/three",
        ]
        assert items[0]["title"] == "Story One"
        assert items[0]["published"] == "Mon, 17 Aug 2026 12:00:00 GMT"
        # No link and a non-URL guid → dropped, never guessed.

    def test_atom_entries(self):
        items = rss_wire._parse_feed(ATOM_FEED)
        assert [i["url"] for i in items] == [
            "https://example.com/atom-1",
            "https://example.com/atom-2",
            "https://example.com/atom-3",
        ]
        assert items[0]["title"] == "Atom Story"
        assert items[0]["published"] == "2026-08-17T12:00:00Z"
        assert items[1]["published"] == "2026-08-17T13:00:00Z"

    def test_malformed_xml_is_empty(self):
        assert rss_wire._parse_feed(b"this is not xml <<<") == []

    def test_empty_body_is_empty(self):
        assert rss_wire._parse_feed(b"") == []

    def test_html_page_is_empty_or_linkless(self):
        # A misconfigured entry pointing at an HTML page must not invent items.
        html = b"<html><body><p>hello</p></body></html>"
        assert rss_wire._parse_feed(html) == []


# =========================================================================
# Watchlist consumption — {type:"rss"} only, everything else ignored
# =========================================================================


class TestRssEntries:
    def test_consumes_only_rss_entries(self):
        watchlist = [
            {"type": "gdelt_book", "value": "iran-war"},
            {"type": "url", "value": "https://example.com/page"},
            {"type": "rss", "value": FEED_URL},
            {"type": "rss", "value": "https://social.example/rss", "tag": "social"},
        ]
        entries = rss_wire._rss_entries(watchlist)
        assert entries == [
            {"url": FEED_URL, "tag": None},
            {"url": "https://social.example/rss", "tag": "social"},
        ]

    def test_garbage_shapes_are_skipped(self):
        assert rss_wire._rss_entries(None) == []
        assert rss_wire._rss_entries({"type": "rss", "value": FEED_URL}) == []
        assert rss_wire._rss_entries(["a string", 42, {"type": "rss"}]) == []
        assert rss_wire._rss_entries(
            [{"type": "rss", "value": "ftp://not-http.example"}]) == []

    def test_non_string_tag_is_dropped(self):
        entries = rss_wire._rss_entries(
            [{"type": "rss", "value": FEED_URL, "tag": 7}])
        assert entries == [{"url": FEED_URL, "tag": None}]


# =========================================================================
# The thin floor — per-source override, global floor fenced
# =========================================================================


class TestThinFloor:
    def _article(self, words):
        return {"content": "x " * words, "word_count": words}

    def test_global_floor_is_80_behaviorally(self):
        """MUTATION FENCE: lowering THIN_CONTENT_MIN_WORDS makes a 79-word
        page pass and this test fail. The global floor must not move."""
        assert reading.is_thin(self._article(79)) is True
        assert reading.is_thin(self._article(80)) is False

    def test_social_floor_admits_a_short_post(self):
        assert reading.is_thin(self._article(30), source_tag="social") is False
        assert reading.is_thin(self._article(24), source_tag="social") is True

    def test_default_path_ignores_the_social_floor(self):
        """MUTATION FENCE (reverse): a 30-word page with NO tag is still
        thin — the override must never leak into the default path."""
        assert reading.is_thin(self._article(30)) is True

    def test_unknown_tag_uses_the_global_floor(self):
        assert reading.is_thin(self._article(30), source_tag="premium") is True

    def test_empty_content_is_thin_at_any_floor(self):
        assert reading.is_thin(
            {"content": "", "word_count": 999}, source_tag="social") is True


# =========================================================================
# The shared interjection budget — the load-bearing reuse
# =========================================================================


class TestSharedBudget:
    def test_posts_through_wires_own_functions(self):
        """Identity, not equality: rss_wire must not grow its own interject
        or its own counter — a local copy could drift to a new reason and
        split the budget into two numbers."""
        assert rss_wire._interject is wire._interject
        assert rss_wire._interjections_today is wire._interjections_today

    def test_caps_are_wires_caps(self):
        assert rss_wire.WIRE_DAILY_CAP is wire.WIRE_DAILY_CAP
        assert rss_wire.WIRE_PER_ROOM_CAP is wire.WIRE_PER_ROOM_CAP
        assert rss_wire.WIRE_FEED_SCAN_CAP is wire.WIRE_FEED_SCAN_CAP

    def test_domain_cap_is_wires_helper(self):
        """Identity again: a local cap_by_domain (or a local cap constant)
        could drift to its own N and split the Phase 7 bias control into
        two rules. Imported, never copied."""
        assert rss_wire.cap_by_domain is wire.cap_by_domain
        assert rss_wire._domain_cap is wire._domain_cap

    def test_stance_summary_is_wires_helper(self):
        assert rss_wire._stance_summary is wire._stance_summary


# =========================================================================
# rss_wire_watch — the per-room pipeline
# =========================================================================


@pytest.fixture(autouse=True)
def clear_cooldowns() -> Generator[None, None, None]:
    rss_wire._fetch_cooldowns.clear()
    yield
    rss_wire._fetch_cooldowns.clear()


def make_room_row(**overrides):
    room = {
        "id": ROOM_ID,
        "name": "Hormuz Room",
        "linked_book_id": BOOK,
        "auto_interjection_enabled": True,
        "trading_config": '{"claim": "Hormuz disruption lifts Brent"}',
        "watchlist": [{"type": "rss", "value": FEED_URL}],
    }
    room.update(overrides)
    return room


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def make_db(*, rooms, seen=(), interjections_today=0):
    """Mock asyncpg connection covering every query rss_wire_watch makes."""
    db = AsyncMock()

    async def _fetch(sql, *args):
        if "FROM rooms" in sql:
            return list(rooms)
        if "SELECT url FROM reading_items" in sql:
            return [{"url": u} for u in seen]
        return []

    async def _fetchval(sql, *args):
        if "FROM llm_decisions" in sql:
            return interjections_today
        return 0

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchval = AsyncMock(side_effect=_fetchval)
    db.fetchrow = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mocks(monkeypatch):
    """Stub the externals: feed bytes, extractor, scorer, saver, interject."""
    m = SimpleNamespace(
        feeds={FEED_URL: RSS2_FEED},
        feed_errors={},
        extract_word_count=800,
        extract_errors={},
        score={"score": 0.9, "why": "Bears on node 2's trigger."},
        feed_calls=[], extract_calls=[], score_calls=[], saved=[],
        interjections=[],
    )

    def _fetch_feed(url):
        m.feed_calls.append(url)
        if url in m.feed_errors:
            raise m.feed_errors[url]
        return m.feeds.get(url, b"")

    async def _extract(url):
        m.extract_calls.append(url)
        if url in m.extract_errors:
            raise m.extract_errors[url]
        return {"url": url, "title": f"Title for {url}", "author": None,
                "site": "Example", "published": "2026-08-17",
                "word_count": m.extract_word_count,
                "content": f"Body of {url}"}

    async def _score(article, thesis_context):
        m.score_calls.append(article["url"])
        return m.score

    async def _save(db, room_id, article, summary, key_claims, source, **kw):
        m.saved.append({"room_id": room_id, "url": article["url"],
                        "summary": summary, "source": source})
        return {"url": article["url"], "title": article.get("title")}

    async def _interject(ctx, conn, room_id, article, verdict):
        m.interjections.append({"room_id": room_id, "url": article["url"]})
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(rss_wire, "_fetch_feed_bytes", _fetch_feed)
    monkeypatch.setattr(rss_wire.dc, "extract_article", _extract)
    monkeypatch.setattr(rss_wire, "_score", _score)
    monkeypatch.setattr(rss_wire, "save_reading", _save)
    monkeypatch.setattr(rss_wire, "_interject", _interject)
    return m


def _ctx(db):
    return SchedulerContext(pool=FakePool(db), broadcast=AsyncMock())


@pytest.mark.asyncio
class TestRssWireWatch:
    @pytest.fixture(autouse=True)
    def daytime(self, monkeypatch):
        """Pin the run outside quiet hours (the wire tests' lesson)."""
        monkeypatch.setattr(rss_wire, "in_quiet_hours", lambda now=None: False)

    async def test_files_and_interjects_above_threshold(self, mocks):
        db = make_db(rooms=[make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))

        assert mocks.feed_calls == [FEED_URL]
        # 3 parseable items, readable cap 2 (wire's WIRE_PER_ROOM_CAP).
        assert mocks.extract_calls == [
            "https://example.com/one", "https://example.com/two",
        ]
        assert len(mocks.saved) == 2
        assert all(s["source"] == "wire" for s in mocks.saved)
        assert mocks.saved[0]["summary"] == "Bears on node 2's trigger."
        assert len(mocks.interjections) == 2

        entry = detail[str(ROOM_ID)]
        assert len(entry["filed"]) == 2
        assert len(entry["interjected"]) == 2

    async def test_ignores_non_rss_watchlist_entries(self, mocks):
        room = make_room_row(watchlist=[
            {"type": "gdelt_book", "value": BOOK},
            {"type": "url", "value": "https://example.com/page"},
        ])
        db = make_db(rooms=[room])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert detail[str(ROOM_ID)] == "no_rss_entries"
        assert mocks.feed_calls == []

    async def test_seen_urls_are_never_extracted(self, mocks):
        db = make_db(rooms=[make_room_row()],
                     seen=("https://example.com/one",
                           "https://example.com/two",
                           "https://example.com/three"))
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert detail[str(ROOM_ID)] == "all_seen"
        assert mocks.extract_calls == []

    async def test_duplicate_urls_across_feeds_scanned_once(self, mocks):
        room = make_room_row(watchlist=[
            {"type": "rss", "value": FEED_URL},
            {"type": "rss", "value": "https://mirror.example/feed"},
        ])
        mocks.feeds["https://mirror.example/feed"] = RSS2_FEED
        db = make_db(rooms=[room])
        await rss_wire.rss_wire_watch(_ctx(db))
        # The mirror repeats the same three URLs; each extracts at most once.
        assert len(mocks.extract_calls) == len(set(mocks.extract_calls))

    async def test_failed_feed_is_cooled_and_recorded(self, mocks):
        mocks.feed_errors[FEED_URL] = OSError("connection refused")
        db = make_db(rooms=[make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        entry = detail[str(ROOM_ID)]
        assert entry["skipped"] == [
            {"feed": FEED_URL, "reason": "fetch_or_parse_failed"}]
        assert rss_wire._in_fetch_cooldown(FEED_URL)

        # Second run inside the cooldown: no refetch.
        mocks.feed_calls.clear()
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert mocks.feed_calls == []
        assert detail[str(ROOM_ID)]["skipped"] == [
            {"feed": FEED_URL, "reason": "fetch_cooldown"}]

    async def test_unparseable_feed_is_cooled(self, mocks):
        mocks.feeds[FEED_URL] = b"<html>not a feed</html>"
        db = make_db(rooms=[make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert rss_wire._in_fetch_cooldown(FEED_URL)
        assert detail[str(ROOM_ID)]["filed"] == []

    async def test_extract_failure_cools_the_article_url(self, mocks):
        mocks.extract_errors["https://example.com/one"] = (
            rss_wire.dc.DefuddleError("blocked"))
        db = make_db(rooms=[make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert rss_wire._in_fetch_cooldown("https://example.com/one")
        # The failure did not consume a READABLE slot — but the feed is
        # single-host, so the Phase 7 domain cap (2/domain) admitted only
        # items one and two; item two alone survives to filing.
        assert len(mocks.saved) == 1
        assert mocks.saved[0]["url"] == "https://example.com/two"
        skipped = detail[str(ROOM_ID)]["skipped"]
        assert {"url": "https://example.com/one",
                "reason": "extract_failed"} in skipped

    async def test_toggle_off_room_is_skipped(self, mocks):
        db = make_db(rooms=[make_room_row(auto_interjection_enabled=False)])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert detail[str(ROOM_ID)] == "toggle_off"
        assert mocks.feed_calls == []

    async def test_quiet_hours_skip_everything(self, mocks, monkeypatch):
        monkeypatch.setattr(rss_wire, "in_quiet_hours", lambda now=None: True)
        db = make_db(rooms=[make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert detail == {"skipped": "quiet_hours"}
        assert mocks.feed_calls == []

    async def test_below_threshold_files_nothing(self, mocks):
        mocks.score = {"score": 0.3, "why": "tangential"}
        db = make_db(rooms=[make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert mocks.saved == []
        assert mocks.interjections == []
        reasons = {s["reason"] for s in detail[str(ROOM_ID)]["skipped"]}
        assert reasons == {"below_threshold"}

    # ---- the shared budget, behaviorally --------------------------------

    async def test_capped_room_declines_before_any_model_call(self, mocks):
        """THE load-bearing test: with the ledger at wire's daily cap —
        however those interjections were spent, GDELT or RSS — this job
        stands down for the room without fetching, scoring, or speaking.
        One budget, one number."""
        db = make_db(rooms=[make_room_row()],
                     interjections_today=wire.WIRE_DAILY_CAP)
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert detail[str(ROOM_ID)] == "cap_reached"
        assert mocks.feed_calls == []
        assert mocks.score_calls == []
        assert mocks.interjections == []

    async def test_budget_is_counted_under_wire_interjection(self, mocks):
        """The counter queries the llm_decisions ledger for wire's OWN
        reason string — the literal mechanism that keeps the daily cap one
        number across both wires."""
        db = make_db(rooms=[make_room_row()])
        await rss_wire.rss_wire_watch(_ctx(db))
        ledger_calls = [c for c in db.fetchval.await_args_list
                        if "llm_decisions" in c.args[0]]
        assert ledger_calls, "the shared counter was never consulted"
        assert all("wire_interjection" in c.args for c in ledger_calls)

    # ---- the per-source thin floor, wired end to end --------------------

    async def test_social_tag_admits_a_short_post(self, mocks):
        room = make_room_row(watchlist=[
            {"type": "rss", "value": FEED_URL, "tag": "social"}])
        mocks.extract_word_count = 30
        db = make_db(rooms=[room])
        await rss_wire.rss_wire_watch(_ctx(db))
        # 30 words would be thin on the global floor; the social floor (25)
        # lets it through to scoring and filing.
        assert len(mocks.score_calls) == 2
        assert len(mocks.saved) == 2

    async def test_untagged_short_extraction_is_still_thin(self, mocks):
        mocks.extract_word_count = 30
        db = make_db(rooms=[make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert mocks.score_calls == []
        assert mocks.saved == []
        reasons = {s["reason"] for s in detail[str(ROOM_ID)]["skipped"]}
        assert reasons == {"thin_content"}

    # ---- the per-domain cap, through the netloc path (Phase 7) ----------

    async def test_domain_cap_lets_a_second_feed_into_the_window(self, mocks):
        """Behaviorally: six unreadable items from one prolific host would
        fill wire.WIRE_FEED_SCAN_CAP on their own; the shared domain cap
        (netloc-derived — RSS items carry no domain field) holds the host
        to two, so the quieter feed's story is reached and filed."""
        prolific = "https://prolific.example/feed.xml"
        quiet = "https://quiet.example/feed.xml"
        room = make_room_row(watchlist=[
            {"type": "rss", "value": prolific},
            {"type": "rss", "value": quiet},
        ])
        mocks.feeds[prolific] = make_flood_feed("prolific.example", 6)
        mocks.feeds[quiet] = make_flood_feed("quiet.example", 1)
        for i in range(1, 7):
            mocks.extract_errors[f"https://prolific.example/p{i}"] = (
                rss_wire.dc.DefuddleError("blocked"))
        db = make_db(rooms=[room])
        await rss_wire.rss_wire_watch(_ctx(db))

        assert "https://quiet.example/p1" in mocks.extract_calls
        assert [s["url"] for s in mocks.saved] == [
            "https://quiet.example/p1"]

    async def test_stance_marker_rides_the_filed_summary(self, mocks):
        mocks.score = {"score": 0.9, "why": "Cuts against node 2.",
                       "stance": "contradicts"}
        db = make_db(rooms=[make_room_row()])
        await rss_wire.rss_wire_watch(_ctx(db))
        assert all(
            s["summary"] == "Cuts against node 2. [stance: contradicts]"
            for s in mocks.saved
        )

    # ---- resilience -----------------------------------------------------

    async def test_broken_room_does_not_sink_the_run(self, mocks):
        other_id = uuid4()
        broken = make_room_row(id=other_id, watchlist="not-a-list-and-truthy")
        # A watchlist that is a truthy non-list is just "no rss entries".
        db = make_db(rooms=[broken, make_room_row()])
        detail = await rss_wire.rss_wire_watch(_ctx(db))
        assert detail[str(other_id)] == "no_rss_entries"
        assert len(detail[str(ROOM_ID)]["filed"]) == 2


# =========================================================================
# Job registration
# =========================================================================


class TestRegistration:
    def test_registers_interval_job(self):
        sched = Scheduler(SchedulerContext(pool=None))
        rss_wire.register_rss_wire_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "rss_wire"
        assert job.interval_s == 900
        assert job.enabled_env == "RSS_WIRE_ENABLED"

    def test_env_gate(self, monkeypatch):
        sched = Scheduler(SchedulerContext(pool=None))
        rss_wire.register_rss_wire_jobs(sched)
        monkeypatch.setenv("RSS_WIRE_ENABLED", "0")
        assert not sched.jobs[0].enabled()
        monkeypatch.setenv("RSS_WIRE_ENABLED", "1")
        assert sched.jobs[0].enabled()
