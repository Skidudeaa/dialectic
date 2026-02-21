"""Tests for llm/prompts.py — PromptBuilder.build()."""

import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from llm.prompts import PromptBuilder, AssembledPrompt
from models import SpeakerType, MessageType, MemoryScope
from tests.conftest import (
    make_message,
    make_room,
    make_user,
    make_memory,
    USER_A_ID,
    USER_B_ID,
)


@pytest.fixture
def builder():
    return PromptBuilder()


# ── Base identity ──


class TestBaseIdentity:
    def test_base_identity_included(self, builder):
        """System prompt starts with BASE_IDENTITY for non-provoker."""
        room = make_room()
        users = [make_user()]
        prompt = builder.build(room, users, [], [])
        assert "co-thinker" in prompt.system
        assert "not an assistant" in prompt.system

    def test_returns_assembled_prompt(self, builder):
        """Return type should be AssembledPrompt."""
        room = make_room()
        prompt = builder.build(room, [], [], [])
        assert isinstance(prompt, AssembledPrompt)
        assert isinstance(prompt.system, str)
        assert isinstance(prompt.messages, list)


# ── Provoker identity ──


class TestProvokerIdentity:
    def test_provoker_identity_used(self, builder):
        """When is_provoker=True, provoker identity replaces base."""
        room = make_room()
        prompt = builder.build(room, [], [], [], is_provoker=True)
        assert "destabilizing voice" in prompt.system
        assert "co-thinker" not in prompt.system

    def test_provoker_mentions_short_responses(self, builder):
        """Provoker identity instructs short responses."""
        room = make_room()
        prompt = builder.build(room, [], [], [], is_provoker=True)
        assert "SHORT" in prompt.system or "1-3 sentences" in prompt.system

    def test_non_provoker_excludes_provoker_text(self, builder):
        """Non-provoker should not include provoker-specific text."""
        room = make_room()
        prompt = builder.build(room, [], [], [], is_provoker=False)
        assert "destabilizing voice" not in prompt.system


# ── Room ontology and rules ──


class TestRoomContext:
    def test_ontology_included(self, builder):
        """Room global_ontology appears in system prompt."""
        room = make_room(global_ontology="All entities are processes")
        prompt = builder.build(room, [], [], [])
        assert "All entities are processes" in prompt.system
        assert "Ontology" in prompt.system

    def test_rules_included(self, builder):
        """Room global_rules appears in system prompt."""
        room = make_room(global_rules="No ad hominem arguments")
        prompt = builder.build(room, [], [], [])
        assert "No ad hominem arguments" in prompt.system
        assert "Rules" in prompt.system

    def test_ontology_and_rules_together(self, builder):
        """Both ontology and rules appear when both are set."""
        room = make_room(
            global_ontology="Process ontology",
            global_rules="Be civil",
        )
        prompt = builder.build(room, [], [], [])
        assert "Process ontology" in prompt.system
        assert "Be civil" in prompt.system

    def test_no_room_context_when_empty(self, builder):
        """No Room Context section when ontology and rules are None."""
        room = make_room(global_ontology=None, global_rules=None)
        prompt = builder.build(room, [], [], [])
        assert "Room Context" not in prompt.system


# ── Memory context ──


class TestMemoryContext:
    def test_memories_formatted(self, builder):
        """Memories appear as key-value entries in system prompt."""
        room = make_room()
        mems = [
            make_memory(key="consensus", content="We agree on dualism"),
            make_memory(key="open-q", content="What about qualia?"),
        ]
        prompt = builder.build(room, [], [], mems)
        assert "**consensus**" in prompt.system
        assert "We agree on dualism" in prompt.system
        assert "**open-q**" in prompt.system
        assert "What about qualia?" in prompt.system

    def test_shared_memory_header(self, builder):
        """Memory section has proper header."""
        room = make_room()
        mems = [make_memory()]
        prompt = builder.build(room, [], [], mems)
        assert "Shared Memory" in prompt.system

    def test_no_memory_section_when_empty(self, builder):
        """No memory section when no memories provided."""
        room = make_room()
        prompt = builder.build(room, [], [], [])
        assert "Shared Memory" not in prompt.system


# ── Cross-session context ──


class TestCrossSessionContext:
    def test_cross_session_included(self, builder):
        """Cross-session context is appended when provided."""
        room = make_room()
        mock_ctx = MagicMock()
        mock_ctx.total_injected = 3
        mock_ctx.to_prompt_section.return_value = (
            "## Cross-Session Context\n- Memory from Room A"
        )
        prompt = builder.build(room, [], [], [], cross_session_context=mock_ctx)
        assert "Cross-Session Context" in prompt.system
        assert "Memory from Room A" in prompt.system

    def test_cross_session_skipped_when_empty(self, builder):
        """Cross-session section omitted when total_injected is 0."""
        room = make_room()
        mock_ctx = MagicMock()
        mock_ctx.total_injected = 0
        prompt = builder.build(room, [], [], [], cross_session_context=mock_ctx)
        assert "Cross-Session" not in prompt.system

    def test_cross_session_skipped_when_none(self, builder):
        """Cross-session section omitted when context is None."""
        room = make_room()
        prompt = builder.build(room, [], [], [], cross_session_context=None)
        assert "Cross-Session" not in prompt.system


# ── User modifiers / participant preferences ──


class TestUserModifiers:
    def test_aggression_level_blended(self, builder):
        """Average aggression level from all users appears in prompt."""
        room = make_room()
        users = [
            make_user("Alice", aggression_level=0.8),
            make_user("Bob", aggression_level=0.2),
        ]
        prompt = builder.build(room, users, [], [])
        # Average = 0.5
        assert "0.5" in prompt.system
        assert "Aggression level" in prompt.system

    def test_metaphysics_tolerance_blended(self, builder):
        """Average metaphysics tolerance from all users appears in prompt."""
        room = make_room()
        users = [
            make_user("Alice", metaphysics_tolerance=1.0),
            make_user("Bob", metaphysics_tolerance=0.0),
        ]
        prompt = builder.build(room, users, [], [])
        assert "0.5" in prompt.system
        assert "Metaphysics tolerance" in prompt.system

    def test_style_modifiers_included(self, builder):
        """User style_modifier values are joined in prompt."""
        room = make_room()
        users = [
            make_user("Alice", style_modifier="Be Socratic"),
            make_user("Bob", style_modifier="Use analogies"),
        ]
        prompt = builder.build(room, users, [], [])
        assert "Be Socratic" in prompt.system
        assert "Use analogies" in prompt.system
        assert "Style notes" in prompt.system

    def test_custom_instructions_included(self, builder):
        """User custom_instructions appear in prompt."""
        room = make_room()
        users = [make_user("Alice", custom_instructions="Always cite sources")]
        prompt = builder.build(room, users, [], [])
        assert "Always cite sources" in prompt.system
        assert "Custom instructions" in prompt.system

    def test_no_participant_section_when_no_users(self, builder):
        """No Participant Preferences section when users list is empty."""
        room = make_room()
        prompt = builder.build(room, [], [], [])
        assert "Participant Preferences" not in prompt.system

    def test_style_modifier_none_excluded(self, builder):
        """Users with no style_modifier don't contribute to style notes."""
        room = make_room()
        users = [
            make_user("Alice", style_modifier=None),
            make_user("Bob", style_modifier="Be concise"),
        ]
        prompt = builder.build(room, users, [], [])
        assert "Be concise" in prompt.system


# ── Message formatting ──


class TestMessageFormatting:
    def test_human_messages_have_user_role(self, builder):
        """Human messages become role='user' with speaker name prefix."""
        room = make_room()
        alice = make_user("Alice", user_id=USER_A_ID)
        msgs = [make_message("Hello world", user_id=USER_A_ID)]
        prompt = builder.build(room, [alice], msgs, [])
        assert len(prompt.messages) == 1
        assert prompt.messages[0]["role"] == "user"
        assert "[Alice]" in prompt.messages[0]["content"]
        assert "Hello world" in prompt.messages[0]["content"]

    def test_llm_messages_have_assistant_role(self, builder):
        """LLM messages become role='assistant'."""
        room = make_room()
        msgs = [
            make_message(
                "I disagree",
                speaker_type=SpeakerType.LLM_PRIMARY,
            )
        ]
        prompt = builder.build(room, [], msgs, [])
        assert prompt.messages[0]["role"] == "assistant"

    def test_provoker_messages_have_assistant_role(self, builder):
        """Provoker messages also become role='assistant'."""
        room = make_room()
        msgs = [
            make_message(
                "But what if...",
                speaker_type=SpeakerType.LLM_PROVOKER,
            )
        ]
        prompt = builder.build(room, [], msgs, [])
        assert prompt.messages[0]["role"] == "assistant"

    def test_system_messages_have_user_role(self, builder):
        """System speaker type messages become role='user' with SYSTEM prefix."""
        room = make_room()
        msgs = [
            make_message(
                "Room settings changed",
                speaker_type=SpeakerType.SYSTEM,
            )
        ]
        prompt = builder.build(room, [], msgs, [])
        assert prompt.messages[0]["role"] == "user"
        assert "[SYSTEM]" in prompt.messages[0]["content"]

    def test_deleted_messages_excluded(self, builder):
        """Deleted messages are not included in formatted output."""
        room = make_room()
        msgs = [
            make_message("visible"),
            make_message("deleted", is_deleted=True),
        ]
        prompt = builder.build(room, [], msgs, [])
        assert len(prompt.messages) == 1
        assert "visible" in prompt.messages[0]["content"]

    def test_message_type_prefixes(self, builder):
        """Structured message types get prefixes."""
        room = make_room()
        claim = make_message("X is true", message_type=MessageType.CLAIM)
        question = make_message("Is X true", message_type=MessageType.QUESTION)
        definition = make_message("X means Y", message_type=MessageType.DEFINITION)
        counter = make_message("But Z", message_type=MessageType.COUNTEREXAMPLE)
        memory_w = make_message("remember this", message_type=MessageType.MEMORY_WRITE)
        text = make_message("just text", message_type=MessageType.TEXT)

        prompt = builder.build(room, [], [claim, question, definition, counter, memory_w, text], [])
        contents = [m["content"] for m in prompt.messages]

        assert any("[CLAIM]" in c for c in contents)
        assert any("[QUESTION]" in c for c in contents)
        assert any("[DEFINITION]" in c for c in contents)
        assert any("[COUNTEREXAMPLE]" in c for c in contents)
        assert any("[MEMORY]" in c for c in contents)
        # TEXT type should have no structured prefix (but has [Unknown] speaker prefix)
        text_content = contents[-1]
        assert "[CLAIM]" not in text_content
        assert "[QUESTION]" not in text_content

    def test_unknown_user_fallback(self, builder):
        """Human message from unknown user_id shows 'Unknown'."""
        room = make_room()
        msg = make_message("hello", user_id=uuid4())  # not in users list
        prompt = builder.build(room, [], [msg], [])
        assert "[Unknown]" in prompt.messages[0]["content"]
