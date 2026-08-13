"""
Tests for llm/wire.py — the 15-minute poller that files thesis-relevant
breaking news into the reading library AND interrupts the room with a real
facilitator turn.

WHY this file exists: the wire spends LLM money on a timer and speaks
uninvited. The expensive mistakes are re-filing what the room already read
(dedup), one dead article killing the run (per-item skips), interrupting a
room that asked not to be (toggle/quiet hours), a fifth interjection in a
day (cap), and a below-threshold story still getting airtime (gating).
Mirrors tests/test_news_night.py + the sweep tests in
tests/test_participation_fsm.py.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from scheduler import Scheduler, SchedulerContext
from llm import wire
from llm.orchestrator import OrchestrationResult
from models import SpeakerType

from tests.conftest import make_message, make_room, make_thread, make_user


ROOM_ID = uuid4()
BOOK = "iran-war"


def make_room_row(**overrides):
    room = {
        "id": ROOM_ID,
        "name": "Hormuz Room",
        "linked_book_id": BOOK,
        "auto_interjection_enabled": True,
        "trading_config": '{"claim": "Hormuz disruption lifts Brent"}',
    }
    room.update(overrides)
    return room


def make_articles(n):
    return [
        {"title": f"Story {i}", "url": f"https://reuters.com/s{i}",
         "seendate": "20260812140000", "domain": "reuters.com"}
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


def make_wire_db(*, rooms, seen=(), interjections_today=0):
    """Mock asyncpg connection covering every query wire_watch makes."""
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
    """Stub the four externals: news feed, extractor, scorer, saver."""
    m = SimpleNamespace(
        articles=make_articles(3),
        news_error=None,
        extract_errors={},
        score={"score": 0.9, "why": "Bears on node 2's trigger."},
        news_calls=[], extract_calls=[], score_calls=[], saved=[],
    )

    async def _service_get(path, **kwargs):
        m.news_calls.append(path)
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

    async def _score(article, thesis_context):
        m.score_calls.append(article["url"])
        return m.score

    async def _save(db, room_id, article, summary, key_claims, source, **kw):
        m.saved.append({"room_id": room_id, "url": article["url"],
                        "summary": summary, "key_claims": key_claims,
                        "source": source})
        return {"url": article["url"], "title": article.get("title")}

    monkeypatch.setattr(wire.td, "service_get", _service_get)
    monkeypatch.setattr(wire.dc, "extract_article", _extract)
    monkeypatch.setattr(wire, "_score", _score)
    monkeypatch.setattr(wire, "save_reading", _save)
    return m


@pytest.fixture
def interjection_calls(monkeypatch):
    """Intercept force_response at the wire's import site and skip the heavy
    Room/Thread/users/messages/memories load; records calls and returns a
    persisted-message-shaped result."""
    calls = []

    async def _load(conn, room_id):
        return (make_room(id=room_id), make_thread(), [make_user()],
                [make_message(content="what is the Hormuz risk?")], [])

    async def _fake(self, *, room, thread, users, messages, memories,
                    use_provoker=False, protocol=None, reason=None):
        calls.append({"room_id": room.id, "reason": reason,
                      "messages": messages})
        response = make_message(
            content="This just broke — it bears on node 2.",
            speaker_type=SpeakerType.LLM_PRIMARY,
            user_id=None,
        )
        return OrchestrationResult(
            triggered=True, decision=None, response=response,
            routing=None, prompt_used=None,
        )

    monkeypatch.setattr(wire, "_load_room_context", _load)
    monkeypatch.setattr(wire.LLMOrchestrator, "force_response", _fake)
    return calls


def _ctx(db):
    broadcast = AsyncMock()
    return SchedulerContext(pool=FakePool(db), broadcast=broadcast), broadcast


# =========================================================================
# Job registration — 15-minute interval, kill switch default OFF
# =========================================================================


class TestWireJobRegistration:
    def test_registers_interval_job(self):
        sched = Scheduler(SchedulerContext(pool=None))
        wire.register_wire_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "wire_watch"
        assert job.interval_s == 900
        assert job.enabled_env == "WIRE_ENABLED"

    def test_env_gate_zero_disables(self, monkeypatch):
        """The shipped .env.example carries WIRE_ENABLED=0 — the job spends
        money on a timer and speaks uninvited, so it ships dark."""
        monkeypatch.setenv("WIRE_ENABLED", "0")
        sched = Scheduler(SchedulerContext(pool=None))
        wire.register_wire_jobs(sched)
        assert not sched.jobs[0].enabled()

    def test_env_gate_on(self, monkeypatch):
        monkeypatch.setenv("WIRE_ENABLED", "1")
        sched = Scheduler(SchedulerContext(pool=None))
        wire.register_wire_jobs(sched)
        assert sched.jobs[0].enabled()


# =========================================================================
# wire_watch — the per-room pipeline
# =========================================================================


@pytest.mark.asyncio
class TestWireWatch:
    @pytest.fixture(autouse=True)
    def daytime(self, monkeypatch):
        """Pin the wire outside quiet hours (the sweep tests were first
        bitten by the real clock at 23:07 CDT — same disease, same cure)."""
        monkeypatch.setattr(wire, "in_quiet_hours", lambda now=None: False)

    async def test_above_threshold_files_and_interjects(
        self, mocks, interjection_calls,
    ):
        db = make_wire_db(rooms=[make_room_row()])
        ctx, broadcast = _ctx(db)
        detail = await wire.wire_watch(ctx)

        assert mocks.news_calls == [f"/api/bridge/news/{BOOK}"]
        # Feed order is the freshness ranking; 3 headlines, cap 2.
        assert mocks.extract_calls == [
            "https://reuters.com/s1", "https://reuters.com/s2",
        ]
        assert len(mocks.saved) == 2
        assert all(s["source"] == "wire" for s in mocks.saved)
        assert all(s["room_id"] == ROOM_ID for s in mocks.saved)
        # The one-sentence why rides as the filed summary.
        assert mocks.saved[0]["summary"] == "Bears on node 2's trigger."

        assert len(interjection_calls) == 2
        assert all(c["reason"] == "wire_interjection"
                   for c in interjection_calls)
        # The article is the trailing context message of the forced turn.
        wire_context = interjection_calls[0]["messages"][-1].content
        assert "WIRE" in wire_context
        assert "Title for https://reuters.com/s1" in wire_context
        assert "Bears on node 2's trigger." in wire_context
        assert broadcast.await_count == 2

        entry = detail[str(ROOM_ID)]
        assert len(entry["filed"]) == 2
        assert len(entry["interjected"]) == 2
        assert entry["skipped"] == []

    async def test_seen_urls_skipped_without_extract(
        self, mocks, interjection_calls,
    ):
        seen = {"https://reuters.com/s1", "https://reuters.com/s2"}
        db = make_wire_db(rooms=[make_room_row()], seen=seen)
        await wire.wire_watch(_ctx(db)[0])

        assert mocks.extract_calls == ["https://reuters.com/s3"]
        assert [s["url"] for s in mocks.saved] == ["https://reuters.com/s3"]
        assert len(interjection_calls) == 1

    async def test_all_seen_is_a_no_op(self, mocks, interjection_calls):
        seen = {a["url"] for a in mocks.articles}
        db = make_wire_db(rooms=[make_room_row()], seen=seen)
        detail = await wire.wire_watch(_ctx(db)[0])

        assert detail[str(ROOM_ID)] == "all_seen"
        assert mocks.extract_calls == []
        assert mocks.score_calls == []
        assert mocks.saved == []
        assert interjection_calls == []

    async def test_defuddle_error_skips_just_that_article(
        self, mocks, interjection_calls,
    ):
        from llm.defuddle_client import DefuddleError
        mocks.extract_errors["https://reuters.com/s1"] = DefuddleError("boom")
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert [s["url"] for s in mocks.saved] == ["https://reuters.com/s2"]
        assert len(interjection_calls) == 1
        assert detail[str(ROOM_ID)]["skipped"] == [
            {"url": "https://reuters.com/s1", "reason": "extract_failed"},
        ]

    async def test_thin_content_never_scores_files_or_interrupts(
        self, mocks, monkeypatch, interjection_calls,
    ):
        """A bot-blocked shell must not be scored, filed, or -- worst of the
        three -- posted into the room as an interjection."""
        async def _thin_extract(url):
            mocks.extract_calls.append(url)
            return {"url": url, "title": "404", "author": None,
                    "site": "ZeroHedge", "published": None,
                    "word_count": 12, "content": "Article not available"}

        monkeypatch.setattr(wire.dc, "extract_article", _thin_extract)
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert mocks.score_calls == []
        assert mocks.saved == []
        assert interjection_calls == []
        assert all(s["reason"] == "thin_content"
                   for s in detail[str(ROOM_ID)]["skipped"])

    async def test_empty_content_is_thin_even_with_a_word_count(
        self, mocks, monkeypatch, interjection_calls,
    ):
        """word_count can be present and plausible while the body is blank --
        the content check is not redundant with the count check."""
        async def _blank_extract(url):
            mocks.extract_calls.append(url)
            return {"url": url, "title": "Cookie wall", "author": None,
                    "site": "Reuters", "published": None,
                    "word_count": 900, "content": "   "}

        monkeypatch.setattr(wire.dc, "extract_article", _blank_extract)
        db = make_wire_db(rooms=[make_room_row()])
        await wire.wire_watch(_ctx(db)[0])

        assert mocks.score_calls == []
        assert mocks.saved == []
        assert interjection_calls == []

    async def test_tradingdesk_error_skips_the_room(
        self, mocks, interjection_calls,
    ):
        from llm.tradingdesk_client import TradingDeskError
        mocks.news_error = TradingDeskError("tradingDesk down")
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert detail[str(ROOM_ID)].startswith("news_unavailable")
        assert mocks.extract_calls == []
        assert mocks.saved == []
        assert interjection_calls == []

    async def test_below_threshold_saves_nothing_and_stays_quiet(
        self, mocks, interjection_calls,
    ):
        mocks.score = {"score": wire.WIRE_THRESHOLD - 0.1, "why": "peripheral"}
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert mocks.saved == []
        assert interjection_calls == []
        entry = detail[str(ROOM_ID)]
        assert entry["filed"] == []
        assert all(s["reason"] == "below_threshold" for s in entry["skipped"])

    async def test_score_parse_failure_counts_as_below_threshold(
        self, mocks, interjection_calls,
    ):
        mocks.score = None
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert mocks.saved == []
        assert interjection_calls == []
        assert all(s["reason"] == "below_threshold"
                   for s in detail[str(ROOM_ID)]["skipped"])

    async def test_daily_cap_stops_the_room(self, mocks, interjection_calls):
        db = make_wire_db(
            rooms=[make_room_row()],
            interjections_today=wire.WIRE_DAILY_CAP,
        )
        detail = await wire.wire_watch(_ctx(db)[0])

        assert detail[str(ROOM_ID)] == "cap_reached"
        assert mocks.news_calls == []
        assert mocks.saved == []
        assert interjection_calls == []

    async def test_quiet_hours_skip_the_whole_job(self, mocks, monkeypatch):
        monkeypatch.setattr(wire, "in_quiet_hours", lambda now=None: True)
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert detail == {"skipped": "quiet_hours"}
        assert mocks.news_calls == []

    async def test_toggle_off_skips_the_room(self, mocks, interjection_calls):
        db = make_wire_db(
            rooms=[make_room_row(auto_interjection_enabled=False)],
        )
        detail = await wire.wire_watch(_ctx(db)[0])

        assert detail[str(ROOM_ID)] == "toggle_off"
        assert mocks.news_calls == []
        assert mocks.saved == []
        assert interjection_calls == []

    async def test_no_articles_is_a_no_op(self, mocks):
        mocks.articles = []
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert detail[str(ROOM_ID)] == "no_articles"
        assert mocks.extract_calls == []

    async def test_failed_interjection_still_files_the_reading(
        self, mocks, monkeypatch,
    ):
        """A dead interjection must not cost the room its library row — the
        reading is already filed either way."""
        async def _load(conn, room_id):
            return (make_room(id=room_id), make_thread(), [make_user()],
                    [make_message(content="hi")], [])

        async def _boom(self, **kwargs):
            raise RuntimeError("orchestrator exploded")

        monkeypatch.setattr(wire, "_load_room_context", _load)
        monkeypatch.setattr(wire.LLMOrchestrator, "force_response", _boom)
        db = make_wire_db(rooms=[make_room_row()])
        detail = await wire.wire_watch(_ctx(db)[0])

        assert len(mocks.saved) == 2
        entry = detail[str(ROOM_ID)]
        assert len(entry["filed"]) == 2
        assert entry["interjected"] == []
        assert all(s["reason"] == "interjection_failed"
                   for s in entry["skipped"])

    async def test_broken_room_does_not_sink_the_others(
        self, mocks, monkeypatch,
    ):
        """One room's unexpected failure is logged and recorded, never raised."""
        other_id = uuid4()
        rooms = [
            make_room_row(),
            make_room_row(id=other_id, linked_book_id="gulf-book"),
        ]
        db = make_wire_db(rooms=rooms)

        original_seen = wire.seen_urls

        async def _seen(conn, room_id):
            if room_id == ROOM_ID:
                raise RuntimeError("db hiccup")
            return await original_seen(conn, room_id)

        monkeypatch.setattr(wire, "seen_urls", _seen)
        detail = await wire.wire_watch(_ctx(db)[0])

        assert detail[str(ROOM_ID)] == "error: RuntimeError"
        # The second room ran the pipeline to completion.
        assert "filed" in detail[str(other_id)]


# =========================================================================
# _parse_score — tolerant JSON parsing
# =========================================================================


class TestParseScore:
    def test_plain_json(self):
        parsed = wire._parse_score(
            '{"score": 0.85, "why": "Directly hits the Hormuz trigger."}'
        )
        assert parsed["score"] == 0.85
        assert parsed["why"] == "Directly hits the Hormuz trigger."

    def test_fenced_json(self):
        parsed = wire._parse_score('```json\n{"score": 0.4}\n```')
        assert parsed["score"] == 0.4
        assert parsed["why"] == ""

    def test_score_clamped_to_unit_interval(self):
        assert wire._parse_score('{"score": 1.7}')["score"] == 1.0
        assert wire._parse_score('{"score": -0.2}')["score"] == 0.0

    def test_garbage_returns_none(self):
        assert wire._parse_score("not json at all") is None
        assert wire._parse_score('{"why": "no score"}') is None
        assert wire._parse_score('{"score": "high"}') is None
        assert wire._parse_score("[0.9]") is None
