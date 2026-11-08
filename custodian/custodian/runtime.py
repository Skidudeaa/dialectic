"""Content-pinned, recorder-owned runtime files for isolated execution.

The copied filesystem is immutable to sandbox workers. Its owner can deliberately
replace it; validation detects ordinary offline changes before every execution.
The manifest pins userspace bytes, not the host kernel or external services.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import stat
import tempfile


class RuntimeError(ValueError):
    pass


_ROOTS = {"usr", "bin", "sbin", "lib", "lib64", "opt"}
_MOUNTPOINTS = {"/", "/work", "/tmp", "/proc", "/dev", "/etc"}


def _allowed(path):
    pure = PurePosixPath(path)
    return pure.is_absolute() and ".." not in pure.parts and len(pure.parts) > 1 and pure.parts[1] in _ROOTS


def _safe_path(value):
    if not isinstance(value, str) or "\0" in value or not value.startswith("/"):
        raise RuntimeError("Runtime paths must be absolute strings")
    if posixpath.normpath(value) != value or value.startswith("//"):
        raise RuntimeError(f"Runtime path is not canonical: {value}")
    return value


def _identity(entries):
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def freeze_runtime(destination: Path, sources: list[str]):
    """Copy selected runtime files and symlink targets; never overwrite a snapshot."""
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"Runtime destination already exists: {destination}")
    if not sources:
        raise RuntimeError("Select at least one runtime source")
    selected = sorted(set(_safe_path(str(p)) for p in sources))
    for source in selected:
        if not _allowed(source) or source == "/opt":
            raise RuntimeError(f"Not an allowed runtime source: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".custodian-runtime-", dir=destination.parent))
    rootfs = temporary / "rootfs"
    rootfs.mkdir()
    entries = {}
    traversed = set()

    def directory(path, mode=0o755):
        path = str(path)
        if path in entries:
            if entries[path]["kind"] != "directory":
                raise RuntimeError(f"Conflicting runtime entries: {path}")
            return
        parent = str(PurePosixPath(path).parent)
        if path != "/":
            directory(parent)
        physical = rootfs / path.lstrip("/")
        physical.mkdir(exist_ok=True)
        entries[path] = {"path": path, "kind": "directory", "mode": mode & 0o555,
                         "source_mode": mode}

    def visit(raw, recurse=True):
        raw = _safe_path(str(raw))
        if not _allowed(raw):
            raise RuntimeError(f"Runtime symlink escapes permitted roots: {raw}")
        # Materialize ancestor symlinks as namespace aliases without copying their
        # entire target directories for each explicitly selected leaf file.
        pieces = PurePosixPath(raw).parts
        for count in range(2, len(pieces)):
            ancestor = Path(*pieces[:count])
            if ancestor.is_symlink():
                visit(str(ancestor), recurse=False)
        source = Path(raw)
        info = source.lstat()
        parent = source.parent.resolve(strict=True)
        actual = str(parent / source.name)
        if not _allowed(actual):
            raise RuntimeError(f"Runtime path escapes permitted roots: {raw}")
        directory(str(parent), stat.S_IMODE(parent.stat().st_mode))
        physical = rootfs / actual.lstrip("/")
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(source)
            lexical = posixpath.normpath(posixpath.join(str(parent), target))
            if not _allowed(lexical):
                raise RuntimeError(f"Runtime symlink escapes permitted roots: {raw} -> {target}")
            # Resolve first to reject cycles before recursive traversal.
            resolved = source.resolve(strict=True)
            if not _allowed(str(resolved)):
                raise RuntimeError(f"Runtime symlink escapes permitted roots: {raw}")
            if actual not in entries:
                physical.symlink_to(target)
                entries[actual] = {"path": actual, "kind": "symlink", "mode": mode, "target": target}
            visit(lexical, recurse=recurse)
        elif stat.S_ISDIR(info.st_mode):
            if any((source / marker).exists() for marker in (".git", "objects.git", "events.sqlite3")):
                raise RuntimeError(f"Repository/state data is not a runtime source: {source}")
            directory(actual, mode)
            if recurse and actual not in traversed:
                traversed.add(actual)
                for child in sorted(source.iterdir()):
                    visit(str(child), recurse=True)
        elif stat.S_ISREG(info.st_mode):
            if actual not in entries:
                digest = hashlib.sha256()
                fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as incoming, physical.open("xb") as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        outgoing.write(chunk)
                        digest.update(chunk)
                after = source.lstat()
                if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode) != (
                        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode):
                    raise RuntimeError(f"Runtime source changed while copying: {source}")
                frozen_mode = mode & 0o555
                physical.chmod(frozen_mode)
                entries[actual] = {"path": actual, "kind": "file", "mode": frozen_mode,
                                   "source_mode": mode, "sha256": digest.hexdigest()}
        else:
            raise RuntimeError(f"Special files are not runtime inputs: {source}")

    try:
        directory("/")
        for path in sorted(_MOUNTPOINTS - {"/"}):
            directory(path)
        for source in selected:
            visit(source)
        # Keep standard merged-/usr aliases without recursively importing all of
        # their contents. These aliases can be dangling in a minimal snapshot.
        for path in ("/bin", "/sbin", "/lib", "/lib64"):
            if Path(path).is_symlink():
                visit(path, recurse=False)
        ordered = [entries[k] for k in sorted(entries)]
        manifest = {"version": 1, "runtime_id": _identity(ordered), "sources": selected, "entries": ordered}
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        (temporary / "manifest.json").chmod(0o444)
        for entry in sorted(ordered, key=lambda e: len(e["path"]), reverse=True):
            if entry["kind"] == "directory":
                (rootfs / entry["path"].lstrip("/")).chmod(entry["mode"])
        verify_runtime(temporary)
        if destination.exists():
            raise RuntimeError(f"Runtime destination appeared during freeze: {destination}")
        temporary.rename(destination)
        return manifest
    except BaseException:
        # The caller owns this private temporary tree. Restore directory write
        # permissions solely to remove our failed, unpublished snapshot.
        for path, dirs, _ in os.walk(temporary, followlinks=False):
            Path(path).chmod(0o700)
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_runtime(runtime_root: Path):
    root = Path(runtime_root)
    if root.is_symlink() or (root / "rootfs").is_symlink() or (root / "manifest.json").is_symlink():
        raise RuntimeError("Runtime root, rootfs and manifest must not be symlinks")
    try:
        manifest = json.loads((root / "manifest.json").read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read runtime manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("entries"), list):
        raise RuntimeError("Unsupported runtime manifest")
    entries = manifest["entries"]
    if manifest.get("runtime_id") != _identity(entries):
        raise RuntimeError("Runtime manifest identity mismatch")
    expected = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("Invalid runtime manifest entry")
        path = _safe_path(entry.get("path"))
        if path in expected or not (_allowed(path) or path in _MOUNTPOINTS):
            raise RuntimeError(f"Forbidden or duplicate runtime entry: {path}")
        if entry.get("kind") not in {"file", "directory", "symlink"}:
            raise RuntimeError(f"Invalid runtime entry kind: {path}")
        if path in _MOUNTPOINTS and entry["kind"] != "directory":
            raise RuntimeError(f"Runtime mountpoint must be an empty directory: {path}")
        expected[path] = entry
    for required in _MOUNTPOINTS:
        if required not in expected:
            raise RuntimeError(f"Missing runtime mountpoint: {required}")
    rootfs = root / "rootfs"
    actual = {"/"}
    for directory, dirs, files in os.walk(rootfs, followlinks=False):
        for name in dirs + files:
            actual.add("/" + str((Path(directory) / name).relative_to(rootfs)))
    if actual != set(expected):
        raise RuntimeError("Runtime file inventory changed")
    for path, entry in expected.items():
        physical = rootfs / path.lstrip("/")
        for ancestor in PurePosixPath(path).parents:
            if expected.get(str(ancestor), {}).get("kind") != "directory":
                raise RuntimeError(f"Runtime file has a nondirectory ancestor: {path}")
        try:
            info = physical.lstat()
            if stat.S_IMODE(info.st_mode) != entry.get("mode"):
                raise RuntimeError(f"Runtime mode changed: {path}")
            if entry["kind"] == "directory":
                if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o222:
                    raise RuntimeError(f"Runtime directory is not frozen: {path}")
            elif entry["kind"] == "symlink":
                if not stat.S_ISLNK(info.st_mode) or os.readlink(physical) != entry.get("target"):
                    raise RuntimeError(f"Runtime symlink changed: {path}")
                target = posixpath.normpath(posixpath.join(str(PurePosixPath(path).parent), entry["target"]))
                if not _allowed(target):
                    raise RuntimeError(f"Runtime symlink escapes: {path}")
            else:
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o222:
                    raise RuntimeError(f"Runtime file is not frozen: {path}")
                with physical.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != entry.get("sha256"):
                        raise RuntimeError(f"Runtime content changed: {path}")
        except OSError as exc:
            raise RuntimeError(f"Cannot validate runtime file {path}: {exc}") from exc
    return manifest


def executable_digest(manifest, executable):
    """Resolve a namespace path against manifest links without host symlink reads."""
    entries = {entry["path"]: entry for entry in manifest["entries"]}
    path = posixpath.normpath(executable)
    for _ in range(40):
        parts = PurePosixPath(path).parts
        replaced = False
        for count in range(2, len(parts) + 1):
            prefix = str(PurePosixPath(*parts[:count]))
            entry = entries.get(prefix)
            if entry and entry["kind"] == "symlink":
                path = posixpath.normpath(posixpath.join(str(PurePosixPath(prefix).parent),
                                                       entry["target"], *parts[count:]))
                replaced = True
                break
        if not replaced:
            return entries.get(path, {}).get("sha256")
    raise RuntimeError("Runtime executable symlink cycle")
