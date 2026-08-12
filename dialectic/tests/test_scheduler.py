"""Tests for scheduler.py — bucket math, job gating, tick idempotency."""

import asyncio
import os

import pytest

import scheduler as scheduler_mod
from scheduler import Job, Scheduler, SchedulerContext, bucket_for


class TestBucketFor:
    def test_alignment(self):
        """Buckets align to interval boundaries."""
        b = bucket_for(900, now_epoch=1000000)
        assert int(b.timestamp()) == 999900  # 1000000 // 900 * 900

    def test_same_bucket_within_interval(self):
        """Two calls inside one interval produce the same bucket."""
        assert bucket_for(600, now_epoch=1200) == bucket_for(600, now_epoch=1799)

    def test_new_bucket_after_interval(self):
        assert bucket_for(600, now_epoch=1200) != bucket_for(600, now_epoch=1800)

    def test_utc(self):
        assert bucket_for(60, now_epoch=0).tzinfo is not None


class TestJobEnabled:
    def test_enabled_by_default(self):
        job = Job("x", 60, None)
        assert job.enabled()

    def test_env_gate_off(self, monkeypatch):
        monkeypatch.setenv("MY_JOB_FLAG", "false")
        job = Job("x", 60, None, enabled_env="MY_JOB_FLAG")
        assert not job.enabled()

    def test_env_gate_default_on(self, monkeypatch):
        monkeypatch.delenv("MY_JOB_FLAG", raising=False)
        job = Job("x", 60, None, enabled_env="MY_JOB_FLAG")
        assert job.enabled()


class FakeConn:
    """Ledger-conflict simulator: first insert per (job, bucket) wins."""

    def __init__(self):
        self.ledger = {}
        self.updates = []
        self._next_id = 1

    async def fetchval(self, query, *args):
        if "INSERT INTO scheduled_job_runs" in query:
            key = (args[0], args[1])
            if key in self.ledger:
                return None
            self.ledger[key] = self._next_id
            self._next_id += 1
            return self.ledger[key]
        if "pg_try_advisory_lock" in query:
            return True
        return None

    async def execute(self, query, *args):
        self.updates.append(args)


class ReleasedConn(FakeConn):
    """Connection proxy invalidated by a database restart."""

    async def fetchval(self, query: str, *args: object) -> object:
        if "INSERT INTO scheduled_job_runs" in query:
            raise RuntimeError("connection has been released back to the pool")
        return await super().fetchval(query, *args)


class AcquireContext:
    def __init__(self, conn: FakeConn):
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, *_args: object) -> bool:
        return False


class SequentialPool:
    def __init__(self, connections: list[FakeConn]):
        self.connections = connections
        self.acquire_count = 0

    def acquire(self) -> AcquireContext:
        conn = self.connections[self.acquire_count]
        self.acquire_count += 1
        return AcquireContext(conn)


class TestTickIdempotency:
    @pytest.mark.asyncio
    async def test_job_runs_once_per_bucket(self):
        runs = []

        async def job_fn(ctx):
            runs.append(1)
            return {"ok": True}

        sched = Scheduler(SchedulerContext(pool=None))
        sched.register(Job("j1", 3600, job_fn))
        conn = FakeConn()
        await sched._tick(conn)
        await sched._tick(conn)  # same bucket — must not run again
        assert len(runs) == 1
        # Ledger updated with success exactly once
        assert len(conn.updates) == 1
        assert conn.updates[0][1] == "success"

    @pytest.mark.asyncio
    async def test_job_error_recorded_not_raised(self):
        async def bad_job(ctx):
            raise RuntimeError("boom")

        sched = Scheduler(SchedulerContext(pool=None))
        sched.register(Job("j2", 3600, bad_job))
        conn = FakeConn()
        await sched._tick(conn)  # must not raise
        assert conn.updates[0][1] == "error"
        assert "boom" in str(conn.updates[0][2])

    @pytest.mark.asyncio
    async def test_disabled_job_skipped(self, monkeypatch):
        monkeypatch.setenv("J3_FLAG", "0")
        runs = []

        async def job_fn(ctx):
            runs.append(1)

        sched = Scheduler(SchedulerContext(pool=None))
        sched.register(Job("j3", 3600, job_fn, enabled_env="J3_FLAG"))
        conn = FakeConn()
        await sched._tick(conn)
        assert runs == []
        assert conn.ledger == {}


class TestSchedulerRecovery:
    @pytest.mark.asyncio
    async def test_reacquires_after_ledger_connection_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        healthy_conn = FakeConn()
        pool = SequentialPool([ReleasedConn(), healthy_conn])
        runs: list[int] = []

        async def job_fn(_ctx: SchedulerContext) -> dict[str, bool]:
            runs.append(1)
            return {"ok": True}

        async def fake_sleep(delay: float) -> None:
            if delay == 60:
                return
            raise asyncio.CancelledError

        monkeypatch.setenv("SCHEDULER_ENABLED", "1")
        monkeypatch.setattr(scheduler_mod.asyncio, "sleep", fake_sleep)

        sched = Scheduler(SchedulerContext(pool=pool))
        sched.register(Job("recoverable", 60, job_fn))

        with pytest.raises(asyncio.CancelledError):
            await sched.run()

        assert pool.acquire_count == 2
        assert runs == [1]
        assert len(healthy_conn.updates) == 1
