"""The house on the board — the participant's own forecast on a round question.

What can only break here: the strict parse (a number nobody committed to must
never reach the scoreboard), the actor='house' / user_id NULL shape of the row
it writes, per-question isolation, and the default-off gate.

The row shape is asserted against real Postgres and not a mocked connection on
purpose: "this row is the machine's, not a person's" is the invariant the
round's blindness rule rests on, and only reading the row back proves it.
Skipped cleanly when dialectic_test is absent.

The tool loop itself is scripted — `tests/test_tool_loop.py` owns its
behaviour, and no test here may reach a provider.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

import llm.house_forecast as hf
from llm.house_forecast import house_forecast, parse_house_block
from llm.tool_loop import ToolLoopResult
from stakes.house import split_by_actor

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)

ROOM = UUID("00000000-0000-4000-8000-00000000b401")
THREAD = UUID("00000000-0000-4000-8000-00000000c401")
CARD = UUID("00000000-0000-4000-8000-00000000d401")
TOKEN = "house-forecast-test-token"

GOOD = (
    "PROBABILITY: 0.72\n"
    "BECAUSE: The desk's own snapshot is four days stale and the two nodes it "
    "prices highest have both moved to approaching since.\n"
    "WATCHING: The next EIA Weekly Petroleum Status Report."
)


# ── the scripted loop ────────────────────────────────────────────────


class ScriptedLoop:
    """ToolLoop stand-in. Each construction shares one script; each `run`
    takes the next entry — a string to answer with, or an exception to raise."""

    script: list = []
    instances: list = []
    requests: list = []

    def __init__(self, router, registry, max_iterations, loop_budget_s):
        self.max_iterations = max_iterations
        self.loop_budget_s = loop_budget_s
        ScriptedLoop.instances.append(self)

    async def run(self, request):
        ScriptedLoop.requests.append(request)
        item = ScriptedLoop.script.pop(0) if ScriptedLoop.script else GOOD
        if isinstance(item, BaseException):
            raise item
        return ToolLoopResult(
            routing=SimpleNamespace(response=SimpleNamespace(content=item)),
            tool_trace=[{"name": "get_thesis_state", "ok": True}],
            iterations=3,
            degraded=False,
        )


@pytest.fixture
def scripted(monkeypatch):
    """Every collaborator but the code under test, scripted."""
    registry_calls: list = []
    ScriptedLoop.script = []
    ScriptedLoop.instances = []
    ScriptedLoop.requests = []
    monkeypatch.setenv(hf.ENABLED_ENV, "1")
    monkeypatch.setattr(hf, "ToolLoop", ScriptedLoop)
    monkeypatch.setattr(hf, "ModelRouter", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        hf, "build_registry",
        lambda room, db: registry_calls.append(room) or SimpleNamespace(),
    )
    return SimpleNamespace(registry_calls=registry_calls, loop=ScriptedLoop)


# ── real Postgres ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dialectic_test unavailable: {exc}")
    # The app's pool registers these codecs (api/main.py _init_connection); a
    # bare connection does not, and the house's event INSERT binds a dict.
    for kind in ("jsonb", "json"):
        await conn.set_type_codec(
            kind, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO rooms (id, created_at, name, token) "
            "VALUES ($1, now(), 'Japan Rate Shock', $2)", ROOM, TOKEN)
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) "
            "VALUES ($1, $2, now(), 'Main')", THREAD, ROOM)
        await conn.execute(
            """INSERT INTO messages (id, thread_id, sequence, created_at,
                   speaker_type, message_type, content)
               VALUES ($1, $2, 1, now(), 'llm_annotator', 'text',
                       'The Sunday Round')""",
            CARD, THREAD)
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


async def _question(db, claim: str = "Does the BOJ raise at or before Dec 19?") -> dict:
    qid = uuid4()
    await db.execute(
        """INSERT INTO commitments (id, room_id, thread_id, source_message_id,
               claim, resolution_criteria, category, created_at, deadline, status)
           VALUES ($1, $2, $3, $4, $5, 'Resolves on the BOJ policy statement.',
                   'round', now(), $6, 'active')""",
        qid, ROOM, THREAD, CARD, claim,
        datetime.now(timezone.utc) + timedelta(days=30),
    )
    return {
        "question": claim,
        "source": "Bank of Japan policy statement",
        "closes": (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat(),
        "base_rate": "2 of the last 9 meetings",
        "commitment_id": str(qid),
        "binned": False,
    }


async def _history(db, commitment_id):
    return await db.fetch(
        "SELECT * FROM commitment_confidence WHERE commitment_id = $1 "
        "ORDER BY recorded_at", UUID(commitment_id),
    )


def _room_record():
    """What `question_round` actually carries: three columns, not a Room."""
    return {"id": ROOM, "name": "Japan Rate Shock", "trading_config": None}


# ── the parse ────────────────────────────────────────────────────────


class TestParse:
    def test_the_shape_parses(self):
        parsed = parse_house_block(GOOD)
        assert parsed["probability"] == 0.72
        assert parsed["because"].startswith("The desk's own snapshot")
        assert parsed["watching"] == "The next EIA Weekly Petroleum Status Report."

    def test_markdown_emphasis_is_not_a_different_answer(self):
        parsed = parse_house_block(
            "**PROBABILITY:** **0.41**\n**BECAUSE:** Nothing has moved.")
        assert parsed["probability"] == 0.41
        assert parsed["watching"] is None

    def test_a_percentage_is_not_a_committed_number(self):
        assert parse_house_block("PROBABILITY: 72%\nBECAUSE: Because.") is None

    def test_prose_around_the_number_is_refused(self):
        assert parse_house_block(
            "PROBABILITY: roughly 0.7\nBECAUSE: Because.") is None

    def test_a_probability_outside_zero_to_one_is_refused(self):
        assert parse_house_block("PROBABILITY: 1.4\nBECAUSE: Because.") is None

    def test_a_number_with_no_reason_is_refused(self):
        assert parse_house_block("PROBABILITY: 0.6") is None

    def test_the_first_number_is_the_committed_one(self):
        parsed = parse_house_block(
            "PROBABILITY: 0.30\nBECAUSE: The base rate holds.\n"
            "PROBABILITY: see above")
        assert parsed["probability"] == 0.30

    def test_an_answer_in_prose_records_nothing(self):
        assert parse_house_block("I'd put it at roughly 70 percent.") is None


# ── the row ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTheHouseRow:
    async def test_a_well_formed_block_lands_exactly_one_house_row(self, db, scripted):
        question = await _question(db)
        ScriptedLoop.script = [GOOD]

        landed = await house_forecast(db, _room_record(), [question])

        rows = await _history(db, question["commitment_id"])
        assert len(rows) == 1
        assert rows[0]["actor"] == "house"
        assert rows[0]["user_id"] is None
        assert rows[0]["confidence"] == pytest.approx(0.72)
        assert rows[0]["reasoning"].startswith("The desk's own snapshot")
        # The predicate every partitioning reader uses must agree: this row is
        # NOT a person's, or the blindness rule unseals on the machine's turn.
        humans, house = split_by_actor(rows)
        assert humans == [] and len(house) == 1
        assert landed[0]["watching"] == "The next EIA Weekly Petroleum Status Report."
        assert landed[0]["tools"] == ["get_thesis_state"]

    async def test_the_confidence_event_is_written_beside_it(self, db, scripted):
        question = await _question(db)
        ScriptedLoop.script = [GOOD]

        await house_forecast(db, _room_record(), [question])

        payload = await db.fetchval(
            """SELECT payload FROM events
               WHERE event_type = 'commitment_confidence_updated'
                 AND room_id = $1""", ROOM)
        assert payload["actor"] == "house"
        assert payload["confidence"] == pytest.approx(0.72)
        assert payload["commitment_id"] == question["commitment_id"]

    async def test_a_malformed_block_records_nothing(self, db, scripted):
        question = await _question(db)
        ScriptedLoop.script = ["Honestly it's a coin flip, maybe 70%?"]

        landed = await house_forecast(db, _room_record(), [question])

        assert landed == []
        assert await _history(db, question["commitment_id"]) == []

    async def test_one_dying_question_does_not_stop_the_others(self, db, scripted):
        first = await _question(db, "Does Brent close above $95 before Oct 31?")
        second = await _question(db, "Does the BOJ raise at or before Dec 19?")
        third = await _question(db, "Does Evergrande file before Nov 30?")
        ScriptedLoop.script = [GOOD, RuntimeError("the provider chain is down"), GOOD]

        landed = await house_forecast(db, _room_record(), [first, second, third])

        assert len(landed) == 2
        assert len(await _history(db, first["commitment_id"])) == 1
        assert await _history(db, second["commitment_id"]) == []
        assert len(await _history(db, third["commitment_id"])) == 1

    async def test_a_binned_question_is_not_forecast(self, db, scripted):
        question = await _question(db)
        question["binned"] = True

        assert await house_forecast(db, _room_record(), [question]) == []
        assert ScriptedLoop.instances == []
        assert await _history(db, question["commitment_id"]) == []

    async def test_the_gate_off_means_no_calls_at_all(self, db, scripted, monkeypatch):
        monkeypatch.delenv(hf.ENABLED_ENV, raising=False)
        question = await _question(db)
        ScriptedLoop.script = [GOOD]

        landed = await house_forecast(db, _room_record(), [question])

        assert landed == []
        # Not merely "no row": the registry was never built and the loop was
        # never constructed, so the gate costs a round nothing when it is off.
        assert scripted.registry_calls == []
        assert ScriptedLoop.instances == []
        assert await _history(db, question["commitment_id"]) == []

    async def test_the_registry_gets_the_full_room_not_the_round_s_record(
        self, db, scripted,
    ):
        """`build_registry` closes over `room.linked_book_id`; the round
        carries three columns. The loader is what makes the call site safe."""
        question = await _question(db)
        ScriptedLoop.script = [GOOD]

        await house_forecast(db, _room_record(), [question])

        assert len(scripted.registry_calls) == 1
        loaded = scripted.registry_calls[0]
        assert loaded.id == ROOM
        assert loaded.primary_model  # a Room, not a Record
        assert ScriptedLoop.instances[0].max_iterations == hf.MAX_ITERATIONS


@pytest.mark.asyncio
class TestTheRealConstructionRuns:
    """The one test that lets `build_registry`, `ModelRouter` and `ToolLoop`
    be themselves.

    Every other test here scripts all three, and the block that builds them
    is wrapped in a bare `except Exception: return []`. That combination is
    this codebase's signature silent failure: one wrong keyword argument, or
    a signature that drifts under us, and the house simply never forecasts
    while the suite stays green and the handoff reads as shipped. The swallow
    is exactly what makes reading the code worthless here -- only running it
    proves the call is right.

    Only the TRANSPORT is stubbed: `ModelRouter.route` never reaches a
    provider, and nothing else is touched.
    """

    async def test_the_loop_is_built_for_real_and_the_row_lands(
        self, db, monkeypatch,
    ):
        from llm.providers import LLMResponse, ProviderName
        from llm.router import ModelRouter, RoutingResult

        monkeypatch.setenv(hf.ENABLED_ENV, "1")
        question = await _question(db)

        async def _route(self, request):
            # The loop asks for tools on the first pass; answering with plain
            # text ends it in one iteration without a provider call.
            return RoutingResult(
                response=LLMResponse(
                    content=("PROBABILITY: 0.72\n"
                             "BECAUSE: JGB 10y already near 2.95%.\n"
                             "WATCHING: the next BOJ statement."),
                    model="claude-sonnet-5", input_tokens=1, output_tokens=1,
                    stop_reason="end_turn", provider=ProviderName.ANTHROPIC,
                ),
                success=True, attempts=[], prompt_hash="x",
            )
        monkeypatch.setattr(ModelRouter, "route", _route)

        landed = await house_forecast(db, _room_record(), [question])
        assert len(landed) == 1, (
            "the real construction block returned nothing -- its bare except "
            "swallowed something, which is the failure this test exists for"
        )
        rows = await _history(db, question["commitment_id"])
        _, house = split_by_actor(rows)
        assert len(house) == 1
        assert house[0]["confidence"] == 0.72
        assert house[0]["user_id"] is None
        # WATCHING has a consumer: it rides the same text column the card
        # renders, rather than being parsed and dropped.
        assert "Watching: the next BOJ statement." in house[0]["reasoning"]

    async def test_a_broken_constructor_is_reported_not_swallowed_silently(
        self, db, monkeypatch, caplog,
    ):
        """The swallow is deliberate -- a room whose columns are not what we
        expect must cost the round a house forecast, never the round. But it
        has to be LOUD, or the difference between 'sat this one out' and
        'has been broken for six weeks' is unobservable."""
        import logging

        monkeypatch.setenv(hf.ENABLED_ENV, "1")
        question = await _question(db)

        def _boom(*a, **kw):
            raise TypeError("build_registry() got an unexpected keyword")
        monkeypatch.setattr(hf, "build_registry", _boom)

        with caplog.at_level(logging.ERROR):
            assert await house_forecast(db, _room_record(), [question]) == []
        assert any("house forecast" in r.message.lower() for r in caplog.records)
        assert await _history(db, question["commitment_id"]) == []
