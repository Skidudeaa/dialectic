# stakes/timeweighted.py — the Good Judgment scoring rule.
#
# ARCHITECTURE: pure functions over a forecast history. No I/O, no database,
# no clock of their own — every boundary is passed in. That is deliberate: a
# scoring rule that reads the wall clock cannot be tested against a worked
# example, and a worked example is the only way to know this is right.
#
# WHY time-weighted, and why it is not a preference: the owners forecast in
# IARPA's ACE tournament, where a question's score is the average Brier over
# every day it was open, evaluated at whatever your standing forecast was that
# day. That rule is what makes UPDATING the measured skill. Under final-answer
# scoring a forecaster who sits at 0.50 for 27 days and moves to 0.95 on the
# last day scores identically to one who was at 0.95 from the start — the
# ledger would say they were equally good, which is the opposite of true.
#
# THE LEAK-SAFE BOUNDARY, borrowed from the desk's own scoring law: a forecast
# is only credited for days at or before min(close, resolved_at). A revision
# entered after the outcome was knowable must not score, and a question
# resolved early stops accruing at resolution rather than at its nominal close.
#
# TRADEOFF: days are the quantum, matching GJP. Two revisions on the same day
# mean the LAST one governs that day — a forecaster who flip-flops inside a
# day is not credited for having briefly held the right number.

from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

# Outcomes that can be scored at all. `partial` and `voided` are deliberately
# absent: the desk's law is partial-counted-never-graded, and inventing a 0.5
# outcome for a binary question is exactly the kind of manufactured number
# this ledger exists to avoid.
OUTCOME_VALUES = {"correct": 1.0, "incorrect": 0.0}


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def scoring_window(opened, close, resolved_at) -> Optional[tuple[date, date]]:
    """The inclusive day range a forecast can earn credit for.

    Ends at min(close, resolved_at) — the leak-safe boundary. Returns None
    when the question cannot be scored at all (no open date, or an end before
    the beginning), which callers must treat as "not scoreable", never as zero.
    """
    start = _as_date(opened)
    ends = [d for d in (_as_date(close), _as_date(resolved_at)) if d is not None]
    if start is None or not ends:
        return None
    end = min(ends)
    if end < start:
        return None
    return start, end


def standing_forecast_by_day(
    history: Iterable[dict],
    window: tuple[date, date],
) -> dict[date, float]:
    """The probability standing on each day of the window.

    `history` is (recorded_at, confidence) entries for ONE forecaster, in any
    order. A day inherits the most recent forecast at or before it; days
    before the first forecast are absent from the result rather than filled
    with 0.5 — someone who never forecast has no score, which is different
    from having forecast badly.
    """
    start, end = window
    entries = []
    for item in history:
        when = _as_date(item.get("recorded_at"))
        confidence = item.get("confidence")
        if when is None or confidence is None:
            continue
        entries.append((when, float(confidence)))
    if not entries:
        return {}
    # Later entries on the same day win: sort ascending and let the dict
    # assignment below overwrite.
    entries.sort(key=lambda pair: pair[0])

    standing: dict[date, float] = {}
    current: Optional[float] = None
    cursor = start
    idx = 0
    # Anything recorded before the window opens sets the starting position.
    while idx < len(entries) and entries[idx][0] < start:
        current = entries[idx][1]
        idx += 1
    while cursor <= end:
        while idx < len(entries) and entries[idx][0] <= cursor:
            current = entries[idx][1]
            idx += 1
        if current is not None:
            standing[cursor] = current
        cursor += timedelta(days=1)
    return standing


def time_weighted_brier(
    history: Iterable[dict],
    *,
    opened,
    close,
    resolved_at,
    resolution: str,
) -> Optional[dict]:
    """Average Brier across every scored day of one forecaster's question.

    Returns None when the question is unscoreable (unknown outcome, no window,
    or the forecaster never entered a number inside it) — callers must render
    that as "not scored", never as a zero, which would read as a perfect score.
    """
    outcome = OUTCOME_VALUES.get(resolution)
    if outcome is None:
        return None
    window = scoring_window(opened, close, resolved_at)
    if window is None:
        return None
    standing = standing_forecast_by_day(history, window)
    if not standing:
        return None

    daily = [(day, (p - outcome) ** 2) for day, p in sorted(standing.items())]
    total = sum(score for _, score in daily)
    days = len(daily)
    final = daily[-1][1]
    return {
        "brier": total / days,
        "days_scored": days,
        # The final-answer Brier, carried alongside rather than instead of.
        # The GAP between them is the interesting number: it says whether a
        # forecaster got there early or merely got there.
        "brier_final_answer": final,
        "lateness_gap": (total / days) - final,
        "first_day": daily[0][0].isoformat(),
        "last_day": daily[-1][0].isoformat(),
    }


def brier_skill_score(brier: float, reference: float) -> Optional[float]:
    """1 - brier/reference. None when the reference cannot discriminate."""
    if reference is None or reference <= 0:
        return None
    return 1.0 - (brier / reference)


# The Brier of an uninformed 0.5 on a binary question. Used as the reference
# when a question carries no base rate, matching the desk's IGNORANCE_REF_BRIER.
IGNORANCE_REF_BRIER = 0.25
