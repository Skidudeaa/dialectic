"""
Scheduler — the missing organ.

ARCHITECTURE: One asyncio task started in the FastAPI lifespan. A Postgres
advisory lock makes it single-instance-safe; a (job_name, scheduled_for)
UNIQUE ledger makes it restart-safe. Jobs are registered declaratively and
run when their interval bucket has no ledger row yet.

WHY: Dialectic had NO timer anywhere — nothing could notice a quiet room, a
stale feed, or a morning. The 64-day-stale trading data happened because
every clock was manual. This scheduler is built to the Q3 plan Phase 3 spec
(pulled forward by the fusion amendment); night-shift and brief jobs will
register on this same scaffold.

TRADEOFF: Interval buckets (floor(epoch/interval)) mean a job that was down
for a whole bucket runs at most once when it comes back (Persistent
semantics via the current bucket only — we deliberately do NOT backfill
missed buckets; for watch-style jobs, running the latest is correct and
replaying the past is noise).

DAILY JOBS: a Job with daily_at/daily_tz ignores interval buckets; the tick
computes today's wall-clock slot via stdlib zoneinfo (DST-correct) and uses
it as the ledger key — the same UNIQUE(job_name, scheduled_for) row gives
exactly-once-per-day across restarts, and a server down through the slot
runs it once when it comes back.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = "dialectic-scheduler"
TICK_SECONDS = 30


@dataclass
class SchedulerContext:
    """What jobs get to work with.

    WHY: jobs must not import api.main (circular); the lifespan hands in the
    pool and a broadcast callable as closures instead.
    """
    pool: object  # asyncpg.Pool
    broadcast: Optional[Callable[..., Awaitable[None]]] = None
    # Optional connection manager for push-recipient filtering (jobs that
    # web-push skip users with an active WS to the room). None = push all.
    connection_manager: Optional[object] = None


@dataclass
class Job:
    name: str
    interval_s: int
    func: Callable[[SchedulerContext], Awaitable[Optional[dict]]]
    # Optional env var that must not be "0"/"false" for the job to run.
    enabled_env: Optional[str] = None
    # Wall-clock daily jobs: "07:00" in daily_tz (e.g. "America/Chicago")
    # instead of interval buckets. interval_s is unused when daily_at is set.
    daily_at: Optional[str] = None
    daily_tz: Optional[str] = None

    def enabled(self) -> bool:
        if not self.enabled_env:
            return True
        val = os.environ.get(self.enabled_env, "1").strip().lower()
        return val not in ("0", "false", "no", "off")


def bucket_for(interval_s: int, now_epoch: Optional[float] = None) -> datetime:
    """Interval-aligned bucket timestamp (pure — unit tested)."""
    epoch = time.time() if now_epoch is None else now_epoch
    aligned = int(epoch) // interval_s * interval_s
    return datetime.fromtimestamp(aligned, tz=timezone.utc)


def daily_for(
    daily_at: str,
    daily_tz: str,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Today's slot for a wall-clock daily job (UTC), or None if not due yet.

    Pure given `now` — unit tested, including across DST boundaries. The
    returned instant is the ledger key: stable for the whole day once the
    slot has passed, so restarts cannot double-run the job.
    """
    tz = ZoneInfo(daily_tz)
    now_utc = now or datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)
    hour, minute = (int(part) for part in daily_at.split(":"))
    slot = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now < slot:
        return None
    return slot.astimezone(timezone.utc)


class Scheduler:
    def __init__(self, ctx: SchedulerContext):
        self.ctx = ctx
        self.jobs: list[Job] = []
        self._task: Optional[asyncio.Task] = None

    def register(self, job: Job) -> None:
        self.jobs.append(job)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="dialectic-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run(self) -> None:
        enabled = os.environ.get("SCHEDULER_ENABLED", "1").strip().lower()
        if enabled in ("0", "false", "no", "off"):
            logger.info("Scheduler disabled via SCHEDULER_ENABLED")
            return

        # Dedicated connection held for the process lifetime: session-level
        # advisory lock releases automatically when the connection closes,
        # so a crashed process can never wedge the lock.
        while True:
            try:
                async with self.ctx.pool.acquire() as conn:
                    got = await conn.fetchval(
                        "SELECT pg_try_advisory_lock(hashtext($1))",
                        ADVISORY_LOCK_KEY,
                    )
                    if not got:
                        logger.info("Scheduler lock held elsewhere; retrying in 60s")
                        await asyncio.sleep(60)
                        continue
                    logger.info(
                        "Scheduler running: %s",
                        ", ".join(f"{j.name}@{j.interval_s}s" for j in self.jobs),
                    )
                    try:
                        while True:
                            await self._tick(conn)
                            await asyncio.sleep(TICK_SECONDS)
                    finally:
                        # Best-effort unlock; connection release covers crashes.
                        try:
                            await conn.fetchval(
                                "SELECT pg_advisory_unlock(hashtext($1))",
                                ADVISORY_LOCK_KEY,
                            )
                        except Exception:
                            pass
            except asyncio.CancelledError:
                logger.info("Scheduler stopped")
                raise
            except Exception:
                logger.exception("Scheduler loop error; restarting in 60s")
                await asyncio.sleep(60)

    async def _tick(self, conn) -> None:
        for job in self.jobs:
            if not job.enabled():
                continue
            if job.daily_at:
                slot = daily_for(job.daily_at, job.daily_tz or "UTC")
                if slot is None:
                    continue  # today's slot hasn't arrived yet
                bucket = slot
            else:
                bucket = bucket_for(job.interval_s)
            try:
                won = await conn.fetchval(
                    """INSERT INTO scheduled_job_runs (job_name, scheduled_for)
                       VALUES ($1, $2)
                       ON CONFLICT (job_name, scheduled_for) DO NOTHING
                       RETURNING id""",
                    job.name, bucket,
                )
            except Exception:
                logger.exception("Ledger insert failed for %s", job.name)
                continue
            if won is None:
                continue  # this bucket already ran (or is running) somewhere

            status, detail = "success", None
            try:
                detail = await job.func(self.ctx)
            except Exception as e:
                logger.exception("Job %s failed", job.name)
                status, detail = "error", {"error": str(e)[:500]}
            try:
                await conn.execute(
                    """UPDATE scheduled_job_runs
                       SET finished_at = now(), status = $2, detail = $3
                       WHERE id = $1""",
                    won, status, detail,
                )
            except Exception:
                logger.exception("Ledger update failed for %s", job.name)
