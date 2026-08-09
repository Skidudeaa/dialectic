"""
Tests for the night shift: llm/night_shift.py, scheduler daily-at support,
and the llm/briefing.py content sections.

WHY this file exists: the 7am brief is the first scheduler job that spends
LLM money and buzzes phones on a wall-clock timer. The expensive mistakes
are a brief that fires twice (ledger), fires at the wrong wall-clock time
(DST), fires with the kill switch off, or pushes someone who is already
looking at the room.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import scheduler as scheduler_mod
from scheduler import Job, Scheduler, SchedulerContext, daily_for
from llm import night_shift
from llm.briefing import BriefingResponse, build_briefing
from models import MessageType, SpeakerType

from tests.conftest import make_message, make_user


ROOM_ID = uuid4()
THREAD_ID = uuid4()
USER_A = uuid4()
USER_B = uuid4()


# =========================================================================
# daily_for — wall-clock slots, DST-correct
# =========================================================================


class TestDailyFor:
    def test_slot_after_it_passes_returns_today(self):
        # 10:30 CDT — the 07:00 slot is due, keyed as 12:00 UTC (CDT = UTC-5).
        now = datetime(2026, 8, 9, 15, 30, tzinfo=timezone.utc)
        slot = daily_for("07:00", "America/Chicago", now=now)
        assert slot == datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

    def test_slot_not_due_yet_returns_none(self):
        # 06:00 CDT — the tick must NOT claim today's ledger row early.
        now = datetime(2026, 8, 9, 11, 0, tzinfo=timezone.utc)
        assert daily_for("07:00", "America/Chicago", now=now) is None

    def test_dst_summer_offset(self):
        # July: CDT = UTC-5, so 07:00 local lands at 12:00 UTC.
        now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
        slot = daily_for("07:00", "America/Chicago", now=now)
        assert slot == datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    def test_dst_winter_offset(self):
        # January: CST = UTC-6, so the same 07:00 local lands at 13:00 UTC.
        # The pair with test_dst_summer_offset is the DST sanity proof.
        now = datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc)
        slot = daily_for("07:00", "America/Chicago", now=now)
        assert slot == datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)

    def test_result_is_utc(self):
        now = datetime(2026, 8, 9, 15, 30, tzinfo=timezone.utc)
        assert daily_for("07:00", "America/Chicago", now=now).tzinfo == timezone.utc


# =========================================================================
# Daily jobs on the tick — ledger idempotency
# =========================================================================


class FakeConn:
    """Ledger-conflict simulator: first insert per (job, bucket) wins."""

    def __init__(self):
        self.ledger = {}
        self.updates = []
        self._next_id = 1

    async def fetchval(self, query, *args):
        if "INSERT INTO scheduled_job_runs" in query:
            key = (args[0], args[1])
            if key in self.ledger:
                return None
            self.ledger[key] = self._next_id
            self._next_id += 1
            return self.ledger[key]
        if "pg_try_advisory_lock" in query:
            return True
        return None

    async def execute(self, query, *args):
        self.updates.append(args)


@pytest.mark.asyncio
class TestDailyJobTick:
    async def test_daily_job_runs_once_per_day(self, monkeypatch):
        fixed = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(
            scheduler_mod, "daily_for", lambda at, tz, now=None: fixed,
        )
        runs = []

        async def job_fn(ctx):
            runs.append(1)
            return {"ok": True}

        sched = Scheduler(SchedulerContext(pool=None))
        sched.register(Job(
            "morning_brief", 86400, job_fn,
            daily_at="07:00", daily_tz="America/Chicago",
        ))
        conn = FakeConn()
        await sched._tick(conn)
        await sched._tick(conn)  # same day, same slot — must not run again
        assert len(runs) == 1
        assert len(conn.updates) == 1
        assert conn.updates[0][1] == "success"

    async def test_daily_job_not_due_is_skipped(self, monkeypatch):
        monkeypatch.setattr(
            scheduler_mod, "daily_for", lambda at, tz, now=None: None,
        )
        runs = []

        async def job_fn(ctx):
            runs.append(1)

        sched = Scheduler(SchedulerContext(pool=None))
        sched.register(Job(
            "morning_brief", 86400, job_fn,
            daily_at="07:00", daily_tz="America/Chicago",
        ))
        conn = FakeConn()
        await sched._tick(conn)
        assert runs == []
        assert conn.ledger == {}  # no early ledger claim

    async def test_interval_jobs_still_use_buckets(self, monkeypatch):
        """Existing interval jobs are untouched by the daily-at machinery."""
        runs = []

        async def job_fn(ctx):
            runs.append(1)

        sched = Scheduler(SchedulerContext(pool=None))
        sched.register(Job("plain", 3600, job_fn))
        conn = FakeConn()
        await sched._tick(conn)
        await sched._tick(conn)
        assert len(runs) == 1


class TestBriefJobRegistration:
    def test_registers_daily_at_7am_chicago(self):
        sched = Scheduler(SchedulerContext(pool=None))
        night_shift.register_brief_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "morning_brief"
        assert job.daily_at == "07:00"
        assert job.daily_tz == "America/Chicago"
        assert job.enabled_env == "NIGHT_SHIFT_ENABLED"

    @pytest.mark.asyncio
    async def test_env_gate_off_skips_the_job(self, monkeypatch):
        monkeypatch.setenv("NIGHT_SHIFT_ENABLED", "0")
        sched = Scheduler(SchedulerContext(pool=None))
        night_shift.register_brief_jobs(sched)
        conn = FakeConn()
        await sched._tick(conn)
        assert conn.ledger == {}

    @pytest.mark.asyncio
    async def test_env_gate_default_on(self, monkeypatch):
        monkeypatch.delenv("NIGHT_SHIFT_ENABLED", raising=False)
        sched = Scheduler(SchedulerContext(pool=None))
        night_shift.register_brief_jobs(sched)
        assert sched.jobs[0].enabled()


# =========================================================================
# build_briefing — content sections over a mock db
# =========================================================================


def msg_row(user, content="Hello", message_type=MessageType.TEXT,
            created_at=None):
    """A DB row shaped like the briefing query returns, via the factories."""
    msg = make_message(content=content, message_type=message_type,
                       user_id=user.id)
    return {
        "sender_name": user.display_name,
        "content": msg.content,
        "message_type": msg.message_type.value if msg.message_type else None,
        "created_at": created_at or msg.created_at,
        "user_id": msg.user_id,
        "speaker_type": msg.speaker_type.value,
    }


def make_briefing_db(*, message_rows=(), commitment_rows=(), snap_ts=None,
                     memories=0, threads_forked=0):
    """Mock asyncpg connection covering every query build_briefing makes."""
    db = AsyncMock()
    db.queries = []

    async def _fetch(sql, *args):
        db.queries.append(sql)
        if "FROM commitments" in sql:
            return list(commitment_rows)
        if "FROM messages" in sql:
            return list(message_rows)
        return []

    async def _fetchval(sql, *args):
        if "FROM memories" in sql:
            return memories
        if "FROM threads" in sql:
            return threads_forked
        return 0

    async def _fetchrow(sql, *args):
        if "FROM rooms" in sql:
            return {"snap_ts": snap_ts}
        return None

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchval = AsyncMock(side_effect=_fetchval)
    db.fetchrow = AsyncMock(side_effect=_fetchrow)
    db.execute = AsyncMock()
    return db


@pytest.fixture
def fake_llm(monkeypatch):
    """Intercept the Haiku summary call at its import site."""
    import llm.providers as providers

    provider = MagicMock()
    provider.complete = AsyncMock(return_value=MagicMock(content="A fake summary."))
    monkeypatch.setattr(providers, "get_provider", lambda name: provider)
    return provider


@pytest.mark.asyncio
class TestBuildBriefing:
    async def test_commitments_section(self, fake_llm):
        deadline = datetime.now(timezone.utc) + timedelta(hours=48)
        db = make_briefing_db(commitment_rows=[{
            "claim": "Brent closes above 90 by Friday",
            "resolution_criteria": "ICE settle price",
            "category": "prediction",
            "deadline": deadline,
        }])
        briefing = await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
        )
        assert len(briefing.commitments_due) == 1
        assert briefing.commitments_due[0]["claim"] == "Brent closes above 90 by Friday"
        assert briefing.commitments_due[0]["deadline"] == deadline
        assert briefing.summary == "Nothing happened while you were away."

    async def test_thesis_staleness_section(self, fake_llm):
        snap_ts = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat()
        db = make_briefing_db(snap_ts=snap_ts)
        briefing = await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
        )
        assert briefing.thesis_staleness is not None
        assert 25 < briefing.thesis_staleness["stale_hours"] < 27

    async def test_thesis_staleness_absent_without_trading_config(self, fake_llm):
        db = make_briefing_db(snap_ts=None)
        briefing = await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
        )
        assert briefing.thesis_staleness is None

    async def test_unanswered_question_detected(self, fake_llm):
        alice = make_user(display_name="Alice", user_id=USER_A)
        now = datetime.now(timezone.utc)
        db = make_briefing_db(message_rows=[
            # Newest first, as the SQL returns them.
            msg_row(alice, "following up on my own point",
                    created_at=now - timedelta(hours=1)),
            msg_row(alice, "what is the Hormuz escalation risk?",
                    message_type=MessageType.QUESTION,
                    created_at=now - timedelta(hours=2)),
        ])
        briefing = await build_briefing(
            db, ROOM_ID, now - timedelta(hours=24),
        )
        assert len(briefing.unanswered_questions) == 1
        assert briefing.unanswered_questions[0].speaker == "Alice"
        assert "Hormuz" in briefing.unanswered_questions[0].content_preview

    async def test_question_answered_by_other_speaker(self, fake_llm):
        alice = make_user(display_name="Alice", user_id=USER_A)
        bob = make_user(display_name="Bob", user_id=USER_B)
        now = datetime.now(timezone.utc)
        db = make_briefing_db(message_rows=[
            msg_row(bob, "about 40% per the model",
                    created_at=now - timedelta(hours=1)),
            msg_row(alice, "what is the Hormuz escalation risk?",
                    message_type=MessageType.QUESTION,
                    created_at=now - timedelta(hours=2)),
        ])
        briefing = await build_briefing(
            db, ROOM_ID, now - timedelta(hours=24),
        )
        assert briefing.unanswered_questions == []

    async def test_llm_summary_used_when_messages_exist(self, fake_llm):
        alice = make_user(display_name="Alice", user_id=USER_A)
        db = make_briefing_db(message_rows=[msg_row(alice)])
        briefing = await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
        )
        assert briefing.summary == "A fake summary."
        assert briefing.messages_missed == 1

    async def test_llm_failure_falls_back(self, fake_llm):
        fake_llm.complete = AsyncMock(side_effect=RuntimeError("boom"))
        alice = make_user(display_name="Alice", user_id=USER_A)
        db = make_briefing_db(message_rows=[msg_row(alice), msg_row(alice)])
        briefing = await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
        )
        assert briefing.summary == "2 messages were exchanged while you were away."

    async def test_exclude_user_id_keeps_endpoint_semantics(self, fake_llm):
        """The endpoint's "what *I* missed" filter survives the extraction."""
        db = make_briefing_db()
        await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
            exclude_user_id=USER_A,
        )
        message_sql = next(s for s in db.queries if "FROM messages" in s)
        assert "m.user_id != $3" in message_sql

    async def test_no_exclude_user_id_is_room_wide(self, fake_llm):
        db = make_briefing_db()
        await build_briefing(
            db, ROOM_ID, datetime.now(timezone.utc) - timedelta(hours=24),
        )
        message_sql = next(s for s in db.queries if "FROM messages" in s)
        assert "m.user_id != $3" not in message_sql


# =========================================================================
# morning_brief job — post + push over a mock pool
# =========================================================================


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


def make_job_db(*, rooms, members, briefs_today=0):
    """Mock asyncpg connection covering every query morning_brief makes."""
    db = AsyncMock()
    db.executed = []

    async def _fetch(sql, *args):
        if "48 hours" in sql:
            return rooms
        if "room_memberships" in sql:
            return [{"user_id": u} for u in members]
        return []

    async def _fetchrow(sql, *args):
        if "FROM threads" in sql:
            return {"id": THREAD_ID}
        return None

    async def _fetchval(sql, *args):
        if "night_shift" in sql:
            return briefs_today
        return 0

    async def _execute(sql, *args):
        db.executed.append(args)

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchrow = AsyncMock(side_effect=_fetchrow)
    db.fetchval = AsyncMock(side_effect=_fetchval)
    db.execute = AsyncMock(side_effect=_execute)
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
        commitments_due=[],
        thesis_staleness=None,
        unanswered_questions=[],
    )
    defaults.update(overrides)
    return BriefingResponse(**defaults)


@pytest.fixture
def push_calls(monkeypatch):
    """Intercept send_web_notifications at its import site."""
    calls = []

    async def _send(db, recipient_user_ids, title, body, data, tag=None):
        calls.append({"recipients": recipient_user_ids, "title": title,
                      "body": body, "data": data, "tag": tag})
        return {"sent": len(recipient_user_ids), "errors": []}

    import api.notifications.webpush as webpush_mod
    monkeypatch.setattr(webpush_mod, "send_web_notifications", _send)
    return calls


@pytest.fixture
def canned_briefing(monkeypatch):
    """Swap build_briefing for a canned response; records the calls."""
    calls = []

    async def _build(db, room_id, since, exclude_user_id=None):
        calls.append({"room_id": room_id, "since": since})
        return make_briefing()

    monkeypatch.setattr(night_shift, "build_briefing", _build)
    return calls


@pytest.mark.asyncio
class TestMorningBriefJob:
    def _ctx(self, db, connected=()):
        mgr = MagicMock()
        mgr.is_user_connected = MagicMock(
            side_effect=lambda user_id, room_id: user_id in connected
        )
        broadcast = AsyncMock()
        ctx = SchedulerContext(
            pool=FakePool(db), broadcast=broadcast, connection_manager=mgr,
        )
        return ctx, broadcast

    async def test_posts_brief_and_pushes_offline_members(
        self, canned_briefing, push_calls,
    ):
        rooms = [{"id": ROOM_ID, "name": "Hormuz Room"}]
        db = make_job_db(rooms=rooms, members=(USER_A, USER_B))
        ctx, broadcast = self._ctx(db, connected=(USER_A,))

        detail = await night_shift.morning_brief(ctx)

        entry = detail[str(ROOM_ID)]
        assert entry["messages_missed"] == 3
        assert entry["pushed"] == 1
        assert entry["message_id"] != "no_thread"

        # Only the member without an active WS to the room gets pushed.
        assert len(push_calls) == 1
        assert push_calls[0]["recipients"] == [str(USER_B)]
        assert push_calls[0]["tag"] == f"brief_{ROOM_ID}"
        assert push_calls[0]["data"]["type"] == "morning_brief"

        # The brief lands as an annotator-lane message sourced night_shift,
        # and goes out over the broadcast.
        inserts = [a for a in db.executed
                   if any(isinstance(v, dict) and v.get("source") == "night_shift"
                          for v in a)]
        assert inserts, "expected a message insert with night_shift metadata"
        broadcast.assert_awaited_once()

    async def test_everyone_watching_means_no_push(
        self, canned_briefing, push_calls,
    ):
        rooms = [{"id": ROOM_ID, "name": "Hormuz Room"}]
        db = make_job_db(rooms=rooms, members=(USER_A, USER_B))
        ctx, _ = self._ctx(db, connected=(USER_A, USER_B))

        detail = await night_shift.morning_brief(ctx)

        assert detail[str(ROOM_ID)]["pushed"] == 0
        assert push_calls == []

    async def test_quiet_room_is_skipped_without_spending(
        self, monkeypatch, push_calls,
    ):
        async def _quiet(db, room_id, since, exclude_user_id=None):
            return make_briefing(summary="Nothing happened while you were away.",
                                 messages_missed=0)

        monkeypatch.setattr(night_shift, "build_briefing", _quiet)
        rooms = [{"id": ROOM_ID, "name": "Hormuz Room"}]
        db = make_job_db(rooms=rooms, members=(USER_A,))
        ctx, broadcast = self._ctx(db)

        detail = await night_shift.morning_brief(ctx)

        assert detail[str(ROOM_ID)] == "quiet"
        assert db.executed == []
        broadcast.assert_not_awaited()
        assert push_calls == []

    async def test_llm_cap_stops_the_line(self, monkeypatch, push_calls):
        build_calls = []

        async def _build(db, room_id, since, exclude_user_id=None):
            build_calls.append(room_id)
            return make_briefing()

        monkeypatch.setattr(night_shift, "build_briefing", _build)
        rooms = [{"id": uuid4(), "name": f"Room {i}"} for i in range(3)]
        db = make_job_db(rooms=rooms, members=(USER_A,),
                         briefs_today=night_shift.NIGHT_SHIFT_LLM_CAP)
        ctx, _ = self._ctx(db)

        detail = await night_shift.morning_brief(ctx)

        assert build_calls == []
        assert all(v == "cap_reached" for v in detail.values())
        assert push_calls == []

    async def test_rooms_query_scoped_to_recent_activity(
        self, canned_briefing, push_calls,
    ):
        """A room with nothing in 48h never reaches the builder."""
        db = make_job_db(rooms=[], members=(USER_A,))
        ctx, _ = self._ctx(db)

        detail = await night_shift.morning_brief(ctx)

        assert detail == {}
        assert canned_briefing == []
