"""
Command registry — one source of truth for operator + LLM commands.

WHY: The Ctrl+K command palette must be a real runtime surface — humans pick
commands, LLMs introspect them via `/api/v1/commands`. A single registry with
typed handlers means the same command is callable from both.

Each :class:`Command` carries:

* an ``id`` (e.g. ``"thesis.open"``)
* a JSON-Schema ``input_schema`` (derived from a Pydantic model where practical)
* a coroutine ``handler`` that accepts the validated input dict

The router in ``web/routes/v1/commands.py`` exposes the registry via:

* ``GET /api/v1/commands`` — list every command + its schema
* ``POST /api/v1/commands/{command_id}`` — dispatch with validated args
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


# ─── Types ───────────────────────────────────────────────────────────────

# WHY: We store JSON-Schema as a plain dict (the output of
# BaseModel.model_json_schema). The ``Command`` dataclass is deliberately
# small — the router is the only code that deserialises handlers.
Handler = Callable[[Dict[str, Any]], Awaitable[Any]]


@dataclass
class Command:
    """A registered operator/LLM command.

    Attributes:
        id: Stable identifier used in URLs (e.g. ``"thesis.open"``).
        title: Human-readable short label shown in the palette.
        description: One-line docstring the LLM can surface.
        category: Loose bucket (``"thesis" | "market" | "outcomes" | "ui"``).
        input_schema: JSON-Schema ``dict`` for handler arguments.
        output_schema: Optional JSON-Schema describing the handler's return.
        handler: Coroutine that receives validated kwargs as a single dict.
    """

    id: str
    title: str
    description: str
    category: str
    input_schema: Dict[str, Any]
    handler: Handler
    output_schema: Optional[Dict[str, Any]] = None
    tags: List[str] = field(default_factory=list)


# ─── Registry ────────────────────────────────────────────────────────────

# Module-level registry. Populated by ``register`` below; seeded at
# import-time by the section further down.
COMMANDS: Dict[str, Command] = {}


def register(cmd: Command) -> Command:
    """Register a command. Raises ``ValueError`` on duplicate id.

    WHY raise on duplicate: a duplicate registration is almost always a bug
    (two modules fighting for the same id) rather than legitimate override.
    Fail loud at import-time.
    """
    if cmd.id in COMMANDS:
        raise ValueError(f"Duplicate command registration: {cmd.id}")
    COMMANDS[cmd.id] = cmd
    return cmd


def list_commands() -> List[Dict[str, Any]]:
    """Return a JSON-serialisable catalog of every registered command."""
    return [
        {
            "id": c.id,
            "title": c.title,
            "description": c.description,
            "category": c.category,
            "input_schema": c.input_schema,
            "output_schema": c.output_schema,
            "tags": c.tags,
        }
        for c in COMMANDS.values()
    ]


def get(command_id: str) -> Optional[Command]:
    """Lookup helper — returns ``None`` on unknown id."""
    return COMMANDS.get(command_id)


def clear() -> None:
    """Drop every registration — test helper only."""
    COMMANDS.clear()


# ─── Helpers to derive JSON-Schema from Pydantic models ──────────────────

def schema_from(model: type[BaseModel]) -> Dict[str, Any]:
    """Normalise model_json_schema output.

    Pydantic emits a ``title`` field that we strip because it pollutes the
    palette UI. Everything else (``properties``, ``required``, ``$defs``) is
    kept verbatim.
    """
    raw = model.model_json_schema()
    raw.pop("title", None)
    return raw


# ─── Seeded commands ─────────────────────────────────────────────────────

# WHY this layout: seed commands live in the same module as the registry so
# ``import web.runtime.command_registry`` is the only thing the router needs
# to populate ``COMMANDS``. No circular import risk — we import the adapters
# lazily inside the handlers.


class BookIdInput(BaseModel):
    """Input carrying a single book id."""

    book_id: str = Field(..., description="Thesis book slug (e.g. iran-hormuz-graph)")


class EmptyInput(BaseModel):
    """Input accepting no arguments."""

    pass


class FocusPanelInput(BaseModel):
    """Input for the UI panel-focus nudge."""

    panel_name: Literal[
        "thesis", "predictions", "journal", "crossbook",
        "brief", "tradingview",
    ] = Field(..., description="Panel id to focus on the client")
    room_id: Optional[str] = Field(
        default=None,
        description="Optional room id — when set, broadcast is scoped to that room",
    )


# ── Handlers ─────────────────────────────────────────────────────────────

async def _thesis_open(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return the current evaluated snapshot for a book."""
    from web.adapters import thesis as thesis_adapter

    book_id = args["book_id"]
    # WHY to_thread: get_state is a stdlib-heavy pure-CPU call.
    return await asyncio.to_thread(thesis_adapter.get_state, book_id)


async def _thesis_diff_last_hour(args: Dict[str, Any]) -> Dict[str, Any]:
    """Diff the two most recent snapshots on disk for a book.

    We compare ``snapshots/{book}-latest.json`` against
    ``snapshots/{book}-prev.json`` when the prev file exists; otherwise the
    latest snapshot is compared with itself (diff is empty). The window is
    "last hour" only in operational spirit — snapshots are rotated by
    ``run-all.py`` which typically runs hourly or faster during the trading
    day.
    """
    from web.adapters import thesis as thesis_adapter
    from tools.bridge import diff_snapshots  # type: ignore[import-untyped]

    book_id = args["book_id"]
    # Reuse the adapter's own path validation + discovery.
    thesis_adapter._validate_book_id(book_id)
    latest_path = thesis_adapter.SNAPSHOTS_DIR / f"{book_id}-latest.json"
    prev_path = thesis_adapter.SNAPSHOTS_DIR / f"{book_id}-prev.json"

    if not latest_path.exists():
        # Fall back to a live export so the command still returns something
        # meaningful when the outbox rotation hasn't run yet.
        snapshot = await asyncio.to_thread(thesis_adapter.get_state, book_id)
        return {
            "hasChanges": False,
            "reason": "no-prior-snapshot",
            "latest": snapshot,
        }

    def _load(p: Path) -> Dict[str, Any]:
        with open(p) as f:
            return json.load(f)

    latest = await asyncio.to_thread(_load, latest_path)
    prev = latest if not prev_path.exists() else await asyncio.to_thread(_load, prev_path)
    delta = await asyncio.to_thread(diff_snapshots.build_delta, prev, latest)
    return delta


async def _market_watchlist(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return the current marketSnapshot slice of a book."""
    from web.adapters import thesis as thesis_adapter

    book_id = args["book_id"]
    state = await asyncio.to_thread(thesis_adapter.get_state, book_id)
    return {
        "book_id": book_id,
        "marketSnapshot": state.get("marketSnapshot", {}),
        "feedFreshness": state.get("feedFreshness", {}),
    }


async def _outcomes_morning_brief(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return the morning brief as plain text for a single book."""
    from web.adapters import outcomes as outcomes_adapter

    book_id = args["book_id"]
    text = await asyncio.to_thread(outcomes_adapter.generate_brief, [book_id])
    return {"book_id": book_id, "brief": text}


async def _outcomes_open_trades(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return all open trades."""
    from web.adapters import outcomes as outcomes_adapter

    trades = await asyncio.to_thread(outcomes_adapter.list_open_trades)
    return {"count": len(trades), "trades": trades}


async def _ui_focus_panel(args: Dict[str, Any]) -> Dict[str, Any]:
    """Nudge the frontend to focus a panel.

    WHY WebSocket broadcast: commands dispatched by the LLM need a channel
    back to the UI. We lazily import the manager so this module stays
    import-safe for tests that don't boot the full app.
    """
    panel_name = args["panel_name"]
    room_id = args.get("room_id")
    payload = {
        "panel": panel_name,
        "requestedAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from web.ws import manager

        if room_id:
            await manager.broadcast(room_id, "focus_panel", payload, user="system")
        else:
            await manager.broadcast_all("focus_panel", payload, user="system")
    except Exception as exc:  # pragma: no cover — broadcast is best-effort
        log.warning("ui.focus_panel broadcast failed: %s", exc)
    return {"ok": True, "panel": panel_name, "roomId": room_id}


# ── Seeder ───────────────────────────────────────────────────────────────

def _seed_builtin_commands() -> None:
    """Register the canonical set of operator/LLM commands.

    Idempotent: clears the registry first so repeated imports during
    testing (``importlib.reload``) don't raise on duplicates.
    """
    COMMANDS.clear()

    register(Command(
        id="thesis.open",
        title="Open thesis",
        description="Return the current evaluated snapshot for a thesis book.",
        category="thesis",
        input_schema=schema_from(BookIdInput),
        output_schema=None,
        handler=_thesis_open,
        tags=["thesis", "read"],
    ))

    register(Command(
        id="thesis.diff.last_hour",
        title="Diff thesis (last hour)",
        description="Diff the two most recent snapshots for a thesis book.",
        category="thesis",
        input_schema=schema_from(BookIdInput),
        output_schema=None,
        handler=_thesis_diff_last_hour,
        tags=["thesis", "diff"],
    ))

    register(Command(
        id="market.watchlist",
        title="Market watchlist",
        description="Return the marketSnapshot slice of a thesis book.",
        category="market",
        input_schema=schema_from(BookIdInput),
        output_schema=None,
        handler=_market_watchlist,
        tags=["market", "read"],
    ))

    register(Command(
        id="outcomes.morning_brief",
        title="Morning brief",
        description="Generate the morning brief for a thesis book.",
        category="outcomes",
        input_schema=schema_from(BookIdInput),
        output_schema=None,
        handler=_outcomes_morning_brief,
        tags=["outcomes", "brief"],
    ))

    register(Command(
        id="outcomes.open_trades",
        title="Open trades",
        description="Return the list of open trades across every book.",
        category="outcomes",
        input_schema=schema_from(EmptyInput),
        output_schema=None,
        handler=_outcomes_open_trades,
        tags=["outcomes", "ledger"],
    ))

    register(Command(
        id="ui.focus_panel",
        title="Focus panel",
        description="Broadcast a UI nudge asking clients to focus a panel.",
        category="ui",
        input_schema=schema_from(FocusPanelInput),
        output_schema=None,
        handler=_ui_focus_panel,
        tags=["ui"],
    ))


# Seed on import so the router always sees a populated registry.
_seed_builtin_commands()
