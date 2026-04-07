"""
Cross-Book Confluence Scanner.

Reads snapshots from multiple thesis-graph books and detects:
  1. Shared market data points (goldSpot, vix appear in both books)
  2. Simultaneous cascade phase alignment (both in Phase 3 = compound signal)
  3. Correlated confluence movements across books
  4. Cross-book recession signal (em-stress + recession-risk both firing)

Outputs cross-book flags as JSON for the morning brief and Dialectic push.
Zero external dependencies — stdlib only.
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_monitor import Snapshot


@dataclass
class CrossBookFlag:
    """WHAT: A single cross-book signal detected by the scanner."""
    flag_type: str  # "phase_alignment", "shared_market", "cross_confluence", "compound_recession"
    severity: str   # "HIGH", "MEDIUM", "LOW"
    books: List[str]
    detail: str
    data: Dict = field(default_factory=dict)


@dataclass
class CrossBookReport:
    """WHAT: Full cross-book analysis output."""
    timestamp: str
    books_analyzed: List[str]
    flags: List[CrossBookFlag]
    shared_markets: Dict[str, Dict[str, float]]
    phase_summary: Dict[str, dict]


def _detect_phase_alignment(snapshots: Dict[str, Snapshot]) -> List[CrossBookFlag]:
    """WHAT: Flag when multiple books are in the same cascade phase simultaneously."""
    flags = []
    phases = {name: snap.cascade_phase for name, snap in snapshots.items()}
    phase_numbers = {name: p.get("number", 0) for name, p in phases.items()}

    # All books in Phase 3 (Amplification) = compound macro stress
    books_at_phase3 = [name for name, num in phase_numbers.items() if num == 3]
    if len(books_at_phase3) >= 2:
        flags.append(CrossBookFlag(
            flag_type="phase_alignment",
            severity="HIGH",
            books=books_at_phase3,
            detail=(
                f"All {len(books_at_phase3)} books simultaneously in Phase 3 (Amplification). "
                "Multiple independent macro shocks amplifying concurrently — compound stress signal."
            ),
            data={name: phases[name] for name in books_at_phase3},
        ))

    # Check for Phase 4 divergence (one book advancing to policy response while other is still amplifying)
    books_at_4 = [name for name, num in phase_numbers.items() if num >= 4]
    books_at_3 = [name for name, num in phase_numbers.items() if num == 3]
    if books_at_4 and books_at_3:
        flags.append(CrossBookFlag(
            flag_type="phase_alignment",
            severity="MEDIUM",
            books=books_at_4 + books_at_3,
            detail=(
                f"Phase divergence: {books_at_4} at Phase 4+ (policy response) "
                f"while {books_at_3} still at Phase 3 (amplification). "
                "Policy response in one thesis may dampen the other."
            ),
        ))
    return flags


def _detect_shared_markets(snapshots: Dict[str, Snapshot]) -> Tuple[Dict[str, Dict[str, float]], List[CrossBookFlag]]:
    """WHAT: Find market data points that appear in multiple books."""
    flags = []
    all_markets: Dict[str, Dict[str, float]] = {}

    for name, snap in snapshots.items():
        for key, val in snap.market_snapshot.items():
            all_markets.setdefault(key, {})[name] = val

    # Report shared keys
    shared = {k: v for k, v in all_markets.items() if len(v) >= 2}
    if shared:
        flags.append(CrossBookFlag(
            flag_type="shared_market",
            severity="LOW",
            books=list(snapshots.keys()),
            detail=f"Shared market data: {list(shared.keys())}. Changes affect both theses.",
            data=shared,
        ))
    return all_markets, flags


def _detect_cross_confluence(snapshots: Dict[str, Snapshot]) -> List[CrossBookFlag]:
    """WHAT: Flag when recession-adjacent confluence nodes fire across books."""
    flags = []
    # Map of recession-adjacent nodes per book
    recession_nodes = {
        "iran-hormuz-graph": ["em-stress", "demand-destruction"],
        "trump-tariffs-graph": ["recession-risk", "earnings-compression", "consumer-confidence"],
    }

    fired_recession = {}
    for name, snap in snapshots.items():
        nodes_to_check = recession_nodes.get(name, [])
        fired = [n for n in nodes_to_check if snap.node_states.get(n) == "fired"]
        if fired:
            fired_recession[name] = fired

    if len(fired_recession) >= 2:
        # Both books have recession-adjacent nodes firing
        all_fired = []
        for nodes in fired_recession.values():
            all_fired.extend(nodes)

        # Sum confluence scores across books for recession nodes
        total_confluence = 0.0
        conf_detail = {}
        for name, snap in snapshots.items():
            for node in fired_recession.get(name, []):
                score = snap.confluence_scores.get(node, 0)
                if score > 0:
                    total_confluence += score
                    conf_detail[f"{name}:{node}"] = score

        severity = "HIGH" if total_confluence >= 3.0 else "MEDIUM"
        flags.append(CrossBookFlag(
            flag_type="compound_recession",
            severity=severity,
            books=list(fired_recession.keys()),
            detail=(
                f"Recession-adjacent nodes firing across {len(fired_recession)} books: "
                f"{all_fired}. Combined confluence: {total_confluence:.2f}. "
                "Independent causal paths converging on recession from different macro shocks."
            ),
            data={"fired": fired_recession, "confluence": conf_detail,
                  "total_confluence": total_confluence},
        ))

    return flags


def _detect_countdown_pressure(snapshots: Dict[str, Snapshot]) -> List[CrossBookFlag]:
    """WHAT: Flag when multiple books have approaching deadlines."""
    flags = []
    urgent = []  # (book, node, days)
    for name, snap in snapshots.items():
        for cd in snap.countdowns:
            days = cd.get("daysRemaining", 999)
            if days <= 30:
                urgent.append((name, cd.get("nodeId", "?"), days, cd.get("label", "?")))

    if len(urgent) >= 2:
        flags.append(CrossBookFlag(
            flag_type="countdown_pressure",
            severity="HIGH" if any(d <= 14 for _, _, d, _ in urgent) else "MEDIUM",
            books=list(set(b for b, _, _, _ in urgent)),
            detail=(
                f"Multiple deadlines within 30 days: "
                + ", ".join(f"{label} ({days}d)" for _, _, days, label in sorted(urgent, key=lambda x: x[2]))
            ),
            data={"countdowns": [{"book": b, "node": n, "days": d, "label": l} for b, n, d, l in urgent]},
        ))
    return flags


def scan_cross_book(snapshots_dir: Path, book_ids: Optional[List[str]] = None) -> CrossBookReport:
    """WHAT: Run full cross-book analysis on available snapshots.

    Args:
        snapshots_dir: Directory containing {book-id}-latest.json files
        book_ids: Optional filter. If None, scans all *-latest.json files.
    """
    snapshots: Dict[str, Snapshot] = {}

    if book_ids:
        for bid in book_ids:
            path = snapshots_dir / f"{bid}-latest.json"
            if path.exists():
                snapshots[bid] = Snapshot.load(path)
    else:
        for path in sorted(snapshots_dir.glob("*-latest.json")):
            bid = path.stem.replace("-latest", "")
            try:
                snapshots[bid] = Snapshot.load(path)
            except (ValueError, json.JSONDecodeError):
                continue

    if len(snapshots) < 2:
        return CrossBookReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            books_analyzed=list(snapshots.keys()),
            flags=[],
            shared_markets={},
            phase_summary={n: s.cascade_phase for n, s in snapshots.items()},
        )

    # Run all detectors
    flags: List[CrossBookFlag] = []
    flags.extend(_detect_phase_alignment(snapshots))
    shared_markets, market_flags = _detect_shared_markets(snapshots)
    flags.extend(market_flags)
    flags.extend(_detect_cross_confluence(snapshots))
    flags.extend(_detect_countdown_pressure(snapshots))

    # Sort by severity
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    flags.sort(key=lambda f: severity_order.get(f.severity, 3))

    return CrossBookReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        books_analyzed=list(snapshots.keys()),
        flags=flags,
        shared_markets=shared_markets,
        phase_summary={n: s.cascade_phase for n, s in snapshots.items()},
    )


def save_cross_book_flags(report: CrossBookReport, output_path: Path) -> None:
    """WHAT: Write cross-book report to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cross-book confluence scanner")
    parser.add_argument("--snapshots-dir", default="snapshots", help="Snapshots directory")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    report = scan_cross_book(Path(args.snapshots_dir))
    if args.output:
        save_cross_book_flags(report, Path(args.output))

    print(f"Books analyzed: {report.books_analyzed}")
    print(f"Flags: {len(report.flags)}")
    for flag in report.flags:
        print(f"  [{flag.severity}] {flag.flag_type}: {flag.detail[:120]}")
