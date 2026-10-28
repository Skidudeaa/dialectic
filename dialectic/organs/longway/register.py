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


class CommitsDisabled(RuntimeError):
    pass


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

    def candidate(self, slug):
        self.module.valid_slug(slug)
        path = self.local(f"candidates/{slug}/record.json")
        if not path.is_file() or self.module.obj(path).get("kind") != "candidate":
            raise ValueError(f"Unknown candidate: {slug}")
        return slug

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
