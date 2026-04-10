"""Health check endpoint — no auth required."""

from pathlib import Path

from fastapi import APIRouter

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
