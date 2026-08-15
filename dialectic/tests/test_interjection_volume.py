# tests/test_interjection_volume.py — the volume controls, measured 2026-08-15
"""
WHY THIS FILE: over a week of production decisions the participant produced
2.06 machine messages per human turn (214 vs 104). Four causes were traced to
values, not to config: an ungated annotator, a novelty threshold sitting inside
the bulk of its own distribution, a group rule firing in a two-person room, and
a case-mismatched SQL literal that pinned the outcome metric to False.

These tests pin the FIX, and each one is written to fail if the specific defect
returns. The novelty and imbalance cases use the real observed values from
llm_decisions rather than invented ones, so a regression is caught against the
distribution that actually motivated the change.
"""
import re
from pathlib import Path

import pytest

from llm.heuristics import (
    BALANCE_MIN_SPEAKERS,
    NOVELTY_THRESHOLD,
    InterjectionEngine,
)

SELF_MODEL_SRC = (Path(__file__).parent.parent / "llm" / "self_model.py").read_text()

# Semantic novelty values that FIRED under the old 0.70 threshold, straight out
# of the reason column. All but two are ordinary conversational drift.
OBSERVED_NOVELTY_FIRED = [
    0.71, 0.71, 0.72, 0.72, 0.72, 0.73, 0.73, 0.75, 0.76, 0.76, 0.77, 0.77,
    0.77, 0.78, 0.78, 0.78, 0.79, 0.79, 0.80, 0.81, 0.81, 0.82, 0.83, 0.84,
    0.84, 0.84, 0.86, 1.00,
]
# The highest novelty that did NOT fire. The old threshold split a continuous
# distribution 0.32..1.00 at 0.70 — there is no gap between these two sets.
OBSERVED_NOVELTY_SILENT_MAX = 0.69


def test_novelty_threshold_sits_in_the_tail_not_the_bulk():
    """The old 0.70 fired on 28 of 28; the new bar must reject the drift."""
    engine = InterjectionEngine()
    fired = [n for n in OBSERVED_NOVELTY_FIRED if n >= engine.semantic_novelty_threshold]

    # Mutation guard: at 0.70 this is 28 and the test goes red.
    assert len(fired) <= 5, (
        f"threshold {engine.semantic_novelty_threshold} still fires on "
        f"{len(fired)}/28 of the observed drift values"
    )
    # ...but it must not silence the genuine spikes either.
    assert 1.00 in fired, "a total topic change must still trigger"


def test_novelty_threshold_is_above_every_observed_silent_value():
    """A bar below this cannot separate the two populations at all."""
    assert NOVELTY_THRESHOLD > OBSERVED_NOVELTY_SILENT_MAX


def test_two_human_room_is_not_an_imbalance():
    """The exact speaker_balance payloads that fired balance_redirect 13x."""
    engine = InterjectionEngine()
    for payload in ({"a": 3, "b": 1}, {"a": 5, "b": 1}, {"a": 4, "b": 1}):
        assert not engine._detect_speaker_imbalance(payload), (
            f"{payload} is one person taking a few turns in a two-person room"
        )


def test_imbalance_still_fires_in_a_real_group():
    """The rule keeps working where it was designed to — 3+ speakers."""
    engine = InterjectionEngine()
    assert engine._detect_speaker_imbalance({"a": 8, "b": 1, "c": 1})
    assert not engine._detect_speaker_imbalance({"a": 4, "b": 3, "c": 3})
    assert BALANCE_MIN_SPEAKERS >= 3


def test_balance_redirect_does_not_fire_for_two_speakers_end_to_end():
    """Through decide(), not just the private helper — the rung is rung 7, so a
    dominated two-person window must fall all the way through to no_trigger."""
    engine = InterjectionEngine()
    decision = engine.decide(
        messages=[],
        mentioned=False,
        semantic_novelty=0.5,
        speaker_balance={"a": 5, "b": 1},
    )
    assert decision.should_interject is False
    assert decision.reason == "no_trigger"


def test_response_measurement_queries_the_stored_speaker_type():
    """The enum VALUE is 'human'; the MEMBER name is HUMAN. Querying the member
    name matches zero rows forever and pins human_responded to False.

    Matched at statement position so a comment quoting the old literal — this
    docstring, or the WHY block beside the query — cannot satisfy or break it.
    """
    from models import SpeakerType

    assert SpeakerType.HUMAN.value == "human"

    predicates = re.findall(
        r"^(?!\s*#)\s*AND speaker_type = '(\w+)'", SELF_MODEL_SRC, re.MULTILINE
    )
    assert predicates, "the speaker_type predicate moved — re-point this test"
    for literal in predicates:
        assert literal == SpeakerType.HUMAN.value, (
            f"self_model.py queries speaker_type = '{literal}', which never "
            f"matches the stored value '{SpeakerType.HUMAN.value}'"
        )


# ── the annotator worth gate ──────────────────────────────────────────────
# Condition 1 (nobody else online) is near-permanent in a two-person room, so
# everything downstream of it is what actually controls volume.


class FakeDB:
    """Presence count then annotations-today, in the order the gate asks."""

    def __init__(self, online=0, annotations_today=0):
        self.online = online
        self.annotations_today = annotations_today
        self.calls = 0

    async def fetchval(self, query, *args):
        self.calls += 1
        if "user_presence" in query:
            return self.online
        return self.annotations_today


class FakeMemory:
    def __init__(self, hits=0, raises=False):
        self.hits = hits
        self.raises = raises
        self.searches = 0

    async def search_memories(self, room_id, query, limit=10):
        self.searches += 1
        if self.raises:
            raise RuntimeError("recall lane down")
        return [object() for _ in range(self.hits)]


def _msg(content):
    from unittest.mock import Mock
    m = Mock()
    m.content = content
    return m


SUBSTANTIAL = "the hormuz cascade node fired again this morning, worth a look"


@pytest.mark.asyncio
async def test_annotates_when_there_is_something_to_connect():
    from llm.annotator import AnnotatorEngine
    from uuid import uuid4

    mem = FakeMemory(hits=3)
    engine = AnnotatorEngine(FakeDB(), mem, None)
    related = await engine.prepare_annotation(uuid4(), uuid4(), _msg(SUBSTANTIAL))

    assert related is not None
    # The contract: a non-None return is never empty, so "annotate" and "has
    # something to say" cannot come apart.
    assert len(related) == 3
    assert mem.searches == 1


@pytest.mark.asyncio
async def test_silent_when_recall_finds_nothing_to_connect():
    """34 of 104 production messages landed here — no memories, no breadcrumb."""
    from llm.annotator import AnnotatorEngine
    from uuid import uuid4

    engine = AnnotatorEngine(FakeDB(), FakeMemory(hits=0), None)
    assert await engine.prepare_annotation(uuid4(), uuid4(), _msg(SUBSTANTIAL)) is None


@pytest.mark.asyncio
async def test_substance_floor_skips_acknowledgements_before_paying_for_recall():
    """15 of 104 production messages were "ok"-class. The floor must cut them
    WITHOUT spending an embedding — that is the point of ordering it first."""
    from llm.annotator import AnnotatorEngine
    from uuid import uuid4

    mem = FakeMemory(hits=5)
    engine = AnnotatorEngine(FakeDB(), mem, None)

    assert await engine.prepare_annotation(uuid4(), uuid4(), _msg("ok")) is None
    assert await engine.prepare_annotation(uuid4(), uuid4(), _msg("sure thing")) is None
    assert mem.searches == 0, "the substance floor must run before recall"


@pytest.mark.asyncio
async def test_a_short_question_still_earns_a_breadcrumb():
    """"why?" is below the character floor and worth marking anyway."""
    from llm.annotator import AnnotatorEngine
    from uuid import uuid4

    engine = AnnotatorEngine(FakeDB(), FakeMemory(hits=2), None)
    assert await engine.prepare_annotation(uuid4(), uuid4(), _msg("why?")) is not None


@pytest.mark.asyncio
async def test_failed_recall_stays_silent_rather_than_annotating_blind():
    """Recall IS the gate — if it cannot run, worth cannot be judged."""
    from llm.annotator import AnnotatorEngine
    from uuid import uuid4

    engine = AnnotatorEngine(FakeDB(), FakeMemory(raises=True), None)
    assert await engine.prepare_annotation(uuid4(), uuid4(), _msg(SUBSTANTIAL)) is None


@pytest.mark.asyncio
async def test_daily_cap_still_bounds_a_runaway():
    from llm.annotator import ANNOTATOR_DAILY_CAP, AnnotatorEngine
    from uuid import uuid4

    mem = FakeMemory(hits=5)
    at_cap = FakeDB(annotations_today=ANNOTATOR_DAILY_CAP)
    engine = AnnotatorEngine(at_cap, mem, None)

    assert await engine.prepare_annotation(uuid4(), uuid4(), _msg(SUBSTANTIAL)) is None
    assert at_cap.calls == 2, "the cap must actually be counted, not assumed"
    assert mem.searches == 0, "the cap must short-circuit before recall"


@pytest.mark.asyncio
async def test_still_silent_when_someone_else_is_online():
    """The original condition must survive the change."""
    from llm.annotator import AnnotatorEngine
    from uuid import uuid4

    mem = FakeMemory(hits=5)
    engine = AnnotatorEngine(FakeDB(online=1), mem, None)
    assert await engine.prepare_annotation(uuid4(), uuid4(), _msg(SUBSTANTIAL)) is None
    assert mem.searches == 0
