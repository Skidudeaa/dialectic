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
