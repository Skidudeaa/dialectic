"""Fail-closed local execution boundary for candidate producers and verifiers.

Linux bubblewrap creates an empty filesystem and process/network namespaces.
Only runtime directories and the candidate are mounted. The controller's state,
foreground checkout, environment, and credentials are not inherited. Explicit
runtime mounts are trusted configuration, not paths selected by model output.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import selectors
import shutil
import signal
import subprocess
import tempfile
import time

from .runtime import executable_digest, verify_runtime


class SandboxError(RuntimeError):
    pass


class Sandbox:
    def __init__(self, mode="isolated", runtime_paths=None, max_output_bytes=4 * 1024 * 1024,
                 runtime_root=None):
        if mode not in {"isolated", "trusted"}:
            raise SandboxError("Execution mode must be isolated or trusted")
        if not isinstance(max_output_bytes, int) or max_output_bytes < 1:
            raise SandboxError("Output limit must be positive")
        self.mode = mode
        self.max_output_bytes = max_output_bytes
        self.runtime_root = Path(runtime_root).absolute() if runtime_root is not None else None
        if self.runtime_root is not None and (mode != "isolated" or runtime_paths):
            raise SandboxError("A pinned runtime requires isolated mode and cannot mix host runtime mounts")
        self._runtime_manifest = self._validate_runtime()
        self.runtime_paths = []
        for value in runtime_paths or []:
            path = Path(value).resolve(strict=True)
            if not path.is_dir() or path == Path("/") or path in {
                Path("/home"), Path("/root"), Path("/workspace"), Path("/etc"),
                Path("/proc"), Path("/sys"), Path("/dev"), Path("/run"), Path("/tmp"),
            }:
                raise SandboxError(f"Runtime mount must be a dedicated dependency directory: {path}")
            if any((path / marker).exists() for marker in (".git", "objects.git", "events.sqlite3")):
                raise SandboxError(f"A repository or state directory is not a runtime mount: {path}")
            self.runtime_paths.append(path)
        self.runtime_paths = sorted(set(self.runtime_paths))
        self._probe = None

    def _validate_runtime(self):
        if self.runtime_root is None:
            return None
        try:
            return verify_runtime(self.runtime_root)
        except (OSError, ValueError) as exc:
            raise SandboxError(f"Invalid pinned runtime: {exc}") from exc

    @staticmethod
    def _environment():
        return {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin",
                "HOME": "/tmp/home", "TMPDIR": "/tmp", "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}

    def _prefix(self, pinned=True):
        executable = shutil.which("bwrap")
        if not executable or platform.system() != "Linux":
            raise SandboxError("Isolated execution requires Linux and bubblewrap; trusted mode is explicit")
        command = [executable, "--unshare-all", "--unshare-user", "--disable-userns",
                   "--die-with-parent", "--new-session", "--cap-drop", "ALL",
                   "--clearenv"]
        if self.runtime_root is not None and pinned:
            self._runtime_manifest = self._validate_runtime()
            command += ["--ro-bind", str(self.runtime_root / "rootfs"), "/"]
        else:
            for name in ("usr", "bin", "sbin", "lib", "lib64"):
                path = Path("/") / name
                if path.is_symlink():
                    command += ["--symlink", os.readlink(path), str(path)]
                elif path.exists():
                    command += ["--ro-bind", str(path), str(path)]
            # WHY: Debian-family hosts route /usr/bin/python3 (and pytest, node, ...)
            # through /etc/alternatives symlinks. Without this one directory the
            # interpreter named in a check is a dangling link inside the namespace
            # and every check fails with "execvp: No such file or directory" —
            # measured on a host whose /usr/bin/python3 -> /etc/alternatives/python3.
            # The directory holds distribution symlinks and a README, never account,
            # DNS or secret data, so it is the only /etc entry mounted (read-only).
            alternatives = Path("/etc/alternatives")
            if alternatives.is_dir() and not alternatives.is_symlink():
                command += ["--ro-bind", str(alternatives), str(alternatives)]
            for path in self.runtime_paths:
                command += ["--ro-bind", str(path), str(path)]
        command += ["--proc", "/proc", "--dev", "/dev", "--size", str(256 * 1024 * 1024),
                    "--tmpfs", "/tmp", "--dir", "/tmp/home", "--dir", "/etc"]
        # No host /etc mount beyond /etc/alternatives: the rest holds account, DNS and secret data.
        for key, value in self._environment().items():
            command += ["--setenv", key, value]
        return command

    def probe(self):
        """Actually create the namespaces; finding a binary is not readiness."""
        if self._probe is not None:
            return dict(self._probe)
        if self.mode == "trusted":
            self._probe = {"available": True, "mode": "trusted", "enforced": False}
            return dict(self._probe)
        # Probe kernel namespace capability using the host runtime. A minimal
        # pinned runtime need not contain /bin/true; actual commands use only it.
        self._validate_runtime()
        command = self._prefix(pinned=False) + ["--dir", "/work", "--chdir", "/work", "--", "/bin/true"]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=self._environment(), timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxError(f"Sandbox probe failed: {exc}") from exc
        if result.returncode:
            raise SandboxError("Sandbox probe failed: " + result.stderr.decode(errors="replace").strip())
        version = subprocess.run([shutil.which("bwrap"), "--version"], capture_output=True,
                                 text=True, timeout=5, env=self._environment()).stdout.strip()
        self._probe = {"available": True, "mode": "isolated", "enforced": True,
                       "backend": "bubblewrap", "version": version}
        return dict(self._probe)

    def _identity(self, argv, directory, readonly):
        self._runtime_manifest = self._validate_runtime()
        binary = argv[0]
        if binary.startswith("/work/"):
            path = directory / binary.removeprefix("/work/")
        elif "/" in binary and not binary.startswith("/"):
            path = directory / binary
        else:
            path = Path(binary) if binary.startswith("/") else Path(
                shutil.which(binary, path=self._environment()["PATH"]) or binary)
        digest = None
        if self._runtime_manifest and not binary.startswith("/work/") and not (
                "/" in binary and not binary.startswith("/")):
            candidates = [binary] if binary.startswith("/") else [
                str(Path(prefix) / binary) for prefix in self._environment()["PATH"].split(":")]
            digest = next((value for candidate in candidates
                           if (value := executable_digest(self._runtime_manifest, candidate))), None)
        elif path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        descriptor = {"mode": self.mode, "backend": self.probe(), "readonly_candidate": readonly,
                      "network": "none" if self.mode == "isolated" else "host",
                      "runtime": "host-runtime-unpinned", "runtime_reproducibility": "UNVERIFIED",
                      "kernel": platform.release(), "machine": platform.machine(),
                      "executable_sha256": digest,
                      "runtime_paths": [str(p) for p in self.runtime_paths],
                      "environment": self._environment(),
                      "immutable_execution": self.mode == "isolated" and readonly}
        if self._runtime_manifest:
            descriptor.update(runtime=self._runtime_manifest["runtime_id"],
                              runtime_reproducibility="content-pinned")
        descriptor["fingerprint"] = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()
        return descriptor

    def run(self, argv, directory, timeout, readonly, cancel=None):
        if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(a, str) and "\0" not in a for a in argv):
            raise SandboxError("Command must be a nonempty argument array")
        if not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or timeout <= 0:
            raise SandboxError("Timeout must be positive and finite")
        directory = Path(directory).resolve(strict=True)
        if not directory.is_dir():
            raise SandboxError("Candidate must be a directory")
        if self.runtime_root is not None and (directory.is_relative_to(self.runtime_root)
                                             or self.runtime_root.is_relative_to(directory)):
            raise SandboxError("Pinned runtime must not overlap the candidate workspace")
        for runtime in self.runtime_paths:
            if directory.is_relative_to(runtime) or runtime.is_relative_to(directory):
                raise SandboxError("Runtime mounts must not overlap the candidate workspace")
        git = directory / ".git"
        if git.is_symlink():
            raise SandboxError("Candidate .git must not be a symlink")
        environment = self._identity(argv, directory, readonly)
        with tempfile.TemporaryDirectory(prefix="custodian-masked-git-") as empty:
            marker = Path(empty) / "empty"
            marker.touch(mode=0o444)
            if self.mode == "isolated":
                command = self._prefix() + ["--ro-bind" if readonly else "--bind", str(directory), "/work"]
                if self._runtime_manifest and self._runtime_manifest["runtime_id"] != environment["runtime"]:
                    raise SandboxError("Pinned runtime changed while preparing execution")
                if git.is_dir():
                    command += ["--ro-bind", empty, "/work/.git"]
                elif git.exists():
                    command += ["--ro-bind", str(marker), "/work/.git"]
                command += ["--chdir", "/work", "--", *argv]
                cwd = None
            else:
                command, cwd = list(argv), directory
            try:
                process = subprocess.Popen(command, cwd=cwd, env=self._environment(),
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, start_new_session=True)
            except OSError as exc:
                raise SandboxError(f"Command could not start: {exc}") from exc
            out, err = bytearray(), bytearray()
            timed_out = cancelled = output_limited = False
            deadline = time.monotonic() + timeout
            selector = selectors.DefaultSelector()
            for stream, output in ((process.stdout, out), (process.stderr, err)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, output)

            def stop():
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

            try:
                while selector.get_map() or process.poll() is None:
                    if not (timed_out or cancelled or output_limited):
                        if cancel and cancel():
                            cancelled = True
                            stop()
                        elif time.monotonic() >= deadline:
                            timed_out = True
                            stop()
                    for key, _ in selector.select(0.05):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        remaining = self.max_output_bytes - len(out) - len(err)
                        key.data.extend(data[:remaining])
                        if len(data) > remaining:
                            output_limited = True
                            stop()
                    # Kill detached/background descendants after the initial command exits.
                    if process.poll() is not None:
                        stop()
                code = process.wait()
            finally:
                stop()
                process.wait()
                selector.close()
                for stream in (process.stdout, process.stderr):
                    if not stream.closed:
                        stream.close()
        return {"exit_code": code, "timed_out": timed_out, "cancelled": cancelled,
                "output_limited": output_limited, "stdout": bytes(out), "stderr": bytes(err),
                "environment": environment}
