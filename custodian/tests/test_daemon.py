"""Scheduling tests keep execution fake and exercise real Git input/lock boundaries."""
import contextlib
import fcntl
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from custodian.config import Config
from custodian.daemon import Daemon, run


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeEngine:
    def __init__(self, root):
        self.repo = root / "repo"
        self.state = root / "state"
        self.repo.mkdir()
        self.state.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "app.py").write_text("VALUE = 1\n")
        self.source_git(self.repo, "add", ".")
        self.source_git(self.repo, "-c", "user.name=Tests", "-c", "user.email=tests@example.invalid", "commit", "-qm", "base")
        self.records, self.calls, self.statuses = [], [], []
        self.captures, self.recoveries, self.waiting = 0, 0, 0
        self.on_run = None

    def source_git(self, directory, *args):
        return subprocess.check_output(["git", "-C", str(directory), *args])

    def git(self, *args):
        return "\n".join(f"refs/heads/custodian/{n}" for n in range(self.waiting))

    def capture(self):
        self.captures += 1
        tree = hashlib.sha256((self.repo / "app.py").read_bytes()).hexdigest()
        return dict(tree=tree, commit="candidate", base=self.source_git(self.repo, "rev-parse", "HEAD").decode().strip())

    def event(self, kind, payload):
        self.records.append(dict(kind=kind, **payload))

    def events(self, kind):
        return [record for record in self.records if record["kind"] == kind]

    def run(self, **kwargs):
        self.calls.append(kwargs)
        status = self.statuses.pop(0) if self.statuses else "PASSED"
        if self.on_run:
            status = self.on_run(kwargs)
        result = dict(id=str(len(self.calls)), status=status, context=kwargs["context"],
                      checks=[{"exit_code": 1 if status == "FAILED" else 0}])
        self.event("attempt_finished", result)
        return result

    def recover(self):
        self.recoveries += 1

    @contextlib.contextmanager
    def lease(self, name="writer.lock", blocking=True):
        with (self.state / name).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            yield


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = FakeEngine(Path(self.temp.name))
        self.clock = Clock()

    def daemon(self, **settings):
        policy = {"checks": [["true"]], "quiet_seconds": 0, "retry_backoff_seconds": 2, **settings}
        return Daemon(self.engine, Config.from_dict(policy), clock=self.clock, wall_clock=self.clock)

    def test_quiet_capture_coalesces_restart_but_policy_and_base_changes_recheck(self):
        daemon = self.daemon(quiet_seconds=10)
        self.assertEqual(daemon.tick()["status"], "DEFERRED")
        self.assertEqual(self.engine.captures, 0)
        self.clock.now += 10
        self.assertEqual(daemon.tick()["status"], "PASSED")
        self.assertEqual(daemon.tick()["status"], "IDLE")
        self.assertEqual(self.engine.captures, 1)
        restarted = self.daemon(quiet_seconds=10)
        restarted.tick()
        self.clock.now += 10
        self.assertEqual(restarted.tick()["status"], "IDLE")
        changed = self.daemon(quiet_seconds=10, checks=[["different-check"]])
        changed.tick()
        self.clock.now += 10
        self.assertEqual(changed.tick()["status"], "PASSED")
        self.engine.source_git(self.engine.repo, "-c", "user.name=Tests", "-c", "user.email=tests@example.invalid",
                               "commit", "--allow-empty", "-qm", "new base same source")
        changed.tick()
        self.clock.now += 10
        self.assertEqual(changed.tick()["status"], "PASSED")
        self.assertEqual(len(self.engine.calls), 3)

    def test_registered_foreground_defers_and_cancels_running_work(self):
        daemon = self.daemon()
        with (self.engine.state / "foreground.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            self.assertEqual(daemon.tick()["status"], "DEFERRED")
        def child(kwargs):
            with (self.engine.state / "foreground.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                self.assertTrue(kwargs["cancel"]())
            return "CANCELLED"
        self.engine.on_run = child
        self.assertEqual(daemon.tick()["status"], "CANCELLED")
        self.assertEqual(self.engine.events("job_done")[-1]["status"], "CANCELLED")

    def test_source_edit_cancels_inflight_work(self):
        daemon = self.daemon()
        def child(kwargs):
            (self.engine.repo / "app.py").write_text("manual foreground edit\n")
            self.assertTrue(kwargs["cancel"]())
            return "CANCELLED"
        self.engine.on_run = child
        self.assertEqual(daemon.tick()["status"], "CANCELLED")

    def test_failed_attempts_retry_with_persistent_backoff_then_stop(self):
        self.engine.statuses = ["FAILED"] * 10
        daemon = self.daemon(max_retries=1)
        self.assertEqual(daemon.tick()["status"], "FAILED")
        self.assertEqual(daemon.tick()["status"], "IDLE")
        self.clock.now += 2
        restarted = self.daemon(max_retries=1)
        self.assertEqual(restarted.tick()["status"], "FAILED")
        self.clock.now += 100
        self.assertEqual(restarted.tick()["status"], "IDLE")
        self.assertEqual(len(self.engine.calls), 2)

    def test_maintenance_jobs_follow_verification_and_respect_proposal_capacity(self):
        daemon = self.daemon(jobs=[{"name": "format", "command": ["formatter"], "interval_seconds": 10}])
        self.assertEqual(daemon.tick()["status"], "PASSED")
        self.engine.waiting = 3
        self.assertEqual(daemon.tick()["reason"], "proposal queue full")
        self.assertEqual(len(self.engine.calls), 1)
        self.engine.waiting = 2
        self.assertEqual(daemon.tick()["status"], "PASSED")
        self.assertEqual(self.engine.calls[-1]["command"], ["formatter"])
        self.assertEqual(daemon.tick()["status"], "IDLE")
        self.clock.now += 10
        self.assertEqual(daemon.tick()["status"], "PASSED")

    def test_model_failure_dispatch_is_durable_and_once_per_candidate_policy(self):
        daemon = self.daemon(model={"auto_on_failure": True})
        self.engine.statuses = ["FAILED", "FAILED"]
        calls = []
        def callback(*args):
            calls.append(args)
            raise RuntimeError("uncertain provider response")
        daemon.on_failure = callback
        self.assertEqual(daemon.tick()["status"], "FAILED")
        self.clock.now += 2
        restarted = self.daemon(model={"auto_on_failure": True})
        restarted.on_failure = callback
        self.assertEqual(restarted.tick()["status"], "FAILED")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.engine.events("model_dispatch")), 1)

    def test_infrastructure_failure_does_not_dispatch_model(self):
        daemon = self.daemon(model={"auto_on_failure": True})
        calls = []
        daemon.on_failure = lambda *args: calls.append(args)
        original = self.engine.run
        def infrastructure_failure(**kwargs):
            result = original(**kwargs)
            result.update(status="FAILED", checks=[], reason="sandbox unavailable")
            return result
        self.engine.run = infrastructure_failure
        self.assertEqual(daemon.tick()["status"], "FAILED")
        self.assertEqual(calls, [])
        self.assertEqual(self.engine.events("model_dispatch"), [])

    def test_run_recovers_job_journal_gap_without_duplicate_attempt(self):
        config = Config.from_dict({"checks": [["true"]], "quiet_seconds": 0})
        daemon = Daemon(self.engine, config)
        result = daemon.tick()
        self.engine.records = [record for record in self.engine.records if record["kind"] != "job_done"]
        outcome = run(self.engine, config, once=True)
        self.assertEqual(outcome["status"], "IDLE")
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual(self.engine.recoveries, 1)
        self.assertTrue(self.engine.events("job_done")[-1]["recovered"])


if __name__ == "__main__":
    unittest.main()
