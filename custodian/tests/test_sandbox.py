"""Exercise the actual kernel boundary, not mocked subprocess argument lists."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from custodian.sandbox import Sandbox, SandboxError


class SandboxIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root / "candidate"
        self.work.mkdir()
        (self.work / "source.py").write_text("VALUE = 1\n")
        (self.work / ".git").write_text("gitdir: /foreground/secret-state\n")
        self.sandbox = Sandbox()
        # Failure is a failed test: isolated mode must actually work in this host.
        self.assertTrue(self.sandbox.probe()["enforced"])

    def run_python(self, code, **kwargs):
        return self.sandbox.run(["/usr/bin/python3", "-c", code], self.work,
                                kwargs.pop("timeout", 3), kwargs.pop("readonly", True), **kwargs)

    def test_readonly_candidate_rejects_write_and_restore(self):
        result = self.run_python(
            "from pathlib import Path; p=Path('source.py'); original=p.read_bytes(); "
            "p.write_text('changed'); p.write_bytes(original)")
        self.assertNotEqual(result["exit_code"], 0, result)
        self.assertEqual((self.work / "source.py").read_text(), "VALUE = 1\n")
        self.assertTrue(result["environment"]["immutable_execution"])

    def test_writable_candidate_keeps_output_but_cannot_read_host_or_credentials(self):
        sentinel = self.root / "foreground-secret"
        sentinel.write_text("private")
        old = os.environ.get("CUSTODIAN_TEST_SECRET")
        os.environ["CUSTODIAN_TEST_SECRET"] = "do not inherit"
        try:
            result = self.run_python(
                "from pathlib import Path; import os; "
                f"assert not Path({str(sentinel)!r}).exists(); "
                "assert 'CUSTODIAN_TEST_SECRET' not in os.environ; "
                "assert Path('.git').read_bytes() == b''; "
                "assert not Path('/home/agent').exists(); "
                "Path('source.py').write_text('VALUE = 2\\n')", readonly=False)
        finally:
            if old is None:
                os.environ.pop("CUSTODIAN_TEST_SECRET", None)
            else:
                os.environ["CUSTODIAN_TEST_SECRET"] = old
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual((self.work / "source.py").read_text(), "VALUE = 2\n")
        self.assertEqual((self.work / ".git").read_text(), "gitdir: /foreground/secret-state\n")
        self.assertEqual(sentinel.read_text(), "private")

    def test_network_is_unreachable_and_new_user_namespaces_are_disabled(self):
        result = self.run_python(
            "import socket,subprocess; s=socket.socket(); s.settimeout(.3); "
            "assert s.connect_ex(('1.1.1.1',443)) != 0; "
            "assert subprocess.run(['unshare','--user','true'],capture_output=True).returncode != 0")
        self.assertEqual(result["exit_code"], 0, result)

    def test_timeout_stops_the_worker(self):
        result = self.run_python("import time; time.sleep(10)", timeout=.1)
        self.assertTrue(result["timed_out"], result)
        self.assertNotEqual(result["exit_code"], 0)

    def test_closing_output_pipes_cannot_bypass_timeout(self):
        result = self.run_python("import os,time; os.close(1); os.close(2); time.sleep(10)", timeout=.1)
        self.assertTrue(result["timed_out"], result)
        self.assertNotEqual(result["exit_code"], 0)

    def test_cancellation_stops_the_worker(self):
        event = threading.Event()
        timer = threading.Timer(.1, event.set)
        timer.start()
        try:
            result = self.run_python("import time; time.sleep(10)", cancel=event.is_set)
        finally:
            timer.join()
        self.assertTrue(result["cancelled"], result)
        self.assertNotEqual(result["exit_code"], 0)

    def test_output_is_bounded_and_overflow_kills_the_worker(self):
        self.sandbox = Sandbox(max_output_bytes=8192)
        result = self.run_python("import os;\nwhile True: os.write(1,b'x'*4096)")
        self.assertTrue(result["output_limited"], result)
        self.assertEqual(len(result["stdout"]) + len(result["stderr"]), 8192)
        self.assertNotEqual(result["exit_code"], 0)

    def test_runtime_mounts_cannot_expose_repository_or_state(self):
        for path in (self.work, self.root):
            (path / "events.sqlite3").touch()
            with self.assertRaises(SandboxError):
                Sandbox(runtime_paths=[path])
        with self.assertRaises(SandboxError):
            Sandbox(runtime_paths=["/"])

    def test_trusted_mode_is_explicit_and_never_claims_enforcement(self):
        sandbox = Sandbox(mode="trusted")
        self.assertFalse(sandbox.probe()["enforced"])
        result = sandbox.run([sys.executable, "-c", "print('trusted')"], self.work, 3, True)
        self.assertEqual(result["stdout"], b"trusted\n")
        self.assertFalse(result["environment"]["immutable_execution"])

    def test_controller_death_kills_namespace_descendants(self):
        marker = self.work / "marker"
        child = "from pathlib import Path; import time;\nwhile True:\n Path('marker').write_text(str(time.time_ns())); time.sleep(.03)"
        controller = subprocess.Popen([
            sys.executable, "-c",
            "from custodian.sandbox import Sandbox; from pathlib import Path; "
            f"Sandbox().run({['/usr/bin/python3', '-c', child]!r},Path({str(self.work)!r}),30,False)",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(marker.exists(), "sandbox worker did not start")
            controller.kill()
            controller.wait(timeout=3)
            time.sleep(.15)
            first = marker.read_bytes()
            time.sleep(.15)
            self.assertEqual(marker.read_bytes(), first)
        finally:
            if controller.poll() is None:
                controller.kill()
                controller.wait()
            controller.stderr.close()


if __name__ == "__main__":
    unittest.main()
