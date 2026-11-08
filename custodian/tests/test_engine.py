"""Behavioral integration tests against real Git repositories and child commands."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from custodian.engine import Engine


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "foreground"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Custodian tests")
        (self.repo / "app.py").write_text("VALUE = 1\n")
        (self.repo / "SPEC.md").write_text("Never replace the source checkout.\n")
        (self.repo / "deleted.txt").write_text("committed, then deleted\n")
        (self.repo / ".gitignore").write_text("ignored.txt\n__pycache__/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "input")
        self.engine = Engine(self.repo, self.root / "state")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args])

    @staticmethod
    def python(code):
        return ["/usr/bin/python3", "-c", code]

    def foreground_state(self):
        # Check bytes and index rather than assuming git status detects everything.
        files = {}
        for path in self.repo.rglob("*"):
            relative = path.relative_to(self.repo)
            if relative.parts[0] == ".git":
                continue
            if path.is_symlink():
                files[str(relative)] = ("link", os.readlink(path))
            elif path.is_file():
                files[str(relative)] = (path.stat().st_mode, path.read_bytes())
        return (
            files,
            (self.repo / ".git" / "index").read_bytes(),
            self.git("rev-parse", "HEAD"),
            self.git("--no-optional-locks", "status", "--porcelain=v1", "-z"),
        )

    def run_attempt(self, **kwargs):
        options = {"intent": "integration test", "command": None, "checks": []}
        options.update(kwargs)
        return self.engine.run(**options)

    def test_candidate_carries_uncommitted_bytes_deletions_and_modes(self):
        (self.repo / "app.py").write_text("VALUE = 2\n")
        (self.repo / "deleted.txt").unlink()
        (self.repo / "untracked.py").write_text("print('draft')\n")
        (self.repo / "untracked.py").chmod(0o755)
        (self.repo / "alias.py").symlink_to("app.py")
        (self.repo / "ignored.txt").write_text("not candidate material\n")
        before = self.foreground_state()

        result = self.run_attempt(checks=[self.python(
            "from pathlib import Path; import os; "
            "assert Path('app.py').read_text() == 'VALUE = 2\\n'; "
            "assert not Path('deleted.txt').exists(); "
            "assert Path('untracked.py').read_text() == \"print('draft')\\n\"; "
            "assert os.access('untracked.py', os.X_OK); "
            "assert Path('alias.py').is_symlink(); "
            "assert os.readlink('alias.py') == 'app.py'; "
            "assert not Path('ignored.txt').exists()"
        )])

        self.assertEqual(result["status"], "PASSED", result)
        self.assertEqual(before, self.foreground_state())

    def test_passing_change_has_distinct_tree_without_foreground_mutation(self):
        before = self.foreground_state()
        result = self.run_attempt(
            command=self.python("from pathlib import Path; Path('app.py').write_text('VALUE = 3\\n')"),
            checks=[self.python("from pathlib import Path; assert Path('app.py').read_text() == 'VALUE = 3\\n'")],
        )
        self.assertEqual(result["status"], "PASSED", result)
        self.assertNotEqual(result["input_tree"], result["output_tree"])
        self.assertTrue(result["branch"].startswith("custodian/"), result)
        self.assertEqual(before, self.foreground_state())

    def test_failed_check_cannot_become_a_passed_attempt(self):
        result = self.run_attempt(checks=[self.python("print('all tests passed'); raise SystemExit(7)")])
        self.assertEqual(result["status"], "FAILED", result)
        self.assertTrue(result["checks"], result)

    def test_verifier_cannot_inherit_ignored_artifacts_from_mutator(self):
        result = self.run_attempt(
            command=self.python(
                "from pathlib import Path; "
                "Path('app.py').write_text('VALUE = 3\\n'); "
                "Path('ignored.txt').write_text('pretend verification fixture')"
            ),
            checks=[self.python(
                "from pathlib import Path; "
                "assert Path('app.py').read_text() == 'VALUE = 3\\n'; "
                "assert not Path('ignored.txt').exists()"
            )],
        )
        self.assertEqual(result["status"], "PASSED", result)

    def test_mutating_checker_cannot_certify_its_original_candidate(self):
        result = self.run_attempt(checks=[self.python(
            "from pathlib import Path; Path('app.py').write_text('VALUE = 99\\n')"
        )])
        self.assertEqual(result["status"], "FAILED", result)
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 1\n")

    def test_protected_deletion_is_rejected_even_when_checks_pass(self):
        result = self.run_attempt(
            command=self.python("from pathlib import Path; Path('SPEC.md').unlink()"),
            checks=[self.python("raise SystemExit(0)")],
            protected=["SPEC.md"],
        )
        self.assertEqual(result["status"], "REJECTED", result)
        self.assertTrue((self.repo / "SPEC.md").exists())

    def test_no_checks_does_not_mean_verified(self):
        result = self.run_attempt()
        self.assertEqual(result["status"], "UNVERIFIED", result)

    def test_subsequent_manual_edit_cannot_inherit_evidence(self):
        result = self.run_attempt(checks=[self.python("raise SystemExit(0)")])
        self.assertEqual(result["status"], "PASSED", result)
        initial = self.engine.status()
        self.assertEqual(initial["current_tree"], result["output_tree"])
        self.assertTrue(initial["applicable"], initial)

        (self.repo / "app.py").write_text("a subsequent manual edit\n")
        current = self.engine.status()
        self.assertNotEqual(current["current_tree"], result["output_tree"])
        self.assertFalse(current["applicable"], current)
        self.assertEqual(current["latest"]["id"], result["id"])
        self.assertEqual(current["latest"]["status"], "PASSED")

    def test_later_success_retains_failed_attempt_and_its_raw_output(self):
        failed = self.run_attempt(checks=[self.python("print('prior failure evidence'); raise SystemExit(2)")])
        passed = self.run_attempt(checks=[self.python("raise SystemExit(0)")])
        outcomes = {event["id"]: event for event in self.engine.events("attempt_finished")}
        self.assertEqual(outcomes[failed["id"]]["status"], "FAILED")
        self.assertEqual(outcomes[passed["id"]]["status"], "PASSED")
        subprocess.run([
            "git", "--git-dir", str(self.engine.archive), "gc", "--prune=now",
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        blob = outcomes[failed["id"]]["checks"][0]["stdout_blob"]
        raw = subprocess.check_output([
            "git", "--git-dir", str(self.engine.archive), "cat-file", "blob", blob,
        ])
        self.assertEqual(raw, b"prior failure evidence\n")

    def test_timed_out_checker_is_failed(self):
        result = self.run_attempt(
            checks=[self.python("import time; time.sleep(10)")],
            timeout=0.1,
        )
        self.assertEqual(result["status"], "FAILED", result)

    def test_failed_mutator_does_not_pass_despite_passing_checks(self):
        result = self.run_attempt(
            command=self.python("raise SystemExit(13)"),
            checks=[self.python("raise SystemExit(0)")],
        )
        self.assertEqual(result["status"], "FAILED", result)

    def test_absolute_symlink_cannot_make_checker_overwrite_foreground(self):
        (self.repo / "escape.py").symlink_to(self.repo / "app.py")
        before = self.foreground_state()
        result = self.run_attempt(checks=[self.python(
            "from pathlib import Path; Path('escape.py').write_text('escaped')"
        )])
        self.assertEqual(result["status"], "FAILED", result)
        self.assertEqual(result["checks"], [])
        self.assertEqual(before, self.foreground_state())

    def test_interrupted_controller_records_unknown_outcome(self):
        with mock.patch.object(self.engine, "_command", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_attempt(command=self.python("raise SystemExit(0)"))
        state = self.engine.status()
        self.assertEqual(state["latest"]["status"], "INTERRUPTED", state)
        self.assertEqual(state["unfinished"], [])

    def test_three_waiting_branches_withhold_the_fourth(self):
        attempts = []
        for value in range(2, 6):
            attempts.append(self.run_attempt(
                command=self.python(
                    f"from pathlib import Path; Path('app.py').write_text('VALUE = {value}\\n')"
                ),
                checks=[self.python("raise SystemExit(0)")],
            ))
        self.assertTrue(all(attempt["status"] == "PASSED" for attempt in attempts), attempts)
        self.assertTrue(all(attempt["branch"] for attempt in attempts[:3]), attempts)
        self.assertIsNone(attempts[3]["branch"])
        self.assertIn("branch_withheld", attempts[3])
        branches = subprocess.check_output([
            "git", "--git-dir", str(self.engine.archive), "for-each-ref",
            "--format=%(refname)", "refs/heads/custodian/",
        ]).splitlines()
        self.assertEqual(len(branches), 3)

    def test_submodule_requires_explicit_support_instead_of_silent_omission(self):
        commit = self.git("rev-parse", "HEAD").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{commit},nested")
        with self.assertRaises((ValueError, RuntimeError)):
            self.engine.capture()

    @staticmethod
    def native_tree(engine, directory):
        """The tree git itself builds from the same bytes, one hash-object per file."""
        names = subprocess.check_output(["git", "-C", str(directory), "ls-files", "--cached", "--others",
                                         "--exclude-standard", "-z"]).split(b"\0")
        records = []
        for raw in sorted(set(names) - {b""}):
            path = directory / os.fsdecode(raw)
            if path.is_symlink():
                mode, data = "120000", os.fsencode(os.readlink(path))
            elif not path.exists():
                continue
            else:
                mode = "100755" if path.stat().st_mode & 0o111 else "100644"
                data = path.read_bytes()
            oid = subprocess.check_output(["git", "--git-dir", str(engine.archive), "hash-object", "-w", "--stdin"],
                                          input=data, env=engine.git_env).decode().strip()
            records.append(f"{mode} {oid}\t".encode() + raw + b"\0")
        env = dict(engine.git_env, GIT_INDEX_FILE=str(engine.state / "native-index"))
        subprocess.check_call(["git", "--git-dir", str(engine.archive), "read-tree", "--empty"], env=env)
        subprocess.run(["git", "--git-dir", str(engine.archive), "update-index", "-z", "--index-info"],
                       input=b"".join(records), env=env, check=True)
        return subprocess.check_output(["git", "--git-dir", str(engine.archive), "write-tree"], env=env).decode().strip()

    def stage_awkward_bytes(self, repo):
        (repo / "crlf.txt").write_bytes(b"line one\r\nline two\r\n")
        (repo / "binary.bin").write_bytes(bytes(range(256)) * 3 + b"\0\0trailing")
        (repo / "empty.txt").write_bytes(b"")
        (repo / "tool.sh").write_text("#!/bin/sh\nexit 0\n")
        (repo / "tool.sh").chmod(0o755)
        (repo / "link").symlink_to("crlf.txt")
        (repo / "nested").mkdir()
        (repo / "nested/same.txt").write_text("duplicate content\n")
        (repo / "same.txt").write_text("duplicate content\n")

    def test_in_process_blob_ids_reproduce_git_trees_and_spawn_nothing_for_stored_blobs(self):
        from custodian import engine as engine_module
        self.stage_awkward_bytes(self.repo)
        (self.repo / "deleted.txt").unlink()
        self.assertEqual(self.engine.object_format, "sha1")
        tree = self.engine._tree(self.repo)
        self.assertEqual(tree, self.native_tree(self.engine, self.repo))
        self.assertEqual(len(tree), 40)
        # Every blob is stored by the first scan; a second scan confirms in one batch and writes none.
        with mock.patch.object(engine_module, "execute", wraps=engine_module.execute) as spy:
            self.assertEqual(self.engine._tree(self.repo), tree)
        self.assertEqual([call.args[0] for call in spy.call_args_list if "hash-object" in call.args[0]], [])
        self.assertEqual(sum("--batch-check" in call.args[0] for call in spy.call_args_list), 1)
        snapshot = self.engine.capture()
        self.assertEqual(snapshot["tree"], tree)
        self.assertTrue(self.engine.audit()["ok"])

    def test_sha256_repositories_keep_their_object_format_end_to_end(self):
        repo = self.root / "sha256"
        repo.mkdir()
        init = subprocess.run(["git", "-C", str(repo), "init", "-q", "--object-format=sha256"],
                              capture_output=True)
        if init.returncode:
            self.skipTest("this git cannot create sha256 repositories")
        for args in (("config", "user.email", "t@example.invalid"), ("config", "user.name", "T")):
            subprocess.check_call(["git", "-C", str(repo), *args])
        (repo / "app.py").write_text("VALUE = 1\n")
        subprocess.check_call(["git", "-C", str(repo), "add", "."])
        subprocess.check_call(["git", "-C", str(repo), "commit", "-qm", "base"])
        self.stage_awkward_bytes(repo)
        engine = Engine(repo, self.root / "state256")
        self.assertEqual(engine.object_format, "sha256")
        tree = engine._tree(repo)
        self.assertEqual(len(tree), 64)
        self.assertEqual(tree, self.native_tree(engine, repo))
        result = engine.run("sha256 candidate", None, [self.python("raise SystemExit(0)")])
        self.assertEqual(result["status"], "PASSED", result)
        self.assertEqual(result["input_tree"], tree)
        self.assertTrue(engine.audit()["ok"])


if __name__ == "__main__":
    unittest.main()
