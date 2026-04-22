"""
v1 scenario evaluation — read-only, revision-bound.

WHY: Scenario evaluation asks "what would happen if scenario X fired?" against
a specific committed snapshot. The answer must never leak into live state:
this route acquires no coordinator lock and performs no writes. It reads a
committed snapshot (immutable) and computes a hypothetical result.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from web.auth import get_current_user
from web.runtime.coordinator import ScenarioEvaluationError
from web.schemas.api import ScenarioEvalResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1", "scenarios"])


@router.post("/theses/{thesis_id}/scenarios/{scenario_id}/evaluate",
             response_model=ScenarioEvalResponse)
async def evaluate_scenario(
    request: Request,
    thesis_id: str,
    scenario_id: str,
    against_revision: Optional[int] = Query(
        default=None, ge=1,
        description="Committed revision to evaluate against (defaults to latest).",
    ),
    _user=Depends(get_current_user),
) -> dict:
    """Evaluate a scenario against a committed revision — read-only.

    Returns the base revision used, the nodes whose states change, and the
    per-instrument portfolio impact. Idempotent: same inputs → same output.
    """
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="coordinator_not_ready")

    try:
        # evaluate_scenario is pure-CPU (deterministic engine + deep-copy).
        # Run in thread pool so a slow propagate() can't stall the event loop.
        result = await asyncio.to_thread(
            coordinator.evaluate_scenario,
            thesis_id, scenario_id, against_revision,
        )
    except ScenarioEvaluationError as e:
        raise HTTPException(status_code=404, detail=e.reason)

    return result
