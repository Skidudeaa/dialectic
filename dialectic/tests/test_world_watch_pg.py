"""
Real-Postgres contracts for llm/world_watch.py — the World Lens consumer
(migration 026). Mirrors tests/test_wire.py's shape: force_response is
monkeypatched (no real LLM calls), everything else — the room/scope/Field
fixtures, the upsert, the fingerprint gate — runs against real Postgres.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/021_geo_scopes.sql
    psql dialectic_test -f migrations/022_geo_scope_lineage.sql
    psql dialectic_test -f migrations/017_field_marks.sql
    psql dialectic_test -f migrations/026_world_observations.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from field_marks import compute_dedup_key
from geo_scopes import insert_scope
from llm import world_watch
from llm.orchestrator import OrchestrationResult
from models import Message, MessageType, SpeakerType
from scheduler import Scheduler, SchedulerContext
from world_signals import WorldSignal, WorldSignalSnapshot, WorldSignalStore

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-e000-{n:012x}")


AMO = _uid(0x1)
ROOM = _uid(0x11)
THREAD = _uid(0x21)

# The same small Hormuz-shaped ring the plan's own seed script draws.
HORMUZ_RING = [[55.6, 26.0], [56.2, 25.6], [57.2, 25.9], [57.0, 26.9], [55.6, 26.0]]
HORMUZ_POLY = {"type": "Polygon", "coordinates": [HORMUZ_RING]}
INSIDE = (56.4, 26.2)      # inside HORMUZ_POLY (verified against an independent point-in-polygon)
OUTSIDE = (57.5, 27.5)     # inside the live adapters' padded bbox, outside the polygon


# ---------------------------------------------------------------------------
# signal fixtures
# ---------------------------------------------------------------------------

def _signal(
    provider: str, source_id: str, lon: float, lat: float, *,
    room_id: UUID = ROOM, layer: str = "quakes",
) -> WorldSignal:
    now = datetime.now(timezone.utc)
    return WorldSignal(
        id=f"world_signal:{provider}:{source_id}", provider=provider,
        source_id=source_id, room_id=room_id, layer=layer, kind="point",
        geometry={"type": "Point", "coordinates": [lon, lat]},
        provenance={
            "provider": provider, "acquisition": f"adapter:{provider}",
            "source_id": source_id, "url": f"https://provider.test/{source_id}",
            "credit": f"{provider.upper()} test credit",
        },
        source_state="ok", freshness="current", coverage="test coverage",
        observed_at=now - timedelta(minutes=2),
        retrieved_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=30),
        label=f"Contact {source_id}", details={},
    )


def _snapshot(provider: str, *signals: WorldSignal) -> WorldSignalSnapshot:
    now = datetime.now(timezone.utc)
    return WorldSignalSnapshot(
        provider=provider,
        configured_room_ids=frozenset(s.room_id for s in signals) or frozenset({ROOM}),
        source_state="ok", freshness="current", coverage="test coverage",
        retrieved_at=now, expires_at=now + timedelta(minutes=30),
        signals=signals,
    )


# ---------------------------------------------------------------------------
# db / fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    has_table = await conn.fetchval("SELECT to_regclass('world_observations')")
    if not has_table:
        await conn.close()
        pytest.skip("migration 026 not applied to the test database")
        return
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    """One room with confirmed Hormuz-shaped geography and a member."""
    tx = db.transaction()
    await tx.start()
    now = datetime.now(timezone.utc)
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo')",
        AMO, now,
    )
    await db.execute(
        """INSERT INTO rooms (id, name, token, created_at, auto_interjection_enabled)
           VALUES ($1,$2,$3,$4,TRUE)""",
        ROOM, "World Watch Test Room", f"tok-{ROOM}", now,
    )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        ROOM, AMO, now,
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,'Main')",
        THREAD, ROOM, now,
    )
    scope_id = await insert_scope(
        db, room_id=ROOM, subject={"entity": "rooms", "id": str(ROOM)},
        kind="polygon", geometry=HORMUZ_POLY, label="Strait of Hormuz",
        authority="human_confirmed",
        provenance={"provider": "human", "acquisition": "human", "credit": "sketch"},
        confirmed_by=AMO, created_by=AMO,
    )
    yield db, scope_id
    await tx.rollback()


@pytest.fixture(autouse=True)
def isolated_signal_store(monkeypatch):
    """world_watch reads the module-level singleton; swap in a fresh store
    per test so tests never share state with the real production singleton
    or with each other."""
    store = WorldSignalStore()
    monkeypatch.setattr(world_watch, "world_signal_store", store)
    return store


async def _bind_scope_to_node(db, scope_id: UUID, *, node_id="hormuz", book_id="hormuz-graph"):
    """A human 'Mark as evidence' causal Field mark: scope -> supports -> node."""
    mark_id = uuid4()
    subjects = [
        {"entity": "geo_scopes", "id": str(scope_id)},
        {"entity": "rooms", "id": str(ROOM), "field": f"thesis_node:{book_id}:{node_id}"},
    ]
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, payload, actor_user_id,
                created_at, dedup_key)
           VALUES ($1,$2,$3,'relation','supports','explicit','human',$4,$5,$6,
                   $7,$8,$9)""",
        mark_id, ROOM, THREAD, subjects, "Hormuz supports the node",
        {"node_label": "Hormuz chokepoint"}, AMO, datetime.now(timezone.utc),
        compute_dedup_key("supports", subjects),
    )
    return mark_id


def _ctx():
    return SchedulerContext(pool=None, broadcast=AsyncMock())


def _fake_force_response(calls: list):
    """Records the call and inserts a real message row (via self.db, the
    same connection/transaction the test itself uses) so the fingerprint
    UPDATE in _maybe_interject has a row to land on — the test_wire.py
    pattern, adapted for a real-Postgres fixture instead of a mocked one."""
    async def _fake(self, *, room, thread, users, messages, memories,
                     use_provoker=False, protocol=None, reason=None):
        content = messages[-1].content if messages else ""
        calls.append({"room_id": room.id, "reason": reason, "content": content})
        message_id = uuid4()
        now = datetime.now(timezone.utc)
        seq = await self.db.fetchval(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = $1",
            thread.id,
        )
        await self.db.execute(
            """INSERT INTO messages
                   (id, thread_id, sequence, created_at, speaker_type, user_id,
                    message_type, content, metadata)
               VALUES ($1,$2,$3,$4,$5,NULL,$6,$7,$8)""",
            message_id, thread.id, seq, now,
            SpeakerType.LLM_PRIMARY.value, MessageType.TEXT.value,
            "Speaking to the contact.", {"source": reason},
        )
        # The real orchestrator writes this row (self_model.log_decision) —
        # _interjections_today / the daily cap read it, so the fake must too.
        await self.db.execute(
            """INSERT INTO llm_decisions
                   (room_id, thread_id, should_interject, reason, confidence,
                    mode, response_message_id, decided_at)
               VALUES ($1,$2,TRUE,$3,1.0,'primary',$4,$5)""",
            room.id, thread.id, reason, message_id, now,
        )
        response = Message(
            id=message_id, thread_id=thread.id, sequence=seq, created_at=now,
            speaker_type=SpeakerType.LLM_PRIMARY, user_id=None,
            message_type=MessageType.TEXT, content="Speaking to the contact.",
        )
        return OrchestrationResult(
            triggered=True, decision=None, response=response,
            routing=None, prompt_used=None,
        )
    return _fake


# ---------------------------------------------------------------------------
# job registration
# ---------------------------------------------------------------------------

def test_registers_a_300s_job_enabled_by_default():
    sched = Scheduler(SchedulerContext(pool=None))
    world_watch.register_world_watch_jobs(sched)
    assert len(sched.jobs) == 1
    job = sched.jobs[0]
    assert job.name == "world_watch"
    assert job.interval_s == 300
    assert job.enabled_env == "WORLD_WATCH_ENABLED"
    assert job.enabled() is True  # default on, no env var set


def test_env_gate_zero_disables(monkeypatch):
    monkeypatch.setenv("WORLD_WATCH_ENABLED", "0")
    sched = Scheduler(SchedulerContext(pool=None))
    world_watch.register_world_watch_jobs(sched)
    assert not sched.jobs[0].enabled()


# ---------------------------------------------------------------------------
# (1) contact inside polygon persists once, second poll bumps seen_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contact_inside_polygon_persists_and_seen_count_bumps(room, isolated_signal_store):
    db, scope_id = room
    isolated_signal_store.replace(_snapshot("usgs", _signal("usgs", "eq-1", *INSIDE)))
    ctx = _ctx()

    first = await world_watch._process_room(ctx, db, ROOM)
    assert first == {"new": 1, "seen": 0, "interjected": False}

    rows = await db.fetch("SELECT * FROM world_observations WHERE room_id = $1", ROOM)
    assert len(rows) == 1
    assert rows[0]["scope_id"] == scope_id
    assert rows[0]["provider"] == "usgs"
    assert rows[0]["seen_count"] == 1

    second = await world_watch._process_room(ctx, db, ROOM)
    assert second == {"new": 0, "seen": 1, "interjected": False}

    rows = await db.fetch("SELECT * FROM world_observations WHERE room_id = $1", ROOM)
    assert len(rows) == 1, "a loitering contact is one row, not a second"
    assert rows[0]["seen_count"] == 2


# ---------------------------------------------------------------------------
# (2) outside the polygon writes nothing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contact_outside_polygon_writes_nothing(room, isolated_signal_store):
    db, scope_id = room
    isolated_signal_store.replace(_snapshot("usgs", _signal("usgs", "eq-2", *OUTSIDE)))
    ctx = _ctx()

    detail = await world_watch._process_room(ctx, db, ROOM)
    assert detail == {"new": 0, "seen": 0, "interjected": False}
    assert await db.fetchval("SELECT COUNT(*) FROM world_observations WHERE room_id = $1", ROOM) == 0


# ---------------------------------------------------------------------------
# (3) a non-persistable provider (iss) never lands a row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_iss_provider_never_persists(room, isolated_signal_store):
    db, scope_id = room
    isolated_signal_store.replace(_snapshot("iss", _signal("iss", "sat-1", *INSIDE)))
    ctx = _ctx()

    detail = await world_watch._process_room(ctx, db, ROOM)
    assert detail == {"new": 0, "seen": 0, "interjected": False}
    assert await db.fetchval("SELECT COUNT(*) FROM world_observations WHERE room_id = $1", ROOM) == 0


# ---------------------------------------------------------------------------
# (4) a new contact in a BOUND scope interjects exactly once, fingerprinted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_contact_in_bound_scope_interjects_once_and_stamps_fingerprint(
    room, isolated_signal_store, monkeypatch,
):
    db, scope_id = room
    await _bind_scope_to_node(db, scope_id, node_id="hormuz", book_id="hormuz-graph")
    isolated_signal_store.replace(_snapshot("usgs", _signal("usgs", "eq-3", *INSIDE)))

    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))
    ctx = _ctx()

    detail = await world_watch._process_room(ctx, db, ROOM)
    assert detail["new"] == 1
    assert detail["interjected"] is True
    assert len(calls) == 1
    assert calls[0]["reason"] == world_watch.INTERJECTION_REASON
    assert "thesis node hormuz" in calls[0]["content"]  # the bound node id
    assert "Strait of Hormuz" in calls[0]["content"]    # the scope label
    ctx.broadcast.assert_awaited_once()

    stamped = await db.fetchval(
        "SELECT metadata->>'world_fingerprint' FROM messages WHERE metadata->>'source' = $1",
        world_watch.INTERJECTION_REASON,
    )
    assert stamped  # non-empty fingerprint landed on the persisted message

    # A repeat poll sees the same contact only as a seen-count bump — no new
    # signal in the scope, so no second interjection.
    repeat = await world_watch._process_room(ctx, db, ROOM)
    assert repeat["new"] == 0
    assert repeat["interjected"] is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fingerprint_alone_blocks_a_repeat_with_the_same_new_signal_set(
    room, isolated_signal_store, monkeypatch,
):
    """Direct test of gate (d), independent of the new/seen split above: the
    same {scope: [signal ids]} material must not interject twice even if it
    is handed to _maybe_interject as 'new' both times."""
    db, scope_id = room
    await _bind_scope_to_node(db, scope_id)
    signal = _signal("usgs", "eq-4", *INSIDE)
    isolated_signal_store.replace(_snapshot("usgs", signal))

    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))
    ctx = _ctx()
    scopes_by_id = {scope_id: (await world_watch.GeoScopeService(db).build(ROOM)).scopes[0]}
    signals_by_id = {signal.id: signal}
    new_by_scope = {scope_id: [signal.id]}

    first = await world_watch._maybe_interject(ctx, db, ROOM, new_by_scope, scopes_by_id, signals_by_id)
    second = await world_watch._maybe_interject(ctx, db, ROOM, new_by_scope, scopes_by_id, signals_by_id)

    assert first is True
    assert second is False
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# (5) a scope with no causal binding persists but never interjects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scope_without_binding_persists_but_never_interjects(
    room, isolated_signal_store, monkeypatch,
):
    db, scope_id = room  # deliberately not bound to any thesis node
    isolated_signal_store.replace(_snapshot("usgs", _signal("usgs", "eq-5", *INSIDE)))

    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))
    ctx = _ctx()

    detail = await world_watch._process_room(ctx, db, ROOM)
    assert detail["new"] == 1
    assert detail["interjected"] is False
    assert len(calls) == 0
    assert await db.fetchval("SELECT COUNT(*) FROM world_observations WHERE room_id = $1", ROOM) == 1


# ---------------------------------------------------------------------------
# guardrails: the toggle and the daily cap still gate a bound, new contact
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_interjection_disabled_suppresses_the_call(
    room, isolated_signal_store, monkeypatch,
):
    db, scope_id = room
    await _bind_scope_to_node(db, scope_id)
    await db.execute("UPDATE rooms SET auto_interjection_enabled = FALSE WHERE id = $1", ROOM)
    isolated_signal_store.replace(_snapshot("usgs", _signal("usgs", "eq-6", *INSIDE)))

    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))
    ctx = _ctx()

    detail = await world_watch._process_room(ctx, db, ROOM)
    assert detail["new"] == 1
    assert detail["interjected"] is False
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_daily_cap_holds(room, isolated_signal_store, monkeypatch):
    db, scope_id = room
    await _bind_scope_to_node(db, scope_id)

    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))
    ctx = _ctx()

    for i in range(world_watch.WORLD_DAILY_CAP):
        isolated_signal_store.replace(_snapshot("usgs", _signal("usgs", f"eq-cap-{i}", *INSIDE)))
        detail = await world_watch._process_room(ctx, db, ROOM)
        assert detail["interjected"] is True

    isolated_signal_store.replace(_snapshot("usgs", _signal("usgs", "eq-cap-over", *INSIDE)))
    over = await world_watch._process_room(ctx, db, ROOM)
    assert over["new"] == 1          # persistence is unaffected by the cap
    assert over["interjected"] is False
    assert len(calls) == world_watch.WORLD_DAILY_CAP


# ---------------------------------------------------------------------------
# fires: cell-days scored against the room's own 30-day baseline (migration 027)
# ---------------------------------------------------------------------------

def _fire(source_id: str, *, frp: float = 30.0, confidence: str = "h",
          acq_date: str = "2026-08-30", cell: str = "26.20,56.40",
          lon: float = INSIDE[0], lat: float = INSIDE[1]) -> WorldSignal:
    base = _signal("firms", source_id, lon, lat, layer="fires")
    return base.model_copy(update={
        "label": f"Fire · {frp:.0f} MW · {confidence} conf",
        "details": {
            "cell": cell, "acq_date": acq_date, "pixels": 1, "frp_mw": frp,
            "confidence": confidence, "satellites": ["N20"],
            "acquired": f"{acq_date} 0412Z",
        },
    })


@pytest.mark.asyncio
async def test_a_novel_hot_fire_in_a_bound_scope_interjects_with_its_verdict(
    room, isolated_signal_store, monkeypatch,
):
    db, scope_id = room
    await _bind_scope_to_node(db, scope_id)
    isolated_signal_store.replace(_snapshot("firms", _fire("d30.cellA")))
    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))

    detail = await world_watch._process_room(_ctx(), db, ROOM)
    assert detail["new"] == 1 and detail["interjected"] is True
    content = calls[0]["content"]
    assert "FRP 30.0 MW" in content
    assert "prior days in this room's 30-day window: 0" in content
    assert "thermal anomaly" in content  # the flare note rides along
    row = await db.fetchrow(
        "SELECT label, details FROM world_observations WHERE provider = 'firms'")
    assert row["details"]["novel"] is True and row["details"]["baseline_days"] == 0
    assert row["label"] == "Fire · 30 MW · h conf · NEW vs 30-day baseline"


@pytest.mark.asyncio
async def test_a_recurring_cell_persists_labelled_as_a_flare_and_never_interjects(
    room, isolated_signal_store, monkeypatch,
):
    db, scope_id = room
    await _bind_scope_to_node(db, scope_id)
    # Yesterday's row in the same cell: the room already knows this source.
    isolated_signal_store.replace(_snapshot("firms", _fire("d29.cellA", acq_date="2026-08-29")))
    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))
    await world_watch._process_room(_ctx(), db, ROOM)
    assert len(calls) == 1  # the first day is novel by construction

    isolated_signal_store.replace(_snapshot("firms", _fire("d30.cellA", frp=80.0)))
    detail = await world_watch._process_room(_ctx(), db, ROOM)
    assert detail["new"] == 1          # persisted…
    assert detail["interjected"] is False  # …but a flare is not news
    assert len(calls) == 1
    row = await db.fetchrow(
        "SELECT label, details FROM world_observations WHERE signal_id = 'world_signal:firms:d30.cellA'")
    assert row["details"]["novel"] is False and row["details"]["baseline_days"] == 1
    assert row["label"].endswith("· recurring 1d (likely flare)")


@pytest.mark.asyncio
async def test_weak_or_low_confidence_novel_fires_persist_but_do_not_wake_the_room(
    room, isolated_signal_store, monkeypatch,
):
    db, scope_id = room
    await _bind_scope_to_node(db, scope_id)
    isolated_signal_store.replace(_snapshot(
        "firms",
        _fire("d30.weak", frp=4.0, cell="26.21,56.41"),
        _fire("d30.lowc", frp=50.0, confidence="l", cell="26.22,56.42"),
    ))
    calls: list = []
    monkeypatch.setattr(world_watch.LLMOrchestrator, "force_response", _fake_force_response(calls))
    detail = await world_watch._process_room(_ctx(), db, ROOM)
    assert detail["new"] == 2
    assert detail["interjected"] is False
    assert calls == []
    assert await db.fetchval("SELECT count(*) FROM world_observations WHERE provider='firms'") == 2


def test_fire_gate_is_the_three_conditions():
    ok = {"novel": True, "frp_mw": 10.0, "confidence": "n"}
    assert world_watch.fire_counts_as_new(ok)
    assert not world_watch.fire_counts_as_new({**ok, "novel": False})
    assert not world_watch.fire_counts_as_new({**ok, "frp_mw": 9.9})
    assert not world_watch.fire_counts_as_new({**ok, "confidence": "l"})


@pytest.mark.asyncio
async def test_a_re_seen_cell_day_refreshes_frp_and_keeps_its_verdict(room, isolated_signal_store):
    db, scope_id = room
    isolated_signal_store.replace(_snapshot("firms", _fire("d30.cellB", frp=12.0, cell="26.23,56.43")))
    await world_watch._process_room(_ctx(), db, ROOM)
    # The next overpass reports the same cell hotter.
    isolated_signal_store.replace(_snapshot("firms", _fire("d30.cellB", frp=45.0, cell="26.23,56.43")))
    detail = await world_watch._process_room(_ctx(), db, ROOM)
    assert detail["new"] == 0 and detail["seen"] == 1
    row = await db.fetchrow(
        "SELECT label, details, seen_count FROM world_observations WHERE signal_id = 'world_signal:firms:d30.cellB'")
    assert row["seen_count"] == 2
    assert row["details"]["frp_mw"] == 45.0          # refreshed
    assert row["details"]["novel"] is True           # verdict survived the merge
    assert row["label"] == "Fire · 45 MW · h conf · NEW vs 30-day baseline"
