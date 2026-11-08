"""Native service management. Rendering never installs or starts anything.

Two scopes. `user` renders a per-user systemd unit (or a launchd agent) and
needs a login session or lingering. `system` renders a systemd system unit in
/etc/systemd/system, managed with plain `systemctl`, started at boot like any
other server daemon — the shape a root-operated host actually runs.
WHY the split exists: a user manager is absent on a headless root box until
someone logs in, so a daemon "activated" there silently dies with the SSH
session. Secrets never enter a unit file; `EnvironmentFile=` names a root-only
file the operator writes.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


class ServiceError(RuntimeError):
    pass


SCOPES = ("user", "system")
SYSTEM_UNIT_DIR = Path("/etc/systemd/system")


def _platform(value=None):
    value = value or sys.platform
    if value in ("linux", "systemd") or value.startswith("linux"):
        return "linux"
    if value in ("darwin", "macos", "launchd"):
        return "darwin"
    raise ServiceError(f"Native services are unsupported on {value}")


def _scope(value, platform):
    if value not in SCOPES:
        raise ServiceError(f"Service scope must be one of {', '.join(SCOPES)}")
    if value == "system" and platform != "linux":
        raise ServiceError("System scope is implemented for systemd only; launchd uses per-user agents")
    return value


def _systemctl(scope):
    return ["systemctl"] + (["--user"] if scope == "user" else [])


def _identity(engine):
    return hashlib.sha256(os.fsencode(Path(engine.repo).resolve())).hexdigest()[:24]


def _name(engine, platform=None):
    key = _identity(engine)
    return f"custodian-{key}.service" if _platform(platform) == "linux" else f"io.custodian.{key}"


def service_path(engine, platform=None, scope="user"):
    platform = _platform(platform)
    scope = _scope(scope, platform)
    if platform == "linux":
        if scope == "system":
            return SYSTEM_UNIT_DIR / _name(engine, platform)
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        if not config_home.is_absolute():
            raise ServiceError("XDG_CONFIG_HOME must be absolute")
        return config_home / "systemd/user" / _name(engine, platform)
    return Path.home() / "Library/LaunchAgents" / (_name(engine, platform) + ".plist")


def _marker(engine):
    return f"custodian-managed:{_identity(engine)}"


def _managed(engine, path):
    if path.is_symlink():
        raise ServiceError(f"Refusing symlink service file: {path}")
    if path.exists():
        if not path.is_file() or _marker(engine) not in path.read_text()[:512]:
            raise ServiceError(f"Refusing to replace an unrelated service file: {path}")
        return True
    return False


def _configuration(engine, config_path):
    try:
        path = Path(config_path).resolve(strict=True)
    except OSError as exc:
        raise ServiceError(f"Configuration is unavailable: {config_path}") from exc
    if not path.is_file():
        raise ServiceError("Configuration must be a regular file")
    repo = Path(engine.repo).resolve()
    if path == repo or repo in path.parents:
        raise ServiceError("Service policy must live outside the foreground repository")
    from .config import Config, ConfigError
    try:
        Config.load(path, repo=repo)
    except ConfigError as exc:
        raise ServiceError(f"Invalid service policy: {exc}") from exc
    return path


def _environment_file(engine, value):
    """A root-only KEY=VALUE file systemd reads; it must exist and live outside the repository."""
    if value is None:
        return None
    try:
        path = Path(value).resolve(strict=True)
    except OSError as exc:
        raise ServiceError(f"Environment file is unavailable: {value}") from exc
    if not path.is_file():
        raise ServiceError("Environment file must be a regular file")
    repo = Path(engine.repo).resolve()
    if path == repo or repo in path.parents:
        raise ServiceError("Environment file must live outside the foreground repository")
    return path


def _quote(value, *, command=False):
    """Quote one systemd setting/argument without shell or specifier expansion."""
    value = str(value)
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    value = value.replace("%", "%%")
    if command:
        value = value.replace("$", "$$")
    return '"' + value + '"'


def _argv(engine, config_path):
    # Keep a virtual environment's interpreter path: resolving its symlink can
    # silently select the system interpreter and lose the installed environment.
    return [str(Path(sys.executable).absolute()), "-m", "custodian", "--repo",
            str(Path(engine.repo).resolve()), "--state-dir", str(Path(engine.state).resolve()),
            "daemon", "--config", str(config_path)]


def render(engine, config_path, platform=None, scope="user", environment_file=None):
    platform = _platform(platform)
    scope = _scope(scope, platform)
    config_path = _configuration(engine, config_path)
    environment_file = _environment_file(engine, environment_file)
    package_root = Path(__file__).resolve().parent.parent
    argv = _argv(engine, config_path)
    if platform == "linux":
        unit = [f"# {_marker(engine)}", "[Unit]", "Description=Custodian repository maintenance",
                "StartLimitIntervalSec=60", "StartLimitBurst=5"]
        if scope == "system":
            # Model requests need the network; everything else runs without it.
            unit += ["After=network-online.target", "Wants=network-online.target"]
        unit += ["", "[Service]", "Type=simple",
                 "WorkingDirectory=" + _quote(package_root),
                 "ExecStart=" + " ".join(_quote(item, command=True) for item in argv),
                 "Environment=PYTHONUNBUFFERED=1"]
        if environment_file is not None:
            unit.append("EnvironmentFile=" + _quote(environment_file))
        unit += ["Restart=on-failure", "RestartSec=5",
                 "KillSignal=SIGTERM", "KillMode=control-group", "TimeoutStopSec=30",
                 "UMask=0077", "", "[Install]",
                 "WantedBy=" + ("multi-user.target" if scope == "system" else "default.target"), ""]
        return "\n".join(unit)
    if environment_file is not None:
        raise ServiceError("EnvironmentFile is a systemd setting; launchd agents read no environment file")
    specification = {
        "Label": _name(engine, platform), "ProgramArguments": argv,
        "WorkingDirectory": str(package_root), "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 5,
        "ProcessType": "Background", "ExitTimeOut": 30,
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(Path(engine.state).resolve() / "service.stdout.log"),
        "StandardErrorPath": str(Path(engine.state).resolve() / "service.stderr.log"),
        "Umask": 0o077,
    }
    xml = plistlib.dumps(specification, sort_keys=False).decode()
    return xml.replace("<plist version=\"1.0\">", f"<!-- {_marker(engine)} -->\n<plist version=\"1.0\">", 1)


def _native(argv, *, check=True):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError(f"Cannot execute {argv[0]}: {exc}") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()[:2000]
        raise ServiceError(f"{' '.join(argv)} failed ({result.returncode}): {detail}")
    return {"returncode": result.returncode, "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()}


def _installed(engine, platform=None, scope="user"):
    path = service_path(engine, platform, scope)
    if not _managed(engine, path):
        raise ServiceError(f"Service is not installed: {path}")
    return path


def install(engine, config_path, start=False, platform=None, scope="user", environment_file=None):
    platform = _platform(platform)
    scope = _scope(scope, platform)
    content = render(engine, config_path, platform, scope=scope, environment_file=environment_file)
    path = service_path(engine, platform, scope)
    _managed(engine, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".custodian-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if platform == "linux":
        _native(_systemctl(scope) + ["daemon-reload"])
    result = {"installed": True, "path": str(path), "name": _name(engine, platform),
              "scope": scope, "started": False}
    if start:
        result.update(globals()["start"](engine, platform=platform, scope=scope))
    return result


def start(engine, platform=None, scope="user"):
    platform = _platform(platform)
    scope = _scope(scope, platform)
    path = _installed(engine, platform, scope)
    name = _name(engine, platform)
    if platform == "linux":
        _native(_systemctl(scope) + ["enable", "--now", name])
    else:
        domain = f"gui/{os.getuid()}"
        target = f"{domain}/{name}"
        loaded = _native(["launchctl", "print", target], check=False)["returncode"] == 0
        _native(["launchctl", "enable", target])
        if not loaded:
            _native(["launchctl", "bootstrap", domain, str(path)])
        else:
            _native(["launchctl", "kickstart", target])
    return {"name": name, "started": True, "path": str(path)}


def stop(engine, platform=None, scope="user"):
    platform = _platform(platform)
    scope = _scope(scope, platform)
    path = _installed(engine, platform, scope)
    name = _name(engine, platform)
    if platform == "linux":
        _native(_systemctl(scope) + ["stop", name])
    else:
        target = f"gui/{os.getuid()}/{name}"
        loaded = _native(["launchctl", "print", target], check=False)["returncode"] == 0
        if loaded:
            _native(["launchctl", "bootout", target])
    return {"name": name, "stopped": True, "path": str(path)}


def status(engine, platform=None, scope="user"):
    platform = _platform(platform)
    scope = _scope(scope, platform)
    path = service_path(engine, platform, scope)
    installed = _managed(engine, path)
    name = _name(engine, platform)
    result = {"name": name, "installed": installed, "path": str(path), "scope": scope, "running": False}
    if not installed:
        return result
    if platform == "linux":
        observation = _native(_systemctl(scope) + ["show", name, "--property=ActiveState,SubState,MainPID,UnitFileState"], check=False)
        properties = dict(line.split("=", 1) for line in observation["stdout"].splitlines() if "=" in line)
        result.update(properties=properties, running=properties.get("ActiveState") == "active")
    else:
        observation = _native(["launchctl", "print", f"gui/{os.getuid()}/{name}"], check=False)
        result["running"] = observation["returncode"] == 0 and "state = running" in observation["stdout"]
    result["supervisor"] = observation
    return result


def uninstall(engine, platform=None, scope="user"):
    platform = _platform(platform)
    scope = _scope(scope, platform)
    path = service_path(engine, platform, scope)
    if not _managed(engine, path):
        return {"installed": False, "removed": False, "path": str(path), "scope": scope}
    if platform == "linux":
        _native(_systemctl(scope) + ["disable", "--now", _name(engine, platform)])
    else:
        stop(engine, platform=platform, scope=scope)
    path.unlink()
    if platform == "linux":
        _native(_systemctl(scope) + ["daemon-reload"])
    return {"installed": False, "removed": True, "path": str(path), "scope": scope}


def health(engine, scope="user"):
    result = {"python": sys.version.split()[0], "python_executable": sys.executable,
              "git": shutil.which("git"), "bubblewrap": shutil.which("bwrap"),
              "repository": str(engine.repo), "state": str(engine.state), "service_scope": scope}
    try:
        platform = _platform()
        scope = _scope(scope, platform)
        binary = "systemctl" if platform == "linux" else "launchctl"
        result["supervisor_binary"] = shutil.which(binary)
        if result["supervisor_binary"]:
            argv = _systemctl(scope) + ["show-environment"] if platform == "linux" else [binary, "print", f"gui/{os.getuid()}"]
            observation = _native(argv, check=False)
            # Do not expose supervisor environment variables or their values.
            result["supervisor_available"] = observation["returncode"] == 0
            result["supervisor_error"] = observation["stderr"][:1000] if observation["returncode"] else None
        else:
            result["supervisor_available"] = False
    except ServiceError as exc:
        result.update(supervisor_available=False, supervisor_error=str(exc))
    return result
