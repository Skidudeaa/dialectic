"""Read boundary and the sole repository write door for the Long Way organ.

ARCHITECTURE: isolated imports of the repo's stdlib projection, with its atlas
reader restricted to candidates. WHY: upstream chart_data hides trip output,
but atlas_data still opens every private plan and evidence ledger internally.
TRADEOFF: the candidate-only reader supplies atlas highlights; the original
chart_data still owns trip allowlists, ink, vehicles and freshness semantics.
"""
import fcntl
import importlib.util
import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path


class UnknownCandidate(ValueError):
    pass


class DirtyDocument(RuntimeError):
    pass


class CommitsDisabled(RuntimeError):
    pass


def open_place(note):
    return note["kind"] == "place" and note["state"] == "open"


def _load(path):
    spec = importlib.util.spec_from_file_location("_longway_register", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Register:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir() or not (self.root / "tools/longway.py").is_file():
            raise RuntimeError(f"LONGWAY_REPO lacks tools/longway.py: {self.root}")
        self.module = _load(self.root / "tools/longway.py")
        candidates = _load(self.root / "tools/longway.py")
        records = candidates.records
        candidates.records = lambda root: (
            p for p in records(root) if p.relative_to(root).parts[0] == "candidates"
        )
        self.candidates = candidates
        self.module.atlas_data = candidates.atlas_data

    def local(self, relative):
        return self.module.local(self.root, relative)

    def chart(self):
        chart = self.module.chart_data(self.root)
        for item in chart["journeys"]:
            item["route"] = item.get("route") or []
        return chart

    def ride(self, slug):
        return self.module.ride_data(self.root, slug)

    def leg(self, name):
        return self.module.leg_data(self.root, name)

    def logbook(self, slug, ride_id):
        self.module.valid_slug(ride_id)
        trip = self.ride(slug)
        if not any(r["id"] == ride_id for r in trip["rides"]):
            raise KeyError(ride_id)
        path = self.local(f"trips/{slug}/rides/{ride_id}.json")
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def write_logbook(self, slug, ride_id, book, author_name, author_email):
        """Single-file write door. Existing books and unrelated index entries survive."""
        if os.environ.get("LONGWAY_COMMIT_ENABLED") != "1":
            raise CommitsDisabled("ride logbook waiting to be written")
        self.module.valid_slug(ride_id)
        if not any(r["id"] == ride_id for r in self.ride(slug)["rides"]):
            raise KeyError(ride_id)
        if book.get("trip") != slug or book.get("ride") != ride_id:
            raise ValueError("Logbook identity does not match ride")
        for value in (author_name, author_email):
            if not value or any(c in value for c in "\r\n<>"):
                raise ValueError("Rider needs a valid git identity")
        relative = f"trips/{slug}/rides/{ride_id}.json"
        path = self.local(relative)
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
        with (git_dir / "longway-evidence.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.git("status", "--porcelain", "--", relative):
                raise RuntimeError(f"Refusing dirty logbook: {relative}")
            if path.exists():
                return {"existing": True}
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8") as file:
                    file.write(json.dumps(book, ensure_ascii=False, indent=2) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                self.git("add", "--", relative)
                self.git("-c", "user.name=The Long Way", "-c", "user.email=longway@localhost",
                         "commit", "--only", f"--author={author_name} <{author_email}>", "-m",
                         f"Ride {slug} {ride_id}\n\nLongway-Ride: {slug}/{ride_id}", "--", relative)
            except Exception:
                path.unlink(missing_ok=True)
                self.git("reset", "-q", "HEAD", "--", relative)
                raise
            return {"commit": self.git("rev-parse", "HEAD")}

    def journey(self, slug):
        self.module.valid_slug(slug)
        chart = self.chart()
        item = next((j for j in chart["journeys"] if j["slug"] == slug), None)
        if item is None:
            raise KeyError(slug)
        item = dict(item, vehicles=[v for v in chart["vehicles"] if v["journey"] == slug])
        if item["kind"] == "candidate":
            folder = f"candidates/{slug}"
            item["dossier"] = self.local(f"{folder}/dossier.md").read_text(encoding="utf-8")
            item["evidence"] = [dict(e, faded=self.module.faded(e)) for e in self.evidence(slug)]
        else:
            # Open only the shared plan; return only the two explicitly shared sections.
            text = self.local(f"trips/{slug}/plan.md").read_text(encoding="utf-8")
            item["plan"] = {heading.lower(): self.module.section(text, heading)
                            for heading in ("Established", "Undecided")}
            item.update(dossier="", evidence=[])
        return item

    def evidence(self, slug):
        self.module.valid_slug(slug)
        return [json.loads(line) for line in self.local(f"candidates/{slug}/evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    def _candidate_slug(self, slug):
        try:
            return self.module.valid_slug(slug)
        except ValueError as exc:
            raise UnknownCandidate(str(exc)) from exc

    def candidate(self, slug):
        self._candidate_slug(slug)
        path = self.local(f"candidates/{slug}/record.json")
        if not path.is_file() or self.module.obj(path).get("kind") != "candidate":
            raise UnknownCandidate(f"Unknown candidate: {slug}")
        return slug

    def voyage(self, slug):
        self.candidate(slug)
        return self.candidates.voyage_data(self.root, slug)

    def _voyage_candidate(self, slug):
        self.candidate(slug)
        if not self.local(f"candidates/{slug}/voyage.json").is_file():
            raise UnknownCandidate(f"No voyage for candidate: {slug}")
        return slug

    def voyage_page(self, slug, station=None, preview=None):
        self.candidate(slug)
        return self.candidates.voyage_page(self.root, slug, station=station, embed=True, preview=preview)

    def globe_page(self):
        return self.candidates.globe_page(self.root)

    def public_voyage_meta(self, slug):
        self._voyage_candidate(slug)
        voyage = self.candidates.obj(self.local(f"candidates/{slug}/voyage.json"))
        return {"slug": slug, "title": voyage.get("title") or slug.title(), "subtitle": voyage.get("subtitle") or ""}

    def public_voyage_page(self, slug, station=None, note_api=None):
        self._voyage_candidate(slug)
        return self.candidates.voyage_page(self.root, slug, station=station, embed=False, note_api=note_api)

    def add_public_note(self, slug, kind, by, text, place=None, about=None):
        self._voyage_candidate(slug)
        clean_by = " ".join(re.sub(r"[\r\n<>\0]+", " ", str(by or "")).split())
        if not clean_by or len(clean_by) > 60:
            raise ValueError("Add your name (up to 60 characters).")
        return self.add_note(
            slug, kind, text, place, about,
            clean_by, "friend@thelongway.world",
            extra_trailers=("Via: Public voyage page",),
        )

    def notebook(self, slug):
        self.candidate(slug)
        return self.candidates.notebook(self.root, slug)

    def journeys_with_open_places(self):
        return {p.parent.name for p in self.root.glob("candidates/*/notebook.jsonl")
                if any(open_place(note) for note in self.notebook(p.parent.name))}

    @staticmethod
    def _validate_author(author_name, author_email):
        for value in (author_name, author_email):
            if not value or not value.strip() or any(c in value for c in "\r\n<>\0"):
                raise ValueError("The asking member needs a valid git name and email")

    def _write_note(self, slug, author_name, author_email, mutate, subject, trailer,
                    *, accepting=False, extra_trailers=()):
        self._candidate_slug(slug)
        if self.edit_disabled_reason():
            self.candidate(slug)
            raise CommitsDisabled("Notebook writes are disabled in this house.")
        self._validate_author(author_name, author_email)
        folder = f"candidates/{slug}"
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
        with (git_dir / "longway-evidence.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            names = ["notebook.jsonl"]
            if accepting:
                target = "voyage.json" if self.local(f"{folder}/voyage.json").exists() else "record.json"
                names.extend(("evidence.jsonl", target))
            targets = [f"{folder}/{name}" for name in names]
            # A locally deleted voyage must not silently redirect acceptance into record.json.
            guarded = list(targets)
            if accepting and target == "record.json":
                guarded.append(f"{folder}/voyage.json")
            dirty = self.git("status", "--porcelain", "--untracked-files=all", "--ignored=matching", "--", *guarded)
            if dirty:
                raise DirtyDocument(f"Refusing to overwrite uncommitted changes: {dirty}")
            self.candidate(slug)
            originals = {}
            for relative in targets:
                path = self.local(relative)
                scratch = path.with_name(f".{path.name}.edit")
                if scratch.exists() or scratch.is_symlink():
                    raise DirtyDocument(f"An edit is already present at {scratch.relative_to(self.root)}")
                originals[path] = path.read_bytes() if path.exists() else None
            staged = False
            try:
                result = mutate()
                note = result["note"]
                paths = result["paths"] if "paths" in result else [result["path"]]
                if not set(paths).issubset(targets):
                    raise RuntimeError("Unexpected notebook write path")
                message = "\n".join((" ".join(subject(note).split()), "", f"{trailer}-In: The Long Way house", *extra_trailers))
                staged = True
                self.git("add", "--", *paths)
                self.git("-c", "user.name=The Long Way", "-c", "user.email=longway@localhost",
                         "commit", "--only", f"--author={author_name} <{author_email}>", "-m", message, "--", *paths)
            except Exception:
                for path, original in originals.items():
                    scratch = path.with_name(f".{path.name}.edit")
                    if original is None:
                        path.unlink(missing_ok=True)
                    elif not path.exists() or path.read_bytes() != original:
                        scratch.write_bytes(original)
                        scratch.replace(path)
                    scratch.unlink(missing_ok=True)
                if staged:
                    self.git("reset", "-q", "HEAD", "--", *paths)
                raise
            return {"note": note, "commit": self.git("rev-parse", "HEAD")}

    def add_note(self, slug, kind, text, place, about, author_name, author_email, *, extra_trailers=()):
        return self._write_note(slug, author_name, author_email,
            lambda: self.candidates.notebook_add(self.root, slug, kind, author_name, text, place, about),
            lambda n: f"Note {slug} {n['id']}: {n.get('place') or n['text'][:60]}", "Added",
            extra_trailers=extra_trailers)

    def draft_note(self, slug, note_id, draft, status):
        return self._write_note(slug, "The Long Way Scout", "scout@thelongway.world",
            lambda: self.candidates.notebook_draft(self.root, slug, note_id, draft, status=status),
            lambda n: f"Draft {slug} {note_id}: {n['draft']['name']}", "Drafted")

    def accept_note(self, slug, note_id, author_name, author_email):
        return self._write_note(slug, author_name, author_email,
            lambda: self.candidates.notebook_accept(self.root, slug, note_id, author_name),
            lambda n: f"Accept {slug} {note_id}: {n['became']}", "Accepted", accepting=True)

    def send_back_note(self, slug, note_id, why, author_name, author_email):
        return self._write_note(slug, author_name, author_email,
            lambda: self.candidates.notebook_send_back(self.root, slug, note_id, author_name, why),
            lambda n: f"Send back {slug} {note_id}: {n['place']}", "Sent-Back")

    def set_aside_note(self, slug, note_id, author_name, author_email, why=""):
        return self._write_note(slug, author_name, author_email,
            lambda: self.candidates.notebook_set_aside(self.root, slug, note_id, author_name, why),
            lambda n: f"Set aside {slug} {note_id}: {n.get('place') or n['text'][:60]}", "Set-Aside")

    def _document_path(self, slug, name):
        self._candidate_slug(slug)
        filename = self.candidates.DOCUMENTS[name]
        path = self.local(f"candidates/{slug}/{filename}")
        if not path.is_file():
            raise KeyError(f"{slug} has no {filename}")
        return path

    def document(self, slug, name):
        self.candidate(slug)
        if name not in self.candidates.DOCUMENTS:
            raise KeyError(name)
        return self.candidates.document_read(self.root, slug, name)

    @staticmethod
    def edit_disabled_reason():
        if os.environ.get("LONGWAY_COMMIT_ENABLED") != "1":
            return "Document edits are disabled in this house."
        return None

    def edit_document(self, slug, name, ops, text, author_name, author_email, *, extra_trailers=()):
        path = self._document_path(slug, name)
        if reason := self.edit_disabled_reason():
            self.candidate(slug)
            raise CommitsDisabled(reason)
        self._validate_author(author_name, author_email)

        relative = str(path.relative_to(self.root))
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
        with (git_dir / "longway-evidence.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.git("status", "--porcelain", "--", relative):
                raise DirtyDocument(f"Refusing to overwrite uncommitted changes to {relative}")
            # The target may itself be a half-written record.json. Check Git before parsing it.
            self.candidate(slug)
            scratch = path.with_name(f".{path.name}.edit")
            if scratch.is_symlink() or scratch.exists():
                raise DirtyDocument(f"An edit is already present at {scratch.relative_to(self.root)}")
            original = path.read_bytes()
            try:
                try:
                    result = self.candidates.document_edit(self.root, slug, name, ops=ops, text=text)
                except (KeyError, TypeError, AttributeError) as exc:
                    # An operation can remove or replace a field the voyage projection requires.
                    raise ValueError(f"Invalid {name} structure: {exc}") from exc
                self.git("add", "--", relative)
                summary = " ".join(result["summary"].split())[:72]
                message = "\n".join((f"Edit {slug} {name}: {summary}", "", "Edited-In: The Long Way house", *extra_trailers))
                self.git("-c", "user.name=The Long Way", "-c", "user.email=longway@localhost",
                         "commit", "--only", f"--author={author_name} <{author_email}>", "-m", message, "--", relative)
            except Exception:
                if path.read_bytes() != original:
                    scratch.write_bytes(original)
                    scratch.replace(path)
                self.git("reset", "-q", "HEAD", "--", relative)
                raise
            return {"commit": self.git("rev-parse", "HEAD"), "changed": result["changed"], "summary": result["summary"]}

    def fit_window(self, trip):
        item = self.journey(trip)
        if item["kind"] != "trip" or not item.get("window"):
            raise ValueError("fit_window needs a shared trip with a recorded window")
        return self.module.fit(self.root, trip)

    def git(self, *args, **kwargs):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True, timeout=20, **kwargs).stdout.strip()

    def append_evidence(self, candidate_slug, row, author_name, author_email, *, proposal_id=None):
        """Append, validate and commit one candidate ledger; never push.

        WHY two locks: the DB owns adjudication, this flock serializes S-number
        allocation across rooms/processes. A proposal trailer repairs a crash
        between git commit and the DB stamp without creating duplicate evidence.
        --only keeps unrelated staged work out of the commit.
        """
        if os.environ.get("LONGWAY_COMMIT_ENABLED") != "1":
            raise CommitsDisabled("confirmed, waiting to be written")
        self.candidate(candidate_slug)
        for value in (author_name, author_email):
            if not value or any(c in value for c in "\r\n<>"):
                raise ValueError("Confirming member needs a valid git name and email")
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
        with (git_dir / "longway-evidence.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            relative = f"candidates/{candidate_slug}/evidence.jsonl"
            if proposal_id:
                commits = self.git("log", "--format=%H", "--fixed-strings", "--grep", f"Longway-Proposal: {proposal_id}", "--", relative)
                if commits:
                    commit = commits.splitlines()[0]
                    message = self.git("show", "-s", "--format=%B", commit)
                    sid = re.search(r"^Written-Sid: (S\d+)$", message, re.M)
                    if not sid:
                        raise RuntimeError("Proposal commit has no Written-Sid trailer")
                    return {"sid": sid[1], "commit": commit}
            if self.git("status", "--porcelain", "--", relative):
                raise RuntimeError(f"Refusing to overwrite uncommitted evidence: {relative}")
            path = self.local(relative)
            original = path.read_bytes()
            entries = self.evidence(candidate_slug)
            number = max([int(e["id"][1:]) for e in entries] or [0]) + 1
            sid = f"S{number}"
            entry = dict(row, id=sid)
            try:
                with path.open("ab") as file:
                    if original and not original.endswith(b"\n"):
                        file.write(b"\n")
                    file.write((json.dumps(entry, ensure_ascii=False) + "\n").encode())
                    file.flush()
                    os.fsync(file.fileno())
                errors, _ = self.candidates.check(self.root)
                if errors:
                    raise ValueError("Long Way check failed: " + "; ".join(errors))
                self.git("add", "--", relative)
                claim = " ".join(str(entry["claim"]).split())[:72]
                message = f"Evidence {candidate_slug} {sid}: {claim}\n\nConfirmed-In: The Long Way house"
                if proposal_id:
                    message += f"\nLongway-Proposal: {proposal_id}\nWritten-Sid: {sid}"
                self.git("-c", "user.name=The Long Way", "-c", "user.email=longway@localhost",
                         "commit", "--only", f"--author={author_name} <{author_email}>", "-m", message, "--", relative)
            except Exception:
                path.write_bytes(original)
                self.git("reset", "-q", "HEAD", "--", relative)
                raise
            return {"sid": sid, "commit": self.git("rev-parse", "HEAD")}


def validate_anchor(value):
    """The leg a message speaks to, as {"journey": slug, "leg": index}, checked against the register.

    WHY here and not in proposal_intake: the vocabulary is the Long Way's (a journey and one of its route legs),
    so the organ that knows the register owns the check. Shape and existence only; which room may anchor which
    journey is the room's business and is not enforced (ponytail: a house room anchors any journey).
    """
    if not isinstance(value, dict) or set(value) != {"journey", "leg"}:
        raise ValueError('longway_anchor must be {"journey": slug, "leg": index}')
    journey, leg = value["journey"], value["leg"]
    if not isinstance(journey, str) or type(leg) is not int or leg < 0:
        raise ValueError("longway_anchor needs a journey slug and a non-negative leg index")
    try:
        item = get_register().journey(journey)
    except (KeyError, ValueError):
        raise ValueError(f"unknown journey: {journey}")
    if leg >= len(item["segments"]):
        raise ValueError(f"{journey} has {len(item['segments'])} legs; leg {leg} does not exist")
    return {"journey": journey, "leg": leg, "from": item["segments"][leg]["from"], "to": item["segments"][leg]["to"]}


@lru_cache(maxsize=1)
def get_register():
    root = os.environ.get("LONGWAY_REPO")
    if not root:
        raise RuntimeError("DIALECTIC_ORGAN=longway requires LONGWAY_REPO")
    return Register(root)


def append_evidence(candidate_slug, row, author_name, author_email, **kwargs):
    return get_register().append_evidence(candidate_slug, row, author_name, author_email, **kwargs)
