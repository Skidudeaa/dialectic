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
        # How much of the question's life this forecaster was actually in.
        # WHY it must be reported beside the Brier and not folded into it: a
        # forecaster who opens the card late is scored only on the days they
        # were present, and those days are nearer the outcome and therefore
        # EASIER. Without coverage beside it, arriving late looks like skill.
        "coverage": days / max(1, (window[1] - window[0]).days + 1),
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


# ── the duel: log score and the head-to-head ─────────────────────────────
#
# WHY a second rule beside Brier rather than instead of it: Brier answers
# "how good were you", which at forty questions a season is a number neither
# of them should believe. The log score answers "who took whose points on
# THIS question", and with exactly two forecasters answering the same slate
# on the same clock the question's difficulty cancels — a paired design most
# platforms structurally cannot run, because they have a crowd instead of a
# pair.
#
# THE CLIP IS THE RULE, not an implementation detail, and it must be stated
# wherever the number is shown. The slider goes to 0.00 and 1.00, and a 0.00
# that resolves yes is infinitely wrong; unclipped, one such answer would
# annihilate a season and the ledger would be unreadable forever after.
# 0.01 is the floor: it reads as "I was essentially certain" and caps a
# single blown call at ln(0.01) ≈ -4.6 nats.
LOG_CLIP = 0.01


def _clip(p: float) -> float:
    return max(LOG_CLIP, min(1.0 - LOG_CLIP, float(p)))


def daily_log_scores(
    history: Iterable[dict],
    window: tuple[date, date],
    outcome: float,
) -> dict[date, float]:
    """Per-day log score for ONE forecaster: ln(p) if it happened, ln(1-p) if
    it did not. Days the forecaster had no standing number are absent, never
    zero — zero is a perfect log score and would read as flawless."""
    import math

    standing = standing_forecast_by_day(history, window)
    return {
        day: math.log(_clip(p) if outcome >= 0.5 else 1.0 - _clip(p))
        for day, p in standing.items()
    }


def time_weighted_log(
    history: Iterable[dict],
    *,
    opened,
    close,
    resolved_at,
    resolution: str,
) -> Optional[dict]:
    """The log-score twin of `time_weighted_brier`, same window, same days."""
    outcome = OUTCOME_VALUES.get(resolution)
    if outcome is None:
        return None
    window = scoring_window(opened, close, resolved_at)
    if window is None:
        return None
    daily = daily_log_scores(history, window, outcome)
    if not daily:
        return None
    return {
        "log_score": sum(daily.values()) / len(daily),
        "days_scored": len(daily),
        "daily": daily,
    }


def window_days(window: tuple[date, date]) -> int:
    """Inclusive day count of a scoring window."""
    start, end = window
    return (end - start).days + 1


def peer_delta(daily_by_actor: dict) -> dict:
    """The head-to-head, scored only on days everyone was actually in.

    `daily_by_actor` maps an actor key to that actor's {day: log score}.
    For each actor: 100 x mean over CONTESTED days of (their log score minus
    the mean of everyone else's that day).

    WHY contested days only: a day one of them had not yet forecast is not a
    day they lost, it is a day they were absent — charging them for it would
    make being slow to open the card indistinguishable from being wrong, and
    `coverage` already reports absence honestly and separately.

    At n=2 this is exactly antisymmetric: +18 for one is -18 for the other.
    That is the whole appeal — the number says who took whose points, and it
    sums to zero, so neither of them can quietly both be winning.
    """
    keys = [k for k, v in daily_by_actor.items() if v]
    if len(keys) < 2:
        return {}
    contested = set(daily_by_actor[keys[0]])
    for k in keys[1:]:
        contested &= set(daily_by_actor[k])
    if not contested:
        return {k: {"peer": None, "contested_days": 0} for k in keys}

    out = {}
    for k in keys:
        others = [o for o in keys if o != k]
        total = 0.0
        for day in contested:
            rival = sum(daily_by_actor[o][day] for o in others) / len(others)
            total += daily_by_actor[k][day] - rival
        out[k] = {
            "peer": 100.0 * total / len(contested),
            "contested_days": len(contested),
        }
    return out
