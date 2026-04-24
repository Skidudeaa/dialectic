"""
v2 WebSocket protocol — versioned envelopes with typed S2C/C2S messages.

WHY: The v1 protocol sends unversioned JSON blobs with no schema contract.
Adding a protocol version, message ID, and typed discriminator enables:
- Backward compatibility detection (v field)
- Gap detection (seq field)
- Bootstrap-on-connect for deterministic first render
- Chat messages alongside thesis events on the same connection
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ── Protocol version ────────────────────────────────────────────────────

PROTOCOL_VERSION = 1


# ── Message type enums ──────────────────────────────────────────────────

class S2CType(str, Enum):
    """Server-to-client message types.

    WHY: Exhaustive enum — the frontend switches on type. Adding a new
    type here is an explicit protocol decision, not an ad-hoc string.
    """
    # Thesis state
    bootstrap = "bootstrap"
    snapshot_full = "snapshot.full"
    snapshot_delta = "snapshot.delta"
    alert_created = "alert.created"
    override_changed = "override.changed"
    runtime_status = "runtime.status"

    # Chat (preserves existing chat functionality)
    chat_message = "chat.message"
    chat_typing = "chat.typing"
    chat_presence = "chat.presence"

    # LLM streaming
    llm_chunk = "llm.chunk"
    llm_done = "llm.done"

    # TradingView
    tv_alert = "tv.alert"

    # Live market tape (Unit 6 — push-driven MarketTicker)
    price_tick = "price.tick"

    # System
    error = "error"
    ping = "ping"
    pong = "pong"


class C2SType(str, Enum):
    """Client-to-server message types."""
    send_message = "send_message"
    typing = "typing"
    set_viewing = "set_viewing"
    subscribe = "subscribe"
    pong = "pong"
    ping = "ping"


# ── Envelope ────────────────────────────────────────────────────────────

class WSEnvelope(BaseModel):
    """Versioned WebSocket message envelope.

    WHY: Every WS message — thesis event, chat, LLM stream, ping — uses
    this envelope. The v field enables protocol evolution. The seq field
    enables gap detection on reconnect (client sees seq=47 then seq=49,
    knows it missed one, re-subscribes for fresh bootstrap).
    """
    v: int = PROTOCOL_VERSION
    type: str  # S2CType or C2SType value
    ts: str  # ISO 8601 UTC
    payload: Dict[str, Any] = Field(default_factory=dict)
    # Optional fields — present on thesis-scoped messages
    thesisId: Optional[str] = None
    revision: Optional[int] = None
    # Server-assigned monotonic sequence per connection
    seq: Optional[int] = None


# ── Typed payload models ────────────────────────────────────────────────

class BootstrapPayload(BaseModel):
    """Payload for S2C 'bootstrap' message — sent on connect and reconnect.

    WHY: Full state on connect means the client renders immediately without
    additional REST calls. On reconnect, the same bootstrap replaces stale
    state — no delta replay needed for a 2-user system with <5KB snapshots.
    """
    # Linked thesis snapshot (for the room's linked book)
    snapshot: Optional[Dict[str, Any]] = None
    # Lightweight catalog of all theses (for dashboard sidebar)
    thesisCatalog: list[Dict[str, Any]] = Field(default_factory=list)
    # Active overrides for the linked thesis
    activeOverrides: list[Dict[str, Any]] = Field(default_factory=list)
    # Recent alerts for the linked thesis
    recentAlerts: list[Dict[str, Any]] = Field(default_factory=list)
    # Current seq for gap detection
    seq: int = 0


class SnapshotDeltaPayload(BaseModel):
    """Payload for S2C 'snapshot.delta' — incremental state changes.

    WHY: Structured deltas instead of generic JSON Patch. Each field
    is optional — only changed fields are included.
    """
    changedNodes: Optional[Dict[str, str]] = None  # nodeId → new state
    changedSummary: Optional[Dict[str, Any]] = None
    phaseChange: Optional[Dict[str, Any]] = None
    overrideChanges: Optional[list[Dict[str, Any]]] = None
    newAlerts: Optional[list[Dict[str, Any]]] = None
    marketUpdates: Optional[Dict[str, float]] = None
    seq: int = 0


class ChatMessagePayload(BaseModel):
    """Payload for S2C/C2S 'chat.message'."""
    id: str
    room_id: str
    user: str
    content: str
    msg_type: str = "user"
    model: Optional[str] = None


class ErrorPayload(BaseModel):
    """Payload for S2C 'error'."""
    message: str
    code: str = "unknown"
