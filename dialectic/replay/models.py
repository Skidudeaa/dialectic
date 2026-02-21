# replay/models.py — Pydantic models for event replay engine

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class RoomState(BaseModel):
    """Room configuration at a point in time."""
    name: Optional[str] = None
    global_ontology: Optional[str] = None
    global_rules: Optional[str] = None
    primary_provider: str = "anthropic"
    fallback_provider: str = "openai"
    primary_model: str = "claude-sonnet-4-20250514"
    provoker_model: str = "claude-haiku-4-20250514"
    auto_interjection_enabled: bool = True
    interjection_turn_threshold: int = 4
    semantic_novelty_threshold: float = 0.7


class ThreadState(BaseModel):
    """Thread state at a point in time."""
    id: UUID
    title: Optional[str] = None
    parent_thread_id: Optional[UUID] = None
    fork_point_message_id: Optional[UUID] = None
    message_count: int = 0


class MessageState(BaseModel):
    """Message state at a point in time."""
    id: UUID
    thread_id: UUID
    sequence: int
    speaker_type: str
    user_id: Optional[UUID] = None
    message_type: str
    content: str
    references_message_id: Optional[UUID] = None
    model_used: Optional[str] = None
    prompt_hash: Optional[str] = None
    token_count: Optional[int] = None
    is_deleted: bool = False
    protocol_id: Optional[UUID] = None
    protocol_phase: Optional[int] = None


class MemoryState(BaseModel):
    """Memory state at a point in time."""
    id: UUID
    key: str
    content: str
    scope: str
    status: str = "active"
    version: int = 1
    owner_user_id: Optional[UUID] = None
    created_by_user_id: Optional[UUID] = None
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None


class MemberState(BaseModel):
    """Room member state at a point in time."""
    user_id: UUID
    display_name: Optional[str] = None
    joined_at: Optional[datetime] = None


class ProtocolState(BaseModel):
    """Active protocol state at a point in time."""
    id: UUID
    thread_id: UUID
    protocol_type: str
    status: str
    current_phase: int
    total_phases: int
    invoked_by_user_id: Optional[UUID] = None
    config: dict = {}


class RoomSnapshot(BaseModel):
    """
    ARCHITECTURE: Complete room state at a point in time.
    WHY: Materializing state from events enables temporal queries.
    TRADEOFF: Full model per snapshot — memory-heavy but complete.
    """
    room_id: UUID
    at_sequence: int
    at_timestamp: Optional[datetime] = None
    room: Optional[RoomState] = None
    threads: list[ThreadState] = []
    messages: list[MessageState] = []
    memories: list[MemoryState] = []
    members: list[MemberState] = []
    active_protocol: Optional[ProtocolState] = None

    @classmethod
    def empty(cls, room_id: UUID, at_sequence: int) -> "RoomSnapshot":
        return cls(room_id=room_id, at_sequence=at_sequence)


class ReplayEvent(BaseModel):
    """
    ARCHITECTURE: Single event for replay playback.
    WHY: Includes timing metadata so clients can recreate real-time pacing.
    TRADEOFF: Adds delay_ms computation per event vs raw event stream.
    """
    sequence: int
    event_type: str
    timestamp: datetime
    delay_ms: int
    payload: dict
    user_display_name: Optional[str] = None


class LLMDecisionReplay(BaseModel):
    """
    ARCHITECTURE: Reconstructs what the LLM saw when it produced a response.
    WHY: Debuggability — understand why the LLM said what it said.
    TRADEOFF: Requires message-level metadata (model_used, prompt_hash).
    """
    message_id: UUID
    model_used: Optional[str] = None
    prompt_hash: Optional[str] = None
    token_count: Optional[int] = None
    messages_in_context: int = 0
    memories_available: int = 0
    interjection_reason: Optional[str] = None
    speaker_type: str = ""


class StateDiff(BaseModel):
    """
    ARCHITECTURE: Changes between two points in time.
    WHY: Enables "what changed?" queries for catch-up and auditing.
    TRADEOFF: Re-scans events in range vs maintaining incremental diffs.
    """
    from_sequence: int
    to_sequence: int
    messages_added: int = 0
    memories_added: int = 0
    memories_edited: int = 0
    memories_invalidated: int = 0
    threads_forked: int = 0
    settings_changed: list[str] = []
    events: list[dict] = []


class TimelineBucket(BaseModel):
    """Single time bucket for timeline heat map."""
    start_sequence: int
    end_sequence: int
    start_time: datetime
    end_time: datetime
    event_count: int
    event_types: dict[str, int] = {}
