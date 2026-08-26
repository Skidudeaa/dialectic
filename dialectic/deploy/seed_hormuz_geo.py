"""
Seed the Iran/Hormuz Trading Room's first geography (World Lens, Phase 0).

Four human_confirmed scopes, all with the room itself as subject:
  1. Strait of Hormuz — a hand-authored polygon (approximate, ~the water
     between the Musandam peninsula and the Iranian coast, Qeshm to the
     Gulf of Oman approaches).
  2. Hormuz traffic-separation lane, inbound (approximate hand-authored
     route through the TSS toward the Gulf).
  3. Persian Gulf — the Natural Earth marine polygon (public domain).
  4. Gulf of Oman — the Natural Earth marine polygon (public domain).

The hand-authored shapes are labelled "(approx.)" in their own label and
say so in provenance.credit — they are a founder's sketch of where the
argument happens, not a chart. Redrawing later is an append-only POST to
/rooms/{id}/geo/{scope_id}/redraw; this script never UPDATEs anything.

Reviewed operator script — run manually, never automatically, as the
founder who is confirming the geometry (their user id is stamped as
confirmed_by, per the CHECK `confirmed_iff_human`):
  /usr/bin/python3 deploy/seed_hormuz_geo.py --confirmed-by <user uuid> \
    --geometry-inspected-by-named-human [--dry-run]

Idempotent: a live scope in the room with the same label is left alone.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geo_scopes import insert_scope, live_predicate, validate_geometry  # noqa: E402
from models import EventType  # noqa: E402

ROOM = UUID("56ba2f1e-5c70-4290-a77d-52404f0095da")  # Iran/Hormuz Trading Room
DATABASE_URL = "postgresql://root@localhost/dialectic"
MARINE = Path(__file__).resolve().parents[1] / "data" / "natural_earth" / "marine.json"

# [lon, lat], closed ring. Approximate, hand-authored (see module docstring).
STRAIT_RING = [
    [55.60, 26.05], [56.20, 25.60], [57.20, 25.85], [57.05, 26.85],
    [56.35, 27.20], [55.60, 26.70], [55.60, 26.05],
]
# Inbound lane of the TSS, west→east read from the Gulf side: approximate.
INBOUND_LANE = [
    [55.30, 26.42], [56.00, 26.58], [56.50, 26.60], [56.90, 26.35],
    [57.40, 25.75],
]

HUMAN = {
    "provider": "human",
    "acquisition": "human",
    "credit": "Hand-authored sketch by a Dialectic founder — approximate, not a chart.",
}


def _natural_earth(name: str) -> tuple[dict, dict]:
    pack = json.loads(MARINE.read_text())
    meta = pack["meta"]
    matches = [f for f in pack["features"] if f["name"] == name]
    if not matches:
        raise SystemExit(f"{name!r} not in {MARINE}")
    # Largest polygon by vertex count when a feature is a multipolygon.
    ring = max((p for f in matches for p in f["polygons"]), key=len)
    closed = [list(p) for p in ring] + [list(ring[0])]
    geometry = {"type": "Polygon", "coordinates": [closed]}
    provenance = {
        "provider": "natural_earth",
        "acquisition": "human",
        "source_id": name,
        "url": meta.get("url"),
        "credit": "Made with Natural Earth",
    }
    return geometry, provenance


SEEDS = [
    ("polygon", "Strait of Hormuz (approx.)",
     {"type": "Polygon", "coordinates": [STRAIT_RING]}, HUMAN),
    ("route", "Hormuz TSS inbound lane (approx.)",
     {"type": "LineString", "coordinates": INBOUND_LANE}, HUMAN),
    ("region", "Persian Gulf", *_natural_earth("Persian Gulf")),
    ("region", "Gulf of Oman", *_natural_earth("Gulf of Oman")),
]


async def main(
    confirmed_by: UUID, dry_run: bool, *, geometry_inspected: bool,
) -> None:
    if not geometry_inspected:
        raise SystemExit(
            "refusing: acknowledge that the named human inspected the geometry",
        )
    conn = await asyncpg.connect(DATABASE_URL)
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    try:
        member = await conn.fetchval(
            "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
            ROOM, confirmed_by,
        )
        if not member:
            raise SystemExit(f"{confirmed_by} is not a member of the Hormuz room; refusing")
        subject = {"entity": "rooms", "id": str(ROOM)}
        now = datetime.now(timezone.utc)
        async with conn.transaction():
            for kind, label, geometry, provenance in SEEDS:
                exists = await conn.fetchval(
                    f"SELECT 1 FROM geo_scopes g WHERE g.room_id = $1 AND g.label = $2 AND {live_predicate('g')}",
                    ROOM, label,
                )
                if exists:
                    print(f"skip (live): {label}")
                    continue
                if dry_run:
                    print(f"would insert: {kind} {label} ({len(json.dumps(geometry))} bytes)")
                    continue
                clean_geometry = validate_geometry(kind, geometry)
                scope_id = await insert_scope(
                    conn, room_id=ROOM, subject=subject, kind=kind,
                    geometry=clean_geometry, label=label, authority="human_confirmed",
                    provenance=provenance, confirmed_by=confirmed_by,
                    created_by=confirmed_by, revision_action="place", now=now,
                )
                await conn.execute(
                    """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
                       VALUES ($1, $2, $3, $4, NULL, $5, $6)""",
                    uuid4(), now, EventType.GEO_SCOPE_CREATED.value, ROOM, confirmed_by,
                    {
                        "scope_id": str(scope_id), "kind": kind,
                        "subject": subject, "label": label,
                        "geometry": clean_geometry,
                        "authority": "human_confirmed",
                        "provenance": provenance, "source_state": "ok",
                        "observed_at": None, "retrieved_at": now.isoformat(),
                        "expires_at": None, "revision_action": "place",
                        "review_note": None,
                        "seed": "deploy/seed_hormuz_geo.py",
                    },
                )
                print(f"inserted: {kind} {label} -> {scope_id}")
            if dry_run:
                raise _Rollback
    except _Rollback:
        print("dry run: rolled back")
    finally:
        await conn.close()


class _Rollback(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmed-by", type=UUID, required=True)
    parser.add_argument(
        "--geometry-inspected-by-named-human",
        action="store_true",
        required=True,
        help="Acknowledge that --confirmed-by names the human who inspected every geometry.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(main(
        args.confirmed_by, args.dry_run,
        geometry_inspected=args.geometry_inspected_by_named_human,
    ))
