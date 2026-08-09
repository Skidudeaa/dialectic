"""
Tests for the participation FSM (W6 / P4): llm/participation_fsm.py,
the self-model FSM rendering, the orchestrator's force_silence toggle,
and the llm/silence_sweep.py job.

WHY this file exists: the sweep makes the LLM speak with nobody in the
room. The expensive mistakes are a follow-up that fires twice for one
quiet event, fires during quiet hours, fires with the room toggle off, or
fires a fourth time in a day — and an FSM whose unknown transitions crash
a turn instead of logging and holding state. Mirrors
cc-sidecar/tests/test_reducer.py: one test per legal transition.
"""

import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from llm import silence_sweep
from llm.orchestrator import LLMOrchestrator, OrchestrationResult
from llm.participation_fsm import (
    EVENT_FOLLOW_UP_SENT,
    EVENT_HUMAN_MESSAGE,
    EVENT_HUMAN_QUESTION,
    EVENT_LLM_SILENCE,
    EVENT_LLM_SPOKE,
    EVENT_QUESTION_ANSWERED,
    TRANSITIONS,
    ParticipationFSM,
    ParticipationState as S,
    StateSource,
    decision_event,
)
from llm.self_model import ParticipationSnapshot, SelfModel
from models import SpeakerType
from scheduler import Scheduler, SchedulerContext

from tests.conftest import (
    make_message,
    make_room,
    make_thread,
    make_user,
)


def machine_in(state: S, **kwargs) -> ParticipationFSM:
    """Hydrate a machine directly into a state (via the snapshot path)."""
    snap = {
        "state": state.value,
        "state_entered_at": datetime.now(timezone.utc).isoformat(),
    }
    snap.update(kwargs)
    return ParticipationFSM.from_snapshot(snap)


# =========================================================================
# Transition table — one test per legal entry
# =========================================================================


class TestTransitionTable:
    # ── From ENGAGED ──

    def test_engaged_human_message_stays_engaged(self):
        m = machine_in(S.ENGAGED)
        assert m.apply(EVENT_HUMAN_MESSAGE) == S.ENGAGED

    def test_engaged_human_question_to_question_pending(self):
        m = machine_in(S.ENGAGED)
        assert m.apply(EVENT_HUMAN_QUESTION) == S.QUESTION_PENDING

    def test_engaged_llm_spoke_to_awaiting_human(self):
        m = machine_in(S.ENGAGED)
        assert m.apply(EVENT_LLM_SPOKE) == S.AWAITING_HUMAN

    def test_engaged_llm_silence_stays_engaged(self):
        m = machine_in(S.ENGAGED)
        assert m.apply(EVENT_LLM_SILENCE) == S.ENGAGED

    # ── From AWAITING_HUMAN ──

    def test_awaiting_human_message_to_engaged(self):
        m = machine_in(S.AWAITING_HUMAN)
        assert m.apply(EVENT_HUMAN_MESSAGE) == S.ENGAGED

    def test_awaiting_human_question_to_question_pending(self):
        m = machine_in(S.AWAITING_HUMAN)
        assert m.apply(EVENT_HUMAN_QUESTION) == S.QUESTION_PENDING

    def test_awaiting_human_llm_spoke_stays_awaiting(self):
        m = machine_in(S.AWAITING_HUMAN)
        assert m.apply(EVENT_LLM_SPOKE) == S.AWAITING_HUMAN

    def test_awaiting_human_llm_silence_to_ignored(self):
        m = machine_in(S.AWAITING_HUMAN)
        assert m.apply(EVENT_LLM_SILENCE) == S.IGNORED

    # ── From QUESTION_PENDING ──

    def test_question_pending_human_message_stays_pending(self):
        m = machine_in(S.QUESTION_PENDING)
        assert m.apply(EVENT_HUMAN_MESSAGE) == S.QUESTION_PENDING

    def test_question_pending_human_question_stays_pending(self):
        m = machine_in(S.QUESTION_PENDING)
        assert m.apply(EVENT_HUMAN_QUESTION) == S.QUESTION_PENDING

    def test_question_pending_llm_spoke_to_awaiting(self):
        m = machine_in(S.QUESTION_PENDING)
        assert m.apply(EVENT_LLM_SPOKE) == S.AWAITING_HUMAN

    def test_question_pending_llm_silence_stays_pending(self):
        m = machine_in(S.QUESTION_PENDING)
        assert m.apply(EVENT_LLM_SILENCE) == S.QUESTION_PENDING

    def test_question_pending_question_answered_to_awaiting(self):
        m = machine_in(S.QUESTION_PENDING)
        assert m.apply(EVENT_QUESTION_ANSWERED) == S.AWAITING_HUMAN

    def test_question_pending_follow_up_sent_to_awaiting(self):
        """The transition that IS the per-event cap: after the sweep's one
        follow-up the machine has left question_pending."""
        m = machine_in(S.QUESTION_PENDING)
        assert m.apply(EVENT_FOLLOW_UP_SENT) == S.AWAITING_HUMAN

    # ── From IGNORED ──

    def test_ignored_human_message_stays_ignored(self):
        m = machine_in(S.IGNORED)
        assert m.apply(EVENT_HUMAN_MESSAGE) == S.IGNORED

    def test_ignored_human_question_to_question_pending(self):
        m = machine_in(S.IGNORED)
        assert m.apply(EVENT_HUMAN_QUESTION) == S.QUESTION_PENDING

    def test_ignored_llm_spoke_to_awaiting(self):
        m = machine_in(S.IGNORED)
        assert m.apply(EVENT_LLM_SPOKE) == S.AWAITING_HUMAN

    def test_ignored_llm_silence_stays_ignored(self):
        m = machine_in(S.IGNORED)
        assert m.apply(EVENT_LLM_SILENCE) == S.IGNORED

    def test_ignored_follow_up_sent_to_awaiting(self):
        m = machine_in(S.IGNORED)
        assert m.apply(EVENT_FOLLOW_UP_SENT) == S.AWAITING_HUMAN

    # ── From DORMANT ──

    def test_dormant_human_message_to_engaged(self):
        m = machine_in(S.DORMANT)
        assert m.apply(EVENT_HUMAN_MESSAGE) == S.ENGAGED

    def test_dormant_human_question_to_question_pending(self):
        m = machine_in(S.DORMANT)
        assert m.apply(EVENT_HUMAN_QUESTION) == S.QUESTION_PENDING

    def test_dormant_llm_spoke_to_awaiting(self):
        m = machine_in(S.DORMANT)
        assert m.apply(EVENT_LLM_SPOKE) == S.AWAITING_HUMAN

    def test_dormant_llm_silence_stays_dormant(self):
        m = machine_in(S.DORMANT)
        assert m.apply(EVENT_LLM_SILENCE) == S.DORMANT

    # ── Table hygiene ──

    def test_unknown_transition_logged_and_unchanged(self, caplog):
        m = machine_in(S.ENGAGED)
        with caplog.at_level(logging.DEBUG):
            result = m.apply(EVENT_FOLLOW_UP_SENT)  # illegal from engaged
        assert result is None
        assert m.state == S.ENGAGED
        assert any("No transition" in r.message for r in caplog.records)

    def test_every_table_target_is_a_known_state(self):
        for (state, event), target in TRANSITIONS.items():
            assert isinstance(state, S) and isinstance(target, S)
            assert isinstance(event, str) and event


class TestStateBookkeeping:
    def test_state_entered_at_advances_on_change(self):
        m = machine_in(
            S.ENGAGED,
            state_entered_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        before = m.state_entered_at
        m.apply(EVENT_HUMAN_QUESTION)
        assert m.state == S.QUESTION_PENDING
        assert m.state_entered_at > before

    def test_state_entered_at_holds_on_self_loop(self):
        """Chatter under a pending question must not restart the sweep's clock."""
        m = machine_in(
            S.QUESTION_PENDING,
            state_entered_at=(datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat(),
        )
        before = m.state_entered_at
        m.apply(EVENT_HUMAN_MESSAGE)
        assert m.state == S.QUESTION_PENDING
        assert m.state_entered_at == before

    def test_apply_sets_observed_source(self):
        m = machine_in(S.ENGAGED, state_source="inferred")
        m.apply(EVENT_HUMAN_MESSAGE)
        assert m.state_source == StateSource.OBSERVED


# =========================================================================
# StateSource tiers
# =========================================================================


class TestStateSource:
    def test_mark_dormant_is_inferred_and_bypasses_table(self):
        # engaged + nothing = dormant has no table entry; the timer path
        # reaches it anyway, with INFERRED confidence.
        assert (S.ENGAGED, "dormant_timer") not in TRANSITIONS
        m = machine_in(S.ENGAGED, state_source="observed")
        m.mark_dormant()
        assert m.state == S.DORMANT
        assert m.state_source == StateSource.INFERRED

    def test_truncation_downgrades_observed_to_reconciled(self):
        m = machine_in(S.QUESTION_PENDING, state_source="observed")
        m.note_truncation()
        assert m.state == S.QUESTION_PENDING  # flag, not a state change
        assert m.context_truncated is True
        assert m.state_source == StateSource.RECONCILED

    def test_second_truncation_downgrades_to_inferred(self):
        m = machine_in(S.ENGAGED, state_source="reconciled")
        m.note_truncation()
        assert m.state_source == StateSource.INFERRED

    def test_fresh_event_clears_truncation_and_restores_observed(self):
        m = machine_in(S.ENGAGED)
        m.note_truncation()
        m.apply(EVENT_HUMAN_QUESTION)
        assert m.state_source == StateSource.OBSERVED
        assert m.context_truncated is False

    def test_snapshot_round_trip(self):
        m = machine_in(S.IGNORED, state_source="reconciled")
        m.note_truncation()
        snap = m.to_snapshot()
        m2 = ParticipationFSM.from_snapshot(snap)
        assert m2.state == S.IGNORED
        assert m2.state_source == StateSource.INFERRED
        assert m2.state_entered_at == m.state_entered_at
        assert m2.context_truncated is True


class TestDecisionEvent:
    def test_spoke_with_pending_question_is_question_answered(self):
        assert decision_event(
            spoke=True, is_question=True, current_state=S.QUESTION_PENDING,
        ) == EVENT_QUESTION_ANSWERED

    def test_spoke_otherwise_is_llm_spoke(self):
        assert decision_event(
            spoke=True, is_question=True, current_state=S.ENGAGED,
        ) == EVENT_LLM_SPOKE

    def test_silence_on_question_is_human_question(self):
        assert decision_event(
            spoke=False, is_question=True, current_state=S.ENGAGED,
        ) == EVENT_HUMAN_QUESTION

    def test_silence_while_awaiting_human_is_llm_silence(self):
        assert decision_event(
            spoke=False, is_question=False, current_state=S.AWAITING_HUMAN,
        ) == EVENT_LLM_SILENCE

    def test_silence_otherwise_is_human_message(self):
        assert decision_event(
            spoke=False, is_question=False, current_state=S.ENGAGED,
        ) == EVENT_HUMAN_MESSAGE


# =========================================================================
# Self-awareness rendering
# =========================================================================


class TestSelfAwarenessRender:
    def test_fsm_lines_rendered(self):
        snapshot = ParticipationSnapshot(
            fsm_state="question_pending", state_source="observed",
        )
        text = SelfModel(db=None).render_self_awareness(snapshot)
        assert "Participation state: question_pending" in text
        assert "unanswered" in text
        assert "State confidence: observed" in text

    def test_missing_fsm_fields_render_nothing(self):
        text = SelfModel(db=None).render_self_awareness(ParticipationSnapshot())
        assert "Participation state" not in text
        assert "State confidence" not in text


# =========================================================================
# Quiet hours — 23:00–07:00 America/Chicago (August = CDT, UTC-5)
# =========================================================================


class TestQuietHours:
    def test_2300_local_is_quiet(self):
        now = datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)  # 23:00 CDT
        assert silence_sweep.in_quiet_hours(now) is True

    def test_2259_local_is_not_quiet(self):
        now = datetime(2026, 8, 9, 3, 59, tzinfo=timezone.utc)  # 22:59 CDT
        assert silence_sweep.in_quiet_hours(now) is False

    def test_0659_local_is_quiet(self):
        now = datetime(2026, 8, 9, 11, 59, tzinfo=timezone.utc)  # 06:59 CDT
        assert silence_sweep.in_quiet_hours(now) is True

    def test_0700_local_is_not_quiet(self):
        now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)  # 07:00 CDT
        assert silence_sweep.in_quiet_hours(now) is False

    def test_midday_is_not_quiet(self):
        now = datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc)  # 12:00 CDT
        assert silence_sweep.in_quiet_hours(now) is False

    def test_env_override_same_day_window(self, monkeypatch):
        monkeypatch.setenv("FSM_QUIET_START", "09:00")
        monkeypatch.setenv("FSM_QUIET_END", "17:00")
        now = datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc)  # 12:00 CDT
        assert silence_sweep.in_quiet_hours(now) is True


# =========================================================================
# Heuristic-path toggle: force_silence suppresses speech, silence still logs
# =========================================================================


@pytest.mark.asyncio
class TestForceSilenceToggle:
    async def test_interjection_suppressed_and_silence_logged(self):
        db = AsyncMock()
        db.fetchrow = AsyncMock(return_value=None)  # no FSM row yet
        orchestrator = LLMOrchestrator(db)
        orchestrator._self_model.log_decision = AsyncMock(return_value=1)

        question = make_message(content="what do you think about Hormuz?")
        result = await orchestrator.on_message(
            room=make_room(),
            thread=make_thread(),
            users=[make_user()],
            messages=[question],
            memories=[],
            force_silence=True,
        )

        assert result.triggered is False
        assert result.decision.should_interject is False
        assert result.decision.reason == "auto_interjection_disabled"

        # The silence decision still hits the self-model ledger, and the FSM
        # saw the human question land on the floor.
        kwargs = orchestrator._self_model.log_decision.await_args.kwargs
        assert kwargs["mode"] == "silence"
        assert kwargs["fsm_state"] == "question_pending"
        assert kwargs["state_source"] == "observed"
        assert kwargs["state_entered_at"] is not None

    async def test_normal_path_unaffected_without_flag(self):
        db = AsyncMock()
        db.fetchrow = AsyncMock(return_value=None)
        orchestrator = LLMOrchestrator(db)
        orchestrator._self_model.log_decision = AsyncMock(return_value=1)

        # A plain statement, no heuristic fires — the ordinary no_trigger
        # silence, not the toggle's reason.
        result = await orchestrator.on_message(
            room=make_room(),
            thread=make_thread(),
            users=[make_user()],
            messages=[make_message(content="filled the car up today")],
            memories=[],
        )

        assert result.triggered is False
        assert result.decision.reason == "no_trigger"


# =========================================================================
# participation_sweep job — scripted acceptance over a mock pool
# =========================================================================


ROOM_ID = uuid4()


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


def sweep_row(state, *, minutes_ago=15, source="observed", toggle=True):
    return {
        "room_id": ROOM_ID,
        "fsm_state": state,
        "state_entered_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        "state_source": source,
        "auto_interjection_enabled": toggle,
    }


def make_sweep_db(*, rows, followups_today=0):
    """Mock asyncpg connection covering the sweep's queries. The ledger for
    fsm upserts is `executed` — UPDATE args land there for assertion."""
    db = AsyncMock()
    db.executed = []

    async def _fetch(sql, *args):
        if "FROM llm_participation_state" in sql:
            return list(rows)
        return []

    async def _fetchval(sql, *args):
        if "FROM llm_decisions" in sql:
            return followups_today
        return 0

    async def _execute(sql, *args):
        db.executed.append((sql, args))

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchval = AsyncMock(side_effect=_fetchval)
    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.fixture
def follow_up_calls(monkeypatch):
    """Intercept force_response at the sweep's import site; records calls and
    returns a persisted-message-shaped result."""
    calls = []

    async def _fake(self, *, room, thread, users, messages, memories,
                  use_provoker=False, protocol=None, reason=None):
        calls.append({"room_id": room.id, "reason": reason})
        response = make_message(
            content="Still chewing on that one.",
            speaker_type=SpeakerType.LLM_PRIMARY,
            user_id=None,
        )
        return OrchestrationResult(
            triggered=True, decision=None, response=response,
            routing=None, prompt_used=None,
        )

    monkeypatch.setattr(silence_sweep.LLMOrchestrator, "force_response", _fake)
    return calls


@pytest.fixture
def room_context(monkeypatch):
    """Skip the heavy Room/Thread/users/messages/memories load."""
    async def _load(conn, room_id):
        return (make_room(id=room_id), make_thread(), [make_user()],
                [make_message(content="what is the Hormuz risk?")], [])

    monkeypatch.setattr(silence_sweep, "_load_room_context", _load)


def fsm_upserts(db):
    """The update_fsm_state writes captured by the mock ledger."""
    return [args for sql, args in db.executed
            if "INSERT INTO llm_participation_state" in sql
            and "fsm_state" in sql]


@pytest.mark.asyncio
class TestParticipationSweep:
    def _ctx(self, db):
        broadcast = AsyncMock()
        return SchedulerContext(pool=FakePool(db), broadcast=broadcast), broadcast

    async def test_question_plus_ten_minutes_sends_exactly_one_follow_up(
        self, follow_up_calls, room_context,
    ):
        db = make_sweep_db(rows=[sweep_row("question_pending", minutes_ago=15)])
        ctx, broadcast = self._ctx(db)

        detail = await silence_sweep.participation_sweep(ctx)

        assert len(follow_up_calls) == 1
        assert follow_up_calls[0]["reason"] == "silence_follow_up"
        assert "follow_up" in detail[str(ROOM_ID)]

        # The machine left question_pending — persisted as awaiting_human —
        # which is what makes a second pass skip the room.
        upserts = fsm_upserts(db)
        assert len(upserts) == 1
        assert upserts[0][1] == "awaiting_human"
        broadcast.assert_awaited_once()

        # Second pass over the post-transition row: zero more follow-ups.
        db2 = make_sweep_db(rows=[sweep_row("awaiting_human", minutes_ago=30)])
        ctx2, _ = self._ctx(db2)
        detail2 = await silence_sweep.participation_sweep(ctx2)
        assert len(follow_up_calls) == 1
        assert detail2 == {}

    async def test_further_silence_after_follow_up_sends_zero_more(
        self, follow_up_calls, room_context,
    ):
        db = make_sweep_db(rows=[sweep_row("awaiting_human", minutes_ago=120)])
        ctx, _ = self._ctx(db)
        await silence_sweep.participation_sweep(ctx)
        assert follow_up_calls == []

    async def test_quiet_hours_send_zero(self, follow_up_calls, monkeypatch):
        monkeypatch.setattr(silence_sweep, "in_quiet_hours", lambda now=None: True)
        db = make_sweep_db(rows=[sweep_row("question_pending", minutes_ago=60)])
        ctx, _ = self._ctx(db)
        detail = await silence_sweep.participation_sweep(ctx)
        assert detail == {"skipped": "quiet_hours"}
        assert follow_up_calls == []

    async def test_toggle_off_sends_zero(self, follow_up_calls, room_context):
        db = make_sweep_db(rows=[sweep_row("question_pending", toggle=False)])
        ctx, _ = self._ctx(db)
        detail = await silence_sweep.participation_sweep(ctx)
        assert detail[str(ROOM_ID)] == "toggle_off"
        assert follow_up_calls == []

    async def test_cap_stops_the_fourth_follow_up(
        self, follow_up_calls, room_context,
    ):
        db = make_sweep_db(
            rows=[sweep_row("question_pending", minutes_ago=60)],
            followups_today=silence_sweep.DAILY_FOLLOWUP_CAP,
        )
        ctx, _ = self._ctx(db)
        detail = await silence_sweep.participation_sweep(ctx)
        assert detail[str(ROOM_ID)] == "cap_reached"
        assert follow_up_calls == []

    async def test_under_the_delay_is_cooling(self, follow_up_calls, room_context):
        db = make_sweep_db(rows=[sweep_row("question_pending", minutes_ago=5)])
        ctx, _ = self._ctx(db)
        detail = await silence_sweep.participation_sweep(ctx)
        assert detail[str(ROOM_ID)] == "cooling"
        assert follow_up_calls == []

    async def test_ignored_state_also_gets_a_follow_up(
        self, follow_up_calls, room_context,
    ):
        db = make_sweep_db(rows=[sweep_row("ignored", minutes_ago=45)])
        ctx, _ = self._ctx(db)
        detail = await silence_sweep.participation_sweep(ctx)
        assert len(follow_up_calls) == 1
        assert "follow_up" in detail[str(ROOM_ID)]

    async def test_stale_machine_marked_dormant_inferred(
        self, follow_up_calls, room_context,
    ):
        db = make_sweep_db(rows=[sweep_row("engaged", minutes_ago=48 * 60)])
        ctx, _ = self._ctx(db)
        detail = await silence_sweep.participation_sweep(ctx)
        assert detail[str(ROOM_ID)] == "dormant"
        assert follow_up_calls == []
        upserts = fsm_upserts(db)
        assert len(upserts) == 1
        assert upserts[0][1] == "dormant"
        assert upserts[0][3] == "inferred"


class TestSweepJobRegistration:
    def test_registers_60s_interval_job(self):
        sched = Scheduler(SchedulerContext(pool=None))
        silence_sweep.register_sweep_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "participation_sweep"
        assert job.interval_s == 60
        assert job.enabled_env == "PARTICIPATION_SWEEP_ENABLED"

    @pytest.mark.asyncio
    async def test_env_gate_off_skips_the_job(self, monkeypatch):
        monkeypatch.setenv("PARTICIPATION_SWEEP_ENABLED", "0")
        sched = Scheduler(SchedulerContext(pool=None))
        silence_sweep.register_sweep_jobs(sched)

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)  # ledger claim succeeds
        await sched._tick(conn)
        conn.execute.assert_not_called()
