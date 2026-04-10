"""Thesis graph routes — state, scenarios, horizon, price fetch + snapshot diff."""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.models import User, HorizonRequest
from web.adapters import thesis as thesis_adapter
from web.ws import manager
from web import state

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent

router = APIRouter(prefix="/api/thesis", tags=["thesis"], dependencies=[Depends(get_current_user)])


@router.get("/books")
async def list_books() -> list:
    return thesis_adapter.list_books()


@router.get("/{book_id}/state")
async def get_state(book_id: str) -> dict:
    try:
        return await asyncio.to_thread(thesis_adapter.get_state, book_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{book_id}/scenarios")
async def get_scenarios(book_id: str) -> list:
    try:
        return await asyncio.to_thread(thesis_adapter.get_scenarios, book_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{book_id}/horizon")
async def run_horizon(book_id: str, req: HorizonRequest) -> dict:
    try:
        return await asyncio.to_thread(thesis_adapter.run_horizon, book_id, req.horizon_days)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{book_id}/fetch-prices")
async def fetch_prices(book_id: str, user: User = Depends(get_current_user)) -> dict:
    """Fetch live prices, re-export snapshot, compute diff, broadcast changes."""
    try:
        prices = await asyncio.to_thread(thesis_adapter.fetch_prices_for_book, book_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Price fetch failed: {e}")

    # Snapshot diff: save previous, export new, compute delta
    try:
        snapshots_dir = _ROOT / "snapshots"
        prev_path = snapshots_dir / f"{book_id}-prev.json"
        latest_path = snapshots_dir / f"{book_id}-latest.json"

        # Rotate: current latest → prev
        old_snapshot = None
        if latest_path.exists():
            # WHY: Read file once to avoid TOCTOU between the two read_text() calls.
            raw = latest_path.read_text()
            old_snapshot = json.loads(raw)
            prev_path.write_text(raw)

        # Export fresh snapshot
        new_state = await asyncio.to_thread(thesis_adapter.export_snapshot, book_id)

        # Compute diff if we have a previous
        diff_summary = None
        if old_snapshot:
            diff_summary = _compute_diff_summary(old_snapshot, new_state)

        # Broadcast diff to all rooms linked to this book
        if diff_summary:
            rooms = state.list_rooms()
            for room in rooms:
                if room.get("linked_book_id") == book_id:
                    msg = state.save_message(
                        room_id=room["id"],
                        user="system",
                        content=diff_summary,
                        msg_type="system",
                    )
                    await manager.broadcast(room["id"], "message", msg, user="system")
    except Exception as e:
        log.warning("Snapshot diff failed: %s", e)

    return prices


def _compute_diff_summary(old: dict, new: dict) -> str | None:
    """Build a human-readable diff between two snapshots."""
    changes: list[str] = []

    # State transitions
    old_states = old.get("nodeStates", {})
    new_states = new.get("nodeStates", {})
    for node_id in set(old_states) | set(new_states):
        old_s = old_states.get(node_id, "?")
        new_s = new_states.get(node_id, "?")
        if old_s != new_s:
            changes.append(f"  {node_id}: {old_s} -> {new_s}")

    # Market price moves > 1%
    old_mkt = old.get("marketSnapshot", {})
    new_mkt = new.get("marketSnapshot", {})
    for sym in set(old_mkt) | set(new_mkt):
        old_p = old_mkt.get(sym)
        new_p = new_mkt.get(sym)
        if old_p and new_p and old_p != 0:
            pct = (new_p - old_p) / old_p * 100
            if abs(pct) >= 1.0:
                changes.append(f"  {sym}: {old_p:.2f} -> {new_p:.2f} ({pct:+.1f}%)")

    # Cascade phase change
    old_phase = old.get("cascadePhase", {}).get("number", 0)
    new_phase = new.get("cascadePhase", {}).get("number", 0)
    if old_phase != new_phase:
        changes.append(f"  CASCADE PHASE: {old_phase} -> {new_phase}")

    if not changes:
        return None

    return "SNAPSHOT UPDATE:\n" + "\n".join(changes)
