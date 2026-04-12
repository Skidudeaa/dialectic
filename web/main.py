"""
FastAPI application for the tradingDesk web layer.

WHY: Wraps the existing CLI tools (thesisgraph, polymarket, lifecycle_monitor,
morning_brief, cross_book) as REST endpoints + WebSocket for real-time chat.
All domain logic lives in tools/ — this layer handles HTTP, auth, and routing.
"""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    global _start_time
    _start_time = time.time()
    log.info("tradingDesk web starting — root: %s", _ROOT)

    # WHY: Initialize SQLite persistence. Repository is stored on app.state
    # so routes can access it via request.app.state.repo.
    from web.persistence.repository import Repository
    from web.persistence.connection import DEFAULT_DB_PATH
    repo = Repository(DEFAULT_DB_PATH)
    applied = repo.initialize()
    if applied:
        log.info("Applied %d database migration(s)", applied)
    app.state.repo = repo
    log.info("SQLite persistence initialized: %s", DEFAULT_DB_PATH)

    # WHY: Give the WS manager access to the repo so broadcast_to_book_rooms
    # can query rooms without importing web.state.
    from web.ws import manager
    manager.set_repo(repo)

    yield
    log.info("tradingDesk web shutting down")


app = FastAPI(
    title="tradingDesk",
    description="Collaborative macro trading analysis workspace",
    version="0.1.0",
    lifespan=lifespan,
)

# WHY: Frontend dev server runs on localhost:5173 (Vite default).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_uptime() -> float:
    return time.time() - _start_time


# ── Route registration ───────────────────────────────────────────────────

from web.routes import auth, health, thesis, market, outcomes, rooms, messages, llm, journal, predictions, tradingview

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(thesis.router)
app.include_router(market.router)
app.include_router(outcomes.router)
app.include_router(rooms.router)
app.include_router(messages.router)
app.include_router(llm.router)
app.include_router(journal.router)
app.include_router(predictions.router)
# WHY three routers: webhook is HMAC-gated (no JWT), management is
# JWT-gated under /api/tradingview, binding CRUD lives under /api/thesis.
for tv_router in tradingview.routers:
    app.include_router(tv_router)

# ── Static frontend serving ─────────────────────────────────────────────
# WHY: Serve the production build directly from FastAPI so there's no need
# for a separate Vite dev server or nginx in front. Single process = simple.
_DIST = _ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="static")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve the SPA — try the exact file, fall back to index.html for client routing."""
        file = _DIST / path
        if file.exists() and file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(_DIST / "index.html"))
