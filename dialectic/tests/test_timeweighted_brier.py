"""The Good Judgment scoring rule, pinned to worked examples.

The owners forecast in IARPA's ACE tournament. The rule there scores every
day a question was open at whatever your standing forecast was that day, so
updating early on real news is the measured skill. Every number below is
computed by hand in the docstring before being asserted, because a scoring
rule that is only checked against its own implementation is not checked.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from stakes.timeweighted import (
    IGNORANCE_REF_BRIER,
    brier_skill_score,
    scoring_window,
    standing_forecast_by_day,
    time_weighted_brier,
)


OPEN = date(2026, 1, 1)
CLOSE = date(2026, 1, 30)


def hist(*pairs):
    return [{"recorded_at": d, "confidence": c} for d, c in pairs]


class TestTheWorkedExample:
    """30-day question, resolves NO. 70% for 10 days, then 20% for 20.

        days 1-10   (0.70 - 0)^2 = 0.49   x10 = 4.9
        days 11-30  (0.20 - 0)^2 = 0.04   x20 = 0.8
        total 5.7 / 30 days                    = 0.19

    Final-answer scoring would say 0.04 and hide ten days of being wrong.
    """

    @pytest.fixture
    def scored(self):
        return time_weighted_brier(
            hist((OPEN, 0.70), (date(2026, 1, 11), 0.20)),
            opened=OPEN, close=CLOSE, resolved_at=None, resolution="incorrect",
        )

    def test_time_weighted_brier_is_the_hand_computed_value(self, scored):
        assert scored["brier"] == pytest.approx(0.19)

    def test_it_scores_every_day_of_the_window(self, scored):
        assert scored["days_scored"] == 30

    def test_final_answer_is_carried_alongside_not_instead(self, scored):
        assert scored["brier_final_answer"] == pytest.approx(0.04)

    def test_the_lateness_gap_is_the_interesting_number(self, scored):
        # 0.19 - 0.04: how much worse you were than your final answer suggests.
        assert scored["lateness_gap"] == pytest.approx(0.15)

    def test_it_differs_from_final_answer_scoring(self, scored):
        """The whole reason for this module."""
        assert scored["brier"] != pytest.approx(scored["brier_final_answer"])


class TestUpdatingIsRewarded:
    def test_early_updater_beats_late_updater_on_identical_endpoints(self):
        """Same start, same finish, different day of the move."""
        early = time_weighted_brier(
            hist((OPEN, 0.70), (date(2026, 1, 6), 0.05)),
            opened=OPEN, close=CLOSE, resolved_at=None, resolution="incorrect",
        )
        late = time_weighted_brier(
            hist((OPEN, 0.70), (date(2026, 1, 26), 0.05)),
            opened=OPEN, close=CLOSE, resolved_at=None, resolution="incorrect",
        )
        assert early["brier"] < late["brier"]
        # And final-answer scoring cannot tell them apart at all.
        assert early["brier_final_answer"] == pytest.approx(
            late["brier_final_answer"]
        )

    def test_a_never_updated_forecast_still_scores(self):
        got = time_weighted_brier(
            hist((OPEN, 0.30)),
            opened=OPEN, close=CLOSE, resolved_at=None, resolution="incorrect",
        )
        assert got["brier"] == pytest.approx(0.09)
        assert got["lateness_gap"] == pytest.approx(0.0)


class TestTheLeakSafeBoundary:
    def test_a_revision_after_close_earns_nothing(self):
        """The outcome is knowable by then. This is the anti-cheat."""
        honest = time_weighted_brier(
            hist((OPEN, 0.80)),
            opened=OPEN, close=CLOSE, resolved_at=None, resolution="incorrect",
        )
        cheat = time_weighted_brier(
            hist((OPEN, 0.80), (date(2026, 2, 15), 0.0)),
            opened=OPEN, close=CLOSE, resolved_at=None, resolution="incorrect",
        )
        assert cheat["brier"] == pytest.approx(honest["brier"])

    def test_early_resolution_stops_the_clock(self):
        """Resolved on day 10 — days 11-30 never happened."""
        got = time_weighted_brier(
            hist((OPEN, 0.60)),
            opened=OPEN, close=CLOSE,
            resolved_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            resolution="incorrect",
        )
        assert got["days_scored"] == 10

    def test_window_ends_at_the_earlier_of_close_and_resolution(self):
        assert scoring_window(OPEN, CLOSE, date(2026, 1, 9)) == (OPEN, date(2026, 1, 9))
        assert scoring_window(OPEN, date(2026, 1, 5), date(2026, 1, 20)) == (
            OPEN, date(2026, 1, 5)
        )


class TestRefusalsRatherThanZeros:
    """None means "not scored". A zero would read as a perfect score."""

    def test_unresolved_is_none(self):
        assert time_weighted_brier(
            hist((OPEN, 0.5)), opened=OPEN, close=CLOSE,
            resolved_at=None, resolution="unresolved",
        ) is None

    @pytest.mark.parametrize("resolution", ["partial", "voided", "", "unclear"])
    def test_ungradeable_outcomes_are_none_not_half(self, resolution):
        """partial-counted-never-graded — the desk's law, kept here."""
        assert time_weighted_brier(
            hist((OPEN, 0.5)), opened=OPEN, close=CLOSE,
            resolved_at=None, resolution=resolution,
        ) is None

    def test_a_forecaster_who_never_entered_a_number_is_none(self):
        assert time_weighted_brier(
            [], opened=OPEN, close=CLOSE,
            resolved_at=None, resolution="correct",
        ) is None

    def test_forecast_entirely_after_the_window_is_none(self):
        assert time_weighted_brier(
            hist((date(2026, 3, 1), 0.9)), opened=OPEN, close=CLOSE,
            resolved_at=None, resolution="correct",
        ) is None

    def test_end_before_start_is_unscoreable(self):
        assert scoring_window(CLOSE, OPEN, None) is None

    def test_missing_dates_are_unscoreable(self):
        assert scoring_window(None, CLOSE, None) is None
        assert scoring_window(OPEN, None, None) is None


class TestStandingForecast:
    def test_a_day_inherits_the_most_recent_prior_forecast(self):
        standing = standing_forecast_by_day(
            hist((OPEN, 0.2), (date(2026, 1, 3), 0.8)), (OPEN, date(2026, 1, 4)),
        )
        assert standing[date(2026, 1, 2)] == 0.2
        assert standing[date(2026, 1, 3)] == 0.8
        assert standing[date(2026, 1, 4)] == 0.8

    def test_days_before_the_first_forecast_are_absent_not_filled(self):
        standing = standing_forecast_by_day(
            hist((date(2026, 1, 3), 0.8)), (OPEN, date(2026, 1, 4)),
        )
        assert date(2026, 1, 1) not in standing
        assert date(2026, 1, 2) not in standing
        assert standing[date(2026, 1, 3)] == 0.8

    def test_last_entry_of_a_day_governs_that_day(self):
        standing = standing_forecast_by_day(
            hist((OPEN, 0.1), (OPEN, 0.9)), (OPEN, OPEN),
        )
        assert standing[OPEN] == 0.9

    def test_history_order_does_not_matter(self):
        forward = standing_forecast_by_day(
            hist((OPEN, 0.2), (date(2026, 1, 3), 0.8)), (OPEN, date(2026, 1, 4)),
        )
        backward = standing_forecast_by_day(
            hist((date(2026, 1, 3), 0.8), (OPEN, 0.2)), (OPEN, date(2026, 1, 4)),
        )
        assert forward == backward

    def test_a_forecast_predating_the_window_sets_the_opening_position(self):
        standing = standing_forecast_by_day(
            hist((date(2025, 12, 20), 0.4)), (OPEN, date(2026, 1, 2)),
        )
        assert standing[OPEN] == 0.4


class TestSkillScore:
    def test_beating_ignorance_is_positive(self):
        assert brier_skill_score(0.10, IGNORANCE_REF_BRIER) == pytest.approx(0.6)

    def test_losing_to_ignorance_is_negative(self):
        assert brier_skill_score(0.40, IGNORANCE_REF_BRIER) == pytest.approx(-0.6)

    def test_a_reference_that_cannot_discriminate_is_none_not_infinity(self):
        assert brier_skill_score(0.1, 0.0) is None
        assert brier_skill_score(0.1, None) is None
