"""Tests for llm/heuristics.py — InterjectionEngine.decide()."""

import pytest

from llm.heuristics import InterjectionEngine, InterjectionDecision
from models import SpeakerType, MessageType
from tests.conftest import make_message, USER_A_ID, USER_B_ID


@pytest.fixture
def engine():
    return InterjectionEngine(turn_threshold=4, semantic_novelty_threshold=0.7)


# ── Explicit mention trigger ──


class TestExplicitMention:
    def test_mention_returns_should_interject(self, engine):
        """When mentioned=True the LLM must always interject."""
        msgs = [make_message("hey")]
        decision = engine.decide(msgs, mentioned=True)
        assert decision.should_interject is True

    def test_mention_confidence_is_one(self, engine):
        """Explicit mention gives maximum confidence."""
        msgs = [make_message("hey")]
        decision = engine.decide(msgs, mentioned=True)
        assert decision.confidence == 1.0

    def test_mention_never_uses_provoker(self, engine):
        """Explicit mention always uses primary mode, never provoker."""
        msgs = [make_message("hey")]
        decision = engine.decide(msgs, mentioned=True)
        assert decision.use_provoker is False

    def test_mention_reason(self, engine):
        """Reason should be 'explicit_mention'."""
        msgs = [make_message("hey")]
        decision = engine.decide(msgs, mentioned=True)
        assert decision.reason == "explicit_mention"

    def test_mention_overrides_other_triggers(self, engine):
        """Mention takes priority even when other triggers would fire."""
        # Enough turns to trigger turn_threshold AND a question
        msgs = [make_message("why?", sequence=i) for i in range(10)]
        decision = engine.decide(msgs, mentioned=True, semantic_novelty=0.99)
        assert decision.reason == "explicit_mention"
        assert decision.use_provoker is False


# ── Turn threshold trigger ──


class TestTurnThreshold:
    def test_threshold_exact(self, engine):
        """Exactly turn_threshold human turns should trigger."""
        msgs = [make_message(f"msg {i}", sequence=i) for i in range(4)]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.confidence == 0.8

    def test_threshold_exceeded(self, engine):
        """More than turn_threshold human turns should trigger."""
        msgs = [make_message(f"msg {i}", sequence=i) for i in range(7)]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert "turn_threshold_exceeded" in decision.reason

    def test_below_threshold_no_trigger(self, engine):
        """Fewer than turn_threshold human turns should NOT trigger (alone)."""
        msgs = [make_message("msg", sequence=i) for i in range(3)]
        decision = engine.decide(msgs)
        # Should not trigger via turn threshold (might still trigger via other)
        assert decision.reason != "turn_threshold_exceeded"

    def test_llm_message_resets_count(self, engine):
        """An LLM message in the middle resets the human-turn counter."""
        msgs = [
            make_message("human 1", sequence=1),
            make_message("human 2", sequence=2),
            make_message(
                "llm response",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=3,
            ),
            make_message("human 3", sequence=4),
            make_message("human 4", sequence=5),
        ]
        decision = engine.decide(msgs)
        # Only 2 human turns since last LLM message -> below threshold
        assert decision.reason != "turn_threshold_exceeded"

    def test_provoker_message_also_resets(self, engine):
        """A provoker message also resets the human-turn counter."""
        msgs = [
            make_message("human 1", sequence=1),
            make_message("human 2", sequence=2),
            make_message(
                "provoker interjection",
                speaker_type=SpeakerType.LLM_PROVOKER,
                sequence=3,
            ),
            make_message("human 3", sequence=4),
        ]
        decision = engine.decide(msgs)
        assert decision.reason != "turn_threshold_exceeded"

    def test_custom_threshold(self):
        """Custom turn_threshold is respected."""
        engine = InterjectionEngine(turn_threshold=2)
        msgs = [make_message("a", sequence=1), make_message("b", sequence=2)]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert "turn_threshold_exceeded" in decision.reason

    def test_turn_threshold_no_provoker(self, engine):
        """Turn threshold always uses primary mode."""
        msgs = [make_message(f"msg {i}", sequence=i) for i in range(5)]
        decision = engine.decide(msgs)
        assert decision.use_provoker is False


# ── Question detection trigger ──


class TestQuestionDetection:
    def test_trailing_question_mark(self, engine):
        """Message ending with '?' triggers question detection."""
        msgs = [make_message("Is this real?")]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "question_detected"
        assert decision.confidence == 0.7

    def test_what_prefix(self, engine):
        """Question starting with 'what' triggers."""
        msgs = [make_message("what is consciousness")]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "question_detected"

    def test_why_prefix(self, engine):
        """Question starting with 'why' triggers."""
        msgs = [make_message("why does this matter")]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "question_detected"

    def test_how_prefix(self, engine):
        """Question starting with 'how' triggers."""
        msgs = [make_message("how do we know")]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "question_detected"

    def test_thoughts_question(self, engine):
        """'thoughts?' pattern triggers question detection."""
        msgs = [make_message("any thoughts?")]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "question_detected"

    def test_does_prefix(self, engine):
        """Question starting with 'does' triggers."""
        msgs = [make_message("does that follow")]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "question_detected"

    def test_non_question_no_trigger(self, engine):
        """Plain statement should not trigger question detection."""
        msgs = [make_message("I agree with the premise")]
        decision = engine.decide(msgs)
        assert decision.reason != "question_detected"

    def test_question_uses_most_recent_human(self, engine):
        """Only the most recent human message is checked for questions."""
        msgs = [
            make_message("what is truth", sequence=1),  # question, but older
            make_message(
                "I respond",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=2,
            ),
            make_message("just a statement", sequence=3),  # most recent human
        ]
        decision = engine.decide(msgs)
        assert decision.reason != "question_detected"

    def test_question_no_provoker(self, engine):
        """Question detection uses primary mode."""
        msgs = [make_message("what do you think?")]
        decision = engine.decide(msgs)
        assert decision.use_provoker is False


# ── Information gap trigger ──


class TestInformationGap:
    def test_information_gap_triggers(self, engine):
        """unsurfaced_memory_count >= 2 triggers information_gap."""
        msgs = [make_message("tell me about epistemology")]
        decision = engine.decide(msgs, unsurfaced_memory_count=3)
        assert decision.should_interject is True
        assert decision.reason == "information_gap"
        assert decision.confidence == 0.65
        assert decision.use_provoker is False

    def test_information_gap_exact_threshold(self, engine):
        """unsurfaced_memory_count == 2 triggers (boundary)."""
        msgs = [make_message("let's discuss")]
        decision = engine.decide(msgs, unsurfaced_memory_count=2)
        assert decision.should_interject is True
        assert decision.reason == "information_gap"

    def test_information_gap_below_threshold(self, engine):
        """unsurfaced_memory_count < 2 does not trigger."""
        msgs = [make_message("I agree")]
        decision = engine.decide(msgs, unsurfaced_memory_count=1)
        assert decision.reason != "information_gap"

    def test_information_gap_zero(self, engine):
        """unsurfaced_memory_count == 0 does not trigger."""
        msgs = [make_message("ok")]
        decision = engine.decide(msgs, unsurfaced_memory_count=0)
        assert decision.reason != "information_gap"

    def test_information_gap_none_skipped(self, engine):
        """When unsurfaced_memory_count is None, check is skipped."""
        msgs = [make_message("msg")]
        decision = engine.decide(msgs, unsurfaced_memory_count=None)
        assert decision.reason != "information_gap"

    def test_information_gap_no_provoker(self, engine):
        """Information gap uses primary mode, not provoker."""
        msgs = [make_message("topic")]
        decision = engine.decide(msgs, unsurfaced_memory_count=5)
        assert decision.use_provoker is False


# ── Semantic novelty spike trigger ──


class TestSemanticNovelty:
    def test_novelty_above_threshold(self, engine):
        """Novelty >= 0.7 triggers interjection with provoker."""
        msgs = [make_message("something novel")]
        decision = engine.decide(msgs, semantic_novelty=0.85)
        assert decision.should_interject is True
        assert "semantic_novelty_spike" in decision.reason
        assert decision.use_provoker is True

    def test_novelty_at_threshold(self, engine):
        """Novelty exactly at threshold should trigger."""
        msgs = [make_message("interesting")]
        decision = engine.decide(msgs, semantic_novelty=0.7)
        assert decision.should_interject is True
        assert "semantic_novelty_spike" in decision.reason

    def test_novelty_below_threshold(self, engine):
        """Novelty below threshold should NOT trigger via novelty."""
        msgs = [make_message("boring")]
        decision = engine.decide(msgs, semantic_novelty=0.3)
        assert decision.reason != "semantic_novelty_spike"

    def test_novelty_confidence_equals_score(self, engine):
        """Confidence should equal the semantic_novelty value."""
        msgs = [make_message("novel insight")]
        decision = engine.decide(msgs, semantic_novelty=0.92)
        assert decision.confidence == 0.92

    def test_novelty_none_skipped(self, engine):
        """When semantic_novelty is None, novelty check is skipped."""
        msgs = [make_message("msg")]
        decision = engine.decide(msgs, semantic_novelty=None)
        assert "semantic_novelty_spike" not in decision.reason

    def test_custom_novelty_threshold(self):
        """Custom semantic_novelty_threshold is respected."""
        engine = InterjectionEngine(semantic_novelty_threshold=0.5)
        msgs = [make_message("different")]
        decision = engine.decide(msgs, semantic_novelty=0.55)
        assert decision.should_interject is True
        assert decision.use_provoker is True


# ── Stagnation detection trigger ──


class TestStagnation:
    def test_stagnation_detected(self):
        """6+ short TEXT-only messages triggers stagnation (with high turn threshold)."""
        # Use a high turn threshold so turn_threshold doesn't fire first
        engine = InterjectionEngine(turn_threshold=100, semantic_novelty_threshold=0.99)
        msgs = [
            make_message("ok", sequence=i, message_type=MessageType.TEXT)
            for i in range(6)
        ]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "stagnation_detected"
        assert decision.use_provoker is True
        assert decision.confidence == 0.6

    def test_stagnation_needs_six_messages(self, engine):
        """Fewer than 6 messages should not trigger stagnation."""
        msgs = [
            make_message("ok", sequence=i, message_type=MessageType.TEXT)
            for i in range(5)
        ]
        decision = engine.decide(msgs)
        assert decision.reason != "stagnation_detected"

    def test_long_messages_no_stagnation(self, engine):
        """Messages averaging >= 100 chars should not trigger stagnation."""
        long_text = "x" * 150
        msgs = [
            make_message(long_text, sequence=i, message_type=MessageType.TEXT)
            for i in range(6)
        ]
        decision = engine.decide(msgs)
        assert decision.reason != "stagnation_detected"

    def test_mixed_types_no_stagnation(self, engine):
        """If message types are not all TEXT, stagnation is not detected."""
        msgs = [
            make_message("ok", sequence=0, message_type=MessageType.TEXT),
            make_message("ok", sequence=1, message_type=MessageType.TEXT),
            make_message("ok", sequence=2, message_type=MessageType.TEXT),
            make_message("ok", sequence=3, message_type=MessageType.TEXT),
            make_message("ok", sequence=4, message_type=MessageType.TEXT),
            make_message("claim!", sequence=5, message_type=MessageType.CLAIM),
        ]
        decision = engine.decide(msgs)
        assert decision.reason != "stagnation_detected"

    def test_stagnation_uses_last_six(self):
        """Stagnation only looks at the last 6 messages."""
        # Use a high turn threshold so turn_threshold doesn't fire first
        engine = InterjectionEngine(turn_threshold=100, semantic_novelty_threshold=0.99)
        old_msgs = [
            make_message("x" * 200, sequence=i, message_type=MessageType.TEXT)
            for i in range(10)
        ]
        stale_msgs = [
            make_message("ok", sequence=10 + i, message_type=MessageType.TEXT)
            for i in range(6)
        ]
        decision = engine.decide(old_msgs + stale_msgs)
        assert decision.reason == "stagnation_detected"


# ── Speaker balance redirect trigger ──


class TestSpeakerBalance:
    def test_balance_redirect_triggers(self, engine):
        """One speaker with 70%+ of messages triggers balance_redirect."""
        msgs = [make_message("I agree")]
        balance = {str(USER_A_ID): 8, str(USER_B_ID): 2}
        decision = engine.decide(msgs, speaker_balance=balance)
        assert decision.should_interject is True
        assert decision.reason == "balance_redirect"
        assert decision.confidence == 0.55
        assert decision.use_provoker is False

    def test_balance_redirect_exact_threshold(self, engine):
        """Exactly 70% triggers (7 out of 10)."""
        msgs = [make_message("msg")]
        balance = {str(USER_A_ID): 7, str(USER_B_ID): 3}
        decision = engine.decide(msgs, speaker_balance=balance)
        assert decision.should_interject is True
        assert decision.reason == "balance_redirect"

    def test_balance_redirect_below_threshold(self, engine):
        """Below 70% does not trigger."""
        msgs = [make_message("msg")]
        balance = {str(USER_A_ID): 6, str(USER_B_ID): 4}
        decision = engine.decide(msgs, speaker_balance=balance)
        assert decision.reason != "balance_redirect"

    def test_balance_single_speaker_no_trigger(self, engine):
        """Only 1 human present should NOT trigger balance redirect."""
        msgs = [make_message("msg")]
        balance = {str(USER_A_ID): 10}
        decision = engine.decide(msgs, speaker_balance=balance)
        assert decision.reason != "balance_redirect"

    def test_balance_none_skipped(self, engine):
        """When speaker_balance is None, check is skipped."""
        msgs = [make_message("msg")]
        decision = engine.decide(msgs, speaker_balance=None)
        assert decision.reason != "balance_redirect"

    def test_balance_empty_dict_no_trigger(self, engine):
        """Empty speaker_balance dict does not trigger."""
        msgs = [make_message("msg")]
        decision = engine.decide(msgs, speaker_balance={})
        assert decision.reason != "balance_redirect"


# ── Silence logging (considered_reasons) ──


class TestSilenceLogging:
    def test_no_trigger_populates_considered_reasons(self, engine):
        """When no trigger fires, considered_reasons lists all evaluated heuristics."""
        msgs = [
            make_message("I think so too", sequence=1),
            make_message(
                "agreed",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=2,
            ),
            make_message("Let me elaborate on that point", sequence=3),
        ]
        decision = engine.decide(msgs)
        assert decision.should_interject is False
        assert decision.reason == "no_trigger"
        assert len(decision.considered_reasons) > 0
        assert "turn_threshold" in decision.considered_reasons
        assert "question_detection" in decision.considered_reasons
        assert "information_gap" in decision.considered_reasons
        assert "semantic_novelty" in decision.considered_reasons
        assert "stagnation" in decision.considered_reasons
        assert "speaker_balance" in decision.considered_reasons

    def test_considered_reasons_empty_on_first_trigger(self, engine):
        """When mention fires immediately, no heuristics were skipped."""
        msgs = [make_message("hey")]
        decision = engine.decide(msgs, mentioned=True)
        assert decision.considered_reasons == []

    def test_considered_reasons_partial_on_mid_trigger(self, engine):
        """When question fires, only heuristics before it are in considered."""
        msgs = [make_message("what is truth?")]
        decision = engine.decide(msgs)
        assert decision.reason == "question_detected"
        # Turn threshold was evaluated but didn't fire
        assert "turn_threshold" in decision.considered_reasons
        # Heuristics after question (info gap, novelty, etc.) were NOT evaluated
        assert "information_gap" not in decision.considered_reasons

    def test_considered_reasons_is_list(self, engine):
        """considered_reasons is always a list."""
        msgs = [make_message("test")]
        decision = engine.decide(msgs)
        assert isinstance(decision.considered_reasons, list)

    def test_silence_with_all_new_params_none(self, engine):
        """Backward compat: all new params as None still returns proper silence."""
        msgs = [
            make_message("I agree", sequence=1),
            make_message(
                "ok",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=2,
            ),
            make_message("sure", sequence=3),
        ]
        decision = engine.decide(
            msgs,
            unsurfaced_memory_count=None,
            speaker_balance=None,
        )
        assert decision.should_interject is False
        assert "information_gap" in decision.considered_reasons
        assert "speaker_balance" in decision.considered_reasons


# ── No trigger / fallthrough ──


class TestNoTrigger:
    def test_no_trigger_basic(self, engine):
        """A benign conversation with no triggers returns no_trigger."""
        msgs = [
            make_message("I think so too", sequence=1),
            make_message(
                "agreed",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=2,
            ),
            make_message("Let me elaborate on that point", sequence=3),
        ]
        decision = engine.decide(msgs)
        assert decision.should_interject is False
        assert decision.reason == "no_trigger"
        assert decision.confidence == 0.0
        assert decision.use_provoker is False


# ── Edge cases ──


class TestEdgeCases:
    def test_empty_messages(self, engine):
        """Empty message list should not crash and should return no_trigger."""
        decision = engine.decide([])
        assert decision.should_interject is False
        assert decision.reason == "no_trigger"

    def test_single_message(self, engine):
        """Single non-triggering message returns no_trigger."""
        msgs = [make_message("hello")]
        decision = engine.decide(msgs)
        # 1 human turn < 4 threshold, no question, no stagnation
        assert decision.should_interject is False

    def test_single_question_message(self, engine):
        """Single question message triggers question_detected."""
        msgs = [make_message("what is truth?")]
        decision = engine.decide(msgs)
        assert decision.should_interject is True
        assert decision.reason == "question_detected"

    def test_priority_order_mention_over_turns(self, engine):
        """Mention takes priority over turn threshold."""
        msgs = [make_message(f"msg {i}", sequence=i) for i in range(10)]
        decision = engine.decide(msgs, mentioned=True)
        assert decision.reason == "explicit_mention"

    def test_priority_order_turns_over_question(self, engine):
        """Turn threshold fires before question detection."""
        msgs = [make_message("why?", sequence=i) for i in range(5)]
        decision = engine.decide(msgs)
        # 5 human turns >= 4 threshold -> turn threshold fires first
        assert "turn_threshold_exceeded" in decision.reason

    def test_priority_order_question_over_novelty(self, engine):
        """Question fires before semantic novelty."""
        # Need < threshold human turns so turn threshold doesn't fire
        msgs = [
            make_message(
                "llm msg",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=1,
            ),
            make_message("what is this?", sequence=2),
        ]
        decision = engine.decide(msgs, semantic_novelty=0.9)
        assert decision.reason == "question_detected"

    def test_priority_order_question_over_info_gap(self, engine):
        """Question fires before information gap."""
        msgs = [
            make_message(
                "llm msg",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=1,
            ),
            make_message("what do you think?", sequence=2),
        ]
        decision = engine.decide(msgs, unsurfaced_memory_count=5)
        assert decision.reason == "question_detected"

    def test_priority_order_info_gap_over_novelty(self, engine):
        """Information gap fires before semantic novelty."""
        msgs = [
            make_message(
                "llm msg",
                speaker_type=SpeakerType.LLM_PRIMARY,
                sequence=1,
            ),
            make_message("I think this is fine", sequence=2),
        ]
        decision = engine.decide(
            msgs, unsurfaced_memory_count=3, semantic_novelty=0.9
        )
        assert decision.reason == "information_gap"

    def test_priority_order_stagnation_over_balance(self):
        """Stagnation fires before speaker balance."""
        engine = InterjectionEngine(turn_threshold=100, semantic_novelty_threshold=0.99)
        msgs = [
            make_message("ok", sequence=i, message_type=MessageType.TEXT)
            for i in range(6)
        ]
        balance = {str(USER_A_ID): 8, str(USER_B_ID): 2}
        decision = engine.decide(msgs, speaker_balance=balance)
        assert decision.reason == "stagnation_detected"

    def test_decision_is_dataclass(self, engine):
        """InterjectionDecision should be a proper dataclass."""
        msgs = [make_message("test")]
        decision = engine.decide(msgs)
        assert isinstance(decision, InterjectionDecision)
        assert hasattr(decision, "should_interject")
        assert hasattr(decision, "reason")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "use_provoker")
        assert hasattr(decision, "considered_reasons")


# ── Backward compatibility ──


class TestBackwardCompatibility:
    def test_old_call_signature_works(self, engine):
        """Calling decide() without new params still works."""
        msgs = [make_message("hello")]
        decision = engine.decide(msgs)
        assert isinstance(decision, InterjectionDecision)

    def test_old_call_with_mentioned_works(self, engine):
        """Old-style call with mentioned=True still works."""
        msgs = [make_message("hey")]
        decision = engine.decide(msgs, mentioned=True)
        assert decision.should_interject is True
        assert decision.reason == "explicit_mention"

    def test_old_call_with_novelty_works(self, engine):
        """Old-style call with semantic_novelty still works."""
        msgs = [make_message("novel")]
        decision = engine.decide(msgs, semantic_novelty=0.85)
        assert decision.should_interject is True
        assert "semantic_novelty_spike" in decision.reason

    def test_decision_has_considered_reasons_default(self, engine):
        """Even old-style decisions have considered_reasons field (defaulting to list)."""
        msgs = [make_message("hey")]
        decision = engine.decide(msgs, mentioned=True)
        assert hasattr(decision, "considered_reasons")
        assert isinstance(decision.considered_reasons, list)

    def test_protocol_decision_compatible(self):
        """InterjectionDecision created outside decide() (e.g. orchestrator protocol mode) still works."""
        decision = InterjectionDecision(
            should_interject=True,
            reason="protocol_active",
            confidence=1.0,
            use_provoker=False,
        )
        assert decision.considered_reasons == []
