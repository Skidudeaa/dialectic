"""
Outcomes adapter — wraps lifecycle_monitor, morning_brief, cross_book.

WHY: These modules expect specific Path arguments and produce dataclass
results. This adapter resolves paths and converts to plain dicts for JSON
serialization.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOTS_DIR = _ROOT / "snapshots"
LEDGER_DIR = _ROOT / "outcomes" / "trades"
OPEN_TRADES_PATH = _ROOT / "outcomes" / "open_trades.json"
BOOKS_DIR = _ROOT / "books"

from tools.outcomes import lifecycle_monitor as lm  # type: ignore[import-untyped]
from tools.outcomes import morning_brief as mb  # type: ignore[import-untyped]
from tools.outcomes import cross_book as cb  # type: ignore[import-untyped]


def generate_brief(book_ids: Optional[List[str]] = None) -> str:
    """Generate morning brief text."""
    return mb.generate_brief(SNAPSHOTS_DIR, LEDGER_DIR, book_ids=book_ids)


def list_open_trades() -> List[Dict[str, Any]]:
    """Return all open trades from open_trades.json."""
    if not OPEN_TRADES_PATH.exists():
        return []
    try:
        with open(OPEN_TRADES_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def evaluate_trade(trade_id: str) -> Dict[str, Any]:
    """Run lifecycle evaluation for a specific trade against latest snapshot."""
    trades = list_open_trades()
    trade = None
    for t in trades:
        if t["trade_id"] == trade_id:
            trade = t
            break
    if trade is None:
        raise ValueError(f"Trade not found: {trade_id}")

    # Resolve book → snapshot
    book_id = trade.get("book", "")
    snapshot_path = SNAPSHOTS_DIR / f"{book_id}-latest.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(f"No snapshot for book: {book_id}")

    # Build predicates from trade config
    predicates = [lm.Predicate(**p) for p in trade.get("predicates", [])]
    ref_price = trade.get("ref_price")
    book_path = BOOKS_DIR / f"{book_id}.json" if book_id else None

    monitor = lm.PredicateLifecycleMonitor(str(LEDGER_DIR))
    event_type, record = monitor.run_evaluation_cycle(
        trade_id=trade_id,
        ticker=trade["ticker"],
        predicates=predicates,
        snapshot_path=snapshot_path,
        ref_price=ref_price,
        book_path=book_path,
    )

    return {
        "trade_id": record.trade_id,
        "ticker": record.ticker,
        "event_type": record.event_type,
        "consistency": _extract_consistency(record),
        "predicates": [_ep_to_dict(ep) for ep in record.evaluated_predicates],
        "dynamic_target": asdict(record.dynamic_target) if record.dynamic_target else None,
        "target_refusal": asdict(record.target_refusal) if record.target_refusal else None,
    }


def _extract_consistency(record: lm.TradeRecord) -> float:
    """Extract consistency score from a trade record."""
    # WHY: consistency is computed during evaluation but stored in verdict.
    # For non-exit events, compute from predicate flip rates.
    if record.verdict:
        return record.verdict.predicate_consistency
    total = len(record.evaluated_predicates)
    if total == 0:
        return 100.0
    flipped = sum(1 for ep in record.evaluated_predicates if ep.is_flipped)
    return round((1 - flipped / total) * 100, 1)


def _ep_to_dict(ep: lm.EvaluatedPredicate) -> Dict[str, Any]:
    """Convert EvaluatedPredicate to a plain dict."""
    return {
        "predicate": asdict(ep.predicate),
        "actual": ep.actual,
        "is_flipped": ep.is_flipped,
        "note": ep.note,
    }


def scan_cross_book(book_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run cross-book scan."""
    report = cb.scan_cross_book(SNAPSHOTS_DIR, book_ids=book_ids)
    return asdict(report)


def get_trade_ledger(trade_id: str) -> List[Dict[str, Any]]:
    """Return JSONL trade history for a specific trade."""
    ledger_path = LEDGER_DIR / f"{trade_id}.jsonl"
    if not ledger_path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in ledger_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = lm._deserialize_record(line)
        if rec:
            records.append(asdict(rec))
    return records
