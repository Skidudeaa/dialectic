# analytics/analyzer.py — Conversation analytics engine
"""
ARCHITECTURE: Read-only analytics computed from event-sourced data.
WHY: All metrics derived from existing events/messages tables — no new schema.
TRADEOFF: Computed on demand (not materialized) — fresh but costs a query per request.
"""

import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from analytics.dna import ConversationDNA


# ============================================================
# RESPONSE MODELS
# ============================================================

class ThreadAnalytics(BaseModel):
    """
    Complete analytics snapshot for a single thread.

    ARCHITECTURE: Flat structure with pre-computed aggregates.
    WHY: Single response gives frontend everything it needs — no follow-up queries.
    TRADEOFF: Payload size vs round-trips.
    """
    thread_id: UUID
    total_messages: int
    human_messages: int
    llm_messages: int
    message_type_counts: dict[str, int]
    argument_density: float
    question_count: int
    question_resolution_rate: float
    fork_count: int
    memory_crystallizations: int
    provoker_interventions: int
    turn_balance: dict[str, int]
    duration_minutes: float
    dna: ConversationDNA


class RoomAnalytics(BaseModel):
    """
    Aggregated analytics across all threads in a room.

    ARCHITECTURE: Room-level rollup with per-thread breakdown available via separate endpoint.
    WHY: Room overview without needing to fetch every thread individually.
    """
    room_id: UUID
    thread_count: int
    total_messages: int
    human_messages: int
    llm_messages: int
    message_type_counts: dict[str, int]
    argument_density: float
    question_count: int
    fork_count: int
    memory_crystallizations: int
    provoker_interventions: int
    turn_balance: dict[str, int]
    duration_minutes: float
    dna: ConversationDNA


# ============================================================
# ANALYZER
# ============================================================

class ConversationAnalyzer:
    """
    Main analytics engine. Queries the database and computes metrics.

    ARCHITECTURE: Stateless service — takes a db connection, runs queries, returns models.
    WHY: No cached state means results are always fresh from the event log.
    TRADEOFF: More DB queries per request vs stale materialized views.
    """

    def __init__(self, db: asyncpg.Connection):
        self.db = db

    async def analyze_thread(self, thread_id: UUID) -> ThreadAnalytics:
        """Compute analytics for a single thread."""
        messages = await self.db.fetch(
            """SELECT speaker_type, message_type, user_id, created_at, content
               FROM messages
               WHERE thread_id = $1 AND NOT is_deleted
               ORDER BY sequence""",
            thread_id
        )

        total = len(messages)
        if total == 0:
            now = datetime.now(timezone.utc)
            empty_dna = ConversationDNA(
                thread_id=thread_id, computed_at=now,
                tension=0, velocity=0, asymmetry=0,
                depth=0, divergence=0, memory_density=0,
            )
            return ThreadAnalytics(
                thread_id=thread_id, total_messages=0,
                human_messages=0, llm_messages=0,
                message_type_counts={}, argument_density=0,
                question_count=0, question_resolution_rate=0,
                fork_count=0, memory_crystallizations=0,
                provoker_interventions=0, turn_balance={},
                duration_minutes=0, dna=empty_dna,
            )

        # Count by speaker type
        human = sum(1 for m in messages if m['speaker_type'] == 'human')
        llm = sum(1 for m in messages if m['speaker_type'] in ('llm_primary', 'llm_provoker'))

        # Count by message type
        type_counts: dict[str, int] = {}
        for m in messages:
            mt = m['message_type']
            type_counts[mt] = type_counts.get(mt, 0) + 1

        # Argument density: (CLAIM + COUNTEREXAMPLE) / total
        claims = type_counts.get('claim', 0)
        counterexamples = type_counts.get('counterexample', 0)
        argument_density = (claims + counterexamples) / total if total > 0 else 0

        # Questions
        question_count = type_counts.get('question', 0)
        question_resolution_rate = self._compute_question_resolution(messages)

        # Fork count (child threads)
        fork_count = await self.db.fetchval(
            "SELECT COUNT(*) FROM threads WHERE parent_thread_id = $1",
            thread_id
        )

        # Memory crystallizations (MEMORY_ADDED events for this thread)
        memory_crystallizations = await self.db.fetchval(
            "SELECT COUNT(*) FROM events WHERE thread_id = $1 AND event_type = 'memory_added'",
            thread_id
        )

        # Provoker interventions
        provoker_interventions = sum(
            1 for m in messages if m['speaker_type'] == 'llm_provoker'
        )

        # Turn balance: messages per speaker (keyed by user_id or speaker_type for LLM)
        turn_balance: dict[str, int] = {}
        for m in messages:
            if m['user_id']:
                key = str(m['user_id'])
            else:
                key = m['speaker_type']
            turn_balance[key] = turn_balance.get(key, 0) + 1

        # Duration
        first_ts = messages[0]['created_at']
        last_ts = messages[-1]['created_at']
        duration_minutes = (last_ts - first_ts).total_seconds() / 60.0

        dna = await self.compute_dna(thread_id)

        return ThreadAnalytics(
            thread_id=thread_id,
            total_messages=total,
            human_messages=human,
            llm_messages=llm,
            message_type_counts=type_counts,
            argument_density=round(argument_density, 4),
            question_count=question_count,
            question_resolution_rate=round(question_resolution_rate, 4),
            fork_count=fork_count,
            memory_crystallizations=memory_crystallizations,
            provoker_interventions=provoker_interventions,
            turn_balance=turn_balance,
            duration_minutes=round(duration_minutes, 2),
            dna=dna,
        )

    async def analyze_room(self, room_id: UUID) -> RoomAnalytics:
        """Aggregate analytics across all threads in a room."""
        messages = await self.db.fetch(
            """SELECT m.speaker_type, m.message_type, m.user_id, m.created_at, m.content
               FROM messages m
               JOIN threads t ON m.thread_id = t.id
               WHERE t.room_id = $1 AND NOT m.is_deleted
               ORDER BY m.created_at""",
            room_id
        )

        thread_count = await self.db.fetchval(
            "SELECT COUNT(*) FROM threads WHERE room_id = $1", room_id
        )

        total = len(messages)
        if total == 0:
            now = datetime.now(timezone.utc)
            empty_dna = ConversationDNA(
                thread_id=room_id, computed_at=now,
                tension=0, velocity=0, asymmetry=0,
                depth=0, divergence=0, memory_density=0,
            )
            return RoomAnalytics(
                room_id=room_id, thread_count=thread_count,
                total_messages=0, human_messages=0, llm_messages=0,
                message_type_counts={}, argument_density=0,
                question_count=0, fork_count=0,
                memory_crystallizations=0, provoker_interventions=0,
                turn_balance={}, duration_minutes=0, dna=empty_dna,
            )

        human = sum(1 for m in messages if m['speaker_type'] == 'human')
        llm = sum(1 for m in messages if m['speaker_type'] in ('llm_primary', 'llm_provoker'))

        type_counts: dict[str, int] = {}
        for m in messages:
            mt = m['message_type']
            type_counts[mt] = type_counts.get(mt, 0) + 1

        claims = type_counts.get('claim', 0)
        counterexamples = type_counts.get('counterexample', 0)
        argument_density = (claims + counterexamples) / total

        question_count = type_counts.get('question', 0)

        # Fork count: threads with a parent in this room
        fork_count = await self.db.fetchval(
            "SELECT COUNT(*) FROM threads WHERE room_id = $1 AND parent_thread_id IS NOT NULL",
            room_id
        )

        memory_crystallizations = await self.db.fetchval(
            "SELECT COUNT(*) FROM events WHERE room_id = $1 AND event_type = 'memory_added'",
            room_id
        )

        provoker_interventions = sum(
            1 for m in messages if m['speaker_type'] == 'llm_provoker'
        )

        turn_balance: dict[str, int] = {}
        for m in messages:
            if m['user_id']:
                key = str(m['user_id'])
            else:
                key = m['speaker_type']
            turn_balance[key] = turn_balance.get(key, 0) + 1

        first_ts = messages[0]['created_at']
        last_ts = messages[-1]['created_at']
        duration_minutes = (last_ts - first_ts).total_seconds() / 60.0

        dna = await self.compute_room_dna(room_id)

        return RoomAnalytics(
            room_id=room_id,
            thread_count=thread_count,
            total_messages=total,
            human_messages=human,
            llm_messages=llm,
            message_type_counts=type_counts,
            argument_density=round(argument_density, 4),
            question_count=question_count,
            fork_count=fork_count,
            memory_crystallizations=memory_crystallizations,
            provoker_interventions=provoker_interventions,
            turn_balance=turn_balance,
            duration_minutes=round(duration_minutes, 2),
            dna=dna,
        )

    async def compute_dna(self, thread_id: UUID) -> ConversationDNA:
        """
        Compute the 6-dimensional DNA fingerprint for a thread.

        ARCHITECTURE: Each dimension computed independently, then clamped to [0, 1].
        WHY: Independent computation means each metric is interpretable on its own.
        TRADEOFF: No cross-dimension normalization — dimensions are not comparable in absolute terms.
        """
        now = datetime.now(timezone.utc)

        messages = await self.db.fetch(
            """SELECT speaker_type, message_type, user_id, created_at, content
               FROM messages
               WHERE thread_id = $1 AND NOT is_deleted
               ORDER BY sequence""",
            thread_id
        )

        total = len(messages)
        if total == 0:
            return ConversationDNA(
                thread_id=thread_id, computed_at=now,
                tension=0, velocity=0, asymmetry=0,
                depth=0, divergence=0, memory_density=0,
            )

        # --- Tension: (COUNTEREXAMPLE + CLAIM) / total ---
        argument_msgs = sum(
            1 for m in messages
            if m['message_type'] in ('claim', 'counterexample')
        )
        tension = argument_msgs / total

        # --- Velocity: messages per hour, sigmoid-normalized ---
        first_ts = messages[0]['created_at']
        last_ts = messages[-1]['created_at']
        hours = max((last_ts - first_ts).total_seconds() / 3600, 0.01)
        msgs_per_hour = total / hours
        # Sigmoid normalization: 30 msgs/hr maps to ~0.5
        velocity = 1.0 / (1.0 + math.exp(-0.1 * (msgs_per_hour - 30)))

        # --- Asymmetry: speaker balance via normalized entropy ---
        speaker_counts: dict[str, int] = {}
        for m in messages:
            key = str(m['user_id']) if m['user_id'] else m['speaker_type']
            speaker_counts[key] = speaker_counts.get(key, 0) + 1

        n_speakers = len(speaker_counts)
        if n_speakers <= 1:
            asymmetry = 0.0
        else:
            # Shannon entropy normalized by max possible entropy
            entropy = 0.0
            for count in speaker_counts.values():
                p = count / total
                if p > 0:
                    entropy -= p * math.log2(p)
            max_entropy = math.log2(n_speakers)
            asymmetry = entropy / max_entropy if max_entropy > 0 else 0.0

        # --- Depth: structured type ratio + message length signal ---
        structured = sum(
            1 for m in messages
            if m['message_type'] in ('claim', 'counterexample', 'definition', 'question')
        )
        type_ratio = structured / total

        avg_length = sum(len(m['content']) for m in messages) / total
        # Sigmoid: 500 chars maps to ~0.5
        length_signal = 1.0 / (1.0 + math.exp(-0.005 * (avg_length - 500)))

        depth = 0.6 * type_ratio + 0.4 * length_signal

        # --- Divergence: fork count / message count ---
        fork_count = await self.db.fetchval(
            "SELECT COUNT(*) FROM threads WHERE parent_thread_id = $1",
            thread_id
        )
        # Sigmoid: 1 fork per 10 messages maps to ~0.5
        fork_ratio = fork_count / max(total, 1)
        divergence = 1.0 / (1.0 + math.exp(-20 * (fork_ratio - 0.1)))

        # --- Memory density: memory ops / message count ---
        memory_ops = await self.db.fetchval(
            """SELECT COUNT(*) FROM events
               WHERE thread_id = $1
                 AND event_type IN ('memory_added', 'memory_edited', 'memory_invalidated')""",
            thread_id
        )
        mem_ratio = memory_ops / max(total, 1)
        # Sigmoid: 1 memory per 10 messages maps to ~0.5
        memory_density = 1.0 / (1.0 + math.exp(-20 * (mem_ratio - 0.1)))

        return ConversationDNA(
            thread_id=thread_id,
            computed_at=now,
            tension=round(_clamp(tension), 4),
            velocity=round(_clamp(velocity), 4),
            asymmetry=round(_clamp(asymmetry), 4),
            depth=round(_clamp(depth), 4),
            divergence=round(_clamp(divergence), 4),
            memory_density=round(_clamp(memory_density), 4),
        )

    async def compute_room_dna(self, room_id: UUID) -> ConversationDNA:
        """
        Aggregate DNA across all threads in a room.

        ARCHITECTURE: Weighted average by message count per thread.
        WHY: Threads with more messages contribute proportionally more.
        TRADEOFF: Ignores temporal ordering of threads.
        """
        now = datetime.now(timezone.utc)

        thread_ids = await self.db.fetch(
            "SELECT id FROM threads WHERE room_id = $1", room_id
        )

        if not thread_ids:
            return ConversationDNA(
                thread_id=room_id, computed_at=now,
                tension=0, velocity=0, asymmetry=0,
                depth=0, divergence=0, memory_density=0,
            )

        # Compute per-thread DNA with message counts for weighting
        dnas: list[tuple[ConversationDNA, int]] = []
        for row in thread_ids:
            tid = row['id']
            count = await self.db.fetchval(
                "SELECT COUNT(*) FROM messages WHERE thread_id = $1 AND NOT is_deleted",
                tid
            )
            if count > 0:
                dna = await self.compute_dna(tid)
                dnas.append((dna, count))

        if not dnas:
            return ConversationDNA(
                thread_id=room_id, computed_at=now,
                tension=0, velocity=0, asymmetry=0,
                depth=0, divergence=0, memory_density=0,
            )

        total_weight = sum(w for _, w in dnas)

        def weighted_avg(attr: str) -> float:
            return sum(getattr(d, attr) * w for d, w in dnas) / total_weight

        return ConversationDNA(
            thread_id=room_id,
            computed_at=now,
            tension=round(weighted_avg('tension'), 4),
            velocity=round(weighted_avg('velocity'), 4),
            asymmetry=round(weighted_avg('asymmetry'), 4),
            depth=round(weighted_avg('depth'), 4),
            divergence=round(weighted_avg('divergence'), 4),
            memory_density=round(weighted_avg('memory_density'), 4),
        )

    @staticmethod
    def _compute_question_resolution(messages: list) -> float:
        """
        Estimate question resolution rate.

        ARCHITECTURE: Heuristic — a question is "resolved" if a non-question
        message from a different speaker follows it before the thread ends.
        WHY: No explicit resolution tracking exists; this is a reasonable proxy.
        TRADEOFF: Over-estimates resolution for active threads, under-estimates
        for threads that end on an unanswered question.
        """
        questions = [
            (i, m) for i, m in enumerate(messages)
            if m['message_type'] == 'question'
        ]
        if not questions:
            return 0.0

        resolved = 0
        for idx, q in questions:
            q_speaker = str(q['user_id']) if q['user_id'] else q['speaker_type']
            # Look for a response from a different speaker
            for j in range(idx + 1, len(messages)):
                r = messages[j]
                r_speaker = str(r['user_id']) if r['user_id'] else r['speaker_type']
                if r_speaker != q_speaker:
                    resolved += 1
                    break

        return resolved / len(questions)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, value))
