"""
Tests for llm/news_night.py — the 05:30 digest that files overnight news
into each linked room's reading library, plus the briefing section that
renders it.

WHY this file exists: the digest spends LLM money on a wall-clock timer
against three external services. The expensive mistakes are re-filing what
the room already read (dedup), one dead article killing the run (per-item
skips), the cap leaking (spend), and the 07:00 brief missing the section.
"""

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from scheduler import Scheduler, SchedulerContext
from llm import news_night, wire
from llm.briefing import BriefingResponse, build_briefing
from llm.night_shift import _render_brief
from llm.defuddle_client import DefuddleError
from llm.tradingdesk_client import TradingDeskError


ROOM_ID = uuid4()
BOOK = "iran-war"


def make_room(**overrides):
    room = {
        "id": ROOM_ID,
        "name": "Hormuz Room",
        "linked_book_id": BOOK,
        "trading_config": '{"claim": "Hormuz disruption lifts Brent"}',
    }
    room.update(overrides)
    return room


def make_articles(n):
    return [
        {"title": f"Story {i}", "url": f"https://reuters.com/s{i}",
         "seendate": "20260812050000", "domain": "reuters.com"}
        for i in range(1, n + 1)
    ]


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


def make_digest_db(*, rooms, seen=(), saved_today=0):
    """Mock asyncpg connection covering every query thesis_news_digest makes."""
    db = AsyncMock()

    async def _fetch(sql, *args):
        if "FROM rooms" in sql:
            return list(rooms)
        if "SELECT url FROM reading_items" in sql:
            return [{"url": u} for u in seen]
        return []

    async def _fetchval(sql, *args):
        if "FROM reading_items" in sql:
            return saved_today
        return 0

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchval = AsyncMock(side_effect=_fetchval)
    db.fetchrow = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mocks(monkeypatch):
    """Stub the four externals: news feed, extractor, distiller, saver."""
    m = SimpleNamespace(
        articles=make_articles(4),
        news_error=None,
        extract_errors={},
        news_calls=[], news_params=[], extract_calls=[], distill_calls=[],
        saved=[],
    )

    async def _service_get(path, **kwargs):
        m.news_calls.append(path)
        m.news_params.append(kwargs.get("params"))
        if m.news_error is not None:
            raise m.news_error
        return {"articles": m.articles}

    async def _extract(url):
        m.extract_calls.append(url)
        if url in m.extract_errors:
            raise m.extract_errors[url]
        return {"url": url, "title": f"Title for {url}", "author": None,
                "site": "Reuters", "published": "2026-08-12",
                "word_count": 800, "content": f"Body of {url}"}

    async def _distill(article, thesis_context):
        m.distill_calls.append(article["url"])
        return {"summary": f"Summary of {article['url']}.",
                "key_claims": ["claim one"],
                "relevance": "Bears on the Hormuz thesis."}

    async def _save(db, room_id, article, summary, key_claims, source, **kw):
        m.saved.append({"room_id": room_id, "url": article["url"],
                        "summary": summary, "key_claims": key_claims,
                        "source": source})
        return {"url": article["url"], "title": article.get("title")}

    monkeypatch.setattr(news_night.td, "service_get", _service_get)
    monkeypatch.setattr(news_night.dc, "extract_article", _extract)
    monkeypatch.setattr(news_night, "_distill", _distill)
    monkeypatch.setattr(news_night, "save_reading", _save)
    return m


def _ctx(db):
    return SchedulerContext(pool=FakePool(db))


# =========================================================================
# Job registration — wall-clock slot, kill switch default OFF
# =========================================================================


class TestNewsJobRegistration:
    def test_registers_daily_at_530_chicago(self):
        sched = Scheduler(SchedulerContext(pool=None))
        news_night.register_news_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "thesis_news_digest"
        assert job.daily_at == "05:30"
        assert job.daily_tz == "America/Chicago"
        assert job.enabled_env == "NEWS_DIGEST_ENABLED"

    def test_env_gate_zero_disables(self, monkeypatch):
        """The shipped .env.example carries NEWS_DIGEST_ENABLED=0 — the job
        spends money on a timer, so it ships dark and is opted into."""
        monkeypatch.setenv("NEWS_DIGEST_ENABLED", "0")
        sched = Scheduler(SchedulerContext(pool=None))
        news_night.register_news_jobs(sched)
        assert not sched.jobs[0].enabled()

    def test_env_gate_on(self, monkeypatch):
        monkeypatch.setenv("NEWS_DIGEST_ENABLED", "1")
        sched = Scheduler(SchedulerContext(pool=None))
        news_night.register_news_jobs(sched)
        assert sched.jobs[0].enabled()


# =========================================================================
# thesis_news_digest — the per-room pipeline
# =========================================================================


@pytest.mark.asyncio
class TestThesisNewsDigest:
    @pytest.fixture(autouse=True)
    def no_exploration(self, monkeypatch):
        """These tests pin the THESIS lane; the exploration pull (default
        on) has its own class below and would add a news call + a save to
        every fixture here."""
        monkeypatch.setenv("NEWS_EXPLORATION_ENABLED", "0")

    async def test_new_articles_fetched_distilled_saved(self, mocks):
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))

        assert mocks.news_calls == [f"/api/bridge/news/{BOOK}"]
        # Feed order is the freshness ranking; 4 headlines, cap 3.
        assert mocks.extract_calls == [
            "https://reuters.com/s1",
            "https://reuters.com/s2",
            "https://reuters.com/s3",
        ]
        assert len(mocks.saved) == 3
        assert all(s["source"] == "night_shift" for s in mocks.saved)
        assert all(s["room_id"] == ROOM_ID for s in mocks.saved)
        # The relevance note rides inside the stored summary.
        assert "Relevance: Bears on the Hormuz thesis." in mocks.saved[0]["summary"]
        entry = detail[str(ROOM_ID)]
        assert len(entry["saved"]) == 3
        assert entry["skipped"] == []

    async def test_seen_urls_skipped_without_extract(self, mocks):
        seen = {"https://reuters.com/s1", "https://reuters.com/s2"}
        db = make_digest_db(rooms=[make_room()], seen=seen)
        await news_night.thesis_news_digest(_ctx(db))

        assert "https://reuters.com/s1" not in mocks.extract_calls
        assert mocks.extract_calls == [
            "https://reuters.com/s3", "https://reuters.com/s4",
        ]
        assert [s["url"] for s in mocks.saved] == [
            "https://reuters.com/s3", "https://reuters.com/s4",
        ]

    async def test_all_seen_is_a_no_op(self, mocks):
        seen = {a["url"] for a in mocks.articles}
        db = make_digest_db(rooms=[make_room()], seen=seen)
        detail = await news_night.thesis_news_digest(_ctx(db))

        assert detail[str(ROOM_ID)] == "all_seen"
        assert mocks.extract_calls == []
        assert mocks.distill_calls == []
        assert mocks.saved == []

    async def test_defuddle_error_skips_just_that_article(self, mocks):
        mocks.extract_errors["https://reuters.com/s2"] = DefuddleError("boom")
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))

        assert [s["url"] for s in mocks.saved] == [
            "https://reuters.com/s1", "https://reuters.com/s3",
        ]
        skipped = detail[str(ROOM_ID)]["skipped"]
        assert skipped == [
            {"url": "https://reuters.com/s2", "reason": "extract_failed"},
        ]

    async def test_tradingdesk_error_skips_the_room(self, mocks):
        mocks.news_error = TradingDeskError("tradingDesk down")
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))

        assert detail[str(ROOM_ID)].startswith("news_unavailable")
        assert mocks.extract_calls == []
        assert mocks.saved == []

    async def test_thin_content_is_skipped_before_the_distill(self, mocks, monkeypatch):
        """Bot-blocked shells ("404", cookie walls) must not be filed — and
        must not spend a distill call on the way out."""
        async def _thin_extract(url):
            return {"url": url, "title": "404", "author": None,
                    "site": "ZeroHedge", "published": None,
                    "word_count": 12, "content": "Article not available"}

        monkeypatch.setattr(news_night.dc, "extract_article", _thin_extract)
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))

        assert mocks.saved == []
        assert mocks.distill_calls == []
        skipped = detail[str(ROOM_ID)]["skipped"]
        # Only the per-room cap's worth of articles is even attempted.
        assert skipped == [
            {"url": a["url"], "reason": "thin_content"}
            for a in mocks.articles[:news_night.NEWS_DIGEST_PER_ROOM_CAP]
        ]

    async def test_per_room_cap_of_three(self, mocks):
        mocks.articles = make_articles(6)
        db = make_digest_db(rooms=[make_room()])
        await news_night.thesis_news_digest(_ctx(db))

        assert len(mocks.extract_calls) == news_night.NEWS_DIGEST_PER_ROOM_CAP
        assert len(mocks.saved) == 3
        assert len(mocks.distill_calls) == 3

    async def test_daily_llm_cap_stops_the_line(self, mocks):
        db = make_digest_db(
            rooms=[make_room()], saved_today=news_night.NEWS_DIGEST_DAILY_LLM_CAP,
        )
        detail = await news_night.thesis_news_digest(_ctx(db))

        assert detail[str(ROOM_ID)] == "cap_reached"
        assert mocks.news_calls == []
        assert mocks.saved == []

    async def test_distill_failure_skips_the_article(self, mocks, monkeypatch):
        async def _bad_distill(article, thesis_context):
            return None

        monkeypatch.setattr(news_night, "_distill", _bad_distill)
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))

        assert mocks.saved == []
        assert len(detail[str(ROOM_ID)]["skipped"]) == 3
        assert all(s["reason"] == "distill_failed"
                   for s in detail[str(ROOM_ID)]["skipped"])


# =========================================================================
# _parse_distill — tolerant JSON parsing
# =========================================================================


class TestParseDistill:
    def test_plain_json(self):
        parsed = news_night._parse_distill(
            '{"summary": "Fed holds.", "key_claims": ["a", "b"], '
            '"relevance": "Rates steady."}'
        )
        assert parsed["summary"] == "Fed holds."
        assert parsed["key_claims"] == ["a", "b"]
        assert parsed["relevance"] == "Rates steady."

    def test_fenced_json(self):
        parsed = news_night._parse_distill(
            '```json\n{"summary": "Fed holds.", "key_claims": []}\n```'
        )
        assert parsed["summary"] == "Fed holds."
        assert parsed["relevance"] == ""

    def test_garbage_returns_none(self):
        assert news_night._parse_distill("not json at all") is None
        assert news_night._parse_distill('{"key_claims": []}') is None

    def test_key_claims_capped(self):
        claims = ", ".join(f'"c{i}"' for i in range(8))
        parsed = news_night._parse_distill(
            f'{{"summary": "s", "key_claims": [{claims}]}}'
        )
        assert len(parsed["key_claims"]) == news_night.KEY_CLAIMS_CAP

    @pytest.mark.parametrize("stance", ["supports", "contradicts", "neutral"])
    def test_stance_all_three_values(self, stance):
        parsed = news_night._parse_distill(
            f'{{"summary": "s", "stance": "{stance}"}}'
        )
        assert parsed["stance"] == stance

    @pytest.mark.parametrize(
        "raw", ['"mostly agrees"', "0.4", "null"],
        ids=["invented", "number", "null"],
    )
    def test_invalid_stance_degrades_to_neutral(self, raw):
        """Stance must never fail an otherwise-good distill."""
        parsed = news_night._parse_distill(
            f'{{"summary": "s", "stance": {raw}}}'
        )
        assert parsed is not None
        assert parsed["stance"] == "neutral"

    def test_missing_stance_defaults_to_neutral(self):
        assert news_night._parse_distill('{"summary": "s"}')["stance"] == "neutral"

    def test_stance_vocabulary_is_wires(self):
        """Identity, not equality: one stance vocabulary across the wire's
        scorer and the digest's distiller, or a later consumer querying
        '[stance: contradicts]' splits into two dialects."""
        assert news_night.WIRE_STANCES is wire.WIRE_STANCES


# =========================================================================
# assemble_digest — the dissent contract (Phase 7)
# =========================================================================


class TestAssembleDigest:
    def test_contradicting_item_is_labeled_counter(self):
        lines = news_night.assemble_digest([
            {"title": "Oil up", "stance": "supports"},
            {"title": "Oil demand collapsing", "stance": "contradicts"},
        ])
        assert lines == [
            "Oil up",
            f"{news_night.COUNTER_LABEL}Oil demand collapsing",
        ]
        assert news_night.NO_DISSENT_LINE not in lines

    def test_no_dissent_is_stated_never_manufactured(self):
        lines = news_night.assemble_digest([
            {"title": "Oil up", "stance": "supports"},
            {"title": "Tankers fine", "stance": "neutral"},
        ])
        assert lines[-1] == news_night.NO_DISSENT_LINE
        assert not any(
            line.startswith(news_night.COUNTER_LABEL) for line in lines)

    def test_empty_corpus_still_states_the_absence(self):
        assert news_night.assemble_digest([]) == [news_night.NO_DISSENT_LINE]

    def test_title_falls_back_to_url(self):
        lines = news_night.assemble_digest(
            [{"url": "https://x.com/a", "stance": "contradicts"}])
        assert lines[0] == f"{news_night.COUNTER_LABEL}https://x.com/a"


# =========================================================================
# The dissent contract, end to end — the mutation fence
# =========================================================================


@pytest.mark.asyncio
class TestDigestDissent:
    @pytest.fixture(autouse=True)
    def no_exploration(self, monkeypatch):
        monkeypatch.setenv("NEWS_EXPLORATION_ENABLED", "0")

    async def test_contradicts_item_is_labeled_in_summary_and_digest(
        self, mocks, monkeypatch,
    ):
        """THE mutation fence: a contradicts-carrying corpus MUST surface a
        labeled COUNTER item — in the filed summary (what the brief and
        recall render) and in the digest lines. Strip the labeling and this
        goes red."""
        async def _distill(article, thesis_context):
            stance = ("contradicts" if article["url"].endswith("/s2")
                      else "supports")
            return {"summary": f"Summary of {article['url']}.",
                    "key_claims": [], "relevance": "", "stance": stance}

        monkeypatch.setattr(news_night, "_distill", _distill)
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))

        counter_saves = [
            s for s in mocks.saved
            if s["summary"].startswith(news_night.COUNTER_LABEL)
        ]
        assert len(counter_saves) == 1
        assert counter_saves[0]["url"] == "https://reuters.com/s2"

        digest = detail[str(ROOM_ID)]["digest"]
        assert any(line.startswith(news_night.COUNTER_LABEL)
                   for line in digest)
        assert news_night.NO_DISSENT_LINE not in digest

    async def test_absence_of_dissent_is_stated_in_the_digest(self, mocks):
        # The default mock distill carries no stance — all neutral.
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))
        digest = detail[str(ROOM_ID)]["digest"]
        assert digest[-1] == news_night.NO_DISSENT_LINE
        assert not any(line.startswith(news_night.COUNTER_LABEL)
                       for line in digest)
        # And no filed summary was decorated.
        assert not any(
            s["summary"].startswith(news_night.COUNTER_LABEL)
            for s in mocks.saved
        )


# =========================================================================
# The exploration budget (Phase 7) — one broad pull per run
# =========================================================================


@pytest.mark.asyncio
class TestExploration:
    async def test_files_one_labeled_thesis_independent_reading(
        self, mocks, monkeypatch,
    ):
        monkeypatch.setenv("NEWS_EXPLORATION_ENABLED", "1")
        contexts = []

        async def _distill(article, thesis_context):
            contexts.append(thesis_context)
            return {"summary": f"Summary of {article['url']}.",
                    "key_claims": ["claim one"], "relevance": "",
                    "stance": "neutral"}

        monkeypatch.setattr(news_night, "_distill", _distill)
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))

        # Exactly ONE extra reading beyond the per-room lane, labeled and
        # filed like the others (source night_shift → brief + cap gauge).
        exploration_saves = [
            s for s in mocks.saved
            if s["summary"].startswith(news_night.EXPLORATION_LABEL)
        ]
        assert len(exploration_saves) == 1
        assert exploration_saves[0]["source"] == "night_shift"
        # It did not double-file a URL the thesis lane already saved.
        assert exploration_saves[0]["url"] == "https://reuters.com/s4"

        # Thesis-INDEPENDENT by construction: empty snapshot context.
        assert contexts[-1] == ""

        # The broad query rode the bridge call as a query override.
        assert mocks.news_params[-1] == {
            "query": news_night.exploration_query()}

        entry = detail["exploration"]
        assert entry["query"] == news_night.exploration_query()
        assert entry["line"].startswith(news_night.EXPLORATION_LABEL)
        # The host room's digest carries the exploration line.
        assert entry["line"] in detail[str(ROOM_ID)]["digest"]

    async def test_flag_off_skips_the_pull(self, mocks, monkeypatch):
        monkeypatch.setenv("NEWS_EXPLORATION_ENABLED", "0")
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))
        assert detail["exploration"] == "disabled"
        assert len(mocks.news_calls) == 1  # the thesis pull only
        assert len(mocks.saved) == 3

    async def test_daily_llm_cap_blocks_the_pull(self, mocks, monkeypatch):
        monkeypatch.setenv("NEWS_EXPLORATION_ENABLED", "1")
        db = make_digest_db(
            rooms=[make_room()],
            saved_today=news_night.NEWS_DIGEST_DAILY_LLM_CAP,
        )
        detail = await news_night.thesis_news_digest(_ctx(db))
        assert detail["exploration"] == "cap_reached"
        assert mocks.saved == []

    async def test_no_linked_rooms_means_no_pull(self, mocks, monkeypatch):
        monkeypatch.setenv("NEWS_EXPLORATION_ENABLED", "1")
        db = make_digest_db(rooms=[])
        detail = await news_night.thesis_news_digest(_ctx(db))
        assert detail["exploration"] == "no_rooms"
        assert mocks.news_calls == []

    async def test_unreadable_broad_feed_spends_nothing(
        self, mocks, monkeypatch,
    ):
        monkeypatch.setenv("NEWS_EXPLORATION_ENABLED", "1")
        mocks.articles = make_articles(4)
        mocks.extract_errors = {
            "https://reuters.com/s4": news_night.dc.DefuddleError("blocked"),
        }
        db = make_digest_db(rooms=[make_room()])
        detail = await news_night.thesis_news_digest(_ctx(db))
        # s1-s3 went to the thesis lane; the only fresh exploration
        # candidate failed extraction — no distill, honest reason.
        assert detail["exploration"] == {
            "query": news_night.exploration_query(),
            "reason": "no_readable_article",
        }
        assert len(mocks.distill_calls) == 3


class TestExplorationRotation:
    def test_same_day_same_query(self):
        d = datetime(2026, 3, 5, 2, 0, tzinfo=timezone.utc)
        assert (news_night.exploration_query(d)
                == news_night.exploration_query(d.replace(hour=23)))

    def test_rotation_walks_the_whole_list_then_wraps(self):
        base = datetime(2026, 3, 5, tzinfo=timezone.utc)
        n = len(news_night.EXPLORATION_QUERIES)
        picks = [news_night.exploration_query(base + timedelta(days=i))
                 for i in range(n)]
        assert sorted(picks) == sorted(news_night.EXPLORATION_QUERIES)
        assert news_night.exploration_query(base + timedelta(days=n)) == picks[0]


# =========================================================================
# Briefing — the digest surfaces in the response and the rendered brief
# =========================================================================


def make_briefing_db(*, reading_rows=()):
    """Mock asyncpg connection for build_briefing's news-digest query."""
    db = AsyncMock()

    async def _fetch(sql, *args):
        if "FROM reading_items" in sql:
            return list(reading_rows)
        return []

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchval = AsyncMock(return_value=0)
    db.fetchrow = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    return db


def make_briefing(**overrides) -> BriefingResponse:
    now = datetime.now(timezone.utc)
    defaults = dict(
        summary="Two people argued about Hormuz escalation.",
        messages_missed=3,
        memories_created=1,
        threads_forked=0,
        highlights=[],
        last_seen=now - timedelta(hours=24),
        generated_at=now,
    )
    defaults.update(overrides)
    return BriefingResponse(**defaults)


@pytest.mark.asyncio
class TestBriefingNewsDigest:
    async def test_briefing_carries_news_digest(self):
        now = datetime.now(timezone.utc)
        db = make_briefing_db(reading_rows=[{
            "url": "https://reuters.com/s1",
            "title": "Tankers divert from Hormuz",
            "site": "Reuters",
            "published": "2026-08-12",
            "summary": "Traffic through the strait fell overnight.",
            "source": "night_shift",
            "created_at": now,
        }])
        briefing = await build_briefing(
            db, ROOM_ID, now - timedelta(hours=24),
        )

        assert len(briefing.news_digest) == 1
        item = briefing.news_digest[0]
        assert item["title"] == "Tankers divert from Hormuz"
        assert item["saved_via"] == "night_shift"

    async def test_briefing_news_digest_defaults_empty(self):
        db = make_briefing_db()
        briefing = await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
        )
        assert briefing.news_digest == []


class TestRenderBriefNewsSection:
    def test_render_brief_shows_read_overnight_section(self):
        briefing = make_briefing(news_digest=[{
            "url": "https://reuters.com/s1",
            "title": "Tankers divert from Hormuz",
            "site": "Reuters",
            "summary": "Traffic through the strait fell overnight. More detail follows.",
        }])
        text = _render_brief(briefing)

        assert "📰 Read overnight:" in text
        assert "Tankers divert from Hormuz" in text
        assert "Reuters" in text
        # First sentence only — the rest of the summary stays out.
        assert "Traffic through the strait fell overnight." in text
        assert "More detail follows." not in text
        # No item carried dissent → the brief SAYS so (Phase 7: report the
        # absence, never manufacture balance).
        assert news_night.NO_DISSENT_LINE in text

    def test_render_brief_absence_line_suppressed_by_counter_item(self):
        briefing = make_briefing(news_digest=[{
            "url": "https://ft.com/s2",
            "title": "Hormuz traffic normalizes",
            "site": "FT",
            "summary": "COUNTER — Transit counts recovered to baseline. [stance: contradicts]",
        }])
        text = _render_brief(briefing)
        assert news_night.NO_DISSENT_LINE not in text
        assert "COUNTER" in text

    def test_render_brief_omits_section_when_empty(self):
        text = _render_brief(make_briefing())
        assert "📰" not in text
