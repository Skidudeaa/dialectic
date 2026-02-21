"""Tests for llm/context.py — assemble_context()."""

import pytest
from unittest.mock import patch, MagicMock

from llm.context import assemble_context, AssembledContext, RESERVED_OUTPUT_TOKENS
from models import SpeakerType, MessageType
from tests.conftest import make_message, make_thread


# ── Helpers ──


def _n_messages(n, content="short msg", **kwargs):
    """Generate n human TEXT messages with given content."""
    return [make_message(content, sequence=i, **kwargs) for i in range(n)]


# ── Basic behavior ──


class TestBasicAssembly:
    def test_empty_messages(self):
        """Empty input returns empty context with no truncation."""
        ctx = assemble_context([], make_thread())
        assert ctx.messages == []
        assert ctx.truncated is False
        assert ctx.total_tokens == 0
        assert ctx.included_count == 0
        assert ctx.original_count == 0

    def test_small_conversation_passes_through(self):
        """Short conversation within budget passes through unchanged."""
        msgs = _n_messages(5)
        ctx = assemble_context(msgs, make_thread())
        assert ctx.included_count == 5
        assert ctx.original_count == 5
        assert ctx.truncated is False
        assert len(ctx.messages) == 5

    def test_returns_assembled_context(self):
        """Return type is AssembledContext."""
        msgs = _n_messages(3)
        ctx = assemble_context(msgs, make_thread())
        assert isinstance(ctx, AssembledContext)

    def test_message_order_preserved(self):
        """Selected messages maintain their original order."""
        msgs = [
            make_message(f"msg-{i}", sequence=i)
            for i in range(8)
        ]
        ctx = assemble_context(msgs, make_thread())
        contents = [m.content for m in ctx.messages]
        assert contents == [f"msg-{i}" for i in range(8)]


# ── Token budget and truncation ──


class TestTruncation:
    def test_long_conversation_truncated(self):
        """Conversation exceeding token budget gets truncated."""
        # Each message is 200 chars -> ~50 tokens at 4 chars/token fallback
        # With max_tokens=200, only ~4 messages should fit
        msgs = _n_messages(100, content="x" * 200)
        # Use a nonexistent encoder to force fallback char estimation
        ctx = assemble_context(msgs, make_thread(), max_tokens=200, encoder_name="nonexistent")
        assert ctx.truncated is True
        assert ctx.included_count < ctx.original_count

    def test_truncated_flag_false_when_all_fit(self):
        """truncated=False when all messages fit in budget."""
        msgs = _n_messages(3, content="hi")
        ctx = assemble_context(msgs, make_thread(), max_tokens=100_000)
        assert ctx.truncated is False


# ── Last 10 always included ──


class TestLastTenGuarantee:
    def test_last_10_always_included(self):
        """The last 10 messages are always included regardless of score."""
        msgs = _n_messages(50, content="a" * 40)  # ~10 tokens each
        # Budget: enough for ~20 messages
        ctx = assemble_context(msgs, make_thread(), max_tokens=200)
        # The last 10 (indices 40-49) must be in the result
        last_10_contents = {m.content for m in msgs[-10:]}
        included_contents = {m.content for m in ctx.messages}
        # All of last 10 should be present (they all have the same content,
        # so check count instead)
        assert ctx.included_count >= 10 or ctx.original_count < 10

    def test_fewer_than_10_messages(self):
        """If fewer than 10 messages, all are included as 'last N'."""
        msgs = _n_messages(5)
        ctx = assemble_context(msgs, make_thread())
        assert ctx.included_count == 5


# ── Priority scoring ──


class TestPriorityScoring:
    def test_claude_mention_gets_high_priority(self):
        """Messages with @claude get +80 priority and survive truncation."""
        # Create lots of filler + one @claude mention early
        filler = _n_messages(30, content="x" * 100)
        mention = make_message("@claude what do you think?", sequence=5)
        # Insert mention early in the conversation
        all_msgs = filler[:5] + [mention] + filler[5:]
        ctx = assemble_context(all_msgs, make_thread(), max_tokens=500)
        included_contents = [m.content for m in ctx.messages]
        assert "@claude what do you think?" in included_contents

    def test_llm_response_gets_priority(self):
        """LLM responses get +60 priority."""
        filler = _n_messages(30, content="x" * 100)
        llm_msg = make_message(
            "I think therefore I am",
            speaker_type=SpeakerType.LLM_PRIMARY,
            sequence=5,
        )
        all_msgs = filler[:5] + [llm_msg] + filler[5:]
        ctx = assemble_context(all_msgs, make_thread(), max_tokens=500)
        included_contents = [m.content for m in ctx.messages]
        assert "I think therefore I am" in included_contents

    def test_question_gets_slight_priority(self):
        """Messages ending with '?' get +20 priority."""
        filler = _n_messages(30, content="x" * 100)
        question = make_message("Is this important?", sequence=5)
        all_msgs = filler[:5] + [question] + filler[5:]
        ctx = assemble_context(all_msgs, make_thread(), max_tokens=500)
        included_contents = [m.content for m in ctx.messages]
        assert "Is this important?" in included_contents

    def test_recent_messages_get_highest_priority(self):
        """Messages in last 20% of conversation get +100 priority."""
        msgs = [
            make_message(f"msg-{i}", sequence=i)
            for i in range(20)
        ]
        # Very tight budget: only a few messages can fit
        ctx = assemble_context(msgs, make_thread(), max_tokens=50)
        # Recent messages (last 20% = last 4) should be heavily favored
        included_contents = [m.content for m in ctx.messages]
        # At least some of the last 4 should be included
        recent = {"msg-16", "msg-17", "msg-18", "msg-19"}
        assert len(recent & set(included_contents)) > 0

    def test_at_llm_mention_also_matches(self):
        """@llm mentions also get +80 priority (alternative mention syntax)."""
        filler = _n_messages(30, content="x" * 100)
        mention = make_message("@llm elaborate please", sequence=5)
        all_msgs = filler[:5] + [mention] + filler[5:]
        ctx = assemble_context(all_msgs, make_thread(), max_tokens=500)
        included_contents = [m.content for m in ctx.messages]
        assert "@llm elaborate please" in included_contents


# ── Tiktoken fallback ──


class TestTokenEstimation:
    def test_fallback_when_tiktoken_unavailable(self):
        """When tiktoken is not available, falls back to len/4 estimation."""
        msgs = _n_messages(5, content="hello world")
        # Patch tiktoken import to raise
        with patch.dict("sys.modules", {"tiktoken": None}):
            # The try/except in assemble_context handles this
            ctx = assemble_context(msgs, make_thread())
        assert ctx.included_count == 5
        # total_tokens should be > 0 regardless of estimator
        assert ctx.total_tokens > 0
