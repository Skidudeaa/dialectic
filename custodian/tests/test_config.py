from pathlib import Path
import tempfile
import unittest

from custodian.config import Config, ConfigError


class ConfigTests(unittest.TestCase):
    def test_external_policy_loads_and_defaults_to_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            path = root / "policy.toml"
            path.write_text('checks = [["python3", "-m", "unittest"]]\n')
            config = Config.load(path, repo=repo)
            self.assertEqual(config.execution_mode, "isolated")
            self.assertIn("tests", config.protected)
            self.assertEqual(config.source, str(path))
            inside = repo / "policy.toml"
            inside.write_text(path.read_text())
            with self.assertRaises(ConfigError):
                Config.load(inside, repo=repo)

    def test_unknown_fields_and_invalid_command_shapes_fail_closed(self):
        for data in ({"check": [["true"]]}, {"checks": ["true"]}, {"checks": [[]]},
                     {"checks": [["true", "\0"]]}, {"execution_mode": "automatic"},
                     {"poll_seconds": 0}, {"timeout_seconds": True}, {"quiet_seconds": float("nan")},
                     {"max_retries": -1}, {"protected": ["../elsewhere"]},
                     {"model": {"api_key": "must-not-be-in-policy"}}):
            with self.subTest(data=data), self.assertRaises(ConfigError):
                Config.from_dict(data)

    def test_jobs_require_checks_and_unique_names(self):
        with self.assertRaises(ConfigError):
            Config.from_dict({"jobs": [{"name": "format", "command": ["formatter"]}]})
        with self.assertRaises(ConfigError):
            Config.from_dict({"checks": [["true"]], "jobs": [{"name": "verify", "command": ["true"]}]})
        config = Config.from_dict({"checks": [["true"]], "jobs": [
            {"name": "format", "command": ["formatter"], "interval_seconds": 1800}]})
        self.assertEqual(config.jobs[0].interval_seconds, 1800)

    def test_policy_digest_changes_with_checks_runtime_and_model(self):
        baseline = Config.from_dict({"checks": [["true"]]})
        for data in ({"checks": [["false"]]}, {"checks": [["true"]], "execution_mode": "trusted"},
                     {"checks": [["true"]], "model": {"auto_on_failure": True}}):
            self.assertNotEqual(baseline.digest(), Config.from_dict(data).digest())

    def test_runtime_mount_cannot_include_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            for path in (root, repo):
                with self.assertRaises(ConfigError):
                    Config.from_dict({"runtime_paths": [str(path)]}, repo=repo)

    def test_runtime_manifest_identity_participates_in_policy_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text('{"runtime_id":"one"}')
            config = Config.from_dict({"runtime_root": str(root)})
            before = config.digest()
            manifest.write_text('{"runtime_id":"two"}')
            self.assertNotEqual(before, config.digest())


if __name__ == "__main__":
    unittest.main()
