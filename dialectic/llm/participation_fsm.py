# llm/participation_fsm.py — the LLM participant's presence state machine

"""
ARCHITECTURE: Table-driven FSM tracking what the LLM's participation *means*
right now — is it in the conversation, waiting on a human, sitting on an
unanswered question, being ignored, or has the room gone dormant. Mirrors
cc-sidecar/cc_sidecar/reducer (states.py / machine.py): every legal
transition is an explicit table entry, unknown (state, event) pairs are
logged and leave the machine unchanged, and timer-driven transitions bypass
the table entirely with a downgraded StateSource.

WHY: The silence sweep needs to know the difference between "the LLM spoke
and the humans are thinking" (do nothing) and "a question has been on the
floor for ten minutes" (exactly one follow-up). That distinction is a state,
not a timer — timers get restarted, states persist.

STATES:
  engaged          conversation flowing, nothing owed either way
  awaiting_human   the LLM (or its follow-up) spoke last; silence is expected
  question_pending a human question is on the floor unanswered
  ignored          the LLM's last contribution went unacknowledged and the
                   humans moved on without it
  dormant          no participation events for a long time (timer-inferred)

EVENTS (the full vocabulary — orchestrator decisions + message arrivals):
  HumanMessage     a human message arrived (not a question)
  HumanQuestion    a human message arrived that the heuristics engine's
                   question signal (llm/heuristics.py _is_question) flags
  LlmSpoke         the orchestrator decided to speak
  LlmSilence       the orchestrator declined while its last message was
                   still unacknowledged (only emitted from awaiting_human)
  QuestionAnswered the LLM spoke while a question was pending
  FollowUpSent     the silence sweep sent its one follow-up

CONFIDENCE (StateSource, mirrors cc-sidecar models.py:38-42):
  OBSERVED    set by real table transitions off real events
  RECONCILED  one downgrade step — the machine was rebuilt after context
              truncation and can no longer vouch for what it "remembers"
  INFERRED    timer-driven transitions (mark_dormant) and the second
              truncation downgrade — a guess, not an observation
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ParticipationState(str, Enum):
    """Finite state set for the LLM's participation in one room."""
    ENGAGED = "engaged"
    AWAITING_HUMAN = "awaiting_human"
    QUESTION_PENDING = "question_pending"
    IGNORED = "ignored"
    DORMANT = "dormant"


class StateSource(str, Enum):
    """Source-of-truth tier for a derived state value."""
    OBSERVED = "observed"
    RECONCILED = "reconciled"
    INFERRED = "inferred"


# Event vocabulary (string constants so call sites and the table share one
# spelling, same as cc-sidecar's hook event names).
EVENT_HUMAN_MESSAGE = "HumanMessage"
EVENT_HUMAN_QUESTION = "HumanQuestion"
EVENT_LLM_SPOKE = "LlmSpoke"
EVENT_LLM_SILENCE = "LlmSilence"
EVENT_QUESTION_ANSWERED = "QuestionAnswered"
EVENT_FOLLOW_UP_SENT = "FollowUpSent"

_S = ParticipationState

# ============================================================
# Transition table: (current_state, event_name) → new_state
# ============================================================
# WHY: Every entry documents one legal state change. If a (state, event)
# pair is not here, apply() logs and leaves the machine unchanged.
TRANSITIONS: dict[tuple[ParticipationState, str], ParticipationState] = {
    # ── From ENGAGED ───────────────────────────────────────
    (_S.ENGAGED, EVENT_HUMAN_MESSAGE):      _S.ENGAGED,
    (_S.ENGAGED, EVENT_HUMAN_QUESTION):     _S.QUESTION_PENDING,
    (_S.ENGAGED, EVENT_LLM_SPOKE):          _S.AWAITING_HUMAN,
    (_S.ENGAGED, EVENT_LLM_SILENCE):        _S.ENGAGED,

    # ── From AWAITING_HUMAN ────────────────────────────────
    (_S.AWAITING_HUMAN, EVENT_HUMAN_MESSAGE):   _S.ENGAGED,
    (_S.AWAITING_HUMAN, EVENT_HUMAN_QUESTION):  _S.QUESTION_PENDING,
    (_S.AWAITING_HUMAN, EVENT_LLM_SPOKE):       _S.AWAITING_HUMAN,
    # WHY ignored lives here: the LLM spoke, a new human message arrived,
    # and the orchestrator declined again — the humans are carrying on
    # without acknowledging the LLM's last turn.
    (_S.AWAITING_HUMAN, EVENT_LLM_SILENCE):     _S.IGNORED,

    # ── From QUESTION_PENDING ──────────────────────────────
    # Chatter that isn't an answer leaves the question open.
    (_S.QUESTION_PENDING, EVENT_HUMAN_MESSAGE):     _S.QUESTION_PENDING,
    (_S.QUESTION_PENDING, EVENT_HUMAN_QUESTION):    _S.QUESTION_PENDING,
    (_S.QUESTION_PENDING, EVENT_LLM_SPOKE):         _S.AWAITING_HUMAN,
    (_S.QUESTION_PENDING, EVENT_LLM_SILENCE):       _S.QUESTION_PENDING,
    (_S.QUESTION_PENDING, EVENT_QUESTION_ANSWERED): _S.AWAITING_HUMAN,
    # The sweep's one follow-up. After this the state has left
    # question_pending — that exit IS the "once per quiet event" cap.
    (_S.QUESTION_PENDING, EVENT_FOLLOW_UP_SENT):    _S.AWAITING_HUMAN,

    # ── From IGNORED ───────────────────────────────────────
    (_S.IGNORED, EVENT_HUMAN_MESSAGE):      _S.IGNORED,
    (_S.IGNORED, EVENT_HUMAN_QUESTION):     _S.QUESTION_PENDING,
    (_S.IGNORED, EVENT_LLM_SPOKE):          _S.AWAITING_HUMAN,
    (_S.IGNORED, EVENT_LLM_SILENCE):        _S.IGNORED,
    (_S.IGNORED, EVENT_FOLLOW_UP_SENT):     _S.AWAITING_HUMAN,

    # ── From DORMANT (any real activity wakes the room) ────
    (_S.DORMANT, EVENT_HUMAN_MESSAGE):      _S.ENGAGED,
    (_S.DORMANT, EVENT_HUMAN_QUESTION):     _S.QUESTION_PENDING,
    (_S.DORMANT, EVENT_LLM_SPOKE):          _S.AWAITING_HUMAN,
    (_S.DORMANT, EVENT_LLM_SILENCE):        _S.DORMANT,
}


def decision_event(
    *,
    spoke: bool,
    is_question: bool,
    current_state: ParticipationState,
) -> str:
    """Map one on_message turn (message arrival + orchestrator decision)
    to the single FSM event it constitutes.

    WHY one event per turn: the arrival and the decision are causally one
    moment — the orchestrator decides *because* the message arrived — so the
    machine consumes them together. QuestionAnswered vs LlmSpoke and
    LlmSilence vs HumanMessage are disambiguated by the state the machine
    was in when the turn started.
    """
    if spoke:
        if current_state == ParticipationState.QUESTION_PENDING:
            return EVENT_QUESTION_ANSWERED
        return EVENT_LLM_SPOKE
    if is_question:
        return EVENT_HUMAN_QUESTION
    if current_state == ParticipationState.AWAITING_HUMAN:
        return EVENT_LLM_SILENCE
    return EVENT_HUMAN_MESSAGE


class ParticipationFSM:
    """
    Per-room participation state machine.

    ARCHITECTURE: One machine per room, hydrated from llm_participation_state
    (fsm_state / state_entered_at / state_source columns) and persisted back
    through the self-model's participation-state upsert. Stateless between
    turns by design — the DB row is the memory.
    """

    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.state = ParticipationState.ENGAGED
        self.state_source = StateSource.OBSERVED
        self.state_entered_at = now
        self.last_event_at = now
        # Compaction-flag pattern (machine.py:88-105): truncation is a flag
        # with a confidence downgrade, not a state.
        self.context_truncated = False

    def apply(self, event_name: str) -> Optional[ParticipationState]:
        """
        Apply an event; return the new state, or None if no transition.

        Unknown (state, event) pairs are logged and leave the machine
        unchanged — future event sources must not crash the room.
        """
        now = datetime.now(timezone.utc)
        self.last_event_at = now

        new_state = TRANSITIONS.get((self.state, event_name))
        if new_state is None:
            logger.debug(
                "No transition for (%s, %s) in participation FSM",
                self.state.value, event_name,
            )
            return None

        if new_state != self.state:
            self.state = new_state
            self.state_entered_at = now
        # A real event re-grounds the machine: observed confidence, and the
        # truncation flag clears because fresh events are flowing again.
        self.state_source = StateSource.OBSERVED
        self.context_truncated = False
        return new_state

    def mark_dormant(self) -> None:
        """
        Timer-driven transition to DORMANT (the sweep calls this).

        WHY: Inferred, not observed — no event said "the room went quiet",
        a clock did. Bypasses the table on purpose (mirror mark_orphaned).
        """
        self.state = ParticipationState.DORMANT
        self.state_source = StateSource.INFERRED
        self.state_entered_at = datetime.now(timezone.utc)

    def note_truncation(self) -> None:
        """
        Post-truncation confidence downgrade (compaction-flag pattern).

        Fed by AssembledContext.truncated: after the prompt dropped messages,
        the machine's picture of the conversation is rebuilt from a partial
        record, so its state is one tier less trustworthy. State itself does
        not change. Steps OBSERVED → RECONCILED → INFERRED.
        """
        self.context_truncated = True
        if self.state_source == StateSource.OBSERVED:
            self.state_source = StateSource.RECONCILED
        elif self.state_source == StateSource.RECONCILED:
            self.state_source = StateSource.INFERRED

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize for persistence (llm_participation_state columns)."""
        return {
            "state": self.state.value,
            "state_source": self.state_source.value,
            "state_entered_at": self.state_entered_at.isoformat(),
            "last_event_at": self.last_event_at.isoformat(),
            "context_truncated": self.context_truncated,
        }

    @classmethod
    def from_snapshot(cls, snap: dict[str, Any]) -> "ParticipationFSM":
        """Rehydrate from a to_snapshot() dict (or the matching DB columns)."""
        fsm = cls()
        fsm.state = ParticipationState(snap["state"])
        source = snap.get("state_source")
        if source:
            fsm.state_source = StateSource(source)
        for field_name in ("state_entered_at", "last_event_at"):
            raw = snap.get(field_name)
            if raw is None:
                continue
            if isinstance(raw, datetime):
                value = raw
            else:
                value = datetime.fromisoformat(str(raw))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            setattr(fsm, field_name, value)
        fsm.context_truncated = bool(snap.get("context_truncated", False))
        return fsm
