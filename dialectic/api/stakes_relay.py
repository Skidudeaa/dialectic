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
# Idempotency keys crossing the seam (td dedups on source_key). Amended
# 2026-08-22 — every key now carries the FORECASTER, because the ledger holds
# one row per (commitment, forecaster) rather than one per commitment:
#   stake:{commitment_id}:{user_id}:created
#   stake:{commitment_id}:{user_id}:confidence:{seq}
#   stake:{commitment_id}:{user_id}:resolved
#
# Mapping: source_type='dialectic_commitment', source_ref=str(commitment id),
# source_label=THE FORECASTER'S display name (td's own model calls this "the
# leaderboard grouping key", so it must be one person), claim + resolution
# criteria → statement, deadline → deadline, category → tag, and the question's
# proposer → a `proposed_by:<name>` tag.
#
# WHY THE FORECASTER AND NOT THE CREATOR (owner ruling, 2026-08-22: a claim
# should be "labeled both human and who proposes"): source_label used to come
# from the commitment's creator. For an ordinary commitment the creator IS the
# forecaster and it looked correct. A Sunday Round question is drafted by
# nobody — `created_by_user_id=None`, which the label helper maps to the
# literal "LLM" — so both humans' round forecasts would have collapsed onto one
# desk row attributed to the machine, and `self_model.fetch_track_record` reads
# that ledger back into the participant's own prompt. See
# docs/reviews/2026-08-21_round-forecast-attribution.md.
#
# Resolution FANS OUT: the manager resolves once per human who forecast, each
# with that person's own last confidence. Resolving a single row would leave
# every other forecaster's claim open forever.
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


def actor_token(user_id) -> str:
    """The forecaster's half of an idempotency key.

    `unattributed` rather than a bare empty segment, so a key never collapses
    to `stake:<id>::created` and silently collides with a differently-shaped
    one. Nothing relays a NULL forecaster today — the house writes directly,
    bypassing this module entirely — but a key shape must not depend on that
    staying true.
    """
    return str(user_id) if user_id else "unattributed"


def create_body(
    commitment: dict,
    *,
    source_label: str,
    confidence: Optional[float],
    forecaster_id=None,
    proposer_label: Optional[str] = None,
) -> Optional[dict]:
    """The td PredictionCreate body for a commitment, or None when the
    commitment is not ledger-mappable (no deadline / no stated confidence).

    ONE ROW PER (COMMITMENT, FORECASTER), and the owner's ruling is the
    reason: a claim should be "labeled both human and who proposes", and a
    question may be answered by one or more humans.

    The defect this replaces: `source_key` was `stake:<id>:created`, one row
    per COMMITMENT, and `source_label` was derived from the commitment's
    CREATOR. For an ordinary commitment the creator IS the forecaster, so it
    looked right for a year. A Sunday Round question is drafted by nobody
    (`question_round.py` creates it `created_by_user_id=None`), which
    `_relay_source_label` maps to the literal "LLM" — so both humans' round
    forecasts would have landed on ONE desk row labelled as the machine's,
    and the participant reads that ledger back as its own track record.

    Note it could not have been fixed at the confidence relay alone: the row
    is created on first contact and td REPLAYS a claimed source_key rather
    than updating it, so the label is settled by whoever gets there first.
    The forecaster has to be in the KEY, not just the label.

    `source_label` stays the forecaster alone because td's own model calls it
    "the leaderboard grouping key" — folding the proposer in would split one
    person across as many rows as there are proposers. The proposer rides a
    tag, which is queryable and grouping-neutral.
    """
    deadline = _deadline_str(commitment)
    if not deadline or confidence is None:
        return None
    commitment_id = str(commitment.get("id"))
    tags = ["dialectic", str(commitment.get("category") or "prediction")]
    if proposer_label:
        tags.append(f"proposed_by:{proposer_label}")
    return {
        "statement": _statement(commitment),
        "confidence": float(confidence),
        "deadline": deadline,
        "tags": tags,
        "source_type": "dialectic_commitment",
        "source_label": source_label,
        "source_ref": commitment_id,
        "source_key": f"stake:{commitment_id}:{actor_token(forecaster_id)}:created",
    }


async def _ensure_ledger_row(
    commitment: dict, *, source_label: str, confidence: Optional[float],
    forecaster_id=None, proposer_label: Optional[str] = None,
) -> Optional[dict]:
    """POST the create; td replays the existing row when the source_key is
    already claimed. Returns the td prediction row, or None if unmappable."""
    body = create_body(
        commitment, source_label=source_label, confidence=confidence,
        forecaster_id=forecaster_id, proposer_label=proposer_label,
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
    forecaster_id=None, proposer_label: Optional[str] = None,
) -> None:
    try:
        await _ensure_ledger_row(
            commitment, source_label=source_label, confidence=confidence,
            forecaster_id=forecaster_id, proposer_label=proposer_label,
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
    forecaster_id=None,
    proposer_label: Optional[str] = None,
) -> None:
    try:
        row = await _ensure_ledger_row(
            commitment, source_label=source_label, confidence=confidence,
            forecaster_id=forecaster_id, proposer_label=proposer_label,
        )
        if not row or not row.get("id"):
            return
        commitment_id = str(commitment.get("id"))
        await td.post(
            f"/api/predictions/{row['id']}/confidence",
            json_body={
                "confidence": float(confidence),
                "reasoning": reasoning,
                "source_key": (
                    f"stake:{commitment_id}:{actor_token(forecaster_id)}"
                    f":confidence:{seq}"
                ),
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
    forecaster_id=None,
    proposer_label: Optional[str] = None,
) -> None:
    """Resolve ONE forecaster's row.

    Since a commitment now has a desk row per forecaster, the caller fans this
    out — once per human who actually forecast, each with that person's OWN
    last confidence. Resolving only the row this relay happened to find would
    leave every other forecaster's claim open forever, which reads on the
    leaderboard as "never answered" rather than as right or wrong.
    """
    try:
        row = await _ensure_ledger_row(
            commitment, source_label=source_label, confidence=last_confidence,
            forecaster_id=forecaster_id, proposer_label=proposer_label,
        )
        if not row or not row.get("id"):
            return
        commitment_id = str(commitment.get("id"))
        await td.post(
            f"/api/predictions/{row['id']}/resolve",
            json_body={
                "resolution": resolution,
                "resolution_notes": resolution_notes,
                "source_key": (
                    f"stake:{commitment_id}:{actor_token(forecaster_id)}"
                    ":resolved"
                ),
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
    forecaster_id=None, proposer_label: Optional[str] = None,
) -> Optional[asyncio.Task]:
    return _schedule(
        _run_created(
            commitment, source_label=source_label, confidence=confidence,
            forecaster_id=forecaster_id, proposer_label=proposer_label,
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
    forecaster_id=None,
    proposer_label: Optional[str] = None,
) -> Optional[asyncio.Task]:
    return _schedule(
        _run_confidence(
            commitment,
            source_label=source_label,
            seq=seq,
            confidence=confidence,
            reasoning=reasoning,
            forecaster_id=forecaster_id,
            proposer_label=proposer_label,
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
    forecaster_id=None,
    proposer_label: Optional[str] = None,
) -> Optional[asyncio.Task]:
    return _schedule(
        _run_resolved(
            commitment,
            forecaster_id=forecaster_id,
            proposer_label=proposer_label,
            source_label=source_label,
            resolution=resolution,
            resolution_notes=resolution_notes,
            last_confidence=last_confidence,
        ),
        "resolved",
    )
