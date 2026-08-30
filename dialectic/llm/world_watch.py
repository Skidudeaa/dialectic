# llm/world_watch.py — the World Lens consumer

"""
ARCHITECTURE: One 5-minute scheduler job — `world_watch`. Per room that owns
confirmed geography (`world_adapters.room_fences`), it reads the same
process-local `world_signal_store` the live adapters write
(`world_signals.py:337`), keeps only the terms-cleared providers, and tests
each contact against the room's OWN human-confirmed scopes with a real
point-in-polygon test rather than the adapters' padded bounding box. A
contact that lands inside a scope is upserted into `world_observations`
(migration 026) — one row per (scope, contact), `seen_count` rising while it
loiters. When a NEW contact lands inside a scope a human has already bound
to a thesis node (a causal Field mark), the room gets one real facilitator
turn about it — the "electric" moment the World Lens plan calls for.

WHY observations are evidence, never geometry: `world_observations.scope_id`
is a hard FK into `geo_scopes` and this module never calls `insert_scope`.
A provider byte earns no authority by riding through here — it is a
citation about a place a human already confirmed, exactly the standing a
`reading_item` has. The authority ladder (`docs/WORLD_LENS_VISION.md`) is
untouched.

WHY point-in-polygon and not the adapters' bbox: `world_adapters.RoomFence`
pads a room's scope bbox by 1.5 degrees so an approaching contact is visible
before it arrives — the right choice for a live cockpit view, wrong for a
durable record. A padded box is why a room "sees" aircraft over Kerman when
its actual scope is the Strait itself; a persisted fact needs the tighter
test. `geo_scopes.point_in_geometry` is stdlib-only (~25 lines); shapely is
not installed and one function is not a reason to add it.

WHY bound-scope-only for the interjection: an observation inside a scope
nobody has connected to a thesis node is a fact about geography, not yet a
fact about the room's argument. `field_marks.FieldMarkService.
causal_geo_bindings` is the same derived read the Field and Atlas already
use for "does this scope mean something here" — reused verbatim rather than
re-deriving a second notion of "matters." Seeding geography (Step 3 of the
plan) without binding it therefore persists observations silently forever,
which is the authority ladder working as designed, not a gap.

GUARDRAILS:
  - `PERSISTABLE_PROVIDERS` — usgs (PD) and launch (CC-BY) persist freely,
    adsb (ODbL) persists with its credit line carried in `provenance`. `iss`
    is ephemeral-only (no redistribution terms recorded) and is never
    written here even though the store may hold it; `ais`/`opensky` are
    excluded the same way. `firms` joined 2026-08-30 (migration 027, NASA
    open data with acknowledgement). See `docs/WORLD_PROVIDERS.md`.
  - fires are scored, not just counted (`_score_fire`): a FIRMS contact is a
    cell-day, and a cell this ROOM has seen on any prior day inside the
    30-day window is a recurring source — a gas flare, a refinery, a
    furnace — not news. Measured over the Persian Gulf, 87 of 106 daily
    cells recur. Only a `novel` cell with FRP >= `FIRE_NOVEL_MIN_FRP_MW` and
    non-low confidence counts as NEW for the interjection gate below;
    everything persists either way, labelled with its baseline.
  - interjection fires only when: (a) a NEW contact (an insert, not a
    seen-count bump) landed in a scope with >=1 causal binding, (b)
    `rooms.auto_interjection_enabled`, (c) under `WORLD_DAILY_CAP`/room/day
    (counted on the `llm_decisions` ledger, reason `world_interjection` —
    `force_response` already writes that row, the wire/sweep pattern), (d)
    outside quiet hours (`llm.silence_sweep.in_quiet_hours`), (e) the
    fingerprint of `{scope_id: sorted new signal ids}` differs from the last
    `world_interjection` message's stored fingerprint (the
    `trading_curator.snapshot_fingerprint` pattern — a contact that keeps
    reporting the same fix must not re-interrupt the room every five
    minutes). Persistence itself is silent and ignores all five gates.
  - retention: a 30-day `DELETE` runs on every tick (see the `ponytail:`
    comment in `run` for why this is not yet a replay store).

CONNECTIONS: acquires its own connection from `ctx.pool`, like `wire.py` and
`silence_sweep.py` — never the scheduler's own ledger connection.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from field_marks import FieldMarkService, causal_geo_binding_from_mark
from geo_scopes import GeoScopeService, point_in_geometry
from llm.orchestrator import LLMOrchestrator
from llm.silence_sweep import _broadcast_follow_up, _load_room_context, in_quiet_hours
from models import Message, MessageType, SpeakerType
from scheduler import Job, SchedulerContext
from world_adapters import room_fences
from world_signals import world_signal_store

logger = logging.getLogger(__name__)

INTERJECTION_REASON = "world_interjection"
WORLD_DAILY_CAP = 2
RETENTION_DAYS = 30

# Never iss/ais — see the module docstring's provider terms note.
PERSISTABLE_PROVIDERS = frozenset({"usgs", "adsb", "launch", "firms"})
# A novel fire cell below this fire radiative power is edge noise, not an
# event (novel Gulf cells on 2026-08-30 ran 58/36/34/31/21 MW at the top).
FIRE_NOVEL_MIN_FRP_MW = 10.0

# The UPDATE branch refreshes the picture, not just the counter: a fire
# cell-day re-seen by the next satellite carries a higher FRP, and the
# `||` merge keeps the baseline keys `_score_fire` wrote (the adapter's
# details never carry them). The label keeps its baseline suffix (the
# fourth ` · ` field) across the refresh.
_UPSERT_OBSERVATION_SQL = """
INSERT INTO world_observations
    (room_id, scope_id, provider, signal_id, layer, kind, label,
     geometry, provenance, details, observed_at, retrieved_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
ON CONFLICT (scope_id, signal_id) DO UPDATE
    SET last_seen_at = NOW(), seen_count = world_observations.seen_count + 1,
        details = world_observations.details || EXCLUDED.details,
        label = CASE WHEN world_observations.details ? 'novel'
                     THEN EXCLUDED.label || ' · ' || split_part(world_observations.label, ' · ', 4)
                     ELSE EXCLUDED.label END,
        observed_at = COALESCE(EXCLUDED.observed_at, world_observations.observed_at)
RETURNING (xmax = 0) AS inserted
"""

_FIRE_PRIOR_DAYS_SQL = """
SELECT count(DISTINCT details->>'acq_date')
FROM world_observations
WHERE room_id = $1 AND layer = 'fires'
  AND details->>'cell' = $2 AND details->>'acq_date' <> $3
"""

_FIRE_VERDICT_SQL = """
UPDATE world_observations
   SET details = details || $3::jsonb, label = $4
 WHERE scope_id = $1 AND signal_id = $2
"""


async def _upsert_observation(conn, room_id: UUID, scope_id: UUID, signal) -> bool:
    """Upsert one contact into one scope. Returns True for a genuinely NEW
    row (an insert), False for a bump of an existing one — the distinction
    `_maybe_interject` needs to tell "still here" from "just arrived"."""
    row = await conn.fetchrow(
        _UPSERT_OBSERVATION_SQL,
        room_id, scope_id, signal.provider, signal.id, signal.layer,
        signal.kind, signal.label, signal.geometry,
        signal.provenance.model_dump(), signal.details,
        signal.observed_at, signal.retrieved_at,
    )
    return bool(row["inserted"])


def fire_counts_as_new(verdict: dict) -> bool:
    """The layer-aware gate: a fires insert is NEW only when the room has
    never seen that cell in the window, it is hot enough, and VIIRS itself
    did not flag the pixel low-confidence."""
    return bool(
        verdict.get("novel")
        and float(verdict.get("frp_mw") or 0.0) >= FIRE_NOVEL_MIN_FRP_MW
        and verdict.get("confidence") != "l"
    )


async def _score_fire(conn, room_id: UUID, scope_id: UUID, signal) -> dict:
    """Score one freshly inserted fire cell-day against the room's own
    history and stamp the verdict on the row. Room-scoped, so a cell known
    in any of the room's scopes is not new to the room. Runs only on
    inserts (~20/day), never on the bump path.

    ponytail: no index on (room_id, layer, details->>'cell') — ~18k rows
    under 30-day retention; add one if this query shows in pg_stat.
    """
    details = signal.details or {}
    cell, acq_date = details.get("cell"), details.get("acq_date")
    prior_days = 0
    if cell and acq_date:
        prior_days = await conn.fetchval(_FIRE_PRIOR_DAYS_SQL, room_id, cell, acq_date) or 0
    novel = prior_days == 0
    suffix = "NEW vs 30-day baseline" if novel else f"recurring {prior_days}d (likely flare)"
    verdict = {
        "baseline_days": prior_days, "novel": novel,
        "frp_mw": details.get("frp_mw"), "confidence": details.get("confidence"),
        "satellites": details.get("satellites"), "acquired": details.get("acquired"),
    }
    await conn.execute(
        _FIRE_VERDICT_SQL, scope_id, signal.id,
        {"baseline_days": prior_days, "novel": novel}, f"{signal.label} · {suffix}",
    )
    return verdict


async def _interjections_today(conn, room_id) -> int:
    """World interjections already posted in this room today (UTC day —
    the wire/sweep `_interjections_today` pattern)."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM llm_decisions
           WHERE room_id = $1
           AND should_interject
           AND reason = $2
           AND decided_at >= $3""",
        room_id, INTERJECTION_REASON, start_of_day,
    )
    return count or 0


async def _last_world_fingerprint(conn, room_id) -> Optional[str]:
    """The fingerprint stamped on this room's most recent world interjection.

    force_response stamps `metadata.source` to the reason string (it has no
    metadata kwarg of its own), so that is the column this queries — the
    fingerprint itself rides in a second key this module UPDATEs onto the
    message after the turn (see `_maybe_interject`).
    """
    row = await conn.fetchrow(
        """SELECT m.metadata->>'world_fingerprint' AS fingerprint
           FROM messages m
           JOIN threads t ON t.id = m.thread_id
           WHERE t.room_id = $1
             AND m.metadata->>'source' = $2
           ORDER BY m.created_at DESC
           LIMIT 1""",
        room_id, INTERJECTION_REASON,
    )
    return row["fingerprint"] if row else None


_FIRE_NOTE = (
    "A fires contact is a NASA FIRMS VIIRS thermal anomaly. In oil and gas "
    "country most detections are flares and furnaces that recur every day; "
    "a cell this room has NOT seen in 30 days, at this power, is the "
    "exception — the question is what it could be, not that it is hot."
)


def _interjection_content(sections, signals_by_id: dict, fire_verdicts: Optional[dict] = None) -> str:
    """The synthetic SYSTEM turn: scope label, each new contact's
    label/layer/provider + credit, and the bound node ids with their
    relation — so the facilitator speaks to a thesis node, not a dot on a
    map."""
    lines = ["WORLD — new contacts just reported inside geography this room placed:"]
    fires_seen = False
    for scope, signal_ids, bindings in sections:
        scope_label = scope.label if scope is not None else "(scope)"
        lines.append(f"\nScope: {scope_label}")
        for signal_id in signal_ids:
            signal = signals_by_id.get(signal_id)
            if signal is None:
                continue
            credit = signal.provenance.credit or signal.provider
            lines.append(
                f"- {signal.label or signal.source_id} "
                f"({signal.layer}, {signal.provider}) — credit: {credit}"
            )
            verdict = (fire_verdicts or {}).get(signal_id)
            if verdict is not None:
                fires_seen = True
                sats = ", ".join(verdict.get("satellites") or []) or "VIIRS"
                lines.append(
                    f"  FRP {verdict.get('frp_mw')} MW, confidence "
                    f"{verdict.get('confidence')}, {sats}, acquired "
                    f"{verdict.get('acquired')}, prior days in this room's "
                    f"30-day window: {verdict.get('baseline_days')}"
                )
        for binding in bindings:
            lines.append(
                f"Bound to thesis node {binding.target.node_id} "
                f"({binding.relation}) in book {binding.target.book_id}."
            )
    if fires_seen:
        lines.append(f"\n{_FIRE_NOTE}")
    lines.append(
        "\nSpeak to what this means for that node in one short turn; "
        "cite the source."
    )
    return "\n".join(lines)


async def _maybe_interject(
    ctx: SchedulerContext, conn, room_id: UUID,
    new_by_scope: dict[UUID, list[str]], scopes_by_id: dict, signals_by_id: dict,
    fire_verdicts: Optional[dict] = None,
) -> bool:
    """Whether this run's new contacts earn the room one facilitator turn.
    See the module docstring's guardrail list for the five gates in order."""
    room_row = await conn.fetchrow(
        "SELECT auto_interjection_enabled FROM rooms WHERE id = $1", room_id,
    )
    if room_row is None or not room_row["auto_interjection_enabled"]:
        return False
    if await _interjections_today(conn, room_id) >= WORLD_DAILY_CAP:
        return False
    if in_quiet_hours():
        return False

    field_service = FieldMarkService(conn)
    material: dict[str, list[str]] = {}
    sections = []
    for scope_id, signal_ids in new_by_scope.items():
        bindings_projection = await field_service.causal_geo_bindings(
            room_id, {scope_id},
        )
        bindings = [
            binding for binding in (
                causal_geo_binding_from_mark(
                    mark, current_scope_id=f"geo_scope:{scope_id}",
                )
                for mark in bindings_projection.marks
            )
            if binding is not None
        ]
        if not bindings:
            continue
        material[str(scope_id)] = sorted(signal_ids)
        sections.append((scopes_by_id.get(scope_id), signal_ids, bindings))

    if not sections:
        return False

    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True).encode("utf-8"),
    ).hexdigest()[:16]
    if await _last_world_fingerprint(conn, room_id) == fingerprint:
        return False

    loaded = await _load_room_context(conn, room_id)
    if loaded is None:
        return False
    room, thread, users, messages, memories = loaded

    context_message = Message(
        id=uuid4(),
        thread_id=thread.id,
        sequence=(messages[-1].sequence + 1) if messages else 1,
        created_at=datetime.now(timezone.utc),
        speaker_type=SpeakerType.SYSTEM,
        user_id=None,
        message_type=MessageType.TEXT,
        content=_interjection_content(sections, signals_by_id, fire_verdicts),
    )

    orchestrator = LLMOrchestrator(conn, db_pool=ctx.pool)
    result = await orchestrator.force_response(
        room=room, thread=thread, users=users,
        messages=[*messages, context_message], memories=memories,
        reason=INTERJECTION_REASON,
    )
    if not (result.triggered and result.response):
        return False

    # force_response has no metadata kwarg, so the fingerprint is stamped
    # here — the trading_curator.snapshot_fingerprint pattern, applied after
    # the turn instead of at persist time.
    await conn.execute(
        """UPDATE messages SET metadata = COALESCE(metadata, '{}'::jsonb)
               || jsonb_build_object('world_fingerprint', $1::text)
           WHERE id = $2""",
        fingerprint, result.response.id,
    )
    await _broadcast_follow_up(ctx, room_id, result.response)
    return True


async def _process_room(ctx: SchedulerContext, conn, room_id: UUID) -> dict:
    """One room's pass: persist every contact inside its confirmed
    geography, then decide whether the new arrivals earn an interjection."""
    scopes_projection = await GeoScopeService(conn).build(room_id)
    scopes_by_id = {
        UUID(scope.id.split(":", 1)[1]): scope
        for scope in scopes_projection.scopes
        if scope.authority != "machine_proposed"
    }
    if not scopes_by_id:
        return {"new": 0, "seen": 0, "interjected": False}

    signals = [
        signal for signal in world_signal_store.project([room_id]).signals
        if signal.provider in PERSISTABLE_PROVIDERS
    ]
    signals_by_id = {signal.id: signal for signal in signals}

    new_count = 0
    seen_count = 0
    new_by_scope: dict[UUID, list[str]] = {}
    fire_verdicts: dict[str, dict] = {}

    for scope_id, scope in scopes_by_id.items():
        for signal in signals:
            coords = signal.geometry.get("coordinates")
            if not (isinstance(coords, (list, tuple)) and len(coords) >= 2):
                continue
            lon, lat = float(coords[0]), float(coords[1])
            # point_in_geometry returns False for Point/LineString scopes by
            # construction, so no separate `scope.kind` check is needed here.
            if not point_in_geometry(scope.geometry, lon, lat):
                continue
            if await _upsert_observation(conn, room_id, scope_id, signal):
                new_count += 1
                if signal.layer == "fires":
                    verdict = await _score_fire(conn, room_id, scope_id, signal)
                    if not fire_counts_as_new(verdict):
                        continue  # persisted and labelled; a flare is not news
                    fire_verdicts[signal.id] = verdict
                new_by_scope.setdefault(scope_id, []).append(signal.id)
            else:
                seen_count += 1

    interjected = False
    if new_by_scope:
        interjected = await _maybe_interject(
            ctx, conn, room_id, new_by_scope, scopes_by_id, signals_by_id,
            fire_verdicts,
        )

    return {"new": new_count, "seen": seen_count, "interjected": interjected}


async def run(ctx: SchedulerContext) -> dict:
    """One pass over every room with confirmed geography."""
    detail: dict = {}
    async with ctx.pool.acquire() as conn:
        # ponytail: 30-day retention ceiling stated here rather than as a
        # separate job — a contact that stopped reporting a month ago is not
        # evidence about "now". A replay store (keeping expired rows for
        # historical query) is a later decision, not this one.
        await conn.execute(
            "DELETE FROM world_observations "
            "WHERE last_seen_at < NOW() - ($1 || ' days')::interval",
            str(RETENTION_DAYS),
        )
        for fence in await room_fences(conn):
            room_key = str(fence.room_id)
            try:
                detail[room_key] = await _process_room(ctx, conn, fence.room_id)
            except Exception:
                # A broken room must not sink the watch for every other one
                # (the wire_watch pattern).
                logger.exception("world_watch failed for room %s", room_key)
                detail[room_key] = "error: processing_failed"
    return detail


def register_world_watch_jobs(scheduler) -> None:
    scheduler.register(Job(
        "world_watch", 300, run, enabled_env="WORLD_WATCH_ENABLED",
    ))
