"""
Tests for llm/round_close_watch.py — the settlement sweep and the credit line.

WHY this file exists, in order of what it would cost to get wrong:

  1. THE LAW. The job may suggest a verdict and may never write one. A
     settlement that resolves itself costs the ledger its standing
     permanently, so there is a test that reads every statement the job
     issued and fails if any of them touches a commitment's resolution.
  2. THE CREDIT LINE'S HONESTY. It names a person and a number in a
     two-person ledger. A fabricated number misstates the record; a
     fabricated name credits the wrong human. Both are checked by feeding
     the validator model output that lies and proving the line is dropped.
  3. IDEMPOTENCE. The scheduler retries and the service restarts often.
     The dedup is a metadata QUERY, so the round-trip through real
     Postgres — post a card, read the ids back, watch the question vanish
     from the backlog — is the only proof that counts.
  4. Degradation. A dead tool channel or a dead provider must cost one
     question its card, never the run.

Component tests use the prediction_watch idiom: a fake pool/conn answering
by the table the job queried, externals stubbed at the module seam.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from llm import round_close_watch as w
from models import SpeakerType
from scheduler import Scheduler, SchedulerContext

ROOM_ID = uuid4()
THREAD_ID = uuid4()
AMO = uuid4()
DAN = uuid4()

NOW = datetime.now(timezone.utc)
CLOSED = NOW - timedelta(days=1)


def make_question(qid=None, *, claim="Brent closes above $90 on Aug 20?"):
    return {
        "id": qid or uuid4(),
        "room_id": ROOM_ID,
        "claim": claim,
        "resolution_criteria": "Resolves on the EIA Weekly Petroleum Status Report.",
        "deadline": CLOSED,
    }


def make_resolved(qid=None, *, resolution="correct"):
    # Settled on the close date, which is what makes the packet's
    # days_before_close read off the deadline. The scorer's boundary is
    # min(close, resolved_at) and the packet follows it.
    return {
        "id": qid or uuid4(),
        "room_id": ROOM_ID,
        "claim": "Brent closes above $90 on Aug 20?",
        "deadline": CLOSED,
        "resolution": resolution,
        "resolved_at": CLOSED,
    }


def make_history():
    """Dan at 0.85 three days out, Amo at 0.40 — the exemplar's own shape."""
    return [
        {"user_id": DAN, "confidence": 0.85, "actor": "human",
         "display_name": "Dan", "recorded_at": CLOSED - timedelta(days=3)},
        {"user_id": AMO, "confidence": 0.40, "actor": "human",
         "display_name": "Amo", "recorded_at": CLOSED - timedelta(days=3)},
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


def make_db(*, closed=(), resolved=(), posted=(), credited=(),
            history=None, members=(AMO, DAN)):
    """Mock connection covering every query either sweep makes."""
    db = AsyncMock()
    db.statements = []

    async def _fetch(sql, *args):
        if "FROM messages" in sql:
            source = args[0]
            ids = posted if source == w.SETTLEMENT_SOURCE else credited
            return [{"commitment_id": str(i)} for i in ids]
        if "FROM commitments" in sql:
            rows = list(resolved) if "resolution IN" in sql else list(closed)
            # The done-set exclusion moved INTO the SQL (it has to: filtering
            # after LIMIT starved the sweep once BACKLOG_SCAN carded-but-
            # untapped questions accumulated, and they accumulate forever
            # because THE LAW forbids this job resolving anything). A fake
            # that ignores $2 would keep these tests green against the exact
            # bug the move fixes, so it honours the parameter.
            if "= ANY($2::uuid[])" in sql:
                excluded = {str(u) for u in (args[1] if len(args) > 1 else [])}
                rows = [r for r in rows if str(r["id"]) not in excluded]
            return rows
        if "FROM commitment_confidence" in sql:
            return list(history if history is not None else make_history())
        if "FROM room_memberships" in sql:
            return [{"user_id": m} for m in members]
        return []

    async def _execute(sql, *args):
        db.statements.append(sql)

    db.fetch = AsyncMock(side_effect=_fetch)
    db.execute = AsyncMock(side_effect=_execute)
    db.fetchrow = AsyncMock(return_value=None)
    return db


@pytest.fixture
def ctx(monkeypatch):
    """A context whose room loads, whose research succeeds, and whose push
    is captured rather than sent."""
    room = SimpleNamespace(
        id=ROOM_ID, name="Hormuz Room",
        primary_provider="anthropic", fallback_provider="openai",
        primary_model="claude-sonnet-5", provoker_model="claude-haiku-4-5",
    )
    thread = SimpleNamespace(id=THREAD_ID)
    state = SimpleNamespace(
        broadcasts=[], pushes=[], gathered=[],
        finding={"verdict": "correct",
                 "rationale": "The EIA report puts the close at $91.40.",
                 "checked": [{"tool": "read_article", "ok": True}]},
        line="Dan, 0.85, Aug 17 — while Amo stood at 0.40.",
    )

    async def _load(conn, room_id):
        return room, thread, []

    async def _gather(db, room_arg, question):
        state.gathered.append(str(question["id"]))
        return state.finding

    async def _phrase(packet):
        return state.line

    async def _send(**kwargs):
        state.pushes.append(kwargs)

    async def _broadcast(room_id, message):
        state.broadcasts.append((room_id, message))

    monkeypatch.setattr(w, "_load", _load)
    monkeypatch.setattr(w, "_gather", _gather)
    monkeypatch.setattr(w, "_phrase", _phrase)
    import api.notifications.webpush as webpush
    monkeypatch.setattr(webpush, "send_web_notifications", _send)

    state.room = room
    state.make = lambda db: SchedulerContext(
        pool=FakePool(db), broadcast=_broadcast, connection_manager=None)
    return state


# ── the law: it suggests, it never settles ───────────────────────────


@pytest.mark.asyncio
async def test_settlement_never_writes_a_resolution(ctx):
    """Every statement the run issued, read back. None may settle anything."""
    db = make_db(closed=[make_question()], resolved=[make_resolved()])
    await w.round_close_watch(ctx.make(db))

    assert db.statements, "the run issued no statements at all"
    for sql in db.statements:
        lowered = " ".join(sql.lower().split())
        assert "update commitments" not in lowered
        assert "resolution" not in lowered or "insert into messages" in lowered
        assert "resolved_at" not in lowered


@pytest.mark.asyncio
async def test_settlement_card_carries_the_suggestion_and_the_source(ctx):
    question = make_question()
    db = make_db(closed=[question])
    detail = await w.round_close_watch(ctx.make(db))

    assert detail["settled"][0]["suggested"] == "correct"
    _, message = ctx.broadcasts[0]
    card = message.payload["metadata"]
    assert card["source"] == w.SETTLEMENT_SOURCE
    body = card[w.SETTLEMENT_SOURCE]
    assert body["commitment_id"] == str(question["id"])
    assert body["claim"] == question["claim"]
    assert body["source"] == question["resolution_criteria"]
    assert body["suggested_verdict"] == "correct"
    assert body["resolved"] is False
    assert body["evidence"] == [{"tool": "read_article", "ok": True}]
    assert message.payload["speaker_type"] == SpeakerType.LLM_ANNOTATOR.value
    # The named source is in the human-readable text too, not only metadata.
    assert question["resolution_criteria"] in message.payload["content"]


# ── idempotence and spend ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_question_already_settled_is_not_settled_again(ctx):
    question = make_question()
    db = make_db(closed=[question], posted=[question["id"]])
    detail = await w.round_close_watch(ctx.make(db))

    assert detail["settled"] == []
    assert ctx.gathered == [], "it researched a question it had already posted"


@pytest.mark.asyncio
async def test_the_run_cap_bounds_the_spend(ctx):
    backlog = [make_question() for _ in range(w.SETTLE_RUN_CAP + 3)]
    db = make_db(closed=backlog)
    detail = await w.round_close_watch(ctx.make(db))

    assert len(detail["settled"]) == w.SETTLE_RUN_CAP
    assert len(ctx.gathered) == w.SETTLE_RUN_CAP


@pytest.mark.asyncio
async def test_a_credited_question_is_not_credited_again(ctx):
    question = make_resolved()
    db = make_db(resolved=[question], credited=[question["id"]])
    detail = await w.round_close_watch(ctx.make(db))

    assert detail["credited"] == []


# ── degradation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_dead_question_does_not_strand_the_backlog(ctx, monkeypatch):
    first, second = make_question(), make_question()

    async def _gather(db, room, question):
        if question["id"] == first["id"]:
            raise RuntimeError("defuddle exploded")
        return ctx.finding

    monkeypatch.setattr(w, "_gather", _gather)
    db = make_db(closed=[first, second])
    detail = await w.round_close_watch(ctx.make(db))

    assert [s["id"] for s in detail["settled"]] == [str(second["id"])]
    assert {"id": str(first["id"]), "reason": "error"} in detail["skipped"]


@pytest.mark.asyncio
async def test_research_that_finds_nothing_posts_no_card(ctx, monkeypatch):
    async def _gather(db, room, question):
        return None

    monkeypatch.setattr(w, "_gather", _gather)
    question = make_question()
    db = make_db(closed=[question])
    detail = await w.round_close_watch(ctx.make(db))

    assert detail["settled"] == []
    assert {"id": str(question["id"]), "reason": "no_finding"} in detail["skipped"]
    assert ctx.broadcasts == []


@pytest.mark.asyncio
async def test_gather_degrades_when_the_tool_channel_is_gone(monkeypatch):
    """No registry means a plain call, not a crash and not a skipped question."""
    room = SimpleNamespace(
        id=ROOM_ID, primary_provider="anthropic", fallback_provider="openai",
        primary_model="claude-sonnet-5", provoker_model="claude-haiku-4-5")

    def _boom(room_arg, db):
        raise RuntimeError("registry unavailable")

    class _Router:
        def __init__(self, **kwargs):
            pass

        async def route(self, request):
            assert request.tools is None, "a text-only degrade must carry no tools"
            return SimpleNamespace(
                success=True,
                response=SimpleNamespace(
                    content='{"verdict": "unclear", "rationale": "EIA is down."}'),
            )

    monkeypatch.setattr(w, "build_registry", _boom)
    monkeypatch.setattr(w, "ModelRouter", _Router)
    finding = await w._gather(None, room, make_question())

    assert finding["verdict"] == "unclear"
    assert finding["checked"] == []


@pytest.mark.asyncio
async def test_gather_reports_the_tools_it_actually_reached(monkeypatch):
    """`checked` is the loop's own trace, failures included — evidence about
    the evidence."""
    room = SimpleNamespace(
        id=ROOM_ID, primary_provider="anthropic", fallback_provider="openai",
        primary_model="claude-sonnet-5", provoker_model="claude-haiku-4-5")
    trace = [{"tool": "get_thesis_news", "ok": True},
             {"tool": "read_article", "ok": False}]

    class _Loop:
        def __init__(self, router, registry, **kwargs):
            pass

        async def run(self, request):
            return SimpleNamespace(
                routing=SimpleNamespace(
                    success=True,
                    response=SimpleNamespace(
                        content='{"verdict":"correct","rationale":"EIA: $91.40."}')),
                tool_trace=trace,
            )

    monkeypatch.setattr(w, "build_registry", lambda room_arg, db: object())
    monkeypatch.setattr(w, "ModelRouter", lambda **kwargs: object())
    monkeypatch.setattr(w, "ToolLoop", _Loop)
    finding = await w._gather(None, room, make_question())

    assert finding["checked"] == trace


@pytest.mark.asyncio
async def test_a_provider_failure_is_a_quiet_skip(monkeypatch):
    room = SimpleNamespace(
        id=ROOM_ID, primary_provider="anthropic", fallback_provider="openai",
        primary_model="claude-sonnet-5", provoker_model="claude-haiku-4-5")

    class _Loop:
        def __init__(self, *a, **k):
            pass

        async def run(self, request):
            raise RuntimeError("anthropic is down")

    monkeypatch.setattr(w, "build_registry", lambda room_arg, db: object())
    monkeypatch.setattr(w, "ModelRouter", lambda **kwargs: object())
    monkeypatch.setattr(w, "ToolLoop", _Loop)

    assert await w._gather(None, room, make_question()) is None


# ── the push ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_settlement_pushes_only_members_without_a_live_socket(ctx):
    class _Manager:
        def is_user_connected(self, user_id, room_id):
            return user_id == AMO

    db = make_db(closed=[make_question()])
    context = SchedulerContext(
        pool=FakePool(db), broadcast=None, connection_manager=_Manager())
    detail = await w.round_close_watch(context)

    assert detail["settled"][0]["pushed"] == 1
    assert ctx.pushes[0]["recipient_user_ids"] == [str(DAN)]
    assert ctx.pushes[0]["data"]["message_id"] == detail["settled"][0]["message_id"]


@pytest.mark.asyncio
async def test_the_credit_line_is_not_pushed(ctx):
    """A settlement is a task with a tap at the end. The line is a remark."""
    db = make_db(resolved=[make_resolved()])
    detail = await w.round_close_watch(ctx.make(db))

    assert len(detail["credited"]) == 1
    assert ctx.pushes == []


# ── the fact packet ──────────────────────────────────────────────────


def test_the_packet_holds_only_what_was_recorded():
    packet = w.fact_packet(make_resolved(), make_history())

    assert packet["outcome"] == "correct"
    names = {f["name"] for f in packet["forecasters"]}
    assert names == {"Dan", "Amo"}
    dan = next(f for f in packet["forecasters"] if f["name"] == "Dan")
    assert dan["final"] == 0.85
    assert dan["revisions"] == 1
    assert dan["forecasts"][0]["days_before_close"] == 3


def test_the_house_is_a_forecaster_and_is_named_as_one():
    history = make_history() + [
        {"user_id": None, "confidence": 0.6, "actor": "house",
         "display_name": None, "recorded_at": CLOSED - timedelta(days=2)},
    ]
    packet = w.fact_packet(make_resolved(), history)

    assert "the house" in {f["name"] for f in packet["forecasters"]}


# ── the credit line's honesty ────────────────────────────────────────


GOOD_LINE = "Dan, 0.85, Aug 17 — three days before the print, while Amo stood at 0.40."


def test_a_line_built_from_the_packet_survives():
    packet = w.fact_packet(make_resolved(), make_history())
    line = f"Dan, 0.85 — while Amo stood at 0.40, {packet['forecasters'][0]['forecasts'][0]['days_before_close']} days out."

    assert w.validate_line(line, packet) is True


def test_a_fabricated_number_drops_the_line():
    packet = w.fact_packet(make_resolved(), make_history())

    assert w.validate_line(
        "Dan, 0.92 — while Amo stood at 0.40.", packet) is False


def test_a_fabricated_name_drops_the_line():
    """The worst output this system could produce: crediting the wrong human."""
    packet = w.fact_packet(make_resolved(), make_history())

    assert w.validate_line(
        "Sarah, 0.85 — while Amo stood at 0.40.", packet) is False


def test_a_paragraph_drops_the_line():
    packet = w.fact_packet(make_resolved(), make_history())

    assert w.validate_line("Dan, 0.85.\nAmo, 0.40.", packet) is False


def test_percent_renderings_of_a_packet_probability_are_allowed():
    packet = w.fact_packet(make_resolved(), make_history())

    assert w.validate_line("Dan at 85, Amo at 40.", packet) is True


@pytest.mark.asyncio
async def test_credit_line_drops_a_model_that_invents(monkeypatch):
    monkeypatch.setattr(
        w, "_phrase",
        AsyncMock(return_value="Dan, 0.99 — while Amo stood at 0.03."))

    assert await w.credit_line(make_resolved(), make_history()) is None


@pytest.mark.asyncio
async def test_credit_line_keeps_a_model_that_reads_the_packet(monkeypatch):
    monkeypatch.setattr(w, "_phrase", AsyncMock(return_value=f'"{GOOD_LINE}"'))

    assert await w.credit_line(make_resolved(), make_history()) == GOOD_LINE


@pytest.mark.asyncio
async def test_an_uncontested_question_has_no_credit_to_assign(monkeypatch):
    """The sentence's whole shape is 'against what the other one said'."""
    phrase = AsyncMock(return_value=GOOD_LINE)
    monkeypatch.setattr(w, "_phrase", phrase)
    solo = [make_history()[0]]

    assert await w.credit_line(make_resolved(), solo) is None
    phrase.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_voided_question_gets_no_line(monkeypatch):
    phrase = AsyncMock(return_value=GOOD_LINE)
    monkeypatch.setattr(w, "_phrase", phrase)

    assert await w.credit_line(
        make_resolved(resolution="voided"), make_history()) is None
    phrase.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_dead_model_costs_the_line_and_nothing_else(monkeypatch):
    monkeypatch.setattr(w, "_phrase", AsyncMock(return_value=None))

    assert await w.credit_line(make_resolved(), make_history()) is None


# ── registration ─────────────────────────────────────────────────────


def test_the_job_registers_hourly_behind_its_own_kill_switch():
    scheduler = Scheduler(SchedulerContext(pool=None))
    w.register_round_close_jobs(scheduler)
    job = [j for j in scheduler.jobs if j.name == "round_close_watch"][0]

    assert job.interval_s == 3600
    assert job.enabled_env == w.ENABLED_ENV
    assert job.func is w.round_close_watch


def test_the_kill_switch_actually_kills(monkeypatch):
    scheduler = Scheduler(SchedulerContext(pool=None))
    w.register_round_close_jobs(scheduler)
    job = [j for j in scheduler.jobs if j.name == "round_close_watch"][0]

    monkeypatch.setenv(w.ENABLED_ENV, "0")
    assert job.enabled() is False
    monkeypatch.setenv(w.ENABLED_ENV, "1")
    assert job.enabled() is True


# ── real Postgres: the dedup round trip ──────────────────────────────

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)

PG_ROOM = UUID("00000000-0000-4000-8000-00000000b401")
PG_THREAD = UUID("00000000-0000-4000-8000-00000000c401")
PG_USER = UUID("00000000-0000-4000-8000-00000000a401")


@pytest_asyncio.fixture
async def pg():
    """A room with one closed round question, rolled back afterwards."""
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dialectic_test unavailable: {exc}")
    for kind in ("jsonb", "json"):
        await conn.set_type_codec(
            kind, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) "
            "VALUES ($1, now(), 'Amo')", PG_USER)
        await conn.execute(
            "INSERT INTO rooms (id, created_at, name, token) "
            "VALUES ($1, now(), 'Settlement Room', 'settle-token')", PG_ROOM)
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) "
            "VALUES ($1, $2, now(), 'Main')", PG_THREAD, PG_ROOM)
        await conn.execute(
            """INSERT INTO commitments
               (id, room_id, thread_id, claim, resolution_criteria, category,
                created_at, deadline, status)
               VALUES ($1, $2, $3, 'Brent above $90?',
                       'Resolves on the EIA Weekly Petroleum Status Report.',
                       'round', now() - interval '10 days',
                       now() - interval '1 day', 'active')""",
            UUID("00000000-0000-4000-8000-00000000e401"), PG_ROOM, PG_THREAD)
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_pg_the_backlog_empties_once_a_card_is_posted(pg):
    """The dedup is a metadata query, so only a real round trip proves it.

    Post the card the job would post, read the ids back the way the job
    reads them, and watch the question leave the backlog. A restart between
    those two steps is the case this defends.
    """
    backlog = await w._closed_questions(pg, set(), w.SETTLE_RUN_CAP)
    assert len(backlog) == 1
    question = backlog[0]

    ctx = SimpleNamespace(broadcast=None)
    metadata = {
        "source": w.SETTLEMENT_SOURCE,
        w.SETTLEMENT_SOURCE: {"commitment_id": str(question["id"]),
                              "suggested_verdict": "correct",
                              "resolved": False},
    }
    await w._post_card(pg, ctx, PG_ROOM, PG_THREAD,
                       w.render_settlement(question, {
                           "verdict": "correct", "rationale": "EIA: $91.40.",
                           "checked": []}),
                       metadata)

    done = await w._posted_ids(pg, w.SETTLEMENT_SOURCE)
    assert str(question["id"]) in done
    assert await w._closed_questions(pg, done, w.SETTLE_RUN_CAP) == []
    # And the credit sweep's own gauge must not see the settlement card.
    assert await w._posted_ids(pg, w.CREDIT_SOURCE) == set()


@pytest.mark.asyncio
async def test_pg_the_settlement_leaves_the_question_active(pg):
    """The card is posted; the question is exactly as unsettled as before."""
    question = (await w._closed_questions(pg, set(), 1))[0]
    await w._post_card(
        pg, SimpleNamespace(broadcast=None), PG_ROOM, PG_THREAD, "card",
        {"source": w.SETTLEMENT_SOURCE,
         w.SETTLEMENT_SOURCE: {"commitment_id": str(question["id"])}})

    row = await pg.fetchrow(
        "SELECT status, resolution, resolved_at FROM commitments WHERE id = $1",
        question["id"])
    assert row["status"] == "active"
    assert row["resolution"] is None
    assert row["resolved_at"] is None


# ── the fences the 2026-08-20 review found missing ───────────────────────

def test_swapped_attributions_drop_the_line():
    """The number set and the name set are both the packet's own, and the
    line is still a lie. This is the failure a model reading the packet will
    actually produce -- not an invented stranger -- and it is the one the
    module's docstring calls the worst output this system can make."""
    packet = w.fact_packet(make_resolved(), make_history())
    names = [f["name"] for f in packet["forecasters"]]
    finals = {f["name"]: f["final"] for f in packet["forecasters"]}
    a, b = names[0], names[1]
    truthful = f"{a}, {finals[a]} — while {b} stood at {finals[b]}."
    swapped = f"{a}, {finals[b]} — while {b} stood at {finals[a]}."
    assert w.validate_line(truthful, packet) is True
    assert w.validate_line(swapped, packet) is False


def test_the_wrong_outcome_drops_the_line():
    resolved = make_resolved()
    packet = w.fact_packet(resolved, make_history())
    other = "incorrect" if packet["outcome"] == "correct" else "correct"
    name = packet["forecasters"][0]["name"]
    final = packet["forecasters"][0]["final"]
    assert w.validate_line(
        f"{name}, {final} — and it came in {other}.", packet) is False
    assert w.validate_line(
        f"{name}, {final} — and it came in {packet['outcome']}.", packet) is True


def test_ordinary_capitalised_english_survives():
    """Before the stopword set these were dropped whenever the packet did not
    happen to contain the word -- which is most packets. The symptom is
    silence, so nothing would ever have reported it."""
    packet = w.fact_packet(make_resolved(), make_history())
    name = packet["forecasters"][0]["name"]
    final = packet["forecasters"][0]["final"]
    for opener in ("The", "It", "Both", "After", "By"):
        assert w.validate_line(
            f"{opener} call was {name}'s, {final}.", packet) is True, opener
    # And a real invented name in that same position is still refused.
    assert w.validate_line(f"Sarah called it at {final}.", packet) is False


@pytest.mark.asyncio
async def test_one_human_and_the_house_is_not_two_forecasters(monkeypatch):
    """`fact_packet` counts the house among the forecasters, so a gate on
    `len(forecasters) >= 2` was satisfied by ONE person plus the machine --
    and the line would then post that person's number as an ordinary message
    while `api/rounds._round_state` was still sealing it from the other
    human. The credit line would have walked around the blindness rule
    through the message lane."""
    history = [
        {"user_id": AMO, "display_name": "Amo", "confidence": 0.85,
         "recorded_at": datetime(2026, 8, 17, tzinfo=timezone.utc),
         "actor": "human"},
        {"user_id": None, "display_name": None, "confidence": 0.60,
         "recorded_at": datetime(2026, 8, 18, tzinfo=timezone.utc),
         "actor": "house"},
    ]
    packet = w.fact_packet(make_resolved(), history)
    assert len(packet["forecasters"]) == 2, "the house IS a forecaster here"

    # `_phrase` must never be AWAITED, not merely "the result is None".
    # Reverting the gate to `len(forecasters) < 2` killed no test until this
    # line existed: without a provider `_phrase` returns None on its own, so
    # the assertion below passed while the gate was wide open. A mutation
    # that kills nothing is a coverage hole, not a pass.
    phrase = AsyncMock(return_value=GOOD_LINE)
    monkeypatch.setattr(w, "_phrase", phrase)
    assert await w.credit_line(make_resolved(), history) is None
    phrase.assert_not_awaited()


@pytest.mark.asyncio
async def test_pg_a_full_backlog_of_carded_questions_does_not_starve_the_sweep(pg):
    """THE LAW forbids this job resolving anything, so a carded-but-untapped
    question stays active with a past deadline FOREVER. Filtering the done
    set after `LIMIT BACKLOG_SCAN` therefore let those rows keep their places
    in the window until nothing live could get in -- and the symptom is an
    empty detail identical to "nothing closed this hour"."""
    carded = []
    for i in range(w.BACKLOG_SCAN):
        qid = uuid4()
        await pg.execute(
            """INSERT INTO commitments
               (id, room_id, thread_id, claim, resolution_criteria, category,
                created_at, deadline, status)
               VALUES ($1, $2, $3, $4, 'src', 'round',
                       now() - interval '40 days',
                       now() - interval '30 days', 'active')""",
            qid, PG_ROOM, PG_THREAD, f"Old carded question {i}")
        carded.append(str(qid))

    # The one fresh closing question is the NEWEST deadline, so `deadline ASC`
    # puts it dead last -- exactly where the old scan could never reach it.
    fresh = await w._closed_questions(pg, set(carded), w.SETTLE_RUN_CAP)
    assert [str(r["id"]) for r in fresh] == [
        "00000000-0000-4000-8000-00000000e401"
    ], "the sweep starved: 50 carded questions crowded out the live one"
