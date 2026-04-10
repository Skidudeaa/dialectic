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
    model: str = "anthropic/claude-sonnet-4-20250514"
    room_id: Optional[str] = None


class LLMCompareRequest(BaseModel):
    prompt: str
    models: List[str] = Field(
        default_factory=lambda: [
            "anthropic/claude-sonnet-4-20250514",
            "openai/gpt-4o",
        ],
        max_length=4,
    )
    room_id: Optional[str] = None


# ── Health ────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: float
    ws_connections: int
    books_loaded: List[str]
    last_snapshots: Dict[str, str]
    llm_available: bool = False
