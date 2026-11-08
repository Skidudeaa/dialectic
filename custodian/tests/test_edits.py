"""Edit admission must finish validation before mutating any candidate bytes."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from custodian.edits import apply_edits


class EditApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        (self.candidate / "app.py").write_text("original\n")

    def edit(self, path="app.py", content="replacement\n"):
        target = self.candidate / path
        return dict(path=path, content=content,
                    expected_sha256=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None)

    def test_later_bad_precondition_prevents_earlier_valid_mutation(self):
        bad = self.edit("other.py", "created\n")
        bad["expected_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            apply_edits(self.candidate, [self.edit(), bad])
        self.assertEqual((self.candidate / "app.py").read_text(), "original\n")
        self.assertFalse((self.candidate / "other.py").exists())

    def test_symlink_target_and_ancestor_cannot_escape_candidate(self):
        external = self.root / "outside"
        external.mkdir()
        (external / "file").write_text("outside\n")
        (self.candidate / "direct").symlink_to(external / "file")
        (self.candidate / "nested").symlink_to(external, target_is_directory=True)
        for path in ("direct", "nested/file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                apply_edits(self.candidate, [dict(path=path, expected_sha256=hashlib.sha256(b"outside\n").hexdigest(), content="escaped")])
        self.assertEqual((external / "file").read_text(), "outside\n")

    def test_conflicting_new_file_and_child_are_rejected_before_any_mutation(self):
        operations = [self.edit(), self.edit("new", "a file"), self.edit("new/child", "a child")]
        with self.assertRaises((ValueError, OSError)):
            apply_edits(self.candidate, operations)
        self.assertEqual((self.candidate / "app.py").read_text(), "original\n")
        self.assertFalse((self.candidate / "new").exists())

    def test_existing_file_ancestor_is_rejected_before_any_mutation(self):
        operations = [self.edit(), dict(path="app.py/child", expected_sha256=None, content="impossible")]
        with self.assertRaises((ValueError, OSError)):
            apply_edits(self.candidate, operations)
        self.assertEqual((self.candidate / "app.py").read_text(), "original\n")


if __name__ == "__main__":
    unittest.main()
