"""Model output is data: bounded edits with exact input preconditions, never tools."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath


def apply_edits(directory: Path, edits: list[dict]):
    directory = Path(directory).resolve()
    if not isinstance(edits, list) or not edits or len(edits) > 100:
        raise ValueError("Expected between 1 and 100 edit operations")
    planned, seen, size = [], set(), 0
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) - {"path", "expected_sha256", "content", "delete"}:
            raise ValueError("Invalid edit fields")
        name = edit.get("path")
        if not isinstance(name, str) or "\\" in name or "\0" in name:
            raise ValueError("Invalid edit path")
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or str(path) != name or
                any(p in ("..", ".git") for p in path.parts) or name in seen):
            raise ValueError("Edit paths must be unique repository-relative paths outside .git")
        seen.add(name)
        target = directory / name
        if any(p.exists() and not p.is_dir() for p in target.parents if p != directory and directory in p.parents):
            raise ValueError("Edit parent must be a directory")
        if any(p.is_symlink() for p in [target, *target.parents] if p != directory and directory in p.parents):
            raise ValueError("Edits cannot traverse symlinks")
        if target.exists() and not target.is_file():
            raise ValueError("Edits operate on regular files")
        if "expected_sha256" not in edit:
            raise ValueError("Every edit must identify expected input bytes or null for a new file")
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if actual != edit["expected_sha256"]:
            raise ValueError(f"Edit input precondition failed: {name}")
        deletion = edit.get("delete", False)
        if not isinstance(deletion, bool):
            raise ValueError("delete must be a boolean")
        if deletion:
            if actual is None or "content" in edit:
                raise ValueError("Deletion requires an existing file and no content")
            data = None
        else:
            if not isinstance(edit.get("content"), str):
                raise ValueError("Replacement content must be a UTF-8 string")
            data = edit["content"].encode("utf-8")
            size += len(data)
            if size > 1024 * 1024:
                raise ValueError("Edit output exceeds 1 MiB")
        planned.append((target, data))
    for name in seen:
        if any(str(parent) in seen for parent in PurePosixPath(name).parents if str(parent) != "."):
            raise ValueError("Edit operations cannot target both a path and its descendant")
    # Validate the entire operation before changing any candidate bytes.
    for target, data in planned:
        if data is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
