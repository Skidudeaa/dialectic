# llm/cross_session_context.py — Cross-session memory injection for LLM prompts

"""
ARCHITECTURE: Extends LLM context with relevant memories from other rooms.
WHY: Enables LLM to reference user's broader knowledge base.
TRADEOFF: Longer contexts vs richer cross-conversation awareness.
"""

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID
import logging

from models import Memory, CrossRoomMemoryResult
from memory.cross_session import CrossSessionMemoryManager

logger = logging.getLogger(__name__)


@dataclass
class CrossSessionContext:
    """Context additions from cross-session memory search."""
    global_memories: List[Memory]  # From auto-inject collections
    relevant_memories: List[CrossRoomMemoryResult]  # Semantically similar from other rooms
    total_injected: int
    
    def to_prompt_section(self) -> str:
        """Format cross-session memories for LLM prompt injection."""
        sections = []
        
        if self.global_memories:
            sections.append("## Persistent Knowledge (from your collections)\n")
            for mem in self.global_memories:
                sections.append(f"- **{mem.key}**: {mem.content}\n")
        
        if self.relevant_memories:
            sections.append("\n## Related Insights (from other conversations)\n")
            for result in self.relevant_memories:
                sections.append(
                    f"- **{result.memory.key}** (from *{result.source_room_name}*, "
                    f"relevance: {result.relevance_score:.0%}): {result.memory.content}\n"
                )
        
        if not sections:
            return ""
        
        return (
            "---\n"
            "# Cross-Session Context\n"
            "The following information comes from the user's other conversations "
            "and persistent knowledge collections. Reference these naturally when relevant, "
            "but don't force connections.\n\n"
            + "".join(sections) +
            "---\n"
        )


class CrossSessionContextBuilder:
    """
    ARCHITECTURE: Builds cross-session context for LLM prompts.
    WHY: Centralized logic for gathering and formatting cross-room memories.
    """

    def __init__(self, cross_session_manager: CrossSessionMemoryManager):
        self.manager = cross_session_manager

    async def build_context(
        self,
        user_id: UUID,
        room_id: UUID,
        recent_messages_text: str,
        max_global_memories: int = 5,
        max_relevant_memories: int = 3,
        min_similarity: float = 0.75,
    ) -> CrossSessionContext:
        """
        Build cross-session context for a room.
        
        Args:
            user_id: The user requesting LLM response
            room_id: Current room ID
            recent_messages_text: Recent conversation text for semantic search
            max_global_memories: Max memories from auto-inject collections
            max_relevant_memories: Max semantically similar memories from other rooms
            min_similarity: Minimum similarity threshold for relevant memories
        
        Returns:
            CrossSessionContext with formatted memories
        """
        # Get auto-inject memories (user's persistent collections)
        global_memories = await self.manager.get_auto_inject_memories(user_id)
        global_memories = global_memories[:max_global_memories]
        
        # Get semantically relevant memories from other rooms
        relevant_memories = []
        if recent_messages_text:
            try:
                relevant_memories = await self.manager.get_relevant_cross_room_memories(
                    user_id=user_id,
                    current_room_id=room_id,
                    context=recent_messages_text,
                    limit=max_relevant_memories,
                    min_similarity=min_similarity,
                )
            except Exception as e:
                logger.warning(f"Failed to fetch cross-room memories: {e}")
        
        return CrossSessionContext(
            global_memories=global_memories,
            relevant_memories=relevant_memories,
            total_injected=len(global_memories) + len(relevant_memories)
        )

    async def should_suggest_promotion(
        self,
        memory: Memory,
        user_id: UUID,
    ) -> bool:
        """
        Determine if LLM should suggest promoting a memory to global.
        
        Heuristics:
        - Memory has been edited multiple times (shows importance)
        - Memory has been referenced from other rooms
        - Content contains definition-like patterns
        """
        # Check if memory has been referenced elsewhere
        references = await self.manager.get_references_from_memory(memory.id)
        if len(references) >= 2:
            return True
        
        # Check if it's been heavily edited
        if memory.version >= 3:
            return True
        
        # Check for definition-like content
        definition_markers = ['is defined as', 'means that', 'refers to', 'is when']
        content_lower = memory.content.lower()
        if any(marker in content_lower for marker in definition_markers):
            return True
        
        return False
