"""
Seed a trading room's first geography (World Lens), from a manifest.

Generalises the original `seed_hormuz_geo.py` (kept as a one-manifest thin
wrapper): every room gets the SAME writer, the same idempotency rule, and
the same event. Only the geometry differs, and the geometry now lives in
`deploy/geo/<room>.json` instead of in the script body.

Manifest shape (see `deploy/geo/*.json`):
    {
      "room_id": "<uuid>", "room_name": "<label, informational only>",
      "scopes": [
        {"kind": "region"|"polygon"|"route"|"point", "label": "...",
         "natural_earth": "<exact name in data/natural_earth/marine.json>",
         "note": "..."},
        {"kind": "polygon", "label": "... (approx.)",
         "ring": [[lon, lat], ...],  # closed ring for polygon/region;
                                      # open LineString-shaped for route
         "note": "..."}
      ]
    }
Exactly one of "natural_earth" / "ring" per scope. A Natural Earth name is
resolved the same way the Hormuz script always resolved one: the largest
ring of the matching feature(s), by vertex count. A hand ring is used as-is
— `geo_scopes.validate_geometry` is the one place ring closure and vertex
bounds are enforced, so this module does not re-implement that check.

Every scope carries `authority="human_confirmed"` with the CLI's
`--confirmed-by` as the confirming human — this script does not decide
geography, it types in what a person has already reviewed. Idempotent: a
live scope in the room with the same label is left alone (matches
`geo_scopes.live_predicate`). This script never UPDATEs anything; redrawing
later is an ordinary POST to `/rooms/{id}/geo/{scope_id}/redraw`.

Reviewed operator script — run manually, never automatically, as the
founder who is confirming the geometry (their user id is stamped as
confirmed_by, per the CHECK `confirmed_iff_human`):

    cd dialectic && python3 deploy/seed_room_geo.py \\
        --manifest deploy/geo/iran-hormuz.json \\
        --confirmed-by <user uuid> [--dry-run]

`DATABASE_URL` env var overrides the default (production) DSN — point it at
`dialectic_test` for a real, non-production run.
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional
from uuid import UUID, uuid4

import asyncpg
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
# WHY only as a script: importing this module from a test must not pull the
# host's .env into the process -- it set QUESTIONS_PER_ROUND=3 under
# test_question_round.py's nose (found 2026-08-30). The house rule ("load
# .env before importing provider code") is about the CLI run, and that is
# the only path that takes it.
if __name__ == "__main__":
    load_dotenv(_REPO_ROOT / ".env")

from geo_scopes import GEO_KINDS, insert_scope, live_predicate, validate_geometry  # noqa: E402
from models import EventType  # noqa: E402

DEFAULT_DATABASE_URL = "postgresql://root@localhost/dialectic"
MARINE = _REPO_ROOT / "data" / "natural_earth" / "marine.json"

HUMAN_PROVENANCE = {
    "provider": "human",
    "acquisition": "human",
    "credit": "Hand-authored sketch by a Dialectic founder — approximate, not a chart.",
}


class ManifestError(ValueError):
    """A manifest file failed schema validation."""


class Seed(NamedTuple):
    kind: str
    label: str
    geometry: dict
    provenance: dict
    note: str


# --- manifest parsing + validation -----------------------------------------

def load_manifest(path: Path) -> dict:
    """Parse and schema-validate a manifest. Raises ManifestError with a
    reason a human running this by hand can act on."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path}: not readable JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: manifest must be a JSON object")
    room_id = raw.get("room_id")
    try:
        UUID(str(room_id))
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{path}: room_id must be a UUID, got {room_id!r}") from exc
    if not raw.get("room_name"):
        raise ManifestError(f"{path}: room_name is required (informational, for the printed log)")
    scopes = raw.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise ManifestError(f"{path}: scopes must be a non-empty list")
    for i, scope in enumerate(scopes):
        _validate_scope_entry(path, i, scope)
    return raw


def _validate_scope_entry(path: Path, index: int, scope: Any) -> None:
    where = f"{path}: scopes[{index}]"
    if not isinstance(scope, dict):
        raise ManifestError(f"{where}: must be an object")
    kind = scope.get("kind")
    if kind not in GEO_KINDS:
        raise ManifestError(f"{where}: kind must be one of {GEO_KINDS}, got {kind!r}")
    if not scope.get("label"):
        raise ManifestError(f"{where}: label is required")
    if not scope.get("note"):
        raise ManifestError(f"{where}: note is required (first-pass provenance for the human reviewer)")
    has_ne = "natural_earth" in scope
    has_ring = "ring" in scope
    if has_ne == has_ring:
        raise ManifestError(f"{where}: exactly one of natural_earth/ring is required")
    if has_ne and not isinstance(scope["natural_earth"], str):
        raise ManifestError(f"{where}: natural_earth must be a string")
    if has_ring and not (isinstance(scope["ring"], list) and len(scope["ring"]) >= 2):
        raise ManifestError(f"{where}: ring must be a list of at least two [lon, lat] positions")


# --- geometry resolution -----------------------------------------------------

def _natural_earth(name: str, marine: Path = MARINE) -> tuple[dict, dict]:
    """The largest ring (by vertex count) of the Natural Earth feature named
    `name`, verbatim from the Hormuz script — this is the one resolution
    rule every manifest entry with a `natural_earth` key relies on."""
    pack = json.loads(marine.read_text())
    meta = pack["meta"]
    matches = [f for f in pack["features"] if f["name"] == name]
    if not matches:
        raise ManifestError(f"{name!r} not in {marine}")
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


def build_seeds(manifest: dict, marine: Path = MARINE) -> list[Seed]:
    """Resolve every manifest scope entry into a Seed. Geometry SHAPE is
    validated here only enough to build a GeoJSON object of the right type;
    `geo_scopes.validate_geometry` (called at insert time, dry-run or not)
    is the actual bounds/closure check — one rule, not two copies of it."""
    seeds = []
    for scope in manifest["scopes"]:
        kind = scope["kind"]
        label = scope["label"]
        note = scope["note"]
        if "natural_earth" in scope:
            geometry, provenance = _natural_earth(scope["natural_earth"], marine)
        else:
            ring = scope["ring"]
            if kind == "route":
                geometry = {"type": "LineString", "coordinates": ring}
            else:
                geometry = {"type": "Polygon", "coordinates": [ring]}
            provenance = HUMAN_PROVENANCE
        seeds.append(Seed(kind, label, geometry, provenance, note))
    return seeds


class _Rollback(Exception):
    pass


async def main(
    manifest_path: Path, confirmed_by: UUID, dry_run: bool,
    *, geometry_inspected: bool = False,
) -> None:
    # WHY the acknowledgement: this script writes `human_confirmed` rows --
    # the top of the authority ladder -- from rings a machine or a builder
    # drew. The flag is the named human saying they LOOKED at the geometry,
    # not just at the labels. A dry run needs no such claim.
    if not dry_run and not geometry_inspected:
        raise SystemExit(
            "refusing to write human_confirmed geometry without "
            "--geometry-inspected-by-named-human",
        )
    manifest = load_manifest(manifest_path)
    room_id = UUID(str(manifest["room_id"]))
    room_name = manifest["room_name"]
    seeds = build_seeds(manifest)

    dsn = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    conn = await asyncpg.connect(dsn)
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    try:
        member = await conn.fetchval(
            "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
            room_id, confirmed_by,
        )
        if not member:
            raise SystemExit(
                f"{confirmed_by} is not a member of {room_name} ({room_id}); refusing",
            )
        subject = {"entity": "rooms", "id": str(room_id)}
        now = datetime.now(timezone.utc)
        async with conn.transaction():
            for kind, label, geometry, provenance, note in seeds:
                exists = await conn.fetchval(
                    f"SELECT 1 FROM geo_scopes g WHERE g.room_id = $1 AND g.label = $2 AND {live_predicate('g')}",
                    room_id, label,
                )
                if exists:
                    print(f"skip (live): {label}")
                    continue
                if dry_run:
                    print(f"would insert: {kind} {label} ({len(json.dumps(geometry))} bytes)")
                    continue
                clean_geometry = validate_geometry(kind, geometry)
                scope_id = await insert_scope(
                    conn, room_id=room_id, subject=subject, kind=kind,
                    geometry=clean_geometry, label=label, authority="human_confirmed",
                    provenance=provenance, confirmed_by=confirmed_by,
                    created_by=confirmed_by, revision_action="place", now=now,
                )
                await conn.execute(
                    """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
                       VALUES ($1, $2, $3, $4, NULL, $5, $6)""",
                    uuid4(), now, EventType.GEO_SCOPE_CREATED.value, room_id, confirmed_by,
                    {
                        "scope_id": str(scope_id), "kind": kind,
                        "subject": subject, "label": label,
                        "geometry": clean_geometry,
                        "authority": "human_confirmed",
                        "provenance": provenance, "source_state": "ok",
                        "observed_at": None, "retrieved_at": now.isoformat(),
                        "expires_at": None, "revision_action": "place",
                        "review_note": note,
                        "seed": f"deploy/seed_room_geo.py --manifest {manifest_path.name}",
                    },
                )
                print(f"inserted: {kind} {label} -> {scope_id}")
            if dry_run:
                raise _Rollback
    except _Rollback:
        print("dry run: rolled back")
    finally:
        await conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--confirmed-by", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--geometry-inspected-by-named-human", action="store_true",
        help="required for a real run: the confirming human has looked at every ring",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(main(
        args.manifest, args.confirmed_by, args.dry_run,
        geometry_inspected=args.geometry_inspected_by_named_human,
    ))
