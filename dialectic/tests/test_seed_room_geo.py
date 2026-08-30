"""
Tests for deploy/seed_room_geo.py — the manifest-driven geography seeder
that replaced the one-room deploy/seed_hormuz_geo.py script.

Pure-Python: manifest schema validation, geometry resolution for both the
"natural_earth" and "ring" scope shapes, and every real manifest under
deploy/geo/ actually parsing and resolving its Natural Earth names against
the real data file (a typo in a manifest should fail here, in CI, not in
the owner's terminal mid-seed).

Real-Postgres (dialectic_test): dry-run writes nothing; a real run inserts
one geo_scopes row + one GEO_SCOPE_CREATED event per scope; a second real
run against the same manifest inserts zero more rows (idempotent by live
exact label, the same rule the original Hormuz script used).

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/021_geo_scopes.sql
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from deploy.seed_room_geo import ManifestError, build_parser, build_seeds, load_manifest, main
from geo_scopes import validate_geometry

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)
GEO_DIR = Path(__file__).resolve().parents[1] / "deploy" / "geo"


def _manifest(**overrides) -> dict:
    base = {
        "room_id": str(uuid4()),
        "room_name": "Test Room",
        "scopes": [
            {
                "kind": "polygon", "label": "Test Ring (approx.)",
                "ring": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
                "note": "test",
            },
        ],
    }
    base.update(overrides)
    return base


def _write(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


# ---------------------------------------------------------------------------
# manifest schema validation
# ---------------------------------------------------------------------------

def test_load_manifest_accepts_a_well_formed_manifest(tmp_path):
    manifest = load_manifest(_write(tmp_path, _manifest()))
    assert manifest["scopes"][0]["kind"] == "polygon"


@pytest.mark.parametrize("broken,reason", [
    ({"room_name": "x", "scopes": [{}]}, "room_id"),
    ({"room_id": str(uuid4()), "scopes": [{}]}, "room_name"),
    ({"room_id": str(uuid4()), "room_name": "x", "scopes": []}, "non-empty"),
    ({"room_id": "not-a-uuid", "room_name": "x", "scopes": [{}]}, "room_id"),
    ({"room_id": str(uuid4()), "room_name": "x"}, "non-empty"),
])
def test_load_manifest_refuses_bad_top_level_shape(tmp_path, broken, reason):
    with pytest.raises(ManifestError, match=reason):
        load_manifest(_write(tmp_path, broken))


@pytest.mark.parametrize("scope,reason", [
    ({"kind": "hexagon", "label": "x", "ring": [[0, 0], [1, 1]], "note": "n"}, "kind"),
    ({"kind": "polygon", "ring": [[0, 0], [1, 1]], "note": "n"}, "label"),
    ({"kind": "polygon", "label": "x", "ring": [[0, 0], [1, 1]]}, "note"),
    ({"kind": "polygon", "label": "x", "note": "n"}, "exactly one"),
    (
        {"kind": "polygon", "label": "x", "ring": [[0, 0], [1, 1]],
         "natural_earth": "Persian Gulf", "note": "n"},
        "exactly one",
    ),
    ({"kind": "polygon", "label": "x", "natural_earth": 5, "note": "n"}, "string"),
    ({"kind": "polygon", "label": "x", "ring": [[0, 0]], "note": "n"}, "two"),
    ("not-a-dict", "object"),
])
def test_load_manifest_refuses_malformed_scope_entries(tmp_path, scope, reason):
    with pytest.raises(ManifestError, match=reason):
        load_manifest(_write(tmp_path, _manifest(scopes=[scope])))


def test_load_manifest_refuses_an_unreadable_path(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "does-not-exist.json")


def test_load_manifest_refuses_non_object_json(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(ManifestError, match="object"):
        load_manifest(path)


# ---------------------------------------------------------------------------
# geometry resolution
# ---------------------------------------------------------------------------

def test_build_seeds_resolves_a_hand_ring_polygon():
    seed = build_seeds(_manifest())[0]
    assert seed.kind == "polygon"
    assert seed.geometry["type"] == "Polygon"
    assert seed.provenance["provider"] == "human"
    validate_geometry(seed.kind, seed.geometry)  # does not raise


def test_build_seeds_resolves_a_hand_ring_route():
    manifest = _manifest(scopes=[{
        "kind": "route", "label": "Test Lane (approx.)",
        "ring": [[0, 0], [1, 1], [2, 0]], "note": "test",
    }])
    seed = build_seeds(manifest)[0]
    assert seed.geometry["type"] == "LineString"
    assert seed.provenance["provider"] == "human"
    validate_geometry(seed.kind, seed.geometry)


def test_build_seeds_resolves_natural_earth_against_the_real_file():
    manifest = _manifest(scopes=[{
        "kind": "region", "label": "Persian Gulf",
        "natural_earth": "Persian Gulf", "note": "test",
    }])
    seed = build_seeds(manifest)[0]
    assert seed.geometry["type"] == "Polygon"
    assert seed.provenance["provider"] == "natural_earth"
    assert seed.provenance["credit"] == "Made with Natural Earth"
    validate_geometry(seed.kind, seed.geometry)


def test_build_seeds_refuses_an_unknown_natural_earth_name():
    manifest = _manifest(scopes=[{
        "kind": "region", "label": "Nowhere",
        "natural_earth": "Sea of Nowhere", "note": "test",
    }])
    with pytest.raises(ManifestError, match="not in"):
        build_seeds(manifest)


# ---------------------------------------------------------------------------
# every real manifest — the owner's actual seed data
# ---------------------------------------------------------------------------

def _real_manifest_paths() -> list[Path]:
    return sorted(GEO_DIR.glob("*.json"))


def test_five_manifests_exist_one_per_live_trading_room():
    # dialectic/CLAUDE.md's "Live trading rooms" table names five rooms.
    assert len(_real_manifest_paths()) == 5


@pytest.mark.parametrize("path", _real_manifest_paths(), ids=lambda p: p.name)
def test_every_real_manifest_parses_and_every_scope_resolves(path):
    manifest = load_manifest(path)
    UUID(manifest["room_id"])  # already checked by load_manifest; re-assert the type
    seeds = build_seeds(manifest)
    assert seeds, f"{path.name} produced no scopes"
    labels = [seed.label for seed in seeds]
    assert len(labels) == len(set(labels)), f"{path.name} has duplicate labels"
    for seed in seeds:
        clean = validate_geometry(seed.kind, seed.geometry)
        assert clean["type"] in ("Polygon", "LineString")
        assert seed.note


def test_cli_shape_is_manifest_confirmed_by_dry_run():
    ns = build_parser().parse_args([
        "--manifest", "deploy/geo/iran-hormuz.json",
        "--confirmed-by", "00000000-0000-0000-0000-000000000000",
        "--dry-run",
    ])
    assert ns.manifest == Path("deploy/geo/iran-hormuz.json")
    assert ns.confirmed_by == UUID(int=0)
    assert ns.dry_run is True


# ---------------------------------------------------------------------------
# real Postgres: dry-run writes nothing, a real run is idempotent
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    has_table = await conn.fetchval("SELECT to_regclass('geo_scopes')")
    if not has_table:
        await conn.close()
        pytest.skip("migration 021 not applied to the test database")
        return
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def seed_room(db):
    """A committed room + user + membership. Committed, not rolled back:
    deploy/seed_room_geo.py's `main()` opens its OWN `asyncpg.connect`,
    a connection separate from `db`, so a transaction/rollback on `db`
    would be invisible to it. Cleaned up explicitly in the finally."""
    user_id, room_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, 'Seeder')",
        user_id, now,
    )
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, $2, $3, 'Seed Room')",
        room_id, now, f"seed-tok-{room_id}",
    )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
        room_id, user_id, now,
    )
    try:
        yield room_id, user_id
    finally:
        has_scopes = await db.fetchval(
            "SELECT count(*) FROM geo_scopes WHERE room_id = $1", room_id,
        )
        if has_scopes:
            # geo_scopes is append-only (migration 022: DELETE is a DB-level
            # trigger error, not just a convention). Once a real run commits
            # geometry for this synthetic room, the room cannot be deleted —
            # its FK cascade would itself issue a DELETE against geo_scopes,
            # which the database refuses. Left in dialectic_test on purpose:
            # that refusal is exactly what the real-run test is proving.
            return
        await db.execute("DELETE FROM events WHERE room_id = $1", room_id)
        await db.execute("DELETE FROM room_memberships WHERE room_id = $1", room_id)
        await db.execute("DELETE FROM rooms WHERE id = $1", room_id)
        await db.execute("DELETE FROM users WHERE id = $1", user_id)


def _two_scope_manifest(room_id: UUID) -> dict:
    # One hand ring, one Natural Earth region — exercises both resolution
    # paths against the real database in the same run.
    return {
        "room_id": str(room_id),
        "room_name": "Seed Room",
        "scopes": [
            {
                "kind": "polygon", "label": "Test Ring (approx.)",
                "ring": [[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]],
                "note": "test",
            },
            {
                "kind": "region", "label": "Persian Gulf",
                "natural_earth": "Persian Gulf", "note": "test",
            },
        ],
    }


@pytest.mark.asyncio
async def test_dry_run_against_dialectic_test_inserts_nothing(
    db, seed_room, tmp_path, monkeypatch,
):
    room_id, user_id = seed_room
    manifest_path = _write(tmp_path, _two_scope_manifest(room_id))
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)

    await main(manifest_path, user_id, True)

    scope_count = await db.fetchval(
        "SELECT count(*) FROM geo_scopes WHERE room_id = $1", room_id,
    )
    event_count = await db.fetchval(
        "SELECT count(*) FROM events WHERE room_id = $1", room_id,
    )
    assert scope_count == 0
    assert event_count == 0


@pytest.mark.asyncio
async def test_real_run_inserts_rows_and_events_then_repeats_as_a_noop(
    db, seed_room, tmp_path, monkeypatch,
):
    room_id, user_id = seed_room
    manifest_path = _write(tmp_path, _two_scope_manifest(room_id))
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)

    await main(manifest_path, user_id, False, geometry_inspected=True)

    scope_rows = await db.fetch(
        "SELECT label, authority, confirmed_by FROM geo_scopes WHERE room_id = $1",
        room_id,
    )
    event_count = await db.fetchval(
        "SELECT count(*) FROM events WHERE room_id = $1 AND event_type = 'geo_scope_created'",
        room_id,
    )
    assert len(scope_rows) == 2
    assert event_count == 2
    assert {row["label"] for row in scope_rows} == {"Test Ring (approx.)", "Persian Gulf"}
    assert all(row["authority"] == "human_confirmed" for row in scope_rows)
    assert all(row["confirmed_by"] == user_id for row in scope_rows)

    # Second real run against the identical manifest: idempotent by live
    # exact label — zero new rows, zero new events.
    await main(manifest_path, user_id, False, geometry_inspected=True)
    scope_count_2 = await db.fetchval(
        "SELECT count(*) FROM geo_scopes WHERE room_id = $1", room_id,
    )
    event_count_2 = await db.fetchval(
        "SELECT count(*) FROM events WHERE room_id = $1 AND event_type = 'geo_scope_created'",
        room_id,
    )
    assert scope_count_2 == 2
    assert event_count_2 == 2


@pytest.mark.asyncio
async def test_refuses_a_confirmed_by_who_is_not_a_room_member(
    db, seed_room, tmp_path, monkeypatch,
):
    room_id, _user_id = seed_room
    stranger = uuid4()
    manifest_path = _write(tmp_path, _two_scope_manifest(room_id))
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)

    with pytest.raises(SystemExit, match="not a member"):
        await main(manifest_path, stranger, True)

    scope_count = await db.fetchval(
        "SELECT count(*) FROM geo_scopes WHERE room_id = $1", room_id,
    )
    assert scope_count == 0
