"""Health check endpoints — no auth required.

- `/api/health`                    legacy combined health (kept stable)
- `/api/v1/health/live`            liveness probe — always 200 once running
- `/api/v1/health/ready`           readiness probe — 200 when DB + coordinator + first tick done

WHY the split (v2 Unit 14): liveness answers "is the process up?" and drives
orchestrator restarts. Readiness answers "can the process serve requests?"
and drives load-balancer traffic. Collapsing them makes rolling deploys
chatty with false-positive restarts while the coordinator is still hydrating.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from web.main import get_uptime
from web.models import HealthResponse
from web.ws import manager

router = APIRouter(tags=["health"])

_ROOT = Path(__file__).resolve().parent.parent.parent


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    books_dir = _ROOT / "books"
    snapshots_dir = _ROOT / "snapshots"

    books: list[str] = []
    if books_dir.exists():
        books = [p.stem for p in sorted(books_dir.glob("*-graph.json"))]

    last_snapshots: dict[str, str] = {}
    if snapshots_dir.exists():
        for p in snapshots_dir.glob("*-latest.json"):
            bid = p.stem.replace("-latest", "")
            stat = p.stat()
            from datetime import datetime, timezone
            last_snapshots[bid] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    import os
    llm_available = bool(os.environ.get("OPENROUTER_API_KEY", ""))

    return HealthResponse(
        uptime_seconds=round(get_uptime(), 1),
        ws_connections=manager.total_connections,
        books_loaded=books,
        last_snapshots=last_snapshots,
        llm_available=llm_available,
    )


@router.get("/api/v1/health/live")
async def live() -> dict:
    """Liveness probe — 200 as soon as the ASGI app is serving requests.

    WHY never 503 here: a 503 on liveness triggers orchestrator restarts.
    Anything transient (DB contention, coordinator hydration) belongs on
    /ready, not here.
    """
    return {"status": "alive", "uptime_seconds": round(get_uptime(), 1)}


@router.get("/api/v1/health/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — 200 iff DB writable + coordinator + first tick done.

    Any missing dependency returns 503 with a `detail` dict the operator can
    inspect to decide whether to wait, page, or roll back.
    """
    detail: dict[str, object] = {
        "db_writable": False,
        "coordinator_initialized": False,
        "first_tick_done": False,
    }

    # DB writable — cheap round-trip; any exception is a fatal for readiness.
    repo = getattr(request.app.state, "repo", None)
    if repo is not None:
        try:
            repo.ping()
            detail["db_writable"] = True
        except Exception as e:  # noqa: BLE001 — surface whatever broke
            detail["db_error"] = str(e)

    # Coordinator presence + first-tick flag.
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        detail["coordinator_initialized"] = True
        detail["first_tick_done"] = bool(getattr(coordinator, "is_ready", False))

    ok = all((
        detail["db_writable"],
        detail["coordinator_initialized"],
        detail["first_tick_done"],
    ))
    status = 200 if ok else 503
    return JSONResponse(
        status_code=status,
        content={"status": "ready" if ok else "not_ready", "detail": detail},
    )


@router.get("/api/ws/protocol")
async def ws_protocol() -> dict:
    """Machine-readable WebSocket protocol documentation for agent clients."""
    return {
        "url_pattern": "/ws/{room_id}",
        "auth": {
            "method": "query_param_or_first_message",
            "query_param": "token",
            "first_message": "raw JWT string",
            "description": "Pass JWT via ?token= query param (recommended for agents) or send raw token as first WS text frame",
        },
        "send_types": {
            "message": {"type": "message", "content": "string"},
            "typing": {"type": "typing", "typing": True},
            "viewing": {"type": "viewing", "viewing": "thesis-id"},
        },
        "receive_types": {
            "message": "New chat message",
            "llm_chunk": "Streaming LLM token",
            "llm_done": "LLM response complete",
            "system": "System notification",
            "presence": "User presence update",
            "typing": "User typing indicator",
            "error": "Error notification",
        },
    }
