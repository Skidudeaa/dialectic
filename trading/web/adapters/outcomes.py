"""
Outcomes adapter — wraps lifecycle_monitor, morning_brief, cross_book.

WHY: These modules expect specific Path arguments and produce dataclass
results. This adapter resolves paths and converts to plain dicts for JSON
serialization.
"""

import fcntl
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
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
from web.adapters import thesis as _thesis_adapter


def generate_brief(book_ids: Optional[List[str]] = None) -> str:
    """Generate morning brief text."""
    return mb.generate_brief(SNAPSHOTS_DIR, LEDGER_DIR, book_ids=book_ids)


def list_open_trades() -> List[Dict[str, Any]]:
    """Return all open trades from open_trades.json.

    Uses a shared fcntl lock so a concurrent kill_trade() writer can't
    leave us mid-rename. Matches web/state.py's locking convention.
    """
    if not OPEN_TRADES_PATH.exists():
        return []
    try:
        with open(OPEN_TRADES_PATH) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
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


# ── Trade lifecycle panel helpers (Unit 10) ──────────────────────────────

def _find_trade(trade_id: str) -> Dict[str, Any]:
    """Return the trade dict or raise ValueError if missing."""
    for t in list_open_trades():
        if t.get("trade_id") == trade_id:
            return t
    raise ValueError(f"Trade not found: {trade_id}")


def _predicate_description(pred: "lm.Predicate") -> str:
    """WHY: The UI needs a human-readable sentence; the raw dataclass is dense.
    Keep it short (~1 line) so the card doesn't balloon."""
    if pred.kind == "state":
        return f"{pred.node_id} == {pred.expected}"
    if pred.kind == "state_set":
        return f"{pred.node_id} in {{{', '.join(pred.allowed)}}}"
    if pred.kind == "threshold":
        return f"{pred.path} {pred.op} {pred.value}"
    if pred.kind == "countdown":
        return f"{pred.node_id} countdown {pred.op} {pred.days}d"
    return f"unknown:{pred.kind}"


def _predicate_id(pred: "lm.Predicate", index: int) -> str:
    """Stable per-predicate id for UI keys. WHY: open_trades.json has no id
    per predicate, so derive one from (kind, node_id|path, index) that's
    stable across identical snapshots."""
    ref = pred.node_id or pred.path or f"ix{index}"
    return f"{pred.kind}:{ref}:{index}"


def _classify_predicate(ep: "lm.EvaluatedPredicate") -> str:
    """Collapse the EvaluatedPredicate result to a UI state bucket.

    - inactive: reference missing (node_id/path absent)
    - fired:    load-bearing predicate flipped — thesis invalidating
    - approaching: supporting predicate flipped, or a near-threshold hold
    - stable:   predicate currently holds

    WHY: lifecycle_monitor's is_flipped is binary. The UI wants three
    colors + grey (missing). We widen "approaching" to include both the
    structural "supporting flipped" case and numeric "within 10%" of a
    threshold boundary — that's the signal the operator cares about.
    """
    if ep.note in ("NODE_MISSING", "PATH_MISSING", "COUNTDOWN_MISSING", "PATH_NON_NUMERIC"):
        return "inactive"
    pred = ep.predicate
    if ep.is_flipped:
        return "fired" if pred.load_bearing else "approaching"
    # Predicate holds. For numeric predicates, flag "approaching" when
    # the actual value is within 10% of the threshold boundary on the
    # failing side — a cheap tripwire that surfaces drifting fundamentals
    # before they flip.
    if pred.kind == "threshold" and isinstance(ep.actual, (int, float)):
        target = pred.value
        actual = ep.actual
        if target != 0:
            gap = abs(actual - target) / max(abs(target), 1e-9)
            if gap <= 0.10 and actual >= 0:
                return "approaching"
    if pred.kind == "countdown" and isinstance(ep.actual, (int, float)):
        # Countdown threshold is days; if we're within 3d of the edge, warn.
        if abs(ep.actual - pred.days) <= 3:
            return "approaching"
    return "stable"


def get_trade_predicates(trade_id: str) -> Dict[str, Any]:
    """Evaluate predicates for a trade against the CURRENT live snapshot.

    Returns a JSON-serializable dict with per-predicate detail and
    aggregate timers. Pure-read — does not write to the ledger. The
    lifecycle_monitor.run_evaluation_cycle() path is avoided because it
    appends an EVALUATION row to the JSONL every call; this endpoint is
    intended to be polled by the UI every ~30s.
    """
    trade = _find_trade(trade_id)
    book_id = trade.get("book", "")
    if not book_id:
        raise ValueError(f"Trade {trade_id} has no linked book")

    # Pull the current evaluated graph state via the thesis adapter
    # (cached 60s). Wrap in the lifecycle Snapshot so predicate evaluation
    # can reuse the same path-walking semantics as the cron pipeline.
    state = _thesis_adapter.get_state(book_id)
    snap = lm.Snapshot(state)

    raw_preds = trade.get("predicates", [])
    predicates: List[Dict[str, Any]] = []
    fire_count = 0
    approach_count = 0
    for ix, pdict in enumerate(raw_preds):
        pred = lm.Predicate(**pdict)
        ep = lm.evaluate_predicate(pred, snap)
        bucket = _classify_predicate(ep)
        if bucket == "fired":
            fire_count += 1
        elif bucket == "approaching":
            approach_count += 1
        predicates.append({
            "id": _predicate_id(pred, ix),
            "kind": pred.kind,
            "description": _predicate_description(pred),
            "state": bucket,
            "actual": ep.actual,
            "note": ep.note,
            "load_bearing": pred.load_bearing,
            "is_flipped": ep.is_flipped,
            "node_id": pred.node_id or None,
            "path": pred.path or None,
            "expected": pred.expected or None,
            "allowed": list(pred.allowed) if pred.allowed else None,
            "op": pred.op or None,
            "value": pred.value,
            "days": pred.days,
        })

    # Aggregate timers: None until the pipeline emits durations; leave
    # the fields declared so the UI can render "—" instead of breaking.
    # Future work ties this to TradeRecord.timestamps but open_trades.json
    # doesn't carry that yet.
    return {
        "trade_id": trade_id,
        "ticker": trade.get("ticker", ""),
        "book": book_id,
        "ref_price": trade.get("ref_price"),
        "direction": trade.get("direction", "long"),
        "predicates": predicates,
        "fire_timer_hours": None,
        "approach_timer_hours": None,
        "fired_count": fire_count,
        "approaching_count": approach_count,
        "snapshot_timestamp": state.get("timestamp", ""),
    }


def kill_trade(trade_id: str, actor: str, reason: str = "") -> Dict[str, Any]:
    """Close a trade manually — writes a KILL row to the ledger and
    removes the trade from open_trades.json.

    Atomicity: open_trades.json is rewritten via temp+rename with an
    exclusive lock. The KILL event is appended to the ledger JSONL first
    (under its own flock) so the ledger record exists even if the
    subsequent rewrite crashes; a crash in the other order could erase
    the trade from open_trades.json without an audit trail.

    Idempotency: if the trade is not in open_trades.json, raise
    ValueError("already_closed"). The route maps that to HTTP 409.
    """
    trades = list_open_trades()
    remaining: List[Dict[str, Any]] = []
    target: Optional[Dict[str, Any]] = None
    for t in trades:
        if t.get("trade_id") == trade_id:
            target = t
        else:
            remaining.append(t)
    if target is None:
        # Could mean trade never existed OR already killed. Surface the
        # latter explicitly so callers can choose 404 vs 409.
        ledger_path = LEDGER_DIR / f"{trade_id}.jsonl"
        if ledger_path.exists():
            # Check for an existing KILL row.
            for line in ledger_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event_type") == "KILL":
                    raise ValueError("already_closed")
        raise ValueError(f"Trade not found: {trade_id}")

    # 1. Append KILL row to the ledger JSONL (with exclusive lock).
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = LEDGER_DIR / f"{trade_id}.jsonl"
    kill_row = {
        "trade_id": trade_id,
        "ticker": target.get("ticker", ""),
        "event_type": "KILL",
        "snapshot_hash": "manual-kill",
        "evaluated_predicates": [],
        "run_id": f"kill-{trade_id}-{int(datetime.now(timezone.utc).timestamp())}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "reason": reason or "manual close",
    }
    with open(ledger_path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(kill_row, separators=(",", ":")) + "\n")
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    # 2. Rewrite open_trades.json atomically (temp + rename, exclusive lock).
    OPEN_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OPEN_TRADES_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(remaining, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    os.replace(str(tmp), str(OPEN_TRADES_PATH))

    return {
        "trade_id": trade_id,
        "killed_at": kill_row["timestamp"],
        "actor": actor,
        "reason": kill_row["reason"],
    }
