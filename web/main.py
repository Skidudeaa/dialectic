"""
FastAPI application for the tradingDesk web layer.

WHY: Wraps the existing CLI tools (thesisgraph, polymarket, lifecycle_monitor,
morning_brief, cross_book) as REST endpoints + WebSocket for real-time chat.
All domain logic lives in tools/ — this layer handles HTTP, auth, and routing.
"""

import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# WHY: tools/ modules use relative imports and expect their parent on sys.path.
# This is the sanctioned approach per project conventions — no restructuring.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools" / "thesis-graph"))
sys.path.insert(0, str(_ROOT / "tools" / "data-fetch"))
sys.path.insert(0, str(_ROOT / "tools" / "outcomes"))
sys.path.insert(0, str(_ROOT / "tools" / "bridge"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    global _start_time
    _start_time = time.time()
    log.info("tradingDesk web starting — root: %s", _ROOT)
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
# WHY: Imports here (not top-level) to ensure sys.path is configured first.

from web.routes import auth, health, thesis, market, outcomes, rooms, messages, llm, journal, predictions  # noqa: E402

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
