"""
Tests for api/trading_ingest — who gets told when a snapshot arrives.

WHY this file exists separately from test_trading_snapshot.py: that one is
about the SHAPE of a payload. This one is about the CONSEQUENCE of one —
whether an LLM alert is generated and whether a phone buzzes. Those are the
expensive mistakes: a curator that fires on every 300s tick turns the room
into noise, and a critical node firing that nobody is told about is the
failure the whole pipeline exists to prevent.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from models import TradingSnapshotRequest, SpeakerType
from api import trading_ingest
from api.trading_ingest import (
    CURATOR_DAILY_CAP,
    CRITICAL_DEDUP_MINUTES,
    WARNING_DEDUP_MINUTES,
    critical_events,
    curator_plan,
    ingest_snapshot,
    max_severity,
)


ROOM_ID = uuid4()
THREAD_ID = uuid4()
USER_A = uuid4()
USER_B = uuid4()


def event(severity="critical", node_id="hormuz_closure",
          old="approaching", new="fired",
          event_type="node.state_changed") -> dict:
    return {
        "event_type": event_type,
        "severity": severity,
        "node_id": node_id,
        "old_value": old,
        "new_value": new,
    }


def make_request(v=3, alert_events=None, **overrides) -> TradingSnapshotRequest:
    body = dict(
        v=v,
        timestamp="2026-08-09T05:07:15Z",
        title="Iran/Hormuz Cascade",
        nodeStates={"hormuz_closure": "fired", "brent_spike": "stable"},
        cascadePhase={"number": 2, "key": "escalation", "status": "active"},
    )
    if v >= 3 and alert_events is not None:
        body["alertEvents"] = alert_events
    body.update(overrides)
    return TradingSnapshotRequest(**body)


# =========================================================================
# SEVERITY HELPERS
# =========================================================================


class TestSeverityHelpers:
    def test_max_severity_of_empty_is_none(self):
        assert max_severity([]) is None

    def test_max_severity_picks_the_highest(self):
        events = [event(severity="info"), event(severity="warning"),
                  event(severity="critical")]
        assert max_severity(events) == "critical"

    def test_max_severity_ignores_ordering(self):
        events = [event(severity="critical"), event(severity="info")]
        assert max_severity(events) == "critical"

    def test_unknown_severity_ranks_below_info(self):
        """A typo'd severity must not be treated as important."""
        assert max_severity([event(severity="URGENT!!")]) is None

    def test_severity_match_is_case_insensitive(self):
        assert max_severity([event(severity="CRITICAL")]) == "critical"

    def test_critical_events_filters(self):
        events = [event(severity="warning"), event(severity="critical"),
                  event(severity="info")]
        assert critical_events(events) == [events[1]]

    def test_non_dict_entries_are_skipped(self):
        """A malformed payload must not crash ingest."""
        assert max_severity(["not-a-dict", event(severity="warning")]) == "warning"
        assert critical_events(["nope"]) == []


# =========================================================================
# CURATOR GATING
# =========================================================================


class TestCuratorPlan:
    def test_v3_with_no_events_stays_silent(self):
        """The 300s heartbeat must not generate a paragraph about nothing."""
        assert curator_plan(make_request(v=3, alert_events=[])) is None

    def test_v3_with_only_info_events_stays_silent(self):
        plan = curator_plan(make_request(
            v=3, alert_events=[event(severity="info", new="monitoring")],
        ))
        assert plan is None

    def test_v3_warning_fires_with_the_long_window_and_the_cap(self):
        plan = curator_plan(make_request(
            v=3, alert_events=[event(severity="warning", new="approaching")],
        ))
        assert plan == {
            "dedup_window_minutes": WARNING_DEDUP_MINUTES,
            "daily_cap": CURATOR_DAILY_CAP,
        }

    def test_v3_critical_fires_with_the_short_window_and_no_cap(self):
        """A node firing is the event the pipeline exists for — the daily
        budget must not be able to swallow it."""
        plan = curator_plan(make_request(v=3, alert_events=[event()]))
        assert plan == {
            "dedup_window_minutes": CRITICAL_DEDUP_MINUTES,
            "daily_cap": None,
        }

    def test_critical_still_dedups(self):
        """Bypassing the cap is not bypassing dedup."""
        plan = curator_plan(make_request(v=3, alert_events=[event()]))
        assert plan["dedup_window_minutes"] == CRITICAL_DEDUP_MINUTES

    def test_a_critical_among_warnings_wins(self):
        plan = curator_plan(make_request(v=3, alert_events=[
            event(severity="warning"), event(severity="critical"),
        ]))
        assert plan["daily_cap"] is None

    @pytest.mark.parametrize("version", [1, 2])
    def test_legacy_payloads_keep_alerting_on_every_receipt(self, version):
        """The CLI bridge pushes v1/v2 with no alertEvents field. Gating those
        off would silently retire the bridge's alerting."""
        plan = curator_plan(make_request(v=version))
        assert plan is not None
        assert plan["dedup_window_minutes"] == CRITICAL_DEDUP_MINUTES
        assert plan["daily_cap"] == CURATOR_DAILY_CAP


# =========================================================================
# INGEST — END TO END OVER A MOCK DB
# =========================================================================


def make_db(*, members=(USER_A, USER_B), curator_today=0, room_name="Hormuz Room"):
    """Mock asyncpg connection covering every query ingest_snapshot makes."""
    db = AsyncMock()

    async def _fetchrow(sql, *args):
        if "FROM memories" in sql:
            return None            # no existing thesis_state_current
        if "FROM threads" in sql:
            return {"id": THREAD_ID}
        if "FROM rooms" in sql:
            return {"name": room_name}
        return None

    async def _fetch(sql, *args):
        if "room_memberships" in sql:
            return [{"user_id": u} for u in members]
        return []

    async def _fetchval(sql, *args):
        # TradingCuratorEngine.should_alert -> offline member count
        if "user_presence" in sql:
            return 1
        # is_duplicate / count_today -> curator message count
        return curator_today

    db.fetchrow = AsyncMock(side_effect=_fetchrow)
    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchval = AsyncMock(side_effect=_fetchval)
    db.execute = AsyncMock()
    return db


def make_connection_manager(connected=()):
    mgr = MagicMock()
    mgr.broadcast = AsyncMock()
    mgr.is_user_connected = MagicMock(
        side_effect=lambda user_id, room_id: user_id in connected
    )
    return mgr


@pytest.fixture
def stub_memory(monkeypatch):
    """MemoryManager.add_memory returns an object with an .id."""
    memory = MagicMock()
    memory.id = uuid4()

    manager = MagicMock()
    manager.add_memory = AsyncMock(return_value=memory)
    manager.edit_memory = AsyncMock(return_value=memory)
    monkeypatch.setattr(trading_ingest, "MemoryManager", lambda db: manager)
    return manager


@pytest.fixture
def curator_calls(monkeypatch):
    """Record generate_alert invocations instead of calling an LLM."""
    calls = []

    class _Curator:
        def __init__(self, db, memory, provider):
            pass

        async def generate_alert(self, room_id, thread_id, snapshot, **kwargs):
            calls.append({"room_id": room_id, "snapshot": snapshot, **kwargs})
            return None

    monkeypatch.setattr(trading_ingest, "TradingCuratorEngine", _Curator)
    return calls


@pytest.fixture
def push_calls(monkeypatch):
    """Intercept send_web_notifications at its import site."""
    calls = []

    async def _send(db, recipients, title, body, data, tag=None):
        calls.append({"recipients": recipients, "title": title, "body": body,
                      "data": data, "tag": tag})
        return {"sent": len(recipients), "errors": []}

    import api.notifications.webpush as webpush_mod
    monkeypatch.setattr(webpush_mod, "send_web_notifications", _send)
    return calls


@pytest.mark.asyncio
class TestIngestCuratorInvocation:
    async def test_v3_empty_events_does_not_invoke_curator(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[]),
        )
        assert curator_calls == []

    async def test_v3_critical_invokes_curator(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
        )
        assert len(curator_calls) == 1
        assert curator_calls[0]["dedup_window_minutes"] == CRITICAL_DEDUP_MINUTES
        assert curator_calls[0]["daily_cap"] is None

    async def test_v3_warning_invokes_curator_under_the_cap(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event(severity="warning")]),
        )
        assert len(curator_calls) == 1
        assert curator_calls[0]["daily_cap"] == CURATOR_DAILY_CAP

    async def test_v2_still_invokes_curator(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID, make_request(v=2),
        )
        assert len(curator_calls) == 1

    async def test_reconcile_source_suppresses_the_curator(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
            fire_curator=False,
        )
        assert curator_calls == []

    async def test_snapshot_is_still_stored_when_alerts_are_suppressed(
        self, stub_memory, curator_calls, push_calls,
    ):
        """Suppressing the alert must not suppress the receipt."""
        db = make_db()
        resp = await ingest_snapshot(
            db, make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
            fire_curator=False,
        )
        assert resp.memory_id is not None
        update_sql = [c.args[0] for c in db.execute.call_args_list
                      if "UPDATE rooms" in c.args[0]]
        assert len(update_sql) == 1

    async def test_curator_failure_does_not_fail_ingest(
        self, stub_memory, push_calls, monkeypatch,
    ):
        class _Boom:
            def __init__(self, *a):
                pass

            async def generate_alert(self, *a, **k):
                raise RuntimeError("anthropic down")

        monkeypatch.setattr(trading_ingest, "TradingCuratorEngine", _Boom)
        resp = await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
        )
        assert resp.memory_id is not None


@pytest.mark.asyncio
class TestIngestCriticalPush:
    async def test_critical_pushes_to_members(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
        )
        assert len(push_calls) == 1
        assert set(push_calls[0]["recipients"]) == {str(USER_A), str(USER_B)}

    async def test_push_title_names_room_node_and_new_value(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(room_name="Hormuz Room"), make_connection_manager(),
            ROOM_ID, make_request(v=3, alert_events=[event()]),
        )
        assert push_calls[0]["title"] == "Hormuz Room: hormuz_closure fired"

    async def test_push_body_is_one_line(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
        )
        body = push_calls[0]["body"]
        assert "\n" not in body
        assert "approaching → fired" in body

    async def test_push_data_and_tag(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
        )
        assert push_calls[0]["data"] == {
            "room_id": str(ROOM_ID), "type": "trading_alert",
        }
        assert push_calls[0]["tag"] == f"trading_{ROOM_ID}"

    async def test_connected_members_are_excluded(
        self, stub_memory, curator_calls, push_calls,
    ):
        """A member with the room open on an active socket already sees it."""
        await ingest_snapshot(
            make_db(), make_connection_manager(connected={USER_A}),
            ROOM_ID, make_request(v=3, alert_events=[event()]),
        )
        assert push_calls[0]["recipients"] == [str(USER_B)]

    async def test_no_push_when_every_member_is_connected(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(connected={USER_A, USER_B}),
            ROOM_ID, make_request(v=3, alert_events=[event()]),
        )
        assert push_calls == []

    async def test_offline_members_are_pushed_regardless_of_presence(
        self, stub_memory, curator_calls, push_calls,
    ):
        """Unlike an ordinary message push, a critical is NOT suppressed by an
        'online' presence row — only by a live socket to this room."""
        db = make_db()
        await ingest_snapshot(
            db, make_connection_manager(connected=()),
            ROOM_ID, make_request(v=3, alert_events=[event()]),
        )
        assert len(push_calls[0]["recipients"]) == 2

    async def test_warning_only_does_not_push(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event(severity="warning")]),
        )
        assert push_calls == []

    async def test_v2_never_pushes(
        self, stub_memory, curator_calls, push_calls,
    ):
        """v1/v2 carry no events, so there is no critical to announce."""
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID, make_request(v=2),
        )
        assert push_calls == []

    async def test_reconcile_does_not_push(
        self, stub_memory, curator_calls, push_calls,
    ):
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
            fire_curator=False,
        )
        assert push_calls == []

    async def test_push_failure_does_not_fail_ingest(
        self, stub_memory, curator_calls, monkeypatch,
    ):
        async def _boom(*a, **k):
            raise RuntimeError("VAPID misconfigured")

        import api.notifications.webpush as webpush_mod
        monkeypatch.setattr(webpush_mod, "send_web_notifications", _boom)
        resp = await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
        )
        assert resp.memory_id is not None

    async def test_multiple_criticals_summarised_with_overflow(
        self, stub_memory, curator_calls, push_calls,
    ):
        events = [event(node_id=f"node_{i}") for i in range(5)]
        await ingest_snapshot(
            make_db(), make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=events),
        )
        assert "+2 more" in push_calls[0]["body"]


@pytest.mark.asyncio
class TestIngestBroadcast:
    async def test_alert_events_reach_connected_clients(
        self, stub_memory, curator_calls, push_calls,
    ):
        mgr = make_connection_manager()
        events = [event()]
        await ingest_snapshot(
            make_db(), mgr, ROOM_ID, make_request(v=3, alert_events=events),
        )
        payload = mgr.broadcast.call_args_list[0].args[1].payload
        assert payload["v"] == 3
        assert payload["alertEvents"] == events

    async def test_event_row_records_severity(
        self, stub_memory, curator_calls, push_calls,
    ):
        db = make_db()
        await ingest_snapshot(
            db, make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[event()]),
        )
        inserts = [c for c in db.execute.call_args_list
                   if "INSERT INTO events" in c.args[0]]
        assert len(inserts) == 1
        payload = inserts[0].args[-1]
        assert payload["severity"] == "critical"
        assert payload["alert_events"] == 1


@pytest.mark.asyncio
class TestSlotHealing:
    """The thesis_state_current slot's invariant is ONE active row. Two
    ingests racing (instant adoption push + tick; live push + reconcile)
    can twin it — observed live 2026-08-12, two actives 115ms apart — so
    the upsert edits the NEWEST row and flips the twins."""

    async def test_twinned_slot_is_healed_on_the_next_push(
        self, stub_memory, curator_calls, push_calls,
    ):
        newest, stale = uuid4(), uuid4()
        db = make_db()
        orig_fetch = db.fetch.side_effect

        async def _fetch(sql, *args):
            if "FROM memories" in sql:
                return [{"id": newest}, {"id": stale}]  # newest first
            return await orig_fetch(sql, *args)

        db.fetch = AsyncMock(side_effect=_fetch)

        await ingest_snapshot(
            db, make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[]),
        )

        stub_memory.edit_memory.assert_awaited_once()
        assert stub_memory.edit_memory.await_args.kwargs["memory_id"] == newest
        heal_sqls = [
            c for c in db.execute.await_args_list
            if "status = 'invalidated'" in c.args[0]
        ]
        assert len(heal_sqls) == 1
        assert heal_sqls[0].args[1] == [stale]

    async def test_single_active_row_is_left_alone(
        self, stub_memory, curator_calls, push_calls,
    ):
        only = uuid4()
        db = make_db()
        orig_fetch = db.fetch.side_effect

        async def _fetch(sql, *args):
            if "FROM memories" in sql:
                return [{"id": only}]
            return await orig_fetch(sql, *args)

        db.fetch = AsyncMock(side_effect=_fetch)

        await ingest_snapshot(
            db, make_connection_manager(), ROOM_ID,
            make_request(v=3, alert_events=[]),
        )

        assert stub_memory.edit_memory.await_args.kwargs["memory_id"] == only
        assert not any(
            "status = 'invalidated'" in c.args[0]
            for c in db.execute.await_args_list
        )
