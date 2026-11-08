"""Subprocess checks of foreground priority and persistent watch scheduling."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from custodian.engine import Engine


class CLIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.state = self.root / "state"
        for args in (("init", "-q"), ("config", "user.name", "CLI tests"),
                     ("config", "user.email", "cli@example.invalid")):
            subprocess.check_call(["git", "-C", str(self.repo), *args])
        (self.repo / "app.py").write_text("VALUE = 1\n")
        subprocess.check_call(["git", "-C", str(self.repo), "add", "."])
        subprocess.check_call(["git", "-C", str(self.repo), "commit", "-qm", "start"])
        self.engine = Engine(self.repo, self.state)
        self.environment = os.environ.copy()
        self.environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        self.processes = []
        self.addCleanup(self.stop_all)

    def launch(self, *args):
        process = subprocess.Popen(
            [sys.executable, "-m", "custodian.cli", "--repo", str(self.repo),
             "--state-dir", str(self.state), *args], env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        return process

    def stop(self, process):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            return process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.communicate(timeout=5)

    def stop_all(self):
        for process in self.processes:
            self.stop(process)

    def until(self, predicate, message, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail(message)

    def watch(self, *args):
        return self.launch("watch", "--quiet", "0.08", "--interval", "0.03", *args)

    def test_default_watch_records_settled_edits_without_executors_and_coalesces_restart(self):
        # Put traps on the usual model CLIs; default watching must remain observation-only.
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        model_calls = self.root / "model-calls"
        for name in ("claude", "codex", "ollama"):
            path = bin_dir / name
            path.write_text(f"#!/bin/sh\nprintf called >> '{model_calls}'\nexit 97\n")
            path.chmod(0o755)
        self.environment["PATH"] = str(bin_dir) + os.pathsep + self.environment["PATH"]
        watcher = self.watch()
        self.until(lambda: len(self.engine.events("observation")) == 1, "Initial tree was not captured")
        (self.repo / "app.py").write_text("VALUE = 2\n")
        self.until(lambda: len(self.engine.events("observation")) == 2, "Settled edit was not captured")
        self.stop(watcher)
        observations = self.engine.events("observation")
        self.assertNotEqual(observations[0]["tree"], observations[1]["tree"])
        restarted = self.watch()
        time.sleep(0.35)
        self.assertIsNone(restarted.poll())
        self.stop(restarted)
        self.assertEqual(len(self.engine.events("observation")), 2)
        self.assertEqual(self.engine.events("attempt_started"), [])
        self.assertFalse(model_calls.exists())

    def test_registered_session_defers_checks_until_exit_and_restart_does_not_repeat(self):
        ready, release = self.root / "ready", self.root / "release"
        child = (
            "from pathlib import Path; import time; "
            f"Path({str(ready)!r}).write_text('ready'); "
            f"deadline=time.monotonic()+5\n"
            f"while not Path({str(release)!r}).exists() and time.monotonic()<deadline: time.sleep(.02)\n"
        )
        foreground = self.launch("session", "--", sys.executable, "-c", child)
        self.until(ready.exists, "Foreground child did not start")
        check = json.dumps(["/usr/bin/python3", "-c", "print('independent check')"])
        watcher = self.watch("--check", check)
        time.sleep(0.3)
        self.assertIsNone(watcher.poll())
        self.assertEqual(self.engine.events("attempt_started"), [])
        (self.repo / "app.py").write_text("VALUE = 3\n")
        release.touch()
        foreground.communicate(timeout=5)
        self.assertEqual(foreground.returncode, 0)
        self.until(lambda: len(self.engine.events("watch_checked")) == 1, "Deferred check did not run")
        self.stop(watcher)
        self.assertEqual(self.engine.events("attempt_finished")[0]["status"], "PASSED")
        self.assertEqual(len(self.engine.events("session_started")), 1)
        self.assertEqual(len(self.engine.events("session_ended")), 1)
        restarted = self.watch("--check", check)
        time.sleep(0.35)
        self.assertIsNone(restarted.poll())
        self.stop(restarted)
        self.assertEqual(len(self.engine.events("attempt_started")), 1)

    def test_foreground_launch_does_not_wait_for_running_check(self):
        ready, release = self.root / "check-ready", self.root / "release-check"
        command = (
            "from pathlib import Path; import time; "
            f"Path({str(ready)!r}).write_text('ready'); deadline=time.monotonic()+5\n"
            f"while not Path({str(release)!r}).exists() and time.monotonic()<deadline: time.sleep(.02)\n"
        )
        worker = self.launch("run", "--mode", "trusted", "--intent", "long check", "--check",
                             json.dumps([sys.executable, "-c", command]))
        self.until(ready.exists, "Check never started")
        foreground = self.launch("session", "--", sys.executable, "-c", "print('foreground ran')")
        try:
            stdout, stderr = foreground.communicate(timeout=2)
            self.assertEqual(foreground.returncode, 0, stderr)
            self.assertIn("foreground ran", stdout)
            self.assertIsNone(worker.poll(), "Check finished before priority was exercised")
        finally:
            release.touch()
        worker.communicate(timeout=5)
        self.assertEqual(worker.returncode, 0)


if __name__ == "__main__":
    unittest.main()
