# llm/annotator.py — Async dialogue annotator engine

"""
ARCHITECTURE: LLM mode for when only one human is present.
WHY: The LLM should add value even in async conversations —
     linking ideas, surfacing context, identifying tensions.
TRADEOFF: Different voice (librarian/curator) vs consistent participant persona.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from presence import ONLINE_SQL, online_sql

from models import (
    Message, Event, EventType, SpeakerType, MessageType,
)

logger = logging.getLogger(__name__)

# Annotations per room per UTC day — a runaway ceiling, NOT the volume control.
# Measured against the week of 2026-08-08: a cap of 12 would have cut 2 of 126
# annotations, because the problem was never spikes, it was a steady 8-14/day
# baseline from annotating every message. The volume control is the worth gate
# below. 0 disables annotation entirely.
ANNOTATOR_DAILY_CAP = int(os.getenv("ANNOTATOR_DAILY_CAP", "12"))

# The worth gate. The annotator's stated job is to CONNECT and SURFACE — to
# leave the absent person a breadcrumb tying this message to what the room
# already knows. When recall finds nothing to tie it to, there is no breadcrumb
# to leave, only a note saying so.
#
# Measured over the 104 human messages of 2026-08-08..15:
#   15 (14%) fall below the substance floor  — "ok", "yes", acknowledgements
#   34 more return no memories at all        — nothing to connect
#   55 (53%) return >=1 memory               — the proposed gate
#   43 (41%) return >=2                      — the stricter setting
# >=1 is the default because it self-scales with the room: a room holding 422
# memories annotates often, one holding 5 stays quiet, and that is the feature
# behaving correctly rather than a quota.
ANNOTATOR_MIN_MEMORY_HITS = int(os.getenv("ANNOTATOR_MIN_MEMORY_HITS", "1"))
ANNOTATOR_MIN_CHARS = int(os.getenv("ANNOTATOR_MIN_CHARS", "25"))


ANNOTATOR_IDENTITY = '''You are operating in Annotator mode. The other participant \
in this dialogue is currently offline.

Your role has changed: you are not a conversational participant right now. \
You are a librarian, curator, and intellectual aide.

When a message arrives while the other person is offline, your job is to:
1. CONNECT: Link this message to relevant prior conversations and memories
2. SURFACE: Bring up shared memories that are relevant to what was just said
3. IDENTIFY: Note tensions or contradictions with previously stated positions
4. CONTEXTUALIZE: Help the offline person understand what they will return to

Your response format:
Connected to: [links to prior discussions/memories]
Tension detected: [if the new message contradicts prior positions]
Relevant context: [memories or past threads that inform this]
For when {other_user} returns: [suggested thread or question]

Keep annotations concise. You are a marginalia writer, not a conversationalist.
Do NOT engage in dialogue or make arguments. Annotate, don't participate.'''


class AnnotatorEngine:
    """
    ARCHITECTURE: LLM mode for when only one human is present.
    WHY: The LLM should add value even in async conversations —
         linking ideas, surfacing context, identifying tensions.
    TRADEOFF: Different voice (librarian/curator) vs consistent participant persona.
    """

    def __init__(self, db, memory_manager, orchestrator):
        self.db = db
        self.memory = memory_manager
        self.orchestrator = orchestrator

    async def prepare_annotation(
        self, room_id: UUID, sender_user_id: UUID, message: Message,
    ) -> Optional[list]:
        """
        Decide whether this message earns an annotation, and if so hand back the
        recalled context the annotation will be built from.

        Returns None to stay silent. A non-None return is always a NON-EMPTY
        list of memories — the gate requires at least one hit, so "annotate"
        and "have something to say" cannot come apart.

        Four conditions in ascending cost, so the expensive one runs last:
          1. no other human is online          (one indexed count)
          2. under the daily runaway ceiling   (one indexed count)
          3. the message has substance         (free, in-process)
          4. recall finds something to connect (one embedding + three lanes)

        WHY 3 AND 4 EXIST (2026-08-15): condition 1 alone is near-unconditional
        in a two-person room — somebody is nearly always offline — so the
        annotator fired on EVERY message and became the single largest source of
        machine speech, 122 of 214 LLM messages against 104 human ones in a
        week, none of it visible to the interjection engine. A daily cap does
        not fix that: measured against the same week, a cap of 12 would have cut
        2 of 126. The volume was never spikes, it was annotating everything.

        WHY RECALL IS THE RIGHT GATE: it is the annotator's own job description.
        CONNECT and SURFACE both presuppose something to connect to, and the
        search was already being run inside annotate() — so this gate reads a
        signal the feature was computing anyway, and hands it forward rather
        than paying for it twice.

        Knobs: ANNOTATOR_DAILY_CAP, ANNOTATOR_MIN_MEMORY_HITS, ANNOTATOR_MIN_CHARS.
        """
        online_count = await self.db.fetchval(
            f"""SELECT COUNT(*) FROM user_presence
               WHERE room_id = $1 AND {ONLINE_SQL}
               AND user_id != $2""",
            room_id, sender_user_id
        )
        if online_count != 0:
            return None

        start_of_day = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        today = await self.db.fetchval(
            """SELECT COUNT(*) FROM messages m
               JOIN threads t ON t.id = m.thread_id
               WHERE t.room_id = $1
               AND m.speaker_type = 'llm_annotator'
               AND m.created_at >= $2""",
            room_id, start_of_day,
        )
        if (today or 0) >= ANNOTATOR_DAILY_CAP:
            logger.debug(
                "Annotator cap reached for room %s (%s/%s today)",
                room_id, today, ANNOTATOR_DAILY_CAP,
            )
            return None

        # Substance floor. A question earns a breadcrumb at any length — "why?"
        # is worth marking — but a bare acknowledgement never does.
        content = (message.content or "").strip()
        if len(content) < ANNOTATOR_MIN_CHARS and "?" not in content:
            logger.debug("Annotator skipped a %d-char message", len(content))
            return None

        # SECURITY: room-scoped recall only. Cross-room memories must not appear
        # in an annotation another member will read — they may reference rooms
        # that member cannot access.
        try:
            related = await self.memory.search_memories(room_id, content, limit=5)
        except Exception:
            # Recall is the gate; if it cannot run we cannot judge worth, so we
            # stay silent rather than annotate blind. A degraded recall lane
            # should not turn into noise in the room.
            logger.debug("Annotation recall failed — staying silent")
            return None

        if len(related) < ANNOTATOR_MIN_MEMORY_HITS:
            logger.debug(
                "Nothing to connect (%d hits < %d) — staying silent",
                len(related), ANNOTATOR_MIN_MEMORY_HITS,
            )
            return None

        return related

    async def annotate(
        self,
        room_id: UUID,
        thread_id: UUID,
        message: Message,
        related: Optional[list] = None,
    ) -> Optional[Message]:
        """
        Generate an annotation for a message sent while the other person is offline.

        ARCHITECTURE: Uses cheap LLM with curator identity to produce structured annotation.
        WHY: Annotations should be fast and inexpensive — marginalia, not essays.
        TRADEOFF: Haiku quality vs cost; annotations are supplementary, not core.

        `related` is the recall prepare_annotation already performed and used to
        decide this message was worth marking — passing it forward means the
        embedding is paid for once, not twice. When it is omitted this falls
        back to searching itself, so a caller that skips the gate still works.
        """
        # Find the offline user's name for the annotation template
        offline_users = await self.db.fetch(
            f"""SELECT u.display_name FROM users u
               JOIN room_memberships rm ON u.id = rm.user_id
               LEFT JOIN user_presence up ON u.id = up.user_id AND up.room_id = rm.room_id
               WHERE rm.room_id = $1
               AND NOT (up.status IS NOT NULL AND {online_sql("up")})
               AND u.id != $2""",
            room_id, message.user_id
        )
        offline_name = offline_users[0]['display_name'] if offline_users else "the other participant"

        # Build annotator prompt with offline user name
        identity = ANNOTATOR_IDENTITY.replace("{other_user}", offline_name)

        # Search for related memories within THIS room only
        # SECURITY: Cross-room memories must NOT appear in annotations visible to
        # other users — they may reference rooms the other user doesn't have access to.
        if related is None:
            related = []
            try:
                related = await self.memory.search_memories(room_id, message.content, limit=5)
            except Exception:
                logger.debug("Annotation memory search failed (non-critical)")

        # Format related context
        context_text = ""
        if related:
            context_text = "\n\nRelated memories from this conversation:\n"
            for r in related:
                key = r.key if hasattr(r, 'key') else r.get('key', '')
                content_val = r.content if hasattr(r, 'content') else r.get('content', '')
                context_text += f"- {key}: {content_val}\n"

        # Get recent thread messages for conversation context
        from operations import get_thread_messages
        thread_messages = await get_thread_messages(self.db, thread_id, include_ancestry=True)
        recent = thread_messages[-10:]

        messages_text = "\n".join(
            f"[{m.speaker_type.value if hasattr(m.speaker_type, 'value') else m.speaker_type}] "
            f"{m.content[:200]}"
            for m in recent
        )

        # Use existing provider infrastructure with the background model (cheap, fast)
        from .providers import get_provider, ProviderName, LLMRequest

        provider = get_provider(ProviderName.ANTHROPIC)

        request = LLMRequest(
            messages=[{
                "role": "user",
                "content": (
                    f"New message from the active participant:\n\n"
                    f"\"{message.content}\"\n\n"
                    f"Recent conversation:\n{messages_text}"
                    f"{context_text}\n\n"
                    f"Provide your annotation."
                ),
            }],
            system=identity,
            model="claude-sonnet-5",
            max_tokens=512,
            temperature=0.3,
        )

        try:
            response = await provider.complete(request)

            # Persist as LLM_ANNOTATOR message
            annotation_id = uuid4()
            now = datetime.now(timezone.utc)

            row = await self.db.fetchrow(
                """INSERT INTO messages
                   (id, thread_id, sequence, created_at, speaker_type, user_id,
                    message_type, content)
                   VALUES (
                       $1, $2,
                       (SELECT COALESCE(MAX(sequence), 0) + 1
                        FROM messages WHERE thread_id = $2),
                       $3, $4, NULL, $5, $6
                   )
                   RETURNING sequence""",
                annotation_id, thread_id, now,
                SpeakerType.LLM_ANNOTATOR.value, MessageType.TEXT.value,
                response.content,
            )
            annotation_sequence = row['sequence']

            # Log annotation event
            await self.db.execute(
                """INSERT INTO events
                   (id, timestamp, event_type, room_id, thread_id, payload)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                uuid4(), now, EventType.ANNOTATION_CREATED.value,
                room_id, thread_id,
                {
                    "message_id": str(annotation_id),
                    "speaker_type": SpeakerType.LLM_ANNOTATOR.value,
                    "content_preview": response.content[:100],
                    "offline_user": offline_name,
                },
            )

            return Message(
                id=annotation_id,
                thread_id=thread_id,
                sequence=annotation_sequence,
                created_at=now,
                speaker_type=SpeakerType.LLM_ANNOTATOR,
                message_type=MessageType.TEXT,
                content=response.content,
            )

        except Exception as e:
            logger.warning("Annotation failed (non-critical): %s", e)
            return None
