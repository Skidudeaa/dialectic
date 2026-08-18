"""
Pure scoring functions over the claims ledger — Brier, skill, calibration,
and the per-source leaderboard.

ARCHITECTURE: stdlib-only pure functions over the dicts list_predictions
returns. No I/O, no repository import — the route filters rows and this
module does arithmetic, so every number here is testable against a
hand-computed fixture.

The scored confidence for a claim is the LAST confidence-history row
recorded at/before resolved_at (the dialectic stakes/manager.py rule):
belief updates after the outcome was known score nothing, and the belief
held going into resolution is what gets graded.

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
#: voided is deliberately absent — a voided claim scores nowhere.
OUTCOME_VALUES = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

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


def scoring_confidence(row: Dict[str, Any]) -> Optional[float]:
    """The LAST history confidence recorded at/before resolved_at.

    None when the row is unresolved or no history row qualifies — the
    dialectic rule EXCLUDES such rows from scoring rather than guessing.
    """
    resolved_at = row.get("resolved_at")
    if not resolved_at:
        return None
    cutoff = _ts(resolved_at)
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
    """Group-level stats from per-claim scoring inputs (scored is non-empty)."""
    n = len(scored)
    mean_brier = sum(s["brier"] for s in scored) / n
    mean_ref = sum(s["ref_brier"] for s in scored) / n
    return {
        "n": n,
        "brier": mean_brier,
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

    Only resolved, non-voided claims with a pre-resolution confidence
    contribute; a group appears only if at least one claim scored.
    """
    if split_by not in LEADERBOARD_SPLITS:
        raise ValueError(f"split_by must be one of {LEADERBOARD_SPLITS}")
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        scored = _scored(row)
        if scored is None:
            continue
        for key in _group_keys(row, split_by):
            groups.setdefault(key, []).append(scored)
    result = [{"group": key, **_aggregate(scored)} for key, scored in groups.items()]
    result.sort(key=lambda g: (g["brier"], g["group"]))
    return result


def calibration_buckets(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """10-bucket calibration curve, matching dialectic stakes/manager.py's
    get_calibration return shape (bucket/midpoint/total/correct/accuracy
    items plus the total/brier headline keys) so the Ledger frontend can
    render either source with one component.

    Partial resolutions count 0.5 correct, exactly as the dialectic scorer
    counts them.
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
    return {
        "calibration": buckets,
        "total_predictions": total,
        "total_correct": sum(s["outcome"] for s in scored),
        "brier_score": (sum(s["brier"] for s in scored) / total) if total else None,
    }
