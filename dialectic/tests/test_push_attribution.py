"""Push attribution: LLM speakers must be labeled Claude, humans by name.

Regression for the always-False uppercase comparison that left every LLM push
attributed to the triggering human.
"""

import pytest

from models import SpeakerType
from transport.handlers import is_llm_speaker


@pytest.mark.parametrize("speaker", [
    SpeakerType.LLM_PRIMARY,
    SpeakerType.LLM_PROVOKER,
    SpeakerType.LLM_ANNOTATOR,
])
def test_llm_speakers_are_llm(speaker):
    assert is_llm_speaker(speaker) is True


@pytest.mark.parametrize("speaker", [SpeakerType.HUMAN, SpeakerType.SYSTEM])
def test_non_llm_speakers_are_not(speaker):
    assert is_llm_speaker(speaker) is False
