# llm/multi_model.py — Multi-model persona coordination

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from models import (
    RoomPersona, Message, Event, EventType,
    SpeakerType, MessageType, MessageCreatedPayload,
)
from .providers import ProviderName, LLMRequest, get_provider

logger = logging.getLogger(__name__)


class MultiModelCoordinator:
    """
    ARCHITECTURE: Turn-taking coordinator for multiple LLM personas per room.
    WHY: Different models/personalities create richer dialectic (Opus=deep, Haiku=quick, GPT=contrarian).
    TRADEOFF: More LLM calls per conversation vs diverse perspectives.
    """

    MAX_LLM_CONSECUTIVE = 2  # Max LLM turns before requiring human input
    COOLDOWN_SECONDS = 30    # Min time between same persona's responses

    def __init__(self, db):
        self.db = db

    async def get_active_personas(self, room_id: UUID) -> list[RoomPersona]:
        """Get all active personas for a room, ordered by display_order."""
        rows = await self.db.fetch(
            """SELECT * FROM room_personas
               WHERE room_id = $1 AND is_active = true
               ORDER BY display_order, created_at""",
            room_id,
        )
        return [RoomPersona(**dict(row)) for row in rows]

    async def should_persona_speak(
        self,
        persona: RoomPersona,
        messages: list[Message],
        trigger_content: str,
    ) -> bool:
        """
        Evaluate whether a specific persona should respond.
        Checks: trigger strategy match, consecutive LLM limit, cooldown.

        ARCHITECTURE: Guard-first evaluation — cheap checks before expensive ones.
        WHY: Prevents infinite LLM loops and respects human turn-taking.
        TRADEOFF: Conservative guards may suppress valid interjections.
        """
        # Guard: consecutive LLM turn limit
        consecutive = 0
        for msg in reversed(messages):
            if msg.speaker_type == SpeakerType.HUMAN:
                break
            consecutive += 1
        if consecutive >= self.MAX_LLM_CONSECUTIVE:
            return False

        # Guard: cooldown — same persona can't speak too frequently
        now = datetime.now(timezone.utc)
        for msg in reversed(messages[-10:]):
            if (
                msg.speaker_type == SpeakerType.LLM_PERSONA
                and hasattr(msg, 'persona_id')
                and msg.persona_id == persona.id
            ):
                elapsed = (now - msg.created_at).total_seconds()
                if elapsed < self.COOLDOWN_SECONDS:
                    return False
                break

        # Check trigger strategy
        strategy = persona.trigger_strategy

        if strategy == "on_mention":
            return f"@{persona.name.lower()}" in trigger_content.lower()

        elif strategy == "after_primary":
            return bool(
                messages
                and messages[-1].speaker_type == SpeakerType.LLM_PRIMARY
            )

        elif strategy == "on_disagreement":
            return self._detect_disagreement(messages[-3:])

        elif strategy == "periodic":
            period = persona.personality.get("period", 5)
            human_count = sum(
                1 for m in messages if m.speaker_type == SpeakerType.HUMAN
            )
            return human_count > 0 and human_count % period == 0

        return False

    def _detect_disagreement(self, recent: list[Message]) -> bool:
        """
        Simple disagreement detection from recent messages.

        ARCHITECTURE: Keyword heuristic over recent human messages.
        WHY: Lightweight trigger — no LLM call needed for detection.
        TRADEOFF: False positives on polite disagreement vs missing subtle tension.
        """
        markers = ["disagree", "but ", "however", "no,", "actually", "wrong"]
        for msg in recent:
            if msg.speaker_type == SpeakerType.HUMAN:
                lower = msg.content.lower()
                if any(w in lower for w in markers):
                    return True
        return False

    async def get_next_persona(
        self,
        room_id: UUID,
        messages: list[Message],
        trigger_content: str,
    ) -> Optional[RoomPersona]:
        """
        Determine which persona (if any) should speak next.
        Returns the highest-priority matching persona, or None.

        ARCHITECTURE: First-match wins across display_order-sorted personas.
        WHY: Deterministic priority prevents multiple personas fighting to speak.
        TRADEOFF: Only one persona per turn; could extend to multi-persona rounds later.
        """
        personas = await self.get_active_personas(room_id)
        for persona in personas:
            if await self.should_persona_speak(persona, messages, trigger_content):
                return persona
        return None

    async def generate_persona_response(
        self,
        persona: RoomPersona,
        messages: list[Message],
        memories: list,
    ) -> Optional[str]:
        """
        Generate a response from a specific persona using its configured provider/model.

        ARCHITECTURE: Uses persona's own identity_prompt as system, not the room-level prompt.
        WHY: Each persona has a distinct voice, model, and perspective.
        TRADEOFF: No shared prompt layers (room rules, etc.) — persona is fully self-contained.
        """
        try:
            provider = get_provider(ProviderName(persona.provider))
        except (KeyError, EnvironmentError) as e:
            logger.warning(
                "Provider %s unavailable for persona %s: %s",
                persona.provider, persona.name, e,
            )
            return None

        # Build conversation messages for the persona
        formatted_messages = []
        for msg in messages:
            if msg.is_deleted:
                continue
            if msg.speaker_type == SpeakerType.HUMAN:
                formatted_messages.append({
                    "role": "user",
                    "content": msg.content,
                })
            elif msg.speaker_type in (
                SpeakerType.LLM_PRIMARY,
                SpeakerType.LLM_PROVOKER,
                SpeakerType.LLM_PERSONA,
                SpeakerType.LLM_ANNOTATOR,
            ):
                formatted_messages.append({
                    "role": "assistant",
                    "content": msg.content,
                })
            elif msg.speaker_type == SpeakerType.SYSTEM:
                formatted_messages.append({
                    "role": "user",
                    "content": f"[SYSTEM] {msg.content}",
                })

        # Build memory context
        memory_section = ""
        if memories:
            lines = [f"- {m.key}: {m.content}" for m in memories if hasattr(m, 'key')]
            if lines:
                memory_section = "\n\n## Shared Memory\n" + "\n".join(lines)

        system_prompt = persona.identity_prompt + memory_section

        temperature = persona.personality.get("temperature", 1.0)
        max_tokens = persona.personality.get("max_tokens", 2048)

        request = LLMRequest(
            messages=formatted_messages,
            system=system_prompt,
            model=persona.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            response = await provider.complete(request)
            return response.content
        except Exception as e:
            logger.error(
                "Persona %s response failed: %s", persona.name, e,
            )
            return None

    async def persist_persona_response(
        self,
        persona: RoomPersona,
        thread_id: UUID,
        room_id: UUID,
        content: str,
    ) -> Message:
        """
        Persist a persona response as a message and log the event.

        ARCHITECTURE: Mirrors orchestrator._persist_response but with persona attribution.
        WHY: Persona messages are first-class messages in the event log.
        TRADEOFF: Some duplication with orchestrator, but keeps persona logic self-contained.
        """
        now = datetime.now(timezone.utc)
        message_id = uuid4()

        # Detect message type
        message_type = self._detect_message_type(content)

        row = await self.db.fetchrow(
            """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content, model_used, persona_id)
               VALUES (
                   $1, $2,
                   (SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = $2),
                   $3, $4, $5, $6, $7, $8, $9
               )
               RETURNING sequence""",
            message_id, thread_id, now,
            SpeakerType.LLM_PERSONA.value, None, message_type.value,
            content, persona.model, persona.id,
        )
        sequence = row["sequence"]

        prompt_hash = hashlib.sha256(
            persona.identity_prompt.encode()
        ).hexdigest()[:16]

        message = Message(
            id=message_id,
            thread_id=thread_id,
            sequence=sequence,
            created_at=now,
            speaker_type=SpeakerType.LLM_PERSONA,
            user_id=None,
            message_type=message_type,
            content=content,
            model_used=persona.model,
            prompt_hash=prompt_hash,
        )

        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=EventType.MESSAGE_CREATED,
            room_id=room_id,
            thread_id=thread_id,
            user_id=None,
            payload=MessageCreatedPayload(
                message_id=message_id,
                sequence=sequence,
                speaker_type=SpeakerType.LLM_PERSONA,
                user_id=None,
                message_type=message_type,
                content=content,
                model_used=persona.model,
                prompt_hash=prompt_hash,
            ).model_dump(),
        )

        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            event.id, event.timestamp, event.event_type.value,
            event.room_id, event.thread_id, event.user_id, event.payload,
        )

        return message

    def _detect_message_type(self, content: str) -> MessageType:
        """Simple heuristic to classify persona response type."""
        content_lower = content.lower()
        if content_lower.startswith(("[claim]", "i claim", "i assert")):
            return MessageType.CLAIM
        if content.rstrip().endswith("?"):
            return MessageType.QUESTION
        if any(p in content_lower for p in ["counterexample", "but consider", "what about"]):
            return MessageType.COUNTEREXAMPLE
        return MessageType.TEXT
