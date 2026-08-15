# tests/test_briefing_excludes_annotator.py — the brief must not read itself
"""
WHY: the morning brief POSTS as llm_annotator, and the summary corpus had no
speaker_type filter — so each night's brief read the previous night's brief
back as conversation to summarize. In Home, whose last window held three
annotator notes and zero human messages, that produced a brief addressed to
nobody: "It looks like the conversation details got cut off partway
through—could you paste…". That is the last thing in the room the two humans
share, and it is the machine talking to itself.

The same filter fixes `messages_missed`, which counted the machine's own
marginalia as messages a human missed — it gates night_shift's "quiet" branch
and drives the push notification, so an unfiltered count wakes someone up over
the machine's own notes.

Matched at statement position, so the WHY comment beside the query (which
necessarily names 'llm_annotator') can neither satisfy nor break these.
"""
import re
from pathlib import Path

BRIEFING_SRC = (Path(__file__).parent.parent / "llm" / "briefing.py").read_text()

# Every WHERE-clause chain that builds the summary corpus.
_CORPUS_QUERIES = re.findall(
    r"FROM messages m\b.*?LIMIT 100", BRIEFING_SRC, re.DOTALL
)


def test_both_corpus_queries_exist():
    """One branch excludes the returning reader, one does not — if this count
    changes, the filter below may have been added to only one of them."""
    assert len(_CORPUS_QUERIES) == 2, (
        f"expected 2 summary-corpus queries, found {len(_CORPUS_QUERIES)}"
    )


def test_every_corpus_query_excludes_the_annotator_lane():
    for query in _CORPUS_QUERIES:
        predicates = re.findall(
            r"^(?!\s*(?:#|--))[^\n]*speaker_type\s*!=\s*'(\w+)'",
            query,
            re.MULTILINE,
        )
        assert "llm_annotator" in predicates, (
            "a summary-corpus query does not exclude llm_annotator, so the "
            "brief can summarize its own previous output"
        )


def test_participant_lanes_are_not_excluded():
    """Claude is a participant — llm_primary and llm_provoker turns ARE the
    conversation someone missed. Only the annotator lane is marginalia written
    FOR the absent person, which is exactly what a brief must not mistake for
    what they were absent from."""
    for lane in ("llm_primary", "llm_provoker", "human"):
        assert f"speaker_type != '{lane}'" not in BRIEFING_SRC, (
            f"{lane} must stay in the brief — excluding it would hide real "
            f"conversation from the person returning to it"
        )
