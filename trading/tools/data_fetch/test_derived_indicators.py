"""Tests for derived_indicators.py — RSI, ATR, SMA, overlay validation."""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from derived_indicators import (
    atr_wilder,
    compute_node_indicators,
    consecutive_closes_above,
    curve_spread,
    rsi_wilder,
    sma,
    validate_derived_indicator_spec,
    _cli_compute,
)

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "derived_indicators.py")


# =========================================================================
# Wilder 1978 canonical reference sequence
# =========================================================================
# Source: J. Welles Wilder Jr., "New Concepts in Technical Trading Systems"
# (1978), RSI section. The 14-close sample series and expected RSI ~70.53
# are reproduced in every charting package. If our RSI drifts from this
# number, it drifts from TradingView and every other mainstream tool.

WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
    46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
]


class TestRSIWilder:
    def test_wilder_canonical_series(self):
        """RSI(14) on Wilder's 1978 reference series should land near 70.53."""
        rsi = rsi_wilder(WILDER_CLOSES, period=14)
        assert rsi is not None
        # Wilder's published value rounds to 70.53; allow ±0.5 to cover
        # rounding choices in intermediate divisions.
        assert 70.0 <= rsi <= 71.1, f"expected ~70.53, got {rsi}"

    def test_empty_series_returns_none(self):
        assert rsi_wilder([], period=14) is None

    def test_too_short_series_returns_none(self):
        assert rsi_wilder([100.0, 101.0, 102.0], period=14) is None

    def test_exactly_period_plus_one_computes(self):
        closes = [100.0 + i for i in range(15)]  # 15 closes = period+1
        rsi = rsi_wilder(closes, period=14)
        assert rsi is not None
        # Pure uptrend, 15 closes rising by 1 each → all gains, no losses
        assert rsi == 100.0

    def test_pure_uptrend_returns_100(self):
        closes = [100.0 + i for i in range(30)]
        assert rsi_wilder(closes, period=14) == 100.0

    def test_flat_series_avg_loss_zero_returns_100(self):
        closes = [100.0] * 30
        # All deltas are zero → gains and losses both zero → avg_loss=0 branch
        assert rsi_wilder(closes, period=14) == 100.0

    def test_pure_downtrend_returns_near_zero(self):
        closes = [200.0 - i for i in range(30)]
        rsi = rsi_wilder(closes, period=14)
        assert rsi is not None
        assert rsi < 5.0

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            rsi_wilder(WILDER_CLOSES, period=0)
        with pytest.raises(ValueError):
            rsi_wilder(WILDER_CLOSES, period=-3)

    def test_period_larger_than_series_returns_none(self):
        assert rsi_wilder(WILDER_CLOSES[:5], period=14) is None

    def test_returns_rounded_to_2_decimals(self):
        rsi = rsi_wilder(WILDER_CLOSES, period=14)
        # A float rounded to 2 decimals always satisfies round(x, 2) == x
        assert round(rsi, 2) == rsi

    def test_symmetric_movement_near_50(self):
        closes = [100.0 + (1 if i % 2 == 0 else -1) for i in range(30)]
        rsi = rsi_wilder(closes, period=14)
        assert rsi is not None
        assert 30.0 <= rsi <= 70.0

    def test_none_input_returns_none(self):
        assert rsi_wilder(None, period=14) is None  # type: ignore[arg-type]


# =========================================================================
# ATR tests
# =========================================================================

class TestATRWilder:
    def test_valid_ohlc_series_returns_positive_float(self):
        closes = [100.0 + i * 0.5 for i in range(30)]
        highs = [c + 1.2 for c in closes]
        lows = [c - 1.1 for c in closes]
        atr = atr_wilder(highs, lows, closes, period=14)
        assert atr is not None
        assert atr > 0

    def test_too_short_returns_none(self):
        highs = [102.0, 103.0, 104.0]
        lows = [100.0, 101.0, 102.0]
        closes = [101.0, 102.0, 103.0]
        assert atr_wilder(highs, lows, closes, period=14) is None

    def test_mismatched_lengths_returns_none(self):
        highs = [102.0] * 20
        lows = [100.0] * 19  # off by one
        closes = [101.0] * 20
        assert atr_wilder(highs, lows, closes, period=14) is None

    def test_empty_inputs_return_none(self):
        assert atr_wilder([], [], [], period=14) is None

    def test_flat_candles_zero_range_returns_zero(self):
        closes = [100.0] * 30
        highs = [100.0] * 30
        lows = [100.0] * 30
        assert atr_wilder(highs, lows, closes, period=14) == 0.0

    def test_gap_ups_inflate_true_range(self):
        # Regular-vol series
        closes = [100.0 + i * 0.1 for i in range(30)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        atr_normal = atr_wilder(highs, lows, closes, period=14)
        # Same thing but with a gap up between 14 and 15
        closes_gap = closes.copy()
        closes_gap[15] = closes_gap[14] + 5.0
        highs_gap = highs.copy()
        highs_gap[15] = highs_gap[14] + 5.0
        lows_gap = lows.copy()
        lows_gap[15] = lows_gap[14] + 5.0
        atr_gapped = atr_wilder(highs_gap, lows_gap, closes_gap, period=14)
        assert atr_normal is not None and atr_gapped is not None
        assert atr_gapped > atr_normal

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            atr_wilder([100.0] * 20, [99.0] * 20, [99.5] * 20, period=0)

    def test_rounded_to_2_decimals(self):
        closes = [100.0 + i * 0.5 for i in range(30)]
        highs = [c + 1.2 for c in closes]
        lows = [c - 1.1 for c in closes]
        atr = atr_wilder(highs, lows, closes, period=14)
        assert atr is not None
        assert round(atr, 2) == atr


# =========================================================================
# SMA tests
# =========================================================================

class TestSMA:
    def test_simple_average(self):
        assert sma([1.0, 2.0, 3.0, 4.0, 5.0], period=5) == 3.0

    def test_uses_only_tail_window(self):
        # period=3, only last 3 averaged
        assert sma([100.0, 200.0, 300.0, 400.0, 500.0], period=3) == 400.0

    def test_too_short_returns_none(self):
        assert sma([1.0, 2.0], period=5) is None

    def test_empty_returns_none(self):
        assert sma([], period=5) is None

    def test_exactly_period_length_works(self):
        closes = [10.0, 20.0, 30.0]
        assert sma(closes, period=3) == 20.0

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            sma([1.0, 2.0], period=0)

    def test_sma50_on_63_closes(self):
        closes = [100.0 + (i % 10) for i in range(63)]
        val = sma(closes, period=50)
        assert val is not None
        # Last 50 closes: i in 13..62, values in [0..9] cycle → avg ≈ 104.5
        assert 103.0 <= val <= 106.0


# =========================================================================
# Consecutive-closes counter
# =========================================================================

class TestConsecutiveClosesAbove:
    def test_three_consecutive_closes_above(self):
        closes = [110.0, 112.0, 114.0, 116.0, 117.0, 118.0]
        assert consecutive_closes_above(closes, 115.0) == 3

    def test_broken_run_counts_only_tail(self):
        # 116 above, 113 below, 116 again above, 117 above → only last 2 count
        closes = [116.0, 113.0, 116.0, 117.0]
        assert consecutive_closes_above(closes, 115.0) == 2

    def test_zero_when_last_close_below(self):
        closes = [116.0, 117.0, 114.0]
        assert consecutive_closes_above(closes, 115.0) == 0

    def test_all_above(self):
        closes = [116.0, 117.0, 118.0]
        assert consecutive_closes_above(closes, 115.0) == 3

    def test_empty_returns_zero(self):
        assert consecutive_closes_above([], 115.0) == 0

    def test_none_in_tail_breaks_run(self):
        closes = [116.0, None, 117.0]  # type: ignore[list-item]
        # Starting from the tail: 117 counts (+1), then None breaks → 1
        assert consecutive_closes_above(closes, 115.0) == 1  # type: ignore[arg-type]

    def test_exact_threshold_counts_as_above(self):
        # Note: we use strict < in the break check, so equal counts as above
        closes = [115.0, 115.0, 115.0]
        assert consecutive_closes_above(closes, 115.0) == 3


# =========================================================================
# Schema validation — the overlay: true tripwire
# =========================================================================

class TestValidateDerivedIndicatorSpec:
    def test_valid_rsi_spec(self):
        # Should not raise
        validate_derived_indicator_spec(
            "brent",
            {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
        )

    def test_rejects_missing_overlay(self):
        with pytest.raises(ValueError, match="overlay=true"):
            validate_derived_indicator_spec(
                "brent", {"kind": "rsi", "period": 14, "symbol": "BZ=F"}
            )

    def test_rejects_overlay_false(self):
        with pytest.raises(ValueError, match="overlay=true"):
            validate_derived_indicator_spec(
                "brent",
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": False},
            )

    def test_rejects_overlay_string_true(self):
        # MUST be the boolean True, not the string "true"
        with pytest.raises(ValueError, match="overlay=true"):
            validate_derived_indicator_spec(
                "brent",
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": "true"},
            )

    def test_rejects_unknown_kind(self):
        with pytest.raises(ValueError, match="unknown derivedIndicator kind"):
            validate_derived_indicator_spec(
                "brent",
                {"kind": "macd", "period": 14, "symbol": "BZ=F", "overlay": True},
            )

    def test_rejects_missing_symbol(self):
        with pytest.raises(ValueError, match="missing 'symbol'"):
            validate_derived_indicator_spec(
                "brent", {"kind": "rsi", "period": 14, "overlay": True}
            )

    def test_rejects_non_dict_spec(self):
        with pytest.raises(ValueError, match="must be a dict"):
            validate_derived_indicator_spec(
                "brent", "rsi14"  # type: ignore[arg-type]
            )


# =========================================================================
# compute_node_indicators
# =========================================================================

class TestComputeNodeIndicators:
    def test_computes_rsi_and_atr_and_sma(self):
        closes = [100.0 + i * 0.3 for i in range(63)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        node = {
            "id": "brent",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
                {"kind": "atr", "period": 14, "symbol": "BZ=F", "overlay": True},
                {"kind": "sma", "period": 50, "symbol": "BZ=F", "overlay": True},
            ],
        }
        ohlcv = {"BZ=F": {"closes": closes, "highs": highs, "lows": lows}}
        result = compute_node_indicators(node, ohlcv)
        assert "rsi14" in result
        assert "atr14" in result
        assert "sma50" in result
        assert isinstance(result["rsi14"], float)
        assert isinstance(result["atr14"], float)
        assert isinstance(result["sma50"], float)

    def test_empty_node_indicators_returns_empty_dict(self):
        node = {"id": "diesel"}
        assert compute_node_indicators(node, {"ANY": {"closes": [1, 2, 3]}}) == {}

    def test_missing_ohlcv_skips_indicator(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
            ],
        }
        # Empty ohlcv — symbol not found
        assert compute_node_indicators(node, {}) == {}

    def test_empty_closes_skips_indicator(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
            ],
        }
        ohlcv = {"BZ=F": {"closes": []}}
        assert compute_node_indicators(node, ohlcv) == {}

    def test_atr_skipped_when_highs_lows_missing(self):
        # Closes present but no highs/lows → RSI works, ATR doesn't
        closes = [100.0 + i * 0.3 for i in range(63)]
        node = {
            "id": "brent",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
                {"kind": "atr", "period": 14, "symbol": "BZ=F", "overlay": True},
            ],
        }
        ohlcv = {"BZ=F": {"closes": closes}}
        result = compute_node_indicators(node, ohlcv)
        assert "rsi14" in result
        assert "atr14" not in result

    def test_raises_on_spec_missing_overlay(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                # overlay flag omitted → should raise at validation time
                {"kind": "rsi", "period": 14, "symbol": "BZ=F"},
            ],
        }
        with pytest.raises(ValueError, match="overlay=true"):
            compute_node_indicators(node, {"BZ=F": {"closes": [1.0] * 30}})

    def test_does_not_mutate_input_node(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
            ],
        }
        closes = [100.0 + (i % 5) for i in range(30)]
        ohlcv = {"BZ=F": {"closes": closes}}
        before = json.dumps(node, sort_keys=True)
        _ = compute_node_indicators(node, ohlcv)
        after = json.dumps(node, sort_keys=True)
        assert before == after

    def test_does_not_mutate_input_ohlcv(self):
        closes = [100.0 + (i % 5) for i in range(30)]
        ohlcv = {"BZ=F": {"closes": closes.copy()}}
        before = json.dumps(ohlcv, sort_keys=True)
        node = {
            "id": "brent",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
            ],
        }
        _ = compute_node_indicators(node, ohlcv)
        after = json.dumps(ohlcv, sort_keys=True)
        assert before == after

    def test_multiple_symbols_per_node(self):
        closes_a = [100.0 + i * 0.3 for i in range(63)]
        closes_b = [50.0 + i * 0.2 for i in range(63)]
        node = {
            "id": "food-spike",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "ZW=F", "overlay": True},
                {"kind": "rsi", "period": 14, "symbol": "ZC=F", "overlay": True},
            ],
        }
        ohlcv = {
            "ZW=F": {"closes": closes_a},
            "ZC=F": {"closes": closes_b},
        }
        # Both RSI values write to the same key "rsi14" → second overwrites
        # the first. This is expected behavior — callers who want per-symbol
        # keys should compute via separate nodes or use kind-unique periods.
        result = compute_node_indicators(node, ohlcv)
        assert "rsi14" in result

    def test_specs_not_a_list_returns_empty(self):
        node = {
            "id": "brent",
            "derivedIndicators": "not-a-list",  # malformed but shouldn't crash
        }
        assert compute_node_indicators(node, {}) == {}


# =========================================================================
# CLI
# =========================================================================

class TestCLI:
    def test_cli_compute_pure_function(self):
        closes = [100.0 + i * 0.3 for i in range(63)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        result = _cli_compute(
            {
                "closes": closes,
                "highs": highs,
                "lows": lows,
                "threshold": 110.0,
            },
            period=14,
        )
        assert "rsi14" in result
        assert "atr14" in result
        assert "sma50" in result
        assert "consecutiveAbove" in result
        assert result["consecutiveAbove"] >= 0

    def test_cli_stdin_roundtrip(self):
        payload = {
            "closes": [100.0 + (i % 5) for i in range(30)],
        }
        proc = subprocess.run(
            [sys.executable, SCRIPT_PATH, "--period", "14"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert "rsi14" in result
        assert "sma50" in result

    def test_cli_malformed_json_exits_2(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT_PATH],
            input="not json at all",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2
        assert "invalid JSON" in proc.stderr

    def test_cli_non_object_exits_2(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT_PATH],
            input="[1, 2, 3]",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2

    def test_cli_empty_payload_returns_nulls(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT_PATH],
            input="{}",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        assert result["rsi14"] is None
        assert result["sma50"] is None

    def test_cli_omits_atr_when_no_highs_lows(self):
        payload = {"closes": [100.0 + (i % 5) for i in range(30)]}
        result = _cli_compute(payload, period=14)
        assert "atr14" not in result

    def test_cli_threshold_produces_consecutive(self):
        payload = {
            "closes": [114.0, 115.0, 116.0, 117.0, 118.0],
            "threshold": 115.0,
        }
        result = _cli_compute(payload, period=14)
        # Last 4 closes (115..118) all >= 115 → count 4
        assert result["consecutiveAbove"] == 4


# =========================================================================
# Curve spread (futures term-structure) tests
# =========================================================================

class TestCurveSpread:
    def test_backwardation_front_above_back(self):
        # Front $70.50, back $69.00 → spread +$1.50 → backwardation.
        # A richer front month vs further-out contracts is the classic
        # supply-stress signature in oil.
        front = [68.0, 69.0, 70.0, 70.50]
        back = [67.8, 68.5, 68.9, 69.00]
        result = curve_spread(front, back)
        assert result is not None
        assert result["shape"] == "backwardation"
        assert result["spread"] == 1.50
        assert result["front"] == 70.50
        assert result["back"] == 69.00

    def test_contango_back_above_front(self):
        # Front $68.00, back $70.20 → spread -$2.20 → contango.
        front = [66.0, 67.0, 67.5, 68.00]
        back = [69.0, 69.5, 70.0, 70.20]
        result = curve_spread(front, back)
        assert result is not None
        assert result["shape"] == "contango"
        assert result["spread"] == -2.20

    def test_flat_spread_within_default_band(self):
        # Spread of $0.05 — below the $0.10 flat-band default → "flat".
        front = [69.90, 70.00, 70.05]
        back = [70.10, 70.05, 70.00]
        result = curve_spread(front, back)
        assert result is not None
        assert result["shape"] == "flat"
        assert abs(result["spread"]) <= 0.10

    def test_flat_band_custom_threshold(self):
        # With flat_band=2.00, a +$1.50 spread falls inside "flat".
        front = [68.0, 69.0, 70.50]
        back = [67.8, 68.5, 69.00]
        result = curve_spread(front, back, flat_band=2.00)
        assert result is not None
        assert result["shape"] == "flat"

    def test_missing_front_returns_none(self):
        assert curve_spread([], [70.0, 71.0]) is None

    def test_missing_back_returns_none(self):
        assert curve_spread([70.0, 71.0], []) is None

    def test_both_empty_returns_none(self):
        assert curve_spread([], []) is None

    def test_trailing_none_returns_none(self):
        # Defensive: if the last close is None, bail rather than crash.
        assert curve_spread([70.0, None], [69.0, 69.5]) is None  # type: ignore[list-item]
        assert curve_spread([70.0, 71.0], [69.0, None]) is None  # type: ignore[list-item]

    def test_only_last_close_used(self):
        # Earlier history is ignored — we report today's spread, not a mean.
        front = [50.0, 60.0, 70.0]
        back = [100.0, 80.0, 69.0]
        result = curve_spread(front, back)
        assert result is not None
        assert result["spread"] == 1.00
        assert result["front"] == 70.0
        assert result["back"] == 69.0

    def test_negative_flat_band_raises(self):
        with pytest.raises(ValueError, match="flat_band"):
            curve_spread([70.0], [69.0], flat_band=-0.5)

    def test_exact_flat_band_boundary_is_flat(self):
        # Spread exactly equal to flat_band (0.10) → flat (inclusive boundary)
        result = curve_spread([70.10], [70.00])
        assert result is not None
        assert result["shape"] == "flat"

    def test_rounding_to_2_decimals(self):
        front = [70.12345]
        back = [69.11111]
        result = curve_spread(front, back)
        assert result is not None
        assert result["spread"] == round(result["spread"], 2) == 1.01
        assert result["front"] == 70.12
        assert result["back"] == 69.11


class TestCurveSpreadIntegration:
    """End-to-end: curveSpread flows through compute_node_indicators into
    the node's tvIndicators overlay, preserving the overlay=true tripwire."""

    def test_curve_spread_writes_to_tv_indicators(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                {
                    "kind": "curveSpread",
                    "frontSymbol": "CL=F",
                    "backSymbol": "CLZ26.NYM",
                    "overlay": True,
                },
            ],
        }
        ohlcv = {
            "CL=F": {"closes": [68.0, 69.0, 70.50]},
            "CLZ26.NYM": {"closes": [67.5, 68.0, 69.00]},
        }
        result = compute_node_indicators(node, ohlcv)
        assert "curveSpread" in result
        assert result["curveSpread"]["shape"] == "backwardation"
        assert result["curveSpread"]["spread"] == 1.50

    def test_curve_spread_contango_integration(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                {
                    "kind": "curveSpread",
                    "frontSymbol": "CL=F",
                    "backSymbol": "CLZ26.NYM",
                    "overlay": True,
                },
            ],
        }
        ohlcv = {
            "CL=F": {"closes": [68.00]},
            "CLZ26.NYM": {"closes": [70.20]},
        }
        result = compute_node_indicators(node, ohlcv)
        assert result["curveSpread"]["shape"] == "contango"

    def test_missing_front_ohlcv_skips(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                {
                    "kind": "curveSpread",
                    "frontSymbol": "CL=F",
                    "backSymbol": "CLZ26.NYM",
                    "overlay": True,
                },
            ],
        }
        # Back present, front missing — should not half-write.
        ohlcv = {"CLZ26.NYM": {"closes": [69.0]}}
        assert compute_node_indicators(node, ohlcv) == {}

    def test_missing_back_ohlcv_skips(self):
        node = {
            "id": "brent",
            "derivedIndicators": [
                {
                    "kind": "curveSpread",
                    "frontSymbol": "CL=F",
                    "backSymbol": "CLZ26.NYM",
                    "overlay": True,
                },
            ],
        }
        ohlcv = {"CL=F": {"closes": [70.0]}}
        assert compute_node_indicators(node, ohlcv) == {}

    def test_curve_spread_rejects_missing_overlay(self):
        """Schema tripwire: curveSpread without overlay=true MUST raise.
        This is what keeps derived values from ever feeding eval_node_state
        or score_confluence — the architectural guarantee from the plan."""
        with pytest.raises(ValueError, match="overlay=true"):
            validate_derived_indicator_spec(
                "brent",
                {
                    "kind": "curveSpread",
                    "frontSymbol": "CL=F",
                    "backSymbol": "CLZ26.NYM",
                },
            )

    def test_curve_spread_rejects_missing_front_symbol(self):
        with pytest.raises(ValueError, match="frontSymbol"):
            validate_derived_indicator_spec(
                "brent",
                {"kind": "curveSpread", "backSymbol": "CLZ26.NYM", "overlay": True},
            )

    def test_curve_spread_rejects_missing_back_symbol(self):
        with pytest.raises(ValueError, match="backSymbol"):
            validate_derived_indicator_spec(
                "brent",
                {"kind": "curveSpread", "frontSymbol": "CL=F", "overlay": True},
            )

    def test_curve_spread_coexists_with_rsi(self):
        # Both a single-symbol (RSI) spec and a curveSpread spec on the same
        # node — both should land in the output dict without clobbering.
        closes = [100.0 + (i % 5) for i in range(30)]
        node = {
            "id": "brent",
            "derivedIndicators": [
                {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": True},
                {
                    "kind": "curveSpread",
                    "frontSymbol": "CL=F",
                    "backSymbol": "CLZ26.NYM",
                    "overlay": True,
                },
            ],
        }
        ohlcv = {
            "BZ=F": {"closes": closes},
            "CL=F": {"closes": [70.50]},
            "CLZ26.NYM": {"closes": [69.00]},
        }
        result = compute_node_indicators(node, ohlcv)
        assert "rsi14" in result
        assert "curveSpread" in result
        assert result["curveSpread"]["shape"] == "backwardation"

    def test_curve_spread_does_not_leak_into_causal_keys(self):
        """Belt-and-suspenders: the output key for curveSpread is a dict, not
        a scalar, so even if downstream glue code grabs `node.tvIndicators`
        and tries to read a numeric threshold from it, curveSpread cannot
        be mistaken for an eval_node_state input like `current` or
        `probability`. Verify the shape explicitly."""
        node = {
            "id": "brent",
            "derivedIndicators": [
                {
                    "kind": "curveSpread",
                    "frontSymbol": "CL=F",
                    "backSymbol": "CLZ26.NYM",
                    "overlay": True,
                },
            ],
        }
        ohlcv = {
            "CL=F": {"closes": [70.50]},
            "CLZ26.NYM": {"closes": [69.00]},
        }
        result = compute_node_indicators(node, ohlcv)
        assert isinstance(result["curveSpread"], dict)
        # Must carry the shape label — not just a raw number.
        assert "shape" in result["curveSpread"]
        # And the spec itself MUST have been validated with overlay=true
        # (any violation would have raised before we got here).
        assert node["derivedIndicators"][0]["overlay"] is True
