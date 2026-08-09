"""
v1 agent-in-room endpoints — surface LLM activity to the analysts.

WHY: The trading-desk LLM (via @claude / @gpt / @gemini / @compare in
chat) is the third analyst in the room, but its state is invisible to
the humans. This router exposes:

  - GET /api/v1/agent/log   — last N LLM calls (model, prompt summary,
    latency, status, the snapshot revision the agent was reasoning
    against at call time). Read from the in-process ring buffer in
    web.routes.llm (`_AGENT_CALL_LOG`).

  - GET /api/v1/agent/state — small "what's the agent up to" digest:
    current snapshot revision for a named thesis, the default model
    constant, and a summary of the last call.

  - POST /api/v1/agent/ping — cheap heartbeat for the frontend to
    detect server liveness without a WebSocket round-trip.

JWT-gated except by design: log/state include the prompt-first-80 and
last-call metadata that we don't want public. Ping returns nothing
sensitive but follows the same router convention so a single auth gate
covers all three.
"""

import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from web.auth import get_current_user
from web.routes.llm import DEFAULT_MODEL, get_agent_log
from web.runtime.coordinator import get_latest_revision

router = APIRouter(
    prefix="/api/v1/agent",
    tags=["v1", "agent"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/log")
async def list_agent_log(
    room_id: Optional[str] = Query(None, description="Filter to a single room"),
    limit: int = Query(20, ge=1, le=50, description="Max rows (default 20, max 50)"),
) -> dict:
    """Return recent LLM calls newest-first.

    WHY structured envelope (not bare list): the frontend renders a
    "last updated" timestamp from the response itself, and may grow
    additional metadata (e.g. total_count) without breaking the shape.
    """
    rows = get_agent_log(room_id=room_id, limit=limit)
    return {
        "rows": rows,
        "count": len(rows),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/state")
async def get_agent_state(
    thesis_id: Optional[str] = Query(
        None, description="Thesis to report revision for"
    ),
) -> dict:
    """Return what the agent is reasoning against right now.

    `snapshot_revision` is None when the coordinator has not yet
    committed a snapshot for the named thesis (or no thesis_id was
    given). The frontend renders that as "n/a" rather than 0 so users
    can tell the difference between "fresh boot" and "revision zero".
    """
    revision = get_latest_revision(thesis_id) if thesis_id else None
    last_row: Optional[dict] = None
    rows = get_agent_log(room_id=None, limit=1)
    if rows:
        last_row = rows[0]
    return {
        "thesis_id": thesis_id,
        "snapshot_revision": revision,
        "default_model": DEFAULT_MODEL,
        "last_call_ts": (last_row or {}).get("ts"),
        "last_call_status": (last_row or {}).get("status"),
        "last_call_model": (last_row or {}).get("model"),
    }


@router.post("/ping")
async def agent_ping() -> dict:
    """Return a cheap liveness echo.

    WHY exposed under JWT: keeps the surface uniform with the rest of
    /api/v1/agent. The body is intentionally minimal (timestamp + ok)
    so the frontend can use it as a sub-50ms server-alive probe.
    """
    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "monotonic_ms": round(time.monotonic() * 1000.0, 1),
    }
