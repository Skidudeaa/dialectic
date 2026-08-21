"""The Sunday Round's forecast door, against real Postgres.

The blindness rule is the reason this file is a PostgreSQL test and not a
component test. "Neither of you sees the other's number until you have both
committed" is a claim about what leaves the server. A UI test cannot tell a
number that was withheld from one that was rendered `display:none` — only
reading the response body can, and only a real query can prove the projection
partitions the history by user correctly.

Setup (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

import api.rounds as rounds_mod
from api.auth.dependencies import AuthenticatedUser
from api.rounds import ForecastRequest, _round_state, bin_question, record_forecast

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)

AMO = UUID("00000000-0000-4000-8000-00000000a301")
DAN = UUID("00000000-0000-4000-8000-00000000a302")
ROOM = UUID("00000000-0000-4000-8000-00000000b301")
THREAD = UUID("00000000-0000-4000-8000-00000000c301")
CARD = UUID("00000000-0000-4000-8000-00000000d301")
TOKEN = "round-test-token"


class _Borrowed:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return None


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Borrowed(self.conn)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dialectic_test unavailable: {exc}")
    # The app's pool registers these codecs (api/main.py _init_connection); a
    # bare connection does not, and every event INSERT binds a dict.
    for kind in ("jsonb", "json"):
        await conn.set_type_codec(
            kind, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES "
            "($1, now(), 'Amo'), ($2, now(), 'Dan')", AMO, DAN)
        await conn.execute(
            "INSERT INTO rooms (id, created_at, name, token) "
            "VALUES ($1, now(), 'Round Room', $2)", ROOM, TOKEN)
        await conn.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES "
            "($1, $2, now()), ($1, $3, now())", ROOM, AMO, DAN)
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) "
            "VALUES ($1, $2, now(), 'Main')", THREAD, ROOM)
        await conn.execute(
            """INSERT INTO messages (id, thread_id, sequence, created_at,
                   speaker_type, message_type, content)
               VALUES ($1, $2, 1, now(), 'llm_annotator', 'text', 'The Sunday Round')""",
            CARD, THREAD)
        rounds_mod._db_pool = _Pool(conn)
        yield conn
    finally:
        rounds_mod._db_pool = None
        await tx.rollback()
        await conn.close()


async def _question(db, *, closes_in_days: int = 30) -> UUID:
    qid = uuid4()
    await db.execute(
        """INSERT INTO commitments (id, room_id, thread_id, source_message_id,
               claim, resolution_criteria, category, created_at, deadline, status)
           VALUES ($1, $2, $3, $4, 'Does the BOJ raise at or before Dec 19?',
                   'Resolves on the BOJ policy statement.', 'round', now(), $5,
                   'active')""",
        qid, ROOM, THREAD, CARD,
        datetime.now(timezone.utc) + timedelta(days=closes_in_days),
    )
    return qid


def _as(user_id):
    return AuthenticatedUser(
        user_id=user_id, email="x@example.com",
        email_verified=True, display_name="Tester",
    )


async def _forecast(db, qid, user, value):
    return await record_forecast(
        ROOM, qid, ForecastRequest(confidence=value),
        token=TOKEN, current_user=_as(user), pool=rounds_mod._db_pool,
    )


def _q(state):
    return state["questions"][0]


@pytest.mark.asyncio
class TestBlindness:
    async def test_a_lone_forecaster_is_told_they_are_waiting(self, db):
        qid = await _question(db)
        q = _q(await _forecast(db, qid, AMO, 0.35))
        assert q["my_forecast"] == 0.35
        assert q["revealed"] is False
        assert q["waiting_on_other"] is True

    async def test_the_other_number_is_ABSENT_not_merely_hidden(self, db):
        """The point of the whole rule: it must not be in the response body."""
        qid = await _question(db)
        await _forecast(db, qid, DAN, 0.70)
        q = _q(await _forecast(db, qid, AMO, 0.35))
        # Amo has now forecast, so reveal is legitimate here.
        assert q["revealed"] is True
        # But before he had, Dan's 0.70 must never have been serialized:
        blind = _q(await _round_state(db, ROOM, CARD, uuid4()))
        assert "others" not in blind
        assert "0.7" not in str(blind) and "0.70" not in str(blind)
        assert blind["others_committed"] == 2

    async def test_a_viewer_who_has_not_forecast_sees_no_numbers(self, db):
        qid = await _question(db)
        await _forecast(db, qid, DAN, 0.70)
        # Amo reads the card without committing.
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        assert q["my_forecast"] is None
        assert q["revealed"] is False
        assert "others" not in q
        assert "0.7" not in str(q)

    async def test_both_committed_reveals_both(self, db):
        qid = await _question(db)
        await _forecast(db, qid, AMO, 0.35)
        q = _q(await _forecast(db, qid, DAN, 0.70))
        assert q["revealed"] is True
        assert q["my_forecast"] == 0.70
        assert [o["forecast"] for o in q["others"]] == [0.35]

    async def test_revision_after_reveal_shows_the_latest_not_the_first(self, db):
        """stakes/manager returns history DESC and two existing components read
        the OLDEST entry by looping forward. This projection must not."""
        qid = await _question(db)
        await _forecast(db, qid, AMO, 0.35)
        await _forecast(db, qid, DAN, 0.70)
        await _forecast(db, qid, AMO, 0.10)
        q = _q(await _round_state(db, ROOM, CARD, DAN))
        assert [o["forecast"] for o in q["others"]] == [0.10]
        assert [o["revisions"] for o in q["others"]] == [2]


@pytest.mark.asyncio
class TestTheCloseIsReal:
    async def test_a_forecast_after_close_is_refused_not_stored(self, db):
        """The scorer would discard it. Confirming a write nobody will ever
        score is worse than refusing it — the desk's own endpoint has this bug."""
        qid = await _question(db, closes_in_days=-1)
        with pytest.raises(HTTPException) as exc:
            await _forecast(db, qid, AMO, 0.35)
        assert exc.value.status_code == 409
        assert "closed" in exc.value.detail
        stored = await db.fetchval(
            "SELECT count(*) FROM commitment_confidence WHERE commitment_id = $1", qid)
        assert stored == 0, "a refused forecast must not be stored"

    async def test_revisions_before_close_are_appended_never_updated(self, db):
        qid = await _question(db)
        await _forecast(db, qid, AMO, 0.35)
        await _forecast(db, qid, AMO, 0.55)
        rows = await db.fetch(
            "SELECT confidence FROM commitment_confidence WHERE commitment_id = $1"
            " AND user_id = $2 ORDER BY recorded_at", qid, AMO)
        assert [r["confidence"] for r in rows] == [0.35, 0.55], (
            "the forecast history is what gets time-weighted; it must accumulate"
        )


@pytest.mark.asyncio
class TestTheVeto:
    async def test_a_binned_question_refuses_forecasts(self, db):
        qid = await _question(db)
        await bin_question(ROOM, qid, token=TOKEN, current_user=_as(AMO),
                           pool=rounds_mod._db_pool)
        with pytest.raises(HTTPException) as exc:
            await _forecast(db, qid, DAN, 0.5)
        assert exc.value.status_code == 409
        assert "binned" in exc.value.detail

    async def test_binning_is_visible_to_both(self, db):
        qid = await _question(db)
        await bin_question(ROOM, qid, token=TOKEN, current_user=_as(AMO),
                           pool=rounds_mod._db_pool)
        assert _q(await _round_state(db, ROOM, CARD, DAN))["status"] == "binned"


@pytest.mark.asyncio
class TestAccessControl:
    async def test_a_non_member_is_refused(self, db):
        qid = await _question(db)
        with pytest.raises(HTTPException) as exc:
            await record_forecast(
                ROOM, qid, ForecastRequest(confidence=0.5),
                token=TOKEN, current_user=_as(uuid4()), pool=rounds_mod._db_pool)
        assert exc.value.status_code == 403

    async def test_a_bad_room_token_is_refused(self, db):
        qid = await _question(db)
        with pytest.raises(HTTPException) as exc:
            await record_forecast(
                ROOM, qid, ForecastRequest(confidence=0.5),
                token="wrong", current_user=_as(AMO), pool=rounds_mod._db_pool)
        assert exc.value.status_code == 401

    async def test_a_question_from_another_room_is_not_found(self, db):
        with pytest.raises(HTTPException) as exc:
            await record_forecast(
                ROOM, uuid4(), ForecastRequest(confidence=0.5),
                token=TOKEN, current_user=_as(AMO), pool=rounds_mod._db_pool)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestOneWholeRound:
    """The journey, end to end, against real Postgres.

    This is the check that would have caught the defect that emptied the
    ledger: a claim that reaches the ledger without a deadline or a
    confidence can never be scored, and every other path into it produced
    exactly that. A round question is born with both.
    """

    async def test_draft_to_score(self, db):
        from llm.question_round import _open_questions, parse_round

        raw = (
            "QUESTION: Does the BOJ raise at or before the December 19 meeting?\n"
            "SOURCE: Bank of Japan policy statement\n"
            "RESOLVES: 2026-12-19\n"
            "BASE_RATE: 22%\n"
            "WHY: The Japan book turns on it.\n"
        )
        questions = parse_round(raw, today=datetime.now(timezone.utc).date())
        assert len(questions) == 1

        await _open_questions(db, ROOM, THREAD, CARD, questions)
        qid = UUID(questions[0]["commitment_id"])

        # BORN SCOREABLE — the whole point.
        row = await db.fetchrow(
            "SELECT deadline, category, status FROM commitments WHERE id = $1", qid)
        assert row["deadline"] is not None, (
            "a round question without a deadline could never be scored"
        )
        assert row["category"] == "round"

        # Amo goes first and is sealed.
        q = _q(await _forecast(db, qid, AMO, 0.30))
        assert q["revealed"] is False and q["waiting_on_other"] is True

        # Dan answers; both open.
        q = _q(await _forecast(db, qid, DAN, 0.75))
        assert q["revealed"] is True
        assert q["others"][0]["forecast"] == 0.30

        # Amo updates on news — TEN DAYS LATER. The dates have to be real:
        # the rule scores a DAY at whatever forecast stood that day, so a whole
        # journey compressed into one afternoon has no lateness to measure and
        # time-weighting is indistinguishable from final-answer scoring. That
        # is correct behaviour, and it is why this backdates rather than
        # asserting a gap that same-day activity cannot produce.
        await db.execute(
            """UPDATE commitment_confidence
               SET recorded_at = recorded_at - interval '10 days'
               WHERE commitment_id = $1""", qid)
        # The QUESTION has to move back with them. The scoring window opens
        # when the question was asked, not when someone first answered it --
        # otherwise a forecaster who opens the card late is scored only over
        # their own shorter, later, EASIER window and arriving late reads as
        # skill. A round posted ten days ago is what this is.
        await db.execute(
            """UPDATE commitments
               SET created_at = created_at - interval '10 days'
               WHERE id = $1""", qid)
        await _forecast(db, qid, AMO, 0.10)

        # It resolves NO.
        await db.execute(
            """UPDATE commitments
               SET status='resolved', resolution='incorrect', resolved_at=now()
               WHERE id = $1""", qid)

        scored = _q(await _round_state(db, ROOM, CARD, AMO))["scores"]
        by_user = {s["user_id"]: s for s in scored}
        amo = by_user[str(AMO)]
        dan = by_user[str(DAN)]

        # Amo moved toward the truth; Dan did not.
        assert amo["brier"] < dan["brier"]
        # And the time-weighted number is NOT the final answer — Amo carries
        # the days he spent at 0.30, which final-answer scoring would erase.
        assert amo["brier"] > amo["brier_final_answer"]
        assert amo["lateness_gap"] > 0
        assert amo["days_scored"] >= 1


@pytest.mark.asyncio
class TestTheHouseIsSealedToo:
    """The third forecaster, and the rule it must not break.

    `commitment_confidence.user_id` is nullable, and `_round_state` used to
    split a question's history on `user_id != viewer_id` alone. A house row
    landing among the humans would set `revealed = True` and unseal one
    person's blind number to the other the instant the machine posted its own
    — with no error anywhere, on the one surface where a leak is the whole
    game. These are the tests that say it does not.
    """

    async def test_a_house_forecast_alone_does_not_unseal_the_card(self, db):
        from stakes.house import record_house_forecast

        qid = await _question(db)
        await _forecast(db, qid, AMO, 0.35)
        # The machine answers. Dan has not.
        await record_house_forecast(
            db, commitment_id=qid, room_id=ROOM, thread_id=THREAD,
            confidence=0.72, reasoning="JGB 10y already near 2.95%.",
        )
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        assert q["revealed"] is False, (
            "the house is not a second human — it must not unseal the card"
        )
        assert q["waiting_on_other"] is True
        assert "others" not in q
        assert q["others_committed"] == 0
        assert "house" not in q
        # Not merely hidden: the number must be ABSENT from the body.
        assert "0.72" not in str(q)
        # That it HAS answered is not an anchor; the number is.
        assert q["house_committed"] is True

    async def test_the_house_appears_only_once_both_humans_are_in(self, db):
        from stakes.house import record_house_forecast

        qid = await _question(db)
        await record_house_forecast(
            db, commitment_id=qid, room_id=ROOM, thread_id=THREAD,
            confidence=0.72, reasoning="JGB 10y already near 2.95%.",
        )
        await _forecast(db, qid, AMO, 0.35)
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        assert q["revealed"] is False
        await _forecast(db, qid, DAN, 0.60)
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        assert q["revealed"] is True
        assert q["house"]["forecast"] == 0.72
        assert q["house"]["because"] == "JGB 10y already near 2.95%."
        # And it is not mistaken for a person on the way through.
        assert [o["forecast"] for o in q["others"]] == [0.60]

    async def test_the_house_row_is_written_as_the_house(self, db):
        from stakes.house import record_house_forecast

        qid = await _question(db)
        await record_house_forecast(
            db, commitment_id=qid, room_id=ROOM, thread_id=THREAD,
            confidence=0.72,
        )
        row = await db.fetchrow(
            "SELECT user_id, actor, confidence FROM commitment_confidence "
            "WHERE commitment_id = $1", qid)
        assert row["actor"] == "house"
        assert row["user_id"] is None
        # And a human's row is still stamped human by the column default, so
        # the two can never be told apart by accident.
        await _forecast(db, qid, AMO, 0.35)
        human = await db.fetchrow(
            "SELECT actor FROM commitment_confidence "
            "WHERE commitment_id = $1 AND user_id = $2", qid, AMO)
        assert human["actor"] == "human"


@pytest.mark.asyncio
class TestTheSecondSlider:
    """Your guess at where THEY will land. It scores the moment you both
    commit and never waits for the world to settle anything.
    """

    async def test_your_read_is_yours_to_see_but_theirs_is_not(self, db):
        qid = await _question(db)
        await record_forecast(
            ROOM, qid, ForecastRequest(confidence=0.35, peer_forecast=0.80),
            token=TOKEN, current_user=_as(AMO), pool=rounds_mod._db_pool,
        )
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        # Hiding your own guess from you would only stop you revising it.
        assert q["my_peer_forecast"] == 0.80
        assert q["revealed"] is False
        # But it must not tell you how you did before they have answered.
        assert "peer_read_error" not in q

    async def test_the_read_error_is_signed_so_it_says_which_way(self, db):
        qid = await _question(db)
        await record_forecast(
            ROOM, qid, ForecastRequest(confidence=0.35, peer_forecast=0.30),
            token=TOKEN, current_user=_as(AMO), pool=rounds_mod._db_pool,
        )
        await _forecast(db, qid, DAN, 0.75)
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        # Read him at 0.30, he came in at 0.75 -- read him LOW by 0.45.
        assert q["peer_read_error"] == pytest.approx(0.45)

    async def test_declining_the_second_slider_is_not_a_guess_of_zero(self, db):
        qid = await _question(db)
        await _forecast(db, qid, AMO, 0.35)
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        assert q["my_peer_forecast"] is None
        await _forecast(db, qid, DAN, 0.75)
        q = _q(await _round_state(db, ROOM, CARD, AMO))
        assert "peer_read_error" not in q, (
            "no read was given, so there is no error to report"
        )

    async def test_the_second_slider_is_not_relayed_to_the_desk(self, db):
        # The desk scores CLAIMS about the world. A bet on your friend is not
        # one, and mirroring it would put a number in the desk's ledger that
        # nothing there knows how to grade.
        import inspect
        from stakes import manager as mgr
        src = inspect.getsource(mgr.CommitmentManager.record_confidence)
        relay_call = src.split("relay_confidence(")[1].split(")")[0]
        assert "peer_forecast" not in relay_call


@pytest.mark.asyncio
class TestTheVerdict:
    """Nothing settles itself. The close-watch job gathers evidence and
    suggests; the human taps. One wrong automatic settlement would cost this
    ledger its standing permanently and there is no earning that back.
    """

    async def test_a_human_tap_turns_a_closed_question_into_a_score(self, db):
        from api.rounds import ResolveRequest, resolve_question

        qid = await _question(db, closes_in_days=-1)
        await db.execute(
            "UPDATE commitments SET created_at = now() - interval '10 days' "
            "WHERE id = $1", qid)
        await db.execute(
            """INSERT INTO commitment_confidence
                   (commitment_id, user_id, confidence, recorded_at)
               VALUES ($1, $2, 0.9, now() - interval '9 days'),
                      ($1, $3, 0.2, now() - interval '9 days')""",
            qid, AMO, DAN)
        state = await resolve_question(
            ROOM, qid, ResolveRequest(resolution="correct"),
            token=TOKEN, current_user=_as(AMO), pool=rounds_mod._db_pool,
        )
        q = state["questions"][0]
        assert q["resolution"] == "correct"
        by_user = {s["user_id"]: s for s in q["scores"]}
        assert by_user[str(AMO)]["brier"] < by_user[str(DAN)]["brier"]
        # The duel is antisymmetric -- it can only say who took whose points.
        assert by_user[str(AMO)]["peer"] == pytest.approx(
            -by_user[str(DAN)]["peer"])
        assert by_user[str(AMO)]["peer"] > 0
        assert by_user[str(AMO)]["contested_days"] >= 1

    async def test_settling_twice_is_refused_not_silently_rewritten(self, db):
        from api.rounds import ResolveRequest, resolve_question

        qid = await _question(db, closes_in_days=-1)
        await resolve_question(
            ROOM, qid, ResolveRequest(resolution="correct"),
            token=TOKEN, current_user=_as(AMO), pool=rounds_mod._db_pool,
        )
        with pytest.raises(HTTPException) as exc:
            await resolve_question(
                ROOM, qid, ResolveRequest(resolution="incorrect"),
                token=TOKEN, current_user=_as(DAN), pool=rounds_mod._db_pool,
            )
        # A re-settle would rewrite resolved_at and silently move every
        # scoring window that hangs off it.
        assert exc.value.status_code == 409
        assert "already settled" in exc.value.detail

    async def test_a_binned_question_can_never_be_settled(self, db):
        from api.rounds import ResolveRequest, resolve_question

        qid = await _question(db, closes_in_days=-1)
        await bin_question(
            ROOM, qid, token=TOKEN, current_user=_as(AMO),
            pool=rounds_mod._db_pool,
        )
        with pytest.raises(HTTPException) as exc:
            await resolve_question(
                ROOM, qid, ResolveRequest(resolution="correct"),
                token=TOKEN, current_user=_as(AMO), pool=rounds_mod._db_pool,
            )
        assert exc.value.status_code == 409
        assert "binned" in exc.value.detail

    async def test_a_voided_question_is_never_scored(self, db):
        from api.rounds import ResolveRequest, resolve_question

        qid = await _question(db, closes_in_days=-1)
        await db.execute(
            """INSERT INTO commitment_confidence
                   (commitment_id, user_id, confidence, recorded_at)
               VALUES ($1, $2, 0.9, now())""", qid, AMO)
        state = await resolve_question(
            ROOM, qid, ResolveRequest(resolution="voided"),
            token=TOKEN, current_user=_as(AMO), pool=rounds_mod._db_pool,
        )
        # Inventing a 0.5 outcome for a binary question is exactly the
        # manufactured number this ledger exists to avoid.
        assert "scores" not in state["questions"][0]


@pytest.mark.asyncio
class TestThePeersAreMembershipNotForecasts:
    async def test_the_card_can_name_them_before_they_answer(self, db):
        # The second slider asks "where will Dan land?", and before reveal the
        # only other place his name appears is inside a forecast -- which is
        # the one thing that must stay sealed.
        qid = await _question(db)
        state = await _round_state(db, ROOM, CARD, AMO)
        assert [p["display_name"] for p in state["peers"]] == ["Dan"]
        assert str(DAN) in [p["user_id"] for p in state["peers"]]
        # Membership only. No number rides along.
        assert "confidence" not in str(state["peers"])
        assert _q(state)["revealed"] is False
