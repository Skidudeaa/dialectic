"""
Real-Postgres contract for the llm_decisions JSONB double-encode fix.

WHY real Postgres: `jsonb_typeof` is the only instrument that can tell
"a JSON array" from "a string that happens to contain JSON text" — asyncpg
hands both back as Python values that print identically in a debugger (a
`list` vs a `str` that LOOKS like a list-of-dicts). Only the server-side
type oracle proves which one actually landed. A mocked `db.fetchrow` cannot
fail this test even with the bug present, because a fake connection has no
JSONB codec to double-encode through in the first place.

THE BUG (fixed alongside this test, llm/self_model.py log_decision): both
columns were `json.dumps(...)`-ed by hand before being handed to asyncpg,
whose pool codec ALSO serializes a dict/list on its own. The result on disk
was a JSON string holding JSON text. Confirmed against the live DB before
the fix: `jsonb_typeof(tool_calls)` / `jsonb_typeof(speaker_balance)` read
'string' for every one of ~192 existing rows, where a correct row reads
'array' / 'object'. Those rows are production data and are NOT migrated by
this change or this test — parse_decision_jsonb is the read-side tolerance
for them, proven here against a row shaped exactly like theirs.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from llm.heuristics import InterjectionDecision
from llm.self_model import SelfModel, parse_decision_jsonb

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM = _uid(0x5EC0DE)
THREAD = _uid(0x5EC0DF)
BASE = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    # Mirrors api/main.py's pool codec registration exactly — a bare
    # connection has none, and that absence is precisely what makes a
    # mocked test blind to this bug (see module docstring).
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    tx = db.transaction()
    await tx.start()
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        ROOM, BASE, uuid4().hex, "JSONB round-trip (test)",
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,$4)",
        THREAD, ROOM, BASE, "Main",
    )
    yield db
    await tx.rollback()


def _decision() -> InterjectionDecision:
    return InterjectionDecision(
        should_interject=True,
        reason="balance_redirect",
        confidence=0.55,
        use_provoker=False,
        considered_reasons=["speaker_balance"],
    )


async def _response_message(db) -> UUID:
    response_id = uuid4()
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
                                 speaker_type, message_type, content)
           VALUES ($1,$2,1,$3,'llm_primary','text','...')""",
        response_id, THREAD, BASE,
    )
    return response_id


# ── the write side ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_new_decision_stores_real_json_types_not_strings(room):
    """The exact production call, with production-shaped values for both
    previously-double-encoded columns."""
    db = room
    response_id = await _response_message(db)

    decision_id = await SelfModel(db).log_decision(
        room_id=ROOM,
        thread_id=THREAD,
        triggered_by_message_id=None,
        decision=_decision(),
        speaker_balance={"amo": 3, "dan": 1},
        message_count=12,
        response_message_id=response_id,
        mode="primary",
        tool_calls=[{"name": "get_live_quotes", "ok": True, "latency_ms": 120}],
    )
    assert decision_id is not None

    row = await db.fetchrow(
        """SELECT jsonb_typeof(speaker_balance) AS balance_type,
                  jsonb_typeof(tool_calls) AS tool_calls_type,
                  speaker_balance, tool_calls
             FROM llm_decisions WHERE id = $1""",
        decision_id,
    )
    # 'string' is exactly what the bug produced. Only 'object'/'array' say
    # the fix landed.
    assert row["balance_type"] == "object", (
        f"speaker_balance stored as jsonb_typeof={row['balance_type']!r}, "
        "expected 'object' — the double-encode bug is back"
    )
    assert row["tool_calls_type"] == "array", (
        f"tool_calls stored as jsonb_typeof={row['tool_calls_type']!r}, "
        "expected 'array' — the double-encode bug is back"
    )
    # And the values round-trip as the real structures, not their repr.
    assert row["speaker_balance"] == {"amo": 3, "dan": 1}
    assert row["tool_calls"] == [{"name": "get_live_quotes", "ok": True, "latency_ms": 120}]


@pytest.mark.asyncio
async def test_falsy_speaker_balance_and_tool_calls_store_null_not_empty(room):
    """`{}`/`[]` read as "measured, and empty"; NULL correctly reads as "not
    measured". log_decision's `or None` must keep choosing NULL here."""
    db = room
    response_id = await _response_message(db)

    decision_id = await SelfModel(db).log_decision(
        room_id=ROOM,
        thread_id=THREAD,
        triggered_by_message_id=None,
        decision=_decision(),
        speaker_balance={},
        message_count=1,
        response_message_id=response_id,
        mode="primary",
        tool_calls=[],
    )
    row = await db.fetchrow(
        "SELECT speaker_balance, tool_calls FROM llm_decisions WHERE id = $1",
        decision_id,
    )
    assert row["speaker_balance"] is None
    assert row["tool_calls"] is None


# ── the read side (parse_decision_jsonb) ────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_decision_jsonb_passes_a_modern_row_through_unchanged(room):
    """A row written by the fixed path round-trips as a real dict, and the
    tolerant parser must not corrupt what is already correct."""
    db = room
    response_id = await _response_message(db)
    await SelfModel(db).log_decision(
        room_id=ROOM, thread_id=THREAD, triggered_by_message_id=None,
        decision=_decision(), speaker_balance={"amo": 2, "dan": 5},
        response_message_id=response_id, mode="primary",
    )
    row = await db.fetchrow(
        "SELECT speaker_balance FROM llm_decisions WHERE response_message_id = $1",
        response_id,
    )
    assert parse_decision_jsonb(row["speaker_balance"]) == {"amo": 2, "dan": 5}


@pytest.mark.asyncio
async def test_parse_decision_jsonb_decodes_a_legacy_double_encoded_row(room):
    """Simulates exactly the ~192 rows already on disk: a JSONB column
    holding a JSON STRING of JSON text, because the pre-fix code called
    json.dumps() before handing the value to the codec that dumps again.

    Built by inserting through raw SQL rather than through log_decision —
    log_decision no longer produces this shape, which is the point; this
    row has to be constructed the way the bug used to, by hand.
    """
    db = room
    response_id = await _response_message(db)
    legacy_shape = json.dumps({"amo": 9, "dan": 0})  # the double-encode
    await db.execute(
        """INSERT INTO llm_decisions
           (room_id, thread_id, response_message_id, should_interject,
            reason, confidence, use_provoker, considered_reasons,
            speaker_balance, mode)
           VALUES ($1,$2,$3,true,'balance_redirect',0.55,false,'{}',$4,'primary')""",
        ROOM, THREAD, response_id, legacy_shape,
    )
    row = await db.fetchrow(
        "SELECT jsonb_typeof(speaker_balance) AS t, speaker_balance "
        "FROM llm_decisions WHERE response_message_id = $1",
        response_id,
    )
    # Confirms the fixture actually reproduces the legacy shape before
    # trusting the assertion below.
    assert row["t"] == "string"
    assert isinstance(row["speaker_balance"], str)

    assert parse_decision_jsonb(row["speaker_balance"]) == {"amo": 9, "dan": 0}


def test_parse_decision_jsonb_passes_none_through():
    assert parse_decision_jsonb(None) is None


def test_parse_decision_jsonb_passes_non_json_text_through_unchanged():
    """Degrade, never raise — a provenance/debug field is not worth a 500."""
    assert parse_decision_jsonb("not json at all") == "not json at all"
