# llm/orchestrator.py — Main orchestration entry point

import asyncio
import asyncpg
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4
import hashlib
import logging
import os

import re

from models import (
    Room, User, Thread, Message, Memory, Event, EventType,
    SpeakerType, MessageType, MessageCreatedPayload,
    ProtocolState,
)
from .providers import ProviderName, LLMRequest
from .router import ModelRouter, RoutingResult
from .heuristics import InterjectionEngine, InterjectionDecision
from .participation_fsm import ParticipationFSM, decision_event
from .prompts import PromptBuilder, AssembledPrompt
from .context import assemble_context
from .cross_session_context import CrossSessionContextBuilder, CrossSessionContext
from .self_memory import LLMSelfMemory
from .self_model import SelfModel
from .identity import LLMIdentityManager
from .tool_loop import ToolLoop
from .tools import ToolRegistry, build_registry
from .vision import count_images, load_message_images
from memory.cross_session import CrossSessionMemoryManager
from memory.manager import MemoryManager

logger = logging.getLogger(__name__)


_PHASE_COMPLETE_RE = re.compile(r"\[PHASE_COMPLETE:\s*(.+?)\]")

# Kill switch. Unset means ON — the feature ships enabled, and the env var
# exists so the room can be put back on the plain streaming path in one
# restart if the tool channel misbehaves live.
_TOOLS_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def tools_enabled() -> bool:
    """Whether the LLM participant may call tools at all, per environment."""
    return os.getenv("DIALECTIC_TOOLS_ENABLED", "").strip().lower() not in _TOOLS_OFF_VALUES


def _hoisted_prediction_proposal(calls: list[dict]) -> Optional[dict]:
    """The draft_prediction proposal from a tool trace, if this turn made one.

    WHY hoist it out of the trace: the Accept button renders off
    metadata.proposal, and asking the client AND the relay endpoint to each
    dig through tools.calls for the one entry carrying prediction-draft
    provenance would duplicate this exact scan in two places. The proposal
    body is the tool's input — the executor already validated it, or ok
    would be False and the entry would be skipped here. First draft wins: a
    turn that revises its own draft is rare, and the humans can accept the
    first and ignore the rest.
    """
    for entry in calls:
        if not entry.get("ok"):
            continue
        if (entry.get("provenance") or {}).get("kind") != "prediction_draft":
            continue
        proposal = dict(entry.get("input") or {})
        proposal["accepted"] = False
        return proposal
    return None


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
    phase_complete_signal: Optional[str] = None


class LLMOrchestrator:
    """
    ARCHITECTURE: Central coordinator for all LLM interactions.
    WHY: Single entry point simplifies state management and logging.
    TRADEOFF: God object risk vs coordination clarity.
    """

    def __init__(self, db, db_pool=None):
        # WHY: `db` is typically a pooled connection scoped to one WebSocket
        # message. Background tasks (self-memory extraction, delayed
        # effectiveness measurement) outlive that scope, so they must acquire
        # fresh connections from `db_pool` — using `db` after release is a
        # use-after-release bug that made those tasks fail silently.
        self.db = db
        self.db_pool = db_pool
        self.heuristics = InterjectionEngine()
        self.prompt_builder = PromptBuilder()
        self._routers: dict[UUID, ModelRouter] = {}
        self._cross_session_builder = CrossSessionContextBuilder(
            CrossSessionMemoryManager(db)
        )
        self._self_model = SelfModel(db)

    async def _get_cross_session_context(
        self, messages: list[Message], room_id: UUID,
    ) -> Optional[CrossSessionContext]:
        """Fetch cross-session context for the triggering user, or None on failure."""
        # Identify the user from the most recent human message
        user_id = None
        for msg in reversed(messages):
            if msg.speaker_type == SpeakerType.HUMAN and msg.user_id:
                user_id = msg.user_id
                break
        if user_id is None:
            return None

        # Build recent conversation text for semantic search (last ~10 messages)
        recent_text = "\n".join(
            msg.content for msg in messages[-10:] if msg.content
        )

        try:
            ctx = await self._cross_session_builder.build_context(
                user_id=user_id,
                room_id=room_id,
                recent_messages_text=recent_text,
            )
            if ctx.total_injected > 0:
                logger.info(
                    f"Cross-session context: {ctx.total_injected} memories "
                    f"({len(ctx.global_memories)} global, {len(ctx.relevant_memories)} relevant)"
                )
                return ctx
        except Exception as e:
            logger.warning(f"Cross-session context unavailable: {e}")
        return None

    async def _get_identity_context(
        self, room_id: UUID, users: list[User],
    ) -> tuple[Optional[str], Optional[dict[UUID, str]]]:
        """
        Fetch the LLM's evolved identity and per-user models for this room.

        ARCHITECTURE: Graceful degradation — identity failures never block responses.
        WHY: Identity is an enhancement, not a prerequisite for LLM participation.
        TRADEOFF: Extra DB queries per response vs persistent intellectual continuity.
        """
        try:
            identity_mgr = LLMIdentityManager(self.db, MemoryManager(self.db))

            evolved_identity = await identity_mgr.get_identity(room_id)

            user_models = {}
            for user in users:
                model = await identity_mgr.get_user_model(user.id, room_id)
                if model:
                    user_models[user.id] = model

            if evolved_identity:
                logger.info("Identity context: evolved identity loaded, %d user models", len(user_models))

            return (
                evolved_identity,
                user_models if user_models else None,
            )
        except Exception as e:
            logger.warning("Identity context unavailable: %s", e)
            return None, None

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
        protocol: Optional[ProtocolState] = None,
        force_silence: bool = False,
    ) -> OrchestrationResult:
        """
        Called after each human message. Decides and executes LLM response.

        ARCHITECTURE: Protocol-aware orchestration.
        WHY: When a protocol is active, skip heuristics and always interject as facilitator.
        TRADEOFF: Extra conditional path vs separate method — keeps single entry point.

        `force_silence` is the auto_interjection_enabled toggle made real
        (handlers.py): the turn still runs the silence path — decision log
        and participation FSM both see the message — but the LLM never
        speaks. Protocol turns are exempt; a facilitated session is not
        auto-interjection.
        """

        speaker_balance: Optional[dict[str, int]] = None
        unsurfaced_memory_count: Optional[int] = None

        # Protocol mode: always interject, skip heuristics
        if protocol is not None:
            decision = InterjectionDecision(
                should_interject=True,
                reason="protocol_active",
                confidence=1.0,
                use_provoker=False,
            )
        elif force_silence:
            decision = InterjectionDecision(
                should_interject=False,
                reason="auto_interjection_disabled",
                confidence=0.0,
                use_provoker=False,
            )
        else:
            # Compute speaker balance from last 10 messages
            balance: dict[str, int] = {}
            for msg in messages[-10:]:
                if msg.speaker_type == SpeakerType.HUMAN and msg.user_id:
                    uid = str(msg.user_id)
                    balance[uid] = balance.get(uid, 0) + 1
            speaker_balance = balance or None

            # Count unsurfaced memories: semantically similar to latest message
            # but not yet referenced in recent conversation
            latest_human = next(
                (m for m in reversed(messages) if m.speaker_type == SpeakerType.HUMAN),
                None,
            )
            if latest_human:
                try:
                    mem_mgr = MemoryManager(self.db)
                    similar = await mem_mgr.search_memories(
                        room_id=thread.room_id,
                        query=latest_human.content,
                        limit=10,
                        min_score=0.6,
                    )
                    # Memories are "surfaced" if their key or content appears in recent messages
                    recent_text = " ".join(
                        m.content for m in messages[-10:] if m.content
                    ).lower()
                    unsurfaced = [
                        m for m in similar
                        if m.key.lower() not in recent_text
                    ]
                    unsurfaced_memory_count = len(unsurfaced)
                except Exception as e:
                    logger.debug("Unsurfaced memory count unavailable: %s", e)

            decision = self.heuristics.decide(
                messages=messages,
                mentioned=mentioned,
                semantic_novelty=semantic_novelty,
                unsurfaced_memory_count=unsurfaced_memory_count,
                speaker_balance=speaker_balance,
            )

        # Participation FSM (W6): every turn is one event — the message
        # arrival plus this decision — and the machine's new state rides the
        # log_decision upsert below back into llm_participation_state.
        fsm = await self._apply_fsm_turn(room.id, messages, decision)

        if not decision.should_interject:
            logger.debug(f"No interjection: {decision.reason}")
            # WHY: Log silence decisions so the LLM accumulates awareness
            # of when and why it chose not to speak.
            triggered_msg = next(
                (m for m in reversed(messages) if m.speaker_type == SpeakerType.HUMAN),
                None,
            )
            await self._self_model.log_decision(
                room_id=room.id,
                thread_id=thread.id,
                triggered_by_message_id=triggered_msg.id if triggered_msg else None,
                decision=decision,
                human_turn_count=getattr(decision, '_human_turns', None),
                semantic_novelty=semantic_novelty,
                unsurfaced_memory_count=unsurfaced_memory_count,
                speaker_balance=speaker_balance,
                message_count=len(messages),
                mode="silence",
                **self._fsm_log_kwargs(fsm),
            )
            return OrchestrationResult(
                triggered=False,
                decision=decision,
                response=None,
                routing=None,
                prompt_used=None,
            )

        logger.info(f"Interjection triggered: {decision.reason}, provoker={decision.use_provoker}")

        # Apply context truncation to prevent token overflow on long conversations
        context = assemble_context(messages, thread)
        truncated_messages = context.messages

        logger.info(
            f"on_message context: {context.included_count}/{context.original_count} messages, "
            f"truncated={context.truncated}, tokens={context.total_tokens}"
        )

        # The truncated flag used to be logged and dropped here; now it feeds
        # the FSM's post-truncation confidence downgrade (flag pattern, not a
        # state change) before the state is persisted with this decision.
        if fsm is not None and context.truncated:
            fsm.note_truncation()

        cross_ctx = await self._get_cross_session_context(messages, thread.room_id)

        # Fetch evolved identity and user models for prompt injection
        evolved_identity, user_models = await self._get_identity_context(
            thread.room_id, users
        )

        # Fetch self-awareness context (the LLM's own participation state)
        self_awareness_section = None
        try:
            snapshot = await self._self_model.get_participation_snapshot(room.id)
            if snapshot:
                self_awareness_section = self._self_model.render_self_awareness(snapshot)
        except Exception as e:
            logger.debug("Self-awareness context unavailable: %s", e)

        message_images = await self._load_message_images(
            thread.room_id, truncated_messages,
            use_provoker=decision.use_provoker, protocol=protocol,
        )

        # Same gate as the streaming path: provoker/protocol turns stay plain,
        # and DIALECTIC_TOOLS_ENABLED can pull the whole feature in one restart.
        registry = self._tool_registry_for(
            room, use_provoker=decision.use_provoker, protocol=protocol,
        )

        prompt = self.prompt_builder.build(
            room=room,
            users=users,
            messages=truncated_messages,
            memories=memories,
            is_provoker=decision.use_provoker,
            cross_session_context=cross_ctx,
            protocol=protocol,
            evolved_identity=evolved_identity,
            user_models=user_models,
            self_awareness=self_awareness_section,
            tools_enabled=registry is not None,
            message_images=message_images,
        )

        router = self._get_router(room)

        request = LLMRequest(
            messages=prompt.messages,
            system=prompt.system,
            model=room.provoker_model if decision.use_provoker else room.primary_model,
        )

        tool_metadata: Optional[dict] = None
        if registry is not None:
            labels = registry.labels()
            loop_result = await ToolLoop(router, registry).run(request)
            routing = loop_result.routing
            if loop_result.tool_trace:
                tool_metadata = {"tools": {
                    "iterations": loop_result.iterations,
                    "degraded": loop_result.degraded,
                    # Stamp the human-facing label at write time, same as the
                    # streaming path — tools.py stays the one source.
                    "calls": [
                        {**entry, "label": labels.get(entry.get("name"), "")}
                        for entry in loop_result.tool_trace
                    ],
                }}
                proposal = _hoisted_prediction_proposal(loop_result.tool_trace)
                if proposal is not None:
                    tool_metadata["proposal"] = proposal
        else:
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

        # Detect and strip [PHASE_COMPLETE: ...] marker from response
        content = routing.response.content
        phase_complete_signal = None
        match = _PHASE_COMPLETE_RE.search(content)
        if match:
            phase_complete_signal = match.group(1).strip()
            content = _PHASE_COMPLETE_RE.sub("", content).rstrip()

        response_message = await self._persist_response(
            thread=thread,
            content=content,
            speaker_type=SpeakerType.LLM_PROVOKER if decision.use_provoker else SpeakerType.LLM_PRIMARY,
            model_used=routing.response.model,
            prompt_hash=routing.prompt_hash,
            token_count=routing.response.input_tokens + routing.response.output_tokens,
            protocol=protocol,
            metadata=tool_metadata,
        )

        # Fire-and-forget: extract LLM self-memories in background
        self._schedule_self_memory_extraction(response_message, thread.room_id, messages)

        # WHY: Log the interjection decision so the LLM accumulates
        # awareness of when and why it chose to speak.
        triggered_msg = next(
            (m for m in reversed(messages) if m.speaker_type == SpeakerType.HUMAN),
            None,
        )
        mode = "provoker" if decision.use_provoker else ("protocol" if protocol else "primary")
        decision_id = await self._self_model.log_decision(
            room_id=room.id,
            thread_id=thread.id,
            triggered_by_message_id=triggered_msg.id if triggered_msg else None,
            decision=decision,
            semantic_novelty=semantic_novelty,
            speaker_balance=speaker_balance,
            message_count=len(messages),
            response_message_id=response_message.id,
            mode=mode,
            tool_calls=tool_metadata["tools"]["calls"] if tool_metadata else None,
            **self._fsm_log_kwargs(fsm),
        )

        # Schedule effectiveness measurement (~30s later)
        if decision_id:
            self._schedule_effectiveness_measurement(
                room_id=room.id,
                llm_message_id=response_message.id,
                decision_id=decision_id,
            )

        return OrchestrationResult(
            triggered=True,
            decision=decision,
            response=response_message,
            routing=routing,
            prompt_used=prompt,
            phase_complete_signal=phase_complete_signal,
        )

    async def _apply_fsm_turn(
        self,
        room_id: UUID,
        messages: list[Message],
        decision: InterjectionDecision,
    ) -> Optional[ParticipationFSM]:
        """Apply this turn to the room's participation FSM; None on failure.

        WHY a helper + a soft failure: the machine is hydrated from
        llm_participation_state (the DB row is its memory), and a missing or
        pre-migration row must never cost the room its turn — the caller just
        passes no FSM fields to log_decision, which COALESCEs around them.
        The returned machine is NOT persisted here: its state rides the
        log_decision upsert later in the turn, after any truncation
        downgrade has been applied.
        """
        try:
            fsm = await self._load_participation_fsm(room_id)
            latest_human = next(
                (m for m in reversed(messages) if m.speaker_type == SpeakerType.HUMAN),
                None,
            )
            # Question detection reuses the heuristics engine's signal rather
            # than inventing a second one.
            is_question = bool(latest_human) and self.heuristics._is_question(
                latest_human.content,
            )
            event = decision_event(
                spoke=decision.should_interject,
                is_question=is_question,
                current_state=fsm.state,
            )
            fsm.apply(event)
            return fsm
        except Exception as e:
            logger.debug("Participation FSM unavailable: %s", e)
            return None

    async def _load_participation_fsm(self, room_id: UUID) -> ParticipationFSM:
        """Hydrate the room's FSM from llm_participation_state, or a fresh one."""
        row = await self.db.fetchrow(
            """SELECT fsm_state, state_entered_at, state_source
               FROM llm_participation_state WHERE room_id = $1""",
            room_id,
        )
        if row and row["fsm_state"]:
            return ParticipationFSM.from_snapshot({
                "state": row["fsm_state"],
                "state_entered_at": row["state_entered_at"],
                "state_source": row["state_source"],
            })
        return ParticipationFSM()

    @staticmethod
    def _fsm_log_kwargs(fsm: Optional[ParticipationFSM]) -> dict:
        """FSM fields for log_decision, or nothing (COALESCE preserves)."""
        if fsm is None:
            return {}
        return {
            "fsm_state": fsm.state.value,
            "state_entered_at": fsm.state_entered_at,
            "state_source": fsm.state_source.value,
        }

    async def force_response(
        self,
        room: Room,
        thread: Thread,
        users: list[User],
        messages: list[Message],
        memories: list[Memory],
        use_provoker: bool = False,
        protocol: Optional[ProtocolState] = None,
        reason: Optional[str] = None,
    ) -> OrchestrationResult:
        """Force LLM response regardless of heuristics.

        `reason` overrides the decision's recorded why (default keeps the
        historic "protocol_active"/"forced"); the participation sweep uses it
        to mark follow-ups it triggered itself. Tools are deliberately NOT
        wired here — the gate in _tool_registry_for excludes every mode that
        calls this path, so there is nothing to route through a loop.

        FSM note: this path deliberately does NOT apply participation-FSM
        events. Its only FSM-aware caller is the silence sweep, which applies
        FollowUpSent itself after the turn succeeds — a generic LlmSpoke here
        would skip that bookkeeping.
        """
        reason = reason or ("protocol_active" if protocol else "forced")
        decision = InterjectionDecision(
            should_interject=True,
            reason=reason,
            confidence=1.0,
            use_provoker=use_provoker,
        )

        # Apply context truncation to prevent token overflow on long conversations
        context = assemble_context(messages, thread)
        truncated_messages = context.messages

        logger.info(
            f"force_response context: {context.included_count}/{context.original_count} messages, "
            f"truncated={context.truncated}, tokens={context.total_tokens}"
        )

        cross_ctx = await self._get_cross_session_context(messages, thread.room_id)

        # Fetch evolved identity and user models for prompt injection
        evolved_identity, user_models = await self._get_identity_context(
            thread.room_id, users
        )

        # Fetch self-awareness context (the LLM's own participation state) —
        # a forced turn is still a turn the LLM should know itself inside of.
        self_awareness_section = None
        try:
            snapshot = await self._self_model.get_participation_snapshot(room.id)
            if snapshot:
                self_awareness_section = self._self_model.render_self_awareness(snapshot)
        except Exception as e:
            logger.debug("Self-awareness context unavailable: %s", e)

        message_images = await self._load_message_images(
            thread.room_id, truncated_messages,
            use_provoker=use_provoker, protocol=protocol,
        )

        prompt = self.prompt_builder.build(
            room=room,
            users=users,
            messages=truncated_messages,
            memories=memories,
            is_provoker=use_provoker,
            cross_session_context=cross_ctx,
            protocol=protocol,
            evolved_identity=evolved_identity,
            user_models=user_models,
            self_awareness=self_awareness_section,
            message_images=message_images,
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

        # Detect and strip [PHASE_COMPLETE: ...] marker from response
        content = routing.response.content
        phase_complete_signal = None
        match = _PHASE_COMPLETE_RE.search(content)
        if match:
            phase_complete_signal = match.group(1).strip()
            content = _PHASE_COMPLETE_RE.sub("", content).rstrip()

        response_message = await self._persist_response(
            thread=thread,
            content=content,
            speaker_type=SpeakerType.LLM_PROVOKER if use_provoker else SpeakerType.LLM_PRIMARY,
            model_used=routing.response.model,
            prompt_hash=routing.prompt_hash,
            token_count=routing.response.input_tokens + routing.response.output_tokens,
            protocol=protocol,
        )

        # Fire-and-forget: extract LLM self-memories in background
        self._schedule_self_memory_extraction(response_message, thread.room_id, messages)

        # WHY: A forced turn was previously invisible to the self-model — the
        # LLM spoke but never logged having spoken, so its participation
        # state (and the sweep's follow-up bookkeeping) drifted from reality.
        triggered_msg = next(
            (m for m in reversed(messages) if m.speaker_type == SpeakerType.HUMAN),
            None,
        )
        mode = "provoker" if use_provoker else ("protocol" if protocol else "primary")
        decision_id = await self._self_model.log_decision(
            room_id=room.id,
            thread_id=thread.id,
            triggered_by_message_id=triggered_msg.id if triggered_msg else None,
            decision=decision,
            message_count=len(messages),
            response_message_id=response_message.id,
            mode=mode,
        )

        # Schedule effectiveness measurement (~30s later)
        if decision_id:
            self._schedule_effectiveness_measurement(
                room_id=room.id,
                llm_message_id=response_message.id,
                decision_id=decision_id,
            )

        return OrchestrationResult(
            triggered=True,
            decision=decision,
            response=response_message,
            routing=routing,
            prompt_used=prompt,
            phase_complete_signal=phase_complete_signal,
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
        - "tool_activity": A tool started or finished
          {"tool": str, "label": str, "status": "started"|"finished"|"failed",
           "latency_ms": int|None}
        - "done": Complete persisted-message metadata including sequence,
          created_at, speaker_type, message_type, and the tool trace
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

        cross_ctx = await self._get_cross_session_context(messages, thread.room_id)

        # Fetch evolved identity and user models for prompt injection
        evolved_identity, user_models = await self._get_identity_context(
            thread.room_id, users
        )

        registry = self._tool_registry_for(room, use_provoker=use_provoker)

        message_images = await self._load_message_images(
            thread.room_id, truncated_messages, use_provoker=use_provoker,
        )

        # Build prompt with truncated messages
        prompt = self.prompt_builder.build(
            room=room,
            users=users,
            messages=truncated_messages,
            memories=memories,
            is_provoker=use_provoker,
            cross_session_context=cross_ctx,
            evolved_identity=evolved_identity,
            user_models=user_models,
            tools_enabled=registry is not None,
            message_images=message_images,
        )

        # Create request for streaming
        model = room.provoker_model if use_provoker else room.primary_model
        request = LLMRequest(
            messages=prompt.messages,
            system=prompt.system,
            model=model,
            stream=True,
        )

        # WHY: Streaming previously bypassed the fallback chain entirely —
        # router.stream() falls back across providers until the first token.
        router = self._get_router(room)

        # Track accumulated content
        accumulated_content = ""
        token_index = 0
        model_used = model
        tool_metadata: Optional[dict] = None

        try:
            if registry is not None:
                labels = registry.labels()
                # ToolLoop owns the whole turn: it may make several round trips
                # and the text of all of them is ONE message in the room.
                async for kind, payload in ToolLoop(router, registry).run_streaming(request):
                    if kind == "token":
                        token = payload["token"]
                        accumulated_content += token
                        yield ("streaming", {"token": token, "index": token_index})
                        token_index += 1
                    elif kind == "tool_start":
                        yield ("tool_activity", {
                            "tool": payload["name"],
                            "label": payload.get("label") or "checking",
                            "status": "started",
                            "latency_ms": None,
                        })
                    elif kind == "tool_result":
                        yield ("tool_activity", {
                            "tool": payload["name"],
                            # tool_result carries no label — the registry that
                            # produced the tool_start is still right here.
                            "label": labels.get(payload["name"], "checking"),
                            "status": "finished" if payload.get("ok") else "failed",
                            "latency_ms": payload.get("latency_ms"),
                        })
                    elif kind == "loop_done":
                        # The loop's own accumulation is authoritative: it spans
                        # every iteration, including a degraded text-only retry
                        # whose tokens we may have started emitting mid-turn.
                        accumulated_content = payload.get("text", accumulated_content)
                        trace = payload.get("tool_trace") or []
                        if trace:
                            tool_metadata = {"tools": {
                                "iterations": payload.get("iterations", 0),
                                "degraded": bool(payload.get("degraded")),
                                # Stamp the human-facing label at write time so
                                # the reader of a months-old trace does not need
                                # a client-side copy of the label table to make
                                # sense of it — tools.py stays the one source.
                                "calls": [
                                    {**entry, "label": labels.get(entry.get("name"), "")}
                                    for entry in trace
                                ],
                            }}
                            proposal = _hoisted_prediction_proposal(trace)
                            if proposal is not None:
                                tool_metadata["proposal"] = proposal
            else:
                async for event_type, data in router.stream(request):
                    if event_type == "attempt":
                        model_used = data["model"]
                        continue
                    token = data["token"]
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
                model_used=model_used,
                prompt_hash=prompt_hash,
                token_count=0,  # Not available from streaming
                metadata=tool_metadata,
            )

            # Fire-and-forget: extract LLM self-memories in background
            self._schedule_self_memory_extraction(response_message, thread.room_id, messages)

            yield ("done", {
                "message_id": str(response_message.id),
                "content": accumulated_content,
                "model_used": model_used,
                "truncated": context.truncated,
                "sequence": response_message.sequence,
                "created_at": response_message.created_at.isoformat(),
                "speaker_type": response_message.speaker_type.value,
                "message_type": response_message.message_type.value,
                # None when no tool ran — the client renders the footer off its
                # presence, so an empty dict would mean "used 0 tools".
                "metadata": tool_metadata,
            })

        except Exception as e:
            # ToolLoop re-raises a provider death that happens AFTER the first
            # token (splicing two answers together is worse than one truncated
            # one), so it lands here exactly like a plain stream failure and
            # the partial text still reaches the room.
            logger.exception("Streaming error")
            yield ("error", {
                "error": str(e),
                "partial_content": accumulated_content,
            })

    def _tool_registry_for(
        self, room: Room, use_provoker: bool, protocol: Optional[ProtocolState] = None,
    ) -> Optional[ToolRegistry]:
        """The tools this turn may use, or None to take the plain stream path.

        WHY not every mode: the provoker is a 1-3 sentence interruption whose
        whole value is arriving fast — a 20s quote check turns a jab into a
        latency. The protocol facilitator is procedurally neutral on substance,
        so fetching evidence is out of role for it. The annotator has its own
        engine and never comes through here at all. That leaves the primary
        participant, which is the one that gets asked "what is Brent doing".
        """
        if use_provoker or protocol is not None:
            return None
        if not tools_enabled():
            logger.info("Tools disabled by DIALECTIC_TOOLS_ENABLED — plain stream path")
            return None
        try:
            registry = build_registry(room, self.db)
        except Exception:
            # A registry that cannot be built is not a reason to lose the turn.
            logger.exception("Tool registry unavailable — falling back to plain stream")
            return None
        return registry if registry.schemas() else None

    async def _load_message_images(
        self,
        room_id: UUID,
        messages: list[Message],
        *,
        use_provoker: bool,
        protocol: Optional[ProtocolState] = None,
    ) -> Optional[dict[UUID, list[dict]]]:
        """Image blocks for the messages about to be rendered, or None.

        WHY not every mode: the same line _tool_registry_for draws, for the same
        reason. The provoker is a 1-3 sentence interruption whose whole value is
        arriving fast, and the protocol facilitator is procedurally neutral on
        substance — both run on deliberately stripped context, and an image is
        the most expensive thing that can ride on a turn (~1-1.5k tokens each).
        The participant that gets asked "what's wrong with this chart" is the
        primary one, and it is the one that gets to look.

        NEVER raises: a DB hiccup or a volume that moved must cost the room the
        picture, not the answer. `messages` is the post-truncation window, so
        the query only ever covers turns that are actually in the prompt.
        """
        if use_provoker or protocol is not None:
            return None
        if not messages:
            return None
        try:
            images = await load_message_images(
                self.db, room_id, [m.id for m in messages]
            )
        except Exception:
            logger.exception("Image attachments unavailable — continuing text-only")
            return None
        if not images:
            return None
        logger.info(
            "Vision: %d image(s) attached to %d message(s) in this prompt",
            count_images(images), len(images),
        )
        return images

    def _schedule_self_memory_extraction(
        self,
        message: Message,
        room_id: UUID,
        messages: list[Message],
    ) -> None:
        """
        Schedule background extraction of LLM self-memories from a response.

        WHY: This task outlives the per-message DB connection scope, so it
        must acquire its own connection from the pool. Using self.db here
        was a use-after-release bug — by the time the task ran, the pooled
        connection had been returned and the extraction failed silently.
        """
        if self.db_pool is None:
            logger.debug("No db_pool available — skipping self-memory extraction")
            return

        recent = messages[-10:]

        async def _extract() -> None:
            try:
                async with self.db_pool.acquire() as conn:
                    self_memory = LLMSelfMemory(conn, MemoryManager(conn))
                    await self_memory.extract_and_store(message, room_id, recent)
            except Exception:
                logger.exception("Self-memory extraction failed")

        asyncio.create_task(_extract())

    def _schedule_effectiveness_measurement(
        self,
        *,
        room_id: UUID,
        llm_message_id: UUID,
        decision_id: int,
    ) -> None:
        """
        Schedule background effectiveness measurement ~30s after LLM speaks.

        WHY: Gives humans time to respond before measuring engagement.
        TRADEOFF: 30s delay means the measurement is always slightly stale,
        but immediate measurement would find zero responses.
        """
        if self.db_pool is None:
            logger.debug("No db_pool available — skipping effectiveness measurement")
            return

        async def _delayed_measure() -> None:
            await asyncio.sleep(30)
            try:
                async with self.db_pool.acquire() as conn:
                    await SelfModel(conn).measure_effectiveness(
                        room_id=room_id,
                        llm_message_id=llm_message_id,
                        decision_id=decision_id,
                    )
            except Exception:
                logger.exception("Effectiveness measurement failed")

        asyncio.create_task(_delayed_measure())

    async def _persist_response(
        self,
        thread: Thread,
        content: str,
        speaker_type: SpeakerType,
        model_used: str,
        prompt_hash: str,
        token_count: int,
        protocol: Optional[ProtocolState] = None,
        metadata: Optional[dict] = None,
    ) -> Message:
        """Create Message record and log event, with optional protocol attribution.

        `metadata` lands in messages.metadata (JSONB) — today the tool trace
        {"tools": {iterations, degraded, calls: [...]}} plus, when the turn
        drafted one, {"proposal": {...}} for the prediction Accept button.
        WHY persist it rather
        than only streaming it: "where did that number come from" is a question
        asked hours later, and a failed check the model then talked around is
        invisible in the text of the message itself.
        """

        now = datetime.now(timezone.utc)
        message_id = uuid4()
        message_type = self._detect_message_type(content)

        protocol_id = protocol.id if protocol else None
        protocol_phase = protocol.current_phase if protocol else None

        # Atomic INSERT with inline sequence calculation to prevent TOCTOU race.
        # WHY retry: under concurrent inserts to the same thread, two
        # transactions can still compute the same next sequence; the
        # UNIQUE (thread_id, sequence) constraint rejects the loser, and a
        # retry recomputes against the winner's committed row.
        row = None
        for attempt in range(3):
            try:
                row = await self.db.fetchrow(
                    """INSERT INTO messages
                       (id, thread_id, sequence, created_at, speaker_type, user_id,
                        message_type, content, model_used, prompt_hash, token_count,
                        protocol_id, protocol_phase, metadata)
                       VALUES (
                           $1, $2,
                           (SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = $2),
                           $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
                       )
                       RETURNING sequence""",
                    message_id, thread.id, now,
                    speaker_type.value, None, message_type.value,
                    content, model_used, prompt_hash, token_count,
                    protocol_id, protocol_phase,
                    # JSONB: the pool's codec serializes the dict — see
                    # CLAUDE.md "pass dict directly to asyncpg".
                    metadata,
                )
                break
            except asyncpg.UniqueViolationError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))
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
            metadata=metadata,
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
