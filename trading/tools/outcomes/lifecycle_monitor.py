"""
Predicate Lifecycle Monitor — Synthesis Layer for tradingDesk.

Architecture: REPAIR → TAG → CAPTURE.
  Layer 0 (REPAIR): amplification wired into score_confluence(),
    propagate_at_horizon() consuming edge.lag. Ships in thesisgraph.py.
  Layer 1 (TAG): Dynamic provenance reads actual DAG edges. INERT tags
    block target emission until the propagator consumes them.
  Layer 2 (CAPTURE): Polymorphic predicates, cross-trade LedgerAnalyzer,
    multi-failure attribution, weighted consistency.

Wires into run-all.py as Step 7.
Zero external dependencies — stdlib only per project convention.
"""

import fcntl
import json
import hashlib
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Union, Tuple, Any

# WHY package-relative: this file moved from /root/tradingDesk to the monorepo's
# trading/ prefix, and the old absolute default silently survived the move —
# __init__ mkdir(parents=True)s its ledger dir, so a CLI run would have
# recreated /root/tradingDesk/outcomes/trades and written trades to a path
# nothing reads. Derive it the way web/adapters/outcomes.py already does.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_DIR = str(_REPO_ROOT / "outcomes" / "trades")


# =============================================================================
# Layer 1: PROVENANCE
# =============================================================================

@dataclass
class ProvenanceTag:
    """WHAT: Epistemic weight of a single input to a computed metric."""
    variable: str
    value: float
    unvalidated_assumption: str
    confidence_level: str  # "INERT" | "UNVERIFIED" | "VALIDATED"


@dataclass
class TargetRefusal:
    """WHAT: Blocking refusal when INERT inputs contaminate a target.

    WHY: Provenance that documents without blocking is autopsy. INERT inputs
    (decorative DAG fields the propagator never reads) must halt target emission
    until the fields are wired into the math.
    """
    reason: str
    contaminants: List[str]
    fix_required: str


@dataclass
class DynamicTarget:
    """WHAT: Computed exit target with full provenance of its inputs."""
    baseline_ref: float
    prob_weighted_net_impact: float
    computed_target: float
    provenance: List[ProvenanceTag]


# =============================================================================
# Layer 2: POLYMORPHIC PREDICATES
# =============================================================================

@dataclass
class Predicate:
    """WHAT: A falsifiable condition required for the trade thesis to remain valid.

    WHY: Single class with kind discriminator rather than a class hierarchy,
    because dataclasses.asdict() handles flat structures cleanly for JSONL
    serialization without external dependencies.

    Kinds:
      "state"     — nodeStates[node_id] == expected
      "state_set" — nodeStates[node_id] in allowed
      "threshold" — snapshot.get_path(path) <op> value
      "countdown" — countdowns[node_id].daysRemaining <op> days
    """
    kind: str
    # State / StateSet / Countdown fields
    node_id: str = ""
    expected: str = ""
    allowed: List[str] = field(default_factory=list)
    # Threshold fields
    path: str = ""
    op: str = ""
    value: float = 0.0
    # Countdown fields
    days: int = 0
    # Common
    load_bearing: bool = True


@dataclass
class EvaluatedPredicate:
    """WHAT: A predicate with its evaluation result against a snapshot."""
    predicate: Predicate
    actual: Any = None  # str | float | int
    is_flipped: bool = False
    note: str = ""  # "NODE_MISSING", "PATH_MISSING", "COUNTDOWN_MISSING"


# =============================================================================
# Layer 3: TRADE LIFECYCLE
# =============================================================================

@dataclass
class PostExitVerdict:
    """WHAT: Calibration capital generated on trade exit or degradation."""
    trade_id: str
    exit_timestamp: str
    predicate_consistency: float
    load_bearing_flipped: List[str]
    supporting_flipped: List[str]
    realized_vs_predicted: str
    recommended_weight_adjustments: Dict[str, float]
    adjustment_provenance: str  # "EMPIRICAL" | "UNVERIFIED_INSUFFICIENT_SAMPLES"


@dataclass
class TradeRecord:
    """WHAT: JSONL ledger entry for a trade lifecycle event."""
    trade_id: str
    ticker: str
    event_type: str  # "ENTRY" | "EVALUATION" | "DEGRADED" | "EXIT"
    snapshot_hash: str
    evaluated_predicates: List[EvaluatedPredicate]
    run_id: str
    timestamp: str = ""
    dynamic_target: Optional[DynamicTarget] = None
    target_refusal: Optional[TargetRefusal] = None
    verdict: Optional[PostExitVerdict] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def _serialize_record(record: TradeRecord) -> str:
    """WHAT: Convert a TradeRecord to a JSON string for JSONL storage."""
    d = asdict(record)
    # WHY: asdict converts everything including None fields. Strip None-valued
    # optional fields to keep JSONL lines compact.
    if d.get("dynamic_target") is None:
        del d["dynamic_target"]
    if d.get("target_refusal") is None:
        del d["target_refusal"]
    if d.get("verdict") is None:
        del d["verdict"]
    return json.dumps(d, separators=(",", ":"))


def _deserialize_record(line: str) -> Optional[TradeRecord]:
    """WHAT: Reconstruct a TradeRecord from a JSONL line."""
    try:
        d = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    preds = [
        EvaluatedPredicate(
            predicate=Predicate(**ep["predicate"]),
            actual=ep.get("actual"),
            is_flipped=ep.get("is_flipped", False),
            note=ep.get("note", ""),
        )
        for ep in d.get("evaluated_predicates", [])
    ]
    prov_target = None
    if "dynamic_target" in d:
        dt = d["dynamic_target"]
        prov_target = DynamicTarget(
            baseline_ref=dt["baseline_ref"],
            prob_weighted_net_impact=dt["prob_weighted_net_impact"],
            computed_target=dt["computed_target"],
            provenance=[ProvenanceTag(**t) for t in dt.get("provenance", [])],
        )
    refusal = None
    if "target_refusal" in d:
        tr = d["target_refusal"]
        refusal = TargetRefusal(**tr)
    verdict = None
    if "verdict" in d:
        v = d["verdict"]
        verdict = PostExitVerdict(**v)
    return TradeRecord(
        trade_id=d["trade_id"],
        ticker=d["ticker"],
        event_type=d["event_type"],
        snapshot_hash=d["snapshot_hash"],
        evaluated_predicates=preds,
        run_id=d["run_id"],
        timestamp=d.get("timestamp", ""),
        dynamic_target=prov_target,
        target_refusal=refusal,
        verdict=verdict,
    )


# =============================================================================
# SNAPSHOT READER (flat nodeStates format from export_state())
# =============================================================================

class SnapshotTooStaleError(ValueError):
    """Raised when a snapshot's timestamp is older than the caller's max_age.

    Callers can catch this explicitly to degrade gracefully (skip evaluation,
    mark trades stale, warn operator) instead of evaluating predicates on
    days-old data after a cron/pipeline failure."""
    pass


class Snapshot:
    """WHY: Hard-fail at the contract boundary. If someone writes a Cytoscape
    book JSON to this path, we know immediately — not silently evaluate empty."""

    REQUIRED_KEYS = {"nodeStates", "confluenceScores", "cascadePhase",
                     "countdowns", "marketSnapshot"}

    def __init__(self, data: dict, path: Optional[Path] = None):
        missing = self.REQUIRED_KEYS - set(data.keys())
        if missing:
            raise ValueError(
                f"Snapshot{f' at {path}' if path else ''} missing required keys: "
                f"{missing}. Expected export_state() output, not a book config."
            )
        self._data = data
        self.node_states: Dict[str, str] = data["nodeStates"]
        self.confluence_scores: Dict[str, float] = data["confluenceScores"]
        self.cascade_phase: dict = data["cascadePhase"]
        self.countdowns: List[dict] = data["countdowns"]
        self.market_snapshot: Dict[str, float] = data["marketSnapshot"]
        self.scenario_impacts: Dict[str, dict] = data.get("scenarioImpacts", {})
        self.portfolio_summary: dict = data.get("portfolioSummary", {})
        self.horizon_trace: Dict[str, dict] = data.get("horizonTrace", {})
        self.v: int = data.get("v", 1)
        self.timestamp: str = data.get("timestamp", "")
        self.title: str = data.get("title", "")

    def age_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds since snapshot.timestamp. None if timestamp is absent or
        unparseable — callers should treat that as "unknown age"."""
        if not self.timestamp:
            return None
        try:
            # export_state writes "YYYY-MM-DDTHH:MM:SSZ" (UTC, Z-suffix).
            # fromisoformat handles the Z since Python 3.11.
            ts = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        if now is None:
            now = datetime.now(timezone.utc)
        return (now - ts).total_seconds()

    @classmethod
    def load(cls, path: Path, max_age_seconds: Optional[float] = None) -> "Snapshot":
        """Load a snapshot file.

        If ``max_age_seconds`` is set, raises :class:`SnapshotTooStaleError`
        when the snapshot's timestamp is older than that. A missing or
        unparseable timestamp is NOT treated as stale — the caller should
        decide how to handle unknown-age snapshots separately.
        """
        if not path.exists():
            raise FileNotFoundError(f"Snapshot missing: {path}")
        data = json.loads(path.read_text())
        snap = cls(data, path)
        if max_age_seconds is not None:
            age = snap.age_seconds()
            if age is not None and age > max_age_seconds:
                raise SnapshotTooStaleError(
                    f"Snapshot at {path} is {age:.0f}s old "
                    f"(max {max_age_seconds:.0f}s). Refusing to evaluate "
                    f"predicates on stale data — investigate upstream "
                    f"fetch/export pipeline."
                )
        return snap

    def content_hash(self) -> str:
        """WHAT: Deterministic hash of snapshot content for dedup and attribution."""
        canonical = json.dumps(self._data, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def get_path(self, dotted_path: str) -> Optional[Any]:
        """WHAT: Walk a dotted path like 'scenarioImpacts.closed-may.netImpact'."""
        current: Any = self._data
        for part in dotted_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def get_countdown_days(self, node_id: str) -> Optional[int]:
        """WHAT: Return daysRemaining for a deadline node."""
        for c in self.countdowns:
            if c.get("nodeId") == node_id:
                return c.get("daysRemaining")
        return None


# =============================================================================
# PREDICATE EVALUATOR
# =============================================================================

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def evaluate_predicate(pred: Predicate, snapshot: Snapshot) -> EvaluatedPredicate:
    """WHAT: Evaluate a single predicate against snapshot state.

    WHY: Hard-fail (is_flipped=True, note="..._MISSING") when referenced
    nodes/paths are absent — per doctrine, structural absence is
    thesis-invalidating, not silently ignored.
    """
    if pred.kind == "state":
        if pred.node_id not in snapshot.node_states:
            return EvaluatedPredicate(pred, actual="", is_flipped=True, note="NODE_MISSING")
        actual = snapshot.node_states[pred.node_id]
        return EvaluatedPredicate(pred, actual=actual, is_flipped=(actual != pred.expected))

    if pred.kind == "state_set":
        if pred.node_id not in snapshot.node_states:
            return EvaluatedPredicate(pred, actual="", is_flipped=True, note="NODE_MISSING")
        actual = snapshot.node_states[pred.node_id]
        return EvaluatedPredicate(pred, actual=actual, is_flipped=(actual not in pred.allowed))

    if pred.kind == "threshold":
        val = snapshot.get_path(pred.path)
        if val is None:
            return EvaluatedPredicate(pred, actual=0, is_flipped=True, note="PATH_MISSING")
        if not isinstance(val, (int, float)):
            return EvaluatedPredicate(pred, actual=0, is_flipped=True, note="PATH_NON_NUMERIC")
        if pred.op not in _OPS:
            return EvaluatedPredicate(pred, actual=val, is_flipped=True, note=f"UNKNOWN_OP:{pred.op}")
        held = _OPS[pred.op](val, pred.value)
        return EvaluatedPredicate(pred, actual=float(val), is_flipped=(not held))

    if pred.kind == "countdown":
        days = snapshot.get_countdown_days(pred.node_id)
        if days is None:
            return EvaluatedPredicate(pred, actual=0, is_flipped=True, note="COUNTDOWN_MISSING")
        if pred.op not in _OPS:
            return EvaluatedPredicate(pred, actual=days, is_flipped=True, note=f"UNKNOWN_OP:{pred.op}")
        held = _OPS[pred.op](days, pred.days)
        return EvaluatedPredicate(pred, actual=days, is_flipped=(not held))

    return EvaluatedPredicate(pred, actual=None, is_flipped=True, note=f"UNKNOWN_KIND:{pred.kind}")


# =============================================================================
# DAG READER (for dynamic INERT-tag detection)
# =============================================================================

def detect_inert_fields(book_path: Path) -> List[ProvenanceTag]:
    """WHAT: Read actual book-JSON edges and detect decorative fields.

    WHY: amplification and lag are declared on edges but may not be consumed
    by the propagator yet. Until REPAIR ships completely, any target that
    depends on propagation inherits these as silent lies.
    """
    data = json.loads(book_path.read_text())
    edges = data.get("edges", [])
    tags = []

    for edge in edges:
        edge_id = f"{edge.get('from', '?')}->{edge.get('to', '?')}"
        # WHY: amplification IS now wired into score_confluence() as of Layer 0.
        # Only flag as INERT if the propagator does NOT read it — i.e., if the
        # node has fan-in < 2 (confluence scoring skips it) AND the edge is the
        # sole incoming edge to a non-indicator node.
        # For now: amplification IS consumed (Layer 0 shipped). Do not tag INERT.

        # Lag: still not consumed by propagate() for standard propagation.
        # propagate_at_horizon() uses it, but the default run-all.py path does not.
        lag_val = edge.get("lag")
        if lag_val and lag_val.lower() != "immediate":
            tags.append(ProvenanceTag(
                variable=f"edge:{edge_id}:lag",
                value=0.0,
                unvalidated_assumption=(
                    f"Declared lag '{lag_val}' only consumed by propagate_at_horizon(). "
                    "Standard propagate() treats all edges as instantaneous."
                ),
                confidence_level="UNVERIFIED",  # UNVERIFIED (not INERT) because horizon propagator exists
            ))
    return tags


# =============================================================================
# PROVENANCE TARGET COMPUTER
# =============================================================================

def compute_provenance_target(
    ref_price: float,
    scenario_impacts: Dict[str, Dict[str, float]],
    book_path: Optional[Path] = None,
) -> Union[DynamicTarget, TargetRefusal]:
    """WHAT: Compute Bravo's dynamic target with full provenance of inputs.

    Returns TargetRefusal if any input is INERT. Since Layer 0 wired
    amplification, INERT tags only appear if new decorative fields are added
    without propagator support.
    """
    provenance: List[ProvenanceTag] = []

    # Dynamic: inspect the actual DAG for inert fields
    if book_path and book_path.exists():
        provenance.extend(detect_inert_fields(book_path))

    # Static: magic numbers embedded in the propagator
    provenance.append(ProvenanceTag(
        variable="eval_scenario_multiplier",
        value=20.0,
        unvalidated_assumption="thesisgraph.py hardcoded 20% max cascade ceiling.",
        confidence_level="UNVERIFIED",
    ))
    provenance.append(ProvenanceTag(
        variable="state_multiplier_approaching",
        value=0.4,
        unvalidated_assumption="thesisgraph.py state multiplier for 'approaching'. Arbitrary constant.",
        confidence_level="UNVERIFIED",
    ))

    # INERT = blocking gate
    inert = [p for p in provenance if p.confidence_level == "INERT"]
    if inert:
        return TargetRefusal(
            reason=f"{len(inert)} INERT inputs contaminate this target",
            contaminants=[p.variable for p in inert],
            fix_required="Wire INERT fields into propagator before target can be trusted.",
        )

    # Compute probability-weighted expected impact
    total_impact = 0.0
    for sid, impact in scenario_impacts.items():
        prob = impact.get("probability", 0)
        net = impact.get("netImpact", 0)
        total_impact += prob * net

    target = ref_price * (1 + total_impact / 100)
    return DynamicTarget(
        baseline_ref=ref_price,
        prob_weighted_net_impact=round(total_impact, 4),
        computed_target=round(target, 2),
        provenance=provenance,
    )


# =============================================================================
# CROSS-TRADE LEDGER ANALYZER
# =============================================================================

class LedgerAnalyzer:
    """WHAT: Reads ALL trade ledgers to compute empirical node reliability.

    WHY: A node's flip rate is a cross-trade signal, not per-trade. em-stress
    participates in XOP and SPY-short; its penalty aggregates across both.
    """
    MIN_SAMPLES = 10

    def __init__(self, ledger_dir: Path):
        self.ledger_dir = ledger_dir

    def _iter_records(self):
        if not self.ledger_dir.exists():
            return
        for f in sorted(self.ledger_dir.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                rec = _deserialize_record(line)
                if rec:
                    yield rec

    def node_flip_rate(self, node_id: str) -> Tuple[float, int]:
        """WHAT: Fraction of evaluations where node flipped, across all trades."""
        total = 0
        flips = 0
        for record in self._iter_records():
            if record.event_type not in ("EVALUATION", "DEGRADED", "EXIT"):
                continue
            for ep in record.evaluated_predicates:
                pred = ep.predicate
                if pred.node_id != node_id:
                    continue
                if not pred.load_bearing:
                    continue
                total += 1
                if ep.is_flipped:
                    flips += 1
                break  # count each record once per node
        return (flips / total, total) if total else (0.0, 0)

    def empirical_weight_adjustment(self, node_id: str) -> Tuple[float, str]:
        """WHAT: Cross-trade empirical weight adjustment for a node.

        Returns (adjustment, provenance_string).
        """
        flip_rate, samples = self.node_flip_rate(node_id)
        if samples < self.MIN_SAMPLES:
            return (-0.25, f"UNVERIFIED_INSUFFICIENT_SAMPLES: n={samples}<{self.MIN_SAMPLES}")
        # WHY: Penalty scales with flip rate, capped at -0.5
        return (round(-min(flip_rate, 0.5), 3), "EMPIRICAL")


# =============================================================================
# PREDICATE LIFECYCLE MONITOR (the orchestrator)
# =============================================================================

class PredicateLifecycleMonitor:
    """WHAT: The synthesis layer. Evaluates predicates, tags provenance, captures outcomes."""

    def __init__(self, ledger_dir: str = DEFAULT_LEDGER_DIR):
        self.ledger_dir = Path(ledger_dir)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.analyzer = LedgerAnalyzer(self.ledger_dir)

    def _compute_run_id(self, trade_id: str, snapshot_hash: str,
                        predicates: List[Predicate]) -> str:
        """WHAT: Content-based dedup hash. No wall-clock."""
        pred_sig = json.dumps(
            sorted(json.dumps(asdict(p), sort_keys=True) for p in predicates),
            sort_keys=True,
        )
        raw = f"{trade_id}|{snapshot_hash}|{pred_sig}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _find_existing(self, trade_id: str, run_id: str) -> Optional[TradeRecord]:
        """WHAT: Check if this run_id already exists in the trade's ledger."""
        ledger_file = self.ledger_dir / f"{trade_id}.jsonl"
        if not ledger_file.exists():
            return None
        for line in ledger_file.read_text().splitlines():
            if not line.strip():
                continue
            rec = _deserialize_record(line)
            if rec and rec.run_id == run_id:
                return rec
        return None

    def _log(self, record: TradeRecord) -> None:
        """WHAT: Append trade lifecycle event to JSONL ledger.

        WHY flock: O_APPEND is only per-write atomic up to PIPE_BUF (4096
        bytes) on Linux. A TradeRecord with many predicates + provenance
        tags can exceed that, and two concurrent writers (cron + manual
        seed, two cron runs overlapping) can interleave mid-record and
        corrupt the JSONL. A subsequent _iter_records parse drops the
        broken lines silently, destroying the empirical-adjustment sample
        base. Match the lock convention used by web/state.py."""
        ledger_file = self.ledger_dir / f"{record.trade_id}.jsonl"
        line = _serialize_record(record) + "\n"
        with ledger_file.open("a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _weighted_consistency(self, evaluated: List[EvaluatedPredicate],
                              snapshot: Snapshot) -> float:
        """WHAT: Predicate consistency weighted by load_bearing × confluence score."""
        def weight(ep: EvaluatedPredicate) -> float:
            pred = ep.predicate
            base = 2.0 if pred.load_bearing else 1.0
            if pred.node_id:
                conf = snapshot.confluence_scores.get(pred.node_id, 1.0)
                return base * max(conf, 0.5)
            return base
        total_w = sum(weight(ep) for ep in evaluated)
        held_w = sum(weight(ep) for ep in evaluated if not ep.is_flipped)
        return round((held_w / total_w) * 100.0, 1) if total_w > 0 else 0.0

    def run_evaluation_cycle(
        self,
        trade_id: str,
        ticker: str,
        predicates: List[Predicate],
        snapshot_path: Path,
        ref_price: Optional[float] = None,
        book_path: Optional[Path] = None,
    ) -> Tuple[str, TradeRecord]:
        """WHAT: Main entry point for step 7 of run-all.py.

        Returns (status, record). status ∈ {EVALUATION, DEGRADED, EXIT, DUPLICATE}.
        """
        snapshot = Snapshot.load(snapshot_path)
        snapshot_hash = snapshot.content_hash()
        evaluated = [evaluate_predicate(p, snapshot) for p in predicates]

        # Idempotency — content-based, no timestamps
        run_id = self._compute_run_id(trade_id, snapshot_hash, predicates)
        existing = self._find_existing(trade_id, run_id)
        if existing:
            return ("DUPLICATE", existing)

        # Classification
        load_bearing_flipped = [ep for ep in evaluated if ep.is_flipped and ep.predicate.load_bearing]
        supporting_flipped = [ep for ep in evaluated if ep.is_flipped and not ep.predicate.load_bearing]
        if load_bearing_flipped:
            event_type = "EXIT"
        elif supporting_flipped:
            event_type = "DEGRADED"
        else:
            event_type = "EVALUATION"

        # Provenance target (or refusal)
        dynamic_target = None
        target_refusal = None
        if ref_price is not None and snapshot.scenario_impacts:
            result = compute_provenance_target(
                ref_price, snapshot.scenario_impacts, book_path,
            )
            if isinstance(result, TargetRefusal):
                target_refusal = result
            else:
                dynamic_target = result

        # Verdict on EXIT or DEGRADED
        verdict = None
        if event_type in ("EXIT", "DEGRADED"):
            def _node_id(ep: EvaluatedPredicate) -> str:
                p = ep.predicate
                return p.node_id or p.path

            failed_lb = [_node_id(ep) for ep in load_bearing_flipped]
            failed_sp = [_node_id(ep) for ep in supporting_flipped]

            # Multi-failure attribution: iterate over ALL flipped load-bearing
            adjustments: Dict[str, float] = {}
            provenances: set = set()
            for node_id in failed_lb:
                adj, prov = self.analyzer.empirical_weight_adjustment(node_id)
                adjustments[node_id] = adj
                provenances.add(prov)
            if event_type == "DEGRADED":
                for node_id in failed_sp:
                    adjustments[node_id] = -0.10
                provenances.add("UNVERIFIED_INSUFFICIENT_SAMPLES: DEGRADED placeholder")

            adj_prov = "EMPIRICAL" if provenances == {"EMPIRICAL"} else "UNVERIFIED_INSUFFICIENT_SAMPLES"

            verdict = PostExitVerdict(
                trade_id=trade_id,
                exit_timestamp=datetime.now(timezone.utc).isoformat(),
                predicate_consistency=self._weighted_consistency(evaluated, snapshot),
                load_bearing_flipped=failed_lb,
                supporting_flipped=failed_sp,
                realized_vs_predicted=(
                    "THESIS_INVALIDATED_PRE_TARGET" if event_type == "EXIT"
                    else "THESIS_DEGRADED"
                ),
                recommended_weight_adjustments=adjustments,
                adjustment_provenance=adj_prov,
            )

        record = TradeRecord(
            trade_id=trade_id,
            ticker=ticker,
            event_type=event_type,
            snapshot_hash=snapshot_hash,
            evaluated_predicates=evaluated,
            run_id=run_id,
            dynamic_target=dynamic_target,
            target_refusal=target_refusal,
            verdict=verdict,
        )
        self._log(record)
        return (event_type, record)


# =============================================================================
# TRADE GATE DEFINITIONS — the three trades
# =============================================================================

# WHY: Every predicate maps to a specific entry from Alpha's Part 4 exit
# architecture, verified against live snapshots. kind discriminator allows
# the evaluator to check state, numeric thresholds, countdown days, and
# set membership — the four classes needed for full exit-gate expression.

XOP_GATE = [
    Predicate(kind="state", node_id="em-stress", expected="fired", load_bearing=True),
    Predicate(kind="threshold", path="confluenceScores.em-stress", op=">=", value=1.60, load_bearing=True),
    Predicate(kind="state_set", node_id="brent", allowed=["approaching", "fired"], load_bearing=True),
    Predicate(kind="countdown", node_id="planting-miss", op="<=", days=14, load_bearing=False),
]

CF_GATE = [
    Predicate(kind="state", node_id="planting-miss", expected="approaching", load_bearing=True),
    Predicate(kind="countdown", node_id="planting-miss", op="<=", days=12, load_bearing=True),
    Predicate(kind="threshold", path="scenarioImpacts.closed-may.netImpact", op=">=", value=5.0, load_bearing=True),
]

SPY_SHORT_GATE = [
    Predicate(kind="threshold", path="confluenceScores.earnings-compression", op=">=", value=2.00, load_bearing=True),
    Predicate(kind="threshold", path="confluenceScores.consumer-confidence", op=">=", value=1.80, load_bearing=True),
    Predicate(kind="threshold", path="confluenceScores.recession-risk", op=">=", value=1.20, load_bearing=True),
    Predicate(kind="state_set", node_id="fed-response", allowed=["monitoring", "stable"], load_bearing=True),
]


# =============================================================================
# RUN-ALL.PY INTEGRATION (Step 7)
# =============================================================================

# WHY 24h: the cron runs Mon/Wed/Fri — a clean weekly cadence is ≤72h between
# runs, but a 24h ceiling catches the common failure mode of "Monday's run
# failed silently and Wednesday's pipeline skipped steps 1-6, so step 7 would
# evaluate against 48-hour-old data as if it were fresh." Callers who know
# they're running an off-cadence manual evaluation can pass their own ceiling.
MAX_SNAPSHOT_AGE_SECONDS = 24 * 60 * 60


def step7_evaluate_open_trades(
    snapshot_path: Path,
    open_trades_path: Path,
    book_id: str = "",
    book_path: Optional[Path] = None,
    ledger_dir: str = DEFAULT_LEDGER_DIR,
    max_snapshot_age_seconds: Optional[float] = MAX_SNAPSHOT_AGE_SECONDS,
) -> Dict[str, str]:
    """WHAT: Evaluate open trades for a specific book against its fresh snapshot.

    WHY: Each book has its own snapshot. SPY-short predicates reference tariffs
    nodes; evaluating them against the iran snapshot produces NODE_MISSING on
    every predicate. The book_id filter ensures each trade only evaluates against
    its own book's output.

    If ``max_snapshot_age_seconds`` is set (default 24h) and the snapshot is
    older than that, every matching trade returns status 'SKIPPED_STALE' and
    NO ledger writes happen. WHY: evaluating EXIT predicates against stale
    data can fire a phantom EXIT record, polluting empirical adjustments with
    wins-recorded-as-losses. Refusing to evaluate is safer than evaluating on
    data we can't trust. Pass ``None`` to disable the check (testing / manual).

    open_trades_path is a JSON file: [
      {"trade_id": "...", "ticker": "...", "predicates": [...], "ref_price": ..., "book": "..."},
      ...
    ]

    Returns {trade_id: status} for trades belonging to this book_id.
    """
    if not open_trades_path.exists():
        return {}
    all_trades = json.loads(open_trades_path.read_text())
    # WHY: Filter to trades belonging to THIS book. If no book_id provided,
    # evaluate all trades (backward-compatible for single-book testing).
    trades = [t for t in all_trades if not book_id or t.get("book", "") == book_id]
    if not trades:
        return {}

    # Staleness gate — load-and-check once up front, so a stale snapshot skips
    # evaluation across every trade for this book rather than surfacing the
    # same error three times.
    try:
        Snapshot.load(snapshot_path, max_age_seconds=max_snapshot_age_seconds)
    except SnapshotTooStaleError as e:
        import sys as _sys
        print(f"  [lifecycle] SKIPPED (stale snapshot): {e}", file=_sys.stderr)
        return {t["trade_id"]: "SKIPPED_STALE" for t in trades}

    monitor = PredicateLifecycleMonitor(ledger_dir=ledger_dir)
    results = {}
    for trade in trades:
        preds = [Predicate(**p) for p in trade["predicates"]]
        status, record = monitor.run_evaluation_cycle(
            trade_id=trade["trade_id"],
            ticker=trade["ticker"],
            predicates=preds,
            snapshot_path=snapshot_path,
            ref_price=trade.get("ref_price"),
            book_path=book_path,
        )
        results[trade["trade_id"]] = status
        if status in ("EXIT", "DEGRADED"):
            print(
                f"  [lifecycle] {trade['trade_id']}: {status} — "
                f"{record.verdict.load_bearing_flipped if record.verdict else '?'}",
                file=__import__("sys").stderr,
            )
    return results
