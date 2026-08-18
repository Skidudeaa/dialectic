# api/stakes_relay.py — the mirror that carries dialectic's stakes into the
# desk's ONE claims ledger.
#
# ARCHITECTURE: dialectic's commitments keep their own tables and UX
# untouched; every lifecycle event (created / confidence restated / resolved)
# is additionally relayed to tradingDesk's predictions ledger so the
# calibration spine scores humans and LLM alike in one place. The hook fires
# from stakes/manager.py — the write layer BOTH doors share (stakes/routes.py
# REST and transport/handlers.py WebSocket converge there), so ledger
# coverage cannot be partial (plan merge decision 3).
#
# WHY fire-and-forget: a room write must never wait on, or fail with, the
# desk. Each relay is an asyncio task holding NO database connection — the
# manager captures every value it needs while it still holds one, and the
# task does HTTP only. A down desk degrades to a debug log.
#
# TRADEOFF — how the desk's prediction id is found without storing it:
# commitments have no metadata column, so persisting td's id would need a
# migration. Instead every relay event first POSTs the create body with
# source_key `stake:{commitment_id}:created`; tradingDesk's
# save_prediction_once is idempotent on source_key and RETURNS THE EXISTING
# ROW on replay (trading/web/routes/predictions.py — verified), so the
# source_key IS the durable lookup: stateless, restart-safe, no cache, no
# listing fallback. Cost: one extra loopback POST per confidence/resolve
# event, and when the ensure-create races the first confidence event the
# seeded history row can duplicate that confidence value — belief unchanged,
# accepted.
#
# Idempotency keys crossing the seam (td dedups on source_key):
#   stake:{commitment_id}:created
#   stake:{commitment_id}:confidence:{seq}
#   stake:{commitment_id}:resolved
#
# Mapping (plan Phase 3): source_type='dialectic_commitment',
# source_ref=str(commitment id), source_label=creator display name or "LLM"
# for a NULL user (the existing stakes convention), claim + resolution
# criteria → statement, deadline → deadline, category → tag.
#
# Deliberately NOT relayed: a commitment with no deadline or no stated
# confidence — tradingDesk's door requires both, and inventing either is the
# confidence-75.0 poison the plan exists to end. The backfill CLI
# (trading/tools/outcomes/import_dialectic_stakes.py) applies the same rule.

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from llm import tradingdesk_client as td

logger = logging.getLogger(__name__)

# Keep strong references: a bare create_task result can be garbage-collected
# mid-flight, silently cancelling the relay.
_tasks: set[asyncio.Task] = set()


def _schedule(coro, what: str) -> Optional[asyncio.Task]:
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        # No running loop (sync context) — the relay is best-effort chrome.
        coro.close()
        logger.debug("stakes relay %s skipped: no running event loop", what)
        return None
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


# ── mapping ──────────────────────────────────────────────────────────


def _statement(commitment: dict) -> str:
    claim = str(commitment.get("claim") or "").strip()
    criteria = str(commitment.get("resolution_criteria") or "").strip()
    if criteria:
        return f"{claim} — resolves when: {criteria}"
    return claim


def _deadline_str(commitment: dict) -> Optional[str]:
    deadline = commitment.get("deadline")
    if deadline is None:
        return None
    if isinstance(deadline, datetime):
        return deadline.date().isoformat()
    value = str(deadline).strip()
    return value or None


def create_body(
    commitment: dict, *, source_label: str, confidence: Optional[float],
) -> Optional[dict]:
    """The td PredictionCreate body for a commitment, or None when the
    commitment is not ledger-mappable (no deadline / no stated confidence)."""
    deadline = _deadline_str(commitment)
    if not deadline or confidence is None:
        return None
    commitment_id = str(commitment.get("id"))
    return {
        "statement": _statement(commitment),
        "confidence": float(confidence),
        "deadline": deadline,
        "tags": ["dialectic", str(commitment.get("category") or "prediction")],
        "source_type": "dialectic_commitment",
        "source_label": source_label,
        "source_ref": commitment_id,
        "source_key": f"stake:{commitment_id}:created",
    }


async def _ensure_ledger_row(
    commitment: dict, *, source_label: str, confidence: Optional[float],
) -> Optional[dict]:
    """POST the create; td replays the existing row when the source_key is
    already claimed. Returns the td prediction row, or None if unmappable."""
    body = create_body(
        commitment, source_label=source_label, confidence=confidence,
    )
    if body is None:
        logger.debug(
            "stakes relay: commitment %s is not ledger-mappable "
            "(deadline or confidence missing)",
            commitment.get("id"),
        )
        return None
    created = await td.post("/api/predictions", json_body=body)
    return created if isinstance(created, dict) else None


# ── the three lifecycle relays ───────────────────────────────────────


async def _run_created(
    commitment: dict, *, source_label: str, confidence: Optional[float],
) -> None:
    try:
        await _ensure_ledger_row(
            commitment, source_label=source_label, confidence=confidence,
        )
    except td.TradingDeskError as e:
        logger.debug("stakes relay (created) desk unavailable: %s", e)
    except Exception:
        logger.debug("stakes relay (created) failed", exc_info=True)


async def _run_confidence(
    commitment: dict,
    *,
    source_label: str,
    seq: int,
    confidence: float,
    reasoning: Optional[str],
) -> None:
    try:
        row = await _ensure_ledger_row(
            commitment, source_label=source_label, confidence=confidence,
        )
        if not row or not row.get("id"):
            return
        commitment_id = str(commitment.get("id"))
        await td.post(
            f"/api/predictions/{row['id']}/confidence",
            json_body={
                "confidence": float(confidence),
                "reasoning": reasoning,
                "source_key": f"stake:{commitment_id}:confidence:{seq}",
            },
        )
    except td.TradingDeskError as e:
        logger.debug("stakes relay (confidence) desk unavailable: %s", e)
    except Exception:
        logger.debug("stakes relay (confidence) failed", exc_info=True)


async def _run_resolved(
    commitment: dict,
    *,
    source_label: str,
    resolution: str,
    resolution_notes: Optional[str],
    last_confidence: Optional[float],
) -> None:
    try:
        row = await _ensure_ledger_row(
            commitment, source_label=source_label, confidence=last_confidence,
        )
        if not row or not row.get("id"):
            return
        commitment_id = str(commitment.get("id"))
        await td.post(
            f"/api/predictions/{row['id']}/resolve",
            json_body={
                "resolution": resolution,
                "resolution_notes": resolution_notes,
                "source_key": f"stake:{commitment_id}:resolved",
            },
        )
    except td.TradingDeskError as e:
        # A 409 lands here too: a human already resolved it on the desk —
        # the desk's resolution wins, ours stands down.
        logger.debug("stakes relay (resolved) desk refused/unavailable: %s", e)
    except Exception:
        logger.debug("stakes relay (resolved) failed", exc_info=True)


# ── public API (called by stakes/manager.py) ─────────────────────────


def relay_created(
    commitment: dict, *, source_label: str, confidence: Optional[float],
) -> Optional[asyncio.Task]:
    return _schedule(
        _run_created(
            commitment, source_label=source_label, confidence=confidence,
        ),
        "created",
    )


def relay_confidence(
    commitment: dict,
    *,
    source_label: str,
    seq: int,
    confidence: float,
    reasoning: Optional[str] = None,
) -> Optional[asyncio.Task]:
    return _schedule(
        _run_confidence(
            commitment,
            source_label=source_label,
            seq=seq,
            confidence=confidence,
            reasoning=reasoning,
        ),
        "confidence",
    )


def relay_resolved(
    commitment: dict,
    *,
    source_label: str,
    resolution: str,
    resolution_notes: Optional[str] = None,
    last_confidence: Optional[float] = None,
) -> Optional[asyncio.Task]:
    return _schedule(
        _run_resolved(
            commitment,
            source_label=source_label,
            resolution=resolution,
            resolution_notes=resolution_notes,
            last_confidence=last_confidence,
        ),
        "resolved",
    )
