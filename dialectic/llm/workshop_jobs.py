# llm/workshop_jobs.py — the Workshop's long runs: start now, be summoned when it ends
"""
ARCHITECTURE: `start()` launches the same bubblewrap sandbox `workshop.run`
uses, but detached — stdout/stderr go to files in the run dir, the process
gets its own session, and an in-process watcher task waits for it (up to
JOB_TIMEOUT_MAX_S) and finalises the `workshop_jobs` row. The 60s
`workshop_job_watch` scheduler job then (a) marks running rows whose process
is gone as `lost` (a backend restart kills jobs: bwrap dies with its parent)
and (b) reports every finished-but-unreported job as a forced participant
turn carrying the output and the filed artifacts, exactly the way
world_watch reports a contact.

WHY a ledger row plus a sweep instead of reporting from the watcher: the
report step can fail (model down, room gone) and must be retried; a row with
reported_at NULL is the retry queue, and it survives restarts even though
the process does not. The scheduler's serial tick never runs the job itself
— it only spawns the report turn, bounded by REPORT_PER_TICK.

TRADEOFF: a job holds no per-room lock while it runs (it would block
run_code for hours); the snapshot/commit at finish takes the lock briefly.
A run_code during a job can touch the same files — history is still
complete, ordering is the humans' problem. ponytail: one running job per
room and MAX_RUNNING_PER_HOST on this shared box.
"""

import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from llm import workshop
from llm.documents import bind_documents
from models import Message, MessageType, SpeakerType
from scheduler import Job, SchedulerContext

logger = logging.getLogger(__name__)

JOB_TIMEOUT_DEFAULT_S = 3600
JOB_TIMEOUT_MAX_S = 6 * 3600
MAX_RUNNING_PER_ROOM = 1
MAX_RUNNING_PER_HOST = 3
MAX_LABEL_CHARS = 120
JOB_WATCH_INTERVAL_S = 60
REPORT_PER_TICK = 3
LOST_GRACE_S = 120
REPORT_REASON = "workshop_job_done"
LIVE_TAIL_BYTES = 2_000

_pool: Any = None
_watchers: dict[str, asyncio.Task] = {}


def set_db_pool(pool) -> None:
    """The pool the watcher task finalises through — the tool's own
    connection belongs to a turn that ends long before the job does."""
    global _pool
    _pool = pool


def _status_for(exit_code: Optional[int], timed_out: bool, killed: bool) -> str:
    if killed:
        return "killed"
    if timed_out:
        return "killed"
    return "done" if exit_code == 0 else "failed"


def _tail_file(path: str, limit: int) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            data = fh.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    return ("…" + text) if size > limit else text


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _root_thread_id(db, room_id: UUID) -> UUID:
    row = await db.fetchrow(
        "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1", room_id,
    )
    if row is None:
        raise RuntimeError("room has no thread")
    return row["id"]


async def start(db, room_id: UUID, code: str, *, label: str, language: str = "python",
                timeout_s: Optional[int] = None) -> dict:
    """Launch one detached run and return its ledger row's essentials.
    Raises ValueError on bad input or when a job is already running here."""
    if not (code or "").strip():
        raise ValueError("code is required")
    if len(code) > workshop.MAX_CODE_CHARS:
        raise ValueError(f"code exceeds {workshop.MAX_CODE_CHARS} characters")
    if language not in workshop.LANGUAGES:
        raise ValueError(f"language must be one of {', '.join(workshop.LANGUAGES)}")
    label = (label or "").strip()
    if not label:
        raise ValueError("label is required — one line saying what the job computes")
    label = label[:MAX_LABEL_CHARS]
    try:
        timeout = int(timeout_s) if timeout_s is not None else JOB_TIMEOUT_DEFAULT_S
    except (TypeError, ValueError):
        raise ValueError("timeout_s must be an integer")
    timeout = max(1, min(timeout, JOB_TIMEOUT_MAX_S))

    running_here = await db.fetchval(
        "SELECT count(*) FROM workshop_jobs WHERE room_id = $1 AND status = 'running'", room_id,
    )
    if running_here >= MAX_RUNNING_PER_ROOM:
        row = await db.fetchrow(
            "SELECT label, started_at FROM workshop_jobs WHERE room_id = $1 AND status = 'running' ORDER BY started_at LIMIT 1",
            room_id,
        )
        raise ValueError(f"a job is already running in this room: {row['label']!r} (since {row['started_at']:%H:%M UTC}); wait for it or ask a human to kill it")
    running_host = await db.fetchval("SELECT count(*) FROM workshop_jobs WHERE status = 'running'")
    if running_host >= MAX_RUNNING_PER_HOST:
        raise ValueError(f"the Workshop is busy ({running_host} jobs running across the house); try later")

    thread_id = await _root_thread_id(db, room_id)
    workspace = workshop.workspace_dir(room_id)
    job_id = uuid4()
    run_rel = os.path.join("runs", f"job-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{job_id.hex[:8]}")
    run_dir = os.path.join(workspace, run_rel)
    os.makedirs(run_dir, exist_ok=True)
    entry_name = "main.py" if language == "python" else "main.sh"
    with open(os.path.join(run_dir, entry_name), "w", encoding="utf-8") as fh:
        fh.write(code if code.endswith("\n") else code + "\n")
    entry = (["/opt/venv/bin/python", f"/work/{run_rel}/{entry_name}"] if language == "python"
             else ["/bin/bash", f"/work/{run_rel}/{entry_name}"])

    await db.execute(
        """INSERT INTO workshop_jobs (id, room_id, thread_id, label, language, code, timeout_s, status, run_dir, started_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'running', $8, clock_timestamp())""",
        job_id, room_id, thread_id, label, language, code, timeout, run_rel,
    )
    before = workshop._snapshot(workspace)
    out_fh = open(os.path.join(run_dir, "stdout.log"), "wb")
    err_fh = open(os.path.join(run_dir, "stderr.log"), "wb")
    try:
        proc = await asyncio.create_subprocess_exec(
            *workshop.bwrap_argv(workspace, entry),
            stdin=asyncio.subprocess.DEVNULL, stdout=out_fh, stderr=err_fh,
            start_new_session=True,
        )
    finally:
        out_fh.close()
        err_fh.close()
    await db.execute("UPDATE workshop_jobs SET pid = $2 WHERE id = $1", job_id, proc.pid)
    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
           VALUES ($1, $2, 'workshop_job_started', $3, $4, NULL, $5)""",
        uuid4(), datetime.now(timezone.utc), room_id, thread_id,
        {"job_id": str(job_id), "label": label, "timeout_s": timeout},
    )
    _watchers[str(job_id)] = asyncio.create_task(
        _watch(job_id, room_id, proc, timeout, workspace, run_rel, before), name=f"workshop-job-{job_id.hex[:8]}",
    )
    return {"job_id": str(job_id), "label": label, "language": language, "timeout_s": timeout, "run_dir": run_rel}


async def _watch(job_id: UUID, room_id: UUID, proc, timeout: int, workspace: str, run_rel: str,
                 before: dict) -> None:
    started = time.monotonic()
    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
    duration_ms = int((time.monotonic() - started) * 1000)
    run_dir = os.path.join(workspace, run_rel)
    stdout_tail = workshop._cap(_tail_file(os.path.join(run_dir, "stdout.log"), 64_000), workshop.STDOUT_CAP)
    stderr_tail = workshop._cap(_tail_file(os.path.join(run_dir, "stderr.log"), 32_000), workshop.STDERR_CAP)
    if timed_out:
        stderr_tail = (stderr_tail + f"\n[killed: exceeded timeout_s={timeout}]").strip()
    async with workshop._lock(room_id):
        after = workshop._snapshot(workspace)
        changed = sorted(p for p, sig in after.items() if before.get(p) != sig)
        commit = await workshop._commit(workspace, f"job {run_rel.rsplit('/', 1)[-1]}")
    try:
        async with _pool.acquire() as conn:
            killed_by = await conn.fetchval("SELECT killed_by FROM workshop_jobs WHERE id = $1", job_id)
            status = _status_for(proc.returncode, timed_out, killed_by is not None)
            await conn.execute(
                """UPDATE workshop_jobs
                   SET status = $2, finished_at = clock_timestamp(), exit_code = $3, commit_sha = $4,
                       stdout_tail = $5, stderr_tail = $6, changed_files = $7::jsonb
                   WHERE id = $1""",
                # Lists and dicts go to asyncpg as-is: the pool's jsonb codec
                # serialises them, and a json.dumps here is encoded twice.
                job_id, status, None if timed_out else proc.returncode, commit,
                stdout_tail, stderr_tail, changed,
            )
            await conn.execute(
                """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
                   SELECT $1, $2, 'workshop_job_finished', room_id, thread_id, NULL, $4 FROM workshop_jobs WHERE id = $3""",
                uuid4(), datetime.now(timezone.utc), job_id,
                {"job_id": str(job_id), "status": status, "exit_code": proc.returncode, "duration_ms": duration_ms},
            )
    except Exception:  # noqa: BLE001 — the sweep's lost-pass is the backstop
        logger.exception("Workshop job %s finalise failed", job_id)
    finally:
        _watchers.pop(str(job_id), None)


async def kill(db, room_id: UUID, job_id: UUID, user_id: UUID) -> bool:
    """A human stops a running job. Stamps killed_by first so the watcher
    records `killed` rather than `failed`; the kill itself is SIGKILL on
    the process group. False when no running job matches in this room."""
    row = await db.fetchrow(
        """UPDATE workshop_jobs SET killed_by = $3
           WHERE id = $1 AND room_id = $2 AND status = 'running'
           RETURNING pid""",
        job_id, room_id, user_id,
    )
    if row is None:
        return False
    if row["pid"]:
        try:
            os.killpg(int(row["pid"]), signal.SIGKILL)
        except ProcessLookupError:
            pass
    return True


def _project(row, workspace: Optional[str]) -> dict:
    out = {
        "id": str(row["id"]), "room_id": str(row["room_id"]), "label": row["label"],
        "language": row["language"], "status": row["status"], "timeout_s": row["timeout_s"],
        "started_at": row["started_at"].isoformat(),
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "elapsed_s": int(((row["finished_at"] or datetime.now(timezone.utc)) - row["started_at"]).total_seconds()),
        "exit_code": row["exit_code"], "commit_sha": row["commit_sha"],
        "changed_files": row["changed_files"] if isinstance(row["changed_files"], list) else json.loads(row["changed_files"] or "[]"),
        "result_message_id": str(row["result_message_id"]) if row["result_message_id"] else None,
        "stdout_tail": row["stdout_tail"], "stderr_tail": row["stderr_tail"],
    }
    if row["status"] == "running" and workspace:
        out["stdout_tail"] = _tail_file(os.path.join(workspace, row["run_dir"], "stdout.log"), LIVE_TAIL_BYTES)
    return out


async def get_job(db, room_id: UUID, job_id: UUID) -> Optional[dict]:
    row = await db.fetchrow("SELECT * FROM workshop_jobs WHERE id = $1 AND room_id = $2", job_id, room_id)
    if row is None:
        return None
    return _project(row, workshop.workspace_dir(room_id))


async def list_jobs(db, room_id: UUID, limit: int = 20) -> list[dict]:
    rows = await db.fetch(
        "SELECT * FROM workshop_jobs WHERE room_id = $1 ORDER BY started_at DESC LIMIT $2",
        room_id, max(1, min(limit, 100)),
    )
    workspace = workshop.workspace_dir(room_id) if rows else None
    return [_project(r, workspace) for r in rows]


# ── the sweep ────────────────────────────────────────────────────────

async def mark_lost(conn) -> int:
    rows = await conn.fetch(
        """SELECT id, pid FROM workshop_jobs
           WHERE status = 'running' AND started_at < now() - make_interval(secs => $1)""",
        LOST_GRACE_S,
    )
    lost = [r["id"] for r in rows if str(r["id"]) not in _watchers and not _pid_alive(r["pid"])]
    if lost:
        await conn.execute(
            """UPDATE workshop_jobs SET status = 'lost', finished_at = clock_timestamp(),
                   stderr_tail = COALESCE(stderr_tail, '') || E'\\n[lost: the backend restarted while this job ran]'
               WHERE id = ANY($1::uuid[])""",
            lost,
        )
    return len(lost)


def report_content(job: dict, artifact_names: list[str]) -> str:
    mins, secs = divmod(int(job["elapsed_s"]), 60)
    hours, mins = divmod(mins, 60)
    took = f"{hours}h {mins}m {secs}s" if hours else f"{mins}m {secs}s"
    lines = [
        f"[Workshop job finished] \"{job['label']}\" — status {job['status']}, "
        f"exit {job['exit_code'] if job['exit_code'] is not None else 'none'}, ran {took} of a {job['timeout_s']}s budget.",
    ]
    if artifact_names:
        lines.append("Files produced (attached to your reply): " + ", ".join(artifact_names))
    else:
        lines.append("No files were produced.")
    if job.get("stdout_tail"):
        lines += ["stdout (tail):", job["stdout_tail"].rstrip()]
    if job.get("stderr_tail"):
        lines += ["stderr (tail):", job["stderr_tail"].rstrip()]
    lines.append(
        "Report what it printed — the numbers before the interpretation — and name the attached files. "
        "If it failed or was killed, say so plainly and what you would change. Do not re-run it in this turn."
    )
    return "\n".join(lines)


async def _report_one(ctx: SchedulerContext, conn, row) -> bool:
    from llm.orchestrator import LLMOrchestrator
    from llm.silence_sweep import _load_room_context
    from transport.websocket import MessageTypes, OutboundMessage

    room_id = row["room_id"]
    workspace = workshop.workspace_dir(room_id)
    job = _project(row, None)
    changed = job["changed_files"]
    artifacts = await workshop.file_artifacts(conn, room_id, workspace, changed) if changed else []
    loaded = await _load_room_context(conn, room_id)
    if loaded is None:
        logger.warning("Workshop job %s: room %s has no context to report into", row["id"], room_id)
        return False
    room, thread, users, messages, memories = loaded
    context_message = Message(
        id=uuid4(), thread_id=thread.id,
        sequence=(messages[-1].sequence + 1) if messages else 1,
        created_at=datetime.now(timezone.utc),
        speaker_type=SpeakerType.SYSTEM, user_id=None, message_type=MessageType.TEXT,
        content=report_content(job, [a["original_name"] for a in artifacts]),
    )
    orchestrator = LLMOrchestrator(conn, db_pool=ctx.pool)
    result = await orchestrator.force_response(
        room=room, thread=thread, users=users,
        messages=[*messages, context_message], memories=memories, reason=REPORT_REASON,
    )
    if not (result.triggered and result.response):
        return False
    response = result.response
    bound = await bind_documents(conn, room_id, response.id, [
        {"provenance": {"kind": "workshop", "attachment_ids": [a["id"] for a in artifacts]}},
    ]) if artifacts else []
    await conn.execute(
        """UPDATE messages SET metadata = COALESCE(metadata, '{}'::jsonb)
               || jsonb_build_object('workshop_job', $1::jsonb)
           WHERE id = $2""",
        {"id": job["id"], "label": job["label"], "status": job["status"]}, response.id,
    )
    await conn.execute(
        "UPDATE workshop_jobs SET result_message_id = $2, reported_at = clock_timestamp() WHERE id = $1",
        row["id"], response.id,
    )
    if ctx.broadcast is not None:
        await ctx.broadcast(room_id, OutboundMessage(
            type=MessageTypes.MESSAGE_CREATED,
            payload={
                "id": str(response.id), "thread_id": str(response.thread_id),
                "sequence": response.sequence, "created_at": response.created_at.isoformat(),
                "speaker_type": response.speaker_type.value, "user_id": None, "user_name": "Claude",
                "message_type": response.message_type.value, "content": response.content,
                "model_used": response.model_used,
                "metadata": {"workshop_job": {"id": job["id"], "label": job["label"], "status": job["status"]}},
                "attachments": bound,
            },
        ))
    return True


async def sweep(ctx: SchedulerContext) -> dict:
    """One tick: retire jobs whose process vanished, then report finished ones."""
    async with ctx.pool.acquire() as conn:
        lost = await mark_lost(conn)
        rows = await conn.fetch(
            """SELECT * FROM workshop_jobs
               WHERE status <> 'running' AND reported_at IS NULL
               ORDER BY finished_at ASC LIMIT $1""",
            REPORT_PER_TICK,
        )
        reported = 0
        for row in rows:
            try:
                if await _report_one(ctx, conn, row):
                    reported += 1
            except Exception:  # noqa: BLE001 — next tick retries; the row keeps reported_at NULL
                logger.exception("Workshop job %s report failed", row["id"])
    return {"lost": lost, "reported": reported, "pending": len(rows) - reported}


def register_workshop_jobs(scheduler) -> None:
    scheduler.register(Job(
        "workshop_job_watch", JOB_WATCH_INTERVAL_S, sweep, enabled_env="DIALECTIC_WORKSHOP_ENABLED",
    ))
