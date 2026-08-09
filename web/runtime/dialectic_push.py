"""
Inline Dialectic push — event-driven snapshot delivery from the coordinator.

ARCHITECTURE: The coordinator calls push_snapshot() at the end of a fetch
cycle for any book carrying meta.dialecticRoomId. The payload is the v3
contract: the existing v2 snapshot export plus `v: 3`, `alertEvents`, and
the thesis identity fields (thesisId / revision / generatedAt).

WHY inline: the SQLite `outbox` table was written as the delivery queue and
no drainer was ever built — 58,769 rows sat pending forever. Pushing inline
at the moment the events are computed is the whole point of the pipeline:
Dialectic learns that a node fired within one tick, not never.

WHY the FILE outbox stays: snapshots/outbox/ (push_to_dialectic.spool_to_outbox)
is the real, working failure spool with a replay path and an operator UI
behind /api/bridge/outbox. A Dialectic outage spools there and drains on a
later push. That mechanism is reused verbatim — this module never duplicates
it.

TRADEOFF (ordering): the spool is drained only AFTER a successful fresh push,
because a success is the cheapest possible proof that Dialectic is reachable —
during an outage we spend zero extra requests. The cost is that replaying
older spools last would leave the room's `thesis_state_current` memory showing
a STALE snapshot (Dialectic upserts that memory by key on every receipt). So
when a drain actually moves at least one spool, the fresh payload is re-posted
once at the end. Receipt is idempotent (memory upsert by stable key), so the
only cost is one extra request on the rare outage-recovery tick.

This module NEVER raises into the caller. Every failure path returns False.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)


# WHY 10s: the coordinator holds the per-thesis lock across this call. A
# Dialectic that accepts the connection but never answers must not be able
# to stall the next fetch cycle — spooling after 10s is strictly better than
# a wedged desk.
PUSH_TIMEOUT_SECONDS = 10.0

# WHY a separate, smaller cap than push_to_dialectic's 500: that cap is sized
# for a cron run that owns its whole process. This drain runs inside a 300s
# tick loop under a lock, so it takes a bounded bite per tick and drains a
# large backlog over successive ticks instead of monopolizing one.
DEFAULT_INLINE_REPLAY_CAP = 25

# Hard ceiling on the whole drain so a slow-but-alive Dialectic cannot hold
# the lock open one spool at a time.
DRAIN_BUDGET_SECONDS = 60.0


def _resolve_dialectic_url() -> str:
    """Same env knob run-all.py and routes/bridge.py honor."""
    return os.environ.get("DIALECTIC_URL", "http://localhost:8002").strip() \
        or "http://localhost:8002"


def _resolve_inline_replay_cap() -> int:
    """Per-tick spool drain cap. Invalid values fall back to the default."""
    raw = os.environ.get("DIALECTIC_INLINE_REPLAY_CAP", "").strip()
    if not raw:
        return DEFAULT_INLINE_REPLAY_CAP
    try:
        val = int(raw)
        if val <= 0:
            raise ValueError("must be positive")
        return val
    except ValueError as e:
        log.warning("invalid DIALECTIC_INLINE_REPLAY_CAP=%r (%s); using %d",
                    raw, e, DEFAULT_INLINE_REPLAY_CAP)
        return DEFAULT_INLINE_REPLAY_CAP


# ════════════════════════════════════════════════════════════════════════
# HTTP CLIENT SINGLETON
# ════════════════════════════════════════════════════════════════════════

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    """Lazily build the shared AsyncClient.

    WHY a singleton: pushes fire every 300s per book. A fresh client per push
    throws away the TCP/TLS connection each time; connection reuse is the
    difference between a ~5ms and a ~150ms push against a remote Dialectic.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=PUSH_TIMEOUT_SECONDS)
    return _client


async def aclose_client() -> None:
    """Close the shared client. Called from RuntimeCoordinator.stop()."""
    global _client
    if _client is not None and not _client.is_closed:
        try:
            await _client.aclose()
        except Exception:  # pragma: no cover — shutdown must never raise
            log.debug("dialectic push client close failed", exc_info=True)
    _client = None


# ════════════════════════════════════════════════════════════════════════
# FILE OUTBOX BRIDGE
# ════════════════════════════════════════════════════════════════════════


def _push_module():
    """Return the single loaded push_to_dialectic module object.

    WHY import from web.routes.bridge rather than repeating the importlib
    dance: a second loader under a different module name would produce a
    SECOND module object with its own OUTBOX_DIR, so a test (or an operator
    knob) that repoints the outbox would silently move only one of them.
    One loader, one module object, one outbox.

    WHY the import is function-local: keeps a runtime→routes edge out of
    module import order entirely.
    """
    from web.routes.bridge import _load_push_module
    return _load_push_module()


# ════════════════════════════════════════════════════════════════════════
# v3 PAYLOAD
# ════════════════════════════════════════════════════════════════════════


def _project_event(evt: Dict[str, Any]) -> Dict[str, Any]:
    """Project a coordinator alert_event onto the v3 wire shape.

    WHY a projection rather than the raw event: event_id and dedupe_key are
    tradingDesk-internal identity, and occurred_at duplicates the snapshot's
    own timestamp. Dialectic gates the curator and web push on severity and
    renders node_id/new_value — those five fields are the contract.
    """
    return {
        "event_type": evt.get("event_type"),
        "severity": evt.get("severity"),
        "node_id": evt.get("node_id"),
        "old_value": evt.get("old_value"),
        "new_value": evt.get("new_value"),
    }


def build_v3_payload(
    thesis_id: str,
    snapshot: dict,
    alert_events: Optional[List[dict]] = None,
) -> dict:
    """Build the v3 contract body from a v2 snapshot export.

    v3 = every v2 field, unchanged, plus:
      v: 3
      alertEvents: [{event_type, severity, node_id, old_value, new_value}]
      thesisId / revision / generatedAt (identity of the producing cycle)

    Dialectic's TradingSnapshotRequest ignores unknown fields, so the extra
    tradingDesk-only blocks the export already carries (feedFreshness,
    horizonTrace, definitionHash) ride along harmlessly.
    """
    payload = dict(snapshot)
    payload["v"] = 3
    payload["alertEvents"] = [_project_event(e) for e in (alert_events or [])]
    payload["thesisId"] = thesis_id
    # revision / generatedAt are stamped onto the export by the coordinator
    # (and persisted into snapshot_json), so they are normally already here.
    # Only default them when pushing a snapshot that predates that stamping.
    payload.setdefault("revision", None)
    payload.setdefault("generatedAt", None)
    return payload


# ════════════════════════════════════════════════════════════════════════
# PUSH
# ════════════════════════════════════════════════════════════════════════


async def _post(url: str, room_token: str, payload: dict) -> bool:
    """One POST attempt. True on 2xx, False on anything else."""
    client = _get_client()
    resp = await client.post(
        url,
        json=payload,
        headers={
            "X-Room-Token": room_token,
            "User-Agent": "tradingDesk-coordinator/3.0",
        },
    )
    if 200 <= resp.status_code < 300:
        return True
    # Body is bounded here so a Dialectic 500 page can't flood the journal.
    log.warning("dialectic push rejected: HTTP %d %s",
                resp.status_code, resp.text[:200])
    return False


def _drain_sync(dialectic_url: str, room_id: str, room_token: str) -> int:
    """Blocking spool drain for one room. Returns spools successfully replayed.

    Delegates to push_to_dialectic.replay_outbox, which replays oldest-first
    and halts on the first failure so ordering survives a mid-drain blip.
    """
    push_mod = _push_module()
    replayed, _failures = push_mod.replay_outbox(
        dialectic_url, room_id, room_token,
        max_per_run=_resolve_inline_replay_cap(),
    )
    return replayed


def _spool_sync(room_id: str, payload: dict, reason: str) -> None:
    """Blocking spool of a failed payload to snapshots/outbox/."""
    push_mod = _push_module()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    push_mod.spool_to_outbox(room_id, body, reason=reason)


async def push_snapshot(
    thesis_id: str,
    snapshot: dict,
    alert_events: List[dict],
    room_id: str,
    room_token: str,
    reason: str,
) -> bool:
    """Push one v3 snapshot to a Dialectic room.

    Returns True when Dialectic accepted the fresh payload, False otherwise.
    NEVER raises: a Dialectic outage, a DNS failure, a malformed room token
    or a bug in this module must not be able to break a fetch cycle.

    `reason` is a short tag for the log line ("events" / "heartbeat" /
    a caller-chosen string) so operators can tell an alert push from the
    hourly keepalive without diffing payloads.
    """
    payload = build_v3_payload(thesis_id, snapshot, alert_events)
    dialectic_url = _resolve_dialectic_url()
    url = f"{dialectic_url.rstrip('/')}/rooms/{room_id}/trading/snapshot"

    try:
        ok = await _post(url, room_token, payload)
    except Exception as e:  # noqa: BLE001 — every transport fault spools
        log.warning("dialectic push failed for %s (%s): %s: %s",
                    thesis_id, reason, type(e).__name__, e)
        ok = False

    if not ok:
        try:
            await asyncio.to_thread(
                _spool_sync, room_id, payload, f"coordinator push ({reason})",
            )
        except Exception:  # noqa: BLE001 — spooling is best-effort too
            log.warning("dialectic spool failed for %s", thesis_id, exc_info=True)
        return False

    log.info("dialectic push ok: %s rev=%s events=%d (%s)",
             thesis_id, payload.get("revision"), len(payload["alertEvents"]),
             reason)

    # Success proves Dialectic is up — opportunistically drain the spool.
    try:
        replayed = await asyncio.wait_for(
            asyncio.to_thread(_drain_sync, dialectic_url, room_id, room_token),
            timeout=DRAIN_BUDGET_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning("dialectic spool drain exceeded %.0fs budget for %s; "
                    "remaining spools stay queued",
                    DRAIN_BUDGET_SECONDS, room_id)
        replayed = 0
    except Exception:  # noqa: BLE001 — drain must never break the cycle
        log.warning("dialectic spool drain failed for %s", room_id, exc_info=True)
        replayed = 0

    if replayed:
        # Older snapshots just overwrote thesis_state_current — restore the
        # room to the state this cycle actually computed. See module docstring.
        log.info("dialectic drained %d spooled snapshot(s) for %s; "
                 "re-posting current revision", replayed, room_id)
        try:
            await _post(url, room_token, payload)
        except Exception:  # noqa: BLE001
            log.warning("dialectic post-drain restore failed for %s", room_id,
                        exc_info=True)

    return True
