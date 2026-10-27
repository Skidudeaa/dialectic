"""start_job — the Workshop's long runs.

Real Postgres (dialectic_test, migration 028) and real bubblewrap where
present: the launch and the watcher's finalisation, the timeout kill, the
human kill, the one-per-room cap, the lost pass after a restart, the report
turn (fake orchestrator; real bind, real row, real broadcast payload), and
the three routes' doors.
"""

import asyncio
import os
import shutil
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

import api.main as main_mod
import api.workshop as workshop_api
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm import workshop, workshop_jobs
from llm.tools import build_registry
from models import Message, MessageType, SpeakerType
from scheduler import Scheduler, SchedulerContext

REAL_VENV = os.path.join(workshop.DEFAULT_ROOT, "venv")
sandbox = pytest.mark.skipif(
    not (shutil.which("bwrap") and shutil.which("prlimit")
         and os.path.isfile(os.path.join(REAL_VENV, "bin", "python"))),
    reason="no bwrap/prlimit or Workshop venv on this host",
)

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)
ROOM = UUID("00000000-0000-4000-8000-00000000b328")
THREAD = UUID("00000000-0000-4000-8000-00000000c328")
USER = UUID("00000000-0000-4000-8000-00000000a328")
MSG = UUID("00000000-0000-4000-8000-00000000d328")


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        return None


class _Pool:
    """The watcher and the sweep acquire from a pool; in a rolled-back test
    that pool must hand back the ONE transaction-bound connection."""

    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


@pytest.fixture
def ws_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DIALECTIC_WORKSHOP_ROOT", str(tmp_path / "workshop"))
    monkeypatch.setenv("DIALECTIC_WORKSHOP_VENV", REAL_VENV)
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    return tmp_path


@pytest_asyncio.fixture
async def pg():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dialectic_test unavailable: {exc}")
    import json
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, now(), 'Job Tester')", USER)
        await conn.execute(
            "INSERT INTO rooms (id, created_at, name, token) VALUES ($1, now(), 'Job Room', 'job-tok')", ROOM)
        await conn.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, now())", ROOM, USER)
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, now(), 'Main')", THREAD, ROOM)
        await conn.execute(
            """INSERT INTO messages (id, thread_id, sequence, created_at, speaker_type, user_id, message_type, content)
               VALUES ($1, $2, 1, now(), 'human', $3, 'text', 'run the sweep please')""",
            MSG, THREAD, USER)
        workshop_jobs.set_db_pool(_Pool(conn))
        yield conn
    finally:
        workshop_jobs.set_db_pool(None)
        workshop_jobs._watchers.clear()
        await tx.rollback()
        await conn.close()


async def _await_watcher(job_id: str, timeout: float = 20.0) -> None:
    task = workshop_jobs._watchers.get(job_id)
    if task is not None:
        await asyncio.wait_for(task, timeout=timeout)


# ── launch, finalise, kill ───────────────────────────────────────────

@sandbox
@pytest.mark.asyncio
async def test_start_runs_detached_and_the_watcher_finalises_the_row(pg, ws_env):
    job = await workshop_jobs.start(pg, ROOM, "print('hello from the job')\nopen('out.csv','w').write('a\\n1\\n')",
                                    label="hello job", timeout_s=30)
    row = await pg.fetchrow("SELECT * FROM workshop_jobs WHERE id = $1", UUID(job["job_id"]))
    assert row["status"] == "running" and row["pid"] and row["label"] == "hello job"
    await _await_watcher(job["job_id"])
    row = await pg.fetchrow("SELECT * FROM workshop_jobs WHERE id = $1", UUID(job["job_id"]))
    assert row["status"] == "done" and row["exit_code"] == 0
    assert row["stdout_tail"] == "hello from the job\n"
    assert row["changed_files"] == ["out.csv"] and row["commit_sha"]
    assert row["reported_at"] is None  # the sweep owes the room its turn
    kinds = await pg.fetch("SELECT event_type FROM events WHERE room_id = $1 ORDER BY timestamp", ROOM)
    assert [r["event_type"] for r in kinds] == ["workshop_job_started", "workshop_job_finished"]


@sandbox
@pytest.mark.asyncio
async def test_timeout_kills_and_records_killed(pg, ws_env):
    job = await workshop_jobs.start(pg, ROOM, "import time\nprint('tick', flush=True)\ntime.sleep(60)",
                                    label="sleeper", timeout_s=2)
    await _await_watcher(job["job_id"])
    row = await pg.fetchrow("SELECT * FROM workshop_jobs WHERE id = $1", UUID(job["job_id"]))
    assert row["status"] == "killed" and row["exit_code"] is None
    assert "tick" in row["stdout_tail"] and "exceeded timeout_s=2" in row["stderr_tail"]


@sandbox
@pytest.mark.asyncio
async def test_a_human_can_stop_a_running_job(pg, ws_env):
    job = await workshop_jobs.start(pg, ROOM, "import time\ntime.sleep(60)", label="to stop", timeout_s=60)
    assert await workshop_jobs.kill(pg, ROOM, UUID(job["job_id"]), USER) is True
    await _await_watcher(job["job_id"])
    row = await pg.fetchrow("SELECT status, killed_by FROM workshop_jobs WHERE id = $1", UUID(job["job_id"]))
    assert row["status"] == "killed" and row["killed_by"] == USER
    assert await workshop_jobs.kill(pg, ROOM, UUID(job["job_id"]), USER) is False  # no longer running


@sandbox
@pytest.mark.asyncio
async def test_one_running_job_per_room(pg, ws_env):
    job = await workshop_jobs.start(pg, ROOM, "import time\ntime.sleep(30)", label="first", timeout_s=30)
    with pytest.raises(ValueError, match="already running"):
        await workshop_jobs.start(pg, ROOM, "print(1)", label="second")
    await workshop_jobs.kill(pg, ROOM, UUID(job["job_id"]), USER)
    await _await_watcher(job["job_id"])


@pytest.mark.asyncio
async def test_start_rejects_bad_input(pg, ws_env):
    with pytest.raises(ValueError):
        await workshop_jobs.start(pg, ROOM, "  ", label="x")
    with pytest.raises(ValueError, match="label"):
        await workshop_jobs.start(pg, ROOM, "print(1)", label="")
    with pytest.raises(ValueError):
        await workshop_jobs.start(pg, ROOM, "print(1)", label="x", language="ruby")
    assert await pg.fetchval("SELECT count(*) FROM workshop_jobs") == 0


# ── the sweep ────────────────────────────────────────────────────────

async def _insert_finished(pg, *, status="done", changed=None, stdout="42\n", age_s=0) -> UUID:
    job_id = uuid4()
    await pg.execute(
        """INSERT INTO workshop_jobs (id, room_id, thread_id, label, language, code, timeout_s, status, run_dir,
                                      started_at, finished_at, exit_code, stdout_tail, changed_files)
           VALUES ($1, $2, $3, 'sweep job', 'python', 'print(42)', 600, $4, 'runs/job-x',
                   now() - make_interval(secs => $5) - interval '90 seconds', now() - make_interval(secs => $5),
                   0, $6, $7::jsonb)""",
        job_id, ROOM, THREAD, status, age_s, stdout, changed or [],
    )
    return job_id


@pytest.mark.asyncio
async def test_mark_lost_retires_a_running_row_whose_process_is_gone(pg, ws_env):
    dead = uuid4()
    await pg.execute(
        """INSERT INTO workshop_jobs (id, room_id, thread_id, label, language, code, timeout_s, status, run_dir, pid, started_at)
           VALUES ($1, $2, $3, 'ghost', 'python', 'x', 60, 'running', 'runs/ghost', 999999, now() - interval '10 minutes')""",
        dead, ROOM, THREAD)
    fresh = uuid4()
    await pg.execute(
        """INSERT INTO workshop_jobs (id, room_id, thread_id, label, language, code, timeout_s, status, run_dir, pid, started_at)
           VALUES ($1, $2, $3, 'young', 'python', 'x', 60, 'running', 'runs/young', 999998, now())""",
        fresh, ROOM, THREAD)
    assert await workshop_jobs.mark_lost(pg) == 1
    rows = {r["id"]: r for r in await pg.fetch("SELECT id, status, stderr_tail FROM workshop_jobs")}
    assert rows[dead]["status"] == "lost" and "restarted" in rows[dead]["stderr_tail"]
    assert rows[fresh]["status"] == "running"  # inside the grace window


class _FakeOrchestrator:
    """Stands in for LLMOrchestrator: records the forced turn's inputs and
    returns a Message that already exists in the table (the bind needs the
    FK to hold)."""
    calls: list[dict] = []

    def __init__(self, conn, db_pool=None):
        self.conn = conn

    async def force_response(self, *, room, thread, users, messages, memories, reason):
        _FakeOrchestrator.calls.append({"reason": reason, "context": messages[-1].content})
        row = await self.conn.fetchrow("SELECT * FROM messages WHERE id = $1", MSG)
        response = Message(
            id=row["id"], thread_id=row["thread_id"], sequence=row["sequence"], created_at=row["created_at"],
            speaker_type=SpeakerType.LLM_PRIMARY, user_id=None, message_type=MessageType.TEXT,
            content="Here is what the sweep found.", model_used="fake",
        )
        return SimpleNamespace(triggered=True, response=response)


@pytest.mark.asyncio
async def test_sweep_reports_a_finished_job_with_its_files_bound(pg, ws_env, monkeypatch):
    import llm.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "LLMOrchestrator", _FakeOrchestrator)
    _FakeOrchestrator.calls.clear()
    ws = workshop.workspace_dir(ROOM)
    with open(os.path.join(ws, "sweep.csv"), "w") as fh:
        fh.write("a\n1\n")
    job_id = await _insert_finished(pg, changed=["sweep.csv"], stdout="p5 86.85\n")
    broadcasts: list = []

    async def broadcast(room_id, msg):
        broadcasts.append((room_id, msg))

    summary = await workshop_jobs.sweep(SchedulerContext(pool=_Pool(pg), broadcast=broadcast))
    assert summary == {"lost": 0, "reported": 1, "pending": 0}
    assert _FakeOrchestrator.calls[0]["reason"] == workshop_jobs.REPORT_REASON
    ctx = _FakeOrchestrator.calls[0]["context"]
    assert '"sweep job"' in ctx and "p5 86.85" in ctx and "sweep.csv" in ctx
    row = await pg.fetchrow("SELECT reported_at, result_message_id FROM workshop_jobs WHERE id = $1", job_id)
    assert row["reported_at"] is not None and row["result_message_id"] == MSG
    att = await pg.fetchrow("SELECT message_id, uploader_user_id, original_name FROM attachments WHERE room_id = $1", ROOM)
    assert att["message_id"] == MSG and att["uploader_user_id"] is None and att["original_name"] == "sweep.csv"
    meta = await pg.fetchval("SELECT metadata FROM messages WHERE id = $1", MSG)
    assert meta["workshop_job"]["id"] == str(job_id)
    assert len(broadcasts) == 1
    payload = broadcasts[0][1].payload
    assert payload["attachments"][0]["original_name"] == "sweep.csv"
    assert payload["metadata"]["workshop_job"]["label"] == "sweep job"
    # Reported once: a second sweep finds nothing owed.
    assert (await workshop_jobs.sweep(SchedulerContext(pool=_Pool(pg), broadcast=broadcast)))["reported"] == 0


@pytest.mark.asyncio
async def test_sweep_keeps_a_job_owed_when_the_turn_does_not_fire(pg, ws_env, monkeypatch):
    import llm.orchestrator as orch_mod

    class _Silent(_FakeOrchestrator):
        async def force_response(self, **kwargs):
            return SimpleNamespace(triggered=False, response=None)

    monkeypatch.setattr(orch_mod, "LLMOrchestrator", _Silent)
    job_id = await _insert_finished(pg)
    summary = await workshop_jobs.sweep(SchedulerContext(pool=_Pool(pg), broadcast=None))
    assert summary["reported"] == 0 and summary["pending"] == 1
    assert await pg.fetchval("SELECT reported_at FROM workshop_jobs WHERE id = $1", job_id) is None


def test_report_content_names_the_numbers_before_the_interpretation():
    text = workshop_jobs.report_content(
        {"label": "GBM sweep", "status": "done", "exit_code": 0, "elapsed_s": 3725, "timeout_s": 7200,
         "stdout_tail": "p5 86.85\n", "stderr_tail": ""}, ["hist.png"],
    )
    assert text.startswith('[Workshop job finished] "GBM sweep" — status done, exit 0, ran 1h 2m 5s')
    assert "hist.png" in text and "p5 86.85" in text and "Do not re-run" in text


def test_scheduler_registration_is_flagged_by_the_workshop_switch():
    scheduler = Scheduler(SchedulerContext(pool=None))
    workshop_jobs.register_workshop_jobs(scheduler)
    job = next(j for j in scheduler.jobs if j.name == "workshop_job_watch")
    assert job.interval_s == workshop_jobs.JOB_WATCH_INTERVAL_S
    assert job.enabled_env == "DIALECTIC_WORKSHOP_ENABLED"


# ── the tool ─────────────────────────────────────────────────────────

@sandbox
@pytest.mark.asyncio
async def test_start_job_tool_returns_job_provenance_and_tells_the_model_to_stop(pg, ws_env):
    room = SimpleNamespace(id=ROOM, linked_book_id=None, trading_config=None)
    tool = build_registry(room, pg).get("start_job")
    assert tool is not None and tool.timeout_s > 10.0
    out = await tool.execute({"code": "print('bg')", "label": "background check", "timeout_s": 30})
    prov = out["provenance"]
    assert prov["kind"] == "workshop_job" and prov["label"] == "background check"
    assert "do not claim results now" in out["status"]
    await _await_watcher(prov["job_id"])
    assert await pg.fetchval("SELECT status FROM workshop_jobs WHERE id = $1", UUID(prov["job_id"])) == "done"


# ── the routes ───────────────────────────────────────────────────────

CALLER = UUID("00000000-0000-4000-8000-00000000a329")
HEADERS = {"X-Room-Token": "room-token"}


def setup_function():
    main_mod.app.dependency_overrides.clear()


def teardown_function():
    main_mod.app.dependency_overrides.clear()


def _client(*, authenticated=True, room=True, member=True) -> TestClient:
    main_mod.app.dependency_overrides.clear()
    db = AsyncMock()

    async def fetchrow(sql, *args):
        if "SELECT 1 FROM rooms" in sql:
            return {"?column?": 1} if room else None
        if "SELECT 1 FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        return None

    db.fetchrow.side_effect = fetchrow

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    main_mod.app.dependency_overrides[workshop_api.get_db] = db_dependency
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=CALLER, email="caller@test", email_verified=True, display_name="Caller")
    return TestClient(main_mod.app)


def test_routes_require_room_token_and_membership(monkeypatch):
    assert _client(room=False).get(f"/rooms/{ROOM}/workshop/jobs", headers=HEADERS).status_code == 401
    assert _client(member=False).get(f"/rooms/{ROOM}/workshop/jobs", headers=HEADERS).status_code == 403
    assert _client(member=False).post(f"/rooms/{ROOM}/workshop/jobs/{uuid4()}/kill", headers=HEADERS).status_code == 403


def test_get_and_kill_route_shapes(monkeypatch):
    job = {"id": str(uuid4()), "status": "running", "label": "x"}
    monkeypatch.setattr(workshop_jobs, "get_job", AsyncMock(return_value=job))
    monkeypatch.setattr(workshop_jobs, "list_jobs", AsyncMock(return_value=[job]))
    killed: list = []

    async def kill(db, room_id, job_id, user_id):
        killed.append((room_id, job_id, user_id))
        return True

    monkeypatch.setattr(workshop_jobs, "kill", kill)
    client = _client()
    assert client.get(f"/rooms/{ROOM}/workshop/jobs", headers=HEADERS).json() == {"jobs": [job]}
    assert client.get(f"/rooms/{ROOM}/workshop/jobs/{job['id']}", headers=HEADERS).json() == job
    res = client.post(f"/rooms/{ROOM}/workshop/jobs/{job['id']}/kill", headers=HEADERS)
    assert res.status_code == 200 and res.json()["killed"] is True
    assert killed == [(ROOM, UUID(job["id"]), CALLER)]  # the caller, never a body-supplied user
    monkeypatch.setattr(workshop_jobs, "kill", AsyncMock(return_value=False))
    assert client.post(f"/rooms/{ROOM}/workshop/jobs/{job['id']}/kill", headers=HEADERS).status_code == 404
