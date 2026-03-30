# api/trading.py — Trading snapshot utilities (importable without full app)

"""
ARCHITECTURE: Standalone formatting and response models for the trading snapshot endpoint.
WHY: Keeps format_thesis_summary testable without importing the full FastAPI app.
TRADEOFF: Extra file vs monolithic main.py — worth it for test isolation.
"""

from uuid import UUID
from pydantic import BaseModel

from models import TradingSnapshotRequest


class TradingSnapshotResponse(BaseModel):
    """Response from storing a trading snapshot."""
    stored_at: str
    memory_id: UUID


def format_thesis_summary(snapshot: TradingSnapshotRequest) -> str:
    """
    Format a TradingSnapshotRequest into a human-readable memory summary.

    ARCHITECTURE: Produces a compact text block for the thesis_state_current memory.
    WHY: LLM context and memory search need a readable summary, not raw JSON.
    TRADEOFF: Fixed format vs template — fixed is simpler and sufficient for single-book.
    """
    lines = [f"Thesis Graph State ({snapshot.timestamp})"]

    # Cascade phase
    if snapshot.cascadePhase:
        phase = snapshot.cascadePhase
        phase_num = phase.get("number", "?")
        phase_key = phase.get("key", "unknown")
        phase_status = phase.get("status", "unknown")
        lines.append(f"Phase: {phase_num} — {phase_key} ({phase_status})")

    # Active nodes (fired and approaching)
    fired = [k for k, v in snapshot.nodeStates.items() if v == "fired"]
    approaching = [k for k, v in snapshot.nodeStates.items() if v == "approaching"]
    if fired or approaching:
        parts = []
        if fired:
            parts.append(f"Fired: {', '.join(fired)}")
        if approaching:
            parts.append(f"Approaching: {', '.join(approaching)}")
        lines.append(f"Active: {'; '.join(parts)}")
    else:
        lines.append("Active: No active signals")

    # Confluence scores
    if snapshot.confluenceScores:
        score_parts = [f"{k}: {v:.2f}" for k, v in snapshot.confluenceScores.items()]
        lines.append(f"Confluence: {', '.join(score_parts)}")

    # Countdowns
    if snapshot.countdowns:
        countdown_parts = []
        for cd in snapshot.countdowns:
            node_id = cd.get("nodeId", "unknown")
            days = cd.get("daysRemaining", "?")
            deadline = cd.get("deadline", "")
            countdown_parts.append(f"{node_id}: {days}d remaining ({deadline})")
        lines.append(f"Countdowns: {'; '.join(countdown_parts)}")

    return "\n".join(lines)
