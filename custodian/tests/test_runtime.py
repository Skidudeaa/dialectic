"""Real minimal userspace snapshots and fail-closed validation."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from custodian.runtime import RuntimeError as RuntimeSnapshotError, freeze_runtime, verify_runtime
from custodian.sandbox import Sandbox, SandboxError


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.cleanup)
        self.runtime = self.root / "runtime"
        self.work = self.root / "candidate"
        self.work.mkdir()
        output = subprocess.check_output(["ldd", "/usr/bin/true"], text=True)
        libraries = re.findall(r"(/[A-Za-z0-9_./+-]+)", output)
        self.sources = ["/usr/bin/true", *libraries]
        self.manifest = freeze_runtime(self.runtime, self.sources)

    def cleanup(self):
        for directory, _, _ in os.walk(self.root, followlinks=False):
            Path(directory).chmod(0o700)
        self.temporary.cleanup()

    def test_snapshot_runs_without_host_runtime_fallback(self):
        sandbox = Sandbox(runtime_root=self.runtime)
        result = sandbox.run(["/usr/bin/true"], self.work, 3, True)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["environment"]["runtime"], self.manifest["runtime_id"])
        self.assertEqual(result["environment"]["runtime_reproducibility"], "content-pinned")
        self.assertEqual(result["environment"]["executable_sha256"], hashlib.sha256(
            Path("/usr/bin/true").read_bytes()).hexdigest())
        # The host has a shell, but the explicitly minimal runtime does not.
        missing = sandbox.run(["/bin/sh", "-c", "exit 0"], self.work, 3, True)
        self.assertNotEqual(missing["exit_code"], 0, missing)

    def test_manifest_identity_is_content_stable(self):
        another = freeze_runtime(self.root / "second", list(reversed(self.sources)))
        self.assertEqual(another["runtime_id"], self.manifest["runtime_id"])
        self.assertEqual(verify_runtime(self.runtime), self.manifest)
        self.assertFalse((self.runtime / "rootfs/usr/bin/true").stat().st_mode & 0o222)

    def test_tampered_bytes_rejected_even_by_existing_sandbox_instance(self):
        sandbox = Sandbox(runtime_root=self.runtime)
        self.assertEqual(sandbox.run(["/usr/bin/true"], self.work, 3, True)["exit_code"], 0)
        executable = self.runtime / "rootfs/usr/bin/true"
        executable.chmod(0o755)
        executable.write_bytes(b"tampered")
        executable.chmod(0o555)
        with self.assertRaisesRegex(SandboxError, "content changed"):
            sandbox.run(["/usr/bin/true"], self.work, 3, True)

    def test_extra_files_or_mode_changes_are_rejected(self):
        directory = self.runtime / "rootfs/usr/bin"
        directory.chmod(0o755)
        extra = directory / "hidden"
        extra.write_text("unexpected input")
        directory.chmod(0o555)
        with self.assertRaisesRegex(RuntimeSnapshotError, "inventory changed"):
            verify_runtime(self.runtime)
        directory.chmod(0o755)
        extra.unlink()
        directory.chmod(0o555)
        executable = directory / "true"
        executable.chmod(0o755)
        with self.assertRaisesRegex(RuntimeSnapshotError, "mode changed"):
            verify_runtime(self.runtime)

    def test_manifest_identity_and_symlink_tampering_are_rejected(self):
        manifest_path = self.runtime / "manifest.json"
        manifest_path.chmod(0o644)
        changed = dict(self.manifest, runtime_id="0" * 64)
        manifest_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(RuntimeSnapshotError, "identity mismatch"):
            verify_runtime(self.runtime)
        manifest_path.write_text(json.dumps(self.manifest))
        rootfs = self.runtime / "rootfs"
        rootfs.chmod(0o755)
        link = rootfs / "bin"
        if link.is_symlink():
            link.unlink()
            link.symlink_to("/workspace")
            rootfs.chmod(0o555)
            with self.assertRaisesRegex(RuntimeSnapshotError, "symlink changed"):
                verify_runtime(self.runtime)

    def test_refuses_forbidden_sources_overwrite_and_mixed_runtime(self):
        for source in ("/etc", "/home", "/workspace", "/tmp", "/usr/../etc", "/dev/null"):
            with self.assertRaises(RuntimeSnapshotError):
                freeze_runtime(self.root / "bad", [source])
        with self.assertRaisesRegex(RuntimeSnapshotError, "already exists"):
            freeze_runtime(self.runtime, self.sources)
        with self.assertRaises(SandboxError):
            Sandbox(runtime_root=self.runtime, runtime_paths=["/usr"])
        with self.assertRaises(SandboxError):
            Sandbox(mode="trusted", runtime_root=self.runtime)


if __name__ == "__main__":
    unittest.main()
