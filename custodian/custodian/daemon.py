"""Deterministic scheduling; quiet time is admission policy, never evidence."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from .config import Config, Job
from .engine import CustodianError


def foreground_active(engine):
    with (engine.state / "foreground.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def git_busy(engine):
    directory = Path(engine.source_git(engine.repo, "rev-parse", "--absolute-git-dir").decode().strip())
    common = Path(engine.source_git(engine.repo, "rev-parse", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        common = engine.repo / common
    return any((root / path).exists() for root in (directory, common) for path in
               ("index.lock", "HEAD.lock", "MERGE_HEAD", "rebase-merge", "rebase-apply",
                "CHERRY_PICK_HEAD", "REVERT_HEAD", "packed-refs.lock"))


def fingerprint(engine):
    """Cheap scheduling observation: names and metadata, not a verification hash."""
    digest = hashlib.sha256()
    digest.update(engine.source_git(engine.repo, "rev-parse", "HEAD"))
    names = engine.source_git(engine.repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    for raw in sorted(set(names.split(b"\0")) - {b""}):
        digest.update(raw + b"\0")
        try:
            info = (engine.repo / os.fsdecode(raw)).lstat()
            digest.update(str((info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)).encode())
        except FileNotFoundError:
            digest.update(b"missing")
    return digest.hexdigest()


class Daemon:
    def __init__(self, engine, config: Config, *, stop=None, on_failure=None,
                 clock=time.monotonic, wall_clock=time.time):
        self.engine, self.config = engine, config
        self.stop = stop or (lambda: False)
        self.clock, self.wall_clock = clock, wall_clock
        self.previous = None
        self.changed_at = self.clock()
        self.snapshot = None
        self.policy = config.digest()
        self.on_failure = on_failure

    def _due(self, name, snapshot, interval):
        key = hashlib.sha256(json.dumps([name, snapshot["tree"], snapshot["base"], self.policy]).encode()).hexdigest()
        records = [event for event in self.engine.events("job_done") if event.get("key") == key]
        if not records:
            return key
        last = records[-1]
        now = self.wall_clock()
        if last["status"] in ("PASSED", "UNVERIFIED"):
            return key if interval and now - last["finished_at"] >= interval else None
        # Foreground preemption is not a failed attempt and may resume once quiet.
        if last["status"] in ("CANCELLED", "INTERRUPTED"):
            return key if now - last["finished_at"] >= self.config.retry_backoff_seconds else None
        failures = 0
        for record in reversed(records):
            if record["status"] not in ("FAILED", "REJECTED", "ERROR"):
                break
            failures += 1
        if failures > self.config.max_retries:
            return None
        delay = self.config.retry_backoff_seconds * (2 ** max(0, failures - 1))
        return key if now - last["finished_at"] >= delay else None

    def tick(self):
        if self.stop():
            return {"status": "STOPPED"}
        # A changed frozen-runtime manifest creates a new execution policy even
        # if the source and configured artifact path have not changed.
        self.policy = self.config.digest()
        if foreground_active(self.engine) or git_busy(self.engine):
            self.changed_at = self.clock()
            return {"status": "DEFERRED", "reason": "foreground activity"}
        current = fingerprint(self.engine)
        if current != self.previous:
            self.previous, self.changed_at, self.snapshot = current, self.clock(), None
        if self.clock() - self.changed_at < self.config.quiet_seconds:
            return {"status": "DEFERRED", "reason": "quiet interval"}
        if self.snapshot is None:
            self.snapshot = self.engine.capture()
            if fingerprint(self.engine) != current:
                self.snapshot = None
                self.changed_at = self.clock()
                return {"status": "DEFERRED", "reason": "capture changed"}
        snapshot = self.snapshot
        if not self.config.checks and not self.config.jobs:
            return {"status": "OBSERVED", "tree": snapshot["tree"]}
        jobs = [("verify", None, 0)] if self.config.checks else []
        jobs += [(job.name, job.command, job.interval_seconds) for job in self.config.jobs if job.enabled]
        for name, command, interval in jobs:
            key = self._due(name, snapshot, interval)
            if key is None:
                continue
            # Avoid spending a maintenance pass on a candidate that cannot be offered.
            if command:
                waiting = self.engine.git("for-each-ref", "--format=%(refname)", "refs/heads/custodian/").splitlines()
                if len(waiting) >= 3:
                    return {"status": "DEFERRED", "reason": "proposal queue full"}
            token = uuid.uuid4().hex
            self.engine.event("job_start", dict(id=token, key=key, job=name, tree=snapshot["tree"],
                                               base=snapshot["base"], policy=self.policy, started_at=self.wall_clock()))
            last_poll = [0.0]
            def cancelled():
                if self.stop() or foreground_active(self.engine):
                    return True
                # Source checks are rate limited; session leases are checked each time.
                now = self.clock()
                if now - last_poll[0] < min(self.config.poll_seconds, 1.0):
                    return False
                last_poll[0] = now
                return git_busy(self.engine) or fingerprint(self.engine) != current
            try:
                result = self.engine.run(
                    intent=f"Scheduled {name}", command=command, checks=self.config.checks,
                    protected=self.config.protected, timeout=self.config.timeout_seconds,
                    cancel=cancelled, mode=self.config.execution_mode, runtime_paths=self.config.runtime_paths,
                    runtime_root=self.config.runtime_root,
                    context={"job": name, "policy": self.policy, "schedule_key": key, "job_id": token}, snapshot=snapshot)
            except Exception as exc:
                self.engine.event("job_done", dict(id=token, key=key, job=name, status="ERROR",
                                                   reason=str(exc), finished_at=self.wall_clock()))
                raise
            self.engine.event("job_done", dict(id=token, key=key, job=name, status=result["status"],
                                               attempt=result["id"], finished_at=self.wall_clock()))
            if result["status"] in ("CANCELLED", "INTERRUPTED"):
                self.changed_at, self.snapshot = self.clock(), None
            elif (name == "verify" and result["status"] == "FAILED" and self.on_failure is not None
                  and any(check.get("exit_code") not in (None, 0) and not check.get("timed_out")
                          and not check.get("cancelled") and not check.get("output_limited") and not check.get("infrastructure_error")
                          for check in result.get("checks", []))
                  and self.config.model.get("auto_on_failure", False) and not cancelled()):
                # Reserve dispatch durably before any provider request. An uncertain
                # interrupted request is never replayed automatically on restart.
                seen = any(event.get("key") == key for event in self.engine.events("model_dispatch"))
                waiting = self.engine.git("for-each-ref", "--format=%(refname)", "refs/heads/custodian/").splitlines()
                if not seen and len(waiting) < 3:
                    model_id = uuid.uuid4().hex
                    self.engine.event("model_dispatch", dict(id=model_id, key=key, failed_attempt=result["id"],
                                                              dispatched_at=self.wall_clock()))
                    try:
                        model_result = self.on_failure(self.engine, self.config, snapshot, result, cancelled)
                    except Exception as exc:
                        self.engine.event("model_done", dict(id=model_id, key=key, status="ERROR", reason=str(exc)))
                    else:
                        self.engine.event("model_done", dict(id=model_id, key=key, result=model_result))
                        result = dict(result, model_result=model_result)
            return result
        return {"status": "IDLE", "tree": snapshot["tree"]}


def run(engine, config, *, once=False, stop=None, on_failure=None):
    """Own one watcher lease; recover abandoned attempts before first dispatch."""
    daemon = Daemon(engine, config, stop=stop, on_failure=on_failure)
    with engine.lease(name="watch.lock", blocking=False):
        engine.recover()
        completed = {event["id"] for event in engine.events("job_done")}
        attempts = {event.get("context", {}).get("job_id"): event
                    for event in engine.events("attempt_finished")}
        for started in engine.events("job_start"):
            if started["id"] not in completed:
                attempt = attempts.get(started["id"])
                engine.event("job_done", dict(id=started["id"], key=started["key"], job=started["job"],
                                               status=attempt["status"] if attempt else "INTERRUPTED",
                                               attempt=attempt["id"] if attempt else None,
                                               finished_at=time.time(), recovered=True))
        while not daemon.stop():
            try:
                result = daemon.tick()
                if result.get("status") not in ("DEFERRED", "IDLE"):
                    print(json.dumps(result), flush=True)
            except (CustodianError, OSError) as exc:
                engine.event("daemon_error", dict(reason=str(exc), observed_at=time.time()))
                if once:
                    raise
            if once:
                return result
            # Responsive termination even with a long configured poll interval.
            until = time.monotonic() + config.poll_seconds
            while not daemon.stop() and time.monotonic() < until:
                time.sleep(min(0.1, max(0, until - time.monotonic())))
