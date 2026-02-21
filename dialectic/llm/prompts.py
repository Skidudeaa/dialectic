# llm/prompts.py — Prompt assembly with user modifier blending

from dataclasses import dataclass
from typing import Optional

from uuid import UUID

from models import Room, User, Message, Memory, SpeakerType, MessageType, ProtocolState

# Optional import for cross-session context
try:
    from .cross_session_context import CrossSessionContext
except ImportError:
    CrossSessionContext = None

# Optional import for protocol instructions
try:
    from .protocol_library import get_protocol_instructions, get_protocol_definition
except ImportError:
    get_protocol_instructions = None
    get_protocol_definition = None


@dataclass
class AssembledPrompt:
    system: str
    messages: list[dict]


class PromptBuilder:
    """
    ARCHITECTURE: Layered prompt construction.
    WHY: Separate concerns (room rules, user style, memory, messages).
    TRADEOFF: Complexity vs customization granularity.
    """

    BASE_IDENTITY = """You are a participant in a long-running philosophical dialogue. You are not an assistant—you are a co-thinker. Your role:

- Engage as an equal, not a helper
- Challenge assumptions, including your own
- Synthesize across speakers when useful
- Introduce tension when conversation stagnates
- Remember: you have memory of past conversations; use it

You may:
- Disagree strongly
- Ask probing questions
- Refuse to answer if a question is malformed
- Change your mind when presented with good arguments

You speak in your own voice. You are not neutral."""

    PROVOKER_IDENTITY = """You are the destabilizing voice in a philosophical dialogue. Your role is to:

- Inject unexpected questions
- Challenge emerging consensus
- Introduce counterexamples
- Push toward edge cases
- Be adversarial but not hostile

Keep responses SHORT (1-3 sentences). You are an interruption, not a lecture."""

    FACILITATOR_IDENTITY = """You are a structured reasoning facilitator guiding a thinking protocol. You are NOT a free participant — you have a specific procedural role:

- Follow the protocol phase instructions precisely
- Keep participants on track within the current phase
- Do not skip ahead or deviate from the protocol structure
- Be neutral on substance, rigorous on process
- Signal phase completion with [PHASE_COMPLETE: reason] when appropriate

You speak with authority on procedure, not on content."""

    def build(
        self,
        room: Room,
        users: list[User],
        messages: list[Message],
        memories: list[Memory],
        is_provoker: bool = False,
        cross_session_context: "CrossSessionContext" = None,
        protocol: Optional[ProtocolState] = None,
        evolved_identity: Optional[str] = None,
        user_models: Optional[dict[UUID, str]] = None,
    ) -> AssembledPrompt:
        """
        Assemble full prompt from components.

        ARCHITECTURE: Protocol-aware, identity-aware prompt assembly.
        WHY: When a protocol is active, the LLM switches from participant to facilitator.
              Evolved identity and user models give the LLM persistent intellectual continuity.
        TRADEOFF: More conditional logic in build(), but avoids separate build paths.

        Args:
            cross_session_context: Optional memories from other rooms/sessions
            protocol: Optional active protocol state — overrides identity when present
            evolved_identity: Optional distilled identity document from prior sessions
            user_models: Optional per-user thinking models {user_id: model_text}
        """

        # Protocol mode: use facilitator identity with protocol-specific override
        if protocol is not None and get_protocol_definition is not None:
            definition = get_protocol_definition(protocol.protocol_type.value)
            identity = definition.facilitator_identity or self.FACILITATOR_IDENTITY
        elif is_provoker:
            identity = self.PROVOKER_IDENTITY
        else:
            identity = self.BASE_IDENTITY

        room_context = self._build_room_context(room)
        user_context = self._blend_user_modifiers(users)
        memory_context = self._build_memory_context(memories)

        # Build cross-session context if provided
        cross_session_section = ""
        if cross_session_context and cross_session_context.total_injected > 0:
            cross_session_section = cross_session_context.to_prompt_section()

        # Build protocol instructions section
        protocol_section = ""
        if protocol is not None and get_protocol_instructions is not None:
            protocol_section = get_protocol_instructions(protocol)

        # Assemble system prompt in priority order:
        # BASE_IDENTITY → Evolved Identity → User Models → Protocol → Room → Preferences → Memory
        system_parts = [identity]

        # Evolved identity: injected between base identity and room context
        # Suppressed for protocol mode (facilitator) and provoker mode (short disruptions)
        if evolved_identity and protocol is None and not is_provoker:
            system_parts.append(f"\n\n## Your Evolved Identity (This Room)\n{evolved_identity}")

        # User models: the LLM's understanding of each participant
        if user_models and protocol is None and not is_provoker:
            user_model_section = self._build_user_models_section(user_models, users)
            if user_model_section:
                system_parts.append(f"\n\n## Your Understanding of the Participants\n{user_model_section}")

        if protocol_section:
            system_parts.append(f"\n\n{protocol_section}")
        if room_context:
            system_parts.append(f"\n\n## Room Context\n{room_context}")
        if user_context:
            system_parts.append(f"\n\n## Participant Preferences\n{user_context}")
        if memory_context:
            system_parts.append(f"\n\n## Shared Memory (This Room)\n{memory_context}")
        if cross_session_section:
            system_parts.append(f"\n\n{cross_session_section}")

        system = "\n".join(system_parts)
        formatted_messages = self._format_messages(messages, users)

        return AssembledPrompt(system=system, messages=formatted_messages)

    def _build_user_models_section(
        self,
        user_models: dict[UUID, str],
        users: list[User],
    ) -> str:
        """Format per-user models for prompt injection."""
        user_map = {u.id: u.display_name for u in users}
        parts = []
        for uid, model_text in user_models.items():
            name = user_map.get(uid, str(uid))
            parts.append(f"### {name}\n{model_text}")
        return "\n\n".join(parts)

    def _build_room_context(self, room: Room) -> str:
        parts = []
        if room.global_ontology:
            parts.append(f"### Ontology\n{room.global_ontology}")
        if room.global_rules:
            parts.append(f"### Rules\n{room.global_rules}")
        return "\n\n".join(parts)

    def _blend_user_modifiers(self, users: list[User]) -> str:
        """Blend style preferences from all participating users."""
        if not users:
            return ""

        avg_aggression = sum(u.aggression_level for u in users) / len(users)
        avg_metaphysics = sum(u.metaphysics_tolerance for u in users) / len(users)

        parts = [
            f"Aggression level: {avg_aggression:.1f}/1.0 (0=gentle, 1=combative)",
            f"Metaphysics tolerance: {avg_metaphysics:.1f}/1.0 (0=strict empiricism, 1=open to speculation)",
        ]

        styles = [u.style_modifier for u in users if u.style_modifier]
        if styles:
            parts.append(f"Style notes: {'; '.join(styles)}")

        instructions = [u.custom_instructions for u in users if u.custom_instructions]
        if instructions:
            parts.append(f"Custom instructions: {' | '.join(instructions)}")

        return "\n".join(parts)

    def _build_memory_context(self, memories: list[Memory]) -> str:
        """Format memories for inclusion in prompt."""
        if not memories:
            return ""

        lines = []
        for mem in memories:
            lines.append(f"- **{mem.key}**: {mem.content}")

        return "\n".join(lines)

    def _format_messages(
        self,
        messages: list[Message],
        users: list[User],
    ) -> list[dict]:
        """Convert Message objects to LLM message format."""
        user_map = {u.id: u.display_name for u in users}
        formatted = []

        for msg in messages:
            if msg.is_deleted:
                continue

            prefix = self._type_prefix(msg.message_type)

            if msg.speaker_type == SpeakerType.HUMAN:
                speaker_name = user_map.get(msg.user_id, "Unknown")
                content = f"[{speaker_name}] {prefix}{msg.content}"
                role = "user"
            elif msg.speaker_type in (SpeakerType.LLM_PRIMARY, SpeakerType.LLM_PROVOKER, SpeakerType.LLM_ANNOTATOR):
                content = f"{prefix}{msg.content}"
                role = "assistant"
            else:
                content = f"[SYSTEM] {msg.content}"
                role = "user"

            formatted.append({"role": role, "content": content})

        return formatted

    def _type_prefix(self, message_type: MessageType) -> str:
        """Generate prefix for structured message types."""
        prefixes = {
            MessageType.CLAIM: "[CLAIM] ",
            MessageType.QUESTION: "[QUESTION] ",
            MessageType.DEFINITION: "[DEFINITION] ",
            MessageType.COUNTEREXAMPLE: "[COUNTEREXAMPLE] ",
            MessageType.MEMORY_WRITE: "[MEMORY] ",
        }
        return prefixes.get(message_type, "")
