# llm/heuristics.py — Interjection decision engine

from dataclasses import dataclass
from typing import Optional
import re

from models import Message, SpeakerType, MessageType


@dataclass
class InterjectionDecision:
    """
    ARCHITECTURE: Explicit decision object for observability.
    WHY: Debug why LLM did/didn't interject.
    """
    should_interject: bool
    reason: str
    confidence: float
    use_provoker: bool


class InterjectionEngine:
    """
    ARCHITECTURE: Rule-based + heuristic interjection triggers.
    WHY: LLM should feel like a participant, not a reactive tool.
    TRADEOFF: False positives (annoying) vs false negatives (silent).
    """

    def __init__(
        self,
        turn_threshold: int = 4,
        semantic_novelty_threshold: float = 0.7,
    ):
        self.turn_threshold = turn_threshold
        self.semantic_novelty_threshold = semantic_novelty_threshold

        self.question_patterns = [
            r'\?$',
            r'^(what|how|why|when|where|who|which|is|are|do|does|can|could|would|should)\b',
            r'\b(thoughts|think|opinion|view|take)\s*\?',
        ]

    def decide(
        self,
        messages: list[Message],
        mentioned: bool = False,
        semantic_novelty: Optional[float] = None,
    ) -> InterjectionDecision:
        """Analyze recent messages and decide whether LLM should interject."""

        if mentioned:
            return InterjectionDecision(
                should_interject=True,
                reason="explicit_mention",
                confidence=1.0,
                use_provoker=False,
            )

        human_turns = 0
        for msg in reversed(messages):
            if msg.speaker_type in (SpeakerType.LLM_PRIMARY, SpeakerType.LLM_PROVOKER):
                break
            if msg.speaker_type == SpeakerType.HUMAN:
                human_turns += 1

        if human_turns >= self.turn_threshold:
            return InterjectionDecision(
                should_interject=True,
                reason=f"turn_threshold_exceeded ({human_turns} >= {self.turn_threshold})",
                confidence=0.8,
                use_provoker=False,
            )

        recent_human = next(
            (m for m in reversed(messages) if m.speaker_type == SpeakerType.HUMAN),
            None
        )
        if recent_human and self._is_question(recent_human.content):
            return InterjectionDecision(
                should_interject=True,
                reason="question_detected",
                confidence=0.7,
                use_provoker=False,
            )

        if semantic_novelty is not None and semantic_novelty >= self.semantic_novelty_threshold:
            return InterjectionDecision(
                should_interject=True,
                reason=f"semantic_novelty_spike ({semantic_novelty:.2f})",
                confidence=semantic_novelty,
                use_provoker=True,
            )

        if self._detect_stagnation(messages):
            return InterjectionDecision(
                should_interject=True,
                reason="stagnation_detected",
                confidence=0.6,
                use_provoker=True,
            )

        return InterjectionDecision(
            should_interject=False,
            reason="no_trigger",
            confidence=0.0,
            use_provoker=False,
        )

    def _is_question(self, text: str) -> bool:
        """Detect if text contains a question."""
        text_lower = text.lower().strip()
        for pattern in self.question_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _detect_stagnation(self, messages: list[Message], window: int = 6) -> bool:
        """Detect conversational stagnation."""
        recent = messages[-window:] if len(messages) >= window else messages

        if len(recent) < window:
            return False

        types = {m.message_type for m in recent}
        if types == {MessageType.TEXT}:
            avg_length = sum(len(m.content) for m in recent) / len(recent)
            if avg_length < 100:
                return True

        return False
