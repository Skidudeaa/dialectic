"""Real repo projection and isolated git-write contracts; no live repo writes."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from organs.longway.register import Register, CommitsDisabled, get_register
from organs.longway.identity import scout_identity

SOURCE = Path(os.environ.get("LONGWAY_TEST_SOURCE", "/root/theLongWay"))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def longway_repo(tmp_path, monkeypatch):
    if not (SOURCE / "tools/longway.py").exists():
        pytest.skip("Set LONGWAY_TEST_SOURCE to the Long Way repo for its real projection")
    root = tmp_path / "longway"
    for relative in ("tools/longway.py", "CHARTER.md", "AGENTS.md", "templates/candidate.md", "templates/trip.md"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / relative, target)
    (root / "archive").mkdir()
    (root / "archive/coverage.json").write_text("[]")
    register = Register(root)
    module = register.module
    for kind, slug in (("candidate", "ogasawara"), ("trip", "friends-2027"), ("trip", "private-trip")):
        folder = module.new_record(root, kind, slug, slug)
        record = module.obj(folder / "record.json")
        record.update(route=[[35.65,139.76,"Tokyo"],[27.09,142.19,"Chichijima"]])
        if kind == "candidate":
            record.update(legs=[{"from":"Tokyo","to":"Chichijima","basis":["S1"]}],
                season={"good":[9,10],"possible":[8,11],"avoid":[],"basis":"hypothesis","note":"Test hypothesis"},
                vehicles=[{"name":"Ogasawara Maru","kind":"ship","operator":"Ogasawara Kaiun","mmsi":"431347000","imo":"9767687","legs":[["Tokyo","Chichijima"]],"basis":["S1"],"timetable":"https://www.ogasawarakaiun.co.jp/"}])
            (folder / "dossier.md").write_text("# Ogasawara\n\n## The pull\nOcean crossing\n\n## Next decision\nWhich month should we investigate?\n")
            entry = dict(id="S1",claim="The ferry sails weekly",status="unverified",url="https://www.ogasawarakaiun.co.jp/",publisher="Ogasawara Kaiun",published_at=None,checked_at=None,support="The ferry sails weekly",scope="Tokyo",recheck_before="before booking")
            (folder / "evidence.jsonl").write_text(json.dumps(entry)+"\n")
        else:
            record.update(shared=slug=="friends-2027",window={"start":"2027-08","end":"2027-11"},reservation="BOOKING-PRIVATE-123")
            (folder / "plan.md").write_text("# Trip\n\n## Established\nAutumn journey\n\n## Bookings\nBOOKING-PRIVATE-123\n\n## Undecided\nWhich month?\n")
            (folder / "evidence.jsonl").write_text("BOOKING-PRIVATE-123")
        module.put_json(folder / "record.json",record)
    git(root,"init","-q")
    git(root,"config","user.name","Fixture")
    git(root,"config","user.email","fixture@localhost")
    git(root,"add",".")
    git(root,"commit","-qm","Initial register")
    monkeypatch.setenv("LONGWAY_REPO",str(root))
    get_register.cache_clear()
    scout_identity.cache_clear()
    yield register
    get_register.cache_clear()
    scout_identity.cache_clear()


def evidence():
    return dict(claim="The ferry sails weekly",status="verified",url="https://www.ogasawarakaiun.co.jp/",publisher="Ogasawara Kaiun",published_at=None,checked_at="2026-10-01",support="The ferry sails weekly",scope="Tokyo",recheck_before="set by the researcher")


def test_private_material_never_read_or_projected(longway_repo, monkeypatch):
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if "trips" in path.parts and path.name == "evidence.jsonl":
            pytest.fail("Trip evidence must never be opened")
        if "private-trip" in path.parts and path.name == "plan.md":
            pytest.fail("Private plan must never be opened")
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,"read_text",guarded)
    chart = longway_repo.chart()
    assert len(chart["journeys"]) == 2
    assert chart["journeys"][0]["segments"][0]["ink"] == "dotted"
    assert "BOOKING-PRIVATE" not in json.dumps(chart)
    shared = longway_repo.journey("friends-2027")
    assert "Which month?" in shared["plan"]["undecided"]
    assert "BOOKING-PRIVATE" not in json.dumps(shared)
    with pytest.raises(KeyError):
        longway_repo.journey("private-trip")
    with pytest.raises(ValueError):
        longway_repo.journey("../../private")
    assert "hypothesis" in longway_repo.fit_window("friends-2027")


def test_append_disabled_and_validation_rollback(longway_repo,monkeypatch):
    before = git(longway_repo.root,"rev-parse","HEAD")
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","0")
    with pytest.raises(CommitsDisabled):
        longway_repo.append_evidence("ogasawara",evidence(),"Alice","alice@example.org")
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","1")
    with pytest.raises(ValueError,match="check failed"):
        longway_repo.append_evidence("ogasawara",dict(evidence(),support=""),"Alice","alice@example.org")
    assert git(longway_repo.root,"rev-parse","HEAD") == before
    assert len(longway_repo.evidence("ogasawara")) == 1
    assert not git(longway_repo.root,"status","--porcelain")


def test_append_one_file_author_and_retry(longway_repo,monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","1")
    unrelated = longway_repo.root / "unrelated.txt"
    unrelated.write_text("keep staged")
    git(longway_repo.root,"add","unrelated.txt")
    result = longway_repo.append_evidence("ogasawara",evidence(),"Alice","alice@example.org",proposal_id="1234")
    assert result["sid"] == "S2"
    assert git(longway_repo.root,"log","-1","--format=%an <%ae>") == "Alice <alice@example.org>"
    assert git(longway_repo.root,"show","--format=","--name-only","HEAD") == "candidates/ogasawara/evidence.jsonl"
    assert git(longway_repo.root,"diff","--cached","--name-only") == "unrelated.txt"
    assert longway_repo.append_evidence("ogasawara",evidence(),"Alice","alice@example.org",proposal_id="1234") == result
    assert len(longway_repo.evidence("ogasawara")) == 2
    assert not longway_repo.candidates.check(longway_repo.root)[0]


def test_scout_reads_charter(longway_repo):
    identity = scout_identity()
    for phrase in ("Go far enough to be surprised", "Why this place?", "Why this approach?", "Where is the human dimension?", "Where is the room for surprise?", "What remains without the mythology?", "(S1, S14)", "Name the actual failure mode", "Freshness follows the decision"):
        assert phrase in identity


def test_scout_prompt_preserves_room_rules_and_other_personas(longway_repo,monkeypatch):
    import organ
    from organs import longway
    from llm.prompts import PromptBuilder
    from tests.conftest import make_room
    monkeypatch.setattr(organ,"active",longway)
    room=make_room(global_rules="Each friend can decline",global_ontology="A claim is not a booking")
    builder=PromptBuilder()
    prompt=builder.build(room,[],[],[])
    assert "Go far enough to be surprised" in prompt.system
    assert "Each friend can decline" in prompt.system
    assert "A claim is not a booking" in prompt.system
    assert "You are the Scout" not in builder.build(room,[],[],[],is_provoker=True).system
