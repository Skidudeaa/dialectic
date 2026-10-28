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
from tests.test_longway_register import longway_repo, SOURCE

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
async def test_manager_bind_and_consent(client,house,db,longway_repo):
    home=await db.fetchval("SELECT id FROM rooms WHERE is_home")
    if home is None:
        home=uuid4()
        await db.execute("INSERT INTO rooms(id,created_at,token,name,is_home) VALUES ($1,clock_timestamp(),$2,'Home',true)",home,str(home))
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
    assert len(chart["journeys"]) == 19
    assert len(chart["vehicles"]) == 25
    assert next(j for j in chart["journeys"] if j["slug"]=="friends-2027")["kind"] == "trip"
    async def feed(url):
        return {"written":"2026-10-28T00:00:00Z","fixes":{}}
    monkeypatch.setattr(fixes,"fetch_feed",feed)
    projected=await fixes.overlay(chart,datetime(2026,10,28,2,tzinfo=timezone.utc))
    ship=next(v for v in projected["vehicles"] if v["name"]=="Ogasawara Maru")
    assert ship["fix"] is None and ship["heard"] is False
    assert projected["fixes_state"]["stale"] is True
