# llm/world.py — the participant's eyes on the world, held to the vision.
#
# ARCHITECTURE (docs/WORLD_LENS_VISION.md): "An LLM may propose that a reading
# concerns the Strait of Hormuz. It may not silently convert prose into
# authoritative coordinates." So the ONE tool here never invents geometry. It
# resolves a NAME — a Natural Earth marine region (public domain, provenance
# in-file) or one of the room's own live, human-confirmed scopes — and
# attaches THAT geometry to a subject as a `machine_proposed` row, which
# renders provisional and cannot anchor a Field mark until a person confirms
# it (geo_scopes.py, field_marks.py). A name it cannot resolve returns the
# nearest candidates instead of a guess, so the model corrects itself rather
# than the map lying.
#
# WHY a proposal EXPIRES: a proposal nobody looks at is not evidence; after
# PROPOSAL_TTL it stops rendering. Confirming inserts a human_confirmed
# replacement that does not expire (api/geo.py).

import difflib
import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from geo_scopes import (
    LIVE_PREDICATE,
    insert_scope,
    resolve_subject_in_room,
)
from models import EventType

MARINE_PATH = Path(__file__).resolve().parents[1] / "data" / "natural_earth" / "marine.json"
PROPOSAL_TTL = timedelta(days=14)
_MAX_CANDIDATES = 5

_SUBJECT_ENTITIES = {
    "room": "rooms",
    "reading": "reading_items",
    "message": "messages",
}


def world_tools_enabled() -> bool:
    """Default on; `DIALECTIC_WORLD_ENABLED=0` removes the tool from the
    registry (the same module-level, read-at-call-time idiom as
    `_cairn_tools_enabled`)."""
    return os.environ.get("DIALECTIC_WORLD_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


@lru_cache(maxsize=1)
def _marine() -> dict:
    return json.loads(MARINE_PATH.read_text())


def marine_names() -> list[str]:
    return [f["name"] for f in _marine()["features"]]


def natural_earth_region(name: str) -> Optional[tuple[str, dict, dict]]:
    """(canonical name, closed Polygon geometry, provenance) for a marine
    feature, or None. Largest ring by vertex count when the feature is a
    multipolygon — the same rule deploy/seed_hormuz_geo.py uses."""
    pack = _marine()
    wanted = name.strip().lower()
    matches = [f for f in pack["features"] if f["name"].lower() == wanted]
    if not matches:
        return None
    ring = max((p for f in matches for p in f["polygons"]), key=len)
    closed = [list(p) for p in ring] + [list(ring[0])]
    geometry = {"type": "Polygon", "coordinates": [closed]}
    provenance = {
        "provider": "natural_earth",
        "acquisition": "llm",
        "source_id": matches[0]["name"],
        "url": pack["meta"].get("url"),
        "credit": "Made with Natural Earth",
    }
    return matches[0]["name"], geometry, provenance


def candidates_for(name: str, extra: list[str] = ()) -> list[str]:
    """Nearest names, for the tool's honest miss: substring hits first, then
    string similarity — case-insensitive, the room's own labels ranking
    with the marine set."""
    pool = list(extra) + marine_names()
    wanted = name.strip().lower()
    out: list[str] = []

    def take(names):
        for n in names:
            if n not in out:
                out.append(n)

    take(n for n in pool if wanted and wanted in n.lower())
    lowered = {n.lower(): n for n in pool}
    close = difflib.get_close_matches(wanted, list(lowered), n=_MAX_CANDIDATES, cutoff=0.3)
    take(lowered[c] for c in close)
    return out[:_MAX_CANDIDATES]


_ROOM_SCOPES_SQL = f"""
SELECT g.id, g.label, g.kind, g.geometry, g.provenance
FROM geo_scopes g
WHERE g.room_id = $1 AND g.authority = 'human_confirmed' AND {LIVE_PREDICATE}
ORDER BY g.created_at DESC
LIMIT 100
"""

_READING_BY_URL_SQL = "SELECT id FROM reading_items WHERE room_id = $1 AND url = $2"

_INSERT_EVENT_SQL = """
INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
VALUES ($1, $2, $3, $4, NULL, NULL, $5)
"""


async def _record_event(
    db: Any, *, event_id: UUID, now: datetime, room_id: UUID, payload: dict,
) -> None:
    await db.execute(
        _INSERT_EVENT_SQL, event_id, now, EventType.GEO_SCOPE_CREATED.value,
        room_id, payload,
    )


def _jsonb(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except ValueError:
            return {}
    return {}


async def propose_geo_scope(db, room_id: UUID, args: dict) -> dict:
    """The executor. Never raises for a bad name — returns the candidates.
    Raises ValueError for a malformed call (the loop reports it as is_error)."""
    region = str(args.get("region") or "").strip()
    if not region:
        raise ValueError("region is required — a named sea, gulf, strait, or one of the room's own scopes")
    subject_kind = str(args.get("subject_kind") or "room").strip().lower()
    entity = _SUBJECT_ENTITIES.get(subject_kind)
    if entity is None:
        raise ValueError("subject_kind must be room, reading or message")
    why = str(args.get("why") or "").strip()[:500]

    # Resolve the subject IN THIS ROOM before anything else.
    if subject_kind == "room":
        subject_id = str(room_id)
    else:
        raw_id = args.get("subject_id")
        if not raw_id and subject_kind == "reading" and args.get("reading_url"):
            raw_id = await db.fetchval(_READING_BY_URL_SQL, room_id, str(args["reading_url"]).strip())
            if not raw_id:
                return {"ok": False, "error": "no reading in this room has that url"}
        try:
            subject_id = str(UUID(str(raw_id)))
        except (TypeError, ValueError):
            raise ValueError("subject_id must be the row's uuid (or reading_url for a reading)")
    subject = {"entity": entity, "id": subject_id}
    if not await resolve_subject_in_room(db, room_id, subject):
        return {"ok": False, "error": f"that {subject_kind} is not in this room"}

    # Resolve the NAME: the room's own confirmed scopes first (a human drew
    # or chose them), then the Natural Earth marine set.
    room_rows = await db.fetch(_ROOM_SCOPES_SQL, room_id)
    room_by_label = {r["label"].lower(): r for r in room_rows if r["label"]}
    hit = room_by_label.get(region.lower())
    if hit is not None:
        geometry = _jsonb(hit["geometry"])
        kind = hit["kind"] if hit["kind"] in ("polygon", "region", "route", "point") else "region"
        label = hit["label"]
        provenance = {
            "provider": "room_scope",
            "acquisition": "llm",
            "source_id": str(hit["id"]),
            "credit": _jsonb(hit["provenance"]).get("credit", ""),
        }
    else:
        resolved = natural_earth_region(region)
        if resolved is None:
            return {
                "ok": False,
                "error": f"no region named {region!r}",
                "candidates": candidates_for(region, [r["label"] for r in room_rows if r["label"]]),
                "note": "Name one of the candidates exactly, or a scope the room already holds.",
            }
        label, geometry, provenance = resolved
        kind = "region"

    now = datetime.now(timezone.utc)
    expires_at = now + PROPOSAL_TTL
    async with db.transaction():
        scope_id = await insert_scope(
            db, room_id=room_id, subject=subject, kind=kind, geometry=geometry,
            label=label, authority="machine_proposed", provenance=provenance,
            expires_at=expires_at, revision_action="propose", now=now,
        )
        await _record_event(
            db, event_id=uuid4(), now=now, room_id=room_id,
            payload={
                "scope_id": str(scope_id),
                "kind": kind,
                "subject": subject,
                "label": label,
                "authority": "machine_proposed",
                "provenance": provenance,
                "source_state": "ok",
                "observed_at": None,
                "retrieved_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "revision_action": "propose",
                "review_note": None,
                "why": why,
            },
        )
    return {
        "ok": True,
        "scope_id": str(scope_id),
        "label": label,
        "subject": subject,
        "authority": "machine_proposed",
        "expires_at": expires_at.isoformat(),
        "note": (
            "Placed as a PROPOSAL. It renders dashed on the World until a "
            "person confirms it in Focus; until then say so if you cite it."
        ),
    }


PROPOSE_GEO_SCOPE_DESCRIPTION = (
    "Propose WHERE something in this room belongs on the World — attach a "
    "named region to the room's thesis, to a reading, or to a message. Use it "
    "when a reading or a claim is plainly about a place (a strait, a gulf, a "
    "sea, a route the room already drew) so the humans can see it on the "
    "globe beside the rest of the evidence. You never invent coordinates: "
    "`region` must name a Natural Earth marine feature (e.g. 'Persian Gulf', "
    "'Gulf of Oman', 'Red Sea', 'Bab el Mandeb', 'Taiwan Strait') or the "
    "exact label of a scope the room already holds; an unknown name returns "
    "candidates instead of a guess. The result is a PROPOSAL — provisional, "
    "dashed on the map, expiring in 14 days unless a person confirms it — "
    "never an authoritative placement."
)

PROPOSE_GEO_SCOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "region": {
            "type": "string",
            "description": "A Natural Earth marine region name, or the exact label of a scope this room already holds.",
        },
        "subject_kind": {
            "type": "string",
            "enum": ["room", "reading", "message"],
            "description": "What the region is about: the room's thesis as a whole (default), a filed reading, or a message.",
        },
        "subject_id": {
            "type": "string",
            "description": "The reading's or message's uuid. Omit for subject_kind=room.",
        },
        "reading_url": {
            "type": "string",
            "description": "For a reading, its url may stand in for subject_id.",
        },
        "why": {
            "type": "string",
            "description": "One sentence on why this place bears on the subject — recorded with the proposal.",
        },
    },
    "required": ["region"],
}
