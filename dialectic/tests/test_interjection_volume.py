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


@pytest.mark.asyncio
async def test_annotator_stops_at_the_daily_cap():
    """Condition 1 (nobody else online) is near-permanent in a 2-person room,
    so the cap is the only thing standing between it and one note per message."""
    from uuid import uuid4
    from llm.annotator import ANNOTATOR_DAILY_CAP, AnnotatorEngine

    class FakeDB:
        def __init__(self, annotations_today):
            self.annotations_today = annotations_today
            self.calls = 0

        async def fetchval(self, query, *args):
            self.calls += 1
            # First call is the presence check, second is the cap count.
            if "user_presence" in query:
                return 0  # nobody else online — the always-true condition
            return self.annotations_today

    room, sender = uuid4(), uuid4()

    under = FakeDB(ANNOTATOR_DAILY_CAP - 1)
    assert await AnnotatorEngine(under, None, None).should_annotate(room, sender)

    at_cap = FakeDB(ANNOTATOR_DAILY_CAP)
    assert not await AnnotatorEngine(at_cap, None, None).should_annotate(room, sender)
    assert at_cap.calls == 2, "the cap must actually be counted, not assumed"


@pytest.mark.asyncio
async def test_annotator_still_silent_when_someone_else_is_online():
    """The original condition must survive the change."""
    from uuid import uuid4
    from llm.annotator import AnnotatorEngine

    class OnlineDB:
        async def fetchval(self, query, *args):
            return 1  # another human is present

    engine = AnnotatorEngine(OnlineDB(), None, None)
    assert not await engine.should_annotate(uuid4(), uuid4())
