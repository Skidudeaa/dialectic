"""
Pydantic models for the web API layer.

WHY: Single source of truth for request/response shapes. Frontend TypeScript
types are generated from these. Every field is explicit — no dict[str, Any]
hand-waving.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    display_name: str


class User(BaseModel):
    username: str
    display_name: str


# ── Rooms ─────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    name: str
    topic: str = ""
    linked_book_id: Optional[str] = None


class RoomUpdate(BaseModel):
    name: Optional[str] = None
    topic: Optional[str] = None
    linked_book_id: Optional[str] = None


class Room(BaseModel):
    id: str
    name: str
    topic: str
    linked_book_id: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    created_at: str


# ── Messages ──────────────────────────────────────────────────────────────

class MessageCreate(BaseModel):
    content: str
    msg_type: Literal["user"] = "user"
    model: Optional[str] = None


class RoomCommand(BaseModel):
    """A slash command dispatched from chat (e.g. ``/brief``).

    WHY a dedicated endpoint: command *results* must be posted as ``system``
    messages, which clients are not allowed to author (see ``MessageCreate``'s
    ``msg_type`` lock). The server executes the command and posts the trusted
    system message itself, then broadcasts it to the room.
    """
    text: str


class PinRequest(BaseModel):
    """Typed pin request — prevents arbitrary dict injection."""
    id: str
    room_id: str
    user: str
    content: str
    msg_type: str
    model: Optional[str] = None
    ts: str


class Message(BaseModel):
    id: str
    room_id: str
    user: str
    content: str
    msg_type: str  # "user" | "llm" | "system"
    model: Optional[str] = None
    ts: str


# ── Watchlist ─────────────────────────────────────────────────────────────

class WatchlistItem(BaseModel):
    symbol: str
    label: str
    last_price: Optional[float] = None
    change_pct: Optional[float] = None
    source: str = "yahoo"  # "yahoo" | "polymarket"


# ── Predictions ───────────────────────────────────────────────────────────

class PredictionCreate(BaseModel):
    statement: str
    confidence: float  # 0.0 – 1.0
    deadline: str  # ISO date
    linked_book_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class Prediction(BaseModel):
    id: str
    user: str
    statement: str
    confidence: float
    deadline: str
    resolution: Optional[str] = None  # "correct" | "incorrect" | None
    resolved_at: Optional[str] = None
    linked_book_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: str


class PredictionResolve(BaseModel):
    resolution: Literal["correct", "incorrect"]


# ── Trade Journal ─────────────────────────────────────────────────────────

class JournalEntryCreate(BaseModel):
    thesis: str
    instrument: str
    direction: str  # "long" | "short"
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    linked_book_id: Optional[str] = None
    notes: str = ""


class JournalEntryUpdate(BaseModel):
    """Update fields for closing a trade — exit price, P&L, notes."""
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class JournalEntry(BaseModel):
    id: str
    user: str
    thesis: str
    instrument: str
    direction: str
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    linked_book_id: Optional[str] = None
    notes: str = ""
    created_at: str


# ── Thesis State ──────────────────────────────────────────────────────────

class ThesisState(BaseModel):
    """Evaluated graph state — mirrors export_state() output."""
    v: int
    timestamp: str
    title: str
    node_states: Dict[str, str]
    confluence_scores: Dict[str, float]
    cascade_phase: Dict[str, Any]
    countdowns: List[Dict[str, Any]]
    market_snapshot: Dict[str, float]
    scenario_impacts: Dict[str, Any]
    portfolio_summary: Dict[str, Any]
    horizon_trace: Optional[Dict[str, Any]] = None


class ScenarioResult(BaseModel):
    scenario_id: str
    label: str
    probability: float
    net_impact: float
    overrides: Dict[str, str]
    instrument_impacts: Dict[str, Any]


class HorizonRequest(BaseModel):
    horizon_days: int = Field(ge=1, le=730)


# ── Market ────────────────────────────────────────────────────────────────

class MarketQuote(BaseModel):
    symbol: str
    price: float
    source: str = "yahoo"


class PolymarketProb(BaseModel):
    slug: str
    probability: Optional[float]


# ── Outcomes ──────────────────────────────────────────────────────────────

class TradeEvaluation(BaseModel):
    trade_id: str
    ticker: str
    event_type: str
    consistency: float
    predicates: List[Dict[str, Any]]
    dynamic_target: Optional[Dict[str, Any]] = None
    target_refusal: Optional[Dict[str, Any]] = None


class CrossBookFlag(BaseModel):
    flag_type: str
    severity: str
    books: List[str]
    detail: str
    data: Dict[str, Any] = Field(default_factory=dict)


class CrossBookResult(BaseModel):
    timestamp: str
    books_analyzed: List[str]
    flags: List[CrossBookFlag]
    shared_markets: Dict[str, Any]
    phase_summary: Dict[str, Any]


# ── LLM ───────────────────────────────────────────────────────────────────

class LLMChatRequest(BaseModel):
    prompt: str
    model: str = "anthropic/claude-sonnet-4.6"
    room_id: Optional[str] = None


class LLMCompareRequest(BaseModel):
    prompt: str
    models: List[str] = Field(
        default_factory=lambda: [
            "anthropic/claude-sonnet-4.6",
            "openai/gpt-5.3-chat",
        ],
        max_length=4,
    )
    room_id: Optional[str] = None


# ── TradingView integration ───────────────────────────────────────────────

# Allowed mutation ops on the webhook — four values only. Any incoming
# op outside this set returns 422. See docs/plans/...tradingview...plan.md §5.
TVOp = Literal[
    "incrementClosesObserved",
    "setNodeState",
    "setProbability",
    "setCurrent",
]

# Target states permitted on setNodeState — matches eval_node_state's
# event-node branch. Disallowed targets return 422.
TVNodeState = Literal["active", "resolved", "partial", "monitoring", "fired"]


class TVBinding(BaseModel):
    """A Pine alert → node mutation binding, stored on node.tvAlertBindings."""
    bindingId: str
    nodeId: str
    op: TVOp
    # op-specific optional fields
    thresholdLevel: Optional[float] = None
    targetState: Optional[TVNodeState] = None
    expectedSymbol: Optional[str] = None
    expectedPineAlertName: Optional[str] = None
    description: str = ""
    # Audit — last fire timestamp and count (populated on successful mutation)
    lastFiredAt: Optional[str] = None
    fireCount: int = 0


class TVBindingCreate(BaseModel):
    """POST body for creating a new binding. JWT-gated."""
    bindingId: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    nodeId: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    op: TVOp
    thresholdLevel: Optional[float] = None
    targetState: Optional[TVNodeState] = None
    expectedSymbol: Optional[str] = Field(default=None, max_length=32)
    expectedPineAlertName: Optional[str] = Field(default=None, max_length=128)
    description: str = Field(default="", max_length=500)


class TVWebhookAlert(BaseModel):
    """Pine Script → webhook body. Intentionally minimal: only the binding
    reference + an optional numeric value. No free-form field writes."""
    book: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    bindingId: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    value: Optional[float] = None
    pineAlertName: Optional[str] = Field(default=None, max_length=128)
    chartSymbol: Optional[str] = Field(default=None, max_length=32)


class TVWebhookAck(BaseModel):
    """Webhook success response. Echoes applied mutation for operator logs."""
    status: Literal["ok"] = "ok"
    bookId: str
    nodeId: str
    op: TVOp
    newValue: Any  # int for incrementClosesObserved, str for state, float for price/prob


class TVIndicatorReading(BaseModel):
    """A single node's tvIndicators dict, flattened for the API surface."""
    nodeId: str
    rsi14: Optional[float] = None
    atr14: Optional[float] = None
    sma50: Optional[float] = None
    source: Optional[str] = None
    computedAt: Optional[str] = None
    # Additional kind/period combinations land here
    extra: Dict[str, float] = Field(default_factory=dict)


class TVAlertEvent(BaseModel):
    """A single audit entry from web/data/tradingview-events.jsonl."""
    ts: str
    bookId: str
    nodeId: Optional[str] = None
    bindingId: Optional[str] = None
    op: Optional[TVOp] = None
    newValue: Any = None
    result: str  # "ok" | "bad_signature" | "bad_timestamp" | etc.
    detail: Optional[str] = None
    sourceIP: Optional[str] = None


class TVStatus(BaseModel):
    """GET /api/tradingview/status — operator-facing configuration snapshot."""
    secretConfigured: bool
    rateLimitPerMin: int
    nonceTtlSeconds: int
    clockSkewSeconds: int
    activeNonces: int
    webhookUrl: str
    recentEventCount: int


# ── Health ────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: float
    ws_connections: int
    books_loaded: List[str]
    last_snapshots: Dict[str, str]
    llm_available: bool = False
