# llm/heuristics.py — Interjection decision engine

from dataclasses import dataclass, field
from typing import Optional
import logging
import re

from models import Message, SpeakerType, MessageType

logger = logging.getLogger(__name__)


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
    considered_reasons: list[str] = field(default_factory=list)


class InterjectionEngine:
    """
    ARCHITECTURE: Rule-based + heuristic interjection triggers (Inner Thoughts 8-heuristic framework).
    WHY: LLM should feel like a participant, not a reactive tool.
    TRADEOFF: False positives (annoying) vs false negatives (silent).

    Heuristics evaluated in priority order:
      1. Explicit mention          (confidence 1.0)
      2. Turn threshold            (confidence 0.8)
      3. Question detection        (confidence 0.7)
      4. Information gap           (confidence 0.65)
      5. Semantic novelty spike    (confidence varies, provoker)
      6. Stagnation detection      (confidence 0.6, provoker)
      7. Speaker balance redirect  (confidence 0.55)
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
        turn_threshold: int = 4,
        unsurfaced_memory_count: Optional[int] = None,
        speaker_balance: Optional[dict[str, int]] = None,
    ) -> InterjectionDecision:
        """
        Analyze recent messages and decide whether LLM should interject.

        ARCHITECTURE: Cascading priority evaluation with silence logging.
        WHY: Each heuristic is checked in order; first match wins, but all
             evaluated-but-not-fired heuristics are logged in considered_reasons
             to enable analysis of when the LLM chose restraint.
        """
        considered_reasons: list[str] = []

        # 1. Explicit mention — highest priority, always fires
        if mentioned:
            return InterjectionDecision(
                should_interject=True,
                reason="explicit_mention",
                confidence=1.0,
                use_provoker=False,
                considered_reasons=considered_reasons,
            )

        # 2. Turn threshold — too many human turns without LLM response
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
                considered_reasons=considered_reasons,
            )
        else:
            considered_reasons.append("turn_threshold")

        # 3. Question detection — most recent human message asks a question
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
                considered_reasons=considered_reasons,
            )
        else:
            considered_reasons.append("question_detection")

        # 4. Information gap — LLM has relevant unsurfaced memories
        #    ARCHITECTURE: Detects when LLM knows something the humans haven't seen.
        #    WHY: Proactive knowledge sharing makes LLM a real participant.
        #    TRADEOFF: May surface tangential memories vs missing relevant context.
        if unsurfaced_memory_count is not None and unsurfaced_memory_count >= 2:
            return InterjectionDecision(
                should_interject=True,
                reason="information_gap",
                confidence=0.65,
                use_provoker=False,
                considered_reasons=considered_reasons,
            )
        else:
            considered_reasons.append("information_gap")

        # 5. Semantic novelty spike — conversation shifted to new territory
        if semantic_novelty is not None and semantic_novelty >= self.semantic_novelty_threshold:
            return InterjectionDecision(
                should_interject=True,
                reason=f"semantic_novelty_spike ({semantic_novelty:.2f})",
                confidence=semantic_novelty,
                use_provoker=True,
                considered_reasons=considered_reasons,
            )
        else:
            considered_reasons.append("semantic_novelty")

        # 6. Stagnation — short, repetitive messages indicate the conversation is stuck
        if self._detect_stagnation(messages):
            return InterjectionDecision(
                should_interject=True,
                reason="stagnation_detected",
                confidence=0.6,
                use_provoker=True,
                considered_reasons=considered_reasons,
            )
        else:
            considered_reasons.append("stagnation")

        # 7. Speaker balance redirect — one human dominates, engage the quieter one
        #    ARCHITECTURE: Tracks per-speaker message counts to detect imbalance.
        #    WHY: LLM can redirect to the quieter participant, promoting equity.
        #    TRADEOFF: Might interrupt a productive monologue vs enabling shy speakers.
        if speaker_balance is not None and self._detect_speaker_imbalance(speaker_balance):
            return InterjectionDecision(
                should_interject=True,
                reason="balance_redirect",
                confidence=0.55,
                use_provoker=False,
                considered_reasons=considered_reasons,
            )
        else:
            considered_reasons.append("speaker_balance")

        # No trigger fired — log considered silence
        logger.debug(
            "Considered silence: evaluated %d heuristics, none fired. reasons=%s",
            len(considered_reasons), considered_reasons,
        )

        return InterjectionDecision(
            should_interject=False,
            reason="no_trigger",
            confidence=0.0,
            use_provoker=False,
            considered_reasons=considered_reasons,
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

    def _detect_speaker_imbalance(self, speaker_balance: dict[str, int]) -> bool:
        """
        Detect if one speaker dominates the recent message window.

        Only triggers when multiple humans are present — a single human
        speaking is expected behaviour, not an imbalance.
        """
        if len(speaker_balance) < 2:
            return False

        total = sum(speaker_balance.values())
        if total == 0:
            return False

        for count in speaker_balance.values():
            if count / total >= 0.7:
                return True

        return False
