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
# APPEND-ONLY with supersession. Nothing here UPDATEs or DELETEs. The live
# set is DERIVED at read time by _LIVE_PREDICATE: not expired, not named as
# another row's supersedes_id, and not a `confirmed_empty` row (a person
# looked; it is not there — the vision's word for an answered "none").
#
# WHY this module imports nothing from workspace_objects / field_marks /
# atlas_objects: those will import the GeoScope shape FROM here (Atlas
# carries the fenced scopes in its projection), and the owning module never
# depends on its own adapters — field_marks.py's own docstring states the
# rule. `GeoSubjectRef` mirrors WorkspaceSourceRef field-for-field for the
# same reason.

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel

# --- vocabularies, order-pinned (tests/test_geo_scopes.py pins the TS side
# in the same order: these render as switch arms and legend rows) ----------

GEO_KINDS = ("point", "route", "polygon", "region")

GEO_AUTHORITIES = ("human_confirmed", "source_reported", "machine_proposed")

# The existing evidence statuses (llm/tools.py's news/polymarket contracts)
# plus `confirmed_empty`: we asked, a person answered, the answer is none.
GEO_SOURCE_STATES = (
    "ok", "partial", "confirmed_empty", "stale", "unavailable",
    "rate_limited", "not_configured",
)

# Where a scope's geometry came from — the acquisition path, distinct from
# the provider. `human` drew or chose it; `adapter:<name>` is a feed fix;
# `llm` is the participant's proposal (always paired with machine_proposed).
GEO_ACQUISITIONS = ("human", "adapter", "llm")

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


def scope_from_row(row) -> GeoScope:
    geometry = _jsonb(row["geometry"])
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
g.confirmed_by, g.confirmed_at, g.supersedes_id, g.created_by, g.created_at
"""

# The derived "still stands" rule, stated ONCE and reused by the room
# projection, the Atlas fence query (atlas_objects.py) and the Field's
# subject allowlist (field_marks.py) so three readers cannot disagree about
# which rows are live.
LIVE_PREDICATE = """
(g.expires_at IS NULL OR g.expires_at > NOW())
AND g.source_state <> 'confirmed_empty'
AND NOT EXISTS (SELECT 1 FROM geo_scopes s WHERE s.supersedes_id = g.id)
"""

_ROOM_SQL = f"""
SELECT {_COLUMNS}
FROM geo_scopes g
WHERE g.room_id = $1 AND {LIVE_PREDICATE}
ORDER BY g.created_at DESC
LIMIT $2
"""

_ONE_SQL = f"""
SELECT {_COLUMNS}
FROM geo_scopes g
WHERE g.id = $1 AND g.room_id = $2
"""

_ROOM_CAP = 500

_INSERT_SQL = """
INSERT INTO geo_scopes
    (id, room_id, subject, kind, geometry, label, authority, provenance,
     observed_at, retrieved_at, expires_at, source_state,
     confirmed_by, confirmed_at, supersedes_id, created_by, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
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

    async def get(self, room_id: UUID, scope_id: UUID) -> Optional[GeoScope]:
        row = await self.db.fetchrow(_ONE_SQL, scope_id, room_id)
        return scope_from_row(row) if row else None

    async def is_live(self, scope_id: UUID) -> bool:
        return bool(await self.db.fetchval(
            f"SELECT 1 FROM geo_scopes g WHERE g.id = $1 AND {LIVE_PREDICATE}",
            scope_id,
        ))


async def insert_scope(
    db, *, room_id: UUID, subject: dict, kind: str, geometry: dict,
    authority: str, provenance: dict, label: str = "",
    observed_at: Optional[datetime] = None, expires_at: Optional[datetime] = None,
    source_state: str = "ok", confirmed_by: Optional[UUID] = None,
    supersedes_id: Optional[UUID] = None, created_by: Optional[UUID] = None,
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
    scope_id = uuid4()
    await db.execute(
        _INSERT_SQL,
        scope_id, room_id, subject, kind, clean, label, authority, provenance,
        observed_at, now, expires_at, source_state,
        confirmed_by, now if confirmed_by is not None else None,
        supersedes_id, created_by, now,
    )
    return scope_id
