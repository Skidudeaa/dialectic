# models.py — Core data model + event sourcing foundation

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


# ============================================================
# ENUMS
# ============================================================

class MessageType(str, Enum):
    TEXT = "text"
    CLAIM = "claim"
    QUESTION = "question"
    DEFINITION = "definition"
    COUNTEREXAMPLE = "counterexample"
    MEMORY_WRITE = "memory_write"
    SYSTEM = "system"


class SpeakerType(str, Enum):
    HUMAN = "human"
    LLM_PRIMARY = "llm_primary"
    LLM_PROVOKER = "llm_provoker"
    LLM_ANNOTATOR = "llm_annotator"
    SYSTEM = "system"


class EventType(str, Enum):
    ROOM_CREATED = "room_created"
    ROOM_SETTINGS_UPDATED = "room_settings_updated"
    THREAD_CREATED = "thread_created"
    THREAD_FORKED = "thread_forked"
    MESSAGE_CREATED = "message_created"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_DELETED = "message_deleted"
    MEMORY_ADDED = "memory_added"
    MEMORY_EDITED = "memory_edited"
    MEMORY_INVALIDATED = "memory_invalidated"
    USER_JOINED_ROOM = "user_joined"
    USER_MODIFIER_UPDATED = "user_modifier_updated"
    # Cross-session memory events
    MEMORY_PROMOTED = "memory_promoted"
    MEMORY_REFERENCED = "memory_referenced"
    COLLECTION_CREATED = "collection_created"
    COLLECTION_MEMORY_ADDED = "collection_memory_added"
    COLLECTION_MEMORY_REMOVED = "collection_memory_removed"
    # Thinking protocol events
    PROTOCOL_INVOKED = "protocol_invoked"
    PROTOCOL_PHASE_ADVANCED = "protocol_phase_advanced"
    PROTOCOL_CONCLUDED = "protocol_concluded"
    PROTOCOL_ABORTED = "protocol_aborted"
    # Async dialogue events
    ANNOTATION_CREATED = "annotation_created"
    BRIEFING_REQUESTED = "briefing_requested"
    # Stakes / commitment events
    COMMITMENT_CREATED = "commitment_created"
    COMMITMENT_CONFIDENCE_UPDATED = "commitment_confidence_updated"
    COMMITMENT_RESOLVED = "commitment_resolved"


class CommitmentStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    VOIDED = "voided"
    EXPIRED = "expired"


class CommitmentResolution(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    VOIDED = "voided"


class CommitmentCategory(str, Enum):
    PREDICTION = "prediction"
    COMMITMENT = "commitment"
    BET = "bet"


class MemoryScope(str, Enum):
    ROOM = "room"      # Visible only in originating room
    USER = "user"      # Visible only to owner user
    GLOBAL = "global"  # Visible across all rooms user participates in
    LLM = "llm"        # LLM-authored memories (positions, claims, frameworks)


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"


# ============================================================
# CORE ENTITIES
# ============================================================

class Room(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime
    token: str
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


class User(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime
    display_name: str
    style_modifier: Optional[str] = None
    aggression_level: float = 0.5
    metaphysics_tolerance: float = 0.5
    custom_instructions: Optional[str] = None


class RoomMembership(BaseModel):
    room_id: UUID
    user_id: UUID
    joined_at: datetime


class Thread(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    room_id: UUID
    created_at: datetime
    parent_thread_id: Optional[UUID] = None
    fork_point_message_id: Optional[UUID] = None
    fork_memory_version: Optional[int] = None
    title: Optional[str] = None


class Message(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    thread_id: UUID
    sequence: int
    created_at: datetime
    speaker_type: SpeakerType
    user_id: Optional[UUID] = None
    message_type: MessageType
    content: str
    references_message_id: Optional[UUID] = None
    references_memory_id: Optional[UUID] = None
    model_used: Optional[str] = None
    prompt_hash: Optional[str] = None
    token_count: Optional[int] = None
    is_deleted: bool = False


class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    room_id: UUID
    created_at: datetime
    updated_at: datetime
    version: int = 1
    scope: MemoryScope
    owner_user_id: Optional[UUID] = None
    key: str
    content: str
    source_message_id: Optional[UUID] = None
    created_by_user_id: Optional[UUID] = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    invalidated_by_user_id: Optional[UUID] = None
    invalidated_at: Optional[datetime] = None
    invalidation_reason: Optional[str] = None
    embedding: Optional[list[float]] = None


class Event(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    sequence: Optional[int] = None
    timestamp: datetime
    event_type: EventType
    room_id: Optional[UUID] = None
    thread_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    payload: dict


# ============================================================
# PAYLOAD SCHEMAS
# ============================================================

class ThreadForkedPayload(BaseModel):
    new_thread_id: UUID
    parent_thread_id: UUID
    fork_point_message_id: UUID
    fork_memory_version: int
    title: Optional[str] = None


class MessageCreatedPayload(BaseModel):
    message_id: UUID
    sequence: int
    speaker_type: SpeakerType
    user_id: Optional[UUID]
    message_type: MessageType
    content: str
    references_message_id: Optional[UUID] = None
    model_used: Optional[str] = None
    prompt_hash: Optional[str] = None
    token_count: Optional[int] = None


class MemoryAddedPayload(BaseModel):
    memory_id: UUID
    scope: MemoryScope
    owner_user_id: Optional[UUID]
    key: str
    content: str
    source_message_id: Optional[UUID]


class MemoryEditedPayload(BaseModel):
    memory_id: UUID
    previous_version: int
    new_version: int
    previous_content: str
    new_content: str
    edit_reason: Optional[str] = None


class MemoryInvalidatedPayload(BaseModel):
    memory_id: UUID
    reason: Optional[str] = None


# ============================================================
# CROSS-SESSION MEMORY MODELS
# ============================================================

class MemoryReference(BaseModel):
    """
    ARCHITECTURE: Tracks when a memory from one room is cited in another.
    WHY: Enables knowledge graph across conversations.
    TRADEOFF: Additional complexity vs powerful cross-session linking.
    """
    id: UUID = Field(default_factory=uuid4)
    source_memory_id: UUID
    target_room_id: UUID
    target_thread_id: Optional[UUID] = None
    target_message_id: Optional[UUID] = None
    referenced_at: datetime
    referenced_by_user_id: Optional[UUID] = None
    referenced_by_llm: bool = False
    citation_context: Optional[str] = None
    relevance_score: Optional[float] = None


class UserMemoryCollection(BaseModel):
    """
    ARCHITECTURE: User-defined collections of memories spanning rooms.
    WHY: Users can curate persistent knowledge across all conversations.
    """
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    auto_inject: bool = False
    display_order: int = 0


class CollectionMembership(BaseModel):
    """Link between a collection and a memory."""
    collection_id: UUID
    memory_id: UUID
    added_at: datetime
    added_by_user_id: Optional[UUID] = None
    notes: Optional[str] = None


class CrossRoomMemoryResult(BaseModel):
    """Memory search result with source room context."""
    memory: Memory
    source_room_id: UUID
    source_room_name: str
    relevance_score: float
    is_local: bool  # True if memory is from current room


# ============================================================
# NEW EVENT TYPES FOR CROSS-SESSION
# ============================================================
# Add these to EventType enum above:
# MEMORY_PROMOTED = "memory_promoted"
# MEMORY_REFERENCED = "memory_referenced"
# COLLECTION_CREATED = "collection_created"
# COLLECTION_MEMORY_ADDED = "collection_memory_added"
# COLLECTION_MEMORY_REMOVED = "collection_memory_removed"


# ============================================================
# THINKING PROTOCOL MODELS
# ============================================================

class ProtocolType(str, Enum):
    STEELMAN = "steelman"
    SOCRATIC = "socratic"
    DEVIL_ADVOCATE = "devil_advocate"
    SYNTHESIS = "synthesis"


class ProtocolStatus(str, Enum):
    INVOKED = "invoked"
    ACTIVE = "active"
    CONCLUDING = "concluding"
    CONCLUDED = "concluded"
    ABORTED = "aborted"


class ProtocolState(BaseModel):
    """
    ARCHITECTURE: Runtime state of an active protocol instance.
    WHY: Decoupled from protocol definition — state lives in DB, definition in code.
    TRADEOFF: Requires join with definition for full context, but keeps state minimal.
    """
    id: UUID
    thread_id: UUID
    room_id: UUID
    protocol_type: ProtocolType
    status: ProtocolStatus
    current_phase: int
    total_phases: int
    invoked_by_user_id: Optional[UUID] = None
    invoked_at: datetime
    config: dict = {}
    synthesis_memory_id: Optional[UUID] = None


class MemoryPromotedPayload(BaseModel):
    """Payload when a room memory is promoted to global scope."""
    memory_id: UUID
    original_room_id: UUID
    promoted_by_user_id: UUID


class MemoryReferencedPayload(BaseModel):
    """Payload when a memory is cited in another room."""
    reference_id: UUID
    source_memory_id: UUID
    source_room_id: UUID
    target_room_id: UUID
    target_message_id: Optional[UUID] = None
    citation_context: Optional[str] = None
