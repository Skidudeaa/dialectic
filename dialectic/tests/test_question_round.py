"""The Sunday Round's drafting job.

The parser is the quality gate. These owners forecast in IARPA's ACE
tournament, so a question missing its resolution source or its close date is
not a question — it is an argument waiting to happen. The parser therefore
DROPS malformed blocks rather than repairing them: an invented resolution
source is precisely the failure the format exists to prevent.
"""

from datetime import date

import pytest

from llm.question_round import (
    ENABLED_ENV,
    question_round,
    QUESTIONS_PER_ROUND,
    ROUND_SYSTEM,
    is_round_day,
    parse_round,
    register_question_round_jobs,
    render_round,
)


TODAY = date(2026, 8, 23)   # a Sunday

GOOD = """QUESTION: Does the Bank of Japan raise its policy rate at or before the December 19 meeting?
SOURCE: Bank of Japan policy statement
RESOLVES: 2026-12-19
BASE_RATE: 22% — BOJ raised at 2 of the last 9 meetings
WHY: The Japan Rate Shock book turns on exactly this.
---
QUESTION: Does front-month Brent settle above $95 on any day before September 30?
SOURCE: ICE Brent front-month settlement
RESOLVES: 2026-09-30
BASE_RATE: NONE
WHY: The Hormuz cascade's first hard trigger.
"""


class TestTheSundayGate:
    def test_fires_on_sunday(self):
        assert is_round_day(date(2026, 8, 23)) is True

    @pytest.mark.parametrize("day", range(17, 23))
    def test_silent_every_other_morning(self, day):
        assert is_round_day(date(2026, 8, day)) is False


class TestParsing:
    def test_parses_a_well_formed_round(self):
        got = parse_round(GOOD, today=TODAY)
        assert len(got) == 2
        assert got[0]["source"] == "Bank of Japan policy statement"
        assert got[0]["closes"] == "2026-12-19"
        assert got[0]["base_rate"].startswith("22%")

    def test_NONE_base_rate_becomes_null_not_the_string(self):
        assert parse_round(GOOD, today=TODAY)[1]["base_rate"] is None

    def test_forecasts_are_not_carried_in_the_block(self):
        """They live in commitment_confidence rows — schema.sql:249-259."""
        assert "forecasts" not in parse_round(GOOD, today=TODAY)[0]

    def test_commitment_id_starts_unfilled(self):
        assert parse_round(GOOD, today=TODAY)[0]["commitment_id"] is None

    def test_a_question_with_no_named_source_is_DROPPED_not_repaired(self):
        raw = ("QUESTION: Will the Fed cut?\n"
               "RESOLVES: 2026-12-01\n---\n") + GOOD
        got = parse_round(raw, today=TODAY)
        assert len(got) == 2
        assert all("Will the Fed cut?" not in q["question"] for q in got)

    def test_a_question_with_no_close_date_is_dropped(self):
        raw = ("QUESTION: Will oil spike?\nSOURCE: ICE\nRESOLVES: soon\n---\n") + GOOD
        assert len(parse_round(raw, today=TODAY)) == 2

    def test_a_question_that_already_closed_is_dropped(self):
        """Nobody can forecast a question whose close date has passed."""
        raw = ("QUESTION: Did it happen?\nSOURCE: X\nRESOLVES: 2026-01-01\n---\n")
        assert parse_round(raw, today=TODAY) == []

    def test_garbage_yields_no_questions_rather_than_raising(self):
        assert parse_round("I'm sorry, I can't help with that.", today=TODAY) == []
        assert parse_round("", today=TODAY) == []

    def test_a_trailing_block_without_its_separator_still_parses(self):
        raw = ("QUESTION: Does X happen?\nSOURCE: The X report\n"
               "RESOLVES: 2026-10-01\nWHY: because")
        assert len(parse_round(raw, today=TODAY)) == 1


class TestTheContract:
    def test_the_prompt_states_all_four_gjp_requirements(self):
        for demand in ("BINARY", "NAMED RESOLUTION SOURCE",
                       "HARD CLOSE DATE", "NON-TRIVIAL"):
            assert demand in ROUND_SYSTEM

    def test_the_prompt_forbids_a_consensus_resolution_source(self):
        assert "consensus" in ROUND_SYSTEM

    def test_render_names_the_source_and_the_close_for_every_question(self):
        text = render_round(parse_round(GOOD, today=TODAY), TODAY)
        assert "Bank of Japan policy statement" in text
        assert "2026-12-19" in text
        assert "closes" in text

    def test_render_tells_them_revisions_are_scored(self):
        """Updating on news is the measured skill; the card must say so."""
        text = render_round(parse_round(GOOD, today=TODAY), TODAY)
        assert "Revise" in text or "revise" in text


class TestRegistration:
    def test_the_job_carries_its_flag_so_the_capability_map_sees_it(self):
        registered = []

        class FakeScheduler:
            def register(self, job):
                registered.append(job)

        register_question_round_jobs(FakeScheduler())
        assert len(registered) == 1
        job = registered[0]
        assert job.name == "question_round"
        assert job.enabled_env == ENABLED_ENV
        # Wall-clock, in THEIR timezone — a round that lands at 3am is not a
        # round anybody looks forward to.
        assert job.daily_at == "09:00"
        assert job.daily_tz == "America/Chicago"

    def test_the_flag_actually_disables_it(self, monkeypatch):
        registered = []

        class FakeScheduler:
            def register(self, job):
                registered.append(job)

        register_question_round_jobs(FakeScheduler())
        monkeypatch.setenv(ENABLED_ENV, "0")
        assert registered[0].enabled() is False
        monkeypatch.setenv(ENABLED_ENV, "1")
        assert registered[0].enabled() is True

    def test_round_size(self):
        assert QUESTIONS_PER_ROUND == 5


class TestWhichRoomsGetARound:
    """The selection query, asserted as SQL because it is the whole blast
    radius: a room that should not receive a round receives one every Sunday
    forever, and a room that should never stops.
    """

    @staticmethod
    def _sql():
        import inspect
        from llm import question_round as mod
        return inspect.getsource(mod.question_round)

    def test_requires_two_members_because_blindness_needs_two(self):
        """A one-member room can NEVER unseal — `revealed` requires both
        forecasters — so a round there would draft questions that could never
        be read. A real one ("Hi Dan!", one member, and that member a retired
        account) qualified under the first version of this query."""
        sql = self._sql()
        assert "room_memberships" in sql
        assert ">= 2" in sql

    def test_requires_human_traffic_not_merely_traffic(self):
        """Twelve scheduled jobs post into rooms on their own, so `messages`
        alone keeps a room looking alive long after both people left it."""
        assert "speaker_type = 'human'" in self._sql()

    def test_excludes_home(self):
        assert "NOT r.is_home" in self._sql()

    def test_the_window_is_stated_once(self):
        sql = self._sql()
        assert sql.count("interval '14 days'") == 1


class TestTheRoundIsIdempotentPerDay:
    def test_the_guard_matches_on_the_round_source(self):
        """A scheduler retry, or a restart inside the 09:00 slot, must not
        post a second round into the same room the same day."""
        import inspect
        from llm import question_round as mod
        sql = inspect.getsource(mod._already_ran_today)
        assert "'question_round'" in sql
        assert "source" in sql


# ── the room reaching the drafter ────────────────────────────────────────

class _FakeConn:
    """Dispatches on the SQL text because `_room_signals` runs two different
    queries against the same connection. Rows are plain dicts — asyncpg
    Records are mappings, and nothing here needs more than that."""

    def __init__(self, messages=(), open_questions=()):
        self.messages = list(messages)
        self.open_questions = list(open_questions)

    async def fetch(self, sql, *args):
        if "speaker_type = 'human'" in sql:
            return [{"content": c} for c in self.messages]
        if "category = 'round'" in sql:
            return [{"claim": c} for c in self.open_questions]
        raise AssertionError(f"unexpected query: {sql[:80]}")


def _room(config, room_id="r1"):
    return {"id": room_id, "name": "Iran/Hormuz", "trading_config": config}


class TestTheRoomReachesTheDrafter:
    """Before 2026-08-20 the drafter saw the room NAME, the thesis TITLE and
    eight reading summaries — nothing else. A live dry run against all four
    rooms produced questions a stranger reading the news could have written,
    which is exactly what the job's own prompt calls a wasted slot. These
    assert the room's own state actually arrives.
    """

    @pytest.mark.asyncio
    async def test_live_nodes_are_offered_and_fired_nodes_are_fenced(self):
        from llm.question_round import _room_signals
        config = {"nodeStates": {
            "fert-shortage": "approaching",
            "rig-confirm": "monitoring",
            "hormuz": "fired",
            "brent": "stable",
            "services": "gated",
        }}
        text = "\n".join(await _room_signals(_FakeConn(), _room(config)))
        assert "fert-shortage" in text and "rig-confirm" in text
        # A question whose answer is already yes fails the round's own
        # criterion 4, so a fired node must arrive fenced, not offered.
        assert "do NOT ask" in text
        fenced = text.split("do NOT ask")[1]
        assert "hormuz" in fenced
        # Neither live nor settled: a stable node is not a forecast.
        assert "brent" not in text and "services" not in text

    @pytest.mark.asyncio
    async def test_the_desks_own_probabilities_arrive_ranked(self):
        from llm.question_round import _room_signals
        config = {"scenarioImpacts": {
            "reopen-apr1": {"probability": 0.18},
            "closed-may": {"probability": 0.42},
            "kharg-strike": {"probability": 0.12},
            "no-number": {"impact": 3},
        }}
        text = "\n".join(await _room_signals(_FakeConn(), _room(config)))
        assert "closed-may 42%" in text
        assert text.index("closed-may") < text.index("reopen-apr1")
        # A scenario carrying no probability is not a probability.
        assert "no-number" not in text

    @pytest.mark.asyncio
    async def test_what_they_said_arrives_oldest_first_and_bounded(self):
        from llm.question_round import _room_signals
        conn = _FakeConn(messages=["newest", "middle", "x" * 400])
        text = "\n".join(await _room_signals(conn, _room({})))
        # The query is DESC (newest first); the prompt reads oldest-first so
        # the argument runs forwards.
        assert text.index("x" * 100) < text.index("newest")
        assert "x" * 241 not in text

    @pytest.mark.asyncio
    async def test_open_questions_are_fenced_against_re_asking(self):
        from llm.question_round import _room_signals
        conn = _FakeConn(open_questions=["Does Brent settle above $95?"])
        text = "\n".join(await _room_signals(conn, _room({})))
        assert "do not re-ask" in text
        assert "Does Brent settle above $95?" in text

    @pytest.mark.asyncio
    async def test_a_json_string_config_does_not_silently_vanish(self):
        """`rooms.trading_config` arrives as a dict only because the app pool
        registers a jsonb codec (api/main.py:126). Under a pool without one it
        is a str, `isinstance(config, dict)` is False, and the entire thesis
        context disappears with no error — which is what happened to the
        2026-08-20 dry-run harness and read as a live bug."""
        import json
        from llm.question_round import _as_config, _room_signals
        raw = json.dumps({"nodeStates": {"fert-shortage": "approaching"}})
        assert _as_config(raw)["nodeStates"]["fert-shortage"] == "approaching"
        text = "\n".join(await _room_signals(_FakeConn(), _room(raw)))
        assert "fert-shortage" in text
        assert _as_config("not json") == {} and _as_config(None) == {}


class TestThePromptTellsTheTruth:
    def test_it_does_not_claim_context_it_was_not_given(self):
        """China Property has zero reading_items and, some weeks, no signals.
        Its prompt used to end 'Ground the questions in the above where you
        can' with nothing above it — an instruction to invent."""
        from llm.question_round import _build_prompt
        bare = _build_prompt("Room", "", [], TODAY, [])
        assert "Ground the questions in the above" not in bare
        assert "no room state this week" in bare

        fed = _build_prompt("Room", "", [], TODAY, ["a signal line"])
        assert "Ground the questions in the above" in fed

    def test_every_question_gets_its_own_close_date(self):
        """`HORIZONS_DAYS[i % 3]` repeated exactly, so a five-question round
        asked for two duplicate horizons — quietly halving the spread the
        mixed-horizon rule exists to create."""
        from llm.question_round import _horizon_dates
        dates = _horizon_dates(TODAY)
        assert len(dates) == len(set(dates)) == QUESTIONS_PER_ROUND
