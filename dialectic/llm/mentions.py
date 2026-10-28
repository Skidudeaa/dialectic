import re
from functools import lru_cache


# Product identity first; provider-era aliases remain accepted compatibility.
# The left boundary prevents an email/domain fragment such as
# `email@dialectic.example` from summoning the participant.
_BASE_ALIASES = ("dialectic", "claude", "llm")
LLM_MENTION_RE = re.compile(
    r"(?<![\w.+-])@(dialectic|claude|llm)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def participant_aliases() -> tuple[str, ...]:
    """The handles that summon the participant: the product-era names plus the active organ's participant
    (The Long Way's Scout). WHY read the organ at first use and never at import: organs.longway imports the
    llm package, which imports this module, so an import-time read of `organ` is a circular import."""
    from organ import identity
    participant = str(identity().get("participant") or "").strip().lower()
    return _BASE_ALIASES + ((participant,) if participant and participant not in _BASE_ALIASES else ())


@lru_cache(maxsize=1)
def _mention_re() -> re.Pattern:
    return re.compile(
        r"(?<![\w.+-])@(" + "|".join(re.escape(a) for a in participant_aliases()) + r")\b",
        re.IGNORECASE,
    )


# The ADDRESS BLOCK: the run of @handles a message opens with. People write
# the people they are talking TO at the front, and everything after that is
# subject matter — "@amo can you make the @llm a different color" is a
# request to Amo that happens to be ABOUT the participant.
LEADING_ADDRESS_RE = re.compile(r"^\s*((?:@[A-Za-z][\w-]*[\s,:;]*)+)")
_ADDRESS_HANDLE_RE = re.compile(r"@([A-Za-z][\w-]*)")

# Inside an address block, a handle that STARTS with an alias is us — the
# `\b` that LLM_MENTION_RE needs to keep `@dialectical` from summoning is
# the wrong test here. A real message read "@amo @llmThe oil futures curve
# just split..." (the space lost to a fast thumb); the block plainly names
# both of us, and reading it as Amo-only would silence a direct summons.
# Erring toward speech is the safe direction for an address we misparse.
_LLM_ALIAS_PREFIXES = _BASE_ALIASES


def contains_explicit_llm_mention(text: str) -> bool:
    """Return whether text explicitly summons the participant (by any of its handles)."""
    return bool(_mention_re().search(text))


def addresses_someone_else(text: str) -> bool:
    """Text opens by handing the turn to people who do not include us.

    WHY this needs its own question, and why it has to outrank the explicit
    mention rather than sit under it: "@amo feature idea can you make it
    highlight the name ... and make the @llm a different color" contains
    `@llm`, so mention detection fired rung 1 and the participant answered a
    request addressed to a human, opening — accurately — "This one's not for
    me to weigh in on." Being right about that in the reply is not the same
    as staying out of it.

    A message with no leading address block returns False and changes
    nothing: "hey @dialectic what do you think" still summons from anywhere,
    which is what mention detection is for.
    """
    if not text:
        return False
    match = LEADING_ADDRESS_RE.match(text)
    if not match:
        return False
    handles = _ADDRESS_HANDLE_RE.findall(match.group(1))
    prefixes = participant_aliases()
    return not any(
        handle.lower().startswith(prefixes) for handle in handles
    )
