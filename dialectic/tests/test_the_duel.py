"""The duel: the third forecaster, the head-to-head, and coverage.

The Sunday Round was built for two people. This is what it takes to seat a
third at the same table without breaking the rule that makes the first two
worth playing: neither human sees the other's number until both are in.

Pure functions only — the read path's three-way split and the resolve door are
in `test_rounds_pg.py`, against real Postgres, because the failure that
matters there is a query.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from stakes.house import HOUSE, HUMAN, is_house, split_by_actor
from stakes.timeweighted import (
    LOG_CLIP,
    daily_log_scores,
    peer_delta,
    scoring_window,
    time_weighted_brier,
    time_weighted_log,
    window_days,
)


def _row(actor=None, **rest):
    row = dict(rest)
    if actor is not None:
        row["actor"] = actor
    return row


class TestWhoIsTheHouse:
    """One predicate, in the shape presence.py earned.

    The bug this prevents is silent: `_round_state` splits a question's
    history on `user_id != viewer_id`, and `commitment_confidence.user_id` is
    nullable. A house row landing in `others` would set `revealed = True` and
    unseal one human's blind forecast to the other the instant the machine
    posted its own.
    """

    def test_a_row_written_before_migration_019_is_human(self):
        # Every row in the table before the actor column existed is a person's,
        # and `.get` must not be the thing that decides otherwise.
        assert is_house(_row()) is False
        assert is_house(_row(actor=None)) is False

    def test_the_actor_column_is_what_decides_not_the_user_id(self):
        # A human row with a NULL user_id (the default of
        # CommitmentManager.record_confidence) is STILL a human row.
        assert is_house(_row(actor=HUMAN, user_id=None)) is False
        assert is_house(_row(actor=HOUSE, user_id=None)) is True

    def test_the_split_preserves_order_within_each_side(self):
        history = [
            _row(actor=HUMAN, confidence=0.1),
            _row(actor=HOUSE, confidence=0.7),
            _row(actor=HUMAN, confidence=0.2),
            _row(actor=HOUSE, confidence=0.6),
        ]
        humans, house = split_by_actor(history)
        assert [h["confidence"] for h in humans] == [0.1, 0.2]
        assert [h["confidence"] for h in house] == [0.7, 0.6]

    def test_a_house_row_never_appears_among_the_humans(self):
        _, house = split_by_actor([_row(actor=HOUSE, confidence=0.5)])
        humans, _ = split_by_actor([_row(actor=HOUSE, confidence=0.5)])
        assert len(house) == 1 and humans == []


OPENED = date(2026, 8, 1)
CLOSE = datetime(2026, 8, 11, tzinfo=timezone.utc)


def _history(start_day: int, value: float, days: int = 1):
    """One forecaster's history: `value` entered on OPENED + start_day."""
    return [{
        "recorded_at": datetime(2026, 8, 1 + start_day, 12, tzinfo=timezone.utc),
        "confidence": value,
    }] * days


class TestCoverageMakesAbsenceHonest:
    """A late forecaster is scored over a SHORTER, LATER window — and later
    is nearer the outcome, so it is easier. Without coverage beside the Brier,
    arriving late reads as skill.
    """

    def test_the_late_arriver_scores_fewer_days(self):
        early = time_weighted_brier(
            _history(0, 0.9), opened=OPENED, close=CLOSE,
            resolved_at=CLOSE, resolution="correct")
        late = time_weighted_brier(
            _history(9, 0.9), opened=OPENED, close=CLOSE,
            resolved_at=CLOSE, resolution="correct")
        assert early["days_scored"] > late["days_scored"]
        # Same number, same outcome, identical Brier -- the ONLY thing that
        # says one of them was barely there is coverage.
        assert early["brier"] == pytest.approx(late["brier"])
        assert early["coverage"] > late["coverage"]
        assert late["coverage"] < 0.5

    def test_coverage_is_one_when_you_were_in_from_the_open(self):
        scored = time_weighted_brier(
            _history(0, 0.9), opened=OPENED, close=CLOSE,
            resolved_at=CLOSE, resolution="correct")
        assert scored["coverage"] == pytest.approx(1.0)

    def test_window_days_is_inclusive(self):
        assert window_days((date(2026, 8, 1), date(2026, 8, 1))) == 1
        assert window_days(scoring_window(OPENED, CLOSE, CLOSE)) == 11


class TestTheLogScoreIsClipped:
    """The slider goes to 0.00 and 1.00, and a 0.00 that resolves yes is
    infinitely wrong. Unclipped, one such call would annihilate a season and
    the ledger would be unreadable forever after. The clip IS the rule.
    """

    def test_certainty_that_is_wrong_is_bounded(self):
        import math
        window = scoring_window(OPENED, CLOSE, CLOSE)
        daily = daily_log_scores(_history(0, 0.0), window, outcome=1.0)
        worst = min(daily.values())
        assert worst == pytest.approx(math.log(LOG_CLIP))
        assert worst > float("-inf")

    def test_certainty_that_is_right_is_not_a_perfect_zero(self):
        window = scoring_window(OPENED, CLOSE, CLOSE)
        daily = daily_log_scores(_history(0, 1.0), window, outcome=1.0)
        assert max(daily.values()) < 0.0

    def test_it_scores_the_same_days_as_the_brier(self):
        kwargs = dict(opened=OPENED, close=CLOSE, resolved_at=CLOSE,
                      resolution="correct")
        brier = time_weighted_brier(_history(3, 0.8), **kwargs)
        logged = time_weighted_log(_history(3, 0.8), **kwargs)
        assert brier["days_scored"] == logged["days_scored"]

    def test_an_unscoreable_question_is_none_and_never_zero(self):
        # Zero is a PERFECT log score. Returning it for "we cannot score this"
        # would render as flawless.
        assert time_weighted_log(
            _history(0, 0.5), opened=OPENED, close=CLOSE,
            resolved_at=CLOSE, resolution="voided") is None


class TestTheHeadToHead:
    """At n=2 the peer score collapses to a duel that sums to exactly zero.
    That is the whole appeal: it can only say one of them took the other's
    points, never that both are winning.
    """

    @staticmethod
    def _daily(a: dict, b: dict):
        return {"a": a, "b": b}

    def test_it_is_antisymmetric(self):
        d1, d2 = date(2026, 8, 1), date(2026, 8, 2)
        out = peer_delta(self._daily(
            {d1: -0.1, d2: -0.1},
            {d1: -0.9, d2: -0.9},
        ))
        assert out["a"]["peer"] == pytest.approx(-out["b"]["peer"])
        assert out["a"]["peer"] > 0 > out["b"]["peer"]

    def test_only_days_both_were_in_are_contested(self):
        d1, d2, d3 = date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)
        out = peer_delta(self._daily(
            {d1: -0.1, d2: -0.1, d3: -0.1},
            {d3: -0.9},
        ))
        # A day one of them had not yet forecast is not a day they LOST -- it
        # is a day they were absent, and coverage reports that separately.
        assert out["a"]["contested_days"] == 1
        assert out["b"]["contested_days"] == 1

    def test_one_forecaster_alone_has_nobody_to_beat(self):
        assert peer_delta({"a": {date(2026, 8, 1): -0.1}}) == {}
        assert peer_delta({"a": {date(2026, 8, 1): -0.1}, "b": {}}) == {}

    def test_no_overlap_is_reported_as_no_contest_not_as_a_draw(self):
        out = peer_delta(self._daily(
            {date(2026, 8, 1): -0.1},
            {date(2026, 8, 9): -0.9},
        ))
        # A zero here would read as "you were exactly level".
        assert out["a"]["peer"] is None
        assert out["a"]["contested_days"] == 0

    def test_three_forecasters_still_sum_to_zero(self):
        # The house makes it three. Each is scored against the MEAN of the
        # others, so the sum stays zero and no single number can be gamed by
        # a third player arriving.
        d = date(2026, 8, 1)
        out = peer_delta({"a": {d: -0.1}, "b": {d: -0.5}, "c": {d: -0.9}})
        assert sum(v["peer"] for v in out.values()) == pytest.approx(0.0)
