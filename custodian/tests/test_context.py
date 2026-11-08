"""Evidence queries must preserve uncertainty and never invent continuity."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from custodian import context
from custodian.engine import Engine


class ContextFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Context tests"),
                     ("config", "user.email", "context@example.invalid")):
            subprocess.check_call(["git", "-C", str(self.repo), *args])
        (self.repo / "app.py").write_text("def before(value: int):\n    return value + 1\n")
        subprocess.check_call(["git", "-C", str(self.repo), "add", "."])
        subprocess.check_call(["git", "-C", str(self.repo), "commit", "-qm", "input"])
        self.engine = Engine(self.repo, self.root / "state")

    def attempted(self, status="FAILED"):
        snap = self.engine.capture()
        item = dict(id="attempt_fixture", input_tree=snap["tree"], output_tree=snap["tree"],
                    status="RUNNING", intent="Declared intent", checks=[], branch=None)
        self.engine.event("attempt_started", item)
        item = dict(item, status=status)
        self.engine.event("attempt_finished", item)
        return item


class ContextTests(ContextFixture):
    def test_busy_state_does_not_wait_or_assert_current_applicability(self):
        item = self.attempted()
        with self.engine.lease():
            view = context.state(self.engine)
        self.assertEqual(view["freshness"], "writer_active")
        self.assertIsNone(view["current_tree"])
        self.assertIsNone(view["applicable"])
        self.assertEqual(view["last_failure"]["id"], item["id"])

    def test_later_edit_cannot_inherit_passed_candidate(self):
        self.attempted("PASSED")
        self.assertTrue(context.state(self.engine)["applicable"])
        (self.repo / "app.py").write_text("CHANGED = True\n")
        view = context.state(self.engine)
        self.assertFalse(view["applicable"])
        self.assertEqual(view["latest"]["status"], "PASSED")

    def test_failed_observation_retains_evidence_without_applicability(self):
        self.attempted("PASSED")
        with mock.patch.object(self.engine, "status", side_effect=RuntimeError("Import unavailable")):
            view = context.state(self.engine)
        self.assertEqual(view["freshness"], "observation_unavailable")
        self.assertIsNone(view["applicable"])
        self.assertEqual(view["latest"]["status"], "PASSED")

    def test_unfinished_attempt_is_unknown_even_when_start_claims_running(self):
        self.engine.event("attempt_started", dict(id="interrupted", status="RUNNING", input_tree="abc"))
        data = context.attempt(self.engine, "interrupted")
        self.assertEqual(data["status"], "INCOMPLETE")
        self.assertFalse(data["outcome_recorded"])
        self.assertEqual(context.history(self.engine)["unfinished"], ["interrupted"])

    def test_decisions_require_real_attempt_and_remain_explicit(self):
        with self.assertRaises(context.ContextError):
            context.record_decision(self.engine, "missing", "Reject", "No evidence")
        item = self.attempted()
        record = context.record_decision(self.engine, item["id"], "Reject approach", "Check failed",
                                         ["Keep the failed implementation"])
        data = context.attempt(self.engine, item["id"])
        self.assertEqual(data["decisions"][0]["id"], record["id"])
        self.assertEqual(context.decisions(self.engine)["provenance"], "explicitly_recorded_not_inferred")
        self.assertEqual(data["status"], "FAILED")

    def test_budget_bounds_utf8_and_marks_detail_loss(self):
        data = context.bounded(dict(id="attempt1", status="FAILED", reason="😃\"\\" * 10_000), 512)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["status"], "FAILED")
        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()), 512)

    def test_map_reads_last_captured_input_not_current_source(self):
        snap = self.engine.capture()
        (self.repo / "app.py").write_text("def after():\n    raise RuntimeError('not executed')\n")
        data = context.repo_map(self.engine)
        self.assertEqual(data["tree"], snap["tree"])
        self.assertEqual([s["name"] for s in data["symbols"]], ["before"])

    def test_hook_injects_start_only_and_does_not_read_transcript_path(self):
        self.attempted()
        payload = dict(cwd=str(self.repo), session_id="session", transcript_path="/not/read")
        output = context.hook_payload(self.engine, "SessionStart", payload)
        packet = output["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(packet), 8192)
        self.assertEqual(json.loads(packet)["latest"]["status"], "FAILED")
        self.assertEqual(context.hook_payload(self.engine, "Stop", payload), {})
        self.assertEqual(context.hook_payload(self.engine, "PreCompact", payload), {})
        nested = self.repo / "nested"
        nested.mkdir()
        self.assertIn("hookSpecificOutput", context.hook_payload(self.engine, "SessionStart", dict(payload, cwd=str(nested))))
        self.assertTrue(all(not e["transcript_ingested"] for e in self.engine.events("lifecycle")))
        with self.assertRaises(context.ContextError):
            context.hook_payload(self.engine, "SessionStart", dict(payload, cwd=str(self.root)))

    def test_context_limits_reject_invalid_values(self):
        for limit in (0, 101, True, "20"):
            with self.assertRaises(context.ContextError):
                context.history(self.engine, limit=limit)
        with self.assertRaises(context.ContextError):
            context.state(self.engine, max_bytes=0)


if __name__ == "__main__":
    unittest.main()
