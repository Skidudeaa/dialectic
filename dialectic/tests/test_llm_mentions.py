import pytest

from llm.mentions import addresses_someone_else, contains_explicit_llm_mention


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


# ── The address block: who a message is TO, vs what it is ABOUT ──


@pytest.mark.parametrize(
    "text",
    [
        # The message that prompted this rule (Home, 2026-08-15): a request
        # to Amo that names the participant as its SUBJECT.
        "@amo feature idea can you make it highlight the name if it is one "
        "of us and make the @llm a different color",
        "@dan what do you think about the BOJ?",
        "@dan, @amo — thoughts?",
        "  @amo ping",
    ],
)
def test_leading_handles_without_us_hand_the_turn_away(text: str) -> None:
    assert addresses_someone_else(text)


@pytest.mark.parametrize(
    "text",
    [
        "@dialectic what do you think?",
        "@dan @dialectic what do you both think?",   # address block includes us
        "hey @dialectic what do you think?",         # summons, no address block
        "the @llm should be blue",                   # about us, not to anyone
        "what do you think about the BOJ?",
        "email@dialectic.example",
        "",
    ],
)
def test_everything_else_leaves_the_ladder_alone(text: str) -> None:
    assert not addresses_someone_else(text)


def test_a_typo_in_our_handle_still_counts_as_being_addressed() -> None:
    """Real message, 2026-08-15: the space between the handles was lost.

    Erring toward speech is the safe direction — a misparsed address that
    stays silent drops a direct summons on the floor.
    """
    assert not addresses_someone_else(
        "@amo @llmThe oil futures curve just split into two markets")
