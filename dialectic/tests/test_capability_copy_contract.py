# tests/test_capability_copy_contract.py — a 16th job must be a BUILD ERROR.
#
# WHY THIS FILE EXISTS: the help screen reads its job list from the running
# scheduler (api/capabilities.py), and the frontend pairs each name with
# authored copy in CapabilityMap.tsx's JOB_COPY. A job with no entry still
# renders — as raw snake_case, with no explanation. That is not a crash and no
# test noticed: on 2026-08-21 SIX of fifteen jobs were in that state, including
# `question_round`, two days before the first Sunday Round was due to fire. The
# only thing the product said about its headline feature was the literal string
# "question_round".
#
# sceneIdentity.ts fences scenes with a total Record over a union, so the
# compiler refuses a missing scene. Job names are strings crossing a language
# boundary and cannot use the type system that way, so the fence is this test.
#
# HOW THE ROSTER IS FOUND, and why not by grepping for `Job(`: a regex over
# llm/*.py is a source-text assertion, and this repo has been burned repeatedly
# by those — a name in a COMMENT satisfies one. So the roster is EXECUTED. We
# read api/main.py only for the list of register functions its lifespan imports,
# then import and CALL each against a real Scheduler and read `job.name` off the
# real Job objects. A comment cannot manufacture a Job; a docstring cannot hide
# one. It also means the roster is the one the app actually boots with.
#
# THE TSX SIDE IS the source-text assertion, unavoidably — a Python test cannot
# execute a TS module. So it matches KEY POSITION (`^  <name>: {`) inside the
# JOB_COPY literal, with comments stripped first. Mutation-proven both ways:
# deleting an entry goes red naming the job, and putting the deleted name in a
# comment instead STAYS red.

import importlib
import re
from pathlib import Path

import pytest

from scheduler import Scheduler, SchedulerContext

DIALECTIC_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = DIALECTIC_ROOT / "api" / "main.py"
CAPABILITY_MAP_TSX = (
    DIALECTIC_ROOT / "frontend" / "app" / "src" / "components" / "layout"
    / "CapabilityMap.tsx"
)

# If discovery silently breaks, an empty roster would make every assertion below
# pass vacuously. These three are load-bearing and long-lived; their absence
# means the parse broke, not that the jobs went away.
_ANCHOR_JOBS = {"morning_brief", "question_round", "scheduler_heartbeat"}

_REGISTER_IMPORT = re.compile(
    r"^\s*from\s+([\w.]+)\s+import\s+(register_\w+)\s*$", re.M
)


def registered_job_names() -> set[str]:
    """Every job name the app registers, read off real Job objects."""
    source = MAIN_PY.read_text(encoding="utf-8")
    pairs = _REGISTER_IMPORT.findall(source)
    assert pairs, f"no register_* imports found in {MAIN_PY}"

    scheduler = Scheduler(SchedulerContext(pool=None))
    for module_name, func_name in pairs:
        module = importlib.import_module(module_name)
        getattr(module, func_name)(scheduler)
    return {job.name for job in scheduler.jobs}


def _strip_comments(source: str) -> str:
    """Comments cannot satisfy or break a key-position match."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def job_copy_keys() -> set[str]:
    """The keys of JOB_COPY, matched at KEY POSITION inside its literal."""
    source = _strip_comments(CAPABILITY_MAP_TSX.read_text(encoding="utf-8"))
    start = source.find("const JOB_COPY")
    assert start != -1, f"JOB_COPY not found in {CAPABILITY_MAP_TSX}"
    end = source.find("\n}\n", start)
    assert end != -1, "JOB_COPY literal is not closed at column 0"
    body = source[start:end]
    # Two-space indent is the object's own top level; a nested `label:` /
    # `what:` sits deeper and does not open a brace, so it cannot match.
    return set(re.findall(r"^  '?([a-z_][a-z0-9_]*)'?:\s*\{", body, re.M))


@pytest.fixture(scope="module")
def roster() -> set[str]:
    return registered_job_names()


@pytest.fixture(scope="module")
def copy_keys() -> set[str]:
    return job_copy_keys()


def test_discovery_is_not_vacuous(roster, copy_keys):
    missing = _ANCHOR_JOBS - roster
    assert not missing, (
        f"job discovery looks broken — anchors missing from the roster: "
        f"{sorted(missing)}. Found: {sorted(roster)}"
    )
    assert copy_keys, "JOB_COPY parsed to zero keys — the matcher is broken"


def test_every_registered_job_has_copy(roster, copy_keys):
    """A job the reader cannot be told about is a job that renders as
    snake_case on the help screen. Add an entry to JOB_COPY in
    frontend/app/src/components/layout/CapabilityMap.tsx."""
    uncopied = roster - copy_keys
    assert not uncopied, (
        f"{len(uncopied)} scheduled job(s) have no entry in JOB_COPY and will "
        f"render as raw snake_case: {sorted(uncopied)}"
    )


@pytest.mark.parametrize("value,expected", [(None, False), ("0", False), ("1", True)])
def test_the_projection_agrees_with_the_body_gate(monkeypatch, value, expected):
    """A job that returns early on every tick must not report itself running.

    congress_watch is the one job in the roster that ships DARK, and until
    2026-08-21 it was the one job whose two gates disagreed: scheduler.Job's
    generic enabled() defaults an UNSET env to ON, while the body's _enabled()
    defaults it to OFF. CONGRESS_WATCH_ENABLED is unset in production, so
    GET /rooms/{id}/capabilities answered enabled=true for a job that did
    nothing, and the help screen printed "on" — the exact failure
    api/capabilities.py's docstring swears cannot happen.

    Asserting agreement alone would be tautological now that one delegates to
    the other, so `expected` pins WHICH answer they agree on.
    """
    from llm import congress_watch

    if value is None:
        monkeypatch.delenv(congress_watch.ENABLED_ENV, raising=False)
    else:
        monkeypatch.setenv(congress_watch.ENABLED_ENV, value)

    scheduler = Scheduler(SchedulerContext(pool=None))
    congress_watch.register_congress_watch_jobs(scheduler)
    job = next(j for j in scheduler.jobs if j.name == "congress_watch")

    assert job.enabled() is expected, (
        f"the scheduler (and so the help screen) says enabled={job.enabled()} "
        f"while the body gate says {congress_watch._enabled()}"
    )
    assert congress_watch._enabled() is expected


def test_no_copy_for_a_job_that_does_not_run(roster, copy_keys):
    """The other direction, and the same defect: prose describing a job the
    scheduler no longer registers advertises a door the server refuses."""
    orphans = copy_keys - roster
    assert not orphans, (
        f"JOB_COPY describes {len(orphans)} job(s) nothing registers: "
        f"{sorted(orphans)}"
    )
