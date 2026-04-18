#!/usr/bin/env python3
"""
Morning Brief Generator.

Reads: latest snapshots, cross-book flags, horizon traces, lifecycle ledger.
Outputs: structured plain-text brief for the operator.

Run after run-all.py or standalone:
  python3 tools/outcomes/morning_brief.py
  python3 tools/outcomes/morning_brief.py --snapshots-dir snapshots --ledger-dir outcomes/trades

Zero external dependencies — stdlib only.
"""

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from lifecycle_monitor import Snapshot, LedgerAnalyzer, _deserialize_record
from cross_book import scan_cross_book, CrossBookReport

# WHY: Pull LLM_ANNOTATOR alerts back from Dialectic so the operator sees
# in the brief the things the curator said while they were offline. Optional
# import: if the client module isn't importable (test envs, broken sys.path)
# the brief still generates without the dialectic section.
_REPO_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
try:  # pragma: no cover - trivial import shim
    from tools.bridge.dialectic_client import DialecticClient, DialecticAPIError
    _HAVE_DIALECTIC_CLIENT = True
except Exception:
    _HAVE_DIALECTIC_CLIENT = False


def _phase_label(phase: dict) -> str:
    names = {1: "Shock", 2: "Transmission", 3: "Amplification",
             4: "Policy Response", 5: "Resolution"}
    num = phase.get("number", 0)
    status = phase.get("status", "?")
    return f"Phase {num}: {names.get(num, '?')} — {status}"


def _format_countdown(cd: dict) -> str:
    days = cd.get("daysRemaining", "?")
    label = cd.get("label", cd.get("nodeId", "?"))
    urgency = "URGENT" if isinstance(days, int) and days <= 7 else ""
    return f"{label} in {days} days {urgency}".strip()


def _format_horizon_trace(trace: dict, node_states_t0: dict) -> List[str]:
    """WHAT: Summarize what changes between T+0 and each horizon."""
    lines = []
    for horizon_key in sorted(trace.keys()):
        h = trace[horizon_key]
        states_h = h.get("states", {})
        conf_h = h.get("confluence", {})
        # Count state changes vs T+0
        promotions = []
        for nid, s_h in states_h.items():
            s_0 = node_states_t0.get(nid, "monitoring")
            if s_h == "fired" and s_0 != "fired":
                promotions.append(nid)
        if promotions:
            lines.append(f"  {horizon_key}: {', '.join(promotions)} promote to fired")
            if conf_h:
                for nid, score in conf_h.items():
                    lines.append(f"    confluence {nid} = {score}")
    return lines


def _format_ledger_summary(ledger_dir: Path) -> List[str]:
    """WHAT: Recent lifecycle events from the JSONL ledger."""
    lines = []
    recent = []
    if ledger_dir.exists():
        for f in sorted(ledger_dir.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                rec = _deserialize_record(line)
                if rec:
                    recent.append(rec)
    # Sort by timestamp, take last 5
    recent.sort(key=lambda r: r.timestamp, reverse=True)
    for rec in recent[:5]:
        verdict_str = ""
        if rec.verdict:
            v = rec.verdict
            failed = v.load_bearing_flipped or v.supporting_flipped
            verdict_str = f" — flipped: {failed}, consistency: {v.predicate_consistency}%"
        lines.append(f"  {rec.trade_id} [{rec.event_type}] {rec.timestamp[:19]}{verdict_str}")
    return lines


def _load_book_room_map(books_dir: Path) -> Dict[str, str]:
    """Map book_id -> dialecticRoomId for books that have one.

    Returns an empty dict if books_dir doesn't exist (test env, fresh checkout).
    Books without a room ID are silently skipped.
    """
    out: Dict[str, str] = {}
    if not books_dir.is_dir():
        return out
    for path in sorted(books_dir.glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta", {}) or {}
        room_id = meta.get("dialecticRoomId")
        if room_id:
            out[path.stem] = str(room_id)
    return out


def _format_dialectic_alerts(
    book_room_map: Dict[str, str],
    dialectic_url: str,
    since: datetime,
    limit_per_thread: int = 25,
) -> List[str]:
    """Pull recent LLM_ANNOTATOR alerts from each room and format for the brief.

    WHY in the brief: the curator generates these when the operator is offline.
    Surfacing them in the morning brief is the moment the operator is most
    likely to need to know what the model flagged overnight.

    Returns lines (possibly empty). Network failures degrade gracefully -- the
    brief still generates, with a one-line note instead of the alerts section.
    """
    if not _HAVE_DIALECTIC_CLIENT or not book_room_map:
        return []

    token = os.environ.get("DIALECTIC_ROOM_TOKEN", "").strip()
    if not token:
        # WHY: don't probe without a token -- the API would 401 and noise the log.
        return []

    client = DialecticClient(dialectic_url, token=token, timeout=5.0)
    since_iso = since.isoformat()
    section: List[str] = []
    for book_id, room_id in book_room_map.items():
        try:
            alerts = client.fetch_curator_alerts(
                room_id, since_iso=since_iso,
                limit_per_thread=limit_per_thread,
            )
        except DialecticAPIError as exc:
            section.append(f"  [{book_id}] dialectic unreachable: {exc}")
            continue
        if not alerts:
            continue
        section.append(f"  [{book_id}] room={room_id[:8]} — {len(alerts)} alert(s)")
        # WHY only most recent 3: the brief is meant to be skimmable. The full
        # archive is in dialectic; this is the headline view.
        for alert in alerts[-3:]:
            ts = alert.created_at[:19]
            preview = alert.content.strip().replace("\n", " ")
            if len(preview) > 280:
                preview = preview[:277] + "..."
            section.append(f"    {ts} — {preview}")
    return section


def generate_brief(
    snapshots_dir: Path,
    ledger_dir: Path,
    book_ids: Optional[List[str]] = None,
    *,
    include_dialectic: bool = True,
    dialectic_url: str = "http://localhost:8002",
    dialectic_lookback_hours: int = 24,
    books_dir: Optional[Path] = None,
) -> str:
    """WHAT: Generate the structured morning brief.

    Reads: snapshots, cross-book flags, horizon traces, lifecycle ledger.
    Returns: plain-text brief string.
    """
    today = date.today()
    lines = [
        f"MORNING BRIEF — {today.isoformat()}",
        f"Generated: {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
        "",
    ]

    # Load snapshots
    snapshots: Dict[str, Snapshot] = {}
    if book_ids:
        for bid in book_ids:
            path = snapshots_dir / f"{bid}-latest.json"
            if path.exists():
                try:
                    snapshots[bid] = Snapshot.load(path)
                except (ValueError, json.JSONDecodeError):
                    lines.append(f"[WARN] Failed to load {bid}")
    else:
        for path in sorted(snapshots_dir.glob("*-latest.json")):
            bid = path.stem.replace("-latest", "")
            try:
                snapshots[bid] = Snapshot.load(path)
            except (ValueError, json.JSONDecodeError):
                continue

    # Per-book sections
    for bid, snap in snapshots.items():
        lines.append(f"{'='*60}")
        lines.append(f"{snap.title.upper()}")
        lines.append(f"[{_phase_label(snap.cascade_phase)}]")
        lines.append("")

        # Hot nodes — fired with high confluence
        hot = []
        for nid, state in snap.node_states.items():
            conf = snap.confluence_scores.get(nid, 0)
            if state == "fired" and conf > 0:
                hot.append((nid, conf))
        hot.sort(key=lambda x: -x[1])
        if hot:
            lines.append("  HOT NODES:")
            for nid, conf in hot:
                lines.append(f"    {nid}: confluence {conf}")

        # Approaching nodes
        approaching = [n for n, s in snap.node_states.items() if s == "approaching"]
        if approaching:
            lines.append(f"  APPROACHING: {', '.join(approaching)}")

        # Countdowns
        for cd in snap.countdowns:
            lines.append(f"  DEADLINE: {_format_countdown(cd)}")

        # Horizon trace (if v:2 snapshot)
        if snap.horizon_trace:
            h_lines = _format_horizon_trace(snap.horizon_trace, snap.node_states)
            if h_lines:
                lines.append("  FORWARD PROJECTION:")
                lines.extend(h_lines)

        # Scenario summary
        if snap.scenario_impacts:
            lines.append("  SCENARIOS:")
            for sid, impact in sorted(snap.scenario_impacts.items(),
                                       key=lambda x: -abs(x[1].get("netImpact", 0))):
                prob = impact.get("probability", 0)
                net = impact.get("netImpact", 0)
                lines.append(f"    {sid}: prob={prob:.0%} impact={net:+.1f}")

        lines.append("")

    # Cross-book analysis
    if len(snapshots) >= 2:
        report = scan_cross_book(snapshots_dir, book_ids=list(snapshots.keys()))
        if report.flags:
            lines.append(f"{'='*60}")
            lines.append("CROSS-BOOK ANALYSIS")
            lines.append("")
            for flag in report.flags:
                lines.append(f"  [{flag.severity}] {flag.flag_type}")
                lines.append(f"    {flag.detail[:200]}")
            lines.append("")

    # Lifecycle ledger summary
    ledger_lines = _format_ledger_summary(ledger_dir)
    if ledger_lines:
        lines.append(f"{'='*60}")
        lines.append("TRADE LIFECYCLE (last 5 events)")
        lines.append("")
        lines.extend(ledger_lines)
        lines.append("")

    # Dialectic curator alerts (LLM_ANNOTATOR messages from offline windows)
    # WHY: The curator generates rich contextual alerts when the operator is
    # offline. Surfacing them here is the brief's highest-value contribution
    # -- it pulls work the LLM did overnight into the place trades are managed.
    if include_dialectic:
        bd = books_dir if books_dir is not None else _REPO_ROOT / "books"
        room_map = _load_book_room_map(bd)
        # Filter the room map to the books we're actually summarizing.
        if book_ids:
            room_map = {bid: rid for bid, rid in room_map.items() if bid in book_ids}
        else:
            room_map = {bid: rid for bid, rid in room_map.items() if bid in snapshots}
        since = datetime.now(timezone.utc) - timedelta(hours=dialectic_lookback_hours)
        alert_lines = _format_dialectic_alerts(room_map, dialectic_url, since)
        if alert_lines:
            lines.append(f"{'='*60}")
            lines.append(f"DIALECTIC CURATOR ALERTS (last {dialectic_lookback_hours}h)")
            lines.append("")
            lines.extend(alert_lines)
            lines.append("")

    lines.append(f"{'='*60}")
    lines.append(f"END BRIEF — {len(snapshots)} books analyzed")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Morning brief generator")
    parser.add_argument("--snapshots-dir", default="snapshots")
    parser.add_argument("--ledger-dir", default="outcomes/trades")
    parser.add_argument("--books-dir", default="books")
    parser.add_argument("--output", default=None, help="Write to file instead of stdout")
    parser.add_argument("--no-dialectic", action="store_true",
                        help="Skip the Dialectic curator-alert pull")
    parser.add_argument("--dialectic-url", default="http://localhost:8002")
    parser.add_argument("--dialectic-lookback-hours", type=int, default=24)
    args = parser.parse_args()

    brief = generate_brief(
        Path(args.snapshots_dir), Path(args.ledger_dir),
        include_dialectic=not args.no_dialectic,
        dialectic_url=args.dialectic_url,
        dialectic_lookback_hours=args.dialectic_lookback_hours,
        books_dir=Path(args.books_dir),
    )
    if args.output:
        Path(args.output).write_text(brief)
        print(f"Brief written to {args.output}", file=sys.stderr)
    else:
        print(brief)
