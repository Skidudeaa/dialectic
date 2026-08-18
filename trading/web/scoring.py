"""
Pure scoring functions over the claims ledger — Brier, skill, calibration,
and the per-source leaderboard.

ARCHITECTURE: stdlib-only pure functions over the dicts list_predictions
returns. No I/O, no repository import — the route filters rows and this
module does arithmetic, so every number here is testable against a
hand-computed fixture.

The scored confidence for a claim is the LAST confidence-history row
recorded at/before the claim's INFORMATION BOUNDARY — min(deadline end,
resolved_at). resolved_at alone leaks future information: a human tap can
land days after the outcome became publicly knowable, and a confidence
updated in that window would grade hindsight as foresight. The deadline is
the one hard, stated boundary every claim carries; where the true event
time precedes the deadline the residual window remains (we do not store
outcome_occurred_at), documented rather than hidden.

The reference forecast for skill scores is the claim's captured base_rate
(Polymarket price when linkable) where present, else the 0.5 ignorance
prior — whose Brier is 0.25 regardless of outcome. Two competing
forecasters come free analytically from the same columns: base-rate-only
Brier is brier(base_rate, outcome), and market-consensus Brier is the
same restricted to rows whose base_rate_source is polymarket.

WHY split_by excludes "direction": a long/short direction field does not
exist on predictions yet; the split ships with Phase 8's laboratory
rather than inventing a column here.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: Outcome values on the [0, 1] scale Brier scores grade against.
#: voided AND partial are deliberately absent — a voided claim scores
#: nowhere, and "partial" names an ambiguous or compound proposition, not
#: a proposition that was exactly 50% true; scoring it as 0.5 manufactures
#: calibration precision the resolution never stated. Partials are counted
#: and surfaced, never graded.
OUTCOME_VALUES = {"correct": 1.0, "incorrect": 0.0}

#: Brier of the 0.5 ignorance prior: (0.5 - outcome)^2 == 0.25 for any outcome.
IGNORANCE_REF_BRIER = 0.25

#: Sample floor below which a group's stats are flagged, matching
#: tools/outcomes/lifecycle_monitor.py's provenance convention.
MIN_EMPIRICAL_SAMPLES = 10

LEADERBOARD_SPLITS = ("source_label", "tag", "horizon")

_HORIZON_BUCKETS = ((7, "<=7d"), (30, "<=30d"), (90, "<=90d"))


def outcome_value(resolution: Optional[str]) -> Optional[float]:
    """Numeric outcome for a resolution; None for voided/unresolved (excluded)."""
    if resolution is None:
        return None
    return OUTCOME_VALUES.get(resolution)


def brier(confidence: float, outcome: float) -> float:
    """Squared error of a probabilistic forecast against a realized outcome."""
    return (confidence - outcome) ** 2


def brier_skill_score(brier_value: float, ref_brier: float) -> Optional[float]:
    """1 - brier/ref_brier; positive beats the reference.

    ref_brier == 0 means the reference forecast was perfect — skill
    relative to perfection is undefined, so None rather than a crash.
    """
    if ref_brier == 0:
        return None
    return 1.0 - brier_value / ref_brier


def _ts(value: str) -> datetime:
    """Parse ISO timestamps/dates; naive values are treated as UTC so that
    date-only deadlines compare cleanly against timezone-aware timestamps."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _information_boundary(row: Dict[str, Any]) -> Optional[datetime]:
    """min(deadline end-of-day, resolved_at) — the leak-safe scoring cutoff.

    WHY not resolved_at alone: manual resolution can lag the knowable
    outcome by days, and a belief restated in that lag window is hindsight.
    The deadline (date-only, so its END of day UTC) bounds it.
    """
    resolved_at = row.get("resolved_at")
    if not resolved_at:
        return None
    cutoff = _ts(resolved_at)
    deadline = row.get("deadline")
    if deadline:
        try:
            deadline_end = _ts(deadline).replace(hour=23, minute=59, second=59)
            cutoff = min(cutoff, deadline_end)
        except ValueError:
            pass  # unparseable deadline: fall back to resolved_at
    return cutoff


def scoring_confidence(row: Dict[str, Any]) -> Optional[float]:
    """The LAST history confidence recorded at/before the information
    boundary (see _information_boundary).

    None when the row is unresolved or no history row qualifies — the
    dialectic rule EXCLUDES such rows from scoring rather than guessing.
    """
    cutoff = _information_boundary(row)
    if cutoff is None:
        return None
    best: Optional[Dict[str, Any]] = None
    for entry in row.get("confidence_history") or []:
        recorded = _ts(entry["recorded_at"])
        if recorded <= cutoff and (best is None or recorded > _ts(best["recorded_at"])):
            best = entry
    return best["confidence"] if best is not None else None


def _scored(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A row's scoring inputs, or None when it scores nowhere
    (unresolved, voided, or no pre-resolution confidence)."""
    outcome = outcome_value(row.get("resolution"))
    if outcome is None:
        return None
    confidence = scoring_confidence(row)
    if confidence is None:
        return None
    base_rate = row.get("base_rate")
    ref_brier = brier(base_rate, outcome) if base_rate is not None else IGNORANCE_REF_BRIER
    return {
        "confidence": confidence,
        "outcome": outcome,
        "brier": brier(confidence, outcome),
        "ref_brier": ref_brier,
        "has_base_rate": base_rate is not None,
    }


def _horizon_bucket(row: Dict[str, Any]) -> str:
    days = (_ts(row["deadline"]) - _ts(row["created_at"])).days
    for limit, label in _HORIZON_BUCKETS:
        if days <= limit:
            return label
    return ">90d"


def _group_keys(row: Dict[str, Any], split_by: str) -> List[str]:
    """Group labels a row belongs to. A multi-tagged row lands in every one
    of its tag groups; a row with nothing lands in an explicit bucket
    rather than silently dropping out of the leaderboard."""
    if split_by == "source_label":
        return [row.get("source_label") or "unlabeled"]
    if split_by == "tag":
        return list(row.get("tags") or []) or ["untagged"]
    if split_by == "horizon":
        return [_horizon_bucket(row)]
    raise ValueError(f"split_by must be one of {LEADERBOARD_SPLITS}")


def _aggregate(scored: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group-level stats from per-claim scoring inputs (None metrics when
    nothing scored — the group still appears, with its coverage counts)."""
    n = len(scored)
    if n == 0:
        return {
            "n": 0, "brier": None, "bss": None, "bss_vs": None,
            "accuracy": None, "bias": None,
            "provenance": "UNVERIFIED_INSUFFICIENT_SAMPLES",
        }
    mean_brier = sum(s["brier"] for s in scored) / n
    mean_ref = sum(s["ref_brier"] for s in scored) / n
    return {
        "n": n,
        "brier": mean_brier,
        # Cohort-level skill: 1 - mean(brier)/mean(ref_brier). Never the
        # mean of per-row ratios — a near-perfect single reference would
        # blow that up.
        "bss": brier_skill_score(mean_brier, mean_ref),
        # "market" the moment any claim carries a captured base_rate: the
        # reference is per-claim best-available, and a mixed group's
        # reference is partially market-informed.
        "bss_vs": "market" if any(s["has_base_rate"] for s in scored) else "ignorance",
        "accuracy": sum(s["outcome"] for s in scored) / n,
        # Signed: positive = overconfident (believed harder than reality paid).
        "bias": sum(s["confidence"] - s["outcome"] for s in scored) / n,
        "provenance": "EMPIRICAL" if n >= MIN_EMPIRICAL_SAMPLES
        else "UNVERIFIED_INSUFFICIENT_SAMPLES",
    }


def leaderboard(rows: List[Dict[str, Any]], split_by: str = "source_label") -> List[Dict[str, Any]]:
    """Per-group forecasting skill, best Brier first.

    Only resolved correct/incorrect claims with a pre-boundary confidence
    are GRADED — but every group appears with coverage counts (partials,
    voided, open, unscorable), because a source that issues claims that
    never resolve would otherwise game the table by absence.
    """
    if split_by not in LEADERBOARD_SPLITS:
        raise ValueError(f"split_by must be one of {LEADERBOARD_SPLITS}")
    groups: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        scored = _scored(row)
        resolution = row.get("resolution")
        for key in _group_keys(row, split_by):
            g = groups.setdefault(
                key,
                {"scored": [], "partials": 0, "voided": 0, "open": 0,
                 "unscorable": 0},
            )
            if scored is not None:
                g["scored"].append(scored)
            elif resolution == "partial":
                g["partials"] += 1
            elif resolution == "voided":
                g["voided"] += 1
            elif resolution is None:
                g["open"] += 1
            else:
                # Resolved correct/incorrect but no confidence before the
                # information boundary — graded nowhere, shown here.
                g["unscorable"] += 1
    result = [
        {
            "group": key,
            **_aggregate(g["scored"]),
            "partials": g["partials"],
            "voided": g["voided"],
            "open": g["open"],
            "unscorable": g["unscorable"],
        }
        for key, g in groups.items()
    ]
    # Graded groups by Brier, then ungraded ones by open-claim count.
    result.sort(key=lambda g: (
        (0, g["brier"], g["group"]) if g["brier"] is not None
        else (1, -g["open"], g["group"])
    ))
    return result


def calibration_buckets(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """10-bucket calibration curve, matching dialectic stakes/manager.py's
    get_calibration return shape (bucket/midpoint/total/correct/accuracy
    items plus the total/brier headline keys) so the Ledger frontend can
    render either source with one component.

    Partial and voided resolutions are counted in the payload but graded
    nowhere (see OUTCOME_VALUES) — this deliberately diverges from the
    dialectic scorer's partial=0.5 convention, which manufactures
    calibration precision the resolution never stated.
    """
    scored = [s for s in (_scored(row) for row in rows) if s is not None]
    buckets: List[Dict[str, Any]] = []
    for i in range(10):
        low, high = i / 10, (i + 1) / 10
        buckets.append({
            "bucket": f"{low:.1f}-{high:.1f}",
            "midpoint": (low + high) / 2,
            "total": 0,
            "correct": 0.0,
            "accuracy": None,
        })
    for s in scored:
        idx = min(int(s["confidence"] * 10), 9)
        buckets[idx]["total"] += 1
        buckets[idx]["correct"] += s["outcome"]
    for b in buckets:
        if b["total"] > 0:
            b["accuracy"] = b["correct"] / b["total"]
    total = len(scored)
    resolutions = [row.get("resolution") for row in rows]
    return {
        "calibration": buckets,
        "total_predictions": total,
        "total_correct": sum(s["outcome"] for s in scored),
        "brier_score": (sum(s["brier"] for s in scored) / total) if total else None,
        # Surfaced, never graded (see OUTCOME_VALUES).
        "total_partial": sum(1 for r in resolutions if r == "partial"),
        "total_voided": sum(1 for r in resolutions if r == "voided"),
    }
