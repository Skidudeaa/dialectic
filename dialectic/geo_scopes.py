# geo_scopes.py — where a thing is, and who says so.
#
# ARCHITECTURE (docs/WORLD_LENS_VISION.md): the World Lens substrate. One
# table (migration 021) attaches geometry to rows that already exist —
# a reading, a room's thesis, a Field mark, a message — through the same
# {entity, id, field} subject ref the Field and the workroom projection use.
# This module OWNS that table the way field_marks.py owns field_marks:
# vocabularies, the row → model projection, the subject allowlist, and the
# one insert path every writer (api/geo.py, the seed script, later the LLM
# tool and the feed adapters) goes through.
#
# AUTHORITY IS A COLUMN. `human_confirmed` is a person's act, stamped in the
# same row (the CHECK in the migration refuses a human_confirmed row without
# confirmed_by). `machine_proposed` is what the participant may write; it
# renders provisional and cannot be a Field-mark subject (field_marks.py's
# allowlist carries the predicate). `source_reported` is an adapter's fix a
# human placed or marked. No LLM-invented coordinate ever becomes
# authoritative by any path but a human's confirm.
#
# APPEND-ONLY with supersession. Migration 022 rejects UPDATE/DELETE in the
# database. The live set is DERIVED at read time: not expired, not named as a
# predecessor, and not rejected/superseded. Legacy `confirmed_empty` rows stay
# immutable and derive rejected review state; new rejection is revision_action.
#
# WHY this module imports nothing from workspace_objects / field_marks /
# atlas_objects: those will import the GeoScope shape FROM here (Atlas
# carries the fenced scopes in its projection), and the owning module never
# depends on its own adapters — field_marks.py's own docstring states the
# rule. `GeoSubjectRef` mirrors WorkspaceSourceRef field-for-field for the
# same reason.

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel

# --- vocabularies, order-pinned (tests/test_geo_scopes.py pins the TS side
# in the same order: these render as switch arms and legend rows) ----------

GEO_KINDS = ("point", "route", "polygon", "region")

GEO_AUTHORITIES = ("human_confirmed", "source_reported", "machine_proposed")

# The existing evidence statuses (llm/tools.py's news/polymarket contracts)
# plus legacy `confirmed_empty`, retained for read compatibility only.
GEO_SOURCE_STATES = (
    "ok", "partial", "confirmed_empty", "stale", "unavailable",
    "rate_limited", "not_configured",
)

# Where a scope's geometry came from — the acquisition path, distinct from
# the provider. `human` drew or chose it; `adapter:<name>` is a feed fix;
# `llm` is the participant's proposal (always paired with machine_proposed).
GEO_ACQUISITIONS = ("human", "adapter", "llm")

GEO_REVISION_ACTIONS = (
    "place", "propose", "confirm", "reject", "redraw", "supersede",
    "ratify", "place_signal",
)

GEO_REVIEW_STATES = ("accepted", "proposed", "rejected", "superseded")

GEO_FRESHNESS_STATES = (
    "current", "stale", "expired", "unknown", "not_applicable",
)

_GEOMETRY_TYPES = {
    "point": "Point",
    "route": "LineString",
    "polygon": "Polygon",
    "region": "Polygon",
}
_MAX_VERTICES = 2000

# Every entity a subject ref may name, and how to check it belongs to the
# room. Table names come from this fixed dict, never from a caller, so the
# f-string in resolve_subject_in_room is not a SQL-injection surface. A room
# is a legitimate subject (the Strait polygon belongs to the Hormuz room,
# not to any one reading), which is the one entry field_marks' list lacks.
_SUBJECT_ENTITY_TABLES = {
    "rooms": ("rooms", "id", "id"),
    "messages": ("messages m JOIN threads t ON t.id = m.thread_id", "t.room_id", "m.id"),
    "reading_items": ("reading_items", "room_id", "id"),
    "memories": ("memories", "room_id", "id"),
    "field_marks": ("field_marks", "room_id", "id"),
}


class GeoSubjectRef(BaseModel):
    """Exactly which row this geometry is about. Mirrors
    workspace_objects.WorkspaceSourceRef (entity, id, field) without importing
    it — see the module docstring."""
    entity: str
    id: str
    field: Optional[str] = None


class GeoProvenance(BaseModel):
    """Who reported this geometry and by what path. `credit` is the
    attribution line a surface must show (Natural Earth asks for "Made with
    Natural Earth"; ODbL feeds require theirs) — attached to the evidence,
    not only to a map layer (vision §take-and-adapt 6)."""
    provider: str
    acquisition: str
    source_id: Optional[str] = None
    url: Optional[str] = None
    credit: str = ""


class GeoFreshness(BaseModel):
    """Observation time is evidence time; retrieval time is ingestion time.
    Review and provider condition remain separate axes on ``GeoScope``."""
    state: str
    observed_at: Optional[datetime] = None
    retrieved_at: datetime
    expires_at: Optional[datetime] = None


class GeoScope(BaseModel):
    """One geometry row exactly as a surface renders it.

    `id` is `geo_scope:<uuid>`, matching every other workspace-object id
    convention. `centroid` is DERIVED ([lon, lat]) so a list or a pin never
    has to re-walk the ring. `supersedes_id` stays a bare row id: it is a
    foreign key into this same table, not a cross-entity ref.
    """
    id: str
    room_id: UUID
    subject: GeoSubjectRef
    kind: str
    geometry: dict
    label: str
    authority: str
    provenance: GeoProvenance
    source_state: str
    revision_action: str
    review_note: Optional[str] = None
    review_state: str
    freshness: GeoFreshness
    centroid: list[float]
    observed_at: Optional[datetime] = None
    retrieved_at: datetime
    expires_at: Optional[datetime] = None
    confirmed_by: Optional[UUID] = None
    confirmed_at: Optional[datetime] = None
    supersedes_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime


class GeoProjection(BaseModel):
    generated_at: datetime
    room_id: UUID
    scopes: list[GeoScope]


class GeoSubjectDestination(BaseModel):
    """The navigation coordinates derived from the stored subject row."""
    room_id: UUID
    thread_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    object_id: Optional[str] = None


class GeoScopeReview(BaseModel):
    root_id: str
    current: GeoScope
    lineage: list[GeoScope]
    subject_destination: GeoSubjectDestination


# --- geometry -------------------------------------------------------------

def _position(value: Any) -> tuple[float, float]:
    if (not isinstance(value, (list, tuple)) or len(value) < 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value[:2])):
        raise ValueError("position must be [lon, lat]")
    lon, lat = float(value[0]), float(value[1])
    if not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
        raise ValueError("position out of range")
    return lon, lat


def validate_geometry(kind: str, geometry: Any) -> dict:
    """A GeoJSON geometry of the type `kind` demands, positions in range,
    rings closed, bounded in size. Returns the geometry with positions
    normalised to [lon, lat] floats. Raises ValueError with a reason a 422
    can carry verbatim.

    WHY rings must arrive closed rather than be closed here: a client that
    forgot the closing vertex may also have forgotten the ring's direction
    or dropped a vertex; refusing is cheaper than guessing.
    """
    if kind not in GEO_KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a GeoJSON object")
    expected = _GEOMETRY_TYPES[kind]
    if geometry.get("type") != expected:
        raise ValueError(f"{kind} requires a {expected} geometry")
    coords = geometry.get("coordinates")
    if expected == "Point":
        return {"type": "Point", "coordinates": list(_position(coords))}
    if expected == "LineString":
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("route needs at least two positions")
        if len(coords) > _MAX_VERTICES:
            raise ValueError("too many vertices")
        return {"type": "LineString", "coordinates": [list(_position(c)) for c in coords]}
    # Polygon: outer ring only is what the World renders; holes are kept if
    # present but every ring must be a closed ring of ≥ 4 positions.
    if not isinstance(coords, list) or not coords:
        raise ValueError("polygon needs an outer ring")
    rings = []
    total = 0
    for ring in coords:
        if not isinstance(ring, list) or len(ring) < 4:
            raise ValueError("a ring needs at least four positions")
        total += len(ring)
        if total > _MAX_VERTICES:
            raise ValueError("too many vertices")
        positions = [list(_position(c)) for c in ring]
        if positions[0] != positions[-1]:
            raise ValueError("a ring must close on its first position")
        rings.append(positions)
    return {"type": "Polygon", "coordinates": rings}


def centroid(geometry: dict) -> list[float]:
    """Vertex-average [lon, lat] — a pin position, not a geodesic centroid.
    The closing vertex of a ring is skipped so it does not double-weight.
    ponytail: vertex average is wrong for rings crossing the antimeridian;
    add a shoelace/great-circle centroid if a scope ever straddles ±180."""
    t = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if t == "Point":
        return [float(coords[0]), float(coords[1])]
    if t == "LineString":
        points = coords
    else:
        outer = coords[0] if coords else []
        points = outer[:-1] if len(outer) > 1 else outer
    if not points:
        return [0.0, 0.0]
    lon = sum(float(p[0]) for p in points) / len(points)
    lat = sum(float(p[1]) for p in points) / len(points)
    return [round(lon, 5), round(lat, 5)]


# --- subjects -------------------------------------------------------------

async def resolve_subject_in_room(db, room_id: UUID, subject: dict) -> bool:
    """The subject ref resolves to a real row IN THIS ROOM, checked in SQL.
    Client payloads and model output are documents, not trust boundaries."""
    table = _SUBJECT_ENTITY_TABLES.get(subject.get("entity"))
    if table is None:
        return False
    source, room_col, id_col = table
    try:
        subject_id = UUID(str(subject.get("id")))
    except (TypeError, ValueError):
        return False
    found = await db.fetchval(
        f"SELECT 1 FROM {source} WHERE {id_col} = $1 AND {room_col} = $2",
        subject_id, room_id,
    )
    return bool(found)


# --- rows -----------------------------------------------------------------

def _jsonb(value: Any) -> dict:
    """A JSONB column as a dict, whichever way the connection hands it over
    (each projection module owns its own copy — workspace_objects._jsonb's
    reasoning)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _derived_revision_action(row: Any) -> str:
    stored = _row_value(row, "revision_action")
    if stored:
        return str(stored)
    if row["source_state"] == "confirmed_empty":
        return "reject"
    if row["supersedes_id"] is not None:
        return "confirm"
    if row["authority"] == "machine_proposed":
        return "propose"
    if row["authority"] == "source_reported":
        return "place_signal"
    return "place"


def _derived_review_state(row: Any, action: str) -> str:
    if bool(_row_value(row, "has_successor", False)):
        return "superseded"
    if action in ("reject", "supersede") or row["source_state"] == "confirmed_empty":
        return "rejected"
    if row["authority"] == "machine_proposed":
        return "proposed"
    return "accepted"


def _derived_freshness(row: Any, now: datetime) -> GeoFreshness:
    observed_at = row["observed_at"]
    retrieved_at = row["retrieved_at"]
    expires_at = row["expires_at"]
    if expires_at is not None and expires_at <= now:
        state = "expired"
    elif row["source_state"] == "stale":
        state = "stale"
    elif row["source_state"] in ("unavailable", "rate_limited", "not_configured"):
        state = "unknown"
    elif observed_at is not None:
        state = "current"
    elif row["authority"] == "source_reported":
        state = "unknown"
    else:
        state = "not_applicable"
    return GeoFreshness(
        state=state, observed_at=observed_at, retrieved_at=retrieved_at,
        expires_at=expires_at,
    )


def scope_from_row(row: Any, *, now: Optional[datetime] = None) -> GeoScope:
    geometry = _jsonb(row["geometry"])
    action = _derived_revision_action(row)
    projection_now = now or datetime.now(timezone.utc)
    return GeoScope(
        id=f"geo_scope:{row['id']}",
        room_id=row["room_id"],
        subject=GeoSubjectRef(**_jsonb(row["subject"])),
        kind=row["kind"],
        geometry=geometry,
        label=row["label"] or "",
        authority=row["authority"],
        provenance=GeoProvenance(**_jsonb(row["provenance"])),
        source_state=row["source_state"],
        revision_action=action,
        review_note=_row_value(row, "review_note"),
        review_state=_derived_review_state(row, action),
        freshness=_derived_freshness(row, projection_now),
        centroid=centroid(geometry),
        observed_at=row["observed_at"],
        retrieved_at=row["retrieved_at"],
        expires_at=row["expires_at"],
        confirmed_by=row["confirmed_by"],
        confirmed_at=row["confirmed_at"],
        supersedes_id=row["supersedes_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


_COLUMNS = """
g.id, g.room_id, g.subject, g.kind, g.geometry, g.label, g.authority,
g.provenance, g.source_state, g.observed_at, g.retrieved_at, g.expires_at,
g.confirmed_by, g.confirmed_at, g.supersedes_id, g.revision_action,
g.review_note, g.created_by, g.created_at,
EXISTS (SELECT 1 FROM geo_scopes successor WHERE successor.supersedes_id = g.id)
    AS has_successor
"""

# The derived "still stands" rule, stated ONCE and reused by the room
# projection, the Atlas fence query (atlas_objects.py) and the Field's
# subject allowlist (field_marks.py) so three readers cannot disagree about
# which rows are live.
def live_predicate(alias: str) -> str:
    """Canonical SQL for a scope that still stands, qualified by ``alias``.

    The alias is owned by source code, never request data. Validation keeps a
    future dynamic caller from turning this shared SQL fragment into an
    injection surface.
    """
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias) is None:
        raise ValueError(f"invalid SQL alias: {alias}")
    return f"""
({alias}.expires_at IS NULL OR {alias}.expires_at > NOW())
AND {alias}.source_state <> 'confirmed_empty'
AND ({alias}.revision_action IS NULL OR {alias}.revision_action NOT IN ('reject', 'supersede'))
AND NOT EXISTS (
    SELECT 1 FROM geo_scopes geo_scope_successor
    WHERE geo_scope_successor.supersedes_id = {alias}.id
)
"""


LIVE_PREDICATE = live_predicate("g")

_ROOM_SQL = f"""
SELECT {_COLUMNS}
FROM geo_scopes g
WHERE g.room_id = $1 AND {LIVE_PREDICATE}
ORDER BY g.created_at DESC
LIMIT $2
"""

_LIVE_COUNT_SQL = f"""
SELECT count(*)
FROM geo_scopes g
WHERE g.room_id = $1 AND {LIVE_PREDICATE}
"""

_EXACT_LIVE_LABEL_SQL = f"""
SELECT {_COLUMNS}
FROM geo_scopes g
WHERE g.room_id = $1 AND g.label = $2 AND {LIVE_PREDICATE}
ORDER BY g.created_at DESC, g.id DESC
LIMIT 2
"""

_ONE_SQL = f"""
SELECT {_COLUMNS}
FROM geo_scopes g
WHERE g.id = $1 AND g.room_id = $2
"""

_ONE_FOR_UPDATE_SQL = f"""
SELECT {_COLUMNS}
FROM geo_scopes g
WHERE g.id = $1 AND g.room_id = $2
FOR UPDATE OF g
"""

_ANCESTORS_SQL = """
WITH RECURSIVE ancestors(id, supersedes_id, path, cycle) AS (
    SELECT g.id, g.supersedes_id, ARRAY[g.id], FALSE
    FROM geo_scopes g
    WHERE g.id = $1 AND g.room_id = $2
  UNION ALL
    SELECT parent.id, parent.supersedes_id,
           ancestors.path || parent.id,
           parent.id = ANY(ancestors.path)
    FROM geo_scopes parent
    JOIN ancestors ON ancestors.supersedes_id = parent.id
    WHERE parent.room_id = $2 AND NOT ancestors.cycle
)
SELECT id, supersedes_id, path, cycle
FROM ancestors
"""

_LINEAGE_SQL = f"""
WITH RECURSIVE lineage(id, path, cycle) AS (
    SELECT g.id, ARRAY[g.id], FALSE
    FROM geo_scopes g
    WHERE g.id = $1 AND g.room_id = $2
  UNION ALL
    SELECT successor.id, lineage.path || successor.id,
           successor.id = ANY(lineage.path)
    FROM geo_scopes successor
    JOIN lineage ON successor.supersedes_id = lineage.id
    WHERE successor.room_id = $2 AND NOT lineage.cycle
)
SELECT {_COLUMNS}, lineage.cycle AS lineage_cycle
FROM lineage
JOIN geo_scopes g ON g.id = lineage.id
ORDER BY cardinality(lineage.path)
"""

_ROOM_CAP = 500

_INSERT_SQL = """
INSERT INTO geo_scopes
    (id, room_id, subject, kind, geometry, label, authority, provenance,
     observed_at, retrieved_at, expires_at, source_state,
     confirmed_by, confirmed_at, supersedes_id, revision_action, review_note,
     created_by, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
"""


class GeoScopeService:
    """Projects the room's live scopes. Read-only by construction."""

    def __init__(self, db):
        self.db = db

    async def build(self, room_id: UUID) -> GeoProjection:
        rows = await self.db.fetch(_ROOM_SQL, room_id, _ROOM_CAP)
        return GeoProjection(
            generated_at=datetime.now(timezone.utc),
            room_id=room_id,
            scopes=[scope_from_row(r) for r in rows],
        )

    async def live_count(self, room_id: UUID) -> int:
        """Exact number of scopes in the canonical live room projection."""
        return int(await self.db.fetchval(_LIVE_COUNT_SQL, room_id))

    async def find_live_by_exact_label(
        self, room_id: UUID, label: str,
    ) -> list[GeoScope]:
        """At most two exact-label live matches, enough to prove uniqueness."""
        rows = await self.db.fetch(_EXACT_LIVE_LABEL_SQL, room_id, label)
        return [scope_from_row(row) for row in rows]

    async def get(self, room_id: UUID, scope_id: UUID) -> Optional[GeoScope]:
        row = await self.db.fetchrow(_ONE_SQL, scope_id, room_id)
        return scope_from_row(row) if row else None

    async def get_for_update(
        self, room_id: UUID, scope_id: UUID,
    ) -> Optional[GeoScope]:
        row = await self.db.fetchrow(_ONE_FOR_UPDATE_SQL, scope_id, room_id)
        return scope_from_row(row) if row else None

    async def is_live(self, scope_id: UUID) -> bool:
        return bool(await self.db.fetchval(
            f"SELECT 1 FROM geo_scopes g WHERE g.id = $1 AND {LIVE_PREDICATE}",
            scope_id,
        ))

    async def review(
        self, room_id: UUID, scope_id: UUID,
    ) -> Optional[GeoScopeReview]:
        ancestors = await self.db.fetch(_ANCESTORS_SQL, scope_id, room_id)
        if not ancestors:
            return None
        if any(row["cycle"] for row in ancestors):
            raise ValueError("geo scope lineage cycle detected while finding root")
        roots = [row["id"] for row in ancestors if row["supersedes_id"] is None]
        if len(roots) != 1:
            raise ValueError("geo scope lineage has no unique root")
        rows = await self.db.fetch(_LINEAGE_SQL, roots[0], room_id)
        if any(row["lineage_cycle"] for row in rows):
            raise ValueError("geo scope lineage cycle detected while finding current scope")
        lineage = [scope_from_row(row) for row in rows]
        destination = await self._subject_destination(room_id, lineage[-1].subject)
        return GeoScopeReview(
            root_id=lineage[0].id,
            current=lineage[-1],
            lineage=lineage,
            subject_destination=destination,
        )

    async def _subject_destination(
        self, room_id: UUID, subject: GeoSubjectRef,
    ) -> GeoSubjectDestination:
        try:
            subject_id = UUID(subject.id)
        except ValueError as exc:
            raise ValueError(f"stored geo subject has invalid id: {subject.id}") from exc
        if subject.entity == "rooms":
            return GeoSubjectDestination(room_id=room_id)
        if subject.entity == "messages":
            thread_id = await self.db.fetchval(
                """SELECT m.thread_id FROM messages m
                   JOIN threads t ON t.id = m.thread_id
                   WHERE m.id = $1 AND t.room_id = $2""",
                subject_id, room_id,
            )
            if thread_id is None:
                raise ValueError("stored geo message subject no longer resolves")
            return GeoSubjectDestination(
                room_id=room_id, thread_id=thread_id, message_id=subject_id,
            )
        prefixes = {
            "reading_items": "reading",
            "field_marks": "field_mark",
            "memories": "memory",
        }
        prefix = prefixes.get(subject.entity)
        if prefix is None:
            raise ValueError(f"stored geo subject entity is unsupported: {subject.entity}")
        return GeoSubjectDestination(
            room_id=room_id, object_id=f"{prefix}:{subject_id}",
        )


async def insert_scope(
    db, *, room_id: UUID, subject: dict, kind: str, geometry: dict,
    authority: str, provenance: dict, label: str = "",
    observed_at: Optional[datetime] = None, expires_at: Optional[datetime] = None,
    source_state: str = "ok", confirmed_by: Optional[UUID] = None,
    supersedes_id: Optional[UUID] = None, created_by: Optional[UUID] = None,
    revision_action: Optional[str] = None, review_note: Optional[str] = None,
    retrieved_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> UUID:
    """The one insert path. Validates the closed vocabularies and the
    geometry here so no writer can reach SQL with a shape the surfaces
    cannot render; the DB CHECKs are the backstop, not the door.

    WHY confirmed_by is forced to match authority rather than trusted: the
    CHECK `confirmed_iff_human` would reject the row anyway, but a ValueError
    names the reason and a 422 can carry it.
    """
    if authority not in GEO_AUTHORITIES:
        raise ValueError(f"unknown authority: {authority}")
    if source_state not in GEO_SOURCE_STATES:
        raise ValueError(f"unknown source_state: {source_state}")
    if revision_action is not None and revision_action not in GEO_REVISION_ACTIONS:
        raise ValueError(f"unknown revision_action: {revision_action}")
    if (authority == "human_confirmed") != (confirmed_by is not None):
        raise ValueError("human_confirmed requires confirmed_by, and only it may carry one")
    if subject.get("entity") not in _SUBJECT_ENTITY_TABLES:
        raise ValueError(f"unknown subject entity: {subject.get('entity')}")
    if provenance.get("acquisition", "").split(":")[0] not in GEO_ACQUISITIONS:
        raise ValueError("provenance.acquisition must be human, adapter:<name> or llm")
    if authority == "machine_proposed" and provenance.get("acquisition") != "llm":
        raise ValueError("machine_proposed geometry must be acquired by llm")
    GeoProvenance(**provenance)  # shape check; raises pydantic ValidationError
    clean = validate_geometry(kind, geometry)
    now = now or datetime.now(timezone.utc)
    if revision_action is None:
        if source_state == "confirmed_empty":
            revision_action = "reject"
        elif supersedes_id is not None:
            revision_action = "confirm"
        elif authority == "machine_proposed":
            revision_action = "propose"
        elif authority == "source_reported":
            revision_action = "place_signal"
        else:
            revision_action = "place"
    scope_id = uuid4()
    await db.execute(
        _INSERT_SQL,
        scope_id, room_id, subject, kind, clean, label, authority, provenance,
        observed_at, retrieved_at or now, expires_at, source_state,
        confirmed_by, now if confirmed_by is not None else None,
        supersedes_id, revision_action, review_note, created_by, now,
    )
    return scope_id
