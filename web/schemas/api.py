"""
v2 API schemas — request/response models for versioned REST endpoints.

WHY: Separate from web/models.py (v1 routes). These models define the
/api/v1/ surface and will eventually be the source for generated
TypeScript types via OpenAPI.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from web.schemas.events import AlertEvent, EventSeverity
from web.schemas.snapshots import ActiveOverride, SnapshotSummary


# ── Bootstrap ───────────────────────────────────────────────────────────

class ThesisCatalogEntry(BaseModel):
    """Lightweight thesis summary for the dashboard sidebar."""
    thesisId: str
    title: str
    definitionHash: Optional[str] = None
    nodeCount: int = 0
    edgeCount: int = 0


class AlertSummary(BaseModel):
    """Aggregated alert counts by severity for the bootstrap response."""
    critical: int = 0
    warning: int = 0
    info: int = 0
    total: int = 0


class SystemStatus(BaseModel):
    """Runtime status for the bootstrap response."""
    uptime_seconds: float = 0.0
    scheduler_running: bool = False
    theses_loaded: int = 0


class BootstrapResponse(BaseModel):
    """GET /api/v1/bootstrap — everything the client needs for first render.

    WHY: A single request that returns the complete initial state makes
    first render deterministic and cheap. The client does not need to
    orchestrate multiple REST calls before it can display anything.
    """
    theses: List[ThesisCatalogEntry]
    snapshots: Dict[str, Any]  # thesisId → ThesisSnapshot dict
    activeOverrides: Dict[str, List[ActiveOverride]]  # thesisId → overrides
    alertSummary: AlertSummary
    system: SystemStatus


# ── Overrides ───────────────────────────────────────────────────────────

class OverrideCreateRequest(BaseModel):
    """POST /api/v1/overrides — create a manual override."""
    thesisId: str
    targetType: str = Field(pattern=r"^(node|marketField|instrument)$")
    targetId: str
    field: str
    value: Any
    reason: str = ""
    expiresInMinutes: Optional[int] = Field(default=None, ge=1, le=10080)


class OverrideResponse(BaseModel):
    """Response after creating or clearing an override."""
    overrideId: str
    thesisId: str
    targetType: str
    targetId: str
    field: str
    value: Any
    actor: Optional[str] = None
    reason: str = ""
    status: str
    createdAt: str
    expiresAt: Optional[str] = None
    clearedAt: Optional[str] = None


# ── Scenarios ───────────────────────────────────────────────────────────

class ScenarioEvalResponse(BaseModel):
    """POST /api/v1/theses/{id}/scenarios/{sid}/evaluate response.

    WHY: Scenario evaluation is read-only and revision-bound. The response
    includes the baseRevision so the client knows which snapshot the
    scenario was evaluated against.
    """
    baseRevision: Optional[int] = None
    scenarioId: str
    label: str
    probability: float
    changedNodes: Dict[str, Dict[str, str]]  # nodeId → {old, new}
    portfolioImpact: Dict[str, Any]
    explanation: str = ""


# ── Alerts ──────────────────────────────────────────────────────────────

class AlertListResponse(BaseModel):
    """GET /api/v1/alerts — paginated alert timeline."""
    events: List[AlertEvent]
    total: int
    hasMore: bool = False


# ── Health ──────────────────────────────────────────────────────────────

class LiveResponse(BaseModel):
    """GET /api/v1/health/live — process is up."""
    status: str = "ok"
    uptime_seconds: float = 0.0


class ReadyResponse(BaseModel):
    """GET /api/v1/health/ready — system is operational.

    WHY: Readiness means: DB writable, coordinator initialized, at least
    one successful tick completed. 503 if not ready.
    """
    status: str  # "ready" | "not_ready"
    db_writable: bool = False
    coordinator_initialized: bool = False
    first_tick_completed: bool = False
    detail: str = ""
