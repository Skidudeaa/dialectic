"""External, validated execution policy. Candidate files never supply authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
import tomllib


class ConfigError(ValueError):
    pass


def _number(value, name, *, minimum=0, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{name} must be a finite number")
    if value < minimum or (positive and value == 0):
        raise ConfigError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return float(value)


def _argv(value, name):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v or "\0" in v for v in value):
        raise ConfigError(f"{name} must be a nonempty array of nonempty argument strings")
    return list(value)


@dataclass(frozen=True)
class Job:
    name: str
    command: list[str]
    interval_seconds: float = 86400
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    checks: list[list[str]] = field(default_factory=list)
    protected: list[str] = field(default_factory=lambda: ["SPEC.md", "AGENTS.md", "CLAUDE.md", "tests"])
    quiet_seconds: float = 600
    poll_seconds: float = 5
    timeout_seconds: float = 120
    execution_mode: str = "isolated"
    runtime_paths: list[str] = field(default_factory=list)
    runtime_root: str | None = None
    jobs: list[Job] = field(default_factory=list)
    model: dict = field(default_factory=dict)
    max_retries: int = 2
    retry_backoff_seconds: float = 60
    source: str | None = field(default=None, compare=False)

    @classmethod
    def load(cls, path, repo=None):
        path = Path(path).expanduser().resolve()
        if repo is not None and path.is_relative_to(Path(repo).resolve()):
            raise ConfigError("Execution policy must live outside the foreground repository")
        try:
            with path.open("rb") as stream:
                data = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Cannot load policy: {exc}") from exc
        return cls.from_dict(data, source=str(path), repo=repo)

    @classmethod
    def from_dict(cls, data, *, source=None, repo=None):
        if not isinstance(data, dict):
            raise ConfigError("Policy must be a table")
        allowed = set(cls.__dataclass_fields__) - {"source"}
        unknown = set(data) - allowed
        if unknown:
            raise ConfigError("Unknown policy fields: " + ", ".join(sorted(unknown)))
        defaults = cls()
        values = dict(data)
        checks = values.get("checks", defaults.checks)
        if not isinstance(checks, list):
            raise ConfigError("checks must be an array of argument arrays")
        values["checks"] = [_argv(v, "checks") for v in checks]
        protected = values.get("protected", defaults.protected)
        if not isinstance(protected, list) or any(not isinstance(v, str) or not v or "\0" in v for v in protected):
            raise ConfigError("protected must contain repository-relative paths")
        for path in protected:
            if Path(path).is_absolute() or any(part in ("", ".", "..") for part in path.rstrip("/").split("/")):
                raise ConfigError(f"Protected path must be a normalized relative path: {path}")
        values["protected"] = [p.rstrip("/") for p in protected]
        for name in ("quiet_seconds", "poll_seconds", "timeout_seconds", "retry_backoff_seconds"):
            values[name] = _number(values.get(name, getattr(defaults, name)), name,
                                   positive=name != "quiet_seconds")
        mode = values.get("execution_mode", defaults.execution_mode)
        if mode not in ("isolated", "trusted"):
            raise ConfigError("execution_mode must be isolated or trusted")
        values["execution_mode"] = mode
        retries = values.get("max_retries", defaults.max_retries)
        if type(retries) is not int or not 0 <= retries <= 10:
            raise ConfigError("max_retries must be an integer from 0 to 10")
        paths = values.get("runtime_paths", [])
        if not isinstance(paths, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
            raise ConfigError("runtime_paths must be absolute directory paths")
        resolved = [str(Path(p).resolve()) for p in paths]
        for path in map(Path, resolved):
            if not path.is_dir():
                raise ConfigError(f"Runtime path is not a directory: {path}")
            if path == Path("/"):
                raise ConfigError("The host root cannot be a runtime path")
            if repo is not None:
                target = Path(repo).resolve()
                if path.is_relative_to(target) or target.is_relative_to(path):
                    raise ConfigError("Runtime paths must not expose the foreground repository")
        values["runtime_paths"] = resolved
        runtime_root = values.get("runtime_root")
        if runtime_root is not None:
            if not isinstance(runtime_root, str) or not Path(runtime_root).is_absolute():
                raise ConfigError("runtime_root must be an absolute runtime artifact directory")
            runtime_root = Path(runtime_root).resolve()
            if not runtime_root.is_dir():
                raise ConfigError("runtime_root directory does not exist")
            if repo is not None:
                target = Path(repo).resolve()
                if runtime_root.is_relative_to(target) or target.is_relative_to(runtime_root):
                    raise ConfigError("runtime_root must not expose the foreground repository")
            values["runtime_root"] = str(runtime_root)
        raw_jobs = values.get("jobs", [])
        if not isinstance(raw_jobs, list):
            raise ConfigError("jobs must be an array of job tables")
        jobs, names = [], set()
        for raw in raw_jobs:
            if not isinstance(raw, dict) or set(raw) - {"name", "command", "interval_seconds", "enabled"}:
                raise ConfigError("Each job requires name/command and optional interval_seconds/enabled")
            name = raw.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
                raise ConfigError("Job names must be 1–64 letters, numbers, underscores or hyphens")
            if name == "verify" or name in names:
                raise ConfigError(f"Reserved or duplicate job name: {name}")
            names.add(name)
            enabled = raw.get("enabled", True)
            if type(enabled) is not bool:
                raise ConfigError("Job enabled must be boolean")
            jobs.append(Job(name, _argv(raw.get("command"), f"job {name} command"),
                            _number(raw.get("interval_seconds", 86400), "interval_seconds", positive=True), enabled))
        if any(j.enabled for j in jobs) and not values["checks"]:
            raise ConfigError("Enabled maintenance jobs require independent checks")
        values["jobs"] = jobs
        if not isinstance(values.get("model", {}), dict):
            raise ConfigError("model must be a table")
        model = values.get("model", {})
        if "auto_on_failure" in model and type(model["auto_on_failure"]) is not bool:
            raise ConfigError("model.auto_on_failure must be boolean")
        if any(key.lower() in ("api_key", "token", "secret", "password") for key in model):
            raise ConfigError("Model credentials belong in an environment variable, not policy")
        values["source"] = source
        return cls(**values)

    def to_dict(self):
        result = asdict(self)
        result.pop("source", None)
        return result

    def digest(self):
        policy = self.to_dict()
        if self.runtime_root:
            try:
                manifest = (Path(self.runtime_root) / "manifest.json").read_bytes()
            except OSError as exc:
                raise ConfigError(f"Cannot read runtime manifest: {exc}") from exc
            policy["runtime_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
