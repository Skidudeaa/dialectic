"""The Long Way's message anchor: a journey leg, checked against the register (organs/longway/register.py)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from organs.longway import register as register_mod


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A one-candidate Long Way repo with two legs, so the index check has an edge."""
    source = Path("/root/theLongWay/tools/longway.py")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/longway.py").write_bytes(source.read_bytes())
    for name in ("candidates", "trips", "reports", "archive", "templates", "prompts", "docs"):
        (tmp_path / name).mkdir()
    (tmp_path / "archive/coverage.json").write_text("[]")
    (tmp_path / "project.json").write_text(json.dumps({"name": "The Long Way"}))
    folder = tmp_path / "candidates/two-legs"
    folder.mkdir()
    (folder / "record.json").write_text(json.dumps({
        "schema_version": 1, "kind": "candidate", "slug": "two-legs", "title": "Two legs", "status": "seed",
        "created_at": "2026-10-01", "updated_at": "2026-10-01", "feasibility": "unverified", "related": [],
        "provenance": "test", "reviewed_by": None, "reviewed_at": None,
        "route": [[1.0, 2.0, "A"], [3.0, 4.0, "B"], [5.0, 6.0, "C"]]}))
    (folder / "dossier.md").write_text("# Two legs\n\n## The pull\n\nA test.\n")
    (folder / "evidence.jsonl").write_text("")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    monkeypatch.setenv("LONGWAY_REPO", str(tmp_path))
    register_mod.get_register.cache_clear()
    yield tmp_path
    register_mod.get_register.cache_clear()


def test_valid_anchor_carries_the_leg_names(repo):
    assert register_mod.validate_anchor({"journey": "two-legs", "leg": 1}) == {
        "journey": "two-legs", "leg": 1, "from": "B", "to": "C"}


@pytest.mark.parametrize("value", [
    None, "two-legs", {"journey": "two-legs"}, {"journey": "two-legs", "leg": "0"}, {"journey": "two-legs", "leg": -1},
    {"journey": "two-legs", "leg": 2}, {"journey": "nowhere", "leg": 0}, {"journey": "two-legs", "leg": 0, "extra": 1},
])
def test_bad_anchors_are_refused(repo, value):
    with pytest.raises(ValueError):
        register_mod.validate_anchor(value)
