"""
Real-Postgres contract: the streaming path records itself.

WHY this file exists: `stream_response` — the `@Claude` path, and the client's
`summon_llm` control — never touched the self-model. Confirmed two ways before
the fix: no reference to `log_decision` anywhere in the method, and across the
first 149 rows of the live `llm_decisions` table not one `explicit_mention`.
Every row came from `on_message`'s heuristic rungs or `force_response`'s
wire/sweep.

So the participant's record of itself contained only the occasions it chose to
speak unprompted, and none of the ones a human asked for — which is the
commonest interaction in the room. Participation counts, the effectiveness
average and the identity distillation all drew on that biased sample.

WHY real Postgres rather than a mocked `db`: the thing that broke here is a
CHAIN — persist the message, log the decision, upsert the reducer, hand back an
id the caller gates on. A mocked connection returns whatever it is told to and
would pass with the chain still severed (see the sibling failure in
`test_self_model_reducer_pg.py`, where a swallowed parse error made
`log_decision` return None and silently skipped every measurement). Only a real
server shows the row.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from llm.orchestrator import LLMOrchestrator
from llm.prompts import AssembledPrompt
from models import Message, MessageType, Room, SpeakerType, Thread

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)

ROOM = UUID("00000000-0000-4000-8000-0000000057a1")
THREAD = UUID("00000000-0000-4000-8000-0000000057a2")
HUMAN_MSG = UUID("00000000-0000-4000-8000-0000000057a3")
BASE = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _json_encoder(value):
    """The SAME encoder the production pool installs (api/main.py lifespan).

    Not a convenience: `_persist_response` logs an event whose JSONB payload
    carries raw UUID and datetime objects, so a bare `json.dumps` codec raises
    DataError on the first write and the test fails for a reason production
    never has. The lifespan defines this inline, so it cannot be imported —
    if that one changes, change this one.
    """
    def default(obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    return json.dumps(value, default=default)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=_json_encoder, decoder=json.loads, schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    """A room, a thread and one human message — rolled back after the test."""
    tx = db.transaction()
    await tx.start()
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        ROOM, BASE, uuid4().hex, "Streaming decision log (test)",
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
        THREAD, ROOM, BASE, "Main",
    )
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
                                 speaker_type, message_type, content)
           VALUES ($1,$2,1,$3,'human','text','@llm what does this do to the thesis?')""",
        HUMAN_MSG, THREAD, BASE,
    )
    yield db
    await tx.rollback()


def _fake_router(text="Two things move here."):
    async def stream(_request):
        yield ("attempt", {"model": "claude-sonnet-5"})
        for chunk in text.split(" "):
            yield ("token", {"token": chunk + " "})
    return SimpleNamespace(stream=stream)


def _orchestrator(db):
    """Everything scripted except the code under test and the database.

    `_tool_registry_for` is stubbed to None so no test can reach tradingDesk
    and the plain `router.stream` branch runs — the tool branch converges on
    the same persist + log tail, which is what this file is about. Stubbing the
    METHOD rather than `build_registry`: the method treats a None registry as a
    programming error (`registry.schemas()`), and production's build_registry
    never returns None, so faking it that way tests a state that cannot occur.
    """
    orch = LLMOrchestrator(db)
    orch._tool_registry_for = MagicMock(return_value=None)
    orch._get_cross_session_context = AsyncMock(return_value=None)
    orch._get_identity_context = AsyncMock(return_value=(None, None))
    orch._get_home_activity_context = AsyncMock(return_value=None)
    orch._load_message_images = AsyncMock(return_value={})
    orch.prompt_builder.build = MagicMock(return_value=AssembledPrompt("system", []))
    orch._get_router = MagicMock(return_value=_fake_router())
    orch._schedule_self_memory_extraction = MagicMock()
    # Spied, not stubbed out: whether this fires is the SECOND half of the
    # defect — log_decision returning None silently skipped it for a week.
    orch._schedule_effectiveness_measurement = MagicMock()
    return orch


async def _room_and_thread(db):
    room_row = await db.fetchrow("SELECT * FROM rooms WHERE id = $1", ROOM)
    thread_row = await db.fetchrow("SELECT * FROM threads WHERE id = $1", THREAD)
    return Room(**dict(room_row)), Thread(**dict(thread_row))


def _human_message():
    return Message(
        id=HUMAN_MSG,
        thread_id=THREAD,
        sequence=1,
        created_at=BASE,
        speaker_type=SpeakerType.HUMAN,
        user_id=None,
        message_type=MessageType.TEXT,
        content="@llm what does this do to the thesis?",
    )


async def _stream(orch, room_obj, thread_obj, **kwargs):
    return [
        event
        async for event in orch.stream_response(
            room=room_obj, thread=thread_obj, users=[],
            messages=[_human_message()], memories=[], **kwargs
        )
    ]


@pytest.mark.asyncio
async def test_an_at_mention_lands_a_decision_row(room):
    """The regression this file is named for: a streamed answer is recorded."""
    db = room
    orch = _orchestrator(db)
    room_obj, thread_obj = await _room_and_thread(db)

    events = await _stream(orch, room_obj, thread_obj)
    assert [e[0] for e in events][-1] == "done", events[-1]

    row = await db.fetchrow(
        "SELECT * FROM llm_decisions WHERE room_id = $1 ORDER BY id DESC LIMIT 1", ROOM
    )
    assert row is not None, "the streaming path logged no decision"
    assert row["reason"] == "explicit_mention"
    assert row["should_interject"] is True
    assert row["mode"] == "primary"
    assert row["confidence"] == pytest.approx(1.0)
    # It must point at the human turn that summoned it, not at nothing.
    assert row["triggered_by_message_id"] == HUMAN_MSG
    # And at the answer it produced, which is what effectiveness is measured on.
    assert row["response_message_id"] is not None

    persisted = await db.fetchrow(
        "SELECT id, speaker_type FROM messages WHERE id = $1", row["response_message_id"]
    )
    assert persisted is not None, "response_message_id points at no row"
    assert persisted["speaker_type"] == SpeakerType.LLM_PRIMARY.value


@pytest.mark.asyncio
async def test_the_reducer_advances_on_a_streamed_turn(room):
    """The decision row is only half of it — the self-model reads this table."""
    db = room
    orch = _orchestrator(db)
    room_obj, thread_obj = await _room_and_thread(db)

    await _stream(orch, room_obj, thread_obj)

    state = await db.fetchrow(
        "SELECT * FROM llm_participation_state WHERE room_id = $1", ROOM
    )
    assert state is not None, "no participation state written for a streamed turn"
    assert state["total_messages_sent"] == 1
    assert state["primary_count"] == 1
    assert state["last_mode"] == "primary"


@pytest.mark.asyncio
async def test_effectiveness_measurement_is_scheduled(room):
    """The gate that was silently shut: `if decision_id:`.

    A reducer failure makes log_decision return None, and then this never runs
    — which is exactly how 14 speaks on 2026-08-16 produced 0 measurements.
    """
    db = room
    orch = _orchestrator(db)
    room_obj, thread_obj = await _room_and_thread(db)

    await _stream(orch, room_obj, thread_obj)

    orch._schedule_effectiveness_measurement.assert_called_once()
    kwargs = orch._schedule_effectiveness_measurement.call_args.kwargs
    row = await db.fetchrow(
        "SELECT id, response_message_id FROM llm_decisions WHERE room_id = $1"
        " ORDER BY id DESC LIMIT 1", ROOM
    )
    # The id handed to the measurement must be the row that was just written,
    # not a stale or invented one.
    assert kwargs["decision_id"] == row["id"]
    assert kwargs["llm_message_id"] == row["response_message_id"]
    assert kwargs["room_id"] == ROOM


@pytest.mark.asyncio
async def test_summon_is_recorded_apart_from_a_mention(room):
    """Two different human actions must stay countable as two things."""
    db = room
    orch = _orchestrator(db)
    room_obj, thread_obj = await _room_and_thread(db)

    await _stream(orch, room_obj, thread_obj, reason="explicit_summon")

    row = await db.fetchrow(
        "SELECT reason FROM llm_decisions WHERE room_id = $1 ORDER BY id DESC LIMIT 1",
        ROOM,
    )
    assert row["reason"] == "explicit_summon"


@pytest.mark.asyncio
async def test_provoker_streams_are_logged_as_provoker(room):
    """`mode` drives primary_count/provoker_count — it cannot be hardcoded."""
    db = room
    orch = _orchestrator(db)
    room_obj, thread_obj = await _room_and_thread(db)

    await _stream(orch, room_obj, thread_obj, use_provoker=True)

    row = await db.fetchrow(
        "SELECT mode, use_provoker FROM llm_decisions WHERE room_id = $1"
        " ORDER BY id DESC LIMIT 1", ROOM,
    )
    assert row["mode"] == "provoker"
    assert row["use_provoker"] is True

    state = await db.fetchrow(
        "SELECT primary_count, provoker_count FROM llm_participation_state"
        " WHERE room_id = $1", ROOM,
    )
    assert state["provoker_count"] == 1
    assert state["primary_count"] == 0
