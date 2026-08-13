import re


# Product identity first; provider-era aliases remain accepted compatibility.
# The left boundary prevents an email/domain fragment such as
# `email@dialectic.example` from summoning the participant.
LLM_MENTION_RE = re.compile(
    r"(?<![\w.+-])@(dialectic|claude|llm)\b",
    re.IGNORECASE,
)


def contains_explicit_llm_mention(text: str) -> bool:
    """Return whether text explicitly summons the Dialectic participant."""
    return bool(LLM_MENTION_RE.search(text))
