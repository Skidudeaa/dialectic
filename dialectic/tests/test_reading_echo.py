"""
Tests for llm/reading_echo.py — the half-hourly job that checks new
readings against OTHER thesis-holding rooms and lands a quiet annotator
note plus a cross-session memory reference where the article bears on the
other room's cascade.

WHY this file exists: the job spends LLM money on a wall-clock timer and
writes into rooms nobody asked it to. The expensive mistakes are echoing
twice (metadata dedup), echoing a room what it already read (library
dedup), spending on a capped or thesis-less room (cap/no-thesis before the
Haiku call), and a cross-room reference leaking into prompt injection (the
reference is a citation only — the cross_session gate is never touched).

Strategy mirrors tests/test_prediction_watch.py: a fake pool/conn answering
by the table the job queried, and the two externals (Haiku relevance,
reference write) stubbed at the module seam.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from scheduler import Scheduler, SchedulerContext
from llm import reading_echo

ORIGIN_ID = uuid4()
TARGET_ID = uuid4()
THREAD_ID = uuid4()
TWIN_ID = uuid4()

URL = "https://reuters.com/hormuz-rerating"


def make_reading(url=URL, *, room_id=ORIGIN_ID, title="Hormuz rerating",
                 origin_name="Hormuz Room"):
    return {
        "room_id": room_id, "url": url, "title": title,
        "site": "Reuters", "summary": "Tanker traffic through Hormuz fell.",
        "key_claims": ["Traffic fell 12%", "Insurance rates doubled"],
        "origin_room_name": origin_name,
    }


def make_room(room_id=TARGET_ID, *, name="Freight Room",
              config='{"posture": "long tankers"}'):
    return {"id": room_id, "name": name, "trading_config": config}


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


def make_echo_db(*, readings=(), rooms=(), echoed=(), seen=(),
                 posted_today=0, twin_id=TWIN_ID, thread_id=THREAD_ID,
                 fail_rooms=()):
    """Mock asyncpg connection covering every query the echo job makes."""
    db = AsyncMock()

    async def _fetch(sql, *args):
        if "FROM reading_items ri" in sql:
            return list(readings)
        if "FROM rooms r" in sql:
            return list(rooms)
        if "FROM messages" in sql:
            if args and args[0] in fail_rooms:
                raise RuntimeError("boom")
            return [{"url": u} for u in echoed]
        if "FROM reading_items" in sql:  # seen_urls: target's own library
            return [{"url": u} for u in seen]
        return []

    async def _fetchrow(sql, *args):
        if "FROM threads" in sql:
            return {"id": thread_id} if thread_id else None
        return None

    async def _fetchval(sql, *args):
        if "COUNT(*)" in sql:
            return posted_today
        if "FROM memories" in sql:
            return twin_id
        return None

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchrow = AsyncMock(side_effect=_fetchrow)
    db.fetchval = AsyncMock(side_effect=_fetchval)
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mocks(monkeypatch):
    """Stub the two externals: the Haiku relevance call and the reference
    write (module seam, prediction_watch._verdict pattern)."""
    m = SimpleNamespace(
        verdict={"relevant": True, "why": "Hormuz freight is the cascade's first link."},
        relevance_calls=[], reference_calls=[],
    )

    async def _relevance(reading, thesis_context):
        m.relevance_calls.append({"url": reading["url"],
                                  "thesis": thesis_context})
        return m.verdict

    async def _create_reference(conn, memory_id, room, thread_id, msg_id,
                                why):
        m.reference_calls.append({
            "source_memory_id": memory_id,
            "target_room_id": room["id"],
            "target_thread_id": thread_id,
            "target_message_id": msg_id,
            "referenced_by_llm": True,
            "citation_context": why,
        })

    monkeypatch.setattr(reading_echo, "_relevance", _relevance)
    monkeypatch.setattr(reading_echo, "_create_reference", _create_reference)
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
        if "INSERT INTO messages" in call.args[0]:
            out.append(call.args[-1])
    return out


def _posted_contents(db):
    out = []
    for call in db.execute.await_args_list:
        if "INSERT INTO messages" in call.args[0]:
            out.append(call.args[-2])
    return out


# =========================================================================
# Job registration — half-hourly interval, kill switch default OFF
# =========================================================================


class TestEchoJobRegistration:
    def test_registers_half_hourly(self):
        sched = Scheduler(SchedulerContext(pool=None))
        reading_echo.register_reading_echo_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "reading_echo"
        assert job.interval_s == 1800
        assert job.enabled_env == "READING_ECHO_ENABLED"

    def test_env_gate_zero_disables(self, monkeypatch):
        """The shipped .env.example carries READING_ECHO_ENABLED=0 — the
        job spends money on a timer, so it ships dark and is opted into."""
        monkeypatch.setenv("READING_ECHO_ENABLED", "0")
        sched = Scheduler(SchedulerContext(pool=None))
        reading_echo.register_reading_echo_jobs(sched)
        assert not sched.jobs[0].enabled()

    def test_env_gate_on(self, monkeypatch):
        monkeypatch.setenv("READING_ECHO_ENABLED", "1")
        sched = Scheduler(SchedulerContext(pool=None))
        reading_echo.register_reading_echo_jobs(sched)
        assert sched.jobs[0].enabled()


# =========================================================================
# Recent-window selection
# =========================================================================


@pytest.mark.asyncio
class TestRecentWindow:
    async def test_reads_come_from_the_lookback_window(self, mocks):
        """The recent-readings query is time-bounded (~two intervals); the
        metadata dedup, not the timing, is what makes overlap harmless."""
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()])
        detail = await reading_echo.echo(_ctx(db))

        recent_sql = db.fetch.await_args_list[0].args[0]
        assert "interval '3700 seconds'" in recent_sql
        assert len(detail["echoed"]) == 1

    async def test_no_recent_readings_is_a_quiet_run(self, mocks):
        db = make_echo_db(readings=[])
        detail = await reading_echo.echo(_ctx(db))

        assert detail == {"echoed": [], "skipped": []}
        assert mocks.relevance_calls == []
        db.execute.assert_not_awaited()


# =========================================================================
# Dedup — already echoed / target read it themselves
# =========================================================================


@pytest.mark.asyncio
class TestDedup:
    async def test_already_echoed_pair_is_skipped(self, mocks):
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()],
                          echoed={URL})
        detail = await reading_echo.echo(_ctx(db))

        assert detail["skipped"] == [
            {"url": URL, "room": str(TARGET_ID), "reason": "already_echoed"}]
        assert mocks.relevance_calls == []
        assert _posted_metadata(db) == []

    async def test_target_room_that_read_it_is_skipped(self, mocks):
        """The URL sits in the TARGET room's own library — they read it
        themselves, an echo would be noise."""
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()],
                          seen={URL})
        detail = await reading_echo.echo(_ctx(db))

        assert detail["skipped"] == [
            {"url": URL, "room": str(TARGET_ID), "reason": "already_read"}]
        assert mocks.relevance_calls == []
        assert _posted_metadata(db) == []


# =========================================================================
# Candidate selection — thesis required, 3-room cap
# =========================================================================


@pytest.mark.asyncio
class TestCandidateRooms:
    async def test_room_without_thesis_is_skipped_before_the_llm(self, mocks):
        db = make_echo_db(readings=[make_reading()],
                          rooms=[make_room(config=None)])
        detail = await reading_echo.echo(_ctx(db))

        assert detail["skipped"] == [
            {"url": URL, "room": str(TARGET_ID), "reason": "no_thesis"}]
        assert mocks.relevance_calls == []

    async def test_target_cap_of_three(self, mocks):
        rooms = [make_room(uuid4(), name=f"Room {i}") for i in range(5)]
        db = make_echo_db(readings=[make_reading()], rooms=rooms)
        detail = await reading_echo.echo(_ctx(db))

        assert len(detail["echoed"]) == reading_echo.READING_ECHO_TARGET_CAP
        assert len(mocks.relevance_calls) == 3


# =========================================================================
# The relevance gate
# =========================================================================


@pytest.mark.asyncio
class TestRelevance:
    async def test_not_relevant_posts_nothing(self, mocks):
        mocks.verdict = {"relevant": False, "why": "Off-thesis."}
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()])
        detail = await reading_echo.echo(_ctx(db))

        assert detail["skipped"] == [
            {"url": URL, "room": str(TARGET_ID), "reason": "not_relevant"}]
        assert mocks.reference_calls == []
        assert _posted_metadata(db) == []

    async def test_relevance_failure_skips_the_pair(self, mocks):
        mocks.verdict = None
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()])
        detail = await reading_echo.echo(_ctx(db))

        assert detail["skipped"] == [
            {"url": URL, "room": str(TARGET_ID), "reason": "relevance_failed"}]
        assert _posted_metadata(db) == []

    async def test_thesis_context_is_capped(self, mocks):
        big = "x" * 5000
        db = make_echo_db(readings=[make_reading()],
                          rooms=[make_room(config=big)])
        await reading_echo.echo(_ctx(db))

        assert len(mocks.relevance_calls[0]["thesis"]) \
            == reading_echo.THESIS_CONTEXT_CAP


# =========================================================================
# The hit — note + reference + broadcast
# =========================================================================


@pytest.mark.asyncio
class TestEchoLands:
    async def test_relevant_reading_posts_note_reference_and_broadcast(
            self, mocks):
        broadcast = AsyncMock()
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()])
        detail = await reading_echo.echo(_ctx(db, broadcast))

        posted = _posted_metadata(db)
        assert len(posted) == 1
        assert posted[0] == {
            "source": "reading_echo",
            "url": URL,
            "origin_room": "Hormuz Room",
        }
        content = _posted_contents(db)[0]
        assert content == (
            "The Hormuz Room room read this — bears on your cascade: "
            f"**Hormuz rerating** (Reuters, {URL})\n\n"
            "Hormuz freight is the cascade's first link."
        )

        assert len(mocks.reference_calls) == 1
        ref = mocks.reference_calls[0]
        assert ref["source_memory_id"] == TWIN_ID
        assert ref["target_room_id"] == TARGET_ID
        assert ref["target_thread_id"] == THREAD_ID
        assert ref["referenced_by_llm"] is True
        assert ref["citation_context"] == \
            "Hormuz freight is the cascade's first link."
        # The citation points at the echo note itself.
        assert ref["target_message_id"] is not None

        broadcast.assert_awaited_once()
        room_arg, outbound = broadcast.await_args.args
        assert room_arg == TARGET_ID
        assert outbound.payload["speaker_type"] == "llm_annotator"
        assert outbound.payload["metadata"] == posted[0]
        assert outbound.payload["content"] == content

        assert detail["echoed"] == [{
            "url": URL, "room": str(TARGET_ID),
            "message_id": str(ref["target_message_id"]),
            "referenced": True,
        }]

    async def test_missing_memory_twin_still_posts_the_note(self, mocks):
        """The library row is the source of truth; the reference degrades,
        the note stands."""
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()],
                          twin_id=None)
        detail = await reading_echo.echo(_ctx(db))

        assert len(_posted_metadata(db)) == 1
        assert mocks.reference_calls == []
        assert detail["echoed"][0]["referenced"] is False

    async def test_reference_failure_does_not_unpost_the_note(
            self, mocks, monkeypatch):
        async def _broken_reference(*args):
            raise RuntimeError("memories down")
        monkeypatch.setattr(reading_echo, "_create_reference",
                            _broken_reference)
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()])
        detail = await reading_echo.echo(_ctx(db))

        assert len(_posted_metadata(db)) == 1
        assert detail["echoed"][0]["referenced"] is False


# =========================================================================
# Daily cap — the note budget, checked before the LLM spend
# =========================================================================


@pytest.mark.asyncio
class TestDailyCap:
    async def test_capped_room_gets_no_note_and_no_llm_call(self, mocks):
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()],
                          posted_today=reading_echo.READING_ECHO_DAILY_CAP)
        detail = await reading_echo.echo(_ctx(db))

        assert detail["skipped"] == [
            {"url": URL, "room": str(TARGET_ID), "reason": "cap_reached"}]
        assert mocks.relevance_calls == []
        assert _posted_metadata(db) == []

    async def test_one_below_the_cap_still_echoes(self, mocks):
        db = make_echo_db(
            readings=[make_reading()], rooms=[make_room()],
            posted_today=reading_echo.READING_ECHO_DAILY_CAP - 1)
        detail = await reading_echo.echo(_ctx(db))

        assert len(detail["echoed"]) == 1


# =========================================================================
# Failure containment — a broken pair never sinks the run
# =========================================================================


@pytest.mark.asyncio
class TestFailureContainment:
    async def test_one_broken_room_does_not_sink_the_others(self, mocks):
        good_room = make_room(uuid4(), name="Good Room")
        db = make_echo_db(
            readings=[make_reading()],
            rooms=[make_room(), good_room],
            fail_rooms={TARGET_ID},
        )
        detail = await reading_echo.echo(_ctx(db))

        reasons = {s["room"]: s["reason"] for s in detail["skipped"]}
        assert reasons[str(TARGET_ID)] == "error"
        assert [e["room"] for e in detail["echoed"]] == [str(good_room["id"])]
        assert len(_posted_metadata(db)) == 1

    async def test_no_thread_room_is_skipped(self, mocks):
        db = make_echo_db(readings=[make_reading()], rooms=[make_room()],
                          thread_id=None)
        detail = await reading_echo.echo(_ctx(db))

        assert detail["skipped"] == [
            {"url": URL, "room": str(TARGET_ID), "reason": "no_thread"}]
        assert mocks.reference_calls == []


# =========================================================================
# _parse_relevance — tolerant JSON parsing
# =========================================================================


class TestParseRelevance:
    def test_plain_json(self):
        parsed = reading_echo._parse_relevance(
            '{"relevant": true, "why": "It moves the first link."}'
        )
        assert parsed == {"relevant": True, "why": "It moves the first link."}

    def test_fenced_json(self):
        parsed = reading_echo._parse_relevance(
            '```json\n{"relevant": false, "why": "Off-thesis."}\n```'
        )
        assert parsed == {"relevant": False, "why": "Off-thesis."}

    def test_garbage_returns_none(self):
        assert reading_echo._parse_relevance("not json at all") is None
        assert reading_echo._parse_relevance('{"why": "no verdict"}') is None
