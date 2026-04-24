"""
v1 audit-log read endpoint.

WHY: The audit_log table records every destructive action (trade kill,
scenario apply, builder delete). The UI needs a single read API to
surface "what changed and who did it" so operators can review history
without opening the SQLite file. JWT-required because the rows include
actor names and reasons that aren't public.
"""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from web.auth import get_current_user
from web.deps import get_repo
from web.persistence.repository import Repository

router = APIRouter(prefix="/api/v1/audit", tags=["v1", "audit"])


@router.get("")
async def list_audit(
    since: Optional[str] = Query(None, description="ISO8601 lower bound on ts"),
    actor: Optional[str] = Query(None, description="Filter by actor username"),
    action: Optional[str] = Query(None, description="Filter by action key, e.g. trade.kill"),
    limit: int = Query(100, ge=1, le=1000),
    user=Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> List[dict]:
    """Return audit rows newest-first.

    WHY query params not body: GET keeps the route bookmarkable and
    plays nicely with HTTP caches if we ever add them. Limit is capped
    at 1000 so a misclick in the UI can't pull the entire table.
    """
    rows = await asyncio.to_thread(
        repo.list_audit,
        since_iso=since,
        actor=actor,
        action=action,
        limit=limit,
    )
    return rows
