"""Real Postgres and HTTP tests for chart fences and the Field-connected ledger."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api import field
from organs.longway import api, fixes, proposals
from tests.test_longway_register import longway_repo, voyage_repo, git, SOURCE

DSN = os.environ.get("DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test")


class Pool:
    def __init__(self, db):
        self.db = db

    @asynccontextmanager
    async def acquire(self):
        yield self.db


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(DSN, timeout=5)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"dialectic_test unavailable: {exc}")
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(typename, schema="pg_catalog", encoder=json.dumps, decoder=json.loads)
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute((Path(__file__).resolve().parents[1] / "migrations/029_longway.sql").read_text())
        await conn.execute((Path(__file__).resolve().parents[1] / "migrations/030_longway_scout.sql").read_text())
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def house(db):
    user, room, thread = uuid4(), uuid4(), uuid4()
    await db.execute("INSERT INTO users(id,created_at,display_name) VALUES ($1,clock_timestamp(),'Alice')",user)
    await db.execute("INSERT INTO user_credentials(user_id,email,password_hash) VALUES ($1,$2,'unused')",user,f"{user}@example.org")
    await db.execute("INSERT INTO rooms(id,created_at,token,name,linked_journey) VALUES ($1,clock_timestamp(),$2,'Ogasawara','ogasawara')",room,str(room))
    await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,clock_timestamp())",room,user)
    await db.execute("INSERT INTO threads(id,room_id,created_at,title) VALUES ($1,$2,clock_timestamp(),'Main')",thread,room)
    return SimpleNamespace(user=AuthenticatedUser(user,f"{user}@example.org",True,"Alice"),room=room,thread=thread,token=str(room),pool=Pool(db))


@pytest_asyncio.fixture
async def home_room(db):
    home = await db.fetchrow("SELECT id,token FROM rooms WHERE is_home")
    if home is None:
        room = uuid4()
        home = await db.fetchrow("""INSERT INTO rooms(id,created_at,token,name,is_home)
            VALUES ($1,clock_timestamp(),$2,'Home',true) RETURNING id,token""", room, str(room))
    return home


@pytest_asyncio.fixture
async def client(db,house):
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(field.router)
    async def connection():
        yield db
    app.dependency_overrides[api.get_db] = connection
    app.dependency_overrides[field.get_db] = connection
    app.dependency_overrides[field.get_pool] = lambda: house.pool
    app.dependency_overrides[get_current_user] = lambda: house.user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test",headers={"X-Room-Token":house.token}) as result:
        yield result


@pytest.mark.asyncio
async def test_chart_projection_and_membership(client,house,db,longway_repo,monkeypatch):
    async def feed(url):
        return {"written":"2026-01-01T00:00:00Z","fixes":{}}
    monkeypatch.setattr(fixes,"fetch_feed",feed)
    response=await client.get(f"/rooms/{house.room}/longway/chart")
    assert response.status_code == 200
    data=response.json()
    assert data["room"] == {"id":str(house.room),"linked_journey":"ogasawara","is_home":False}
    assert len(data["rooms"]) == 1
    assert data["fixes_state"]["stale"] is True
    assert data["vehicles"][0]["fix"] is None and data["vehicles"][0]["heard"] is False
    assert "BOOKING-PRIVATE" not in response.text
    assert (await client.get(f"/rooms/{house.room}/longway/journey/private-trip")).status_code == 404
    assert (await client.post(f"/rooms/{house.room}/longway/bind",json={"slug":"friends-2027"})).status_code == 403
    await db.execute("DELETE FROM room_memberships WHERE room_id=$1",house.room)
    assert (await client.get(f"/rooms/{house.room}/longway/chart")).status_code == 403


@pytest.mark.asyncio
async def test_manager_bind_and_consent(client,house,db,longway_repo,home_room):
    home=home_room["id"]
    await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at,can_manage_home) VALUES ($1,$2,clock_timestamp(),true)",home,house.user.user_id)
    assert (await client.post(f"/rooms/{house.room}/longway/bind",json={"slug":"friends-2027"})).status_code == 200
    assert await db.fetchval("SELECT linked_journey FROM rooms WHERE id=$1",house.room) == "friends-2027"
    consent={"member_id":str(house.user.user_id),"binds":"Research only, no booking", "confirmed_on":"2026-10-28","channel":"in person"}
    response=await client.post(f"/rooms/{house.room}/longway/confirmations",json=consent)
    assert response.status_code == 200
    assert response.json()["recorded_by"] == str(house.user.user_id)
    assert len((await client.get(f"/rooms/{house.room}/longway/confirmations")).json()) == 1
    consent["member_id"]=str(uuid4())
    assert (await client.post(f"/rooms/{house.room}/longway/confirmations",json=consent)).status_code == 422


@pytest.mark.asyncio
async def test_real_repo_contract(monkeypatch):
    from organs.longway.register import Register
    if not SOURCE.exists():
        pytest.skip("Long Way source unavailable")
    chart=Register(SOURCE).chart()
    from organs.longway import observe
    from unittest.mock import AsyncMock
    monkeypatch.setattr(observe, "trains", AsyncMock(return_value=[]))
    # Membership of the live chart changes as journeys and vehicles are registered.
    records = [json.loads(p.read_text()) for kind in ("candidates", "trips")
               for p in (SOURCE / kind).glob("*/record.json")]
    shown = [r for r in records if r["kind"] == "candidate" or r.get("shared") is True]
    assert sorted(j["slug"] for j in chart["journeys"]) == sorted(r["slug"] for r in shown)
    assert sorted((v["journey"], v["name"]) for v in chart["vehicles"]) == sorted(
        (r["slug"], v["name"]) for r in shown for v in r.get("vehicles", []))
    assert next(j for j in chart["journeys"] if j["slug"]=="friends-2027")["kind"] == "trip"
    async def feed(url):
        return {"written":"2026-10-28T00:00:00Z","fixes":{}}
    monkeypatch.setattr(fixes,"fetch_feed",feed)
    projected=await fixes.overlay(chart,datetime(2026,10,28,2,tzinfo=timezone.utc))
    ship=next(v for v in projected["vehicles"] if v["name"]=="Ogasawara Maru")
    assert ship["fix"] is None and ship["heard"] is False
    assert projected["fixes_state"]["stale"] is True


@pytest.mark.asyncio
async def test_voyage_round_trip(client, house, voyage_repo, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    root = voyage_repo.root
    prefix = f"/rooms/{house.room}/longway"
    # The fixture room is linked to Ogasawara. A voyage needs no room of its own.
    monkeypatch.setattr(fixes, "fetch_feed", AsyncMock(return_value={"fixes": {}}))
    chart = (await client.get(f"{prefix}/chart")).json()
    assert next(j for j in chart["journeys"] if j["slug"] == "nile")["voyage"] is True
    page = f"{prefix}/voyage/nile/page?station=aswan"
    original = await client.get(page)
    assert original.status_code == 200 and original.headers["cache-control"] == "no-store"
    assert "Original bank" in original.json()["html"]
    assert 'const HOST = {"embed": true, "station": "aswan"};' in original.json()["html"]
    document = f"{prefix}/document/nile/voyage"
    doc = (await client.get(document)).json()
    assert doc["writable"] and doc["why"] is None and doc["format"] == "json"
    path = "stations/aswan/kicker"
    head = git(root, "rev-parse", "HEAD")
    (root / "other").write_text("already staged")
    git(root, "add", "other")
    edited = await client.post(document, json={"ops": [{"op": "set", "path": path, "value": "A blue sail"}]})
    assert edited.status_code == 200, edited.text
    sha = git(root, "rev-parse", "HEAD")
    assert edited.json() == {"commit": sha, "changed": [path], "summary": path}
    assert git(root, "rev-list", "--count", f"{head}..HEAD") == "1"
    assert git(root, "log", "-1", "--format=%an <%ae>") == f"Alice <{house.user.email}>"
    assert git(root, "log", "-1", "--format=%B") == f"Edit nile voyage: {path}\n\nEdited-In: The Long Way house"
    relative = "candidates/nile/voyage.json"
    assert git(root, "show", "--format=", "--name-only", sha) == relative
    assert json.loads(git(root, "show", f"HEAD:{relative}"))["stations"][0]["kicker"] == "A blue sail"
    assert git(root, "diff", "--cached", "--name-only") == "other"
    fresh = await client.get(page)
    assert fresh.headers["cache-control"] == "no-store"
    assert "A blue sail" in fresh.json()["html"] and "Original bank" not in fresh.json()["html"]


@pytest.mark.asyncio
async def test_house_only_member_edits_candidate_without_a_room(client, house, home_room, db, voyage_repo, monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    home = home_room["id"]
    await db.execute("""UPDATE room_memberships SET room_id=$1, can_manage_home=false
        WHERE room_id=$2 AND user_id=$3""", home, house.room, house.user.user_id)
    memberships = await db.fetch("SELECT room_id,can_manage_home FROM room_memberships WHERE user_id=$1", house.user.user_id)
    assert [tuple(row) for row in memberships] == [(home, False)]
    assert not await db.fetchval("SELECT EXISTS(SELECT 1 FROM rooms WHERE linked_journey='nile')")

    root = voyage_repo.root
    head = git(root, "rev-parse", "HEAD")
    url = f"/rooms/{home}/longway"
    headers = {"X-Room-Token": home_room["token"]}
    page = await client.get(f"{url}/voyage/nile/page", headers=headers)
    assert page.status_code == 200 and "Original bank" in page.json()["html"]
    document = f"{url}/document/nile/voyage"
    response = await client.get(document, headers=headers)
    assert response.status_code == 200 and response.json()["writable"] is True
    assert response.json()["value"]["stations"][0]["kicker"] == "Original bank"
    path = "stations/aswan/kicker"
    edited = await client.post(document, headers=headers, json={"ops": [{"op": "set", "path": path, "value": "From the House"}]})
    assert edited.status_code == 200, edited.text
    assert edited.json()["commit"] == git(root, "rev-parse", "HEAD")
    assert git(root, "rev-list", "--count", f"{head}..HEAD") == "1"
    assert git(root, "log", "-1", "--format=%an <%ae>") == f"Alice <{house.user.email}>"
    assert json.loads(git(root, "show", "HEAD:candidates/nile/voyage.json"))["stations"][0]["kicker"] == "From the House"


@pytest.mark.asyncio
async def test_document_refusals(client, house, voyage_repo, monkeypatch):
    root = voyage_repo.root
    head = git(root, "rev-parse", "HEAD")
    prefix = f"/rooms/{house.room}/longway/document/nile"
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    for name, path, value, reason in (
        ("voyage", "stations/aswan/moment/cite", ["S999"], "voyage.json cites S999, missing from candidates/nile/evidence.jsonl"),
        ("record", "status", "shortlisted", "status is not changed here"),
    ):
        target = root / f"candidates/nile/{name}.json"
        original = target.read_bytes()
        refused = await client.post(f"{prefix}/{name}", json={"ops": [{"op": "set", "path": path, "value": value}]})
        assert refused.status_code == 400 and reason in refused.json()["detail"]
        assert target.read_bytes() == original and git(root, "rev-parse", "HEAD") == head
    target = root / "candidates/nile/voyage.json"
    target.write_bytes(target.read_bytes() + b"  ")
    dirty = target.read_bytes()
    body = {"ops": [{"op": "set", "path": "stations/aswan/kicker", "value": "Changed"}]}
    refused = await client.post(f"{prefix}/voyage", json=body)
    assert refused.status_code == 409 and "uncommitted changes to candidates/nile/voyage.json" in refused.json()["detail"]
    assert target.read_bytes() == dirty and git(root, "rev-parse", "HEAD") == head

    record = root / "candidates/nile/record.json"
    original_record = record.read_bytes()
    record.write_bytes(b'{"title":')
    refused = await client.post(f"{prefix}/record", json={"ops": [{"op": "set", "path": "title", "value": "New"}]})
    assert refused.status_code == 409 and "uncommitted changes to candidates/nile/record.json" in refused.json()["detail"]
    assert record.read_bytes() == b'{"title":' and git(root, "rev-parse", "HEAD") == head
    record.write_bytes(original_record)

    monkeypatch.delenv("LONGWAY_COMMIT_ENABLED")
    target = root / "candidates/nile/dossier.md"
    original = target.read_bytes()
    doc = (await client.get(f"{prefix}/dossier")).json()
    assert doc["writable"] is False and doc["why"] and doc["value"] == original.decode()
    refused = await client.post(f"{prefix}/dossier", json={"text": "Change the pull"})
    assert refused.status_code == 409 and refused.json()["detail"] == doc["why"]
    assert target.read_bytes() == original and git(root, "rev-parse", "HEAD") == head


@pytest.mark.asyncio
async def test_voyage_lookup_and_room_fences(client, house, db, voyage_repo, monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    original = Path.open
    def guard(path, *args, **kwargs):
        if "trips" in path.parts:
            pytest.fail(f"Opened trip file {path}")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guard)
    prefix = f"/rooms/{house.room}/longway"
    for slug in ("friends-2027", "private-trip", "unknown", "ogasawara"):
        page = await client.get(f"{prefix}/voyage/{slug}/page")
        assert page.status_code == 404 and page.json()["detail"] == "Unknown journey"
    for suffix in ("friends-2027/record", "unknown/record", "ogasawara/voyage", "nile/river"):
        url = f"{prefix}/document/{suffix}"
        assert (await client.get(url)).status_code == 404
        assert (await client.post(url, json={"text": "new text"})).status_code == 404
    station = await client.get(f"{prefix}/voyage/nile/page?station=absent")
    assert station.status_code == 400 and "no station 'absent'" in station.json()["detail"]
    # The successful edit must also run its repository-wide check without opening trips.
    url = f"{prefix}/document/nile/dossier"
    assert (await client.post(url, json={"text": "# New dossier"})).status_code == 200
    assert (await client.get(url)).json()["value"] == "# New dossier\n"
    await db.execute("DELETE FROM room_memberships WHERE room_id=$1", house.room)
    expected = (await client.get(f"{prefix}/journey/nile")).json()
    for refusal in (await client.get(f"{prefix}/voyage/nile/page"), await client.get(url),
                    await client.post(url, json={"text": "forbidden"})):
        assert refusal.status_code == 403 and refusal.json() == expected


@pytest.mark.asyncio
async def test_edit_body_contract(client, house, voyage_repo):
    url = f"/rooms/{house.room}/longway/document/nile/record"
    for body in ({}, {"ops": [], "text": "both"}, {"ops": [{}] * 201}, {"text": "x" * 200_001}):
        response = await client.post(url, json=body)
        assert response.status_code == 422 and response.json()["detail"][0]["loc"][0] == "body"
