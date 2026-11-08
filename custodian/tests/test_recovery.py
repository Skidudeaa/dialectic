"""Crash recovery and proposal publication are observable state transitions."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from custodian.engine import Engine


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "foreground"
        self.repo.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Recovery tests"),
                     ("config", "user.email", "recovery@example.invalid")):
            subprocess.check_call(["git", "-C", str(self.repo), *args])
        (self.repo / "app.py").write_text("VALUE = 1\n")
        subprocess.check_call(["git", "-C", str(self.repo), "add", "."])
        subprocess.check_call(["git", "-C", str(self.repo), "commit", "-qm", "input"])
        self.engine = Engine(self.repo, self.root / "state")

    @staticmethod
    def python(code):
        return ["/usr/bin/python3", "-c", code]

    def run_attempt(self, **kwargs):
        arguments = dict(intent="Recovery test", command=None, checks=[self.python("raise SystemExit(0)")])
        arguments.update(kwargs)
        return self.engine.run(**arguments)

    def proposal(self):
        result = self.run_attempt(command=self.python(
            "from pathlib import Path; Path('app.py').write_text('VALUE = 2\\n')"))
        self.assertEqual(result["status"], "PASSED", result)
        self.assertTrue(result["branch"], result)
        return result

    def refs(self):
        return self.engine.git("for-each-ref", "--format=%(refname:short)", "refs/heads/custodian/").splitlines()

    def test_sigkill_preserves_progress_recovers_unknown_outcome_and_cleans_worktrees(self):
        code = (
            "from pathlib import Path; from custodian.engine import Engine; import sys; "
            "engine = Engine(Path(sys.argv[1]), Path(sys.argv[2])); "
            "engine.run('Abrupt crash', None, "
            "[['/usr/bin/python3','-c',\"print('retained-before-crash')\"], "
            "['/usr/bin/python3','-c','import time; time.sleep(30)']], timeout=40)"
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        process = subprocess.Popen([sys.executable, "-c", code, str(self.repo), str(self.engine.state)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

        self.addCleanup(cleanup)
        deadline = time.monotonic() + 8
        progress = []
        while time.monotonic() < deadline:
            progress = self.engine.events("attempt_progress")
            if progress:
                break
            if process.poll() is not None:
                self.fail("Controller exited before crash point: " + process.communicate()[1].decode())
            time.sleep(0.02)
        self.assertTrue(progress, "First isolated checker never completed")
        attempt_id = progress[0]["id"]
        self.assertEqual(self.engine.events("attempt_finished"), [])
        process.send_signal(signal.SIGKILL)
        process.communicate(timeout=5)

        recovered = self.engine.recover()
        self.assertEqual(recovered["recovered"], [attempt_id])
        result = self.engine.events("attempt_finished")[-1]
        self.assertEqual(result["status"], "INTERRUPTED")
        self.assertIsNone(result["branch"])
        self.assertEqual(result["recovered_evidence"][0]["phase"], "check")
        blob = result["recovered_evidence"][0]["evidence"]["stdout_blob"]
        output = subprocess.check_output(["git", "--git-dir", str(self.engine.archive), "cat-file", "blob", blob])
        self.assertEqual(output, b"retained-before-crash\n")
        self.assertEqual(list((self.engine.state / "work").iterdir()), [])
        self.assertEqual(self.engine.proposals(), [])
        self.assertTrue(self.engine.audit()["ok"])
        self.assertEqual(self.run_attempt()["status"], "PASSED")
        self.assertEqual(self.engine.recover()["recovered"], [])

    def test_recovery_closes_passed_completion_ref_gap_without_publishing_failed_outcome(self):
        passed = self.proposal()
        self.engine.git("update-ref", "-d", "refs/heads/" + passed["branch"])
        self.assertNotIn(passed["branch"], self.refs())
        failed = self.run_attempt(checks=[self.python("raise SystemExit(2)")])
        self.assertEqual(failed["status"], "FAILED")
        # Simulate an interrupted publisher with a failed verdict and a reserved
        # branch name. Recovery must inspect the verdict, not the name alone.
        failed_record = dict(failed, branch="custodian/failed-reserved")
        self.engine.event("attempt_finished", failed_record)
        self.engine.recover()
        self.assertIn(passed["branch"], self.refs())
        self.assertNotIn(failed_record["branch"], self.refs())
        proposals = self.engine.proposals()
        self.assertEqual([p["id"] for p in proposals], [passed["id"]])
        self.assertTrue(all(p["status"] == "PASSED" for p in proposals))

    def test_disposed_branch_is_not_resurrected_and_acceptance_is_not_merge_claim(self):
        result = self.proposal()
        before = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"])
        disposition = self.engine.dispose(result["id"], "accepted", "Reviewed externally")
        self.assertFalse(disposition["integration_verified"])
        self.assertEqual(self.engine.proposals(), [])
        self.engine.recover()
        self.assertNotIn(result["branch"], self.refs())
        self.assertEqual(self.engine.proposals(), [])
        # Simulate a controller death between the durable disposition event and
        # deleting the private branch. Replay must finish that deletion too.
        self.engine.git("update-ref", "refs/heads/" + result["branch"], result["output_commit"])
        self.engine.recover()
        self.assertNotIn(result["branch"], self.refs())
        self.assertEqual(self.engine.proposals(), [])
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"]), before)
        self.assertTrue(self.engine.audit()["ok"])

    def test_audit_detects_missing_retained_stdout_object(self):
        result = self.run_attempt(checks=[self.python("print('unique audit evidence')")])
        self.assertEqual(result["status"], "PASSED", result)
        self.assertTrue(self.engine.audit()["ok"])
        oid = result["checks"][0]["stdout_blob"]
        obj = self.engine.archive / "objects" / oid[:2] / oid[2:]
        self.assertTrue(obj.is_file(), "Fixture expects a newly written loose object")
        obj.unlink()
        audit = self.engine.audit()
        self.assertFalse(audit["ok"])
        self.assertIn("Missing evidence object " + oid, audit["errors"])

    def test_cancelled_attempt_does_not_publish_proposal(self):
        result = self.run_attempt(command=self.python("raise SystemExit(0)"), cancel=lambda: True)
        self.assertEqual(result["status"], "CANCELLED", result)
        self.assertIsNone(result["branch"])
        self.assertEqual(self.engine.proposals(), [])
        self.assertEqual(self.engine.events("attempt_finished")[-1]["status"], "CANCELLED")
        self.assertEqual(self.engine.recover()["recovered"], [])


if __name__ == "__main__":
    unittest.main()
