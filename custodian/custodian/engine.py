"""Immutable candidates and append-only observations. No model owns state.

The source directory is an import surface, not a transactional filesystem.
Two equal scans reduce accidental partial imports; they do not prove atomicity.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import time
import uuid


class CustodianError(RuntimeError):
    pass


def execute(argv, *, cwd=None, env=None, data=None):
    result = subprocess.run(argv, cwd=cwd, env=env, input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise CustodianError(result.stderr.decode(errors="replace").strip())
    return result.stdout


class Engine:
    def __init__(self, repo: Path, state: Path | None = None):
        self.git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.repo = Path(execute(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], env=self.git_env)
                         .decode().strip()).resolve()
        key = hashlib.sha256(os.fsencode(self.repo)).hexdigest()[:24]
        self.state = (Path(state) if state else Path.home() / ".local/state/custodian" / key).resolve()
        if self.state == self.repo or self.repo in self.state.parents:
            raise CustodianError("State must live outside the foreground repository")
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.archive = self.state / "objects.git"
        self.git_env.update(GIT_AUTHOR_NAME="Custodian", GIT_AUTHOR_EMAIL="custodian@localhost",
                            GIT_COMMITTER_NAME="Custodian", GIT_COMMITTER_EMAIL="custodian@localhost",
                            GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0",
                            GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        with self.lease(name="setup.lock"):
            if not self.archive.exists():
                object_format = self.source_git(self.repo, "rev-parse", "--show-object-format").decode().strip()
                execute(["git", "init", "--bare", "--quiet", f"--object-format={object_format}",
                         str(self.archive)], env=self.git_env)
            with self.db() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, "
                           "kind TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS events_kind_seq ON events(kind,seq)")
                db.execute("CREATE INDEX IF NOT EXISTS events_kind_id ON events(kind,json_extract(payload,'$.id'))")
                db.execute("CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events "
                           "BEGIN SELECT RAISE(ABORT,'append only'); END")
                db.execute("CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events "
                           "BEGIN SELECT RAISE(ABORT,'append only'); END")
            identity = self.state / "repository"
            if identity.exists() and identity.read_text() != str(self.repo):
                raise CustodianError("State belongs to a different repository")
            identity.write_text(str(self.repo))
        # Blob identities are computed in-process in the archive's own object format
        # (sha1 or sha256); git only ever confirms or stores them.
        self.object_format = self.git("rev-parse", "--show-object-format")
        if self.object_format not in ("sha1", "sha256"):
            raise CustodianError(f"Unsupported archive object format: {self.object_format}")

    # Pending blob bytes held in memory before a batch write; bounds RAM on large drafts.
    _BLOB_FLUSH_BYTES = 64 * 1024 * 1024

    def _blob_id(self, content: bytes) -> str:
        """The object id git assigns a blob of these exact bytes, without a process."""
        digest = hashlib.new(self.object_format)
        digest.update(b"blob %d\0" % len(content))
        digest.update(content)
        return digest.hexdigest()

    def _store_blobs(self, blobs: dict[str, bytes]):
        """Write only the blobs the archive lacks.

        ARCHITECTURE: one `cat-file --batch-check` answers "which of these N ids
        exist" in a single process; the base commit's history is fetched before a
        scan, so unmodified tracked files are already present and only edited or
        new files cost a `hash-object` spawn. Measured on a 1,571-file repository
        the per-file spawn loop cost ~7 s per scan, five scans per attempt, and
        every status()/hook/MCP read; this path makes a scan sub-second. git's own
        id for each written blob must equal ours or the candidate is refused.
        """
        if not blobs:
            return
        listing = execute(["git", "--git-dir", str(self.archive), "cat-file", "--batch-check"],
                          data="".join(oid + "\n" for oid in blobs).encode(), env=self.git_env)
        for line in listing.decode().splitlines():
            oid, _, status = line.partition(" ")
            if status == "missing":
                stored = self.git("hash-object", "-w", "--stdin", data=blobs[oid])
                if stored != oid:
                    raise CustodianError(f"Blob identity mismatch: computed {oid}, git stored {stored}")
            elif oid not in blobs:
                raise CustodianError(f"Unexpected object in batch check: {line}")

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.state / "events.sqlite3", timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def lease(self, name="writer.lock", blocking=True):
        with (self.state / name).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def event(self, kind, payload):
        with self.db() as db:
            db.execute("INSERT INTO events(kind,created,payload) VALUES(?,?,?)",
                       (kind, time.time(), json.dumps(payload, sort_keys=True)))

    def events(self, kind=None):
        with self.db() as db:
            rows = db.execute("SELECT kind,payload FROM events " +
                              ("WHERE kind=? " if kind else "") + "ORDER BY seq",
                              (kind,) if kind else ()).fetchall()
        return [dict(kind=k, **json.loads(p)) for k, p in rows]

    def git(self, *args, data=None, env=None):
        return execute(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false", "--git-dir", str(self.archive), *args],
                       data=data, env=env or self.git_env).decode().strip()

    def source_git(self, directory, *args):
        return execute(["git", "-C", str(directory), *args], env=self.git_env)

    def _read_entry(self, directory, raw):
        """Open every path component relative to a held descriptor without following links."""
        parts = os.fsdecode(raw).split("/")
        if any(p in ("", ".", "..", ".git") for p in parts):
            raise CustodianError("Invalid candidate path")
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in parts[:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                return "120000", os.fsencode(os.readlink(parts[-1], dir_fd=fd))
            if not stat.S_ISREG(info.st_mode):
                raise CustodianError(f"Unsupported file type: {os.fsdecode(raw)}")
            leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(leaf, "rb") as stream:
                actual = os.fstat(stream.fileno())
                if not stat.S_ISREG(actual.st_mode):
                    raise CustodianError("File type changed during capture")
                content = stream.read(32 * 1024 * 1024 + 1)
                if len(content) > 32 * 1024 * 1024:
                    raise CustodianError(f"Capture file exceeds 32 MiB: {os.fsdecode(raw)}")
            return ("100755" if actual.st_mode & 0o111 else "100644"), content
        finally:
            os.close(fd)

    def _tree(self, directory):
        """Construct a tree from bytes, not the foreground index or mtimes."""
        tracked = self.source_git(directory, "ls-files", "--stage", "-z")
        if any(entry.startswith(b"160000 ") for entry in tracked.split(b"\0")):
            raise CustodianError("Submodules require an explicit capture contract; refusing partial evidence")
        names = self.source_git(directory, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        records, pending, pending_bytes = [], {}, 0
        for raw in sorted(set(names.split(b"\0")) - {b""}):
            try:
                mode, content = self._read_entry(directory, raw)
            except FileNotFoundError:
                continue  # Tracked deletion.
            oid = self._blob_id(content)
            records.append(f"{mode} {oid}\t".encode() + raw + b"\0")
            if oid not in pending:
                pending[oid] = content
                pending_bytes += len(content)
                if pending_bytes >= self._BLOB_FLUSH_BYTES:
                    self._store_blobs(pending)
                    pending, pending_bytes = {}, 0
        self._store_blobs(pending)
        fd, name = tempfile.mkstemp(dir=self.state, prefix="index-")
        os.close(fd)
        os.unlink(name)
        env = dict(self.git_env, GIT_INDEX_FILE=name)
        try:
            self.git("read-tree", "--empty", env=env)
            self.git("update-index", "-z", "--index-info", data=b"".join(records), env=env)
            return self.git("write-tree", env=env)
        finally:
            Path(name).unlink(missing_ok=True)

    def capture(self):
        with self.lease():
            return self._capture()

    def _capture(self):
        base = self.source_git(self.repo, "rev-parse", "HEAD").decode().strip()
        # Copy history into our private database first; the source ref/index is
        # untouched, and every unmodified tracked blob is then already stored, so
        # the two scans below write only the draft's edited or new files.
        self.git("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", str(self.repo), base)
        first, second = self._tree(self.repo), self._tree(self.repo)
        if first != second or base != self.source_git(self.repo, "rev-parse", "HEAD").decode().strip():
            raise CustodianError("Import changed during capture; retry after editing settles")
        commit = self.git("commit-tree", second, "-p", base,
                          data=b"Custodian observed draft; intent unknown\n")
        snapshot = dict(id=uuid.uuid4().hex, tree=second, commit=commit, base=base,
                        atomic=False, intent="UNKNOWN", observed_at=time.time())
        self.git("update-ref", f"refs/custodian/observations/{snapshot['id']}", commit)
        self.event("observation", snapshot)
        return snapshot

    def _command(self, argv, directory, timeout, *, readonly=False, mode="isolated", runtime_paths=None, runtime_root=None, cancel=None):
        if not argv or not all(isinstance(x, str) for x in argv):
            raise CustodianError("Commands must be nonempty argument arrays")
        started = time.time()
        from .sandbox import Sandbox
        runner = Sandbox(mode=mode, runtime_paths=runtime_paths or [], runtime_root=runtime_root)
        result = runner.run(argv, Path(directory), timeout, readonly=readonly, cancel=cancel)
        result["infrastructure_error"] = result["stderr"].startswith(b"bwrap:")
        stdout = self.git("hash-object", "-w", "--stdin", data=result.pop("stdout"))
        stderr = self.git("hash-object", "-w", "--stdin", data=result.pop("stderr"))
        for oid in (stdout, stderr):
            self.git("update-ref", f"refs/custodian/evidence/{oid}", oid)
        return dict(result, argv=argv, stdout_blob=stdout, stderr_blob=stderr,
                    started_at=started, ended_at=time.time())

    def _safe_links(self, directory):
        # Worktrees are not security sandboxes. Still reject obvious link escapes
        # before executing ordinary trusted tools against imported source.
        for raw in self.source_git(directory, "ls-files", "-z").split(b"\0"):
            if not raw:
                continue
            path = directory / os.fsdecode(raw)
            if path.is_symlink():
                target = os.readlink(path)
                if os.path.isabs(target) or not path.resolve().is_relative_to(directory):
                    raise CustodianError(f"Escaping symlink cannot be executed: {os.fsdecode(raw)}")

    def run(self, intent: str, command: list[str] | None, checks: list[list[str]],
            protected: list[str] | None = None, timeout: float = 60, *, mode="isolated",
            runtime_paths=None, runtime_root=None, cancel=None, context=None, snapshot=None, edits=None):
        if timeout <= 0:
            raise CustodianError("Timeout must be positive")
        with self.lease():
            if command and edits is not None:
                raise CustodianError("An attempt takes a command or edit operations, not both")
            if snapshot:
                known = next((o for o in self.events("observation") if o["id"] == snapshot.get("id")), None)
                if not known or any(known[k] != snapshot.get(k) for k in ("commit", "tree", "base")):
                    raise CustodianError("Unknown or altered input observation")
            else:
                snapshot = self._capture()
            for runtime in runtime_paths or []:
                path = Path(runtime).resolve()
                if (path == self.repo or path in self.repo.parents or self.repo in path.parents or
                    path == self.state or path in self.state.parents or self.state in path.parents):
                    raise CustodianError("Runtime mounts must not expose the source repository or state")
            attempt = dict(id=uuid.uuid4().hex, intent=intent, input_tree=snapshot["tree"],
                           input_commit=snapshot["commit"], base=snapshot["base"],
                           output_tree=None, status="RUNNING", checks=[], branch=None,
                           protected=protected or [], started_at=time.time(),
                           context=context or {}, mode=mode,
                           environment=dict(platform=os.uname().sysname, release=os.uname().release,
                                            external_state="UNVERIFIED", isolation=mode,
                                            immutable_execution="read-only-candidate" if mode == "isolated" else "UNVERIFIED"))
            self.event("attempt_started", attempt)
            work = self.state / "work" / attempt["id"]
            verify = self.state / "work" / (attempt["id"] + "-verify")
            work.parent.mkdir(exist_ok=True)
            try:
                if cancel and cancel():
                    raise InterruptedError("Foreground activity or controller stop")
                self.git("worktree", "add", "--quiet", "--detach", str(work), snapshot["commit"])
                self._safe_links(work)
                if self._tree(work) != snapshot["tree"]:
                    raise CustodianError("Worker checkout differs from imported candidate bytes")
                if edits is not None:
                    from .edits import apply_edits
                    apply_edits(work, edits)
                    attempt["edit_operations"] = edits
                attempt["execution"] = self._command(command, work, timeout, mode=mode,
                                                     runtime_paths=runtime_paths, runtime_root=runtime_root, cancel=cancel) if command else None
                if attempt["execution"]:
                    self.event("attempt_progress", dict(id=attempt["id"], phase="execution", evidence=attempt["execution"]))
                    if attempt["execution"].get("cancelled"):
                        raise InterruptedError("Foreground activity or controller stop")
                output = self._tree(work)
                attempt["output_tree"] = output
                result_commit = self.git("commit-tree", output, "-p", snapshot["commit"],
                                         data=("Custodian attempt " + attempt["id"] + "\n").encode())
                self.git("update-ref", f"refs/custodian/attempts/{attempt['id']}", result_commit)
                attempt["output_commit"] = result_commit
                changed = execute(["git", "--git-dir", str(self.archive), "diff-tree", "--no-commit-id",
                                   "--name-only", "-r", "-z", snapshot["tree"], output], env=self.git_env)
                paths = [os.fsdecode(p) for p in changed.split(b"\0") if p]
                attempt["changed_paths"] = paths
                forbidden = [p for p in paths if any(p == q.rstrip("/") or p.startswith(q.rstrip("/") + "/")
                                                     for q in (protected or []))]
                if forbidden:
                    attempt.update(status="REJECTED", reason="Protected paths changed", violations=forbidden)
                elif attempt["execution"] and (attempt["execution"]["exit_code"] != 0 or
                        attempt["execution"].get("output_limited") or attempt["execution"].get("timed_out")):
                    attempt.update(status="FAILED", reason="Candidate command failed")
                else:
                    attempt["status"] = "PASSED" if checks else "UNVERIFIED"
                    if checks:
                        self.git("worktree", "add", "--quiet", "--detach", str(verify), result_commit)
                        self._safe_links(verify)
                        if self._tree(verify) != output:
                            raise CustodianError("Verifier checkout differs from candidate bytes")
                    for argv in checks:
                        if cancel and cancel():
                            raise InterruptedError("Foreground activity or controller stop")
                        evidence = self._command(argv, verify, timeout, readonly=True, mode=mode,
                                                 runtime_paths=runtime_paths, runtime_root=runtime_root, cancel=cancel)
                        evidence["tree"] = output
                        evidence["tree_after"] = self._tree(verify)
                        self.git("update-ref", f"refs/custodian/checks/{attempt['id']}/{len(attempt['checks'])}", evidence["tree_after"])
                        evidence["claim"] = ("Command exit against a read-only candidate; not semantic correctness" if mode == "isolated"
                                             else "Command exit and before/after bytes; execution not immutable")
                        attempt["checks"].append(evidence)
                        self.event("attempt_progress", dict(id=attempt["id"], phase="check", evidence=evidence))
                        if evidence.get("cancelled"):
                            raise InterruptedError("Foreground activity or controller stop")
                        if (evidence["exit_code"] != 0 or evidence["tree_after"] != output or
                                evidence.get("output_limited") or evidence.get("timed_out")):
                            attempt.update(status="FAILED", reason="Check failed or changed candidate bytes")
                            break
                # A branch denotes a candidate, never an automatic approval or merge.
                if attempt["status"] == "PASSED" and (command or edits is not None):
                    waiting = self.git("for-each-ref", "--format=%(refname)", "refs/heads/custodian/").splitlines()
                    if len(waiting) < 3:
                        attempt["branch"] = "custodian/" + attempt["id"][:12]
                    else:
                        attempt["branch_withheld"] = "Three proposal branches are already waiting"
            except InterruptedError as exc:
                attempt.update(status="CANCELLED", reason=str(exc))
            except Exception as exc:
                attempt.update(status="FAILED", reason=str(exc))
            except BaseException:
                attempt.update(status="INTERRUPTED", reason="Controller interrupted; outcome unknown")
                raise
            finally:
                attempt["ended_at"] = time.time()
                self.event("attempt_finished", attempt)
                if attempt["status"] == "PASSED" and attempt.get("branch"):
                    self.git("update-ref", "refs/heads/" + attempt["branch"], result_commit)
                    self.event("proposal_created", dict(id=attempt["id"], branch=attempt["branch"], commit=result_commit))
                # Worktrees from killed processes remain recoverable; completed ones are disposable.
                if work.exists():
                    self.git("worktree", "remove", "--force", str(work))
                if verify.exists():
                    self.git("worktree", "remove", "--force", str(verify))
            return attempt

    def recover(self):
        """Reconcile dead controllers. The exclusive lease proves no live attempt owns the workspace."""
        with self.lease(blocking=False):
            finished = {a["id"]: a for a in self.events("attempt_finished")}
            recovered = []
            for started in self.events("attempt_started"):
                if started["id"] not in finished:
                    result = dict(started)
                    result.pop("kind", None)
                    progress = [p for p in self.events("attempt_progress") if p["id"] == started["id"]]
                    result.update(status="INTERRUPTED", reason="Recovered abandoned controller; outcome unknown",
                                  ended_at=time.time(), recovered_evidence=progress, branch=None)
                    self.event("attempt_finished", result)
                    finished[started["id"]] = result
                    recovered.append(started["id"])
            for result in finished.values():
                for suffix in ("", "-verify"):
                    work = self.state / "work" / (result["id"] + suffix)
                    if work.exists():
                        self.git("worktree", "remove", "--force", str(work))
                if result["status"] == "PASSED" and result.get("branch"):
                    dispositions = [d for d in self.events("proposal_disposition") if d["id"] == result["id"]]
                    if dispositions:
                        self.git("update-ref", "-d", "refs/heads/" + result["branch"])
                    else:
                        self.git("update-ref", "refs/heads/" + result["branch"], result["output_commit"])
            self.git("worktree", "prune")
            if recovered:
                self.event("recovery", dict(attempts=recovered))
            return dict(recovered=recovered)

    def proposals(self):
        refs = set(self.git("for-each-ref", "--format=%(refname:short)", "refs/heads/custodian/").splitlines())
        disposed = {d["id"] for d in self.events("proposal_disposition")}
        return [a for a in self.events("attempt_finished") if a.get("branch") in refs and a["id"] not in disposed]

    def dispose(self, attempt_id, disposition, reason=""):
        if disposition not in ("accepted", "rejected", "withdrawn"):
            raise CustodianError("Disposition must be accepted, rejected, or withdrawn")
        with self.lease():
            result = next((a for a in self.events("attempt_finished") if a["id"] == attempt_id), None)
            if not result or not result.get("branch"):
                raise CustodianError("No proposal for this attempt")
            self.event("proposal_disposition", dict(id=attempt_id, disposition=disposition, reason=reason,
                                                    integration_verified=False))
            self.git("update-ref", "-d", "refs/heads/" + result["branch"])
            return dict(id=attempt_id, disposition=disposition, integration_verified=False)

    def diff(self, attempt_id, *, full=False):
        result = next((a for a in self.events("attempt_finished") if a["id"] == attempt_id), None)
        if not result or not result.get("output_tree"):
            raise CustodianError("Attempt has no output candidate")
        return self.git("diff", "--no-ext-diff", "--no-textconv", result["base"] if full else result["input_tree"],
                        result["output_tree"])

    def audit(self):
        with self.lease():
            with self.db() as db:
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            errors = [] if integrity == "ok" else [integrity]
            records = self.events()
            def visit(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in ("stdout_blob", "stderr_blob", "response_blob", "tree", "tree_after", "commit",
                                   "input_tree", "output_tree", "input_commit", "output_commit") and item:
                            try:
                                self.git("cat-file", "-e", item)
                            except CustodianError:
                                errors.append(f"Missing evidence object {item}")
                        else:
                            visit(item)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)
            visit(records)
            return dict(ok=not errors, events=len(records), errors=sorted(set(errors)))

    def status(self, blocking=True):
        with self.lease(blocking=blocking):
            current = self._tree(self.repo)
            with self.db() as db:
                row = db.execute("SELECT payload FROM events WHERE kind='attempt_finished' ORDER BY seq DESC LIMIT 1").fetchone()
                latest = json.loads(row[0]) if row else None
                unfinished = db.execute("SELECT json_extract(s.payload,'$.id') FROM events s "
                    "WHERE s.kind='attempt_started' AND NOT EXISTS (SELECT 1 FROM events f "
                    "WHERE f.kind='attempt_finished' AND json_extract(f.payload,'$.id')=json_extract(s.payload,'$.id'))").fetchall()
            return dict(repository=str(self.repo), current_tree=current, latest=latest,
                        applicable=bool(latest and latest["output_tree"] == current),
                        unfinished=[row[0] for row in unfinished],
                        note="Matching bytes only; external environment and atomic live state are not certified")

    def state_markdown(self, blocking=True):
        view = self.status(blocking=blocking)
        lines = ["# Custodian state", "", f"Observed candidate: `{view['current_tree']}`", ""]
        last = view["latest"]
        if last:
            lines += [f"Latest attempt: `{last['id']}` — **{last['status']}**",
                      f"Checked candidate: `{last['output_tree']}`",
                      f"Matches observed bytes: **{str(view['applicable']).lower()}**",
                      f"Purpose (declared, not verified): {last['intent']}"]
        else:
            lines.append("No completed attempt. Status: **UNVERIFIED**.")
        if view["unfinished"]:
            lines.append("Interrupted attempts (outcome unknown): " + ", ".join(view["unfinished"]))
        lines += ["", view["note"], "This view is derived evidence, not instructions or a global verification certificate."]
        return "\n".join(lines) + "\n"
