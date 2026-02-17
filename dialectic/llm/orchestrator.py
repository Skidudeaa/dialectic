# llm/orchestrator.py — Main orchestration entry point

from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4
import hashlib
import logging
import sys
import pathlib

_package_root = str(pathlib.Path(__file__).resolve().parent.parent)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

from models import (
    Room, User, Thread, Message, Memory, Event, EventType,
    SpeakerType, MessageType, MessageCreatedPayload
)
from .providers import ProviderName, LLMRequest, get_provider
from .router import ModelRouter, RoutingResult
from .heuristics import InterjectionEngine, InterjectionDecision
from .prompts import PromptBuilder, AssembledPrompt
from .context import assemble_context

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationResult:
    """
    ARCHITECTURE: Full trace of orchestration decision + execution.
    WHY: Observability for debugging, analytics, memory attribution.
    """
    triggered: bool
    decision: InterjectionDecision
    response: Optional[Message]
    routing: Optional[RoutingResult]
    prompt_used: Optional[AssembledPrompt]


class LLMOrchestrator:
    """
    ARCHITECTURE: Central coordinator for all LLM interactions.
    WHY: Single entry point simplifies state management and logging.
    TRADEOFF: God object risk vs coordination clarity.
    """

    def __init__(self, db):
        self.db = db
        self.heuristics = InterjectionEngine()
        self.prompt_builder = PromptBuilder()
        self._routers: dict[UUID, ModelRouter] = {}

    def _get_router(self, room: Room) -> ModelRouter:
        """Get or create router for room."""
        if room.id not in self._routers:
            self._routers[room.id] = ModelRouter(
                primary_provider=ProviderName(room.primary_provider),
                fallback_provider=ProviderName(room.fallback_provider),
                primary_model=room.primary_model,
                fallback_model=room.provoker_model,
            )
        return self._routers[room.id]

    async def on_message(
        self,
        room: Room,
        thread: Thread,
        users: list[User],
        messages: list[Message],
        memories: list[Memory],
        mentioned: bool = False,
        semantic_novelty: Optional[float] = None,
    ) -> OrchestrationResult:
        """Called after each human message. Decides and executes LLM response."""

        decision = self.heuristics.decide(
            messages=messages,
            mentioned=mentioned,
            semantic_novelty=semantic_novelty,
        )

        if not decision.should_interject:
            logger.debug(f"No interjection: {decision.reason}")
            return OrchestrationResult(
                triggered=False,
                decision=decision,
                response=None,
                routing=None,
                prompt_used=None,
            )

        logger.info(f"Interjection triggered: {decision.reason}, provoker={decision.use_provoker}")

        prompt = self.prompt_builder.build(
            room=room,
            users=users,
            messages=messages,
            memories=memories,
            is_provoker=decision.use_provoker,
        )

        router = self._get_router(room)

        request = LLMRequest(
            messages=prompt.messages,
            system=prompt.system,
            model=room.provoker_model if decision.use_provoker else room.primary_model,
        )

        routing = await router.route(request)

        if not routing.success:
            error_message = await self._emit_system_error(thread, routing)
            return OrchestrationResult(
                triggered=True,
                decision=decision,
                response=error_message,
                routing=routing,
                prompt_used=prompt,
            )

        response_message = await self._persist_response(
            thread=thread,
            content=routing.response.content,
            speaker_type=SpeakerType.LLM_PROVOKER if decision.use_provoker else SpeakerType.LLM_PRIMARY,
            model_used=routing.response.model,
            prompt_hash=routing.prompt_hash,
            token_count=routing.response.input_tokens + routing.response.output_tokens,
        )

        return OrchestrationResult(
            triggered=True,
            decision=decision,
            response=response_message,
            routing=routing,
            prompt_used=prompt,
        )

    async def force_response(
        self,
        room: Room,
        thread: Thread,
        users: list[User],
        messages: list[Message],
        memories: list[Memory],
        use_provoker: bool = False,
    ) -> OrchestrationResult:
        """Force LLM response regardless of heuristics."""
        decision = InterjectionDecision(
            should_interject=True,
            reason="forced",
            confidence=1.0,
            use_provoker=use_provoker,
        )

        prompt = self.prompt_builder.build(
            room=room,
            users=users,
            messages=messages,
            memories=memories,
            is_provoker=use_provoker,
        )

        router = self._get_router(room)
        request = LLMRequest(
            messages=prompt.messages,
            system=prompt.system,
            model=room.provoker_model if use_provoker else room.primary_model,
        )

        routing = await router.route(request)

        if not routing.success:
            error_message = await self._emit_system_error(thread, routing)
            return OrchestrationResult(
                triggered=True,
                decision=decision,
                response=error_message,
                routing=routing,
                prompt_used=prompt,
            )

        response_message = await self._persist_response(
            thread=thread,
            content=routing.response.content,
            speaker_type=SpeakerType.LLM_PROVOKER if use_provoker else SpeakerType.LLM_PRIMARY,
            model_used=routing.response.model,
            prompt_hash=routing.prompt_hash,
            token_count=routing.response.input_tokens + routing.response.output_tokens,
        )

        return OrchestrationResult(
            triggered=True,
            decision=decision,
            response=response_message,
            routing=routing,
            prompt_used=prompt,
        )

    async def stream_response(
        self,
        room: Room,
        thread: Thread,
        users: list[User],
        messages: list[Message],
        memories: list[Memory],
        use_provoker: bool = False,
    ) -> AsyncIterator[tuple[str, dict]]:
        """
        Stream LLM response token-by-token.

        Yields tuples of (event_type, data) where event_type is:
        - "thinking": Processing started
        - "streaming": Token received {"token": str, "index": int}
        - "done": Complete {"message_id": str, "content": str, "model_used": str, "truncated": bool}
        - "error": Failed {"error": str, "partial_content": str}
        """
        # Signal processing started
        yield ("thinking", {})

        # Apply context truncation
        context = assemble_context(messages, thread)
        truncated_messages = context.messages

        logger.info(
            f"Context assembled: {context.included_count}/{context.original_count} messages, "
            f"truncated={context.truncated}, tokens={context.total_tokens}"
        )

        # Build prompt with truncated messages
        prompt = self.prompt_builder.build(
            room=room,
            users=users,
            messages=truncated_messages,
            memories=memories,
            is_provoker=use_provoker,
        )

        # Create request for streaming
        model = room.provoker_model if use_provoker else room.primary_model
        request = LLMRequest(
            messages=prompt.messages,
            system=prompt.system,
            model=model,
            stream=True,
        )

        # Get provider directly for streaming
        provider_name = ProviderName(room.primary_provider)
        provider = get_provider(provider_name)

        # Track accumulated content
        accumulated_content = ""
        token_index = 0

        try:
            async for token in provider.stream(request):
                accumulated_content += token
                yield ("streaming", {"token": token, "index": token_index})
                token_index += 1

            # Persist the complete message
            speaker_type = SpeakerType.LLM_PROVOKER if use_provoker else SpeakerType.LLM_PRIMARY
            prompt_hash = hashlib.sha256(prompt.system.encode()).hexdigest()[:16]

            response_message = await self._persist_response(
                thread=thread,
                content=accumulated_content,
                speaker_type=speaker_type,
                model_used=model,
                prompt_hash=prompt_hash,
                token_count=0,  # Not available from streaming
            )

            yield ("done", {
                "message_id": str(response_message.id),
                "content": accumulated_content,
                "model_used": model,
                "truncated": context.truncated,
            })

        except Exception as e:
            logger.exception("Streaming error")
            yield ("error", {
                "error": str(e),
                "partial_content": accumulated_content,
            })

    async def _persist_response(
        self,
        thread: Thread,
        content: str,
        speaker_type: SpeakerType,
        model_used: str,
        prompt_hash: str,
        token_count: int,
    ) -> Message:
        """Create Message record and log event."""

        now = datetime.utcnow()
        message_id = uuid4()
        message_type = self._detect_message_type(content)

        # Atomic INSERT with inline sequence calculation to prevent TOCTOU race
        row = await self.db.fetchrow(
            """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content, model_used, prompt_hash, token_count)
               VALUES (
                   $1, $2,
                   (SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = $2),
                   $3, $4, $5, $6, $7, $8, $9, $10
               )
               RETURNING sequence""",
            message_id, thread.id, now,
            speaker_type.value, None, message_type.value,
            content, model_used, prompt_hash, token_count
        )
        sequence = row['sequence']

        message = Message(
            id=message_id,
            thread_id=thread.id,
            sequence=sequence,
            created_at=now,
            speaker_type=speaker_type,
            user_id=None,
            message_type=message_type,
            content=content,
            model_used=model_used,
            prompt_hash=prompt_hash,
            token_count=token_count,
        )

        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=EventType.MESSAGE_CREATED,
            room_id=thread.room_id,
            thread_id=thread.id,
            user_id=None,
            payload=MessageCreatedPayload(
                message_id=message_id,
                sequence=sequence,
                speaker_type=speaker_type,
                user_id=None,
                message_type=message_type,
                content=content,
                model_used=model_used,
                prompt_hash=prompt_hash,
                token_count=token_count,
            ).model_dump()
        )

        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            event.id, event.timestamp, event.event_type.value,
            event.room_id, event.thread_id, event.user_id, event.payload
        )

        return message

    async def _emit_system_error(self, thread: Thread, routing: RoutingResult) -> Message:
        """Create system message indicating LLM failure."""

        attempt_summary = ", ".join(
            f"{a['provider']}/{a['model']}" for a in routing.attempts
        )
        content = f"[All LLM providers failed after {len(routing.attempts)} attempts: {attempt_summary}]"

        return await self._persist_response(
            thread=thread,
            content=content,
            speaker_type=SpeakerType.SYSTEM,
            model_used="",
            prompt_hash=routing.prompt_hash,
            token_count=0,
        )

    def _detect_message_type(self, content: str) -> MessageType:
        """Simple heuristic to classify LLM response type."""
        content_lower = content.lower()

        if content_lower.startswith(("[claim]", "i claim", "i assert")):
            return MessageType.CLAIM
        if content.rstrip().endswith("?"):
            return MessageType.QUESTION
        if content_lower.startswith(("[definition]", "by", "define:")):
            return MessageType.DEFINITION
        if any(phrase in content_lower for phrase in ["counterexample", "but consider", "what about"]):
            return MessageType.COUNTEREXAMPLE

        return MessageType.TEXT
