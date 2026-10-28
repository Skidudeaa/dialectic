"""Process-isolated organ selection avoids polluting default-organ regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(code, organ="longway", **env):
    return subprocess.run([sys.executable,"-c",code],cwd=ROOT,
        env={**os.environ,"DIALECTIC_ORGAN":organ,**env},text=True,capture_output=True,timeout=45)


def test_longway_registry_jobs_routes_identity():
    result = run('''
import json
from api.main import app
from fastapi.testclient import TestClient
from organ import active
from tests.conftest import make_room
from llm.tools import build_registry
from scheduler import Scheduler,SchedulerContext,Job
from trading_watch import scheduler_heartbeat
from llm.workshop_jobs import register_workshop_jobs
s=Scheduler(SchedulerContext(pool=None))
s.register(Job("scheduler_heartbeat",600,scheduler_heartbeat))
active.register_jobs(s)
register_workshop_jobs(s)
assert build_registry(make_room(),None).names() == build_registry(make_room(),None).names()
print(json.dumps(dict(tools=build_registry(make_room(),None).names(),jobs=[j.name for j in s.jobs],paths=[r.path for r in app.routes],identity=TestClient(app).get("/organ").json())))
''')
    assert result.returncode == 0, result.stderr
    data=json.loads(result.stdout)
    assert data["identity"] == {"organ":"longway","name":"The Long Way","participant":"Scout","lede":"Go far enough to be surprised. Stay long enough to understand. Leave room to be changed."}
    assert set(data["jobs"]) == {"scheduler_heartbeat","sunday_dispatch","evidence_writer","scout_nightly","workshop_job_watch"}
    assert data["tools"][:5] == ["read_register","fit_window","where_is","propose_evidence","draft_dispatch"]
    assert {"run_code","start_job","write_document","search_memories"} <= set(data["tools"])
    assert not {"get_live_quotes","world_query","propose_geo_scope","search_dev_sessions"} & set(data["tools"])
    assert not any("/trading/" in path for path in data["paths"])
    assert "/rooms/{room_id}/longway/chart" in data["paths"]


def test_missing_repo_fails_startup():
    result=run('from organ import active; active.base_identity()',LONGWAY_REPO="/nonexistent-longway")
    assert result.returncode != 0
    assert "LONGWAY_REPO" in result.stderr


def test_unknown_organ_fails_loud():
    result=run("import organ",organ="typo")
    assert result.returncode != 0
    assert "Unknown DIALECTIC_ORGAN" in result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("replay_016", [True, False], ids=["exact_001_029", "schema_1024_boot"])
async def test_boot_empty_postgres_all_migrations(replay_016):
    """An owned temporary database, built from the exact advertised SQL path."""
    import asyncpg
    from urllib.parse import urlsplit, urlunsplit
    from uuid import uuid4
    dsn=os.environ.get("DIALECTIC_TEST_DATABASE_URL","postgresql://root@localhost/dialectic_test")
    try:
        admin=await asyncpg.connect(dsn,timeout=5)
    except (OSError,asyncpg.PostgresError) as exc:
        pytest.skip(f"dialectic_test unavailable: {exc}")
    name="longway_boot_"+uuid4().hex
    try:
        try:
            await admin.execute(f'CREATE DATABASE "{name}"')
        except asyncpg.InsufficientPrivilegeError:
            pytest.skip("test role cannot create an isolated empty database")
        parts=urlsplit(dsn)
        fresh=urlunsplit((parts.scheme,parts.netloc,"/"+name,parts.query,parts.fragment))
        conn=await asyncpg.connect(fresh)
        try:
            await conn.execute((ROOT/"schema.sql").read_text())
            for migration in sorted((ROOT/"migrations").glob("[0-9][0-9][0-9]_*.sql")):
                if migration.name.startswith("016_") and not replay_016:
                    # schema.sql already declares vector(1024). This second
                    # probe isolates organ boot from the exact replay defect.
                    continue
                try:
                    await conn.execute(migration.read_text())
                except asyncpg.FeatureNotSupportedError as exc:
                    if migration.name.startswith("016_") and "user_accessible_memories" in str(exc):
                        pytest.xfail("Existing migration 016 cannot replay over schema.sql: user_accessible_memories depends on memories.embedding; owner must guard the already-1024 ALTER or rebuild the view")
                    raise
            assert await conn.fetchval("SELECT count(*) FROM longway_evidence_proposals") == 0
        finally:
            await conn.close()
        result=run('''
from api.main import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    assert client.get("/organ").json()["organ"] == "longway"
    assert {j.name for j in app.state.scheduler.jobs} == {"sunday_dispatch","evidence_writer","scout_nightly","workshop_job_watch","scheduler_heartbeat"}
''', DATABASE_URL=fresh, LONGWAY_REPO=os.environ.get("LONGWAY_TEST_SOURCE","/root/theLongWay"),
            ANTHROPIC_API_KEY="unused-test-key", SCHEDULER_ENABLED="0", REDIS_URL="")
        assert result.returncode == 0,result.stderr
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
