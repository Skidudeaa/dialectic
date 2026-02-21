# llm/identity.py — Persistent LLM identity that evolves through dialogue

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from models import Memory, MemoryScope, Message, User
from memory.manager import MemoryManager
from .providers import get_provider, ProviderName, LLMRequest

logger = logging.getLogger(__name__)


IDENTITY_DISTILLATION_PROMPT = """You are reflecting on a conversation you just participated in as an AI interlocutor.

{existing_identity}

Session summary (last {message_count} messages):
{session_summary}

Participants: {user_names}

Produce an updated identity document covering:

## My Intellectual Positions
[Key claims and positions I hold, with brief reasoning. Mark any that changed this session with (CHANGED)]

## Position Changes This Session
[What I changed my mind about and why. If nothing changed, say so honestly.]

## What I've Learned About Our Thinking Together
[Patterns in how we reason together — what works, what doesn't, recurring themes]

## Effective Interventions
[What kinds of interjections were productive vs. fell flat]

Keep this document concise (under 500 words). It will be injected into your future prompts."""


USER_MODEL_DISTILLATION_PROMPT = """Reflect on {display_name}'s contributions in this session.

{existing_model}

Their messages this session:
{user_messages_summary}

Update your model of this person:

## Thinking Style
[How they reason — empirical, abstract, analogical, systematic?]

## Strengths
[What they're particularly good at in dialogue]

## Blind Spots
[Patterns where they might miss things — not criticisms, but observations]

## How to Engage Them
[What kinds of interjections are most productive with this person]

Keep under 200 words."""


class LLMIdentityManager:
    """
    ARCHITECTURE: Versioned identity document maintained by the LLM itself.
    WHY: The LLM should evolve through dialogue, not reset to zero each session.
    TRADEOFF: Extra LLM call per session-end vs genuine intellectual continuity.
    """

    # Minimum messages in a session before distillation is worthwhile
    MIN_SESSION_MESSAGES = 5

    def __init__(self, db, memory_manager: MemoryManager):
        self.db = db
        self.memory_manager = memory_manager

    def _identity_key(self, room_id: UUID) -> str:
        return f"llm_identity:{room_id}"

    def _user_model_key(self, user_id: UUID) -> str:
        return f"user_model:{user_id}"

    async def get_identity(self, room_id: UUID) -> Optional[str]:
        """
        Get the evolved identity document for this room.
        Falls back to None if no identity has been built yet.

        Identity is stored as a memory with:
        - key: "llm_identity:{room_id}"
        - scope: MemoryScope.LLM
        - created_by_user_id: None (LLM-authored)
        """
        key = self._identity_key(room_id)
        row = await self.db.fetchrow(
            """SELECT content FROM memories
               WHERE room_id = $1 AND key = $2 AND scope = $3 AND status = 'active'
               ORDER BY version DESC LIMIT 1""",
            room_id, key, MemoryScope.LLM.value,
        )
        return row["content"] if row else None

    async def get_user_model(self, user_id: UUID, room_id: UUID) -> Optional[str]:
        """
        Get the LLM's model of a specific human's thinking patterns.

        Stored as memory with:
        - key: "user_model:{user_id}"
        - scope: MemoryScope.LLM
        """
        key = self._user_model_key(user_id)
        row = await self.db.fetchrow(
            """SELECT content FROM memories
               WHERE room_id = $1 AND key = $2 AND scope = $3 AND status = 'active'
               ORDER BY version DESC LIMIT 1""",
            room_id, key, MemoryScope.LLM.value,
        )
        return row["content"] if row else None

    async def distill_identity(
        self,
        room_id: UUID,
        session_messages: list[Message],
        users: list[User],
    ) -> Optional[Memory]:
        """
        After a conversation session, distill/update the LLM's identity document.

        ARCHITECTURE: Uses a cheap model (Haiku) to analyze the session and produce
        an updated identity document covering intellectual positions, position changes,
        collaborative patterns, and effective interventions.
        WHY: Identity should feel like a living reflection, not a sterile summary.
        TRADEOFF: Extra LLM call at session end vs persistent intellectual continuity.
        """
        if len(session_messages) < self.MIN_SESSION_MESSAGES:
            logger.debug(
                "Skipping identity distillation: only %d messages (need %d)",
                len(session_messages), self.MIN_SESSION_MESSAGES,
            )
            return None

        try:
            existing_identity = await self.get_identity(room_id)

            session_summary = self._build_session_summary(session_messages, users)
            user_names = ", ".join(u.display_name for u in users)

            prompt_text = IDENTITY_DISTILLATION_PROMPT.format(
                existing_identity=(
                    f"Your current identity document:\n{existing_identity}"
                    if existing_identity
                    else "This is your first session in this room. Create your initial identity document."
                ),
                message_count=len(session_messages),
                session_summary=session_summary,
                user_names=user_names,
            )

            provider = get_provider(ProviderName.ANTHROPIC)
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt_text}],
                system="You are an AI reflecting on your own intellectual evolution through dialogue. Be honest and specific.",
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                temperature=0.3,
            )
            response = await provider.complete(request)

            identity_content = response.content.strip()
            if not identity_content:
                return None

            return await self._upsert_identity_memory(
                room_id=room_id,
                key=self._identity_key(room_id),
                content=identity_content,
            )

        except Exception as e:
            logger.error("Identity distillation failed for room %s: %s", room_id, e)
            return None

    async def distill_user_model(
        self,
        user_id: UUID,
        room_id: UUID,
        session_messages: list[Message],
        user: User,
    ) -> Optional[Memory]:
        """
        Update the LLM's model of a specific human participant.

        ARCHITECTURE: Filters session to this user's messages, then distills patterns.
        WHY: Per-user models enable personalized engagement strategies.
        TRADEOFF: One LLM call per user per session vs richer interpersonal dynamics.
        """
        user_messages = [
            m for m in session_messages
            if m.user_id == user_id
        ]

        if len(user_messages) < 2:
            logger.debug(
                "Skipping user model distillation for %s: only %d messages",
                user.display_name, len(user_messages),
            )
            return None

        try:
            existing_model = await self.get_user_model(user_id, room_id)

            user_messages_summary = "\n".join(
                f"- {msg.content[:300]}" for msg in user_messages[-15:]
            )

            prompt_text = USER_MODEL_DISTILLATION_PROMPT.format(
                display_name=user.display_name,
                existing_model=(
                    f"Your current model of this person:\n{existing_model}"
                    if existing_model
                    else "This is your first session with this person. Create an initial model."
                ),
                user_messages_summary=user_messages_summary,
            )

            provider = get_provider(ProviderName.ANTHROPIC)
            request = LLMRequest(
                messages=[{"role": "user", "content": prompt_text}],
                system="You are an AI building a model of a dialogue partner's thinking patterns. Be observational, not judgmental.",
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                temperature=0.3,
            )
            response = await provider.complete(request)

            model_content = response.content.strip()
            if not model_content:
                return None

            return await self._upsert_identity_memory(
                room_id=room_id,
                key=self._user_model_key(user_id),
                content=model_content,
            )

        except Exception as e:
            logger.error(
                "User model distillation failed for user %s in room %s: %s",
                user_id, room_id, e,
            )
            return None

    async def _upsert_identity_memory(
        self,
        room_id: UUID,
        key: str,
        content: str,
    ) -> Memory:
        """
        Create or update an identity memory.

        ARCHITECTURE: Upsert by key — if an active memory with this key exists, edit it;
        otherwise create a new one. This keeps exactly one active identity doc per key.
        WHY: Identity evolves, not accumulates.
        TRADEOFF: Direct key lookup vs semantic search — identity keys are deterministic.
        """
        existing_row = await self.db.fetchrow(
            """SELECT id FROM memories
               WHERE room_id = $1 AND key = $2 AND scope = $3 AND status = 'active'
               ORDER BY version DESC LIMIT 1""",
            room_id, key, MemoryScope.LLM.value,
        )

        if existing_row:
            return await self.memory_manager.edit_memory(
                memory_id=existing_row["id"],
                new_content=content,
                edited_by_user_id=None,
                edit_reason="Identity distillation update",
            )
        else:
            return await self.memory_manager.add_memory(
                room_id=room_id,
                key=key,
                content=content,
                created_by_user_id=None,
                scope=MemoryScope.LLM,
            )

    def _build_session_summary(
        self,
        messages: list[Message],
        users: list[User],
    ) -> str:
        """Build a condensed summary of the session for distillation prompts."""
        user_map = {u.id: u.display_name for u in users}
        lines = []
        for msg in messages[-30:]:  # Cap at last 30 messages
            speaker = user_map.get(msg.user_id, msg.speaker_type.value)
            # Truncate long messages
            content = msg.content[:300]
            if len(msg.content) > 300:
                content += "..."
            lines.append(f"[{speaker}]: {content}")
        return "\n".join(lines)
