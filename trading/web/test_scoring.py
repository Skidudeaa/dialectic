"""
Scoring math tests — every expected value is HAND-COMPUTED, never copied
from the function under test, so a wrong formula cannot certify itself.

Worked examples used throughout:
  brier(0.8, 1.0) = (0.8 - 1.0)^2 = 0.04
  brier(0.6, 0.0) = 0.36
  ignorance reference = 0.25 (the Brier of a flat 0.5 forecast)
  bss(0.04, 0.25) = 1 - 0.04/0.25 = 0.84
  bss(0.04, 0.16) = 1 - 0.04/0.16 = 0.75   (ref = brier(base_rate 0.6, correct))
"""

import pytest

from web import scoring


def _row(
    *,
    confidence=0.8,
    resolution="correct",
    resolved_at="2026-02-01T00:00:00+00:00",
    history=None,
    base_rate=None,
    base_rate_source=None,
    source_label="amo",
    tags=None,
    created_at="2026-01-01T00:00:00+00:00",
    deadline="2026-01-05",
):
    """A prediction dict in the list_predictions shape. Default history is
    the single creation-time seed row, matching what the migration and
    save_prediction_once produce."""
    if history is None:
        history = [{
            "actor": source_label,
            "confidence": confidence,
            "reasoning": None,
            "recorded_at": created_at,
        }]
    return {
        "id": "p1",
        "user": "amo",
        "statement": "test claim",
        "confidence": confidence,
        "deadline": deadline,
        "resolution": resolution,
        "resolved_at": resolved_at,
        "resolution_notes": None,
        "resolution_spec": None,
        "linked_book_id": None,
        "tags": list(tags) if tags else [],
        "source_type": "human",
        "source_label": source_label,
        "source_ref": None,
        "base_rate": base_rate,
        "base_rate_source": base_rate_source,
        "confidence_history": history,
        "created_at": created_at,
    }


# ═══════════════════════════════════════════════════════════════════════
# OUTCOME + BRIER PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════

class TestPrimitives:
    def test_outcome_values(self):
        assert scoring.outcome_value("correct") == 1.0
        assert scoring.outcome_value("partial") == 0.5
        assert scoring.outcome_value("incorrect") == 0.0

    def test_voided_and_unresolved_score_nowhere(self):
        assert scoring.outcome_value("voided") is None
        assert scoring.outcome_value(None) is None

    def test_brier_hand_computed(self):
        assert scoring.brier(0.8, 1.0) == pytest.approx(0.04)
        assert scoring.brier(0.6, 0.0) == pytest.approx(0.36)
        assert scoring.brier(0.5, 0.5) == 0.0

    def test_bss_vs_ignorance(self):
        assert scoring.brier_skill_score(0.04, 0.25) == pytest.approx(0.84)

    def test_bss_vs_market_reference(self):
        # ref = brier(base_rate 0.6, outcome 1.0) = 0.16
        assert scoring.brier_skill_score(0.04, 0.16) == pytest.approx(0.75)

    def test_bss_worse_than_reference_is_negative(self):
        assert scoring.brier_skill_score(0.5, 0.25) == pytest.approx(-1.0)

    def test_bss_perfect_reference_guarded(self):
        assert scoring.brier_skill_score(0.04, 0.0) is None


# ═══════════════════════════════════════════════════════════════════════
# LAST-PRE-RESOLUTION CONFIDENCE (the dialectic stakes rule)
# ═══════════════════════════════════════════════════════════════════════

class TestScoringConfidence:
    def test_last_row_at_or_before_resolved_at_wins(self):
        row = _row(
            confidence=0.9,  # current column must NOT be what scores
            resolved_at="2026-03-01T00:00:00+00:00",
            history=[
                {"confidence": 0.9, "recorded_at": "2026-03-02T00:00:00+00:00"},
                {"confidence": 0.6, "recorded_at": "2026-02-15T00:00:00+00:00"},
                {"confidence": 0.8, "recorded_at": "2026-01-01T00:00:00+00:00"},
            ],
        )
        assert scoring.scoring_confidence(row) == 0.6

    def test_history_order_does_not_matter(self):
        row = _row(
            resolved_at="2026-03-01T00:00:00+00:00",
            history=[
                {"confidence": 0.8, "recorded_at": "2026-01-01T00:00:00+00:00"},
                {"confidence": 0.9, "recorded_at": "2026-03-02T00:00:00+00:00"},
                {"confidence": 0.6, "recorded_at": "2026-02-15T00:00:00+00:00"},
            ],
        )
        assert scoring.scoring_confidence(row) == 0.6

    def test_row_exactly_at_resolved_at_qualifies(self):
        row = _row(
            resolved_at="2026-02-15T00:00:00+00:00",
            history=[{"confidence": 0.7, "recorded_at": "2026-02-15T00:00:00+00:00"}],
        )
        assert scoring.scoring_confidence(row) == 0.7

    def test_unresolved_row_is_none(self):
        assert scoring.scoring_confidence(_row(resolution=None, resolved_at=None)) is None

    def test_no_qualifying_history_excluded_not_guessed(self):
        row = _row(
            resolved_at="2026-01-01T00:00:00+00:00",
            history=[{"confidence": 0.9, "recorded_at": "2026-02-01T00:00:00+00:00"}],
        )
        assert scoring.scoring_confidence(row) is None

    def test_scored_uses_history_not_current_column(self):
        # Post-resolution belief update must not change the grade: the
        # 0.6 held at resolution scores, not the 0.9 written after.
        row = _row(
            confidence=0.9,
            resolution="incorrect",
            resolved_at="2026-03-01T00:00:00+00:00",
            history=[
                {"confidence": 0.9, "recorded_at": "2026-03-05T00:00:00+00:00"},
                {"confidence": 0.6, "recorded_at": "2026-02-01T00:00:00+00:00"},
            ],
        )
        [group] = scoring.leaderboard([row])
        assert group["brier"] == pytest.approx(0.36)  # (0.6 - 0.0)^2


# ═══════════════════════════════════════════════════════════════════════
# LEADERBOARD
# ═══════════════════════════════════════════════════════════════════════

class TestLeaderboard:
    def test_group_stats_hand_computed_vs_ignorance(self):
        rows = [
            _row(confidence=0.8, resolution="correct"),    # brier 0.04, bias -0.2
            _row(confidence=0.6, resolution="incorrect"),  # brier 0.36, bias +0.6
        ]
        [group] = scoring.leaderboard(rows)
        assert group["group"] == "amo"
        assert group["n"] == 2
        assert group["brier"] == pytest.approx(0.20)
        assert group["bss"] == pytest.approx(1 - 0.20 / 0.25)  # 0.2
        assert group["bss_vs"] == "ignorance"
        assert group["accuracy"] == pytest.approx(0.5)
        assert group["bias"] == pytest.approx(0.2)
        assert group["provenance"] == "UNVERIFIED_INSUFFICIENT_SAMPLES"

    def test_market_reference_flagged(self):
        rows = [_row(confidence=0.8, resolution="correct",
                     base_rate=0.6, base_rate_source="polymarket",
                     source_label="capex-insider")]
        [group] = scoring.leaderboard(rows)
        assert group["brier"] == pytest.approx(0.04)
        assert group["bss"] == pytest.approx(0.75)  # ref = (0.6-1)^2 = 0.16
        assert group["bss_vs"] == "market"

    def test_perfect_reference_guard_survives_aggregation(self):
        rows = [_row(confidence=0.8, resolution="correct", base_rate=1.0)]
        [group] = scoring.leaderboard(rows)
        assert group["bss"] is None
        assert group["bss_vs"] == "market"

    def test_voided_rows_are_excluded(self):
        rows = [
            _row(confidence=0.8, resolution="correct"),
            _row(confidence=0.9, resolution="voided"),
        ]
        [group] = scoring.leaderboard(rows)
        assert group["n"] == 1

    def test_group_of_only_voided_rows_is_absent(self):
        assert scoring.leaderboard([_row(resolution="voided")]) == []

    def test_signed_bias_positive_means_overconfident(self):
        [group] = scoring.leaderboard([_row(confidence=0.8, resolution="incorrect")])
        assert group["bias"] == pytest.approx(0.8)
        [group] = scoring.leaderboard([_row(confidence=0.3, resolution="correct")])
        assert group["bias"] == pytest.approx(-0.7)

    def test_partial_outcome_half_credit(self):
        [group] = scoring.leaderboard([_row(confidence=0.7, resolution="partial")])
        assert group["accuracy"] == pytest.approx(0.5)
        assert group["brier"] == pytest.approx(0.04)  # (0.7 - 0.5)^2

    def test_empirical_provenance_at_exactly_ten(self):
        def rows(n):
            return [_row(confidence=0.7, resolution="correct") for _ in range(n)]
        [nine] = scoring.leaderboard(rows(9))
        assert nine["provenance"] == "UNVERIFIED_INSUFFICIENT_SAMPLES"
        [ten] = scoring.leaderboard(rows(10))
        assert ten["provenance"] == "EMPIRICAL"

    def test_best_brier_sorts_first(self):
        rows = [
            _row(confidence=0.6, resolution="incorrect", source_label="dan"),   # 0.36
            _row(confidence=0.8, resolution="correct", source_label="amo"),     # 0.04
        ]
        groups = scoring.leaderboard(rows)
        assert [g["group"] for g in groups] == ["amo", "dan"]

    def test_tag_split_multi_membership_and_untagged(self):
        rows = [
            _row(confidence=0.8, resolution="correct", tags=["oil", "gold"]),
            _row(confidence=0.6, resolution="incorrect"),
        ]
        groups = {g["group"]: g for g in scoring.leaderboard(rows, split_by="tag")}
        assert set(groups) == {"oil", "gold", "untagged"}
        assert groups["oil"]["n"] == 1
        assert groups["gold"]["brier"] == pytest.approx(0.04)
        assert groups["untagged"]["brier"] == pytest.approx(0.36)

    def test_horizon_split_buckets(self):
        created = "2026-01-01T00:00:00+00:00"
        rows = [
            _row(created_at=created, deadline="2026-01-05"),  # 4d
            _row(created_at=created, deadline="2026-01-21"),  # 20d
            _row(created_at=created, deadline="2026-03-01"),  # 59d
            _row(created_at=created, deadline="2026-12-01"),  # 334d
        ]
        groups = {g["group"] for g in scoring.leaderboard(rows, split_by="horizon")}
        assert groups == {"<=7d", "<=30d", "<=90d", ">90d"}

    def test_unlabeled_source_bucket(self):
        [group] = scoring.leaderboard([_row(source_label=None)])
        assert group["group"] == "unlabeled"

    def test_invalid_split_raises(self):
        with pytest.raises(ValueError):
            scoring.leaderboard([_row()], split_by="direction")

    def test_empty_rows_empty_leaderboard(self):
        assert scoring.leaderboard([]) == []


# ═══════════════════════════════════════════════════════════════════════
# CALIBRATION BUCKETS
# ═══════════════════════════════════════════════════════════════════════

class TestCalibrationBuckets:
    def test_empty_is_nulls_not_crashes(self):
        result = scoring.calibration_buckets([])
        assert result["total_predictions"] == 0
        assert result["total_correct"] == 0
        assert result["brier_score"] is None
        assert len(result["calibration"]) == 10
        assert all(b["total"] == 0 and b["accuracy"] is None
                   for b in result["calibration"])

    def test_bucket_boundaries(self):
        rows = [
            _row(confidence=0.05, resolution="correct"),
            _row(confidence=0.1, resolution="correct"),   # lands in 0.1-0.2
            _row(confidence=1.0, resolution="correct"),   # clamped into 0.9-1.0
        ]
        result = scoring.calibration_buckets(rows)
        by_label = {b["bucket"]: b for b in result["calibration"]}
        assert by_label["0.0-0.1"]["total"] == 1
        assert by_label["0.1-0.2"]["total"] == 1
        assert by_label["0.9-1.0"]["total"] == 1

    def test_headline_stats_hand_computed(self):
        rows = [
            _row(confidence=0.8, resolution="correct"),    # brier 0.04
            _row(confidence=0.6, resolution="incorrect"),  # brier 0.36
        ]
        result = scoring.calibration_buckets(rows)
        assert result["total_predictions"] == 2
        assert result["total_correct"] == pytest.approx(1.0)
        assert result["brier_score"] == pytest.approx(0.20)

    def test_partial_counts_half_correct(self):
        result = scoring.calibration_buckets([_row(confidence=0.75, resolution="partial")])
        bucket = {b["bucket"]: b for b in result["calibration"]}["0.7-0.8"]
        assert bucket["total"] == 1
        assert bucket["correct"] == pytest.approx(0.5)
        assert bucket["accuracy"] == pytest.approx(0.5)

    def test_voided_and_unresolved_excluded(self):
        rows = [
            _row(resolution="voided"),
            _row(resolution=None, resolved_at=None),
            _row(confidence=0.8, resolution="correct"),
        ]
        assert scoring.calibration_buckets(rows)["total_predictions"] == 1

    def test_bucket_shape_matches_dialectic_scorer(self):
        # The Ledger frontend renders both scorers with one component —
        # pin the per-bucket keys and midpoint convention.
        [first, *_] = scoring.calibration_buckets([])["calibration"]
        assert set(first) == {"bucket", "midpoint", "total", "correct", "accuracy"}
        assert first["bucket"] == "0.0-0.1"
        assert first["midpoint"] == pytest.approx(0.05)
