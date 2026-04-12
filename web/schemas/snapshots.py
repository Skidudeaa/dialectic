"""
v2 snapshot schema — canonical output of the RuntimeCoordinator.

WHY: The snapshot is the single unit of truth that flows from the engine
through persistence, WebSocket broadcast, Dialectic push, and the bootstrap
API. Every consumer reads this shape. Defining it as Pydantic models
ensures validation at write boundaries and enables OpenAPI type generation.

The schema mirrors export_state() output from thesisgraph.py with v2
additions: thesisId, revision, definitionHash, quality metadata, watermarks,
and activeOverrides.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Node state enum ─────────────────────────────────────────────────────

class NodeStateValue(str, Enum):
    """Possible node evaluation states from eval_node_state."""
    fired = "fired"
    approaching = "approaching"
    stable = "stable"
    gated = "gated"
    constrained = "constrained"
    monitoring = "monitoring"
    resolved = "resolved"
    active = "active"
    partial = "partial"


# ── Snapshot quality ────────────────────────────────────────────────────

class QualityStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    stale = "stale"
    error = "error"


class SnapshotQuality(BaseModel):
    """Data freshness and health metadata for a thesis snapshot.

    WHY: A live trading desk without freshness metadata is unreliable.
    Every snapshot carries quality state so clients can display stale/degraded
    indicators and operators know whether to trust the data.
    """
    status: QualityStatus = QualityStatus.healthy
    last_success_at: Optional[str] = None
    last_attempt_at: Optional[str] = None
    stale: bool = False
    issues: List[str] = Field(default_factory=list)


class Watermarks(BaseModel):
    """Timestamps of last successful data fetch per provider."""
    prices: Optional[str] = None
    polymarket: Optional[str] = None


# ── Snapshot sub-structures ─────────────────────────────────────────────

class CascadePhase(BaseModel):
    number: int
    key: str
    status: str  # "STARTING" | "ACTIVE" | "APPROACHING" | "UNKNOWN" etc.


class Countdown(BaseModel):
    nodeId: str
    label: str
    deadline: str
    daysRemaining: int = Field(ge=0)


class ScenarioImpact(BaseModel):
    probability: float = Field(ge=0.0, le=1.0)
    netImpact: float


class PortfolioSummary(BaseModel):
    monthlyBudget: int = 0
    topPositions: List[str] = Field(default_factory=list)
    sgovAvailable: int = 0


class HorizonEntry(BaseModel):
    """Forward propagation result at a specific time horizon."""
    states: Dict[str, str]
    confluence: Dict[str, float]


class TVIndicatorReading(BaseModel):
    """Derived technical indicator values for a single node."""
    rsi14: Optional[float] = None
    atr14: Optional[float] = None
    sma50: Optional[float] = None
    source: Optional[str] = None
    computedAt: Optional[str] = None


class NodeSummary(BaseModel):
    """Aggregate node counts by state for the snapshot summary."""
    fired: int = 0
    approaching: int = 0
    stable: int = 0
    gated: int = 0
    constrained: int = 0
    monitoring: int = 0


class SnapshotSummary(BaseModel):
    """Quick-glance summary for dashboard cards and bootstrap."""
    nodeCounts: NodeSummary
    phase: str
    topCountdowns: List[Countdown] = Field(default_factory=list)


# ── Override record (referenced by snapshot) ────────────────────────────

class OverrideStatus(str, Enum):
    active = "active"
    expired = "expired"
    cleared = "cleared"


class ActiveOverride(BaseModel):
    """An override currently in effect, as surfaced in the snapshot."""
    overrideId: str
    targetType: str  # "node" | "marketField" | "instrument"
    targetId: str
    field: str
    value: Any
    actor: Optional[str] = None
    reason: str = ""
    createdAt: str
    expiresAt: Optional[str] = None


# ── Main snapshot model ─────────────────────────────────────────────────

class ThesisSnapshot(BaseModel):
    """Canonical snapshot — the single unit of truth for one thesis at one point in time.

    WHY: Every downstream consumer (WS broadcast, bootstrap API, Dialectic push,
    diff engine, frontend render) reads this shape. Defining it once with
    validation prevents drift and catches corruption at write boundaries.
    """
    # Schema version — currently 2 (from export_state), will bump to 3
    # when v2 runtime additions (thesisId, revision, quality) are live.
    v: int = 2

    # v2 runtime additions (optional until coordinator is wired)
    thesisId: Optional[str] = None
    revision: Optional[int] = None
    definitionHash: Optional[str] = None

    # Timestamps
    timestamp: str
    generatedAt: Optional[str] = None

    # Quality and freshness (v2 addition)
    quality: SnapshotQuality = Field(default_factory=SnapshotQuality)
    watermarks: Watermarks = Field(default_factory=Watermarks)

    # Core thesis data (matches existing export_state output)
    title: str = ""
    nodeStates: Dict[str, str] = Field(default_factory=dict)
    confluenceScores: Dict[str, float] = Field(default_factory=dict)
    cascadePhase: CascadePhase = Field(
        default_factory=lambda: CascadePhase(number=0, key="unknown", status="UNKNOWN")
    )
    countdowns: List[Countdown] = Field(default_factory=list)
    marketSnapshot: Dict[str, float] = Field(default_factory=dict)
    scenarioImpacts: Dict[str, ScenarioImpact] = Field(default_factory=dict)
    portfolioSummary: PortfolioSummary = Field(default_factory=PortfolioSummary)
    horizonTrace: Dict[str, HorizonEntry] = Field(default_factory=dict)

    # Derived technical indicators (v:2 addition, non-causal overlay)
    tvIndicators: Dict[str, TVIndicatorReading] = Field(default_factory=dict)

    # Summary for dashboard cards (v2 addition — computed from nodeStates)
    summary: Optional[SnapshotSummary] = None

    # Active overrides at snapshot time (v2 addition)
    activeOverrides: List[ActiveOverride] = Field(default_factory=list)


def snapshot_from_export(export: dict, thesis_id: Optional[str] = None) -> ThesisSnapshot:
    """Adapt export_state() output to ThesisSnapshot model.

    WHY: export_state() returns a plain dict with camelCase keys. This
    bridge function validates the output and adds v2 fields (thesisId,
    quality, watermarks) so the rest of the system works with typed models.
    """
    return ThesisSnapshot(
        v=export.get("v", 2),
        thesisId=thesis_id,
        timestamp=export.get("timestamp", ""),
        title=export.get("title", ""),
        nodeStates=export.get("nodeStates", {}),
        confluenceScores=export.get("confluenceScores", {}),
        cascadePhase=CascadePhase(**export["cascadePhase"]) if "cascadePhase" in export else CascadePhase(number=0, key="unknown", status="UNKNOWN"),
        countdowns=[Countdown(**c) for c in export.get("countdowns", [])],
        marketSnapshot=export.get("marketSnapshot", {}),
        scenarioImpacts={
            k: ScenarioImpact(**v) for k, v in export.get("scenarioImpacts", {}).items()
        },
        portfolioSummary=PortfolioSummary(**export["portfolioSummary"]) if "portfolioSummary" in export else PortfolioSummary(),
        horizonTrace={
            k: HorizonEntry(**v) for k, v in export.get("horizonTrace", {}).items()
        },
        tvIndicators={
            k: TVIndicatorReading(**v) for k, v in export.get("tvIndicators", {}).items()
        },
    )
