# llm/workshop.py — the participant's hands: code that runs in a room-scoped sandbox
"""
ARCHITECTURE: one persistent Linux workspace per room under
DIALECTIC_WORKSHOP_ROOT/rooms/<room_id> (default /var/lib/dialectic/workshop),
executed through bubblewrap as `nobody` (uid 65534 in a fresh user namespace)
with NO network, /usr and the Workshop's own uv venv read-only, the workspace
read-write at /work, a tmpfs /tmp, prlimit caps, and a wall-clock kill. Every
run is a git commit in the workspace — reproducibility is history, not a flag.
Files a run creates or changes become `attachments` rows with uploader NULL
and message NULL, bound to the turn's message by the same two-phase bind
write_document uses (documents.bind_documents reads provenance.attachment_ids).

WHY bubblewrap and not Docker or Firecracker: Docker is banned on this host;
Firecracker is not installed and needs a kernel+rootfs pipeline. bwrap is
installed, needs no daemon, and a user namespace plus --unshare-all is exactly
"no network, no secrets". Measured 2026-10-27 on this host: numpy / pandas /
matplotlib run; connect(1.1.1.1:53) fails errno 101; /etc/shadow and
dialectic/.env do not exist inside; a sleep(30) under a 3s kill left no orphan.

TRADEOFF: the sandbox shares the production host's kernel and CPU. prlimit
caps address space, process count and file size; the asyncio timeout caps
wall clock. It is not a VM. Before the Workshop gets network or credentials
it belongs on a second machine (docs/MOONSHOT_2026-10-27.md, Organ 1).
"""

import asyncio
import hashlib
import logging
import mimetypes
import os
import shutil
import signal
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from api.attachments import (
    attachment_payload, image_dimensions, max_bytes_for_kind, media_root,
    sanitize_original_name,
)

logger = logging.getLogger(__name__)

DEFAULT_ROOT = "/var/lib/dialectic/workshop"
# The tool loop gives a primary turn 60s and the registry law caps every
# guard under half of it, so a run is bounded at 25s with a 29s guard.
# ponytail: hours-long work is start_job (MOONSHOT Organ 1), not a longer cap.
RUN_TIMEOUT_DEFAULT_S = 15
RUN_TIMEOUT_MAX_S = 25
MAX_CODE_CHARS = 40_000
STDOUT_CAP = 4_000
STDERR_CAP = 2_000
ARTIFACT_CAP = 8
LANGUAGES = ("python", "bash")
# A fire-and-forget subprocess per room, serialised per room so two turns
# cannot race one git index. ponytail: per-process dict; a second backend
# worker would need a file lock in the workspace.
_room_locks: dict[str, asyncio.Lock] = {}

_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_SKIP_DIRS = {".git", "runs", "__pycache__", ".cache"}


def workshop_enabled() -> bool:
    """Kill switch, read at call time like the other tool-group flags."""
    return os.environ.get("DIALECTIC_WORKSHOP_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")


def workshop_root() -> str:
    return os.environ.get("DIALECTIC_WORKSHOP_ROOT", DEFAULT_ROOT)


def venv_dir() -> str:
    """The sandbox interpreter's venv — overridable so a test can point the
    workspace root at tmp_path while still running the real venv."""
    return os.environ.get("DIALECTIC_WORKSHOP_VENV") or os.path.join(workshop_root(), "venv")


def workspace_dir(room_id: UUID) -> str:
    """The room's workspace, created and git-initialised on first use."""
    path = os.path.join(workshop_root(), "rooms", str(room_id))
    os.makedirs(os.path.join(path, "runs"), exist_ok=True)
    if not os.path.isdir(os.path.join(path, ".git")):
        with open(os.path.join(path, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("__pycache__/\n.cache/\n")
        # Synchronous on purpose: first use only, and the directory must be a
        # repo before any run can be committed.
        import subprocess
        subprocess.run(["git", "init", "-q", path], check=True)
    return path


def _lock(room_id: UUID) -> asyncio.Lock:
    return _room_locks.setdefault(str(room_id), asyncio.Lock())


def bwrap_argv(workspace: str, entry: list[str]) -> list[str]:
    """The exact sandbox command. Pure so a test can pin the fence: no
    network, nobody's uid, /usr and the venv read-only, only /work writable."""
    bwrap = shutil.which("bwrap")
    prlimit = shutil.which("prlimit")
    if not bwrap or not prlimit:
        raise RuntimeError("Workshop needs bwrap and prlimit on this host")
    venv = venv_dir()
    if not os.path.isfile(os.path.join(venv, "bin", "python")):
        raise RuntimeError(
            f"Workshop venv missing at {venv}: build it with "
            "`uv venv --python /usr/bin/python3.12 venv && uv pip install --python venv/bin/python numpy pandas matplotlib ...`"
        )
    argv = [
        prlimit, "--as=8000000000", "--nproc=128", "--nofile=256", "--fsize=200000000",
        bwrap,
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
        "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--ro-bind", venv, "/opt/venv",
        "--bind", workspace, "/work", "--chdir", "/work",
        "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev",
        "--unshare-all", "--uid", "65534", "--gid", "65534",
        "--die-with-parent", "--new-session",
        "--clearenv",
        "--setenv", "HOME", "/work",
        "--setenv", "PATH", "/opt/venv/bin:/usr/bin:/bin",
        # The entry script lives under runs/<id>/, so sys.path[0] is NOT the
        # workspace; this is what lets run two `import helper` from run one.
        "--setenv", "PYTHONPATH", "/work",
        "--setenv", "MPLBACKEND", "Agg",
        "--setenv", "MPLCONFIGDIR", "/tmp/mpl",
        "--setenv", "XDG_CACHE_HOME", "/tmp/cache",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONUNBUFFERED", "1",
    ]
    for optional in ("/etc/localtime", "/etc/fonts"):
        if os.path.exists(optional):
            argv += ["--ro-bind", optional, optional]
    return argv + ["--"] + entry


def _snapshot(workspace: str) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for base, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            full = os.path.join(base, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out[os.path.relpath(full, workspace)] = (st.st_size, st.st_mtime_ns)
    return out


async def _drain(stream, cap: int = 1_000_000) -> bytes:
    """Read a pipe to EOF, keeping the first `cap` bytes and discarding the
    rest — a run that prints without end must neither fill memory nor block
    on a full pipe."""
    buf = bytearray()
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(buf)
        if len(buf) < cap:
            buf += chunk[: cap - len(buf)]


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.6), int(limit * 0.4)
    return text[:head] + f"\n…[{len(text) - limit} characters cut]…\n" + text[-tail:]


async def _git(workspace: str, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", workspace, "-c", "user.name=Dialectic", "-c", "user.email=workshop@dialectic.local",
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", "replace").strip()


async def _commit(workspace: str, message: str) -> Optional[str]:
    await _git(workspace, "add", "-A")
    code, _ = await _git(workspace, "commit", "-q", "-m", message)
    if code != 0:  # nothing to commit
        return None
    _, sha = await _git(workspace, "rev-parse", "HEAD")
    return sha or None


async def run(room_id: UUID, code: str, language: str = "python", timeout_s: Optional[int] = None) -> dict:
    """Run one program in the room's workspace. Never raises for the program's
    own failure — exit code, stderr and a timed_out flag come back as data.
    Raises ValueError for bad input and RuntimeError when the host lacks the
    sandbox, both of which the tool loop turns into an is_error result."""
    if not (code or "").strip():
        raise ValueError("code is required")
    if len(code) > MAX_CODE_CHARS:
        raise ValueError(f"code exceeds {MAX_CODE_CHARS} characters")
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {', '.join(LANGUAGES)}")
    try:
        timeout = int(timeout_s) if timeout_s is not None else RUN_TIMEOUT_DEFAULT_S
    except (TypeError, ValueError):
        raise ValueError("timeout_s must be an integer")
    timeout = max(1, min(timeout, RUN_TIMEOUT_MAX_S))

    workspace = workspace_dir(room_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_rel = os.path.join("runs", f"{stamp}-{uuid4().hex[:8]}")
    run_dir = os.path.join(workspace, run_rel)
    os.makedirs(run_dir, exist_ok=True)
    entry_name = "main.py" if language == "python" else "main.sh"
    with open(os.path.join(run_dir, entry_name), "w", encoding="utf-8") as fh:
        fh.write(code if code.endswith("\n") else code + "\n")
    entry = (["/opt/venv/bin/python", f"/work/{run_rel}/{entry_name}"] if language == "python"
             else ["/bin/bash", f"/work/{run_rel}/{entry_name}"])

    async with _lock(room_id):
        before = _snapshot(workspace)
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *bwrap_argv(workspace, entry),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        # Readers run as their own tasks so the timeout cancels only the
        # wait, never the read: cancelling communicate() under wait_for drops
        # every byte already read, and a killed run came back with no output
        # (measured 2026-10-27: print('start') then sleep → stdout '').
        out_task = asyncio.create_task(_drain(proc.stdout))
        err_task = asyncio.create_task(_drain(proc.stderr))
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
        out_b, err_b = await out_task, await err_task
        duration_ms = int((time.monotonic() - started) * 1000)
        after = _snapshot(workspace)
        changed = sorted(p for p, sig in after.items() if before.get(p) != sig)
        first_line = next((ln.strip() for ln in code.splitlines() if ln.strip()), language)[:72]
        commit = await _commit(workspace, f"run {stamp}: {first_line}")

    return {
        "language": language,
        "run_dir": run_rel,
        "exit_code": None if timed_out else proc.returncode,
        "timed_out": timed_out,
        "timeout_s": timeout,
        "duration_ms": duration_ms,
        "stdout": _cap(out_b.decode("utf-8", "replace"), STDOUT_CAP),
        "stderr": _cap(err_b.decode("utf-8", "replace"), STDERR_CAP),
        "changed_files": changed,
        "commit": commit,
    }


def select_artifacts(workspace: str, rel_paths: list[str]) -> list[tuple[str, str, str]]:
    """The (rel_path, mime, kind) a run's new/changed files would file as —
    the one filter file_artifacts and the job report share, so a report can
    name exactly the files that will attach without filing them first.
    Oversize and empty files and anything past ARTIFACT_CAP are skipped, not
    failed: the run already happened and its output is real either way."""
    chosen: list[tuple[str, str, str]] = []
    for rel in rel_paths:
        if len(chosen) >= ARTIFACT_CAP:
            break
        full = os.path.join(workspace, rel)
        if not os.path.isfile(full):
            continue
        mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        kind = "image" if mime in _IMAGE_MIMES else "file"
        size = os.path.getsize(full)
        if size == 0 or size > max_bytes_for_kind(kind):
            logger.info("Workshop skipped artifact %s (%d bytes, %s)", rel, size, kind)
            continue
        chosen.append((rel, mime, kind))
    return chosen


async def file_artifacts(db, room_id: UUID, workspace: str, rel_paths: list[str]) -> list[dict]:
    """File the run's new/changed files as LLM-authored attachments (uploader
    NULL, message NULL) — the orchestrator binds them to the turn's message."""
    payloads: list[dict] = []
    for rel, mime, kind in select_artifacts(workspace, rel_paths):
        full = os.path.join(workspace, rel)
        with open(full, "rb") as fh:
            data = fh.read()
        sha = hashlib.sha256(data).hexdigest()
        width, height = image_dimensions(data, mime) if kind == "image" else (None, None)
        ext = os.path.splitext(rel)[1].lower()
        relative = os.path.join(str(room_id), sha[:2], f"{sha}{ext}")
        final = os.path.join(media_root(), relative)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        tmp = f"{final}.{uuid4().hex}.part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, final)
        row = await db.fetchrow(
            """INSERT INTO attachments
                   (id, room_id, message_id, uploader_user_id, kind, mime,
                    bytes, sha256, width, height, original_name, storage_path, created_at)
               VALUES ($1, $2, NULL, NULL, $3, $4, $5, $6, $7, $8, $9, $10, $11)
               RETURNING *""",
            uuid4(), room_id, kind, mime, len(data), sha, width, height,
            sanitize_original_name(os.path.basename(rel)), relative,
            datetime.now(timezone.utc),
        )
        payloads.append(attachment_payload(row))
    return payloads
