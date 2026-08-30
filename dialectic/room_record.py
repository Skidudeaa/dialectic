# room_record.py — the participant reads its own room.
#
# ARCHITECTURE: one read model over what OTHER write paths in this room
# have already produced (the Field, commitments, the Round, the reading
# library) — no new storage, three read-only queries here plus two reused
# from field_inference/reading, wrapped as one `## What This Room Has
# Recorded` prompt section using home_activity.py's own nonce mechanism.
# WHY: the 2026-08-29 audit found llm/prompts.py and llm/orchestrator.py
# had ZERO references to field_mark/question_round/commitment/
# reading_items — every feature shipped since 08-12 was a spoke that
# never routed back through the hub the participant actually reads. This
# module is the read half of closing that loop; wiring it into the
# orchestrator/prompt layers is a separate step, deliberately not done
# here so this file has exactly one job.
#
# THE ROUND IS PRESENCE-ONLY, ON PURPOSE. `stakes/house.py`'s header
# explains the failure class: a sealed forecast value reaching a reader
# that isn't the blindness-gated `api/rounds._round_state` unseals it the
# instant it is read back. The SQL below counts DISTINCT forecasters —
# it never selects `commitment_confidence.confidence` or
# `.peer_forecast`. `tests/test_room_record_pg.py` mutation-tests this:
# selecting confidence must fail the test, not just look wrong.
#
# HUMAN-REVIEWED FIELD MARKS ONLY. field_inference drops several
# provisional, unreviewed marks into a room per day (origin='inferred',
# review='provisional'). Surfacing those to the participant would just
# have it read back its own unconfirmed drafts as if they were the
# room's settled record — an echo, not new information. A mark only
# belongs here once a human has made it directly (origin='explicit') or
# ruled on it (review derived to confirmed/contested).

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from field_marks import FieldMarkService, causal_subject_roles
from geo_scopes import GeoScopeService
from llm.field_inference import _correction_digest_rows, _render_digest
from llm.news_night import COUNTER_LABEL
from llm.reading import recent_readings
from workspace_objects import WorkspaceObjectService

FIELD_MARKS_CAP = 25
CORRECTIONS_CAP = 10
ROUND_CAP = 10
COMMITMENTS_CAP = 10
READINGS_CAP = 8
READING_WINDOW = timedelta(days=3)
GEOGRAPHY_CAP = 10
WORLD_GROUP_CAP = 8
WORLD_ITEM_CAP = 3

_HEADER = (
    "## What This Room Has Recorded\n"
    "Confirmed and contested marks, open commitments, the open Round "
    "(forecast presence only — the numbers are sealed until both humans "
    "commit), and what was read lately. Treat as the room's own ledger; "
    "cite it, do not restate it. Geography is what humans placed; "
    "observations are what feeds reported inside it — cite the scope and "
    "the source, never invent a position.\n"
)

# Presence only. Selecting `cc.confidence` or `cc.peer_forecast` here would
# put a sealed number in front of a reader with no viewer-blindness gate at
# all — see the module docstring. Kept as its own statement rather than
# reused from api/rounds.py: that module's queries are shaped around ONE
# viewer's blindness, and this read has no viewer.
_ROUND_SQL = """
SELECT c.id, c.claim, c.deadline,
       count(DISTINCT cc.user_id) FILTER (WHERE cc.actor = 'human')
           AS human_forecasts,
       bool_or(cc.actor = 'house') AS house_forecast
FROM commitments c
LEFT JOIN commitment_confidence cc ON cc.commitment_id = c.id
WHERE c.room_id = $1 AND c.category = 'round' AND c.status = 'active'
  AND c.deadline > now()
GROUP BY c.id
ORDER BY c.deadline
LIMIT $2
"""

# workspace_objects.WorkspaceObject carries no `deadline` field (the
# commitments() adapter folds category into provenance.detail and drops
# the raw row entirely) — this is the one supplemental read needed to
# render "(due <date>)" for the same rows commitments() already selected,
# filtered and derived a review_state for. Still selects no
# confidence-shaped column; deadline is not a sealed value.
_COMMITMENT_DEADLINES_SQL = (
    "SELECT id, deadline FROM commitments WHERE id = ANY($1::uuid[])"
)

# Presence-and-counts only — never `wo.geometry`. The instruction line in
# `_HEADER` exists precisely because this section is the participant's only
# ambient look at live feeds, and a coordinate rendered here would be a
# position the model never verified, quoted back as if it had (World Lens
# plan, Step 4).
_WORLD_GROUPED_SQL = """
SELECT g.id AS scope_id, g.label AS scope_label, wo.layer, count(*) AS n,
       (array_agg(wo.label ORDER BY wo.last_seen_at DESC))[1] AS newest_label,
       (array_agg(wo.provider ORDER BY wo.last_seen_at DESC))[1] AS newest_provider,
       max(wo.last_seen_at) AS newest_at
FROM world_observations wo
JOIN geo_scopes g ON g.id = wo.scope_id
WHERE wo.room_id = $1 AND wo.last_seen_at > now() - interval '24 hours'
GROUP BY g.id, g.label, wo.layer
ORDER BY newest_at DESC
LIMIT $2
"""

_WORLD_RECENT_BOUND_SQL = """
SELECT wo.label, wo.provider, wo.last_seen_at, g.label AS scope_label
FROM world_observations wo
JOIN geo_scopes g ON g.id = wo.scope_id
WHERE wo.room_id = $1 AND wo.last_seen_at > now() - interval '24 hours'
  AND wo.scope_id = ANY($2::uuid[])
ORDER BY wo.last_seen_at DESC
LIMIT $3
"""


@dataclass
class RoomRecord:
    field_lines: list = field(default_factory=list)
    correction_lines: list = field(default_factory=list)
    round_lines: list = field(default_factory=list)
    commitment_lines: list = field(default_factory=list)
    reading_lines: list = field(default_factory=list)
    geography_lines: list = field(default_factory=list)
    world_lines: list = field(default_factory=list)

    def to_prompt_section(self, max_chars: int = 6000) -> str:
        """Nonce-delimited data section — home_activity.py's
        `to_prompt_section` mechanism copied exactly (same marker
        strings, same whole-block truncation with a trailing marker,
        never mid-line). Empty room -> "" so the prompt omits this
        section like every other optional one; a non-empty result always
        carries the header AND the nonce block together, since a header
        with an empty ledger under it is worse than no header at all.
        """
        blocks = [
            b for b in (
                self._block(
                    "Field (human-reviewed or human-made, newest first, ≤25)",
                    self.field_lines,
                ),
                self._block("Corrections (≤10)", self.correction_lines),
                self._block("Open Round (≤10)", self.round_lines),
                self._block("Open commitments (≤10)", self.commitment_lines),
                self._block("Read lately (3 days, ≤8)", self.reading_lines),
                self._block("Geography", self.geography_lines),
                self._block("Seen in the world (24h)", self.world_lines),
            )
            if b
        ]
        if not blocks:
            return ""
        nonce = secrets.token_hex(4)
        footer = f"[END-DATA-ONLY-BLOCK-{nonce}]"
        assembled = f"[DATA-ONLY-BLOCK-{nonce}]\n"
        truncated = False
        for block in blocks:
            if len(assembled) + len(block) + len(footer) + 1 > max_chars:
                truncated = True
                break
            assembled += block
        if truncated:
            assembled += "[record truncated]\n"
        return _HEADER + assembled + footer

    @staticmethod
    def _block(title: str, lines: list) -> str:
        if not lines:
            return ""
        return f"### {title}\n" + "\n".join(lines) + "\n"


def _age(at: Optional[datetime]) -> str:
    """Small "2h ago" / "3d ago" renderer. No shared humanizer exists yet
    (checked self_model.py, briefing.py, home_activity.py) — this stays
    local rather than inventing a shared module for one caller."""
    if at is None:
        return "unknown"
    seconds = (datetime.now(timezone.utc) - at).total_seconds()
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _field_lines(marks) -> list:
    """Human-reviewed or human-made marks, newest first, capped."""
    kept = [
        m for m in marks
        if m.review in ("confirmed", "contested") or m.origin == "explicit"
    ]
    kept.sort(key=lambda m: m.created_at, reverse=True)
    return [
        f"- [{m.relation}] {m.title} ({m.review})"
        for m in kept[:FIELD_MARKS_CAP]
    ]


def _round_lines(rows) -> list:
    lines = []
    for row in rows:
        n = row["human_forecasts"] or 0
        suffix = ", house" if row["house_forecast"] else ""
        lines.append(
            f"- {row['claim']} — closes {row['deadline']:%a %b %d}; "
            f"forecasts in: {n} of 2 humans{suffix}"
        )
    return lines


async def _commitment_lines(conn, room_id: UUID) -> list:
    """Open, non-Round commitments. `category='round'` rows ride the same
    `commitments` table as ordinary predictions/bets, so they must be
    excluded here the same way `_ROUND_SQL` selects them — via
    `provenance.detail`, the one place workspace_objects.commitments()
    still carries the raw `category` value."""
    objects = await WorkspaceObjectService(conn).commitments(room_id)
    open_commitments = [
        o for o in objects
        if o.status == "active" and o.provenance.detail != "round"
    ][:COMMITMENTS_CAP]
    if not open_commitments:
        return []
    ids = [UUID(o.id.split(":", 1)[1]) for o in open_commitments]
    deadline_rows = await conn.fetch(_COMMITMENT_DEADLINES_SQL, ids)
    deadlines = {r["id"]: r["deadline"] for r in deadline_rows}
    lines = []
    for o in open_commitments:
        deadline = deadlines.get(UUID(o.id.split(":", 1)[1]))
        if deadline is None:
            lines.append(f"- {o.title}")
            continue
        due_flag = ", DUE" if o.review_state == "awaiting_human" else ""
        lines.append(f"- {o.title} (due {deadline:%b %d}{due_flag})")
    return lines


def _reading_lines(rows) -> list:
    lines = []
    for row in rows:
        summary = row.get("summary") or ""
        prefix = COUNTER_LABEL if summary.startswith(COUNTER_LABEL) else ""
        title = row["title"] or row["url"]
        saved_at = (
            datetime.fromisoformat(row["saved_at"]) if row["saved_at"] else None
        )
        lines.append(
            f"- {prefix}{title} — {row['site'] or 'unknown'} "
            f"({row['saved_via']}, {_age(saved_at)})"
        )
    return lines


async def _geography_lines(conn, room_id: UUID, scopes) -> tuple[list, list]:
    """`- {label} ({kind}, {authority}) → {relation} {node_id}` per causal
    binding a live, human-authority scope carries, or `— unbound` when it
    carries none. Returns the lines plus the bound scope ids (raw uuids,
    not `geo_scope:`-prefixed) so `_world_lines` can find the individual
    recent contacts worth naming instead of only aggregate counts.

    WHY `causal_subject_roles` rather than trusting subject array order:
    the same function field_marks.py itself uses to resolve a causal mark's
    evidence/target roles — subject POSITION in the stored JSON is not
    semantic, entity kind is (field_marks.py's own rule).
    """
    if not scopes:
        return [], []
    scope_ids = {UUID(s.id.split(":", 1)[1]) for s in scopes}
    bindings = await FieldMarkService(conn).causal_geo_bindings(room_id, scope_ids)
    by_scope: dict = {}
    for mark in bindings.marks:
        roles = causal_subject_roles(
            mark.relation, [s.model_dump() for s in mark.subjects],
        )
        if roles is None:
            continue
        by_scope.setdefault(roles.evidence["id"], []).append(
            (mark.relation, roles.node_id),
        )
    lines = []
    for scope in scopes:
        scope_id = scope.id.split(":", 1)[1]
        scope_bindings = by_scope.get(scope_id, [])
        if not scope_bindings:
            lines.append(f"- {scope.label} ({scope.kind}, {scope.authority}) — unbound")
            continue
        for relation, node_id in scope_bindings:
            lines.append(
                f"- {scope.label} ({scope.kind}, {scope.authority}) "
                f"→ {relation} {node_id}"
            )
    return lines, [UUID(sid) for sid in by_scope]


async def _world_lines(conn, room_id: UUID, bound_scope_ids: list) -> list:
    """Aggregate counts per scope+layer (≤8), then up to 3 individual newest
    contacts but only inside scopes a human has already bound to a thesis
    node — an unbound scope's contacts are evidence about a place, not yet
    evidence about anything the room has claimed."""
    grouped = await conn.fetch(_WORLD_GROUPED_SQL, room_id, WORLD_GROUP_CAP)
    lines = [
        f'- {row["scope_label"]}: {row["n"]} {row["layer"]} contact(s), '
        f'newest "{row["newest_label"]}" {_age(row["newest_at"])} '
        f'({row["newest_provider"]})'
        for row in grouped
    ]
    if bound_scope_ids:
        recent = await conn.fetch(
            _WORLD_RECENT_BOUND_SQL, room_id, bound_scope_ids, WORLD_ITEM_CAP,
        )
        lines.extend(
            f'- {row["label"]} in {row["scope_label"]}, '
            f'{_age(row["last_seen_at"])}, via {row["provider"]}'
            for row in recent
        )
    return lines


async def build_room_record(conn, room_id: UUID) -> RoomRecord:
    """Read-only statements (Round, plus the commitments/field-marks/geo
    reads inside their reused services) plus two reused functions — no
    writes, no new storage. Every list is independently capped;
    `RoomRecord.to_prompt_section` renders "" when every block comes back
    empty.
    """
    marks = (await FieldMarkService(conn).build(room_id)).marks
    digest_rows = await _correction_digest_rows(conn, room_id)
    round_rows = await conn.fetch(_ROUND_SQL, room_id, ROUND_CAP)
    since = datetime.now(timezone.utc) - READING_WINDOW
    readings = await recent_readings(
        conn, room_id, since=since, limit=READINGS_CAP,
    )
    geo_scopes = [
        s for s in (await GeoScopeService(conn).build(room_id)).scopes
        if s.authority != "machine_proposed"
    ][:GEOGRAPHY_CAP]
    geography_lines, bound_scope_ids = await _geography_lines(
        conn, room_id, geo_scopes,
    )
    world_lines = await _world_lines(conn, room_id, bound_scope_ids)

    return RoomRecord(
        field_lines=_field_lines(marks),
        correction_lines=(
            _render_digest(digest_rows[:CORRECTIONS_CAP]).split("\n")
            if digest_rows else []
        ),
        round_lines=_round_lines(round_rows),
        geography_lines=geography_lines,
        world_lines=world_lines,
        commitment_lines=await _commitment_lines(conn, room_id),
        reading_lines=_reading_lines(readings),
    )
