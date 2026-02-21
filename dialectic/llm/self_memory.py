# llm/self_memory.py — Post-response extraction pipeline for LLM epistemic state

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from models import Memory, MemoryScope, Message
from memory.manager import MemoryManager
from .providers import get_provider, ProviderName, LLMRequest

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_TEMPLATE = """Analyze this response from an LLM participant in a collaborative dialogue.
Extract any substantive claims, positions, or frameworks the LLM expressed.

Response: {llm_response}

Context (recent messages): {context_summary}

For each claim, provide:
- topic: A short topic label (2-5 words)
- position: The specific claim or position (1-2 sentences)
- is_change: Whether this contradicts a previously stated position

Output as JSON array:
[{{"topic": "...", "position": "...", "is_change": false}}]

If no substantive claims, return empty array: []"""


class LLMSelfMemory:
    """
    ARCHITECTURE: Post-response extraction pipeline for LLM epistemic state.
    WHY: The LLM should remember its own positions across context windows.
    TRADEOFF: Extra LLM call per response (cheap model) vs persistent identity.
    """

    def __init__(self, db, memory_manager: MemoryManager):
        self.db = db
        self.memory_manager = memory_manager

    async def extract_and_store(
        self,
        llm_response: Message,
        room_id: UUID,
        recent_context: list[Message],
    ) -> list[Memory]:
        """
        Extract claims/positions from an LLM response and store as LLM-scoped memories.

        Uses a cheap model (Haiku) to analyze the LLM's response and extract:
        - Key claims it made
        - Position changes ("I was wrong about X")
        - Definitions or frameworks it proposed

        Returns list of created memories.
        """
        try:
            claims = await self._extract_claims(llm_response, recent_context)
            if not claims:
                logger.debug("No claims extracted from LLM response %s", llm_response.id)
                return []

            memories = await self._store_claims(claims, room_id, llm_response.id)
            logger.debug(
                "Extracted %d claims from LLM response %s, stored %d memories",
                len(claims), llm_response.id, len(memories),
            )
            return memories

        except Exception as e:
            logger.error("Self-memory extraction failed for message %s: %s", llm_response.id, e)
            return []

    async def _extract_claims(
        self,
        llm_response: Message,
        recent_context: list[Message],
    ) -> list[dict]:
        """
        ARCHITECTURE: Single cheap LLM call to extract structured claims.
        WHY: Haiku/mini is fast and cheap enough to run on every response.
        TRADEOFF: Extraction quality vs cost — cheap model may miss nuance.
        """
        context_summary = "\n".join(
            f"[{msg.speaker_type.value}]: {msg.content[:200]}"
            for msg in recent_context[-10:]
            if msg.content
        )

        extraction_prompt = EXTRACTION_PROMPT_TEMPLATE.format(
            llm_response=llm_response.content,
            context_summary=context_summary,
        )

        provider = get_provider(ProviderName.ANTHROPIC)
        request = LLMRequest(
            messages=[{"role": "user", "content": extraction_prompt}],
            system="You are a claim extraction assistant. Extract claims as JSON.",
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            temperature=0.0,
        )
        response = await provider.complete(request)

        return self._parse_claims(response.content)

    def _parse_claims(self, raw_response: str) -> list[dict]:
        """Parse JSON claims from extraction response, tolerating malformed output."""
        try:
            # Try direct JSON parse first
            claims = json.loads(raw_response)
            if isinstance(claims, list):
                return [
                    c for c in claims
                    if isinstance(c, dict)
                    and "topic" in c
                    and "position" in c
                ]
            return []
        except json.JSONDecodeError:
            pass

        # Fallback: extract JSON array from surrounding text
        start = raw_response.find("[")
        end = raw_response.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                claims = json.loads(raw_response[start:end + 1])
                if isinstance(claims, list):
                    return [
                        c for c in claims
                        if isinstance(c, dict)
                        and "topic" in c
                        and "position" in c
                    ]
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to parse claims from extraction response")
        return []

    async def _store_claims(
        self,
        claims: list[dict],
        room_id: UUID,
        source_message_id: UUID,
    ) -> list[Memory]:
        """
        ARCHITECTURE: Upsert semantics — update existing LLM memories on same topic.
        WHY: Prevents memory bloat; LLM's position on a topic evolves, not accumulates.
        TRADEOFF: Semantic search for dedup adds latency vs cleaner memory state.
        """
        created: list[Memory] = []

        for claim in claims:
            topic = claim["topic"]
            position = claim["position"]
            is_change = claim.get("is_change", False)

            try:
                existing = await self._find_existing_llm_memory(room_id, topic)

                if existing:
                    # Update existing memory with new position
                    reason = "Position changed" if is_change else "Position refined"
                    memory = await self.memory_manager.edit_memory(
                        memory_id=existing.memory_id,
                        new_content=position,
                        edited_by_user_id=None,
                        edit_reason=reason,
                    )
                    created.append(memory)
                else:
                    # Create new LLM memory
                    memory = await self.memory_manager.add_memory(
                        room_id=room_id,
                        key=topic,
                        content=position,
                        created_by_user_id=None,
                        scope=MemoryScope.LLM,
                        source_message_id=source_message_id,
                    )
                    created.append(memory)

            except Exception as e:
                logger.error("Failed to store claim '%s': %s", topic, e)
                continue

        return created

    async def _find_existing_llm_memory(
        self,
        room_id: UUID,
        topic: str,
    ) -> Optional["SimilarityMatch"]:
        """Search for an existing LLM memory on the same topic via semantic similarity."""
        from memory.vector_store import SimilarityMatch

        matches = await self.memory_manager.search_memories(
            room_id=room_id,
            query=topic,
            limit=5,
            min_score=0.75,
        )

        # Filter to LLM-scoped memories only
        for match in matches:
            if match.scope == MemoryScope.LLM.value:
                return match

        return None
