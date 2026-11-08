"""Model proposals cross the real controller and Linux verifier boundary."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from custodian.config import Config
from custodian.engine import CustodianError, Engine
from custodian.maintenance import build_context, propose


class MaintenanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "foreground"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Maintenance integration")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "app.py").write_text("VALUE = 1\n")
        (self.repo / "SPEC.md").write_text("Protected contract\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_app.py").write_text("assert True\n")
        (self.repo / ".gitignore").write_text("__pycache__/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.engine = Engine(self.repo, self.root / "state")
        self.model = dict(model="test-model", input_usd_per_million="1", output_usd_per_million="3",
                          include=["app.py", "SPEC.md", "tests/*"])
        self.config = Config(checks=[["/usr/bin/python3", "-c",
                                     "from pathlib import Path; assert Path('app.py').read_text() == 'VALUE = 2\\n'"]],
                             model=self.model)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args])

    def edit(self, path="app.py", content="VALUE = 2\n"):
        target = self.repo / path
        return dict(path=path, content=content,
                    expected_sha256=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None)

    @staticmethod
    def response(edits):
        return dict(edits=edits, rationale="Fix the observed failure", request_id="model-test-request",
                    reservation_id="reservation-test", usage=dict(input_tokens=100, output_tokens=20),
                    cost_usd="0.01", reserved_usd="0.1")

    def foreground(self):
        return ((self.repo / "app.py").read_bytes(), (self.repo / ".git/index").read_bytes(),
                self.git("rev-parse", "HEAD"), self.git("status", "--porcelain=v1"))

    def test_model_edit_passes_independent_readonly_check_and_creates_private_branch(self):
        before = self.foreground()
        with patch("custodian.maintenance.Provider") as broker:
            broker.return_value.propose.return_value = self.response([self.edit()])
            result = propose(self.engine, self.config, "Fix the draft")
        self.assertEqual(result["status"], "PASSED", result)
        self.assertTrue(result["branch"].startswith("custodian/"))
        self.assertEqual(before, self.foreground())
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertEqual(result["environment"]["immutable_execution"], "read-only-candidate")
        responses = self.engine.events("model_response")
        self.assertEqual(len(responses), 1)
        self.assertEqual(result["context"]["response_blob"], responses[0]["response_blob"])
        self.assertNotEqual(result["input_tree"], result["output_tree"])
        supplied = broker.return_value.propose.call_args.args[0]
        self.assertEqual(supplied["input_tree"], result["input_tree"])
        self.assertEqual(next(f for f in supplied["files"] if f["path"] == "app.py")["content"], "VALUE = 1\n")

    def test_model_abstention_retains_rationale_without_creating_an_attempt(self):
        with patch("custodian.maintenance.Provider") as broker:
            response = self.response([])
            response["rationale"] = "Evidence does not justify a safe edit"
            broker.return_value.propose.return_value = response
            result = propose(self.engine, self.config, "Inspect the draft")
        self.assertEqual(result["status"], "NO_CHANGE")
        self.assertEqual(self.engine.events("attempt_started"), [])
        self.assertEqual(len(self.engine.events("model_abstained")), 1)
        self.assertTrue(self.engine.audit()["ok"])

    def test_protected_contract_or_tests_cannot_be_changed_by_model(self):
        for target in ("SPEC.md", "tests/test_app.py"):
            with self.subTest(target=target), patch("custodian.maintenance.Provider") as broker:
                broker.return_value.propose.return_value = self.response([self.edit(target, "replaced\n")])
                result = propose(self.engine, self.config, "Attempt protected change")
                self.assertEqual(result["status"], "REJECTED", result)
                self.assertEqual(result["checks"], [])
                self.assertIsNone(result["branch"])

    def test_stale_content_precondition_fails_before_any_check(self):
        edit = self.edit()
        edit["expected_sha256"] = "0" * 64
        with patch("custodian.maintenance.Provider") as broker:
            broker.return_value.propose.return_value = self.response([edit])
            result = propose(self.engine, self.config, "Apply stale edit")
        self.assertEqual(result["status"], "FAILED", result)
        self.assertIn("precondition", result["reason"])
        self.assertEqual(result["checks"], [])
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 1\n")

    def test_foreground_edit_during_model_request_cannot_inherit_candidate_evidence(self):
        edit = self.edit()

        def response_after_edit(context, cancel=None):
            self.assertEqual(next(f for f in context["files"] if f["path"] == "app.py")["content"], "VALUE = 1\n")
            (self.repo / "app.py").write_text("VALUE = 3\n")
            return self.response([edit])

        with patch("custodian.maintenance.Provider") as broker:
            broker.return_value.propose.side_effect = response_after_edit
            result = propose(self.engine, self.config, "Check the imported input only")
        self.assertEqual(result["status"], "PASSED", result)
        self.assertEqual((self.repo / "app.py").read_text(), "VALUE = 3\n")
        status = self.engine.status()
        self.assertFalse(status["applicable"], status)
        self.assertEqual(status["latest"]["id"], result["id"])
        self.assertNotEqual(status["current_tree"], result["output_tree"])

    def test_undisclosed_file_is_rejected_before_attempt_execution(self):
        (self.repo / "private.py").write_text("PRIVATE = True\n")
        with patch("custodian.maintenance.Provider") as broker:
            broker.return_value.propose.return_value = self.response([self.edit("private.py", "PRIVATE = False\n")])
            with self.assertRaisesRegex(CustodianError, "outside the disclosed"):
                propose(self.engine, self.config, "Undisclosed edit")
        self.assertEqual(self.engine.events("attempt_started"), [])
        self.assertEqual((self.repo / "private.py").read_text(), "PRIVATE = True\n")

    def test_model_code_cannot_write_absolute_foreground_path_during_check(self):
        target = self.repo / "app.py"
        payload = f"from pathlib import Path\nPath({str(target)!r}).write_text('escaped')\n"
        config = Config(checks=[["/usr/bin/python3", "app.py"]], model=self.model)
        before = self.foreground()
        with patch("custodian.maintenance.Provider") as broker:
            broker.return_value.propose.return_value = self.response([self.edit(content=payload)])
            result = propose(self.engine, config, "Sandbox escape attempt")
        self.assertEqual(result["status"], "FAILED", result)
        self.assertEqual(before, self.foreground())
        self.assertNotEqual(result["checks"][0]["exit_code"], 0)
        self.assertIsNone(result["branch"])

    def test_no_checks_or_trusted_mode_blocks_model_before_provider_dispatch(self):
        for config in (Config(model=self.model), Config(checks=self.config.checks, model=self.model, execution_mode="trusted")):
            with self.subTest(config=config), patch("custodian.maintenance.Provider") as broker:
                with self.assertRaises(CustodianError):
                    propose(self.engine, config, "Must not dispatch")
                broker.assert_not_called()

    def test_disclosure_policy_excludes_nested_secret_files(self):
        (self.repo / ".env").write_text("SECRET=root-value\n")
        (self.repo / "config").mkdir()
        (self.repo / "config/.env.production").write_text("SECRET=nested-value\n")
        (self.repo / "config/credentials.json").write_text('{"secret":"credential-value"}')
        (self.repo / "config/service.pem").write_text("private key\n")
        config = Config(model=dict(self.model, include=["*"]))
        context = build_context(self.engine, self.engine.capture(), config, "Inspect allowed code")
        paths = {item["path"] for item in context["files"]}
        self.assertIn("app.py", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn("config/.env.production", paths)
        self.assertNotIn("config/credentials.json", paths)
        self.assertNotIn("config/service.pem", paths)


if __name__ == "__main__":
    unittest.main()
