#!/usr/bin/env python3
"""
CLI to seed ENTRY events into the JSONL trade ledger.

Usage:
  python3 tools/outcomes/log_entry.py --trade xop
  python3 tools/outcomes/log_entry.py --trade cf
  python3 tools/outcomes/log_entry.py --trade spy-short
  python3 tools/outcomes/log_entry.py --trade xop --ref-price 188.18
  python3 tools/outcomes/log_entry.py --list

Seeds the three trades' predicate gates from lifecycle_monitor.py.
"""

import argparse
import fcntl
import json
import sys
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone

# WHY: Resolve import path relative to this file so the CLI works from anywhere.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from lifecycle_monitor import (
    Predicate, EvaluatedPredicate, TradeRecord,
    XOP_GATE, CF_GATE, SPY_SHORT_GATE,
    _serialize_record,
)


# WHY: Canonical trade definitions. ref_price from the book JSON instruments.
TRADES = {
    "xop": {
        "trade_id": "TRD-XOP-HORMUZ",
        "ticker": "XOP",
        "predicates": XOP_GATE,
        "ref_price": 188.18,
        "book": "iran-hormuz-graph",
    },
    "cf": {
        "trade_id": "TRD-CF-PLANTING",
        "ticker": "CF",
        "predicates": CF_GATE,
        "ref_price": 136.45,
        "book": "iran-hormuz-graph",
    },
    "spy-short": {
        "trade_id": "TRD-SH-RECESSION",
        "ticker": "SH",
        "predicates": SPY_SHORT_GATE,
        "ref_price": 15.50,  # SH (inverse SPY ETF) approximate
        "book": "trump-tariffs-graph",
    },
}


def seed_entry(trade_key: str, ref_price: float | None, ledger_dir: Path) -> None:
    """Write an ENTRY record to the trade's JSONL ledger."""
    trade = TRADES[trade_key]
    tid = trade["trade_id"]
    ledger_file = ledger_dir / f"{tid}.jsonl"

    # Check if entry already exists
    if ledger_file.exists():
        for line in ledger_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                if d.get("event_type") == "ENTRY":
                    print(f"ENTRY already exists for {tid}. Skipping.", file=sys.stderr)
                    return
            except json.JSONDecodeError:
                continue

    price = ref_price if ref_price is not None else trade["ref_price"]
    predicates = trade["predicates"]

    # ENTRY records have unevaluated predicates (actual=None, is_flipped=False)
    evaluated = [
        EvaluatedPredicate(predicate=p, actual=None, is_flipped=False)
        for p in predicates
    ]

    record = TradeRecord(
        trade_id=tid,
        ticker=trade["ticker"],
        event_type="ENTRY",
        snapshot_hash="entry-seed",
        evaluated_predicates=evaluated,
        run_id=f"entry-{tid}",
    )

    ledger_dir.mkdir(parents=True, exist_ok=True)
    # WHY flock: match PredicateLifecycleMonitor._log — two concurrent writers
    # (this CLI + a racing cron) can interleave JSONL records beyond O_APPEND's
    # PIPE_BUF atomicity guarantee, producing lines that fail parse and
    # silently drop from _iter_records.
    line = _serialize_record(record) + "\n"
    with ledger_file.open("a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    print(f"Seeded ENTRY for {tid} ({trade['ticker']}) at ref ${price:.2f}")
    print(f"  Predicates: {len(predicates)} ({sum(1 for p in predicates if p.load_bearing)} load-bearing)")
    print(f"  Ledger: {ledger_file}")


def write_open_trades_json(ledger_dir: Path) -> None:
    """Write outcomes/open_trades.json for run-all.py Step 7 to consume."""
    open_trades = []
    for key, trade in TRADES.items():
        open_trades.append({
            "trade_id": trade["trade_id"],
            "ticker": trade["ticker"],
            "predicates": [asdict(p) for p in trade["predicates"]],
            "ref_price": trade["ref_price"],
            "book": trade["book"],
        })
    out_path = ledger_dir.parent / "open_trades.json"
    out_path.write_text(json.dumps(open_trades, indent=2))
    print(f"Wrote {out_path} ({len(open_trades)} trades)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ENTRY events into the trade ledger.")
    parser.add_argument("--trade", choices=list(TRADES.keys()), help="Trade to seed")
    parser.add_argument("--ref-price", type=float, help="Override reference price")
    parser.add_argument("--all", action="store_true", help="Seed all three trades")
    parser.add_argument("--list", action="store_true", help="List available trades")
    parser.add_argument("--write-open-trades", action="store_true",
                        help="Write outcomes/open_trades.json for run-all.py")
    parser.add_argument("--ledger-dir", default=str(Path(__file__).resolve().parents[2] / "outcomes" / "trades"),
                        help="Ledger directory")
    args = parser.parse_args()

    ledger_dir = Path(args.ledger_dir)

    if args.list:
        for key, trade in TRADES.items():
            print(f"  {key:12s}  {trade['trade_id']}  {trade['ticker']:4s}  "
                  f"${trade['ref_price']:.2f}  ({len(trade['predicates'])} predicates)")
        return

    if args.write_open_trades:
        write_open_trades_json(ledger_dir)
        return

    if args.all:
        for key in TRADES:
            seed_entry(key, None, ledger_dir)
        write_open_trades_json(ledger_dir)
        return

    if args.trade:
        seed_entry(args.trade, args.ref_price, ledger_dir)
        return

    # WHY exit 2: no action flag provided is a misuse, not a request for help.
    # Exit 0 here silently greened cron pipelines that chained `log_entry.py &&
    # push_snapshot.sh` — the push would proceed after a no-op log step.
    parser.print_help(sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
