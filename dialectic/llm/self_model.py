"""
Persistent self-model for the LLM participant.

ARCHITECTURE: Three layers —
  1. Decision log: append-only record of every orchestrator decision
  2. Participation reducer: per-room derived state updated after each decision
  3. Self-awareness context: rendered into the prompt so the LLM knows itself

WHY: The LLM participant should not be stateless between messages. It needs
accumulated awareness of its own participation patterns — when it spoke,
when it chose silence, how its contributions landed, and the shape of the
conversation it's participating in.

TRADEOFF: Additional DB writes per message (~2 queries). Acceptable because
the LLM API call itself takes 1-5 seconds; a few milliseconds of bookkeeping
is invisible.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import UUID

from .heuristics import InterjectionDecision

logger = logging.getLogger(__name__)


@dataclass
class ParticipationSnapshot:
    """
    The LLM's self-model for a room, rendered from DB state.

    WHY: This is the data structure that gets injected into the prompt.
    It answers: "What have I been doing in this conversation?"
    """
    # Temporal
    last_spoke_at: Optional[datetime] = None
    turns_since_last_spoke: int = 0
    seconds_since_last_spoke: Optional[int] = None
    total_messages_sent: int = 0
    total_silences: int = 0

    # Mode
    primary_count: int = 0
    provoker_count: int = 0
    last_mode: Optional[str] = None

    # Confidence
    avg_confidence_last_10: Optional[float] = None
    confidence_trend: str = "stable"

    # Balance
    llm_message_ratio: Optional[float] = None

    # Effectiveness
    engaged_count: int = 0
    ignored_count: int = 0
    effectiveness_avg: Optional[float] = None

    # Conversation shape
    active_thread_count: int = 1
    total_fork_count: int = 0

    # Session
    session_count: int = 0
    days_since_last_session: Optional[float] = None

    # Recent silence reasons
    recent_silence_reasons: list[str] = field(default_factory=list)


class SelfModel:
    """
    Manages the LLM's persistent self-model.

    Called by the orchestrator after every decision (speak or silence).
    Queries the DB to build self-awareness context for prompts.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    async def log_decision(
        self,
        *,
        room_id: UUID,
        thread_id: UUID,
        triggered_by_message_id: Optional[UUID],
        decision: InterjectionDecision,
        human_turn_count: Optional[int] = None,
        semantic_novelty: Optional[float] = None,
        unsurfaced_memory_count: Optional[int] = None,
        speaker_balance: Optional[dict[str, int]] = None,
        message_count: Optional[int] = None,
        response_message_id: Optional[UUID] = None,
        mode: str = "silence",
    ) -> Optional[int]:
        """
        Persist a decision to the llm_decisions log.

        Called on both the speak and silence paths.
        Returns the decision ID, or None on failure.
        """
        try:
            import json
            balance_json = json.dumps(speaker_balance) if speaker_balance else None
            considered = decision.considered_reasons if hasattr(decision, 'considered_reasons') else []

            row = await self.db.fetchrow(
                """INSERT INTO llm_decisions
                   (room_id, thread_id, triggered_by_message_id,
                    should_interject, reason, confidence, use_provoker,
                    considered_reasons, human_turn_count, semantic_novelty,
                    unsurfaced_memory_count, speaker_balance, message_count_in_thread,
                    response_message_id, mode)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                   RETURNING id""",
                room_id, thread_id, triggered_by_message_id,
                decision.should_interject, decision.reason, decision.confidence,
                decision.use_provoker, considered, human_turn_count,
                semantic_novelty, unsurfaced_memory_count,
                balance_json, message_count,
                response_message_id, mode,
            )
            decision_id = row["id"] if row else None

            # Update participation state
            await self._update_participation_state(
                room_id=room_id,
                decision=decision,
                response_message_id=response_message_id,
                mode=mode,
            )

            return decision_id

        except Exception as e:
            # WHY: Self-model failures must never block the conversation.
            # Log and continue — the LLM works without self-awareness,
            # it's just less aware.
            logger.warning("Failed to log decision: %s", e)
            return None

    async def _update_participation_state(
        self,
        *,
        room_id: UUID,
        decision: InterjectionDecision,
        response_message_id: Optional[UUID],
        mode: str,
    ) -> None:
        """
        Update the per-room participation reducer.

        ARCHITECTURE: Upsert pattern — creates the row on first decision,
        updates incrementally thereafter. This is the reducer.
        """
        now = datetime.now(timezone.utc)
        spoke = decision.should_interject

        if spoke:
            await self.db.execute(
                """INSERT INTO llm_participation_state
                   (room_id, last_spoke_at, last_spoke_message_id,
                    turns_since_last_spoke, total_messages_sent, total_silences,
                    primary_count, provoker_count, protocol_count,
                    last_mode, recent_confidences, updated_at)
                   VALUES ($1, $2, $3, 0, 1, 0,
                           CASE WHEN $4 = 'primary' THEN 1 ELSE 0 END,
                           CASE WHEN $4 = 'provoker' THEN 1 ELSE 0 END,
                           CASE WHEN $4 = 'protocol' THEN 1 ELSE 0 END,
                           $4, ARRAY[$5::REAL], $2)
                   ON CONFLICT (room_id) DO UPDATE SET
                       last_spoke_at = $2,
                       last_spoke_message_id = $3,
                       turns_since_last_spoke = 0,
                       total_messages_sent = llm_participation_state.total_messages_sent + 1,
                       primary_count = llm_participation_state.primary_count + CASE WHEN $4 = 'primary' THEN 1 ELSE 0 END,
                       provoker_count = llm_participation_state.provoker_count + CASE WHEN $4 = 'provoker' THEN 1 ELSE 0 END,
                       protocol_count = llm_participation_state.protocol_count + CASE WHEN $4 = 'protocol' THEN 1 ELSE 0 END,
                       last_mode = $4,
                       recent_confidences = (
                           CASE WHEN array_length(llm_participation_state.recent_confidences, 1) >= 10
                           THEN llm_participation_state.recent_confidences[2:10] || ARRAY[$5::REAL]
                           ELSE llm_participation_state.recent_confidences || ARRAY[$5::REAL]
                           END
                       ),
                       updated_at = $2""",
                room_id, now, response_message_id, mode, decision.confidence,
            )
        else:
            # Silence: increment turns and silence count
            await self.db.execute(
                """INSERT INTO llm_participation_state
                   (room_id, turns_since_last_spoke, total_silences,
                    recent_confidences, updated_at)
                   VALUES ($1, 1, 1, ARRAY[$2::REAL], $3)
                   ON CONFLICT (room_id) DO UPDATE SET
                       turns_since_last_spoke = llm_participation_state.turns_since_last_spoke + 1,
                       total_silences = llm_participation_state.total_silences + 1,
                       recent_confidences = (
                           CASE WHEN array_length(llm_participation_state.recent_confidences, 1) >= 10
                           THEN llm_participation_state.recent_confidences[2:10] || ARRAY[$2::REAL]
                           ELSE llm_participation_state.recent_confidences || ARRAY[$2::REAL]
                           END
                       ),
                       updated_at = $3""",
                room_id, decision.confidence, now,
            )

        # Update derived metrics
        await self._update_derived_metrics(room_id)

    async def _update_derived_metrics(self, room_id: UUID) -> None:
        """
        Compute derived metrics from the recent_confidences array.

        WHY: Confidence trend tells the LLM whether it's becoming more
        or less certain about when to speak. A falling trend might mean
        the conversation is in unfamiliar territory.
        """
        try:
            row = await self.db.fetchrow(
                "SELECT recent_confidences FROM llm_participation_state WHERE room_id = $1",
                room_id,
            )
            if not row or not row["recent_confidences"]:
                return

            confs = row["recent_confidences"]
            avg = sum(confs) / len(confs) if confs else None

            # Compute trend from first half vs second half
            trend = "stable"
            if len(confs) >= 4:
                mid = len(confs) // 2
                first_half = sum(confs[:mid]) / mid
                second_half = sum(confs[mid:]) / (len(confs) - mid)
                diff = second_half - first_half
                if diff > 0.1:
                    trend = "rising"
                elif diff < -0.1:
                    trend = "falling"

            await self.db.execute(
                """UPDATE llm_participation_state
                   SET avg_confidence_last_10 = $1, confidence_trend = $2
                   WHERE room_id = $3""",
                avg, trend, room_id,
            )
        except Exception as e:
            logger.debug("Failed to update derived metrics: %s", e)

    async def get_participation_snapshot(
        self, room_id: UUID,
    ) -> Optional[ParticipationSnapshot]:
        """
        Load the current participation state for a room.

        WHY: This is what gets rendered into the prompt. The LLM sees
        its own participation history.
        """
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM llm_participation_state WHERE room_id = $1",
                room_id,
            )
            if not row:
                return None

            # Compute seconds since last spoke
            seconds_since = None
            if row["last_spoke_at"]:
                delta = datetime.now(timezone.utc) - row["last_spoke_at"]
                seconds_since = int(delta.total_seconds())

            # Get recent silence reasons from decision log
            silence_rows = await self.db.fetch(
                """SELECT reason FROM llm_decisions
                   WHERE room_id = $1 AND should_interject = FALSE
                   ORDER BY decided_at DESC LIMIT 5""",
                room_id,
            )
            silence_reasons = [r["reason"] for r in silence_rows]

            return ParticipationSnapshot(
                last_spoke_at=row["last_spoke_at"],
                turns_since_last_spoke=row["turns_since_last_spoke"] or 0,
                seconds_since_last_spoke=seconds_since,
                total_messages_sent=row["total_messages_sent"] or 0,
                total_silences=row["total_silences"] or 0,
                primary_count=row["primary_count"] or 0,
                provoker_count=row["provoker_count"] or 0,
                last_mode=row["last_mode"],
                avg_confidence_last_10=row["avg_confidence_last_10"],
                confidence_trend=row["confidence_trend"] or "stable",
                llm_message_ratio=row["llm_message_ratio"],
                engaged_count=row["engaged_count"] or 0,
                ignored_count=row["ignored_count"] or 0,
                effectiveness_avg=row["effectiveness_avg"],
                active_thread_count=row["active_thread_count"] or 1,
                total_fork_count=row["total_fork_count"] or 0,
                session_count=row["session_count"] or 0,
                days_since_last_session=row["days_since_last_session"],
                recent_silence_reasons=silence_reasons,
            )

        except Exception as e:
            logger.warning("Failed to load participation snapshot: %s", e)
            return None

    async def measure_effectiveness(
        self,
        *,
        room_id: UUID,
        llm_message_id: UUID,
        decision_id: int,
    ) -> None:
        """
        Measure how humans responded to an LLM message.

        Called as a background task ~30 seconds after the LLM speaks,
        giving humans time to respond.

        WHY: The LLM needs to know if its contributions land. Without
        this, the identity distillation relies on LLM self-report, which
        is unreliable.
        """
        try:
            # Find human messages after this LLM message (within 3 messages)
            responses = await self.db.fetch(
                """SELECT content, char_length(content) as length
                   FROM messages
                   WHERE thread_id = (SELECT thread_id FROM messages WHERE id = $1)
                   AND sequence > (SELECT sequence FROM messages WHERE id = $1)
                   AND speaker_type = 'HUMAN'
                   ORDER BY sequence
                   LIMIT 3""",
                llm_message_id,
            )

            if not responses:
                # No human response — ignored
                human_responded = False
                response_length = 0
                effectiveness = 0.0
            else:
                human_responded = True
                response_length = responses[0]["length"]
                # Simple effectiveness heuristic:
                # longer responses = more engaged, questions = very engaged
                effectiveness = min(1.0, response_length / 200.0)
                if "?" in (responses[0]["content"] or ""):
                    effectiveness = min(1.0, effectiveness + 0.3)

            await self.db.execute(
                """UPDATE llm_decisions
                   SET effectiveness_score = $1,
                       human_responded = $2,
                       human_response_length = $3
                   WHERE id = $4""",
                effectiveness, human_responded, response_length, decision_id,
            )

            # Update participation state aggregates
            if human_responded:
                await self.db.execute(
                    """UPDATE llm_participation_state
                       SET engaged_count = engaged_count + 1,
                           avg_human_response_length_after = COALESCE(
                               (avg_human_response_length_after * engaged_count + $1) / (engaged_count + 1),
                               $1
                           )
                       WHERE room_id = $2""",
                    response_length, room_id,
                )
            else:
                await self.db.execute(
                    """UPDATE llm_participation_state
                       SET ignored_count = ignored_count + 1
                       WHERE room_id = $1""",
                    room_id,
                )

            logger.debug(
                "Effectiveness measured for decision %d: score=%.2f responded=%s",
                decision_id, effectiveness, human_responded,
            )

        except Exception as e:
            logger.debug("Failed to measure effectiveness: %s", e)

    def render_self_awareness(self, snapshot: ParticipationSnapshot) -> str:
        """
        Render the participation snapshot into a prompt section.

        WHY: The LLM reads this about itself before deciding how to respond.
        This is the self-model becoming self-awareness.
        """
        lines = ["## Your Participation State (This Conversation)"]

        # Temporal
        if snapshot.seconds_since_last_spoke is not None:
            turns = snapshot.turns_since_last_spoke
            secs = snapshot.seconds_since_last_spoke
            if secs < 60:
                time_str = f"{secs}s"
            elif secs < 3600:
                time_str = f"{secs // 60}m"
            else:
                time_str = f"{secs // 3600}h {(secs % 3600) // 60}m"
            lines.append(f"- You last spoke {turns} turn(s) ago ({time_str})")
        elif snapshot.total_messages_sent == 0:
            lines.append("- You have not spoken yet in this conversation")

        lines.append(
            f"- You've sent {snapshot.total_messages_sent} message(s) total, "
            f"chose silence {snapshot.total_silences} time(s)"
        )

        # Mode
        if snapshot.total_messages_sent > 0:
            mode_parts = []
            if snapshot.primary_count:
                mode_parts.append(f"{snapshot.primary_count} as primary")
            if snapshot.provoker_count:
                mode_parts.append(f"{snapshot.provoker_count} as provoker")
            if mode_parts:
                lines.append(f"- Mode breakdown: {', '.join(mode_parts)}")

        # Confidence
        if snapshot.avg_confidence_last_10 is not None:
            lines.append(
                f"- Your confidence has been {snapshot.confidence_trend} "
                f"(avg {snapshot.avg_confidence_last_10:.2f} over last 10 decisions)"
            )

        # Effectiveness
        total_spoken = snapshot.engaged_count + snapshot.ignored_count
        if total_spoken > 0:
            engage_rate = snapshot.engaged_count / total_spoken
            lines.append(
                f"- {snapshot.engaged_count}/{total_spoken} of your contributions "
                f"received engaged human responses ({engage_rate:.0%})"
            )
            if snapshot.ignored_count > 0:
                lines.append(
                    f"- {snapshot.ignored_count} contribution(s) received no human response"
                )

        # Recent silence reasons
        if snapshot.recent_silence_reasons:
            unique_reasons = list(dict.fromkeys(snapshot.recent_silence_reasons))[:3]
            lines.append(
                f"- Recent silence reasons: {', '.join(unique_reasons)}"
            )

        # Session
        if snapshot.session_count > 1:
            lines.append(
                f"- This is session #{snapshot.session_count} with these participants"
            )
            if snapshot.days_since_last_session is not None:
                if snapshot.days_since_last_session < 1:
                    lines.append("- Last session was earlier today")
                else:
                    lines.append(
                        f"- Last session was {snapshot.days_since_last_session:.0f} day(s) ago"
                    )

        return "\n".join(lines)
