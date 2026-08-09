# llm/briefing.py — shared morning-briefing builder

"""
ARCHITECTURE: The briefing body used to live inside the /rooms/{id}/briefing
endpoint (api/main.py). It is extracted here so BOTH the on-demand endpoint
and the night-shift morning_brief job call the same builder. This module
deliberately imports nothing from FastAPI or api.* — the LLM provider import
stays lazy so importing this module never touches provider config.

WHY: async dialogue needs a "catch-up" mechanism, not raw message history —
and the 7am brief must produce exactly what a returning user would see.

TRADEOFF: LLM call per briefing vs pre-computed summaries. Haiku is cheap and
the deterministic sections (commitments, staleness, unanswered questions)
carry the facts even when the summary call fails.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class BriefingHighlight(BaseModel):
    """A single highlight from missed activity."""
    speaker: str
    content_preview: str
    message_type: str
    timestamp: datetime


class BriefingResponse(BaseModel):
    """Morning briefing summarizing what happened while user was offline."""
    summary: str
    messages_missed: int
    memories_created: int
    threads_forked: int
    highlights: List[BriefingHighlight]
    last_seen: Optional[datetime]
    generated_at: datetime
    # Deterministic content sections (additive — the pre-extraction response
    # shape is untouched). Each carries facts the Haiku summary might omit.
    commitments_due: List[dict] = []
    thesis_staleness: Optional[dict] = None
    unanswered_questions: List[BriefingHighlight] = []


def _speaker_key(row) -> str:
    """Stable per-speaker key, mirroring analytics/analyzer.py's heuristic."""
    return str(row['user_id']) if row['user_id'] else row['speaker_type']


def _unanswered_questions(message_rows) -> List[BriefingHighlight]:
    """Questions with no later reply from a different speaker.

    ARCHITECTURE: Heuristic mirror of analyzer._compute_question_resolution —
    a question counts as answered if ANY later message in the window comes
    from a different speaker.
    TRADEOFF: Over-counts "unanswered" for questions answered after the
    window; a brief that nudges is the safe direction to be wrong in.
    """
    unanswered = []
    for idx, q in enumerate(message_rows):
        if q['message_type'] != 'question':
            continue
        q_speaker = _speaker_key(q)
        answered = any(
            _speaker_key(r) != q_speaker
            for r in message_rows[idx + 1:]
        )
        if not answered:
            unanswered.append(BriefingHighlight(
                speaker=q['sender_name'],
                content_preview=q['content'][:200],
                message_type='question',
                timestamp=q['created_at'],
            ))
    return unanswered


async def _commitments_due(db, room_id: UUID) -> List[dict]:
    """Active commitments with deadlines inside 72h (stakes/manager.py)."""
    try:
        from stakes.manager import CommitmentManager

        rows = await CommitmentManager(db).get_expiring_soon(room_id, days=3)
        return [{
            "claim": row["claim"],
            "resolution_criteria": row.get("resolution_criteria"),
            "category": row.get("category"),
            "deadline": row["deadline"],
        } for row in rows]
    except Exception as e:
        # A stakes hiccup must not sink the whole brief.
        logger.warning(f"Briefing commitments section failed: {e}")
        return []


async def _thesis_staleness(db, room_id: UUID, now: datetime) -> Optional[dict]:
    """Age of the room's trading_config snapshot, if the room has one.

    Query pattern mirrors trading_watch._linked_rooms: the snapshot timestamp
    rides inside rooms.trading_config->>'timestamp'.
    """
    try:
        row = await db.fetchrow(
            "SELECT trading_config->>'timestamp' AS snap_ts FROM rooms WHERE id = $1",
            room_id,
        )
    except Exception as e:
        logger.warning(f"Briefing staleness section failed: {e}")
        return None
    if not row or not row["snap_ts"]:
        return None
    try:
        snap_at = datetime.fromisoformat(str(row["snap_ts"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if snap_at.tzinfo is None:
        snap_at = snap_at.replace(tzinfo=timezone.utc)
    return {
        "last_snapshot": snap_at,
        "stale_hours": round((now - snap_at).total_seconds() / 3600, 1),
    }


async def build_briefing(
    db,
    room_id: UUID,
    since: datetime,
    exclude_user_id: Optional[UUID] = None,
) -> BriefingResponse:
    """Build the morning briefing for a room.

    `since` is presence-derived (user_presence.last_heartbeat) for the
    endpoint, and now-24h for the night-shift job. `exclude_user_id` keeps
    the endpoint's "what *I* missed" semantics; the job passes None for a
    room-wide brief.
    """
    now = datetime.now(timezone.utc)
    last_seen = since

    # Fetch messages since last_seen (capped at 100 to prevent OOM on long absences)
    if exclude_user_id is not None:
        message_rows = await db.fetch(
            """SELECT m.*, COALESCE(u.display_name, m.speaker_type) as sender_name
               FROM messages m
               JOIN threads t ON m.thread_id = t.id
               LEFT JOIN users u ON m.user_id = u.id
               WHERE t.room_id = $1
                 AND m.created_at > $2
                 AND NOT m.is_deleted
                 AND (m.user_id IS NULL OR m.user_id != $3)
               ORDER BY m.created_at DESC
               LIMIT 100""",
            room_id, last_seen, exclude_user_id
        )
    else:
        message_rows = await db.fetch(
            """SELECT m.*, COALESCE(u.display_name, m.speaker_type) as sender_name
               FROM messages m
               JOIN threads t ON m.thread_id = t.id
               LEFT JOIN users u ON m.user_id = u.id
               WHERE t.room_id = $1
                 AND m.created_at > $2
                 AND NOT m.is_deleted
               ORDER BY m.created_at DESC
               LIMIT 100""",
            room_id, last_seen
        )
    # Reverse to chronological order after LIMIT
    message_rows = list(reversed(message_rows))

    messages_missed = len(message_rows)

    # Count memories created since last_seen
    memories_created = await db.fetchval(
        """SELECT COUNT(*) FROM memories
           WHERE room_id = $1 AND created_at > $2""",
        room_id, last_seen
    ) or 0

    # Count threads forked since last_seen
    threads_forked = await db.fetchval(
        """SELECT COUNT(*) FROM threads
           WHERE room_id = $1 AND created_at > $2
           AND parent_thread_id IS NOT NULL""",
        room_id, last_seen
    ) or 0

    # Build highlights from messages (up to 10 most significant)
    highlights = []
    for row in message_rows[:10]:
        highlights.append(BriefingHighlight(
            speaker=row['sender_name'],
            content_preview=row['content'][:200],
            message_type=row['message_type'] if row['message_type'] else 'text',
            timestamp=row['created_at'],
        ))

    # Deterministic content sections
    commitments_due = await _commitments_due(db, room_id)
    thesis_staleness = await _thesis_staleness(db, room_id, now)
    unanswered = _unanswered_questions(message_rows)

    # Generate LLM summary if there are messages to summarize
    summary = "Nothing happened while you were away."
    if message_rows:
        try:
            from llm.providers import get_provider, ProviderName, LLMRequest

            messages_text = "\n".join(
                f"[{row['sender_name']}] {row['content'][:300]}"
                for row in message_rows[:30]  # Cap at 30 messages for context
            )

            provider = get_provider(ProviderName.ANTHROPIC)
            request = LLMRequest(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Summarize what happened in this conversation. "
                        f"Be concise (2-4 sentences). Focus on: who said what, "
                        f"key claims made, questions raised, and any tensions.\n\n"
                        f"{messages_text}"
                    ),
                }],
                system="You are summarizing missed conversation activity for a returning user. Be brief and informative.",
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                temperature=0.2,
            )
            response = await provider.complete(request)
            summary = response.content
        except Exception as e:
            logger.warning(f"Briefing LLM summary failed: {e}")
            summary = f"{messages_missed} messages were exchanged while you were away."

    return BriefingResponse(
        summary=summary,
        messages_missed=messages_missed,
        memories_created=memories_created,
        threads_forked=threads_forked,
        highlights=highlights,
        last_seen=last_seen,
        generated_at=now,
        commitments_due=commitments_due,
        thesis_staleness=thesis_staleness,
        unanswered_questions=unanswered,
    )
