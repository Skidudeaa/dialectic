"""
ARCHITECTURE: Context assembly with smart truncation for LLM.
WHY: CONTEXT.md requires prioritized truncation that keeps @Claude exchanges.
TRADEOFF: Heuristic scoring vs simpler FIFO truncation.
"""

from dataclasses import dataclass
from typing import Optional
import sys
import pathlib

_package_root = str(pathlib.Path(__file__).resolve().parent.parent)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

from models import Message, Thread, SpeakerType


@dataclass
class AssembledContext:
    """Result of context assembly."""
    messages: list[Message]
    truncated: bool
    total_tokens: int
    included_count: int
    original_count: int


# Default context limits (can be overridden per room)
DEFAULT_MAX_TOKENS = 100_000  # ~100k tokens for Claude 3
RESERVED_OUTPUT_TOKENS = 4_000  # Reserve for response


def assemble_context(
    messages: list[Message],
    thread: Thread,
    max_tokens: int = DEFAULT_MAX_TOKENS - RESERVED_OUTPUT_TOKENS,
    encoder_name: str = "cl100k_base",
) -> AssembledContext:
    """
    Assemble context from messages with smart truncation.

    Priority (high to low):
    1. Most recent messages (last ~20%)
    2. Messages with @Claude mentions
    3. Claude's responses
    4. Messages near conversation topic shifts
    5. Older messages (truncated first)

    For forked threads: messages already filtered by get_thread_messages().
    """
    if not messages:
        return AssembledContext(
            messages=[],
            truncated=False,
            total_tokens=0,
            included_count=0,
            original_count=0,
        )

    encoder = None
    try:
        import tiktoken
        encoder = tiktoken.get_encoding(encoder_name)
    except Exception:
        # Fallback: estimate 4 chars per token
        pass

    def estimate_tokens(msg: Message) -> int:
        if encoder:
            return len(encoder.encode(msg.content))
        return len(msg.content) // 4

    def priority_score(msg: Message, idx: int, total: int) -> float:
        """Higher score = more likely to keep."""
        score = 0.0

        # Recency: last 20% get high priority
        recency_pct = idx / total
        if recency_pct >= 0.8:
            score += 100.0
        elif recency_pct >= 0.6:
            score += 50.0

        # @Claude mentions get high priority
        if "@claude" in msg.content.lower() or "@llm" in msg.content.lower():
            score += 80.0

        # Claude's own responses get priority (context for follow-ups)
        if msg.speaker_type in (SpeakerType.LLM_PRIMARY, SpeakerType.LLM_PROVOKER):
            score += 60.0

        # Questions get slight priority
        if msg.content.rstrip().endswith("?"):
            score += 20.0

        return score

    # Score all messages
    scored = [
        (msg, priority_score(msg, i, len(messages)), estimate_tokens(msg))
        for i, msg in enumerate(messages)
    ]

    # Always include last N messages regardless of score
    ALWAYS_INCLUDE_LAST = 10

    # Sort by priority (but preserve order for inclusion)
    sorted_by_priority = sorted(
        range(len(scored)),
        key=lambda i: scored[i][1],
        reverse=True,
    )

    # Select messages within token budget
    selected_indices = set()
    total_tokens = 0

    # First: always include last N messages
    for i in range(max(0, len(messages) - ALWAYS_INCLUDE_LAST), len(messages)):
        msg, _, tokens = scored[i]
        if total_tokens + tokens <= max_tokens:
            selected_indices.add(i)
            total_tokens += tokens

    # Then: add by priority until budget exhausted
    for i in sorted_by_priority:
        if i in selected_indices:
            continue
        msg, _, tokens = scored[i]
        if total_tokens + tokens <= max_tokens:
            selected_indices.add(i)
            total_tokens += tokens

    # Reconstruct in original order
    selected_messages = [
        messages[i] for i in sorted(selected_indices)
    ]

    return AssembledContext(
        messages=selected_messages,
        truncated=len(selected_messages) < len(messages),
        total_tokens=total_tokens,
        included_count=len(selected_messages),
        original_count=len(messages),
    )
