"""
Bootstrap endpoint — everything the client needs for first render.

WHY: A single request that returns the complete initial state makes first
render deterministic and cheap. The client does not need to orchestrate
multiple REST calls before it can display anything.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request

from web.auth import get_current_user
from web.deps import get_repo
from web.persistence.repository import Repository
from web.schemas.api import (
    AlertSummary,
    BootstrapResponse,
    SystemStatus,
    ThesisCatalogEntry,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.get("/bootstrap")
async def bootstrap(
    request: Request,
    _user=Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> dict:
    """Return everything the client needs for first render.

    WHY: The bootstrap response includes the thesis catalog, latest
    snapshots, active overrides, alert summary, and system status. A
    client that calls this endpoint once can render the full dashboard
    without any additional REST calls.
    """
    coordinator = getattr(request.app.state, "coordinator", None)

    # Build thesis catalog
    theses = []
    snapshots = {}
    active_overrides = {}

    if coordinator:
        for tid in coordinator.get_thesis_ids():
            defn = coordinator.definitions.get(tid, {})
            meta = defn.get("meta", {})
            theses.append(ThesisCatalogEntry(
                thesisId=tid,
                title=meta.get("title", tid),
                definitionHash=coordinator.definition_hashes.get(tid),
                nodeCount=len(defn.get("nodes", [])),
                edgeCount=len(defn.get("edges", [])),
            ).model_dump())

            # Latest snapshot
            snap = coordinator.get_latest_snapshot(tid)
            if snap:
                snapshots[tid] = snap

            # Active overrides per thesis
            overrides = await asyncio.to_thread(repo.list_active_overrides, tid)
            if overrides:
                active_overrides[tid] = overrides

    # Alert summary
    all_alerts = await asyncio.to_thread(repo.list_alert_events, limit=100)
    alert_counts = {"critical": 0, "warning": 0, "info": 0}
    for evt in all_alerts:
        sev = evt.get("severity", "info")
        if sev in alert_counts:
            alert_counts[sev] += 1

    # System status
    from web.main import get_uptime
    system = SystemStatus(
        uptime_seconds=get_uptime(),
        scheduler_running=coordinator.is_ready if coordinator else False,
        theses_loaded=len(theses),
    )

    return BootstrapResponse(
        theses=theses,
        snapshots=snapshots,
        activeOverrides=active_overrides,
        alertSummary=AlertSummary(
            **alert_counts,
            total=sum(alert_counts.values()),
        ),
        system=system,
    ).model_dump()
