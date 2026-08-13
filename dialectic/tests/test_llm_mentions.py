import pytest

from llm.mentions import contains_explicit_llm_mention


@pytest.mark.parametrize(
    "text",
    [
        "@Dialectic examine this",
        "@dialectic examine this",
        "@Claude examine this",
        "@claude examine this",
        "@llm examine this",
    ],
)
def test_explicit_participant_aliases_are_mentions(text: str) -> None:
    assert contains_explicit_llm_mention(text)


@pytest.mark.parametrize(
    "text",
    [
        "dialectical materialism",
        "claudette said hello",
        "email@dialectic.example",
        "the llm should notice this without a summon",
    ],
)
def test_non_mentions_do_not_trigger(text: str) -> None:
    assert not contains_explicit_llm_mention(text)
