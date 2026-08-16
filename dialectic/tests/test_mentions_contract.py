"""The participant's handles exist on both sides of the wire — pin them.

`llm/mentions.py` decides whether Dialectic was ADDRESSED (rung 0 of the
interjection ladder reads it). `frontend/app/src/lib/mentions.ts` decides how
an address is PAINTED. Two copies of the same three words, which is exactly
the drift this repo has been bitten by before.

The assertions below match STATEMENTS, not prose: a comment quoting an alias
must not be able to satisfy them, and a missing extraction must fail loudly
rather than compare two empty lists.
"""

import re
from pathlib import Path

import pytest

from llm.mentions import _LLM_ALIAS_PREFIXES, LLM_MENTION_RE

TS_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "frontend" / "app" / "src" / "lib" / "mentions.ts"
)


@pytest.fixture(scope="module")
def ts_aliases() -> list[str]:
    if not TS_SOURCE.exists():
        pytest.skip(f"frontend source not present: {TS_SOURCE}")
    source = TS_SOURCE.read_text(encoding="utf-8")
    # Anchored at statement position so a line of prose cannot satisfy it.
    match = re.search(
        r"^export const PARTICIPANT_ALIASES\s*=\s*\[([^\]]*)\]", source, re.M,
    )
    assert match, "PARTICIPANT_ALIASES assignment not found in mentions.ts"
    aliases = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    assert aliases, "extraction found the statement but no aliases — the guard is blind"
    return aliases


def test_typescript_aliases_match_the_python_tuple(ts_aliases):
    assert sorted(ts_aliases) == sorted(_LLM_ALIAS_PREFIXES)


def test_typescript_aliases_match_the_mention_regex(ts_aliases):
    alternation = re.search(r"@\(([a-z|]+)\)", LLM_MENTION_RE.pattern)
    assert alternation, "LLM_MENTION_RE no longer has an alias alternation"
    assert sorted(ts_aliases) == sorted(alternation.group(1).split("|"))


def test_both_sides_agree_on_the_prefix_rule():
    """`@llmThe` — a real message, the space lost to a fast thumb — is us.

    The server errs toward speech when it misparses an address; the client
    must not paint that same handle as a stranger.
    """
    from llm.mentions import addresses_someone_else
    assert addresses_someone_else("@amo @llmThe oil futures curve split") is False
