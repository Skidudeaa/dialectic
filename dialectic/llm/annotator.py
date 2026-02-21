# llm/annotator.py — Async dialogue annotator engine

"""
ARCHITECTURE: LLM mode for when only one human is present.
WHY: The LLM should add value even in async conversations —
     linking ideas, surfacing context, identifying tensions.
TRADEOFF: Different voice (librarian/curator) vs consistent participant persona.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from models import (
    Message, Event, EventType, SpeakerType, MessageType,
)

logger = logging.getLogger(__name__)


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

    async def should_annotate(self, room_id: UUID, sender_user_id: UUID) -> bool:
        """
        Check if annotator mode should activate.
        True when: only one human is online in the room.
        """
        online_count = await self.db.fetchval(
            """SELECT COUNT(*) FROM user_presence
               WHERE room_id = $1 AND status = 'online'
               AND user_id != $2""",
            room_id, sender_user_id
        )
        return online_count == 0

    async def annotate(
        self,
        room_id: UUID,
        thread_id: UUID,
        message: Message,
    ) -> Optional[Message]:
        """
        Generate an annotation for a message sent while the other person is offline.

        ARCHITECTURE: Uses cheap LLM with curator identity to produce structured annotation.
        WHY: Annotations should be fast and inexpensive — marginalia, not essays.
        TRADEOFF: Haiku quality vs cost; annotations are supplementary, not core.
        """
        # Find the offline user's name for the annotation template
        offline_users = await self.db.fetch(
            """SELECT u.display_name FROM users u
               JOIN room_memberships rm ON u.id = rm.user_id
               LEFT JOIN user_presence up ON u.id = up.user_id AND up.room_id = rm.room_id
               WHERE rm.room_id = $1
               AND (up.status IS NULL OR up.status != 'online')
               AND u.id != $2""",
            room_id, message.user_id
        )
        offline_name = offline_users[0]['display_name'] if offline_users else "the other participant"

        # Build annotator prompt with offline user name
        identity = ANNOTATOR_IDENTITY.replace("{other_user}", offline_name)

        # Search for related memories within THIS room only
        # SECURITY: Cross-room memories must NOT appear in annotations visible to
        # other users — they may reference rooms the other user doesn't have access to.
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

        # Use existing provider infrastructure with Haiku (cheap, fast)
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
            model="claude-haiku-4-5-20251001",
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
