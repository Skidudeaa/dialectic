#!/usr/bin/env python3
"""
Thesis Graph Generator

Transforms a graph JSON config into a complete interactive HTML dashboard
with a causal DAG visualization (Cytoscape.js), cascade tracker, scenario
engine, portfolio view, and journal.

Usage:
    python3 thesisgraph.py config.json -o output.html
    python3 thesisgraph.py config.json -o output.html --fetch
    python3 thesisgraph.py config.json -o output.html --validate --screenshot --publish

WHY: The thesis IS the graph. Positions live at specific nodes. Triggers are
threshold crossings that propagate downstream. This generator collapses the
entire mental model into a single self-contained HTML file where the math
enforces consistency: if you believe A, B, and C, then D follows with
probability X and portfolio impact Y.
"""

import argparse
import html as html_mod
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# =========================================================================
# CONFIG VALIDATION
# =========================================================================

REQUIRED_TOP = ["meta", "nodes", "edges"]
REQUIRED_NODE = ["id", "label", "type"]
REQUIRED_EDGE = ["from", "to", "strength"]
VALID_NODE_TYPES = {"event", "price", "indicator", "deadline", "gate", "constraint", "conditional", "reversal"}
VALID_PHASE_STATUS = {
    "MONITORING", "WATCHING", "NOT YET", "APPROACHING", "STARTING",
    "ACTIVE", "COMPLETE", "RESOLVED",
}
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _issue(field: str, message: str, severity: str = "error") -> dict:
    return {"field": field, "message": message, "severity": severity}


def load_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)


def validate_config(cfg: dict) -> list[dict]:
    """Validate graph config. Returns a list of structured issues.

    Each issue is {"field": <dotted-path>, "message": str, "severity": "error"|"warning"}.
    Never raises — malformed inputs surface as severity='error' entries so the
    caller (CLI, coordinator, builder API) gets a single, uniform failure surface.

    Callers needing the legacy (errors, warnings) tuple can split by severity:
        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]
    """
    issues: list[dict] = []

    try:
        if not isinstance(cfg, dict):
            issues.append(_issue("<root>", f"config must be a dict, got {type(cfg).__name__}"))
            return issues

        for field in REQUIRED_TOP:
            if field not in cfg:
                issues.append(_issue(field, f"missing required field '{field}'"))

        meta = cfg.get("meta")
        if not isinstance(meta, dict):
            issues.append(_issue("meta", "meta must be a dict"))
            meta = {}
        if not meta.get("title"):
            issues.append(_issue("meta.title", "meta.title is required"))

        # Nodes
        node_ids: set = set()
        nodes = cfg.get("nodes", [])
        if not isinstance(nodes, list):
            issues.append(_issue("nodes", "nodes must be a list"))
            nodes = []
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                issues.append(_issue(f"nodes[{i}]", "node must be a dict"))
                continue
            nid = n.get("id", f"[node {i}]")
            for f in REQUIRED_NODE:
                if f not in n:
                    issues.append(_issue(f"nodes[{nid}].{f}", f"missing '{f}'"))
            ntype = n.get("type")
            if ntype and ntype not in VALID_NODE_TYPES:
                issues.append(_issue(
                    f"nodes[{nid}].type",
                    f"invalid type '{ntype}' (valid: {sorted(VALID_NODE_TYPES)})",
                ))
            if nid in node_ids:
                issues.append(_issue(f"nodes[{nid}].id", "duplicate node ID"))
            node_ids.add(nid)

            # Threshold numeric types — reject strings like "0.7".
            for ti, th in enumerate(n.get("thresholds", []) or []):
                if not isinstance(th, dict):
                    continue
                level = th.get("level")
                if level is not None and not isinstance(level, (int, float)):
                    issues.append(_issue(
                        f"nodes[{nid}].thresholds[{ti}].level",
                        f"must be numeric, got {type(level).__name__}: {level!r}",
                    ))
                closes_req = th.get("closesRequired")
                if closes_req is not None and not isinstance(closes_req, int):
                    issues.append(_issue(
                        f"nodes[{nid}].thresholds[{ti}].closesRequired",
                        f"must be int, got {type(closes_req).__name__}",
                    ))

            # Feed schema by provider.
            feed = n.get("feed")
            if isinstance(feed, dict):
                provider = feed.get("source")
                if provider == "polymarket" and not feed.get("slug"):
                    issues.append(_issue(f"nodes[{nid}].feed", "polymarket feed requires 'slug'"))
                elif provider == "yahoo" and not feed.get("symbol"):
                    issues.append(_issue(f"nodes[{nid}].feed", "yahoo feed requires 'symbol'"))
                elif provider == "fred" and not feed.get("series"):
                    issues.append(_issue(f"nodes[{nid}].feed", "fred feed requires 'series'"))
                elif provider == "eia" and not (feed.get("series") or feed.get("route")):
                    issues.append(_issue(f"nodes[{nid}].feed", "eia feed requires 'series' or 'route'"))
                elif provider == "treasury" and not (feed.get("tenor") or feed.get("spread")):
                    issues.append(_issue(f"nodes[{nid}].feed", "treasury feed requires 'tenor' or 'spread'"))
                elif provider == "gdelt" and not (feed.get("query") or feed.get("standardQuery")):
                    issues.append(_issue(f"nodes[{nid}].feed", "gdelt feed requires 'query' or 'standardQuery'"))

        # Reference validity for gatedBy / constrainedBy — needs full node set.
        for n in nodes:
            if not isinstance(n, dict):
                continue
            nid = n.get("id", "<?>")
            for ref in n.get("gatedBy", []) or []:
                if ref not in node_ids:
                    issues.append(_issue(
                        f"nodes[{nid}].gatedBy",
                        f"references unknown node '{ref}'",
                    ))
            for ref in n.get("constrainedBy", []) or []:
                if ref not in node_ids:
                    issues.append(_issue(
                        f"nodes[{nid}].constrainedBy",
                        f"references unknown node '{ref}'",
                    ))

        # Edges
        edges = cfg.get("edges", [])
        if not isinstance(edges, list):
            issues.append(_issue("edges", "edges must be a list"))
            edges = []
        for i, e in enumerate(edges):
            if not isinstance(e, dict):
                issues.append(_issue(f"edges[{i}]", "edge must be a dict"))
                continue
            eid = f"edges[{i}]"
            for f in REQUIRED_EDGE:
                if f not in e:
                    issues.append(_issue(f"{eid}.{f}", f"missing '{f}'"))
            if e.get("from") and e["from"] not in node_ids:
                issues.append(_issue(f"{eid}.from", f"'from' node '{e['from']}' not defined"))
            if e.get("to") and e["to"] not in node_ids:
                issues.append(_issue(f"{eid}.to", f"'to' node '{e['to']}' not defined"))
            strength = e.get("strength")
            if strength is not None:
                if not isinstance(strength, (int, float)):
                    issues.append(_issue(
                        f"{eid}.strength",
                        f"must be numeric in (0,1], got {type(strength).__name__}: {strength!r}",
                    ))
                elif not (0 < strength <= 1):
                    issues.append(_issue(
                        f"{eid}.strength",
                        f"strength {strength} outside (0,1]",
                        severity="warning",
                    ))
            amp = e.get("amplification")
            if amp is not None and not isinstance(amp, (int, float)):
                issues.append(_issue(
                    f"{eid}.amplification",
                    f"must be numeric, got {type(amp).__name__}",
                ))
            # Lag format validity — parse_lag_days returns a conservative 30-day
            # fallback for unparseable strings. Flag those so operators notice.
            lag = e.get("lag")
            if lag and isinstance(lag, str) and lag.lower() != "immediate":
                if not re.match(
                    r"^(date-gated\s+.+|\d+(?:\s*-\s*\d+)?\s*(day|week|month)s?)$",
                    lag.strip(),
                    re.IGNORECASE,
                ):
                    issues.append(_issue(
                        f"{eid}.lag",
                        f"unparseable lag '{lag}' — will fall back to 30d; "
                        "use 'immediate', 'N weeks', 'N-M months', or 'date-gated <date>'",
                        severity="warning",
                    ))

        # Instruments
        # WHY: The instruments dict may contain an "overlays" key with nested
        # overlay definitions (dicts, not arrays). Skip non-list values.
        instruments = cfg.get("instruments", {})
        if instruments and not isinstance(instruments, dict):
            issues.append(_issue("instruments", "instruments must be a dict keyed by node id"))
            instruments = {}
        seen_inst_ids: set = set()
        for nid, insts in instruments.items():
            if not isinstance(insts, list):
                continue
            if nid not in node_ids and nid != "reserve":
                issues.append(_issue(
                    f"instruments.{nid}",
                    f"node '{nid}' not found in graph",
                    severity="warning",
                ))
            for inst in insts:
                if not isinstance(inst, dict):
                    issues.append(_issue(f"instruments.{nid}", "instrument must be a dict"))
                    continue
                iid = inst.get("id")
                if not iid:
                    issues.append(_issue(f"instruments.{nid}", "missing instrument 'id'"))
                    continue
                if iid in seen_inst_ids:
                    issues.append(_issue(
                        f"instruments.{nid}.{iid}",
                        f"duplicate instrument id '{iid}'",
                    ))
                seen_inst_ids.add(iid)

        # marketFields — list of {key, label, value, step, nodeId} entries
        mf = cfg.get("marketFields")
        if mf is not None:
            if not isinstance(mf, list):
                issues.append(_issue("marketFields", "marketFields must be a list"))
            else:
                for i, field in enumerate(mf):
                    if not isinstance(field, dict):
                        issues.append(_issue(
                            f"marketFields[{i}]", "each marketField must be a dict"
                        ))
                        continue
                    if not field.get("key"):
                        issues.append(_issue(
                            f"marketFields[{i}].key", "marketField missing 'key'"
                        ))
                    value = field.get("value")
                    if value is not None and not isinstance(value, (int, float)):
                        issues.append(_issue(
                            f"marketFields[{i}].value",
                            f"must be numeric, got {type(value).__name__}",
                        ))

        # Scenarios
        for si, s in enumerate(cfg.get("scenarios", []) or []):
            if not isinstance(s, dict):
                issues.append(_issue(f"scenarios[{si}]", "scenario must be a dict"))
                continue
            sid = s.get("id", f"[scenario {si}]")
            if "id" not in s:
                issues.append(_issue(f"scenarios[{si}].id", "scenario missing 'id'"))
            prob = s.get("probability")
            if prob is not None:
                if not isinstance(prob, (int, float)):
                    issues.append(_issue(
                        f"scenarios[{sid}].probability",
                        f"must be numeric in [0,1], got {type(prob).__name__}",
                    ))
                elif not (0 <= prob <= 1):
                    issues.append(_issue(
                        f"scenarios[{sid}].probability",
                        f"{prob} outside [0,1]",
                    ))
            for override_node in (s.get("overrides") or {}):
                if override_node not in node_ids:
                    issues.append(_issue(
                        f"scenarios[{sid}].overrides",
                        f"override node '{override_node}' not in graph",
                        severity="warning",
                    ))

        # Cascade phases
        phases = cfg.get("cascadePhases")
        if phases is not None:
            if not isinstance(phases, dict):
                issues.append(_issue("cascadePhases", "cascadePhases must be a dict"))
            else:
                expected = {"shock", "transmission", "amplification", "policyResponse", "resolution"}
                actual = set(phases.keys())
                missing = expected - actual
                if missing:
                    issues.append(_issue(
                        "cascadePhases",
                        f"missing phases {sorted(missing)}",
                        severity="warning",
                    ))
                for pk, pv in phases.items():
                    if not isinstance(pv, dict):
                        continue
                    status = pv.get("status")
                    if status and str(status).upper() not in VALID_PHASE_STATUS:
                        issues.append(_issue(
                            f"cascadePhases.{pk}.status",
                            f"invalid status '{status}' (valid: {sorted(VALID_PHASE_STATUS)})",
                        ))

        # Cycle check via topo sort. A malformed edge dict would otherwise
        # raise a KeyError deep in the graph walk; catch that so the validator
        # always returns a structured result.
        if isinstance(cfg.get("nodes"), list) and isinstance(cfg.get("edges"), list):
            try:
                topo_sort(cfg["nodes"], cfg["edges"])
            except (ValueError, KeyError, TypeError) as ex:
                issues.append(_issue("<graph>", f"topo sort failed: {ex}"))

    except Exception as ex:
        # Belt-and-suspenders: any unexpected validator error surfaces as a
        # structured issue so callers never see a raw exception.
        issues.append(_issue(
            "<validator>",
            f"validator internal error: {type(ex).__name__}: {ex}",
        ))

    return issues


# =========================================================================
# GRAPH PROPAGATION (Python-side, mirrored in JS)
# =========================================================================

def topo_sort(nodes: list, edges: list) -> list[str]:
    """Kahn's algorithm for topological sort. Returns ordered node IDs."""
    adj = {n["id"]: [] for n in nodes}
    indeg = {n["id"]: 0 for n in nodes}
    for e in edges:
        src, dst = e["from"], e["to"]
        if src in adj and dst in adj:
            adj[src].append(dst)
            indeg[dst] += 1
    queue = [nid for nid, d in indeg.items() if d == 0]
    result = []
    while queue:
        nid = queue.pop(0)
        result.append(nid)
        for child in adj[nid]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    if len(result) < len(nodes):
        raise ValueError("Cycle detected in graph")
    return result


def eval_node_state(node: dict, upstream_states: dict, edges: list) -> str:
    """Evaluate a single node's state based on type + upstream.

    Returns one of: 'fired', 'approaching', 'stable', 'gated', 'constrained', 'monitoring'
    """
    ntype = node.get("type", "indicator")

    # Event nodes: state field directly
    if ntype == "event":
        st = node.get("state", "monitoring")
        if st in ("active", "fired"):
            return "fired"
        if st == "resolved":
            return "stable"
        if st == "partial":
            return "approaching"
        return "monitoring"

    # Price nodes: compare current vs thresholds
    if ntype == "price":
        current = node.get("current")
        thresholds = node.get("thresholds", [])
        if current is None or not thresholds:
            return "monitoring"
        # Check from highest to lowest
        sorted_th = sorted(thresholds, key=lambda t: t.get("level", 0), reverse=True)
        for th in sorted_th:
            lvl = th.get("level", 0)
            if current >= lvl:
                # WHY: closesRequired gates firing on N daily closes above the level.
                # The node-level `closesObserved` counter is populated by the
                # derived-indicators pass (local Yahoo close series) or by Pine Script
                # webhooks. When it reaches closesRequired we promote in Python too;
                # otherwise we stay "approaching" and the browser JS can promote
                # later if the user enters additional closes interactively.
                closes_req = th.get("closesRequired")
                if closes_req and closes_req > 0:
                    closes_obs = int(node.get("closesObserved", 0) or 0)
                    if closes_obs >= closes_req:
                        return "fired"
                    return "approaching"
                return "fired"
        # Check approaching (within 5% of lowest threshold)
        lowest = min(t.get("level", 0) for t in thresholds)
        if lowest > 0 and current / lowest >= 0.95:
            return "approaching"
        return "stable"

    # Indicator nodes: check if upstream is firing
    if ntype == "indicator":
        # Count incoming fired/approaching edges
        incoming = [e for e in edges if e["to"] == node["id"]]
        if not incoming:
            return "monitoring"
        fired_count = sum(1 for e in incoming if upstream_states.get(e["from"]) == "fired")
        appr_count = sum(1 for e in incoming if upstream_states.get(e["from"]) == "approaching")
        if fired_count > 0:
            return "fired" if fired_count >= len(incoming) * 0.5 else "approaching"
        if appr_count > 0:
            return "approaching"
        return "stable"

    # Deadline nodes: check conditions + date
    if ntype == "deadline":
        deadline_str = node.get("deadline")
        conditions = node.get("conditions", [])
        if deadline_str:
            try:
                dl = date.fromisoformat(deadline_str)
                today = date.today()
                days_left = (dl - today).days
                if days_left < 0:
                    # Past deadline
                    # WHY: deadline nodes are irreversible once fired
                    return "fired"
                if days_left <= 14:
                    # Check if any upstream conditions met
                    for cond in conditions:
                        parts = cond.split(".")
                        if len(parts) >= 1 and upstream_states.get(parts[0]) in ("fired", "approaching"):
                            return "approaching"
                    return "approaching" if days_left <= 7 else "gated"
            except (ValueError, TypeError):
                pass
        return "gated"

    # Gate nodes: binary fired or monitoring
    if ntype == "gate":
        condition = node.get("condition", "")
        current = node.get("current")
        # Gates require manual confirmation, default monitoring
        return "monitoring"

    # Constraint nodes: active (blocking) or inactive
    if ntype == "constraint":
        current = node.get("current")
        threshold = node.get("threshold")
        if current is not None and threshold is not None:
            if current > threshold:
                return "constrained"
        return "stable"

    # Conditional nodes: gated if gatedBy not fired, constrained if constraint active
    if ntype == "conditional":
        gated_by = node.get("gatedBy", [])
        constrained_by = node.get("constrainedBy", [])
        # Check constraints first
        for cid in constrained_by:
            if upstream_states.get(cid) == "constrained":
                return "constrained"
        # Check gates
        all_gates_open = all(upstream_states.get(g) == "fired" for g in gated_by)
        if not all_gates_open:
            return "gated"
        return "approaching"

    # Reversal nodes: check threshold direction for de-escalation
    if ntype == "reversal":
        current = node.get("current")
        threshold = node.get("threshold")
        if current is not None and threshold is not None:
            if current <= threshold:
                # WHY: Same closesRequired gating as price nodes — see comment above.
                closes_req = node.get("closesRequired")
                if closes_req and closes_req > 0:
                    closes_obs = int(node.get("closesObserved", 0) or 0)
                    if closes_obs >= closes_req:
                        return "fired"
                    return "approaching"
                return "fired"
            ratio = current / threshold if threshold else 999
            if ratio < 1.12:
                return "approaching"
        return "stable"

    return "monitoring"


def propagate(cfg: dict) -> dict:
    """Run full propagation through the graph. Returns {nodeId: state}."""
    nodes = cfg["nodes"]
    edges = cfg["edges"]
    order = topo_sort(nodes, edges)
    node_map = {n["id"]: n for n in nodes}
    states = {}

    for nid in order:
        node = node_map[nid]
        states[nid] = eval_node_state(node, states, edges)

    return states


def score_confluence(cfg: dict, states: dict) -> dict:
    """Score fan-in nodes. Returns {nodeId: score} for nodes with fan-in >= 2."""
    edges = cfg["edges"]
    node_map = {n["id"]: n for n in cfg["nodes"]}
    scores = {}

    # Build reverse adjacency (who feeds into each node)
    fan_in = {}
    for e in edges:
        fan_in.setdefault(e["to"], []).append(e)

    for nid, incoming in fan_in.items():
        if len(incoming) < 2:
            continue
        score = 0.0
        for e in incoming:
            src_state = states.get(e["from"], "stable")
            signal = 1.0 if src_state == "fired" else (0.5 if src_state == "approaching" else 0.0)
            # WHY: amplification models crack-spread magnification, supply-chain
            # concentration, or leverage effects that make the downstream signal
            # stronger (>1.0) or weaker (<1.0) than the raw strength implies.
            # Default 1.0 preserves existing behavior for edges without the field.
            score += signal * e.get("strength", 0.5) * e.get("amplification", 1.0)
        scores[nid] = round(score, 2)

    return scores


def parse_lag_days(lag_str: str, ref_date: date | None = None) -> int:
    """Parse an edge lag string into a midpoint day count.

    WHY: Edge lag declarations like "1-2 weeks" are currently decorative —
    propagate() ignores them. This parser makes them machine-readable so
    propagate_at_horizon() can filter edges by temporal reachability.

    Handles: "immediate", "N week(s)", "N-M weeks", "N month(s)", "N-M months",
    "date-gated <date_str>". Returns midpoint of the range in days.
    """
    if ref_date is None:
        ref_date = date.today()

    if not lag_str or lag_str.lower() == "immediate":
        return 1

    # Date-gated: "date-gated Apr 15" or "date-gated 2026-04-15"
    if lag_str.lower().startswith("date-gated"):
        date_part = lag_str[len("date-gated"):].strip()
        # Try ISO format first
        try:
            target = date.fromisoformat(date_part)
            return max(0, (target - ref_date).days)
        except ValueError:
            pass
        # Try "Apr 15" / "Apr 15 2026" style
        import calendar
        months = {v.lower(): k for k, v in enumerate(calendar.month_abbr) if k}
        months.update({v.lower(): k for k, v in enumerate(calendar.month_name) if k})
        parts = date_part.split()
        if len(parts) >= 2 and parts[0].lower().rstrip(",") in months:
            month = months[parts[0].lower().rstrip(",")]
            day_num = int(parts[1].rstrip(","))
            year = int(parts[2]) if len(parts) >= 3 else ref_date.year
            target = date(year, month, day_num)
            if target < ref_date and len(parts) < 3:
                target = date(year + 1, month, day_num)
            return max(0, (target - ref_date).days)
        return 30  # fallback

    # Range: "1-2 weeks", "2-4 months", "1 week", "3 months"
    m = re.match(r"(\d+)(?:\s*-\s*(\d+))?\s*(day|week|month)s?", lag_str.strip(), re.IGNORECASE)
    if m:
        low = int(m.group(1))
        high = int(m.group(2)) if m.group(2) else low
        unit = m.group(3).lower()
        multiplier = {"day": 1, "week": 7, "month": 30}[unit]
        return int((low + high) / 2 * multiplier)

    return 30  # conservative fallback for unparseable strings


def compute_arrival_times(cfg: dict,
                          ref_date: date | None = None) -> dict[str, float]:
    """Shortest-path arrival time at each node from any self-firing source.

    WHY: The horizon filter needs cumulative path lag, not per-edge lag. A
    chain A -(7d)-> B -(7d)-> C should see C arrive at T+14, not T+7. This
    helper computes the earliest day each node could receive a causal signal
    via any path from a node that is already firing / approaching at T=0.

    A node "self-fires" when eval_node_state(node, {}, []) returns fired or
    approaching — that is, the node would be firing even with no upstream.
    Events with state=fired, price nodes above threshold, past-deadline
    deadline nodes, etc.

    Nodes that depend on upstream see arrival = min(src_arrival + lag(edge)).
    Unreachable nodes return float("inf").
    """
    order = topo_sort(cfg["nodes"], cfg["edges"])
    node_map = {n["id"]: n for n in cfg["nodes"]}
    incoming_by_node: dict[str, list] = {nid: [] for nid in order}
    for e in cfg["edges"]:
        if e.get("to") in incoming_by_node:
            incoming_by_node[e["to"]].append(e)

    arrival: dict[str, float] = {nid: float("inf") for nid in order}
    for nid in order:
        node = node_map[nid]
        # Self-firing sources seed at 0.
        self_state = eval_node_state(node, {}, [])
        if self_state in ("fired", "approaching"):
            arrival[nid] = 0
        # Relax via incoming edges. Topo order guarantees src is settled.
        for e in incoming_by_node[nid]:
            src_arr = arrival.get(e["from"], float("inf"))
            if src_arr == float("inf"):
                continue
            lag = parse_lag_days(e.get("lag", "immediate"), ref_date)
            candidate = src_arr + lag
            if candidate < arrival[nid]:
                arrival[nid] = candidate

    return arrival


def propagate_at_horizon(cfg: dict, horizon_days: int,
                         ref_date: date | None = None) -> dict:
    """Run propagation filtered by cumulative temporal reachability.

    WHY: The standard propagate() treats all edges as instantaneous — lag
    declarations are decorative. This function keeps only edges whose
    CUMULATIVE arrival at the destination is within the horizon, then runs
    propagate() + score_confluence() on the time-filtered graph.

    An edge from X to Y is kept iff (arrival_time[X] + lag(edge)) <= horizon.
    Two 7-day edges in series correctly require T>=14 for the downstream
    node to receive signal, not T>=7.

    Returns {"states": {nodeId: state}, "confluence": {nodeId: score}}.
    """
    import copy
    hcfg = copy.deepcopy(cfg)
    arrival = compute_arrival_times(hcfg, ref_date)

    kept_edges = []
    for e in hcfg["edges"]:
        src_arr = arrival.get(e.get("from"), float("inf"))
        if src_arr == float("inf"):
            # Upstream never fires under current state — edge carries no
            # signal at any horizon. Drop it so downstream doesn't see noise.
            continue
        lag = parse_lag_days(e.get("lag", "immediate"), ref_date)
        if src_arr + lag <= horizon_days:
            kept_edges.append(e)
    hcfg["edges"] = kept_edges

    states = propagate(hcfg)
    confluence = score_confluence(hcfg, states)
    return {"states": states, "confluence": confluence}


def get_current_phase(cfg: dict) -> tuple[int, str]:
    """Determine current cascade phase from config. Returns (phase_number, phase_key)."""
    phases = cfg.get("cascadePhases", {})
    # Order: shock=1, transmission=2, amplification=3, policyResponse=4, resolution=5
    phase_order = ["shock", "transmission", "amplification", "policyResponse", "resolution"]
    current = 1
    current_key = "shock"
    for i, key in enumerate(phase_order, 1):
        p = phases.get(key, {})
        status = p.get("status", "").upper()
        if status in ("COMPLETE", "STARTING", "ACTIVE"):
            current = i
            current_key = key
        elif status in ("APPROACHING",):
            current = i
            current_key = key
            break
    return current, current_key


def eval_scenario(cfg: dict, scenario: dict, base_states: dict = None) -> tuple[dict, dict]:
    """Apply scenario overrides, re-propagate, compute portfolio impact.
    Returns (new_states, portfolio_impact).
    """
    import copy
    scfg = copy.deepcopy(cfg)
    overrides = scenario.get("overrides", {})
    node_map = {n["id"]: n for n in scfg["nodes"]}

    for nid, val in overrides.items():
        if nid not in node_map:
            continue
        node = node_map[nid]
        if isinstance(val, str):
            # String override sets node state directly
            node["state"] = val
        elif isinstance(val, (int, float)):
            # Numeric override sets node.current
            node["current"] = val

    new_states = propagate(scfg)

    # Compute portfolio impact using instrument betas
    instruments = cfg.get("instruments", {})
    impact = {}
    if base_states is None:
        base_states = propagate(cfg)

    for nid, insts in instruments.items():
        if not isinstance(insts, list):
            continue
        for inst in insts:
            iid = inst.get("id")
            beta = inst.get("beta", 0.5)
            ref = inst.get("ref", 0)
            if ref <= 0:
                continue

            base_st = base_states.get(nid, "stable")
            new_st = new_states.get(nid, "stable")

            # Estimate price move based on state transition
            state_multiplier = {"fired": 1.0, "approaching": 0.4, "stable": 0.0,
                                "gated": -0.1, "constrained": -0.2, "monitoring": 0.0}
            base_sig = state_multiplier.get(base_st, 0)
            new_sig = state_multiplier.get(new_st, 0)
            delta_sig = new_sig - base_sig

            # WHY: Beta * signal delta * reference move gives estimated % impact
            # This is a heuristic: real beta is against the specific node's price,
            # scaled to a +-20% reference move for a full state transition.
            pct_impact = beta * delta_sig * 20  # +-20% max move per full signal
            dollar_impact = ref * pct_impact / 100 if ref else 0

            impact[iid] = {
                "pctImpact": round(pct_impact, 1),
                "dollarImpact": round(dollar_impact, 2),
                "from": base_st,
                "to": new_st,
            }

    return new_states, impact


# =========================================================================
# STATE EXPORT
# =========================================================================

def export_state(cfg: dict, states: dict, confluence: dict,
                 phase_num: int, phase_key: str,
                 scenarios_result: list[tuple[dict, dict, dict]],
                 today: date | None = None) -> dict:
    """Build the snapshot JSON for cross-system integration.

    Returns a dict matching the snapshot shape defined in INTEGRATION.md.
    The `today` parameter is injectable for testing (defaults to date.today()).
    """
    if today is None:
        today = date.today()

    meta = cfg.get("meta", {})
    nodes = cfg.get("nodes", [])
    node_map = {n["id"]: n for n in nodes}

    # --- nodeStates: direct from propagation output ---
    node_states = dict(states)

    # --- confluenceScores: direct from score_confluence output ---
    confluence_scores = dict(confluence)

    # --- cascadePhase: from phase info + config status ---
    phases = cfg.get("cascadePhases", {})
    phase_status = "UNKNOWN"
    if phase_key in phases:
        phase_status = phases[phase_key].get("status", "UNKNOWN")
    cascade_phase = {
        "number": phase_num,
        "key": phase_key,
        "status": phase_status,
    }

    # --- countdowns: find all deadline nodes, compute daysRemaining ---
    countdowns = []
    for node in nodes:
        if node.get("type") != "deadline":
            continue
        deadline_str = node.get("deadline")
        if not deadline_str:
            continue
        try:
            dl = date.fromisoformat(deadline_str)
            days_remaining = max(0, (dl - today).days)
            countdowns.append({
                "nodeId": node["id"],
                "label": node.get("label", node["id"]),
                "deadline": deadline_str,
                "daysRemaining": days_remaining,
            })
        except (ValueError, TypeError):
            continue

    # --- marketSnapshot: from marketFields config ---
    # WHY: marketFields have their own `value` which may differ from the
    # associated node's `current` (e.g. goldSpot=4492 vs dxy-stress.current=100.18).
    # The marketField value is the market price; nodeId is just a graph association.
    market_snapshot = {}
    for mf in cfg.get("marketFields", []):
        key = mf.get("key")
        if not key:
            continue
        value = mf.get("value")
        if value is not None:
            market_snapshot[key] = value

    # --- scenarioImpacts: from eval_scenario results ---
    scenario_impacts = {}
    for scenario, new_states, impact in scenarios_result:
        sid = scenario.get("id", "unknown")
        probability = scenario.get("probability", 0)
        # Compute net impact as probability-weighted sum of pctImpacts
        total_pct = sum(v.get("pctImpact", 0) for v in impact.values())
        net_impact = round(probability * total_pct, 1) if impact else 0
        scenario_impacts[sid] = {
            "probability": probability,
            "netImpact": net_impact,
        }

    # --- portfolioSummary: from instruments config ---
    instruments = cfg.get("instruments", {})
    monthly_budget = meta.get("monthlyBudget", 0)
    positions = []
    sgov_available = 0

    for nid, insts in instruments.items():
        if not isinstance(insts, list):
            continue
        for inst in insts:
            iid = inst.get("id", "?")
            monthly = inst.get("monthly", 0)
            if inst.get("isReserve") and iid.upper() == "SGOV":
                sgov_available = monthly
            if monthly > 0:
                positions.append((iid, monthly))

    # Sort by monthly allocation descending, take top positions
    positions.sort(key=lambda x: -x[1])
    top_positions = [f"{iid} ${monthly}/mo" for iid, monthly in positions[:6]]

    portfolio_summary = {
        "monthlyBudget": monthly_budget,
        "topPositions": top_positions,
        "sgovAvailable": sgov_available,
    }

    # --- horizonTrace: time-aware forward propagation ---
    # WHY: Shows WHEN each downstream node fires given current upstream states.
    # The standard propagation treats all edges as instantaneous; horizon trace
    # adds the temporal dimension by filtering edges by lag reachability.
    horizon_trace = {}
    for h in (7, 28, 90):
        result = propagate_at_horizon(cfg, h, ref_date=today)
        horizon_trace[f"T+{h}d"] = {
            "states": result["states"],
            "confluence": result["confluence"],
        }

    # --- tvIndicators: non-causal snapshot overlay ---
    # WHY top-level: Dialectic consumers and diff-snapshots scan top-level
    # keys; embedding under marketSnapshot would mix derived overlays with
    # raw prices. Always emitted (possibly empty) so v:2 snapshot shape is
    # stable regardless of whether any node has derivedIndicators.
    tv_indicators: dict = {}
    for node in nodes:
        tv = node.get("tvIndicators")
        if isinstance(tv, dict) and tv:
            tv_indicators[node["id"]] = dict(tv)

    # --- feedFreshness: per-source fetched_at / ttl for UI staleness ---
    # WHY: fetch_prices / fetch_polymarket / fetch_fred / compute_derived_indicators
    # stamp cfg["_feed_freshness"][source] = {source, fetchedAt, ttlSeconds, detail}
    # on a successful fetch. Promote that into the snapshot so downstream
    # consumers (WS broadcast, bootstrap, diff, frontend) know what's fresh.
    # Always emitted (possibly empty) to keep the v:2 shape stable.
    feed_freshness = dict(cfg.get("_feed_freshness", {}))

    # --- Assemble snapshot ---
    snapshot = {
        "v": 2,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": meta.get("title", "Untitled Thesis"),
        "nodeStates": node_states,
        "confluenceScores": confluence_scores,
        "cascadePhase": cascade_phase,
        "countdowns": countdowns,
        "marketSnapshot": market_snapshot,
        "scenarioImpacts": scenario_impacts,
        "feedFreshness": feed_freshness,
        "portfolioSummary": portfolio_summary,
        "horizonTrace": horizon_trace,
        "tvIndicators": tv_indicators,
    }

    return snapshot


# =========================================================================
# PRICE FETCHER
# =========================================================================

def fetch_prices(cfg: dict, retries: int = 2) -> dict:
    """Fetch current prices from Yahoo Finance. Mutates and returns cfg."""
    import urllib.parse

    # Collect all yahoo symbols from node feeds
    symbols = []
    sym_to_node = {}
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "yahoo" and "symbol" in feed:
                sym = feed["symbol"]
                if sym not in sym_to_node:
                    symbols.append(sym)
                    sym_to_node[sym] = node["id"]

    # Also collect instrument tickers for price fetch
    inst_syms = []
    for nid, insts in cfg.get("instruments", {}).items():
        if not isinstance(insts, list):
            continue
        for inst in insts:
            iid = inst.get("id")
            if iid and iid not in inst_syms:
                inst_syms.append(iid)

    all_syms = symbols + inst_syms
    if not all_syms:
        print("  No fetchable symbols found, skipping", file=sys.stderr)
        return cfg

    yahoo_base = "https://query1.finance.yahoo.com/v7/finance/spark"
    batch_size = 8
    all_results = []

    # WHY: Python is not subject to CORS — call Yahoo Finance directly.
    # The browser-side JS fetch in the generated dashboard now routes through
    # our own /api/relay/yahoo endpoint (see web/routes/relay.py); the prior
    # allorigins.win dependency has been retired.
    for i in range(0, len(all_syms), batch_size):
        batch = all_syms[i:i + batch_size]
        yahoo_url = f"{yahoo_base}?symbols={','.join(batch)}&range=1d&interval=1d"

        for attempt in range(1, retries + 1):
            try:
                req = Request(yahoo_url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=20) as resp:
                    batch_data = json.loads(resp.read())
                    all_results.extend(batch_data.get("spark", {}).get("result", []))
                break
            except (URLError, TimeoutError, OSError) as e:
                if attempt < retries:
                    time.sleep(2)
                else:
                    print(f"  Batch {i // batch_size + 1} failed: {e}", file=sys.stderr)
            except Exception as e:
                print(f"  Batch {i // batch_size + 1} error: {e}", file=sys.stderr)
                break
        if i + batch_size < len(all_syms):
            time.sleep(1.5)

    if not all_results:
        print("  Warning: no usable price data returned", file=sys.stderr)
        return cfg

    count = 0
    node_map = {n["id"]: n for n in cfg["nodes"]}
    for item in all_results:
        sym = item.get("symbol")
        if not sym:
            continue
        meta = item.get("response", [{}])[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            continue

        # Update node current price
        if sym in sym_to_node:
            nid = sym_to_node[sym]
            if nid in node_map and "current" in node_map[nid]:
                old = node_map[nid]["current"]
                node_map[nid]["current"] = round(price, 2)
                print(f"  {nid}: ${old} -> ${round(price, 2)}", file=sys.stderr)
                count += 1

        # Update instrument ref prices
        for nid, insts in cfg.get("instruments", {}).items():
            if not isinstance(insts, list):
                continue
            for inst in insts:
                if inst.get("id") == sym:
                    old = inst.get("ref", 0)
                    inst["ref"] = round(price, 2)
                    count += 1

    print(f"  Fetched {count}/{len(all_syms)} prices", file=sys.stderr)

    # Stamp feed freshness for the Yahoo source if we got anything back.
    # `cfg["_feed_freshness"]` is a private namespace picked up by
    # export_state() and promoted to snapshot["feedFreshness"]. UI reads that
    # to paint amber badges once `now - fetched_at > ttl_seconds`.
    if count > 0:
        _stamp_feed_freshness(
            cfg,
            source="yahoo",
            ttl_seconds=300,  # 5 min — spark API is roughly 15-min-delayed
            detail=f"{count}/{len(all_syms)} symbols",
        )
    return cfg


def _stamp_feed_freshness(cfg: dict, *, source: str, ttl_seconds: int,
                          detail: str | None = None) -> None:
    """Record that `source` completed a live fetch just now.

    Keeps the write on a private cfg namespace so it propagates through the
    propagate() → export_state() pipeline without polluting the book JSON
    schema. Idempotent — a second call for the same source overwrites.
    """
    freshness = cfg.setdefault("_feed_freshness", {})
    entry: dict = {
        "source": source,
        "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttlSeconds": int(ttl_seconds),
    }
    if detail:
        entry["detail"] = detail
    freshness[source] = entry


def update_config_file(config_path: str, cfg: dict) -> None:
    """Write fetched prices back into the JSON config file.

    WHY: Atomic write via tmp+rename prevents config corruption if the process
    is killed or disk fills up mid-write. os.replace() is atomic on POSIX.

    Underscore-prefixed top-level keys (_feed_freshness, _ohlcv, _close_events)
    are transient runtime state and MUST NOT be persisted to the book JSON.
    They are stripped before write to keep the on-disk schema clean.
    """
    # Shallow copy without `_`-prefixed keys; values stay shared so we don't
    # duplicate the whole graph.
    to_write = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
    tmp_path = config_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(to_write, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, config_path)
        print(f"  Config updated: {config_path}", file=sys.stderr)
    except Exception:
        # Clean up the partial temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def fetch_polymarket(cfg: dict) -> dict:
    """Fetch live probabilities from Polymarket for nodes with polymarket feeds.

    WHY separate from fetch_prices: Polymarket provides prediction market
    probabilities (0-1 event likelihood), not asset prices. These update
    node 'probability' fields, not 'current' price fields. Different data
    type, different API, different update semantics.

    Scans all nodes for feeds with source="polymarket", batches the slugs,
    calls the polymarket module, and writes probabilities back into the cfg.
    """
    # WHY dynamic import: the polymarket module lives in tools/data_fetch/.
    # We resolve the path relative to this script so it works regardless
    # of the working directory.
    polymarket_dir = os.path.join(os.path.dirname(__file__), "..", "data_fetch")
    polymarket_dir = os.path.abspath(polymarket_dir)

    if not os.path.isfile(os.path.join(polymarket_dir, "polymarket.py")):
        print("  polymarket: module not found, skipping", file=sys.stderr)
        return cfg

    # WHY sys.path insert: stdlib-only constraint means no pip install.
    # We add the module directory to sys.path so we can import it directly.
    if polymarket_dir not in sys.path:
        sys.path.insert(0, polymarket_dir)

    try:
        import polymarket as pm
    except ImportError as e:
        print(f"  polymarket: import failed: {e}", file=sys.stderr)
        return cfg

    # Collect all polymarket slugs from node feeds
    slug_to_nodes: dict = {}  # slug -> list of node IDs that use this slug
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "polymarket" and "market" in feed:
                slug = feed["market"]
                if slug not in slug_to_nodes:
                    slug_to_nodes[slug] = []
                slug_to_nodes[slug].append(node["id"])

    if not slug_to_nodes:
        print("  polymarket: no polymarket feeds found in nodes", file=sys.stderr)
        return cfg

    slugs = list(slug_to_nodes.keys())
    print(f"  polymarket: fetching {len(slugs)} market(s)...", file=sys.stderr)

    # Fetch all probabilities in one batch
    results = pm.fetch_markets(slugs)

    # Write probabilities back into matching nodes
    node_map = {n["id"]: n for n in cfg["nodes"]}
    count = 0
    for slug, prob in results.items():
        if prob is None:
            print(f"  polymarket: {slug} -> no data", file=sys.stderr)
            continue
        for nid in slug_to_nodes.get(slug, []):
            if nid in node_map:
                old_prob = node_map[nid].get("probability")
                node_map[nid]["probability"] = round(prob, 4)
                old_str = f"{old_prob:.1%}" if old_prob is not None else "none"
                print(f"  polymarket: {nid}: {old_str} -> {prob:.1%}", file=sys.stderr)
                count += 1

    print(f"  polymarket: updated {count}/{len(slugs)} node(s)", file=sys.stderr)

    # Stamp freshness if at least one slug resolved. Polymarket prediction
    # markets update on minutes-to-tens-of-minutes cadence; 15 min TTL is a
    # reasonable "amber if older than this" bound.
    if count > 0:
        _stamp_feed_freshness(
            cfg,
            source="polymarket",
            ttl_seconds=900,
            detail=f"{count}/{len(slugs)} markets",
        )
    return cfg


def fetch_fred(cfg: dict) -> dict:
    """Fetch live macro series from FRED for nodes with fred feeds.

    WHY separate from fetch_prices / fetch_polymarket: FRED is end-of-day
    macro data (Treasury yields, FX rates, policy proxies). It writes to
    node 'current' (like Yahoo) but uses a different API + auth model
    (requires FRED_API_KEY). Keeping the dispatch separate lets us stamp
    feed-freshness with the right TTL (3600s, FRED publishes once/day).

    Additive: nodes without `"source": "fred"` feeds are untouched.
    Silent skip if FRED_API_KEY is missing — the operator may not have
    configured FRED yet, and we don't want to abort the whole --fetch
    run for a missing optional key.
    """
    # WHY dynamic import: the fred module lives in tools/data_fetch/.
    # Resolve relative to this script so cwd doesn't matter.
    fred_dir = os.path.join(os.path.dirname(__file__), "..", "data_fetch")
    fred_dir = os.path.abspath(fred_dir)

    if not os.path.isfile(os.path.join(fred_dir, "fred.py")):
        print("  fred: module not found, skipping", file=sys.stderr)
        return cfg

    if fred_dir not in sys.path:
        sys.path.insert(0, fred_dir)

    try:
        import fred as fred_mod  # type: ignore[import-not-found]
    except ImportError as e:
        print(f"  fred: import failed: {e}", file=sys.stderr)
        return cfg

    # Collect all FRED series IDs from node feeds. One series can map to
    # multiple nodes (e.g. DGS10 used by both us-10y and recession-risk).
    series_to_nodes: dict = {}
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "fred" and "series" in feed:
                series_id = feed["series"]
                if series_id not in series_to_nodes:
                    series_to_nodes[series_id] = []
                series_to_nodes[series_id].append(node["id"])

    if not series_to_nodes:
        return cfg

    series_ids = list(series_to_nodes.keys())
    print(f"  fred: fetching {len(series_ids)} series...", file=sys.stderr)

    try:
        results = fred_mod.fetch_series_batch(series_ids)
    except fred_mod.FredAuthError as e:
        # WHY silent-on-missing-key: FRED is optional. Operators running
        # the engine without a FRED key still get Yahoo + Polymarket data.
        # Surface a single line to stderr so the operator knows why the
        # fred-sourced nodes weren't updated, but don't abort.
        print(f"  fred: skipped ({e})", file=sys.stderr)
        return cfg
    except Exception as e:
        print(f"  fred: batch fetch failed: {e}", file=sys.stderr)
        return cfg

    # Write values back into matching node 'current' fields.
    node_map = {n["id"]: n for n in cfg["nodes"]}
    count = 0
    for series_id, obs in results.items():
        if not isinstance(obs, dict) or "value" not in obs:
            continue
        value = obs["value"]
        for nid in series_to_nodes.get(series_id, []):
            if nid not in node_map:
                continue
            node = node_map[nid]
            # WHY only update if 'current' already exists: indicator-type
            # nodes (no current price field) should not silently grow one.
            if "current" in node:
                old = node["current"]
                node["current"] = round(value, 4)
                print(
                    f"  fred: {nid} ({series_id}): {old} -> "
                    f"{round(value, 4)} (obs {obs.get('observation_date')})",
                    file=sys.stderr,
                )
                count += 1

    print(
        f"  fred: updated {count} node(s) from {len(results)}/"
        f"{len(series_ids)} series",
        file=sys.stderr,
    )

    # Stamp freshness if at least one series resolved. FRED publishes most
    # daily series once per business day around 16:00 ET — 3600s TTL keeps
    # the badge green during a normal coordinator tick interval, and goes
    # amber if a tick missed (or FRED is mid-publish).
    if results:
        _stamp_feed_freshness(
            cfg,
            source="fred",
            ttl_seconds=3600,
            detail=f"{len(results)}/{len(series_ids)} series",
        )
    return cfg


def fetch_eia(cfg: dict) -> dict:
    """Fetch EIA Open Data observations for nodes with `source: "eia"`.

    Book JSON shapes accepted:
        # Petroleum 'series' shorthand (most common — diesel, gasoline)
        {"source": "eia", "series": "EMD_EPD2D_PTE_NUS_DPG"}

        # Full route + facets (crude stocks, ng storage, refinery util)
        {"source": "eia", "route": "petroleum/stoc/wstk/data",
         "facets": {"product": ["EPC0"], "duoarea": ["NUS"]},
         "frequency": "weekly"}

    WHY separate from fetch_fred: EIA has its own auth (EIA_API_KEY) and
    a richer query model (route + facets, not a flat series ID). Mirroring
    the polymarket/fred pattern keeps each source isolated for failure
    handling and freshness stamping.

    Silent skip if EIA_API_KEY is missing — EIA is optional like FRED.
    """
    eia_dir = os.path.join(os.path.dirname(__file__), "..", "data_fetch")
    eia_dir = os.path.abspath(eia_dir)

    if not os.path.isfile(os.path.join(eia_dir, "eia.py")):
        print("  eia: module not found, skipping", file=sys.stderr)
        return cfg

    if eia_dir not in sys.path:
        sys.path.insert(0, eia_dir)

    try:
        import eia as eia_mod  # type: ignore[import-not-found]
    except ImportError as e:
        print(f"  eia: import failed: {e}", file=sys.stderr)
        return cfg

    # Build (spec_key -> [node_ids]) and the spec list to fetch.
    spec_to_nodes: dict = {}
    specs = []
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") != "eia":
                continue
            # Two forms: 'series' shorthand or full 'route' + 'facets'.
            if feed.get("series"):
                spec = eia_mod.spec_petroleum_series(
                    feed["series"],
                    frequency=feed.get("frequency", "weekly"),
                )
            elif feed.get("route"):
                spec = eia_mod.EIASpec(
                    key=feed.get("key") or feed["route"],
                    route=feed["route"],
                    facets=feed.get("facets", {}),
                    frequency=feed.get("frequency"),
                    length=feed.get("length", 1),
                )
            else:
                continue

            if spec.key not in spec_to_nodes:
                spec_to_nodes[spec.key] = []
                specs.append(spec)
            spec_to_nodes[spec.key].append(node["id"])

    if not specs:
        return cfg

    print(f"  eia: fetching {len(specs)} series...", file=sys.stderr)

    try:
        results = eia_mod.fetch_series_batch(specs)
    except eia_mod.EIAAuthError as e:
        print(f"  eia: skipped ({e})", file=sys.stderr)
        return cfg
    except Exception as e:
        print(f"  eia: batch fetch failed: {e}", file=sys.stderr)
        return cfg

    node_map = {n["id"]: n for n in cfg["nodes"]}
    count = 0
    resolved = 0
    for key, obs in results.items():
        if obs is None:
            continue
        resolved += 1
        for nid in spec_to_nodes.get(key, []):
            node = node_map.get(nid)
            if node is None or "current" not in node:
                continue
            old = node["current"]
            node["current"] = round(obs.value, 4)
            print(
                f"  eia: {nid} ({key}): {old} -> {round(obs.value, 4)} "
                f"{obs.units} (period {obs.period})",
                file=sys.stderr,
            )
            count += 1

    print(
        f"  eia: updated {count} node(s) from {resolved}/{len(specs)} specs",
        file=sys.stderr,
    )

    if resolved:
        _stamp_feed_freshness(
            cfg,
            source="eia",
            ttl_seconds=86400 * 8,  # most EIA series are weekly; allow 8d
            detail=f"{resolved}/{len(specs)} specs",
        )
    return cfg


def fetch_treasury(cfg: dict) -> dict:
    """Fetch US Treasury daily yield curve and apply to nodes.

    Book JSON shapes accepted:
        {"source": "treasury", "tenor": "10Y"}
        {"source": "treasury", "spread": ["10Y", "2Y"]}

    Treasury fetches happen once per --fetch run (one HTTP request returns
    the full year's curve). Spread feeds compute long-short in basis
    points; tenor feeds write the raw rate (percent).

    No auth required. Silent skip on transient failure — Treasury XML
    isn't always available the moment a tick fires.
    """
    treasury_dir = os.path.join(os.path.dirname(__file__), "..", "data_fetch")
    treasury_dir = os.path.abspath(treasury_dir)

    if not os.path.isfile(os.path.join(treasury_dir, "treasury.py")):
        print("  treasury: module not found, skipping", file=sys.stderr)
        return cfg

    if treasury_dir not in sys.path:
        sys.path.insert(0, treasury_dir)

    try:
        import treasury as treasury_mod  # type: ignore[import-not-found]
    except ImportError as e:
        print(f"  treasury: import failed: {e}", file=sys.stderr)
        return cfg

    # Discover treasury feeds and decide whether we need to fetch.
    treasury_feeds = []
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "treasury":
                treasury_feeds.append((node["id"], feed))

    if not treasury_feeds:
        return cfg

    print(
        f"  treasury: fetching latest yield curve for "
        f"{len(treasury_feeds)} feed(s)...",
        file=sys.stderr,
    )

    try:
        latest = treasury_mod.fetch_latest()
    except treasury_mod.TreasuryError as e:
        print(f"  treasury: fetch failed: {e}", file=sys.stderr)
        return cfg
    except Exception as e:
        print(f"  treasury: unexpected error: {e}", file=sys.stderr)
        return cfg

    node_map = {n["id"]: n for n in cfg["nodes"]}
    count = 0
    for nid, feed in treasury_feeds:
        node = node_map.get(nid)
        if node is None or "current" not in node:
            continue

        if feed.get("tenor"):
            tenor = feed["tenor"]
            value = latest.tenors.get(tenor)
            if value is None:
                print(
                    f"  treasury: {nid}: tenor {tenor} missing for "
                    f"{latest.date}",
                    file=sys.stderr,
                )
                continue
            old = node["current"]
            node["current"] = round(value, 4)
            print(
                f"  treasury: {nid} ({tenor}): {old} -> {round(value, 4)}% "
                f"(date {latest.date})",
                file=sys.stderr,
            )
            count += 1
        elif feed.get("spread"):
            spread = feed["spread"]
            if not (isinstance(spread, list) and len(spread) == 2):
                print(
                    f"  treasury: {nid}: spread must be [long, short]",
                    file=sys.stderr,
                )
                continue
            bps = treasury_mod.compute_spread(latest, spread[0], spread[1])
            if bps is None:
                print(
                    f"  treasury: {nid}: spread {spread} unavailable for "
                    f"{latest.date}",
                    file=sys.stderr,
                )
                continue
            old = node["current"]
            node["current"] = round(bps, 4)
            print(
                f"  treasury: {nid} ({spread[0]}-{spread[1]}): {old} -> "
                f"{round(bps, 1)}bps (date {latest.date})",
                file=sys.stderr,
            )
            count += 1

    print(
        f"  treasury: updated {count}/{len(treasury_feeds)} node(s) "
        f"(curve date {latest.date})",
        file=sys.stderr,
    )

    if count:
        _stamp_feed_freshness(
            cfg,
            source="treasury",
            ttl_seconds=86400 * 2,  # daily series; 2-day window for weekends
            detail=f"curve {latest.date}",
        )
    return cfg


def fetch_gdelt(cfg: dict) -> dict:
    """Fetch GDELT volume signals for nodes with `source: "gdelt"`.

    Book JSON shapes accepted:
        {"source": "gdelt", "query": "Hormuz AND blockade", "timespan": "1d"}
        {"source": "gdelt", "standardQuery": "iran-hormuz-event",
         "timespan": "7d"}

    Each unique query is fetched once (deduped across nodes). Latest
    bucket value is written to node['current']. No auth required.

    Only nodes that ALREADY declare `current` are fetched for. A gdelt node
    without it is watch-only: its book declares the feed so the news bridge
    can serve headlines for that thesis, and it wants no volume number.
    Declaring `current` is how such a node opts in.

    GDELT recommends ~1 req/sec; we sleep 1s between fetches to stay polite.
    """
    gdelt_dir = os.path.join(os.path.dirname(__file__), "..", "data_fetch")
    gdelt_dir = os.path.abspath(gdelt_dir)

    if not os.path.isfile(os.path.join(gdelt_dir, "gdelt.py")):
        print("  gdelt: module not found, skipping", file=sys.stderr)
        return cfg

    if gdelt_dir not in sys.path:
        sys.path.insert(0, gdelt_dir)

    try:
        import gdelt as gdelt_mod  # type: ignore[import-not-found]
    except ImportError as e:
        print(f"  gdelt: import failed: {e}", file=sys.stderr)
        return cfg

    # Build (query, timespan) -> [node_ids]. Dedup so we don't double-fetch.
    fetch_jobs: dict = {}
    for node in cfg.get("nodes", []):
        # WHY skip a node with no `current`: the write loop below refuses to
        # touch one, so fetching on its behalf spends a request on a value
        # that is thrown away. GDELT is the desk's only unauthenticated
        # source and it throttles per-IP — five watch-only rhetoric nodes
        # re-fetching every tick starve the news bridge of the budget it
        # needs to answer with actual headlines.
        if "current" not in node:
            continue
        for feed in node.get("feeds", []):
            if feed.get("source") != "gdelt":
                continue

            timespan = feed.get("timespan", "1d")
            if feed.get("standardQuery"):
                query = gdelt_mod.get_standard_query(feed["standardQuery"])
                if query is None:
                    print(
                        f"  gdelt: unknown standardQuery "
                        f"{feed['standardQuery']!r}",
                        file=sys.stderr,
                    )
                    continue
            else:
                query = feed.get("query")
                if not query:
                    continue

            key = (query, timespan)
            if key not in fetch_jobs:
                fetch_jobs[key] = []
            fetch_jobs[key].append(node["id"])

    if not fetch_jobs:
        return cfg

    print(
        f"  gdelt: fetching {len(fetch_jobs)} unique queries...",
        file=sys.stderr,
    )

    import time as _time
    node_map = {n["id"]: n for n in cfg["nodes"]}
    count = 0
    resolved = 0

    for i, ((query, timespan), nids) in enumerate(fetch_jobs.items()):
        try:
            value = gdelt_mod.fetch_volume_latest(query, timespan=timespan)
        except gdelt_mod.GdeltRateLimitError as e:
            print(f"  gdelt: rate-limited, aborting: {e}", file=sys.stderr)
            break
        except gdelt_mod.GdeltError as e:
            print(f"  gdelt: {query!r} -> {e}", file=sys.stderr)
            continue

        # WHY 1s polite pacing between unique queries: matches GDELT guidance.
        if i < len(fetch_jobs) - 1:
            _time.sleep(1.0)

        if value is None:
            print(f"  gdelt: {query!r}: no data in {timespan}", file=sys.stderr)
            continue
        resolved += 1

        for nid in nids:
            node = node_map.get(nid)
            if node is None or "current" not in node:
                continue
            old = node["current"]
            node["current"] = round(value, 6)
            print(
                f"  gdelt: {nid} ({query[:40]!r}): {old} -> "
                f"{round(value, 6)} ({timespan})",
                file=sys.stderr,
            )
            count += 1

    print(
        f"  gdelt: updated {count} node(s) from {resolved}/{len(fetch_jobs)} "
        f"queries",
        file=sys.stderr,
    )

    if resolved:
        _stamp_feed_freshness(
            cfg,
            source="gdelt",
            ttl_seconds=3600,  # GDELT updates every 15 minutes
            detail=f"{resolved}/{len(fetch_jobs)} queries",
        )
    return cfg


# =========================================================================
# DERIVED INDICATORS (local RSI / ATR / SMA, non-causal overlays)
# =========================================================================

_YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"


def fetch_ohlcv_for_derived(cfg: dict, retries: int = 2) -> dict:
    """Fetch 3 months of OHLCV for symbols referenced by derivedIndicators.

    WHY a separate fetch from fetch_prices(): fetch_prices() uses the v7
    spark batch endpoint, which returns only the current price (no close
    history). The v8 chart endpoint returns full OHLCV series but is
    per-symbol, not batched. We only pay the extra round-trips for symbols
    that actually need history for indicator computation — typically
    4–8 symbols per book, not the full watchlist.

    Mutates cfg in-place by adding a transient "_ohlcv" key:
        cfg["_ohlcv"][symbol] = {"closes":[...], "highs":[...], "lows":[...]}

    The leading-underscore name marks it transient. compute_derived_indicators()
    strips it before returning, so it never leaks into book JSONs that
    get written back by update_config_file().
    """
    import urllib.parse

    wanted: set[str] = set()
    for node in cfg.get("nodes", []):
        for spec in node.get("derivedIndicators", []) or []:
            if not isinstance(spec, dict):
                continue
            if spec.get("symbol"):
                wanted.add(str(spec["symbol"]))
            # curveSpread uses two symbols instead of one — pick both up so
            # compute_node_indicators has OHLCV for the front and back legs.
            if spec.get("frontSymbol"):
                wanted.add(str(spec["frontSymbol"]))
            if spec.get("backSymbol"):
                wanted.add(str(spec["backSymbol"]))

    if not wanted:
        return cfg

    cfg.setdefault("_ohlcv", {})
    fetched = 0
    for symbol in sorted(wanted):
        encoded = urllib.parse.quote(symbol, safe="=^.-")
        url = f"{_YAHOO_CHART_BASE}{encoded}?range=3mo&interval=1d"
        succeeded = False
        for attempt in range(1, retries + 1):
            try:
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read())
                chart = data.get("chart", {})
                results = chart.get("result") or []
                if not results:
                    err = chart.get("error") or "no result"
                    print(f"  ohlcv {symbol}: empty result ({err})", file=sys.stderr)
                    succeeded = True
                    break
                quote = results[0].get("indicators", {}).get("quote", [{}])[0]
                timestamps_raw = results[0].get("timestamp") or []
                closes_raw = quote.get("close") or []
                highs_raw = quote.get("high") or []
                lows_raw = quote.get("low") or []
                # Pair each close with its timestamp (Yahoo aligns these arrays
                # index-by-index). Filter out nulls in the close position, and
                # convert the timestamp to ISO market-date for close-observation
                # table keying downstream.
                paired = list(zip(
                    timestamps_raw or [None] * len(closes_raw),
                    closes_raw,
                    highs_raw or [None] * len(closes_raw),
                    lows_raw or [None] * len(closes_raw),
                ))
                closes: list[float] = []
                highs: list[float] = []
                lows: list[float] = []
                dates: list[str] = []
                for ts, c, h, l in paired:
                    if c is None:
                        continue
                    closes.append(round(float(c), 4))
                    if h is not None:
                        highs.append(round(float(h), 4))
                    if l is not None:
                        lows.append(round(float(l), 4))
                    if ts is not None:
                        try:
                            dates.append(
                                datetime.fromtimestamp(int(ts), tz=timezone.utc)
                                .date().isoformat()
                            )
                        except (ValueError, TypeError, OSError):
                            dates.append("")
                    else:
                        dates.append("")
                if closes:
                    cfg["_ohlcv"][symbol] = {
                        "closes": closes,
                        "highs": highs,
                        "lows": lows,
                        "dates": dates,
                    }
                    fetched += 1
                    print(f"  ohlcv {symbol}: {len(closes)} closes", file=sys.stderr)
                succeeded = True
                break
            except (URLError, HTTPError, TimeoutError, OSError) as e:
                if attempt < retries:
                    time.sleep(2)
                else:
                    print(f"  ohlcv {symbol}: failed ({e})", file=sys.stderr)
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                print(f"  ohlcv {symbol}: parse error ({e})", file=sys.stderr)
                break
        if succeeded:
            time.sleep(0.4)

    print(f"  ohlcv: fetched {fetched}/{len(wanted)} symbol(s)", file=sys.stderr)
    return cfg


def compute_derived_indicators(cfg: dict) -> dict:
    """Populate each node's tvIndicators and emit close events.

    Call order: runs AFTER fetch_ohlcv_for_derived() (which populates the
    transient cfg["_ohlcv"] stash) and BEFORE propagate(). The coordinator
    is responsible for consuming the emitted close events (writing them to
    SQLite and patching per-node streak counts onto effective cfg) before
    propagate() runs.

    Mutates cfg in-place:
        - Writes node["tvIndicators"] = {"rsi14": ..., "atr14": ...,
          "source": "derived_from_yahoo", "computedAt": ISO8601}.
        - Attaches cfg["_close_events"] = [{node_id, threshold_key,
          threshold_level, market_date, close_value, qualifies}, ...] — one
          record per (node × threshold-with-closesRequired × close-in-series).
        - Strips cfg["_ohlcv"] at the end (transient only).

    Does NOT mutate node["closesObserved"] — the streak count is now sourced
    from the close_observations SQLite table, driven by the coordinator. CLI
    callers that still want closesObserved visible in generated HTML must
    derive it from the returned events.

    Does NOT touch node["current"], node["state"], node["probability"], or
    any other propagation-read field.
    """
    di_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "data_fetch")
    )
    if di_dir not in sys.path:
        sys.path.insert(0, di_dir)

    # Always seed an empty events bucket so the coordinator can branch on
    # "key exists" without special-casing import/OHLCV failures.
    cfg["_close_events"] = []

    try:
        import derived_indicators as di
    except ImportError as e:
        print(f"  derived_indicators: import failed: {e}", file=sys.stderr)
        cfg.pop("_ohlcv", None)
        return cfg

    ohlcv = cfg.get("_ohlcv") or {}
    if not ohlcv:
        print("  derived_indicators: no OHLCV available, skipping", file=sys.stderr)
        cfg.pop("_ohlcv", None)
        return cfg

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated_nodes = 0
    events_emitted = 0

    for node in cfg.get("nodes", []):
        specs = node.get("derivedIndicators") or []
        if not specs:
            continue

        try:
            tv = di.compute_node_indicators(node, ohlcv)
        except ValueError as e:
            print(f"  derived_indicators: {e}", file=sys.stderr)
            continue

        if tv:
            tv["source"] = "derived_from_yahoo"
            tv["computedAt"] = now_iso
            node["tvIndicators"] = tv
            updated_nodes += 1

        # Emit close events for every (threshold, close) pair on price/reversal
        # nodes with closesRequired gates. The coordinator writes these to the
        # close_observations table (PK-dedup on thesis_id + node_id +
        # market_date + threshold_key) and computes the streak count.
        if node.get("type") not in ("price", "reversal"):
            continue
        thresholds_with_closes = [
            th for th in (node.get("thresholds") or [])
            if isinstance(th, dict) and th.get("closesRequired") and th.get("level") is not None
        ]
        if not thresholds_with_closes:
            continue
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            symbol = spec.get("symbol")
            series = ohlcv.get(symbol) or {}
            closes = series.get("closes") or []
            dates = series.get("dates") or []
            if not closes:
                continue
            # Pair closes with dates; fall back to the empty string when Yahoo
            # didn't return timestamps (keeps the PK deterministic).
            for idx, close_value in enumerate(closes):
                market_date = dates[idx] if idx < len(dates) else ""
                if not market_date:
                    continue  # Skip undated rows — can't key the PK safely.
                for th in thresholds_with_closes:
                    level = float(th["level"])
                    cfg["_close_events"].append({
                        "node_id": node["id"],
                        "threshold_key": str(th["level"]),
                        "threshold_level": level,
                        "market_date": market_date,
                        "close_value": float(close_value),
                        "qualifies": close_value >= level,
                    })
                    events_emitted += 1

    print(
        f"  derived_indicators: updated {updated_nodes} node(s), "
        f"emitted {events_emitted} close event(s)",
        file=sys.stderr,
    )
    # Stamp freshness when at least one node got new indicator values.
    # Derived indicators compute off daily closes so TTL tracks the daily
    # bar cadence (24h).
    if updated_nodes > 0:
        _stamp_feed_freshness(
            cfg,
            source="derived",
            ttl_seconds=86400,
            detail=f"{updated_nodes} node(s)",
        )
    cfg.pop("_ohlcv", None)
    return cfg


# =========================================================================
# DATA TRANSFORM
# =========================================================================

def build_nodes_js(cfg: dict) -> str:
    """Transform nodes to compact JS array."""
    nodes = []
    for n in cfg["nodes"]:
        d = {
            "id": n["id"],
            "label": n["label"],
            "type": n["type"],
            "phase": n.get("phase", 1),
        }
        if "state" in n:
            d["state"] = n["state"]
        if "current" in n:
            d["current"] = n["current"]
        if "thresholds" in n:
            d["thresholds"] = n["thresholds"]
        if "threshold" in n:
            d["threshold"] = n["threshold"]
        if "feeds" in n:
            d["feeds"] = n["feeds"]
        if "probability" in n:
            d["probability"] = n["probability"]
        if "indicators" in n:
            d["indicators"] = n["indicators"]
        if "deadline" in n:
            d["deadline"] = n["deadline"]
        if "conditions" in n:
            d["conditions"] = n["conditions"]
        if "logic" in n:
            d["logic"] = n["logic"]
        if "irreversible" in n:
            d["irreversible"] = n["irreversible"]
        if "countdown" in n:
            d["countdown"] = n["countdown"]
        if "context" in n:
            d["context"] = n["context"]
        if "confluence" in n:
            d["confluence"] = n["confluence"]
        if "historicalLag" in n:
            d["historicalLag"] = n["historicalLag"]
        if "regimes" in n:
            d["regimes"] = n["regimes"]
        if "gatedBy" in n:
            d["gatedBy"] = n["gatedBy"]
        if "constrainedBy" in n:
            d["constrainedBy"] = n["constrainedBy"]
        if "constrains" in n:
            d["constrains"] = n["constrains"]
        if "gates" in n:
            d["gates"] = n["gates"]
        if "condition" in n:
            d["condition"] = n["condition"]
        if "closesRequired" in n:
            d["closesRequired"] = n["closesRequired"]
        if "closesObserved" in n:
            d["closesObserved"] = n["closesObserved"]
        if "tvIndicators" in n:
            d["tvIndicators"] = n["tvIndicators"]
        if "additionalCondition" in n:
            d["additionalCondition"] = n["additionalCondition"]
        if "action" in n:
            d["action"] = n["action"]
        if "lag" in n:
            d["lag"] = n["lag"]
        nodes.append(d)
    return json.dumps(nodes, separators=(",", ":"))


def build_edges_js(cfg: dict) -> str:
    """Transform edges to compact JS array."""
    edges = []
    for e in cfg["edges"]:
        d = {
            "from": e["from"],
            "to": e["to"],
            "strength": e["strength"],
        }
        if "mechanism" in e:
            d["mechanism"] = e["mechanism"]
        if "lag" in e:
            d["lag"] = e["lag"]
        if "amplification" in e:
            d["amplification"] = e["amplification"]
        edges.append(d)
    return json.dumps(edges, separators=(",", ":"))


def build_instruments_js(cfg: dict) -> str:
    """Instruments dict → compact JS object. Filters to only list-valued entries."""
    # WHY: The config may nest "overlays" as a dict inside instruments.
    # JS expects {nodeId: [instrument_array, ...]} — skip non-list values.
    filtered = {k: v for k, v in cfg.get("instruments", {}).items() if isinstance(v, list)}
    return json.dumps(filtered, separators=(",", ":"))


def build_scenarios_js(cfg: dict) -> str:
    """Scenarios array → compact JS."""
    return json.dumps(cfg.get("scenarios", []), separators=(",", ":"))


def build_cascade_js(cfg: dict) -> str:
    """Cascade phases → compact JS."""
    return json.dumps(cfg.get("cascadePhases", {}), separators=(",", ":"))


def build_analogs_js(cfg: dict) -> str:
    """Analogs array → compact JS."""
    return json.dumps(cfg.get("analogs", []), separators=(",", ":"))


def build_topo_order_js(cfg: dict) -> str:
    """Pre-computed topological order → JS array."""
    order = topo_sort(cfg["nodes"], cfg["edges"])
    return json.dumps(order, separators=(",", ":"))


def build_fetch_syms_js(cfg: dict) -> str:
    """Build fetch symbol mapping for browser-side fetch."""
    sym_map = {}  # yahoo symbol → {nodeId, field}
    inst_syms = []

    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "yahoo" and "symbol" in feed:
                # WHY: Keep first occurrence — if brent and de-escalation both
                # reference BZ=F, we want the upstream (brent) node to get the price.
                if feed["symbol"] not in sym_map:
                    sym_map[feed["symbol"]] = node["id"]

    for nid, insts in cfg.get("instruments", {}).items():
        if not isinstance(insts, list):
            continue
        for inst in insts:
            iid = inst.get("id")
            if iid:
                inst_syms.append(iid)

    return json.dumps({"nodeMap": sym_map, "instruments": inst_syms}, separators=(",", ":"))


def build_defaults_js(cfg: dict) -> str:
    """Generate DEFAULTS object for initial graph state."""
    # Build market data from nodes with numeric current fields
    market = {}
    for n in cfg["nodes"]:
        if "current" in n and isinstance(n["current"], (int, float)):
            market[n["id"]] = n["current"]

    today_str = datetime.now().strftime("%Y-%m-%d")
    claim = cfg.get("meta", {}).get("claim", "")
    init_note = f"Graph initialized. {claim}".replace("'", "\\'")

    return json.dumps({
        "v": 1,
        "market": market,
        "prices": {},
        "positions": {},
        "closeLogs": {},
        "gates": {},
        "journal": [{"id": 1, "date": today_str, "type": "setup", "text": init_note, "node": ""}],
        "ui": {"tab": "graph", "jFilt": "all", "scenario": "", "expanded": []},
    }, separators=(",", ":"))


# =========================================================================
# PIPELINE INTEGRATION
# =========================================================================

def find_skill_script(name: str) -> str | None:
    """Locate an infographic-gen skill script."""
    candidates = [
        Path(__file__).parent.parent.parent / ".." / ".claude" / "skills" / "infographic-gen" / "scripts" / name,
        Path.home() / ".claude" / "skills" / "infographic-gen" / "scripts" / name,
    ]
    for p in candidates:
        resolved = p.resolve()
        if resolved.is_file():
            return str(resolved)
    return None


def run_validate(html_path: str) -> bool:
    script = find_skill_script("validate.py")
    if not script:
        print("  Warning: validate.py not found, skipping validation", file=sys.stderr)
        return True
    result = subprocess.run([sys.executable, script, html_path], capture_output=True, text=True, timeout=30)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode == 0


def run_screenshot(html_path: str, output_dir: str = ".") -> str | None:
    script = find_skill_script("screenshot.py")
    if not script:
        print("  Warning: screenshot.py not found, skipping", file=sys.stderr)
        return None
    base = Path(html_path).stem
    out = str(Path(output_dir) / f"{base}-og.png")
    result = subprocess.run(
        [sys.executable, script, html_path, "--crop-hero", "--output", out],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode == 0 and os.path.isfile(out):
        print(f"  Screenshot: {out}")
        return out
    print(f"  Warning: screenshot failed: {result.stderr}", file=sys.stderr)
    return None


def run_publish(html_path: str, cfg: dict, args) -> None:
    script = find_skill_script("publish.py")
    if not script:
        print("  Error: publish.py not found", file=sys.stderr)
        return
    meta = cfg.get("meta", {})
    cmd = [
        sys.executable, script, html_path,
        "--username", args.username,
        "--api-url", args.api_url,
        "--title", meta.get("title", "Thesis Graph"),
        "--category", args.category,
    ]
    if args.slug:
        cmd += ["--slug", args.slug]
    env = os.environ.copy()
    result = subprocess.run(cmd, env=env, capture_output=False, text=True, timeout=30)


# =========================================================================
# HTML GENERATION
# =========================================================================

def generate_html(cfg: dict) -> str:
    """Generate the complete thesis graph HTML from config."""
    meta = cfg.get("meta", {})
    title = meta.get("title", "Thesis Graph")
    as_of = meta.get("asOf", datetime.now().strftime("%Y-%m-%d"))
    claim = meta.get("claim", "")

    phase_num, phase_key = get_current_phase(cfg)
    states = propagate(cfg)
    confluence = score_confluence(cfg, states)

    # Read Cytoscape libraries from lib/ directory
    # WHY: cytoscape-dagre requires dagre (which includes graphlib) as an
    # external dependency. We inline dagre.min.js before cytoscape-dagre.js.
    lib_dir = Path(__file__).parent / "lib"
    cyto_path = lib_dir / "cytoscape.min.js"
    dagre_core_path = lib_dir / "dagre.min.js"
    dagre_ext_path = lib_dir / "cytoscape-dagre.js"

    cyto_js = ""
    dagre_js = ""
    if cyto_path.is_file():
        cyto_js = cyto_path.read_text()
    else:
        print(f"  Warning: {cyto_path} not found, graph will not render", file=sys.stderr)
    # Concatenate dagre core + cytoscape-dagre extension
    dagre_parts = []
    if dagre_core_path.is_file():
        dagre_parts.append(dagre_core_path.read_text())
    else:
        print(f"  Warning: {dagre_core_path} not found, layout will not work", file=sys.stderr)
    if dagre_ext_path.is_file():
        dagre_parts.append(dagre_ext_path.read_text())
    else:
        print(f"  Warning: {dagre_ext_path} not found, layout will not work", file=sys.stderr)
    dagre_js = "\n".join(dagre_parts)

    nodes_js = build_nodes_js(cfg)
    edges_js = build_edges_js(cfg)
    instruments_js = build_instruments_js(cfg)
    scenarios_js = build_scenarios_js(cfg)
    cascade_js = build_cascade_js(cfg)
    analogs_js = build_analogs_js(cfg)
    topo_js = build_topo_order_js(cfg)
    fetch_js = build_fetch_syms_js(cfg)
    defaults_js = build_defaults_js(cfg)
    states_js = json.dumps(states, separators=(",", ":"))
    confluence_js = json.dumps(confluence, separators=(",", ":"))

    html = get_template()
    # WHY: quote=True escapes " and ' — needed because __CLAIM__ appears in
    # a content="..." attribute. Prevents stored XSS via crafted config values.
    esc = lambda s: html_mod.escape(s, quote=True)
    replacements = {
        "__TITLE__": esc(title),
        "__AS_OF__": esc(as_of),
        "__CLAIM__": esc(claim),
        "__PHASE_NUM__": str(phase_num),
        "__PHASE_KEY__": phase_key,
        "__CYTOSCAPE_JS__": cyto_js,
        "__DAGRE_JS__": dagre_js,
        "__NODES_JS__": nodes_js,
        "__EDGES_JS__": edges_js,
        "__INSTRUMENTS_JS__": instruments_js,
        "__SCENARIOS_JS__": scenarios_js,
        "__CASCADE_JS__": cascade_js,
        "__ANALOGS_JS__": analogs_js,
        "__TOPO_ORDER_JS__": topo_js,
        "__FETCH_JS__": fetch_js,
        "__DEFAULTS_JS__": defaults_js,
        "__INIT_STATES_JS__": states_js,
        "__CONFLUENCE_JS__": confluence_js,
    }
    for marker, value in replacements.items():
        html = html.replace(marker, value)

    return html


# =========================================================================
# CSS
# =========================================================================

CSS_STYLES = r"""
:root{
  --bg0:#120C06;--bg1:#160E08;
  --s0:rgba(255,255,255,.04);--s1:rgba(255,255,255,.06);--s2:rgba(255,255,255,.09);
  --b0:rgba(255,255,255,.05);--b1:rgba(255,255,255,.085);
  --r-sm:6px;--r-md:14px;--r-pill:20px;
  --sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-6:24px;--sp-8:32px;
  --e-out:cubic-bezier(.22,1,.36,1);--dur-fast:.2s;--dur-med:.35s;
  --t1:#FFF7EE;--t2:rgba(255,247,238,.72);--t3:rgba(255,247,238,.50);--t4:rgba(255,247,238,.38);
  --font-display:'Outfit',system-ui,sans-serif;
  --font-mono:'JetBrains Mono','Fira Code',monospace;
  --c-fired:#E05555;--c-appr:#E69A4C;--c-stable:#6E8FAD;--c-gated:#555555;--c-cstr:#AD7FA8;
  --c-up:#4CC4B4;--c-dn:#C44C4C;--c-warn:#E69A4C;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:linear-gradient(180deg,var(--bg0),var(--bg1));background-attachment:fixed;color:var(--t1);font-family:var(--font-display);font-size:14px;line-height:1.5;min-height:100vh;-webkit-font-smoothing:antialiased}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--b1);border-radius:3px}
.page{max-width:1400px;margin:0 auto;padding:0 var(--sp-4) var(--sp-8)}

/* Header */
.app-hdr{position:sticky;top:0;z-index:100;background:var(--bg0);border-bottom:1px solid var(--b0);padding:var(--sp-3) var(--sp-4) 0;max-width:1400px;margin:0 auto}
.hdr-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:var(--sp-2);flex-wrap:wrap;gap:var(--sp-2)}
.hdr-title{font-size:18px;font-weight:800}
.hdr-title .mono{font-family:var(--font-mono);color:var(--c-warn)}
.phase-badge{font-family:var(--font-mono);font-size:12px;font-weight:700;padding:2px 10px;border-radius:var(--r-pill);letter-spacing:1px}
.hdr-export{display:flex;gap:var(--sp-2);align-items:center;flex-wrap:wrap}
.btn-sm{font-family:var(--font-mono);font-size:11px;padding:4px 10px;border:1px solid var(--b1);border-radius:var(--r-sm);background:var(--s0);color:var(--t3);cursor:pointer;transition:all var(--dur-fast)}
.btn-sm:hover{background:var(--s2);color:var(--t1)}

/* Tabs */
.tab-bar{display:flex;gap:var(--sp-1);padding-bottom:var(--sp-2);overflow-x:auto}
.tab-btn{font-family:var(--font-mono);font-size:12px;font-weight:600;letter-spacing:1px;padding:var(--sp-2) var(--sp-4);border:none;border-bottom:2px solid transparent;background:none;color:var(--t4);cursor:pointer;transition:all var(--dur-fast)}
.tab-btn:hover{color:var(--t2)}
.tab-btn.active{color:var(--t1);border-bottom-color:var(--c-warn)}
.tab-pane{display:none;padding-top:var(--sp-4)}
.tab-pane.active{display:block}

/* Section label */
.sec-label{font-family:var(--font-mono);font-size:11px;font-weight:600;letter-spacing:2.5px;text-transform:uppercase;color:var(--t4);margin-bottom:var(--sp-4);display:flex;align-items:center;gap:var(--sp-2)}
.sec-label::after{content:'';flex:1;height:1px;background:var(--b0)}

/* Market data bar */
.mkt-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:var(--sp-3);padding:var(--sp-4);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);margin-bottom:var(--sp-6)}
.mkt-item{text-align:center}
.mkt-lbl{font-family:var(--font-mono);font-size:10px;font-weight:500;letter-spacing:1px;color:var(--t4);display:block;margin-bottom:2px}
.mkt-inp{font-family:var(--font-mono);font-size:14px;font-weight:700;color:var(--t1);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);padding:3px var(--sp-2);width:100%;max-width:110px;text-align:center}
.mkt-inp:focus{outline:none;border-color:var(--c-warn);background:var(--s1)}

/* Graph tab */
#cy{width:100%;height:560px;border:1px solid var(--b0);border-radius:var(--r-md);background:var(--bg1);margin-bottom:var(--sp-4)}
#node-detail{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4) var(--sp-6);min-height:80px;transition:all var(--dur-med)}
.nd-title{font-size:16px;font-weight:800;margin-bottom:var(--sp-2)}
.nd-type{font-family:var(--font-mono);font-size:11px;color:var(--t4);letter-spacing:1px;text-transform:uppercase}
.nd-state{font-family:var(--font-mono);font-size:12px;font-weight:700;padding:2px 8px;border-radius:var(--r-sm);margin-left:var(--sp-2)}
.nd-section{margin-top:var(--sp-3);padding-top:var(--sp-3);border-top:1px solid var(--b0)}
.nd-section h4{font-family:var(--font-mono);font-size:11px;letter-spacing:2px;color:var(--t4);margin-bottom:var(--sp-2);text-transform:uppercase}
.nd-feed{font-family:var(--font-mono);font-size:12px;color:var(--t3);padding:2px 0}
.nd-indicator{display:flex;gap:var(--sp-3);padding:3px 0;font-size:12px}
.nd-indicator .dot{width:8px;height:8px;border-radius:50%;margin-top:5px;flex-shrink:0}
.nd-threshold{font-family:var(--font-mono);font-size:12px;padding:2px 0;display:flex;justify-content:space-between}
.nd-context{font-size:13px;color:var(--t3);line-height:1.6}
.nd-empty{color:var(--t4);font-size:13px;padding:var(--sp-6);text-align:center}

/* Cascade tab */
.cascade-timeline{position:relative;padding-left:40px}
.cascade-phase{position:relative;padding:var(--sp-4) var(--sp-6);margin-bottom:var(--sp-4);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);border-left:4px solid var(--t4)}
.cascade-phase.cp-complete{border-left-color:var(--c-up);background:rgba(76,196,180,.03)}
.cascade-phase.cp-active{border-left-color:var(--c-warn);background:rgba(230,154,76,.04)}
.cascade-phase.cp-approaching{border-left-color:var(--c-appr);background:rgba(230,154,76,.02)}
.cascade-phase.cp-watching{border-left-color:var(--t4)}
.cp-num{position:absolute;left:-40px;top:var(--sp-4);width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--font-mono);font-size:13px;font-weight:700;border:2px solid var(--b1);background:var(--bg0)}
.cp-complete .cp-num{border-color:var(--c-up);color:var(--c-up)}
.cp-active .cp-num{border-color:var(--c-warn);color:var(--c-warn)}
.cp-here{font-family:var(--font-mono);font-size:10px;font-weight:800;letter-spacing:2px;color:var(--c-warn);margin-bottom:var(--sp-2)}
.cp-title{font-size:15px;font-weight:700;margin-bottom:var(--sp-2)}
.cp-status{font-family:var(--font-mono);font-size:11px;font-weight:700;padding:2px 8px;border-radius:var(--r-sm);margin-left:var(--sp-2);letter-spacing:1px}
.cp-signposts{list-style:none;margin-top:var(--sp-3)}
.cp-sp{display:flex;gap:var(--sp-2);padding:3px 0;font-size:13px;align-items:flex-start}
.cp-sp-icon{font-size:14px;flex-shrink:0;width:20px;text-align:center}
.cp-sp-text{color:var(--t2)}
.cp-sp-val{font-family:var(--font-mono);font-size:11px;color:var(--t3);margin-left:auto;flex-shrink:0}
.cp-timing{font-family:var(--font-mono);font-size:11px;color:var(--t4);margin-top:var(--sp-3);padding-top:var(--sp-2);border-top:1px solid var(--b0)}
.countdown-box{background:rgba(230,154,76,.08);border:1px solid rgba(230,154,76,.2);border-radius:var(--r-md);padding:var(--sp-4);margin-bottom:var(--sp-4);text-align:center}
.countdown-num{font-family:var(--font-mono);font-size:32px;font-weight:800;color:var(--c-warn)}
.countdown-lbl{font-family:var(--font-mono);font-size:11px;color:var(--t3);letter-spacing:2px;margin-top:var(--sp-1)}

/* Scenario tab */
.sc-pills{display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-bottom:var(--sp-6)}
.sc-pill{font-family:var(--font-mono);font-size:12px;padding:6px 14px;border:1px solid var(--b1);border-radius:var(--r-pill);background:var(--s0);color:var(--t3);cursor:pointer;transition:all var(--dur-fast)}
.sc-pill:hover{background:var(--s2);color:var(--t1)}
.sc-pill.active{border-color:var(--c-warn);color:var(--t1);background:rgba(230,154,76,.08)}
.sc-prob{font-size:10px;color:var(--t4);margin-left:var(--sp-1)}
.sc-detail{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-6);margin-bottom:var(--sp-6)}
.sc-name{font-size:16px;font-weight:700;margin-bottom:var(--sp-1)}
.sc-notes{font-size:13px;color:var(--t3);margin-bottom:var(--sp-4);line-height:1.6}
.sc-overrides{margin-bottom:var(--sp-4)}
.sc-override-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--b0);font-family:var(--font-mono);font-size:12px}
.sc-override-row:last-child{border-bottom:none}
.sc-override-node{color:var(--t2)}
.sc-override-val{font-weight:700}
.waterfall{margin-top:var(--sp-4)}
.wf-row{display:flex;align-items:center;gap:var(--sp-3);padding:4px 0;font-family:var(--font-mono);font-size:12px}
.wf-label{width:60px;font-weight:600;flex-shrink:0}
.wf-bar-wrap{flex:1;height:16px;position:relative;background:var(--s0);border-radius:3px;overflow:hidden}
.wf-bar{position:absolute;top:0;height:100%;border-radius:3px;transition:width var(--dur-med)}
.wf-bar.pos{background:rgba(76,196,180,.3);left:50%}
.wf-bar.neg{background:rgba(196,76,76,.3);right:50%}
.wf-pct{width:60px;text-align:right;flex-shrink:0}
.sc-ev{background:var(--s1);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4);margin-top:var(--sp-6)}
.sc-ev-title{font-family:var(--font-mono);font-size:11px;letter-spacing:2px;color:var(--t4);margin-bottom:var(--sp-3);text-transform:uppercase}
.sc-empty{color:var(--t4);font-size:13px;text-align:center;padding:var(--sp-8)}

/* Portfolio tab */
.port-group{margin-bottom:var(--sp-6)}
.port-group-title{font-size:14px;font-weight:700;margin-bottom:var(--sp-3);display:flex;align-items:center;gap:var(--sp-2)}
.port-group-badge{font-family:var(--font-mono);font-size:10px;padding:2px 6px;border-radius:var(--r-sm);letter-spacing:1px}
.port-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--sp-4)}
.p-card{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4);position:relative;overflow:hidden}
.p-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:var(--r-md) var(--r-md) 0 0}
.p-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px}
.p-ticker{font-family:var(--font-mono);font-size:17px;font-weight:700}
.p-alloc{font-family:var(--font-mono);font-size:12px;color:var(--t2)}
.p-role{font-size:12px;color:var(--t3);margin-bottom:var(--sp-2)}
.p-pos{font-family:var(--font-mono);font-size:12px;padding:var(--sp-2) var(--sp-3);background:var(--s1);border-radius:var(--r-sm);margin-bottom:var(--sp-3)}
.p-pos-row{display:flex;justify-content:space-between;padding:1px 0}
.p-pos-row .lbl{color:var(--t3)}
.p-pos-row .val{font-weight:600}
.p-empty{font-size:12px;color:var(--t4);font-style:italic;margin-bottom:var(--sp-3)}
.p-range{margin-bottom:var(--sp-1)}
.p-track{position:relative;height:5px;background:rgba(255,255,255,.06);border-radius:3px}
.p-fill{position:absolute;top:0;left:0;bottom:0;border-radius:3px;transition:width var(--dur-med) var(--e-out)}
.p-mark{position:absolute;top:50%;width:10px;height:10px;border-radius:50%;transform:translate(-50%,-50%);border:2px solid var(--t1);z-index:2;transition:left var(--dur-med) var(--e-out)}
.p-labels{display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:11px;margin-top:2px}
.p-labels .stp{color:var(--c-dn)}
.p-labels .tgt{color:var(--c-up)}
.p-metrics{display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:11px;margin-top:1px}
.p-metrics .up{color:var(--c-up)}
.p-metrics .rr{color:var(--t3)}
.p-metrics .dn{color:var(--t4)}
.p-price-row{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-2)}
.p-price-lbl{font-family:var(--font-mono);font-size:11px;color:var(--t4)}
.p-price-inp{font-family:var(--font-mono);font-size:13px;font-weight:600;color:var(--t1);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);padding:2px var(--sp-2);width:85px;text-align:right}
.p-price-inp:focus{outline:none;border-color:var(--c-warn);background:var(--s1)}
.pos-form{display:none;padding:var(--sp-3);background:var(--s1);border-radius:var(--r-sm);margin-top:var(--sp-2)}
.pos-form.open{display:block}
.pf-row{display:flex;gap:var(--sp-2);margin-bottom:var(--sp-2);flex-wrap:wrap}
.pf-inp{font-family:var(--font-mono);font-size:12px;padding:4px var(--sp-2);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);color:var(--t1);min-width:0}
.pf-inp:focus{outline:none;border-color:var(--c-warn)}
.pf-inp.w-date{width:120px}.pf-inp.w-num{width:80px}.pf-inp.w-note{flex:1;min-width:120px}
select.pf-inp{appearance:none;padding-right:20px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23FFF7EE' d='M3 5l3 3 3-3'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 6px center}
.btn-add{font-family:var(--font-mono);font-size:11px;font-weight:700;padding:4px 12px;border:none;border-radius:var(--r-sm);cursor:pointer;transition:all var(--dur-fast)}
.btn-add.primary{background:var(--c-up);color:var(--bg0)}.btn-add.primary:hover{filter:brightness(1.1)}
.btn-add.ghost{background:transparent;border:1px solid var(--b1);color:var(--t3)}.btn-add.ghost:hover{color:var(--t1)}
.btn-open-form{font-family:var(--font-mono);font-size:11px;color:var(--t4);background:none;border:1px dashed var(--b0);border-radius:var(--r-sm);padding:4px 10px;cursor:pointer;margin-top:var(--sp-2);width:100%;transition:all var(--dur-fast)}
.btn-open-form:hover{border-color:var(--b1);color:var(--t2)}
.port-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:var(--sp-3);margin-bottom:var(--sp-6)}
.stat-card{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-3) var(--sp-4);text-align:center}
.stat-val{font-family:var(--font-mono);font-size:22px;font-weight:700;line-height:1.2}
.stat-lbl{font-family:var(--font-mono);font-size:11px;letter-spacing:1.5px;color:var(--t4);margin-top:2px}
.pl-up{color:var(--c-up)}.pl-dn{color:var(--c-dn)}.pl-flat{color:var(--t3)}

/* Journal tab */
.j-form{display:flex;gap:var(--sp-2);padding:var(--sp-4);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);margin-bottom:var(--sp-4);flex-wrap:wrap;align-items:flex-end}
.j-form label{display:flex;flex-direction:column;gap:2px;font-family:var(--font-mono);font-size:11px;color:var(--t4)}
.j-inp{font-family:var(--font-mono);font-size:12px;padding:4px var(--sp-2);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);color:var(--t1)}
.j-inp:focus{outline:none;border-color:var(--c-warn)}
.j-node{width:120px}
.j-note{flex:1;min-width:200px}
.j-filters{display:flex;gap:var(--sp-2);margin-bottom:var(--sp-4);flex-wrap:wrap}
.j-filt{font-family:var(--font-mono);font-size:11px;padding:4px 10px;border:1px solid var(--b0);border-radius:var(--r-pill);background:none;color:var(--t4);cursor:pointer;transition:all var(--dur-fast)}
.j-filt:hover{color:var(--t2)}
.j-filt.active{border-color:var(--c-warn);color:var(--t1);background:rgba(230,154,76,.08)}
.j-entry{display:flex;gap:var(--sp-3);padding:var(--sp-3) 0;border-bottom:1px solid var(--b0)}
.j-entry:last-child{border-bottom:none}
.j-date{font-family:var(--font-mono);font-size:11px;color:var(--t4);min-width:68px;flex-shrink:0}
.j-type{font-family:var(--font-mono);font-size:11px;font-weight:700;min-width:56px;flex-shrink:0;text-transform:uppercase;letter-spacing:.5px}
.j-type.trade{color:var(--c-warn)}.j-type.review{color:var(--c-up)}.j-type.trigger{color:var(--c-up)}.j-type.note{color:var(--t3)}.j-type.setup{color:var(--c-cstr)}.j-type.state{color:var(--c-fired)}
.j-node-tag{font-family:var(--font-mono);font-size:10px;color:var(--c-appr);background:rgba(230,154,76,.08);padding:1px 5px;border-radius:3px;margin-left:var(--sp-1)}
.j-empty{font-size:13px;color:var(--t4);text-align:center;padding:var(--sp-8)}

/* Responsive */
@media(max-width:1000px){.port-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.port-grid{grid-template-columns:1fr}#cy{height:400px}.mkt-bar{grid-template-columns:repeat(2,1fr)}.hdr-row{flex-wrap:wrap;gap:var(--sp-2)}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}}
"""


# =========================================================================
# JS LOGIC
# =========================================================================

JS_LOGIC = r"""
/* ── XSS Escaping ─────────────────────────────────────────────── */
// WHY: Config-sourced strings (node labels, context, journal text) are injected
// into innerHTML. Without escaping, a crafted config or imported state file can
// execute arbitrary JS in the viewer's browser.
function esc(s){if(s==null)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

/* ── State ─────────────────────────────────────────────────────── */
let B;
const NODE_MAP={};NODES.forEach(n=>{NODE_MAP[n.id]=n});
const STATE_COLORS={fired:'#E05555',approaching:'#E69A4C',stable:'#6E8FAD',gated:'#555555',constrained:'#AD7FA8',monitoring:'#777777'};
const STATE_ORDER=['fired','approaching','stable','gated','constrained','monitoring'];
let cy=null;

function load(){
  try{const r=localStorage.getItem('tg1');if(r){B=JSON.parse(r);if(!B.v||B.v<1){B=JSON.parse(JSON.stringify(DEFAULTS))}}else{B=JSON.parse(JSON.stringify(DEFAULTS))}}catch(e){B=JSON.parse(JSON.stringify(DEFAULTS))}
  if(!B.closeLogs)B.closeLogs={};if(!B.gates)B.gates={};if(!B.positions)B.positions={};if(!B.prices)B.prices={};
  if(!B.ui)B.ui={tab:'graph',jFilt:'all',scenario:'',expanded:[]};
  // Init instrument prices from config
  Object.keys(INSTRUMENTS).forEach(nid=>{INSTRUMENTS[nid].forEach(inst=>{if(!B.prices[inst.id])B.prices[inst.id]=inst.ref||0})});
}
function save(){B.modified=new Date().toISOString();try{localStorage.setItem('tg1',JSON.stringify(B))}catch(e){}}
function exportState(){const j=JSON.stringify(B,null,2);const b=new Blob([j],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download=`thesis-graph-${new Date().toISOString().slice(0,10)}.json`;a.click();URL.revokeObjectURL(u)}
function importState(file){const r=new FileReader();r.onload=e=>{try{const d=JSON.parse(e.target.result);if(d.v===1){B=d;save();renderAll();initGraph()}}catch(err){alert('Invalid file')}};r.readAsText(file)}
function resetState(){if(!confirm('Reset all state? This clears positions, journal, close logs, and gate toggles.'))return;B=JSON.parse(JSON.stringify(DEFAULTS));save();renderAll();initGraph()}
function today(){return new Date().toISOString().slice(0,10)}
function fmt(n,d){if(n==null)return'--';d=d!=null?d:2;return n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d})}
function fPct(n){return(n>=0?'+':'')+n.toFixed(1)+'%'}
function fDate(d){if(!d)return'--';return new Date(d+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'})}

/* ── Node State Evaluation (mirrors Python) ────────────────── */
function evalNodeState(node,market,upstreamStates){
  const t=node.type;
  // Event: state field directly
  if(t==='event'){
    const s=node.state||'monitoring';
    if(s==='active'||s==='fired')return'fired';
    if(s==='resolved')return'stable';
    if(s==='partial')return'approaching';
    return'monitoring';
  }
  // Price: compare current vs thresholds
  if(t==='price'){
    const cur=market[node.id]!=null?market[node.id]:node.current;
    const ths=node.thresholds||[];
    if(cur==null||!ths.length)return'monitoring';
    const sorted=[...ths].sort((a,b)=>(b.level||0)-(a.level||0));
    // WHY: closesRequired can't be evaluated at generation time — needs close log
    for(const th of sorted){
      if(cur>=(th.level||0)){
        if(th.closesRequired){
          const closes=(B.closeLogs[node.id]||[]).filter(c=>c.value>=(th.level||0));
          if(closes.length>=th.closesRequired)return'fired';
          if(cur>=(th.level||0))return'approaching';
        }
        return'fired';
      }
    }
    const lowest=Math.min(...ths.map(t=>t.level||Infinity));
    if(lowest>0&&cur/lowest>=0.95)return'approaching';
    return'stable';
  }
  // Indicator: upstream propagation
  if(t==='indicator'){
    const incoming=EDGES.filter(e=>e.to===node.id);
    if(!incoming.length)return'monitoring';
    let fc=0,ac=0;
    incoming.forEach(e=>{
      const s=upstreamStates[e.from];
      if(s==='fired')fc++;else if(s==='approaching')ac++;
    });
    if(fc>0)return fc>=incoming.length*0.5?'fired':'approaching';
    if(ac>0)return'approaching';
    return'stable';
  }
  // Deadline: check conditions + date
  if(t==='deadline'){
    const dl=node.deadline;
    if(!dl)return'gated';
    const now=new Date();const dlDate=new Date(dl+'T23:59:59');
    const daysLeft=Math.ceil((dlDate-now)/(1000*60*60*24));
    if(daysLeft<0)return'fired';
    const conds=node.conditions||[];
    let anyMet=false;
    conds.forEach(c=>{const p=c.split('.')[0];if(upstreamStates[p]==='fired'||upstreamStates[p]==='approaching')anyMet=true});
    if(daysLeft<=7)return anyMet?'fired':'approaching';
    if(daysLeft<=14)return anyMet?'approaching':'gated';
    return'gated';
  }
  // Gate: binary toggle from user
  if(t==='gate'){return B.gates[node.id]?'fired':'monitoring'}
  // Constraint: active if current > threshold
  if(t==='constraint'){
    const cur=market[node.id]!=null?market[node.id]:node.current;
    const th=node.threshold;
    if(cur!=null&&th!=null&&cur>th)return'constrained';
    return'stable';
  }
  // Conditional: gated if gatedBy not fired, constrained if constraint active
  if(t==='conditional'){
    const gb=node.gatedBy||[];const cb=node.constrainedBy||[];
    for(const cid of cb){if(upstreamStates[cid]==='constrained')return'constrained'}
    const allOpen=gb.every(g=>upstreamStates[g]==='fired');
    if(!allOpen)return'gated';
    return'approaching';
  }
  // Reversal: de-escalation check
  if(t==='reversal'){
    const cur=market[node.id]!=null?market[node.id]:(node.feeds&&node.feeds[0]?market[node.feeds[0].symbol]:null);
    const th=node.threshold;
    if(cur!=null&&th!=null){
      if(cur<=th){
        const closes=(B.closeLogs[node.id]||[]).filter(c=>c.value<=th);
        if(node.closesRequired&&closes.length<node.closesRequired)return'approaching';
        return'fired';
      }
      if(cur/th<1.12)return'approaching';
    }
    return'stable';
  }
  return'monitoring';
}

function recalculate(){
  const market=Object.assign({},B.market);
  const states={};
  TOPO_ORDER.forEach(nid=>{
    const node=NODE_MAP[nid];if(!node)return;
    states[nid]=evalNodeState(node,market,states);
  });
  return states;
}

function scoreConfluence(states){
  const fanIn={};
  EDGES.forEach(e=>{if(!fanIn[e.to])fanIn[e.to]=[];fanIn[e.to].push(e)});
  const scores={};
  Object.keys(fanIn).forEach(nid=>{
    const incoming=fanIn[nid];
    if(incoming.length<2)return;
    let score=0;
    incoming.forEach(e=>{
      const s=states[e.from]||'stable';
      const sig=s==='fired'?1.0:s==='approaching'?0.5:0;
      score+=sig*(e.strength||0.5);
    });
    scores[nid]=Math.round(score*100)/100;
  });
  return scores;
}

/* ── Graph Rendering ───────────────────────────────────────── */
function initGraph(){
  const container=document.getElementById('cy');
  if(!container||typeof cytoscape==='undefined')return;

  const elements=[];
  NODES.forEach(n=>{
    elements.push({data:{id:n.id,label:n.label,type:n.type,phase:n.phase||1}});
  });
  EDGES.forEach(e=>{
    elements.push({data:{id:e.from+'-'+e.to,source:e.from,target:e.to,strength:e.strength,mechanism:e.mechanism||'',lag:e.lag||''}});
  });

  cy=cytoscape({
    container:container,
    elements:elements,
    style:[
      {selector:'node',style:{
        'label':'data(label)','text-valign':'center','text-halign':'center',
        'font-family':'"Outfit",system-ui,sans-serif','font-size':'11px','font-weight':'600',
        'color':'#FFF7EE','text-wrap':'wrap','text-max-width':'90px',
        'background-color':'#6E8FAD','border-width':2,'border-color':'rgba(255,255,255,.15)',
        'width':function(el){return 30+el.data('phase')*12},
        'height':function(el){return 30+el.data('phase')*12},
        'text-outline-width':2,'text-outline-color':'#120C06',
        'transition-property':'background-color,border-color',
        'transition-duration':'0.3s'
      }},
      {selector:'edge',style:{
        'width':function(el){return Math.max(1.5,(el.data('strength')||0.5)*5)},
        'line-color':'rgba(255,255,255,.15)',
        'target-arrow-color':'rgba(255,255,255,.25)',
        'target-arrow-shape':'triangle',
        'curve-style':'bezier',
        'arrow-scale':0.8,
        'transition-property':'line-color,target-arrow-color',
        'transition-duration':'0.3s'
      }},
      {selector:'node:selected',style:{
        'border-width':3,'border-color':'#E69A4C','overlay-opacity':0
      }}
    ],
    layout:{name:'dagre',rankDir:'TB',nodeSep:40,rankSep:60,edgeSep:10,padding:20},
    userZoomingEnabled:true,userPanningEnabled:true,boxSelectionEnabled:false,
    minZoom:0.3,maxZoom:2.5
  });

  cy.on('tap','node',function(evt){
    const nid=evt.target.id();
    renderNodeDetail(nid);
  });
  cy.on('tap',function(evt){
    if(evt.target===cy){document.getElementById('node-detail').innerHTML='<div class="nd-empty">Click a node to see details</div>'}
  });
  cy.on('mouseover','edge',function(evt){
    const ed=evt.target.data();
    evt.target.style({'line-color':'rgba(255,255,255,.4)','target-arrow-color':'rgba(255,255,255,.5)'});
    // Show tooltip if mechanism exists
    const tip=document.getElementById('edge-tip');
    if(tip&&ed.mechanism){
      tip.textContent=ed.mechanism+(ed.lag?' ('+ed.lag+')':'');
      tip.style.display='block';
      const pos=evt.renderedPosition||evt.position;
      if(pos){tip.style.left=(pos.x||0)+'px';tip.style.top=(pos.y||0)+'px'}
    }
  });
  cy.on('mouseout','edge',function(evt){
    evt.target.style({'line-color':'rgba(255,255,255,.15)','target-arrow-color':'rgba(255,255,255,.25)'});
    const tip=document.getElementById('edge-tip');
    if(tip)tip.style.display='none';
  });

  renderGraph();
}

function renderGraph(){
  if(!cy)return;
  const states=recalculate();
  const conf=scoreConfluence(states);

  cy.nodes().forEach(n=>{
    const nid=n.id();
    const st=states[nid]||'monitoring';
    const col=STATE_COLORS[st]||'#777';
    n.style({'background-color':col,'border-color':col,'border-opacity':0.5});
    // Confluence badge
    if(conf[nid]&&conf[nid]>0.5){
      n.style({'border-width':3+Math.min(conf[nid]*2,4),'border-color':'#E69A4C'});
    }
  });

  // Color edges whose source is fired/approaching
  cy.edges().forEach(e=>{
    const srcSt=states[e.data('source')]||'stable';
    if(srcSt==='fired'){
      e.style({'line-color':'rgba(224,85,85,.5)','target-arrow-color':'rgba(224,85,85,.6)'});
    }else if(srcSt==='approaching'){
      e.style({'line-color':'rgba(230,154,76,.4)','target-arrow-color':'rgba(230,154,76,.5)'});
    }else{
      e.style({'line-color':'rgba(255,255,255,.15)','target-arrow-color':'rgba(255,255,255,.25)'});
    }
  });
}

function renderNodeDetail(nid){
  const node=NODE_MAP[nid];if(!node)return;
  const states=recalculate();
  const st=states[nid]||'monitoring';
  const col=STATE_COLORS[st]||'#777';
  const conf=scoreConfluence(states);

  let h=`<div class="nd-title">${esc(node.label)} <span class="nd-type">${esc(node.type)}</span><span class="nd-state" style="background:${col}22;color:${col};border:1px solid ${col}44">${st.toUpperCase()}</span></div>`;

  // Probability
  if(node.probability!=null){h+=`<div style="font-family:var(--font-mono);font-size:13px;margin-top:4px">Probability: <strong>${(node.probability*100).toFixed(1)}%</strong></div>`}

  // Current value
  if(B.market[nid]!=null){h+=`<div style="font-family:var(--font-mono);font-size:13px;margin-top:4px">Current: <strong>${fmt(B.market[nid])}</strong></div>`}
  else if(node.current!=null){h+=`<div style="font-family:var(--font-mono);font-size:13px;margin-top:4px">Current: <strong>${fmt(node.current)}</strong></div>`}

  // Thresholds
  if(node.thresholds&&node.thresholds.length){
    h+=`<div class="nd-section"><h4>Thresholds</h4>`;
    node.thresholds.forEach(th=>{
      const cur=B.market[nid]!=null?B.market[nid]:node.current;
      const pct=cur!=null&&th.level?(cur/th.level*100).toFixed(1):'--';
      const above=cur!=null&&cur>=th.level;
      h+=`<div class="nd-threshold"><span>${esc(th.label)||''}: ${th.level}</span><span style="color:${above?'var(--c-fired)':'var(--t4)'}${th.closesRequired?' ':''}${th.closesRequired?'('+th.closesRequired+' closes)':''}">${pct}%</span></div>`;
    });
    h+=`</div>`;
  }

  // Deadline countdown
  if(node.deadline){
    const dlDate=new Date(node.deadline+'T23:59:59');const now=new Date();
    const days=Math.ceil((dlDate-now)/(1000*60*60*24));
    h+=`<div class="nd-section"><h4>Deadline</h4><div style="font-family:var(--font-mono);font-size:18px;font-weight:800;color:${days<=7?'var(--c-fired)':days<=14?'var(--c-warn)':'var(--t2)'}">${days>0?days+' days':days===0?'TODAY':'PASSED ('+Math.abs(days)+'d ago)'}</div><div style="font-size:12px;color:var(--t4)">${esc(node.deadline)}${node.irreversible?' — IRREVERSIBLE':''}</div></div>`;
  }

  // Feeds
  if(node.feeds&&node.feeds.length){
    h+=`<div class="nd-section"><h4>Data Feeds</h4>`;
    node.feeds.forEach(f=>{h+=`<div class="nd-feed">${esc(f.source)}${f.symbol?' — '+esc(f.symbol):''}${f.series?' — '+esc(f.series):''}${f.label?' ('+esc(f.label)+')':''}</div>`});
    h+=`</div>`;
  }

  // Indicators
  if(node.indicators&&node.indicators.length){
    h+=`<div class="nd-section"><h4>Indicators</h4>`;
    node.indicators.forEach(ind=>{
      const dotCol=ind.status==='red'?'var(--c-fired)':ind.status==='amber'?'var(--c-warn)':'var(--c-stable)';
      h+=`<div class="nd-indicator"><span class="dot" style="background:${dotCol}"></span><span>${esc(ind.label)}: <strong>${esc(ind.value)||'--'}</strong></span></div>`;
    });
    h+=`</div>`;
  }

  // Confluence
  if(conf[nid]){
    h+=`<div class="nd-section"><h4>Signal Confluence</h4><div style="font-family:var(--font-mono);font-size:16px;font-weight:700;color:${conf[nid]>1.5?'var(--c-fired)':'var(--c-warn)'}">${conf[nid].toFixed(2)}</div><div style="font-size:12px;color:var(--t4)">${EDGES.filter(e=>e.to===nid).length} upstream paths converge</div></div>`;
  }

  // Instruments at this node
  if(INSTRUMENTS[nid]){
    h+=`<div class="nd-section"><h4>Instruments</h4>`;
    INSTRUMENTS[nid].forEach(inst=>{
      const price=B.prices[inst.id]||inst.ref;
      h+=`<div style="font-family:var(--font-mono);font-size:12px;padding:2px 0">${inst.id} — $${fmt(price)} (ref: $${fmt(inst.ref)})${inst.role?' — '+inst.role:''}</div>`;
    });
    h+=`</div>`;
  }

  // Context
  if(node.context){h+=`<div class="nd-section"><h4>Context</h4><div class="nd-context">${esc(node.context)}</div></div>`}
  // Historical lag
  if(node.historicalLag){h+=`<div style="font-family:var(--font-mono);font-size:11px;color:var(--t4);margin-top:var(--sp-2)">Historical: ${esc(node.historicalLag)}</div>`}
  // Action
  if(node.action){h+=`<div class="nd-section"><h4>Action</h4><div style="font-size:13px;font-weight:600;color:var(--c-warn)">${esc(node.action)}</div></div>`}

  document.getElementById('node-detail').innerHTML=h;
}

/* ── Cascade Rendering ─────────────────────────────────────── */
function renderCascade(){
  const phaseOrder=['shock','transmission','amplification','policyResponse','resolution'];
  const phaseLabels={shock:'Phase 1: Shock',transmission:'Phase 2: Transmission',amplification:'Phase 3: Amplification',policyResponse:'Phase 4: Policy Response',resolution:'Phase 5: Resolution'};
  let h='';

  // Countdown for deadline nodes
  NODES.forEach(n=>{
    if(n.type==='deadline'&&n.countdown&&n.deadline){
      const dlDate=new Date(n.deadline+'T23:59:59');const now=new Date();
      const days=Math.ceil((dlDate-now)/(1000*60*60*24));
      if(days>0){
        h+=`<div class="countdown-box"><div class="countdown-num">${days}</div><div class="countdown-lbl">DAYS UNTIL ${esc(n.label).toUpperCase()}</div><div style="font-size:12px;color:var(--t3);margin-top:4px">${esc(n.deadline)}${n.irreversible?' — irreversible once passed':''}</div></div>`;
      }else if(days<=0){
        h+=`<div class="countdown-box" style="background:rgba(224,85,85,.08);border-color:rgba(224,85,85,.2)"><div class="countdown-num" style="color:var(--c-fired)">${days===0?'TODAY':'PASSED'}</div><div class="countdown-lbl">${esc(n.label).toUpperCase()}</div></div>`;
      }
    }
  });

  h+=`<div class="cascade-timeline">`;
  phaseOrder.forEach((key,i)=>{
    const phase=CASCADE[key];if(!phase)return;
    const status=(phase.status||'').toUpperCase();
    const cls=status==='COMPLETE'?'cp-complete':
      (status==='STARTING'||status==='ACTIVE')?'cp-active':
      status==='APPROACHING'?'cp-approaching':'cp-watching';
    const isHere=status==='STARTING'||status==='ACTIVE';
    const statusCol=status==='COMPLETE'?'var(--c-up)':(status==='STARTING'||status==='ACTIVE')?'var(--c-warn)':status==='APPROACHING'?'var(--c-appr)':'var(--t4)';

    h+=`<div class="cascade-phase ${cls}"><span class="cp-num">${i+1}</span>`;
    if(isHere)h+=`<div class="cp-here">&#9654; WE ARE HERE</div>`;
    h+=`<div class="cp-title">${esc(phase.label)||phaseLabels[key]} <span class="cp-status" style="background:${statusCol}22;color:${statusCol}">${esc(status)}</span></div>`;

    // Signposts
    if(phase.signposts&&phase.signposts.length){
      h+=`<ul class="cp-signposts">`;
      phase.signposts.forEach(sp=>{
        const spSt=(sp.status||'').toLowerCase();
        const icon=spSt==='fired'?'&#10003;':spSt==='approaching'?'&#9202;':spSt==='partial'?'&#9679;':'&#9675;';
        const iconCol=spSt==='fired'?'color:var(--c-up)':spSt==='approaching'?'color:var(--c-warn)':'color:var(--t4)';
        h+=`<li class="cp-sp"><span class="cp-sp-icon" style="${iconCol}">${icon}</span><span class="cp-sp-text">${esc(sp.text)}</span>`;
        if(sp.value)h+=`<span class="cp-sp-val">${esc(sp.value)}</span>`;
        h+=`</li>`;
      });
      h+=`</ul>`;
    }

    // Timing
    if(phase.estimatedTiming){h+=`<div class="cp-timing">Est: ${phase.estimatedTiming}</div>`}

    h+=`</div>`;
  });
  h+=`</div>`;

  // Analogs
  if(ANALOGS.length){
    h+=`<div class="sec-label" style="margin-top:var(--sp-8)">Historical Analogs</div>`;
    ANALOGS.forEach(a=>{
      h+=`<div style="background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4);margin-bottom:var(--sp-3)"><div style="font-weight:700;font-size:14px">${esc(a.name)} <span style="font-family:var(--font-mono);font-size:11px;color:var(--t4)">${esc(a.similarity)||''}</span></div>`;
      if(a.keyLags){
        Object.entries(a.keyLags).forEach(([k,v])=>{
          h+=`<div style="font-family:var(--font-mono);font-size:12px;color:var(--t3);padding:1px 0">${esc(k)}: ${esc(v)}</div>`;
        });
      }
      if(a.notes)h+=`<div style="font-size:13px;color:var(--t3);margin-top:4px">${esc(a.notes)}</div>`;
      h+=`</div>`;
    });
  }

  document.getElementById('cascade-content').innerHTML=h;
}

/* ── Scenario Rendering ────────────────────────────────────── */
function evalScenario(scenario){
  // Apply overrides to a copy of market and node states
  const market=Object.assign({},B.market);
  const overrides=scenario.overrides||{};
  // Build temporary node map with overrides applied
  const tempNodes={};
  NODES.forEach(n=>{tempNodes[n.id]=Object.assign({},n)});
  Object.keys(overrides).forEach(nid=>{
    if(!tempNodes[nid])return;
    const val=overrides[nid];
    if(typeof val==='string'){tempNodes[nid].state=val}
    else if(typeof val==='number'){tempNodes[nid].current=val;market[nid]=val}
  });

  // Propagate with overrides
  const states={};
  TOPO_ORDER.forEach(nid=>{
    const node=tempNodes[nid];if(!node)return;
    // For overridden event nodes, use overridden state
    if(overrides[nid]&&typeof overrides[nid]==='string'){
      if(overrides[nid]==='resolved')states[nid]='stable';
      else if(overrides[nid]==='active'||overrides[nid]==='fired')states[nid]='fired';
      else if(overrides[nid]==='partial')states[nid]='approaching';
      else states[nid]=evalNodeState(node,market,states);
    }else{
      states[nid]=evalNodeState(node,market,states);
    }
  });

  // Compute portfolio impact
  const baseStates=recalculate();
  const impact={};
  const stateMult={fired:1.0,approaching:0.4,stable:0.0,gated:-0.1,constrained:-0.2,monitoring:0.0};
  Object.keys(INSTRUMENTS).forEach(nid=>{
    INSTRUMENTS[nid].forEach(inst=>{
      const beta=inst.beta||0.5;const ref=inst.ref||0;
      if(ref<=0||inst.isReserve)return;
      const baseSig=stateMult[baseStates[nid]||'stable']||0;
      const newSig=stateMult[states[nid]||'stable']||0;
      const delta=newSig-baseSig;
      const pctImpact=Math.round(beta*delta*200)/10;
      impact[inst.id]={pct:pctImpact,from:baseStates[nid]||'stable',to:states[nid]||'stable'};
    });
  });

  return{states,impact};
}

function renderScenarios(){
  const sel=B.ui.scenario||'';
  let h='<div class="sc-pills">';
  SCENARIOS.forEach(s=>{
    const act=s.id===sel?'active':'';
    h+=`<button class="sc-pill ${act}" data-sc="${esc(s.id)}">${esc(s.name)}<span class="sc-prob">${s.probability!=null?Math.round(s.probability*100)+'%':''}</span></button>`;
  });
  h+='</div>';

  if(!sel||!SCENARIOS.find(s=>s.id===sel)){
    // Show probability-weighted EV across all scenarios
    h+=`<div class="sc-ev"><div class="sc-ev-title">Probability-Weighted Expected Impact</div>`;
    const ev={};
    SCENARIOS.forEach(s=>{
      const{impact}=evalScenario(s);
      const prob=s.probability||0;
      Object.keys(impact).forEach(iid=>{
        if(!ev[iid])ev[iid]=0;
        ev[iid]+=impact[iid].pct*prob;
      });
    });
    if(Object.keys(ev).length){
      const sorted=Object.entries(ev).sort((a,b)=>b[1]-a[1]);
      sorted.forEach(([iid,pct])=>{
        const col=pct>=0?'var(--c-up)':'var(--c-dn)';
        const w=Math.min(Math.abs(pct)*2,50);
        h+=`<div class="wf-row"><span class="wf-label">${iid}</span><div class="wf-bar-wrap"><div class="wf-bar ${pct>=0?'pos':'neg'}" style="width:${w}%;${pct<0?'right:50%;left:auto':'left:50%'}"></div></div><span class="wf-pct" style="color:${col}">${pct>=0?'+':''}${pct.toFixed(1)}%</span></div>`;
      });
    }else{h+=`<div class="sc-empty">No instruments with beta defined</div>`}
    h+=`</div>`;

    document.getElementById('scenario-content').innerHTML=h;
    return;
  }

  const scenario=SCENARIOS.find(s=>s.id===sel);
  const{states:scStates,impact}=evalScenario(scenario);

  // Scenario detail panel
  h+=`<div class="sc-detail"><div class="sc-name">${esc(scenario.name)} <span style="font-family:var(--font-mono);font-size:12px;color:var(--t4)">${scenario.probability!=null?Math.round(scenario.probability*100)+'%':''}</span></div>`;
  if(scenario.notes)h+=`<div class="sc-notes">${esc(scenario.notes)}</div>`;

  // Overrides table
  const overrides=scenario.overrides||{};
  if(Object.keys(overrides).length){
    h+=`<div class="sc-overrides"><div style="font-family:var(--font-mono);font-size:11px;letter-spacing:2px;color:var(--t4);margin-bottom:var(--sp-2)">OVERRIDES</div>`;
    Object.entries(overrides).forEach(([nid,val])=>{
      const node=NODE_MAP[nid];
      const label=node?node.label:nid;
      const valStr=typeof val==='string'?val:'$'+fmt(val);
      h+=`<div class="sc-override-row"><span class="sc-override-node">${esc(label)}</span><span class="sc-override-val">${esc(valStr)}</span></div>`;
    });
    h+=`</div>`;
  }

  // Node state changes
  const baseStates=recalculate();
  h+=`<div style="margin-top:var(--sp-4)"><div style="font-family:var(--font-mono);font-size:11px;letter-spacing:2px;color:var(--t4);margin-bottom:var(--sp-2)">STATE CHANGES</div>`;
  NODES.forEach(n=>{
    const base=baseStates[n.id]||'monitoring';
    const sc=scStates[n.id]||'monitoring';
    if(base!==sc){
      h+=`<div style="font-family:var(--font-mono);font-size:12px;padding:2px 0"><span style="color:var(--t2)">${esc(n.label)}</span> <span style="color:${STATE_COLORS[base]}">${base}</span> → <span style="color:${STATE_COLORS[sc]}">${sc}</span></div>`;
    }
  });
  h+=`</div>`;

  // Waterfall chart
  h+=`<div class="waterfall"><div style="font-family:var(--font-mono);font-size:11px;letter-spacing:2px;color:var(--t4);margin-bottom:var(--sp-2);margin-top:var(--sp-4)">PORTFOLIO IMPACT</div>`;
  const sorted=Object.entries(impact).sort((a,b)=>b[1].pct-a[1].pct);
  sorted.forEach(([iid,data])=>{
    if(data.pct===0)return;
    const col=data.pct>=0?'var(--c-up)':'var(--c-dn)';
    const w=Math.min(Math.abs(data.pct)*2,50);
    h+=`<div class="wf-row"><span class="wf-label">${iid}</span><div class="wf-bar-wrap"><div class="wf-bar ${data.pct>=0?'pos':'neg'}" style="width:${w}%;${data.pct<0?'right:50%;left:auto':'left:50%'}"></div></div><span class="wf-pct" style="color:${col}">${data.pct>=0?'+':''}${data.pct.toFixed(1)}%</span></div>`;
  });
  h+=`</div></div>`;

  document.getElementById('scenario-content').innerHTML=h;
}

/* ── Portfolio Rendering ───────────────────────────────────── */
function posVal(id){const pos=B.positions[id];if(!pos||!pos.lots||!pos.lots.length)return{shares:0,cost:0,mktVal:0,pl:0,plPct:0};let sh=0,cost=0;pos.lots.forEach(l=>{if(l.type==='buy'){sh+=l.shares;cost+=l.shares*l.price}else{const avg=sh>0?cost/sh:0;sh-=l.shares;cost-=l.shares*avg}});const price=B.prices[id]||0;const mv=sh*price;return{shares:sh,cost,mktVal:mv,pl:mv-cost,plPct:cost>0?((mv-cost)/cost*100):0}}
function bookTotals(){let tv=0,tc=0;Object.keys(INSTRUMENTS).forEach(nid=>{INSTRUMENTS[nid].forEach(inst=>{const p=posVal(inst.id);tv+=p.mktVal;tc+=p.cost})});return{val:tv,cost:tc,pl:tv-tc,plPct:tc>0?((tv-tc)/tc*100):0}}

function renderPortfolio(){
  const bt=bookTotals();
  const states=recalculate();
  const plCls=bt.pl>0?'pl-up':bt.pl<0?'pl-dn':'pl-flat';

  let h=`<div class="port-stats"><div class="stat-card"><div class="stat-val">$${fmt(bt.val,0)}</div><div class="stat-lbl">BOOK VALUE</div></div><div class="stat-card"><div class="stat-val ${plCls}">${bt.pl>=0?'+':''}$${fmt(bt.pl,0)}</div><div class="stat-lbl">UNREALIZED P&L</div></div><div class="stat-card"><div class="stat-val ${plCls}">${fPct(bt.plPct)}</div><div class="stat-lbl">RETURN</div></div><div class="stat-card"><div class="stat-val">$${fmt(bt.cost,0)}</div><div class="stat-lbl">TOTAL DEPLOYED</div></div></div>`;

  // Group instruments by node
  const nodeOrder=TOPO_ORDER.filter(nid=>INSTRUMENTS[nid]);
  // Add "reserve" if present
  if(INSTRUMENTS['reserve'])nodeOrder.push('reserve');

  nodeOrder.forEach(nid=>{
    const insts=INSTRUMENTS[nid];if(!insts||!insts.length)return;
    const node=NODE_MAP[nid];
    const st=states[nid]||'monitoring';
    const stCol=STATE_COLORS[st]||'#777';
    const label=node?node.label:(nid==='reserve'?'Reserve':'Unknown');

    h+=`<div class="port-group"><div class="port-group-title">${esc(label)} <span class="port-group-badge" style="background:${stCol}22;color:${stCol};border:1px solid ${stCol}44">${st.toUpperCase()}</span></div><div class="port-grid">`;

    insts.forEach(inst=>{
      const c=B.prices[inst.id]||inst.ref;
      const pv=posVal(inst.id);
      const isReserve=inst.isReserve;
      let rangeH='',posH='';

      if(pv.shares>0){
        const plc=pv.pl>=0?'pl-up':'pl-dn';
        posH=`<div class="p-pos"><div class="p-pos-row"><span class="lbl">Shares</span><span class="val">${fmt(pv.shares,2)}</span></div><div class="p-pos-row"><span class="lbl">Avg Cost</span><span class="val">$${fmt(pv.cost/pv.shares)}</span></div><div class="p-pos-row"><span class="lbl">Mkt Value</span><span class="val">$${fmt(pv.mktVal)}</span></div><div class="p-pos-row"><span class="lbl">P&L</span><span class="val ${plc}">${pv.pl>=0?'+':''}$${fmt(pv.pl)} (${fPct(pv.plPct)})</span></div></div>`;
      }else{
        posH='<div class="p-empty">No position yet</div>';
      }

      if(!isReserve&&inst.targetLow!=null&&inst.stop!=null){
        const pos=rngPos(c,inst.stop,inst.targetLow);
        const up=((inst.targetLow-c)/c*100);
        const dn=((c-inst.stop)/c*100);
        const rr=dn>0?(up/dn).toFixed(1):'--';
        const fc=pos<30?'var(--c-dn)':stCol;
        rangeH=`<div class="p-range"><div class="p-track"><div class="p-fill" style="width:${pos}%;background:${fc};opacity:.3"></div><div class="p-mark" style="left:${pos}%;background:${stCol}"></div></div><div class="p-labels"><span class="stp">${fmt(inst.stop)}</span><span>${fmt(c)}</span><span class="tgt">${fmt(inst.targetLow)}-${fmt(inst.targetHigh)}</span></div><div class="p-metrics"><span class="up">${fPct(up)} tgt</span><span class="rr">${rr}:1</span><span class="dn">${fPct(-dn)} stop</span></div></div>`;
      }

      // Lot list
      let lotsH='';
      const lots=(B.positions[inst.id]&&B.positions[inst.id].lots)||[];
      if(lots.length){
        lotsH='<div style="margin-top:6px;font-family:var(--font-mono);font-size:11px">';
        lots.forEach(l=>{lotsH+=`<div style="display:flex;justify-content:space-between;padding:1px 0;border-bottom:1px solid var(--b0)"><span style="color:var(--t4)">${fDate(l.date)}</span><span style="color:${l.type==='buy'?'var(--c-up)':'var(--c-dn)'}">${l.type==='buy'?'+':'-'}${l.shares}</span><span>$${fmt(l.price)}</span></div>`});
        lotsH+='</div>';
      }

      h+=`<div class="p-card" data-inst="${inst.id}"><style>.p-card[data-inst="${inst.id}"]::before{background:${stCol}}</style><div class="p-head"><span class="p-ticker" style="color:${stCol}">${inst.id}</span>${inst.monthly?`<span class="p-alloc">$${inst.monthly.toLocaleString()}/mo</span>`:''}</div><div class="p-role">${inst.role||''}</div>${posH}<div class="p-price-row"><span class="p-price-lbl">Price</span><input type="number" step=".01" class="p-price-inp" value="${c}" data-inst="${inst.id}"></div>${rangeH}${lotsH}<button class="btn-open-form" data-pf="${inst.id}">+ Add Position</button><div class="pos-form" id="pf-${inst.id}"><div class="pf-row"><input type="date" class="pf-inp w-date" value="${today()}" data-f="date"><input type="number" class="pf-inp w-num" placeholder="Shares" step=".01" data-f="shares"><input type="number" class="pf-inp w-num" placeholder="Price" step=".01" value="${c}" data-f="price"><select class="pf-inp" data-f="type"><option value="buy">Buy</option><option value="sell">Sell</option></select></div><div class="pf-row"><input type="text" class="pf-inp w-note" placeholder="Note" data-f="note"><div style="display:flex;gap:var(--sp-2)"><button class="btn-add primary" data-pf-add="${inst.id}">Add</button><button class="btn-add ghost" data-pf-cancel="${inst.id}">Cancel</button></div></div></div></div>`;
    });

    h+=`</div></div>`;
  });

  document.getElementById('portfolio-content').innerHTML=h;
}

function rngPos(c,s,t){if(!s||!t)return 50;const r=t-s;return r===0?50:Math.max(0,Math.min(100,((c-s)/r)*100))}

/* ── Journal Rendering ─────────────────────────────────────── */
function renderJournal(){
  const filt=B.ui.jFilt||'all';
  const types=['all','trade','review','trigger','note','setup','state'];
  let fh='';
  types.forEach(t=>{fh+=`<button class="j-filt ${t===filt?'active':''}" data-jf="${t}">${t==='all'?'All':t.charAt(0).toUpperCase()+t.slice(1)}</button>`});
  document.getElementById('j-filters').innerHTML=fh;
  const entries=filt==='all'?B.journal:B.journal.filter(e=>e.type===filt);
  if(!entries.length){document.getElementById('j-list').innerHTML='<div class="j-empty">No entries yet.</div>';return}
  let eh='';
  entries.forEach(e=>{
    eh+=`<div class="j-entry"><span class="j-date">${fDate(e.date)}</span><span class="j-type ${esc(e.type)}">${esc(e.type)}</span><span>${esc(e.text)}${e.node?'<span class="j-node-tag">'+esc(e.node)+'</span>':''}</span></div>`;
  });
  document.getElementById('j-list').innerHTML=eh;
}

/* ── Market Data Bar ───────────────────────────────────────── */
function renderMarketBar(){
  let h='';
  NODES.forEach(n=>{
    if(n.current!=null&&typeof n.current==='number'){
      const hasFeed=n.feeds&&n.feeds.some(f=>f.source==='yahoo'||f.source==='eia'||f.source==='fred');
      if(hasFeed||n.type==='price'||n.type==='constraint'||n.type==='reversal'){
        const val=B.market[n.id]!=null?B.market[n.id]:n.current;
        h+=`<div class="mkt-item"><label class="mkt-lbl" for="mkt-${esc(n.id)}">${esc(n.label)}</label><input class="mkt-inp" type="number" step="0.01" id="mkt-${esc(n.id)}" data-nid="${esc(n.id)}" value="${val}"></div>`;
      }
    }
  });
  document.getElementById('mkt-bar').innerHTML=h;
}

/* ── Phase Badge ───────────────────────────────────────────── */
function renderPhaseBadge(){
  const states=recalculate();
  // Determine highest active phase
  let maxPhase=1;
  NODES.forEach(n=>{
    const st=states[n.id];
    if((st==='fired'||st==='approaching')&&(n.phase||1)>maxPhase)maxPhase=n.phase||1;
  });
  const colors={1:'#6E8FAD',2:'#E69A4C',3:'#E05555',4:'#AD7FA8',5:'#4CC4B4'};
  const col=colors[maxPhase]||'#6E8FAD';
  document.getElementById('phase-badge').innerHTML=`<span class="phase-badge" style="background:${col}22;color:${col};border:1px solid ${col}44">Phase ${maxPhase}</span>`;
}

/* ── Master Render ─────────────────────────────────────────── */
function renderAll(){
  renderPhaseBadge();
  renderMarketBar();
  renderGraph();
  renderCascade();
  renderScenarios();
  renderPortfolio();
  renderJournal();
}

/* ── Event Binding ─────────────────────────────────────────── */
function bindEvents(){
  // Tabs
  document.querySelector('.tab-bar').addEventListener('click',e=>{
    const b=e.target.closest('.tab-btn');if(!b)return;
    document.querySelectorAll('.tab-btn,.tab-pane').forEach(el=>el.classList.remove('active'));
    b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active');
    B.ui.tab=b.dataset.tab;save();
    // Re-render graph when switching to graph tab (Cytoscape needs visible container)
    if(b.dataset.tab==='graph'&&cy){cy.resize();cy.fit(undefined,20)}
  });

  // Market data inputs
  document.getElementById('mkt-bar').addEventListener('input',e=>{
    if(e.target.classList.contains('mkt-inp')){
      const nid=e.target.dataset.nid;
      const v=parseFloat(e.target.value);
      if(!isNaN(v)){B.market[nid]=v;save();renderGraph();renderPhaseBadge()}
    }
  });

  // Scenario pills
  document.getElementById('scenario-content').addEventListener('click',e=>{
    const pill=e.target.closest('.sc-pill');
    if(pill){
      const sid=pill.dataset.sc;
      B.ui.scenario=B.ui.scenario===sid?'':sid;
      save();renderScenarios();
    }
  });

  // Portfolio: price inputs
  document.getElementById('portfolio-content').addEventListener('input',e=>{
    if(e.target.classList.contains('p-price-inp')){
      const id=e.target.dataset.inst;
      const v=parseFloat(e.target.value);
      if(!isNaN(v)){B.prices[id]=v;save();renderPortfolio()}
    }
  });

  // Portfolio: position forms
  document.getElementById('portfolio-content').addEventListener('click',e=>{
    const ob=e.target.closest('[data-pf]');
    if(ob&&!e.target.dataset.pfAdd&&!e.target.dataset.pfCancel){
      const f=document.getElementById('pf-'+ob.dataset.pf);
      if(f)f.classList.toggle('open');return;
    }
    const ab=e.target.closest('[data-pf-add]');
    if(ab){
      const id=ab.dataset.pfAdd;
      const f=document.getElementById('pf-'+id);
      const dt=f.querySelector('[data-f="date"]').value;
      const sh=f.querySelector('[data-f="shares"]').value;
      const pr=f.querySelector('[data-f="price"]').value;
      const tp=f.querySelector('[data-f="type"]').value;
      const nt=f.querySelector('[data-f="note"]').value;
      if(sh&&pr){
        if(!B.positions[id])B.positions[id]={lots:[]};
        B.positions[id].lots.push({date:dt||today(),shares:+sh,price:+pr,type:tp,note:nt||''});
        B.journal.unshift({id:Date.now(),date:today(),type:'trade',text:`${tp==='buy'?'Bought':'Sold'} ${sh} ${id} @ $${fmt(+pr)}${nt?'. '+nt:''}`,node:''});
        save();renderPortfolio();
        f.classList.remove('open');
      }
      return;
    }
    const cb=e.target.closest('[data-pf-cancel]');
    if(cb){const f=document.getElementById('pf-'+cb.dataset.pfCancel);if(f)f.classList.remove('open')}
  });

  // Journal: add entry
  document.getElementById('j-add').addEventListener('click',()=>{
    const t=document.getElementById('j-type').value;
    const d=document.getElementById('j-date').value||today();
    const n=document.getElementById('j-text').value.trim();
    const nd=document.getElementById('j-node-sel').value;
    if(!n)return;
    B.journal.unshift({id:Date.now(),date:d,type:t,text:n,node:nd});
    save();document.getElementById('j-text').value='';renderJournal();
  });
  document.getElementById('j-text').addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();document.getElementById('j-add').click()}
  });

  // Journal: filters
  document.getElementById('journal').addEventListener('click',e=>{
    const f=e.target.closest('.j-filt');
    if(f){B.ui.jFilt=f.dataset.jf;save();renderJournal()}
  });

  // Export / Import / Reset
  document.getElementById('btn-export').addEventListener('click',exportState);
  document.getElementById('btn-import').addEventListener('change',e=>{if(e.target.files[0])importState(e.target.files[0])});
  document.getElementById('btn-reset').addEventListener('click',resetState);

  // Fetch Live
  //
  // WHY the two-step fetch: when this dashboard is served by the tradingDesk
  // webapp, the relative `/api/relay/yahoo` path hits our own relay on the
  // droplet — no third-party dependency, controlled allowlist, 30s cache.
  // When the file is opened standalone (file:// or any non-webapp host),
  // the relay 404s and we fall back to the hosted relay on the production
  // droplet. allorigins.win is gone.
  document.getElementById('btn-fetch').addEventListener('click',async()=>{
    const btn=document.getElementById('btn-fetch');
    btn.textContent='Fetching...';btn.disabled=true;
    const RELAY_BASES=[
      // Same-origin relay first — works when served by the webapp.
      '/api/relay/yahoo',
      // Fall back to the production droplet when opened standalone.
      'https://167.99.113.232:8000/api/relay/yahoo',
    ];
    async function relayFetch(yUrl){
      let lastErr;
      for(const base of RELAY_BASES){
        try{
          const r=await fetch(`${base}?url=${encodeURIComponent(yUrl)}`);
          if(r.ok)return await r.json();
          lastErr=new Error(`relay ${base} ${r.status}`);
        }catch(e){lastErr=e;}
      }
      throw lastErr||new Error('relay unreachable');
    }
    try{
      const allSyms=[...Object.keys(FETCH_SYMS.nodeMap),...FETCH_SYMS.instruments];
      if(!allSyms.length){btn.textContent='No symbols';btn.disabled=false;return}
      // Batch into groups of 8
      for(let i=0;i<allSyms.length;i+=8){
        const batch=allSyms.slice(i,i+8);
        const yUrl=`https://query1.finance.yahoo.com/v7/finance/spark?symbols=${encodeURIComponent(batch.join(','))}&range=1d&interval=1d`;
        const d=await relayFetch(yUrl);
        (d.spark?.result||[]).forEach(item=>{
          const s=item.symbol;
          const p=item.response?.[0]?.meta?.regularMarketPrice;
          if(!p)return;
          // Update node market data
          if(FETCH_SYMS.nodeMap[s]){
            const nid=FETCH_SYMS.nodeMap[s];
            B.market[nid]=+p.toFixed(2);
          }
          // Update instrument prices
          if(B.prices[s]!==undefined)B.prices[s]=+p.toFixed(2);
        });
        if(i+8<allSyms.length)await new Promise(r=>setTimeout(r,1500));
      }
      B.journal.unshift({id:Date.now(),date:today(),type:'note',text:'Live fetch completed',node:''});
      save();renderAll();
      btn.textContent='Fetched';setTimeout(()=>{btn.textContent='Fetch Live';btn.disabled=false},2000);
    }catch(e){
      btn.textContent='Failed';setTimeout(()=>{btn.textContent='Fetch Live';btn.disabled=false},2000);
      console.error('Fetch error:',e);
    }
  });
}

/* ── Init ──────────────────────────────────────────────────── */
load();
document.getElementById('j-date').value=today();
bindEvents();
renderAll();
// WHY: Cytoscape needs a visible container to compute layout.
// Initialize after a small delay to ensure DOM is ready.
setTimeout(()=>{initGraph()},100);
// Restore active tab
if(B.ui.tab){
  const tb=document.querySelector(`.tab-btn[data-tab="${B.ui.tab}"]`);
  if(tb){
    document.querySelectorAll('.tab-btn,.tab-pane').forEach(el=>el.classList.remove('active'));
    tb.classList.add('active');document.getElementById(B.ui.tab).classList.add('active');
    if(B.ui.tab==='graph'&&cy)setTimeout(()=>{cy.resize();cy.fit(undefined,20)},200);
  }
}
"""


# =========================================================================
# HTML TEMPLATE
# =========================================================================

def get_template() -> str:
    """Return the complete HTML template with __PLACEHOLDER__ markers."""
    return r"""<!--
  __CLAIM__
-->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<meta name="description" content="__CLAIM__">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__CLAIM__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
""" + CSS_STYLES + r"""
</style>
<script>
__CYTOSCAPE_JS__
</script>
<script>
__DAGRE_JS__
</script>
</head>
<body>
<header class="app-hdr">
  <div class="hdr-row">
    <div class="hdr-title">__TITLE__ <span class="mono">__AS_OF__</span></div>
    <div id="phase-badge"></div>
    <div class="hdr-export">
      <button class="btn-sm" id="btn-fetch" style="border-color:var(--c-up);color:var(--c-up)">Fetch Live</button>
      <button class="btn-sm" id="btn-export">Export</button>
      <button class="btn-sm" id="btn-reset">Reset</button>
      <label class="btn-sm" style="cursor:pointer">Import<input type="file" accept=".json" id="btn-import" style="display:none"></label>
    </div>
  </div>
  <nav class="tab-bar" role="tablist">
    <button class="tab-btn active" data-tab="graph" role="tab">Graph</button>
    <button class="tab-btn" data-tab="cascade" role="tab">Cascade</button>
    <button class="tab-btn" data-tab="scenarios" role="tab">Scenarios</button>
    <button class="tab-btn" data-tab="portfolio" role="tab">Portfolio</button>
    <button class="tab-btn" data-tab="journal" role="tab">Journal</button>
  </nav>
</header>
<div class="page">

<!-- Market Data Bar -->
<div class="sec-label" style="margin-top:var(--sp-4)">Market Data</div>
<div class="mkt-bar" id="mkt-bar"></div>

<!-- Graph Tab -->
<section class="tab-pane active" id="graph">
  <div id="cy"></div>
  <div id="edge-tip" style="display:none;position:fixed;background:var(--bg0);border:1px solid var(--b1);padding:4px 8px;border-radius:var(--r-sm);font-family:var(--font-mono);font-size:11px;color:var(--t2);pointer-events:none;z-index:200;max-width:300px"></div>
  <div id="node-detail"><div class="nd-empty">Click a node to see details</div></div>
</section>

<!-- Cascade Tab -->
<section class="tab-pane" id="cascade">
  <div id="cascade-content"></div>
</section>

<!-- Scenarios Tab -->
<section class="tab-pane" id="scenarios">
  <div id="scenario-content"></div>
</section>

<!-- Portfolio Tab -->
<section class="tab-pane" id="portfolio">
  <div id="portfolio-content"></div>
</section>

<!-- Journal Tab -->
<section class="tab-pane" id="journal">
  <div class="j-form" id="j-form">
    <label>Type<select class="j-inp" id="j-type"><option value="note">Note</option><option value="trade">Trade</option><option value="review">Review</option><option value="trigger">Trigger</option><option value="state">State Change</option></select></label>
    <label>Date<input type="date" class="j-inp" id="j-date"></label>
    <label>Node<select class="j-inp j-node" id="j-node-sel"><option value="">--</option></select></label>
    <label class="j-note">Entry<input type="text" class="j-inp" id="j-text" placeholder="What happened?"></label>
    <button class="btn-add primary" id="j-add">Log</button>
  </div>
  <div class="j-filters" id="j-filters"></div>
  <div id="j-list"></div>
</section>

</div>

<script>
// ── Data Constants (injected at generation time) ──────────
const NODES=__NODES_JS__;
const EDGES=__EDGES_JS__;
const INSTRUMENTS=__INSTRUMENTS_JS__;
const SCENARIOS=__SCENARIOS_JS__;
const CASCADE=__CASCADE_JS__;
const ANALOGS=__ANALOGS_JS__;
const TOPO_ORDER=__TOPO_ORDER_JS__;
const FETCH_SYMS=__FETCH_JS__;
const DEFAULTS=__DEFAULTS_JS__;
const INIT_STATES=__INIT_STATES_JS__;
const CONFLUENCE=__CONFLUENCE_JS__;

// Populate journal node selector
(function(){
  const sel=document.getElementById('j-node-sel');
  if(sel){NODES.forEach(n=>{const o=document.createElement('option');o.value=n.id;o.textContent=n.label;sel.appendChild(o)})}
})();

""" + JS_LOGIC + r"""
</script>
</body>
</html>
"""


# =========================================================================
# CLI
# =========================================================================

def print_summary(cfg: dict, file=None) -> None:
    """Print a config summary table.

    When file is specified, all output goes there (e.g. sys.stderr for
    --export-state mode, so stdout stays clean for JSON piping).
    """
    out = file or sys.stdout
    meta = cfg.get("meta", {})
    nodes = cfg.get("nodes", [])
    edges = cfg.get("edges", [])
    instruments = cfg.get("instruments", {})
    scenarios = cfg.get("scenarios", [])
    phases = cfg.get("cascadePhases", {})

    total_insts = sum(len(v) for v in instruments.values() if isinstance(v, list))
    phase_num, phase_key = get_current_phase(cfg)

    print(f"\n  Title:       {meta.get('title', '?')}", file=out)
    print(f"  As Of:       {meta.get('asOf', '?')}", file=out)
    print(f"  Nodes:       {len(nodes)} ({', '.join(sorted(set(n.get('type', '?') for n in nodes)))})", file=out)
    print(f"  Edges:       {len(edges)}", file=out)
    print(f"  Instruments: {total_insts} across {len(instruments)} node groups", file=out)
    print(f"  Scenarios:   {len(scenarios)}", file=out)
    print(f"  Phase:       {phase_num} ({phase_key})", file=out)

    # Propagation summary
    try:
        states = propagate(cfg)
        fired = [nid for nid, s in states.items() if s == "fired"]
        approaching = [nid for nid, s in states.items() if s == "approaching"]
        if fired:
            print(f"\n  FIRED:       {', '.join(fired)}", file=out)
        if approaching:
            print(f"  APPROACHING: {', '.join(approaching)}", file=out)
    except Exception as e:
        print(f"  Propagation error: {e}", file=out)

    # Confluence
    try:
        scores = score_confluence(cfg, states)
        if scores:
            print(f"\n  Confluence:", file=out)
            for nid, score in sorted(scores.items(), key=lambda x: -x[1]):
                print(f"    {nid:20s}  {score:.2f}", file=out)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Generate a thesis graph from JSON config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s config.json --dry-run                Validate + summarize only
  %(prog)s config.json -o graph.html             Generate HTML
  %(prog)s config.json -o graph.html --fetch     Generate with live prices
  %(prog)s config.json --fetch --update-config   Write live prices into JSON
  %(prog)s config.json -o graph.html --fetch --validate --publish --force
  %(prog)s config.json --export-state snap.json  Export state as JSON
  %(prog)s config.json --export-state -          Export state to stdout (pipe)
        """,
    )
    parser.add_argument("config", help="JSON config path")
    parser.add_argument("-o", "--output", default="thesis-graph.html", help="Output HTML file")
    parser.add_argument("--fetch", action="store_true", help="Fetch live prices from Yahoo Finance")
    parser.add_argument("--update-config", action="store_true", help="Write fetched prices back into JSON config")
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize only")
    parser.add_argument("--force", action="store_true", help="Overwrite output without asking")
    parser.add_argument("--validate", action="store_true", help="Run validate.py on output")
    parser.add_argument("--screenshot", action="store_true", help="Generate OG screenshot")
    parser.add_argument("--publish", action="store_true", help="Publish to Reading Room")
    parser.add_argument("--username", default="admin", help="Reading Room username")
    parser.add_argument("--slug", help="URL slug for published article")
    parser.add_argument("--category", default="ANALYSIS", help="Article category")
    parser.add_argument("--api-url", default="http://127.0.0.1:8100", help="Reading Room API URL")
    parser.add_argument("--export-state", metavar="FILE",
                        help="Export evaluated graph state as JSON (use - for stdout)")
    args = parser.parse_args()

    # When --export-state is active, all status output goes to stderr
    # so stdout stays clean for JSON piping
    exporting = args.export_state is not None
    log = sys.stderr if exporting else sys.stdout

    # Load
    print(f"Loading: {args.config}", file=log)
    cfg = load_config(args.config)

    # Validate
    issues = validate_config(cfg)
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    for w in warnings:
        print(f"  WARN: {w['field']}: {w['message']}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"  ERROR: {e['field']}: {e['message']}", file=sys.stderr)
        print(f"\n  {len(errors)} error(s). Fix and retry.", file=sys.stderr)
        sys.exit(1)
    print(f"  Valid ({len(warnings)} warning(s))", file=log)

    # Summary
    print_summary(cfg, file=log)

    # Fetch
    if args.fetch or args.update_config:
        print("\nFetching live prices...", file=log)
        cfg = fetch_prices(cfg)
        # WHY polymarket runs alongside yahoo: different data sources feed
        # different node fields (prices vs. probabilities). Both need to
        # run when --fetch is used so the graph has complete live data.
        print("\nFetching Polymarket probabilities...", file=log)
        cfg = fetch_polymarket(cfg)
        # WHY FRED after Yahoo + Polymarket: FRED is end-of-day macro data
        # (Treasury yields, FX rates, policy proxies). It writes to node
        # 'current' fields like Yahoo, but uses a separate API + auth.
        # Silent skip if FRED_API_KEY is unset — FRED is optional.
        print("\nFetching FRED macro series...", file=log)
        cfg = fetch_fred(cfg)
        # WHY EIA after FRED: same dispatch shape (auth-gated, optional),
        # but a different provider for energy-specific data — diesel,
        # crude stocks, refinery util, NG storage. Iran/Hormuz cascade
        # depends on this for diesel + distillate transmission.
        print("\nFetching EIA energy series...", file=log)
        cfg = fetch_eia(cfg)
        # WHY Treasury after EIA: no-auth XML feed for the daily Treasury
        # yield curve. Daily data, single round-trip per --fetch (full year
        # in one call). Powers recession-risk + japan-rate-shock nodes.
        print("\nFetching Treasury yield curve...", file=log)
        cfg = fetch_treasury(cfg)
        # WHY GDELT last among data feeds: no-auth article-volume signal
        # for geopolitical event nodes. Slower (1s/req polite pacing) and
        # the failure mode is more graceful, so it tail-loads naturally.
        print("\nFetching GDELT event volumes...", file=log)
        cfg = fetch_gdelt(cfg)
        # WHY derived indicators AFTER polymarket, BEFORE update_config:
        # (a) they may bump closesObserved which the propagation engine
        # reads, so they need to be applied before any propagate() call;
        # (b) they mutate nodes, so update_config must see the results to
        # persist them; (c) they live on the same cfg dict as everything
        # else for the rest of the pipeline.
        print("\nFetching OHLCV for derived indicators...", file=log)
        cfg = fetch_ohlcv_for_derived(cfg)
        print("\nComputing derived indicators...", file=log)
        cfg = compute_derived_indicators(cfg)
        if args.update_config:
            update_config_file(args.config, cfg)

    # Export state (runs at same point as --dry-run: after propagation, before HTML)
    if exporting:
        states = propagate(cfg)
        confluence = score_confluence(cfg, states)
        phase_num, phase_key = get_current_phase(cfg)

        # Evaluate all scenarios
        scenarios_result = []
        for scenario in cfg.get("scenarios", []):
            new_states, impact = eval_scenario(cfg, scenario, base_states=states)
            scenarios_result.append((scenario, new_states, impact))

        snapshot = export_state(cfg, states, confluence, phase_num, phase_key,
                                scenarios_result)
        snapshot_json = json.dumps(snapshot, indent=2, ensure_ascii=False)

        export_target = args.export_state
        if export_target == "-":
            # Write to stdout (clean — all other output went to stderr)
            sys.stdout.write(snapshot_json + "\n")
        else:
            export_path = os.path.abspath(export_target)
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            # WHY atomic rename: run-all.py rotates {book}-latest → {book}-prev
            # then calls this exporter. If the process dies mid-write (OOM,
            # SIGTERM, disk pressure), a naive write_text can leave a
            # zero-byte or truncated {book}-latest.json — the next cron pass
            # either crashes on json.loads or (worse) treats partial data as
            # canonical. Write to .tmp, fsync, rename — on a POSIX filesystem
            # the rename is atomic so readers see old-full or new-full, never
            # a torn file.
            tmp_path = export_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(snapshot_json)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, export_path)
            print(f"\n  Exported: {export_path} ({len(snapshot_json):,} bytes)", file=log)

        # If -o was not explicitly provided on the command line, stop here
        # (similar to --dry-run). If -o was provided, continue to generate HTML.
        if "--output" not in sys.argv and "-o" not in sys.argv:
            print(f"\n  --export-state: JSON exported.", file=log)
            return

    # Dry run exits here
    if args.dry_run:
        print("\n  --dry-run: no HTML generated.", file=log)
        return

    # Overwrite check
    output = os.path.abspath(args.output)
    if os.path.isfile(output) and not args.force:
        print(f"\n  Output exists: {output}", file=log)
        print(f"  Use --force to overwrite.", file=log)
        sys.exit(1)

    # Generate
    print(f"\nGenerating HTML...", file=log)
    html = generate_html(cfg)
    Path(output).write_text(html)
    print(f"  Written: {output} ({len(html):,} bytes)", file=log)

    # Validate
    if args.validate:
        print("\nValidating...", file=log)
        run_validate(output)

    # Screenshot
    if args.screenshot:
        print("\nScreenshotting...", file=log)
        run_screenshot(output, str(Path(output).parent))

    # Publish
    if args.publish:
        print("\nPublishing...", file=log)
        run_publish(output, cfg, args)

    print("\nDone.", file=log)


if __name__ == "__main__":
    main()
