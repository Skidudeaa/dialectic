#!/usr/bin/env python3
"""Derived technical indicators — RSI, ATR, SMA — computed from OHLCV series.

WHY this exists
---------------
TradingView's Scanner/Screener API requires session-cookie authentication and
returns 403 from datacenter IPs (verified 2026-04 via the tradingview-screener
project README). Rather than rotate cookies or run a headless browser, we
compute the indicators we actually need (RSI, ATR, SMA) in-process from the
same Yahoo Finance OHLCV series the thesis-graph engine already has.

WHY these values are NON-CAUSAL
-------------------------------
RSI is derived FROM price. Feeding RSI back into `eval_node_state()` as if it
were a second cause would be reading the same thermometer twice — a category
error red-teamed in the Alpha plan competition (see .planning/tv-plan/
red-team-alpha.md finding F3). Therefore every entry in `node.derivedIndicators`
MUST carry `overlay: true`. The loader rejects specs without it. This is a
schema-enforced tripwire against anyone reopening the "let RSI cause things"
door in the future.

The ONE exception is `closesObserved`: when we see N consecutive Yahoo closes
above a threshold that has `closesRequired` set, we increment the counter that
the ALREADY-EXISTING `closesRequired` gate at `thesisgraph.py:201` was
designed to consume. We don't add new state-transition logic — we provide the
data the existing logic was waiting for.

Conventions
-----------
- Stdlib only. Zero pip deps. Uses `sys`, `json`, `argparse`.
- Pure functions: no I/O, no network, no mutation of inputs (except the
  single `compute_node_indicators` helper that builds and returns a new
  dict).
- Returns `None` when input is insufficient instead of raising.
- All public functions carry type hints.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable


# =========================================================================
# CORE MATH — Wilder's 1978 reference implementations
# =========================================================================

def rsi_wilder(closes: list[float], period: int = 14) -> float | None:
    """Wilder's Relative Strength Index.

    WHY Wilder smoothing vs plain moving average: Wilder's original 1978
    paper defines RSI using an exponential-like smoothing that gives older
    observations decreasing but never-zero weight. This matches how every
    mainstream charting platform (TradingView included) renders RSI.
    Using a simple rolling mean would drift from what the operator sees on
    their chart.

    Algorithm:
        gains[i] = max(closes[i] - closes[i-1], 0)
        losses[i] = max(closes[i-1] - closes[i], 0)
        avg_gain[period-1] = mean(gains[:period])
        avg_loss[period-1] = mean(losses[:period])
        avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i]) / period
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

    Returns None when `closes` has fewer than `period + 1` usable entries.
    Returns 100.0 when the avg loss is zero (pure uptrend — canonical
    handling).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if closes is None or len(closes) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def atr_wilder(highs: list[float], lows: list[float],
               closes: list[float], period: int = 14) -> float | None:
    """Wilder's Average True Range.

    True Range at bar i is max of:
        high[i] - low[i]
        abs(high[i] - close[i-1])
        abs(low[i] - close[i-1])

    Then Wilder smoothing over `period` bars (same algorithm as RSI).

    Returns None when any of the three series has fewer than `period + 1`
    entries, or when the lists are not the same length. Caller is expected
    to have stripped `None` entries before passing the arrays in.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if not highs or not lows or not closes:
        return None
    n = len(closes)
    if len(highs) != n or len(lows) != n:
        return None
    if n < period + 1:
        return None

    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return round(atr, 2)


def sma(closes: list[float], period: int) -> float | None:
    """Simple moving average of the last `period` closes.

    Returns None when fewer than `period` closes are available.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if closes is None or len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def curve_spread(front_closes: list[float], back_closes: list[float],
                 flat_band: float = 0.10) -> dict | None:
    """Front-month minus back-month futures spread — a structural curve-shape
    signal (backwardation vs contango).

    WHY this is non-causal: like RSI/ATR, the spread is derived FROM the same
    futures prices the thesis already watches. Feeding it into
    eval_node_state() would be reading the same thermometer twice. The
    `overlay: true` tripwire on every derivedIndicators spec keeps this
    architectural — curve values live in the tvIndicators overlay block and
    never cross into propagate() or score_confluence().

    WHY "flat" band: paper-thin spreads (|spread| < $0.10 by default) aren't
    meaningful curve signals — they're noise. Bucket those as "flat" rather
    than forcing them into backwardation/contango.

    Arguments:
        front_closes: daily close series for the front-month contract
                      (e.g. CL=F). Must have at least one entry; only the
                      last value is used (spot spread today, not a history).
        back_closes:  daily close series for the back-month contract
                      (e.g. CLZ26.NYM). Same contract, different expiry.
        flat_band:    absolute spread magnitude treated as flat, in the same
                      units as the contracts (USD for oil).

    Returns:
        None when either series is empty (missing data → no overlay written).
        Otherwise a dict:
            {"spread": 1.23, "shape": "backwardation",
             "front": 70.50, "back": 69.27}
        where shape ∈ {"backwardation", "contango", "flat"}:
            spread >  flat_band → "backwardation" (front richer than back)
            spread < -flat_band → "contango"      (back richer than front)
            |spread| <= flat_band → "flat"
        All numeric values rounded to 2 decimals.
    """
    if flat_band < 0:
        raise ValueError("flat_band must be non-negative")
    if not front_closes or not back_closes:
        return None
    front = front_closes[-1]
    back = back_closes[-1]
    if front is None or back is None:
        return None
    spread = float(front) - float(back)
    if spread > flat_band:
        shape = "backwardation"
    elif spread < -flat_band:
        shape = "contango"
    else:
        shape = "flat"
    return {
        "spread": round(spread, 2),
        "shape": shape,
        "front": round(float(front), 2),
        "back": round(float(back), 2),
    }


def consecutive_closes_above(closes: list[float], threshold: float) -> int:
    """Count how many of the most recent closes sit above `threshold`,
    counting only the contiguous tail run (stops at first close below).

    WHY contiguous tail: this matches the semantics of `closesRequired` in
    the engine. `closesRequired=3` means THREE CONSECUTIVE daily closes
    above the level — not three closes anywhere in the history window. A
    close that breaks below the level resets the streak.

    Returns 0 on empty input or when the final close is below threshold.
    Treats None entries in the tail as "break" (defensive — upstream should
    already strip Nones, but we don't crash).
    """
    if not closes:
        return 0
    count = 0
    for close in reversed(closes):
        if close is None or close < threshold:
            break
        count += 1
    return count


# =========================================================================
# NODE-LEVEL COMPUTATION
# =========================================================================

def validate_derived_indicator_spec(node_id: str, spec: dict) -> None:
    """Raise ValueError if the spec is missing the overlay=true tripwire
    or carries an unknown `kind`.

    This is the schema-enforced guard against re-introducing RSI-as-cause.
    Called from `compute_node_indicators` before any computation runs.
    """
    if not isinstance(spec, dict):
        raise ValueError(
            f"node {node_id}: derivedIndicators entry must be a dict, got "
            f"{type(spec).__name__}"
        )
    if spec.get("overlay") is not True:
        raise ValueError(
            f"node {node_id}: derivedIndicators entry without overlay=true "
            f"is rejected. Derived indicators are NON-CAUSAL snapshot "
            f"overlays only — they must never feed eval_node_state() or "
            f"score_confluence(). If you want to encode technical judgement "
            f"as a cause, add a real node with its own feeds and edges."
        )
    kind = spec.get("kind")
    if kind not in ("rsi", "atr", "sma", "curveSpread"):
        raise ValueError(
            f"node {node_id}: unknown derivedIndicator kind {kind!r}. "
            f"Supported: rsi, atr, sma, curveSpread."
        )
    if kind == "curveSpread":
        # Curve spread is a two-symbol spec — front month minus back month.
        # It does NOT carry a single 'symbol' field; requiring both front
        # and back explicitly is how we prevent silent half-configs.
        for required in ("frontSymbol", "backSymbol"):
            if required not in spec:
                raise ValueError(
                    f"node {node_id}: curveSpread derivedIndicator missing "
                    f"{required!r}"
                )
    else:
        if "symbol" not in spec:
            raise ValueError(
                f"node {node_id}: derivedIndicators entry missing 'symbol'"
            )


def compute_node_indicators(node: dict, ohlcv: dict) -> dict:
    """Compute all `derivedIndicators` specs on a single node.

    Arguments:
        node: a node dict from cfg["nodes"]. Reads `node["derivedIndicators"]`
              (a list of spec dicts, each with overlay=true, kind, symbol,
              period).
        ohlcv: the transient cfg["_ohlcv"] dict, shape:
               {symbol: {"closes": [...], "highs": [...], "lows": [...]}}.
               Entries may be partial — if highs/lows are missing, ATR is
               skipped for that symbol.

    Returns a dict of computed values suitable for writing into
    `node["tvIndicators"]`. Does NOT mutate the input node or ohlcv dict.
    Empty dict when the node has no derivedIndicators or all symbols are
    missing from the ohlcv stash.
    """
    out: dict = {}
    specs = node.get("derivedIndicators", [])
    if not isinstance(specs, list) or not specs:
        return out

    node_id = node.get("id", "?")
    for spec in specs:
        validate_derived_indicator_spec(node_id, spec)
        kind = spec["kind"]

        # curveSpread has a different shape from the single-symbol indicators.
        # Handle it first and `continue` so the rest of the branch can assume
        # `spec["symbol"]` exists.
        if kind == "curveSpread":
            front_symbol = spec["frontSymbol"]
            back_symbol = spec["backSymbol"]
            front_series = ohlcv.get(front_symbol, {})
            back_series = ohlcv.get(back_symbol, {})
            front_closes = front_series.get("closes") or []
            back_closes = back_series.get("closes") or []
            if not front_closes or not back_closes:
                # Missing data on either leg → skip, don't half-write.
                continue
            flat_band = float(spec.get("flatBand", 0.10))
            result = curve_spread(front_closes, back_closes, flat_band=flat_band)
            if result is not None:
                out["curveSpread"] = result
            continue

        symbol = spec["symbol"]
        series = ohlcv.get(symbol, {})
        closes = series.get("closes") or []
        if not closes:
            continue

        period = int(spec.get("period", 14))
        value: float | None = None
        key = f"{kind}{period}"

        if kind == "rsi":
            value = rsi_wilder(closes, period)
        elif kind == "atr":
            highs = series.get("highs") or []
            lows = series.get("lows") or []
            if highs and lows:
                value = atr_wilder(highs, lows, closes, period)
        elif kind == "sma":
            value = sma(closes, period)

        if value is not None:
            out[key] = value

    return out


# =========================================================================
# CLI — ad-hoc testing against a JSON stdin payload
# =========================================================================

def _cli_compute(series_payload: dict, period: int = 14) -> dict:
    """Run all three indicators + consecutive-closes on a series payload.

    Input shape:
        {"closes": [...], "highs": [...], "lows": [...], "threshold": 115.0}

    Output shape:
        {"rsi14": 64.3, "atr14": 3.21, "sma50": 110.5, "consecutiveAbove": 2}
    """
    closes = [c for c in series_payload.get("closes", []) if c is not None]
    highs = [h for h in series_payload.get("highs", []) if h is not None]
    lows = [l for l in series_payload.get("lows", []) if l is not None]
    threshold = series_payload.get("threshold")

    result: dict = {}
    result[f"rsi{period}"] = rsi_wilder(closes, period)
    if highs and lows:
        result[f"atr{period}"] = atr_wilder(highs, lows, closes, period)
    result["sma50"] = sma(closes, 50)
    if threshold is not None:
        result["consecutiveAbove"] = consecutive_closes_above(closes, float(threshold))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ad-hoc derived indicator computation over a JSON OHLCV payload.",
        epilog=(
            "Example:\n"
            "  echo '{\"closes\": [100, 101, 99, 102, ...]}' | "
            "python3 derived_indicators.py --period 14\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--period", type=int, default=14,
                        help="Indicator period (default 14)")
    parser.add_argument("--input", type=str, default="-",
                        help="Path to JSON file (use '-' for stdin)")
    args = parser.parse_args()

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        with open(args.input) as f:
            raw = f.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        return 2

    if not isinstance(payload, dict):
        print("Error: expected a JSON object at top level", file=sys.stderr)
        return 2

    result = _cli_compute(payload, period=args.period)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
