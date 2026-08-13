"""
Tests for llm/prediction_watch.py — the hourly deadline watcher that gathers
evidence for due logged predictions, asks Haiku for a verdict, and posts a
resolution_proposal card the human settles.

WHY this file exists: the job spends LLM money on a wall-clock timer against
three external services. The expensive mistakes are re-proposing what was
already proposed (dedup), a dead desk killing the run (quiet skip), the cap
leaking (spend), and a proposal landing in the wrong room (book → room
mapping is the only path home).

Strategy mirrors tests/test_news_night.py: a fake pool/conn answering by the
table the job queried, and the four externals (predictions list, news feed,
extractor, verdict) stubbed at the module seam.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from scheduler import Scheduler, SchedulerContext
from llm import prediction_watch
from llm.defuddle_client import DefuddleError
from llm.tradingdesk_client import TradingDeskError

ROOM_ID = uuid4()
THREAD_ID = uuid4()
BOOK = "iran-hormuz-graph"

TODAY = date.today()
DUE_TODAY = TODAY.isoformat()
DUE_TOMORROW = (TODAY + timedelta(days=1)).isoformat()
FAR_FUTURE = (TODAY + timedelta(days=30)).isoformat()


def make_prediction(pid, *, deadline=DUE_TODAY, linked_book_id=BOOK,
                    resolution=None, statement="Brent closes above $90"):
    return {
        "id": pid,
        "statement": statement,
        "confidence": 0.7,
        "deadline": deadline,
        "linked_book_id": linked_book_id,
        "resolution": resolution,
        "resolved_at": None,
        "tags": ["dialectic"],
    }


def make_articles(n):
    return [
        {"title": f"Story {i}", "url": f"https://reuters.com/s{i}"}
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


_DEFAULT_ROOM = object()


def make_watch_db(*, proposed_ids=(), room=_DEFAULT_ROOM, thread_id=THREAD_ID):
    """Mock asyncpg connection covering every query the watch job makes."""
    if room is _DEFAULT_ROOM:
        room = {"id": ROOM_ID, "name": "Hormuz Room"}
    db = AsyncMock()

    async def _fetch(sql, *args):
        if "FROM messages" in sql:
            return [{"prediction_id": pid} for pid in proposed_ids]
        return []

    async def _fetchrow(sql, *args):
        if "FROM rooms" in sql:
            return room
        if "FROM threads" in sql:
            return {"id": thread_id} if thread_id else None
        return None

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchrow = AsyncMock(side_effect=_fetchrow)
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mocks(monkeypatch):
    """Stub the four externals: predictions list, news feed, extractor,
    verdict."""
    m = SimpleNamespace(
        predictions=[],
        predictions_error=None,
        articles=make_articles(3),
        news_error=None,
        extract_errors={},
        verdict={"verdict": "correct", "rationale": "Traffic data confirms it."},
        news_calls=[], extract_calls=[], verdict_calls=[],
    )

    async def _get(path, **kwargs):
        if m.predictions_error is not None:
            raise m.predictions_error
        return m.predictions

    async def _service_get(path, **kwargs):
        m.news_calls.append(path)
        if m.news_error is not None:
            raise m.news_error
        return {"articles": m.articles}

    async def _extract(url):
        m.extract_calls.append(url)
        if url in m.extract_errors:
            raise m.extract_errors[url]
        return {"url": url, "title": f"Title for {url}",
                "content": f"Body of {url}"}

    async def _verdict(prediction, evidence):
        m.verdict_calls.append({"id": str(prediction["id"]),
                                "evidence": evidence})
        return m.verdict

    monkeypatch.setattr(prediction_watch.td, "get", _get)
    monkeypatch.setattr(prediction_watch.td, "service_get", _service_get)
    monkeypatch.setattr(prediction_watch.dc, "extract_article", _extract)
    monkeypatch.setattr(prediction_watch, "_verdict", _verdict)
    return m


def _ctx(db, broadcast=None):
    return SchedulerContext(
        pool=FakePool(db),
        broadcast=broadcast if broadcast is not None else AsyncMock(),
    )


def _posted_metadata(db):
    """The metadata dicts the job inserted into messages."""
    out = []
    for call in db.execute.await_args_list:
        sql = call.args[0]
        if "INSERT INTO messages" in sql:
            out.append(call.args[-1])
    return out


# =========================================================================
# Job registration — hourly interval, kill switch default OFF
# =========================================================================


class TestWatchJobRegistration:
    def test_registers_hourly(self):
        sched = Scheduler(SchedulerContext(pool=None))
        prediction_watch.register_prediction_watch_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "prediction_deadline_watch"
        assert job.interval_s == 3600
        assert job.enabled_env == "PREDICTION_WATCH_ENABLED"

    def test_env_gate_zero_disables(self, monkeypatch):
        """The shipped .env.example carries PREDICTION_WATCH_ENABLED=0 — the
        job spends money on a timer, so it ships dark and is opted into."""
        monkeypatch.setenv("PREDICTION_WATCH_ENABLED", "0")
        sched = Scheduler(SchedulerContext(pool=None))
        prediction_watch.register_prediction_watch_jobs(sched)
        assert not sched.jobs[0].enabled()

    def test_env_gate_on(self, monkeypatch):
        monkeypatch.setenv("PREDICTION_WATCH_ENABLED", "1")
        sched = Scheduler(SchedulerContext(pool=None))
        prediction_watch.register_prediction_watch_jobs(sched)
        assert sched.jobs[0].enabled()


# =========================================================================
# prediction_deadline_watch — the due-filter
# =========================================================================


@pytest.mark.asyncio
class TestDueFilter:
    async def test_future_and_resolved_predictions_are_skipped(self, mocks):
        mocks.predictions = [
            make_prediction("p-due", deadline=DUE_TODAY),
            make_prediction("p-runway", deadline=DUE_TOMORROW),
            make_prediction("p-far", deadline=FAR_FUTURE),
            make_prediction("p-resolved", resolution="correct"),
        ]
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        proposed = {p["id"] for p in detail["proposed"]}
        assert proposed == {"p-due", "p-runway"}
        reasons = {s["id"]: s["reason"] for s in detail["skipped"]}
        assert reasons["p-far"] == "not_due"
        assert reasons["p-resolved"] == "already_resolved"

    async def test_unparseable_deadline_is_skipped_not_fatal(self, mocks):
        mocks.predictions = [
            make_prediction("p-bad", deadline="not-a-date"),
            make_prediction("p-due"),
        ]
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        assert [p["id"] for p in detail["proposed"]] == ["p-due"]
        reasons = {s["id"]: s["reason"] for s in detail["skipped"]}
        assert reasons["p-bad"] == "bad_deadline"

    async def test_desk_down_is_a_quiet_run(self, mocks):
        mocks.predictions_error = TradingDeskError("tradingDesk down")
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        assert detail["proposed"] == []
        assert detail["error"].startswith("predictions_unavailable")
        db.execute.assert_not_awaited()
        assert mocks.verdict_calls == []


# =========================================================================
# Dedup + run cap
# =========================================================================


@pytest.mark.asyncio
class TestDedupAndCap:
    async def test_already_proposed_prediction_is_skipped(self, mocks):
        mocks.predictions = [
            make_prediction("p-old"),
            make_prediction("p-new"),
        ]
        db = make_watch_db(proposed_ids={"p-old"})
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        assert [p["id"] for p in detail["proposed"]] == ["p-new"]
        reasons = {s["id"]: s["reason"] for s in detail["skipped"]}
        assert reasons["p-old"] == "already_proposed"
        assert len(mocks.verdict_calls) == 1

    async def test_run_cap_of_three(self, mocks):
        mocks.predictions = [make_prediction(f"p-{i}") for i in range(5)]
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        assert len(detail["proposed"]) == prediction_watch.PREDICTION_WATCH_RUN_CAP
        capped = [s for s in detail["skipped"] if s["reason"] == "cap_reached"]
        assert len(capped) == 2
        assert len(mocks.verdict_calls) == 3


# =========================================================================
# The linked-prediction pipeline — evidence, verdict, annotator post
# =========================================================================


@pytest.mark.asyncio
class TestLinkedPipeline:
    async def test_linked_prediction_gets_evidence_verdict_and_card(self, mocks):
        mocks.predictions = [make_prediction("p-1")]
        broadcast = AsyncMock()
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db, broadcast))

        assert mocks.news_calls == [f"/api/bridge/news/{BOOK}"]
        # Feed order is the freshness ranking; 3 headlines, cap 2.
        assert mocks.extract_calls == [
            "https://reuters.com/s1", "https://reuters.com/s2",
        ]
        assert len(mocks.verdict_calls) == 1
        evidence = mocks.verdict_calls[0]["evidence"]
        assert [ev["url"] for ev in evidence] == [
            "https://reuters.com/s1", "https://reuters.com/s2",
        ]

        posted = _posted_metadata(db)
        assert len(posted) == 1
        metadata = posted[0]
        assert metadata["source"] == "prediction_watch"
        proposal = metadata["resolution_proposal"]
        assert proposal["prediction_id"] == "p-1"
        assert proposal["statement"] == "Brent closes above $90"
        assert proposal["verdict"] == "correct"
        assert proposal["rationale"] == "Traffic data confirms it."
        assert proposal["accepted"] is False
        assert proposal["evidence"] == [
            {"url": "https://reuters.com/s1",
             "title": "Title for https://reuters.com/s1"},
            {"url": "https://reuters.com/s2",
             "title": "Title for https://reuters.com/s2"},
        ]

        broadcast.assert_awaited_once()
        room_arg, outbound = broadcast.await_args.args
        assert room_arg == ROOM_ID
        assert outbound.payload["metadata"]["resolution_proposal"]["prediction_id"] == "p-1"
        assert detail["proposed"][0]["room_id"] == str(ROOM_ID)

    async def test_defuddle_failure_degrades_to_less_evidence(self, mocks):
        mocks.extract_errors["https://reuters.com/s1"] = DefuddleError("boom")
        mocks.predictions = [make_prediction("p-1")]
        db = make_watch_db()
        await prediction_watch.prediction_deadline_watch(_ctx(db))

        evidence = mocks.verdict_calls[0]["evidence"]
        # s1 failed, s2/s3 are the next-freshest — the cap still fills.
        assert [ev["url"] for ev in evidence] == [
            "https://reuters.com/s2", "https://reuters.com/s3",
        ]
        assert len(_posted_metadata(db)) == 1

    async def test_news_failure_still_posts_with_no_evidence(self, mocks):
        mocks.news_error = TradingDeskError("bridge down")
        mocks.predictions = [make_prediction("p-1")]
        db = make_watch_db()
        await prediction_watch.prediction_deadline_watch(_ctx(db))

        assert mocks.verdict_calls[0]["evidence"] == []
        proposal = _posted_metadata(db)[0]["resolution_proposal"]
        assert proposal["evidence"] == []

    async def test_verdict_failure_skips_the_prediction(self, mocks):
        mocks.verdict = None
        mocks.predictions = [make_prediction("p-1")]
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        assert detail["proposed"] == []
        reasons = {s["id"]: s["reason"] for s in detail["skipped"]}
        assert reasons["p-1"] == "verdict_failed"
        db.execute.assert_not_awaited()

    async def test_unclear_verdict_still_posts_a_card(self, mocks):
        """An unclear verdict is metadata-only: the message posts, the
        frontend renders no action buttons for it."""
        mocks.verdict = {"verdict": "unclear",
                         "rationale": "The evidence does not settle it."}
        mocks.predictions = [make_prediction("p-1")]
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        proposal = _posted_metadata(db)[0]["resolution_proposal"]
        assert proposal["verdict"] == "unclear"
        assert detail["proposed"][0]["verdict"] == "unclear"


# =========================================================================
# Room mapping — linked predictions only in v1
# =========================================================================


@pytest.mark.asyncio
class TestRoomMapping:
    async def test_unlinked_prediction_is_noted_and_skipped(self, mocks):
        """tradingDesk predictions carry no room id; without a linked book
        there is no room to come home to."""
        mocks.predictions = [
            make_prediction("p-loose", linked_book_id=None),
            make_prediction("p-linked"),
        ]
        db = make_watch_db()
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        assert [p["id"] for p in detail["proposed"]] == ["p-linked"]
        reasons = {s["id"]: s["reason"] for s in detail["skipped"]}
        assert reasons["p-loose"] == "unlinked_no_room"

    async def test_no_room_bound_to_the_book_skips(self, mocks):
        mocks.predictions = [make_prediction("p-orphan")]
        db = make_watch_db(room=None)  # no rooms row bound to the book
        detail = await prediction_watch.prediction_deadline_watch(_ctx(db))

        reasons = {s["id"]: s["reason"] for s in detail["skipped"]}
        assert reasons["p-orphan"] == "no_room_for_book"
        assert mocks.verdict_calls == []


# =========================================================================
# _parse_verdict — tolerant JSON parsing
# =========================================================================


class TestParseVerdict:
    def test_plain_json(self):
        parsed = prediction_watch._parse_verdict(
            '{"verdict": "correct", "rationale": "The data says so."}'
        )
        assert parsed == {"verdict": "correct",
                          "rationale": "The data says so."}

    def test_fenced_json(self):
        parsed = prediction_watch._parse_verdict(
            '```json\n{"verdict": "unclear", "rationale": "Mixed signals."}\n```'
        )
        assert parsed["verdict"] == "unclear"

    def test_unknown_verdict_returns_none(self):
        assert prediction_watch._parse_verdict(
            '{"verdict": "maybe", "rationale": "..."}'
        ) is None

    def test_garbage_returns_none(self):
        assert prediction_watch._parse_verdict("not json at all") is None
        assert prediction_watch._parse_verdict('{"rationale": "no verdict"}') is None
