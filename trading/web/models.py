"""
Pydantic models for the web API layer.

WHY: Single source of truth for request/response shapes. Frontend TypeScript
types are generated from these. Every field is explicit — no dict[str, Any]
hand-waving.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


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

class Room(BaseModel):
    id: str
    name: str
    topic: str
    linked_book_id: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    created_at: str


# ── Messages ──────────────────────────────────────────────────────────────

class Message(BaseModel):
    id: str
    room_id: str
    user: str
    content: str
    msg_type: str  # "user" | "llm" | "system"
    model: Optional[str] = None
    ts: str
    # kind discriminates structured entries; meta carries the kind's payload
    # (ArticleMeta / CodeExhibitMeta as a dict). Both default for legacy rows.
    kind: str = "text"
    meta: Optional[Dict[str, Any]] = None


# ── Watchlist ─────────────────────────────────────────────────────────────

class WatchlistItem(BaseModel):
    symbol: str
    label: str
    last_price: Optional[float] = None
    change_pct: Optional[float] = None
    source: str = "yahoo"  # "yahoo" | "polymarket"


# ── Predictions ───────────────────────────────────────────────────────────

#: Shapes a resolution_spec may take. Validated at the door so Phase 2's
#: deterministic auto-resolver never has to defend against malformed specs.
_RESOLUTION_SPEC_KEYS = {
    "price_cross": {"kind", "symbol", "comparator", "threshold"},
    "polymarket": {"kind", "market_id"},
}


class PredictionCreate(BaseModel):
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    deadline: str  # ISO date
    linked_book_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source_key: Optional[str] = None
    # Provenance: who/what originated the claim. source_label is the
    # leaderboard grouping key (defaults to the creating user server-side).
    source_type: Literal[
        "human", "llm", "dialectic_commitment", "newsletter", "polymarket"
    ] = "human"
    source_label: Optional[str] = None
    source_ref: Optional[str] = None
    # Captured reference forecast (Polymarket price when linkable) — the
    # baseline that Brier skill scores are computed against.
    base_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    base_rate_source: Optional[str] = None
    resolution_spec: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _validate_resolution_spec(self) -> "PredictionCreate":
        """Strict shape check: an unknown or misspelled key silently ignored
        here would surface as a claim that never auto-resolves."""
        spec = self.resolution_spec
        if spec is None:
            return self
        kind = spec.get("kind")
        expected = _RESOLUTION_SPEC_KEYS.get(kind)
        if expected is None:
            raise ValueError(f"resolution_spec.kind must be one of {sorted(_RESOLUTION_SPEC_KEYS)}")
        if set(spec) != expected:
            raise ValueError(f"resolution_spec for kind={kind!r} requires exactly keys {sorted(expected)}")
        if kind == "price_cross":
            if not isinstance(spec["symbol"], str) or not spec["symbol"]:
                raise ValueError("resolution_spec.symbol must be a non-empty string")
            if spec["comparator"] not in ("above", "below"):
                raise ValueError("resolution_spec.comparator must be 'above' or 'below'")
            if not isinstance(spec["threshold"], (int, float)) or isinstance(spec["threshold"], bool):
                raise ValueError("resolution_spec.threshold must be a number")
        elif kind == "polymarket":
            if not isinstance(spec["market_id"], str) or not spec["market_id"]:
                raise ValueError("resolution_spec.market_id must be a non-empty string")
        return self


class Prediction(BaseModel):
    id: str
    user: str
    statement: str
    confidence: float
    deadline: str
    resolution: Optional[str] = None  # "correct" | "incorrect" | "partial" | "voided" | None
    resolved_at: Optional[str] = None
    resolution_notes: Optional[str] = None
    resolution_spec: Optional[Dict[str, Any]] = None
    linked_book_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source_type: str = "human"
    source_label: Optional[str] = None
    source_ref: Optional[str] = None
    base_rate: Optional[float] = None
    base_rate_source: Optional[str] = None
    confidence_history: List[Dict[str, Any]] = Field(default_factory=list)  # newest first
    created_at: str


class PredictionResolve(BaseModel):
    resolution: Literal["correct", "incorrect", "partial", "voided"]
    source_key: Optional[str] = None
    resolution_notes: Optional[str] = None


class PredictionConfidenceCreate(BaseModel):
    """One appended belief-update on an open claim."""
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: Optional[str] = None


# ── Paper portfolio ───────────────────────────────────────────────────────

class PaperFillCreate(BaseModel):
    """One paper fill request.

    WHY dollars, not shares: the human thinks in position size; td computes
    quantity = dollars / live quote at fill time, so the desk owns the price
    and a stale client can never write its own. Deposits seed cash (the
    server pins symbol='CASH', price=1.0, quantity=dollars).
    """
    book_id: str = Field(pattern=r"^[a-zA-Z0-9_:-]+$", max_length=128)
    kind: Literal["trade", "deposit"] = "trade"
    symbol: str = Field(default="CASH", max_length=32)
    side: Literal["buy", "sell"] = "buy"
    dollars: float = Field(gt=0)
    rationale: str = ""
    node_id: Optional[str] = None
    prediction_id: Optional[str] = None
    source_key: Optional[str] = None

    @model_validator(mode="after")
    def _trades_need_a_real_symbol(self) -> "PaperFillCreate":
        """'CASH' is the deposit sentinel — a trade against it would corrupt
        the derived cash balance, so it is refused at the door."""
        if self.kind == "trade" and (not self.symbol or self.symbol.upper() == "CASH"):
            raise ValueError("trade fills require a quoted symbol ('CASH' is the deposit sentinel)")
        return self


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
