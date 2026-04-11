// TypeScript interfaces matching web/models.py Pydantic models.

export interface User {
  username: string;
  display_name: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  display_name: string;
}

export interface Room {
  id: string;
  name: string;
  topic: string;
  linked_book_id: string | null;
  participants: string[];
  created_at: string;
}

export interface Message {
  id: string;
  room_id: string;
  user: string;
  content: string;
  msg_type: "user" | "llm" | "system";
  model: string | null;
  ts: string;
}

export interface WatchlistItem {
  symbol: string;
  label: string;
  last_price: number | null;
  change_pct: number | null;
  source: string;
}

export interface Prediction {
  id: string;
  user: string;
  statement: string;
  confidence: number;
  deadline: string;
  resolution: string | null;
  resolved_at: string | null;
  linked_book_id: string | null;
  tags: string[];
  created_at: string;
}

export interface JournalEntry {
  id: string;
  user: string;
  thesis: string;
  instrument: string;
  direction: string;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  tags: string[];
  linked_book_id: string | null;
  notes: string;
  created_at: string;
}

export interface ThesisBook {
  id: string;
  filename: string;
  title: string;
  nodes: number;
  edges: number;
}

export interface ThesisState {
  v: number;
  timestamp: string;
  title: string;
  nodeStates: Record<string, string>;
  confluenceScores: Record<string, number>;
  cascadePhase: {
    number: number;
    key: string;
    status: string;
  };
  countdowns: Array<{
    nodeId: string;
    label?: string;
    daysRemaining: number;
  }>;
  marketSnapshot: Record<string, number>;
  scenarioImpacts: Record<string, {
    probability: number;
    netImpact: number;
  }>;
  portfolioSummary: Record<string, unknown>;
  horizonTrace?: Record<string, unknown>;
}

export interface CrossBookFlag {
  flag_type: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  books: string[];
  detail: string;
  data: Record<string, unknown>;
}

export interface CrossBookResult {
  timestamp: string;
  books_analyzed: string[];
  flags: CrossBookFlag[];
  shared_markets: Record<string, unknown>;
  phase_summary: Record<string, unknown>;
}

export interface TradeInfo {
  trade_id: string;
  ticker: string;
  predicates: unknown[];
  ref_price: number;
  book: string;
}

export interface WSMessage {
  type: "message" | "llm_chunk" | "llm_done" | "system" | "state_update" | "error" | "typing" | "presence" | "tv-alert";
  payload: Record<string, unknown>;
  ts: string;
  user: string;
}

// ── TradingView integration ─────────────────────────────────────────────

export type TVOp =
  | "incrementClosesObserved"
  | "setNodeState"
  | "setProbability"
  | "setCurrent";

export type TVNodeState =
  | "active"
  | "resolved"
  | "partial"
  | "monitoring"
  | "fired";

export interface TVBinding {
  bindingId: string;
  nodeId: string;
  op: TVOp;
  thresholdLevel?: number | null;
  targetState?: TVNodeState | null;
  expectedSymbol?: string | null;
  expectedPineAlertName?: string | null;
  description?: string;
  fireCount?: number;
  lastFiredAt?: string | null;
}

export interface TVBindingCreate {
  bindingId: string;
  nodeId: string;
  op: TVOp;
  thresholdLevel?: number;
  targetState?: TVNodeState;
  expectedSymbol?: string;
  expectedPineAlertName?: string;
  description?: string;
}

export interface TVStatus {
  secretConfigured: boolean;
  rateLimitPerMin: number;
  nonceTtlSeconds: number;
  clockSkewSeconds: number;
  activeNonces: number;
  webhookUrl: string;
  recentEventCount: number;
}

export interface TVAlertEvent {
  ts: string;
  result: string;
  bookId?: string | null;
  bindingId?: string | null;
  nodeId?: string | null;
  op?: TVOp | null;
  newValue?: unknown;
  detail?: string | null;
  sourceIP?: string | null;
}

// tvIndicators dict — the per-node reading from the thesisgraph snapshot.
export interface TVIndicatorReading {
  rsi14?: number;
  atr14?: number;
  sma50?: number;
  source?: string;
  computedAt?: string;
  // Additional kind/period keys may appear (e.g. rsi7, sma20)
  [key: string]: string | number | undefined;
}

// Payload carried by the tv-alert WebSocket message
export interface TVAlertWSPayload {
  bookId: string;
  nodeId: string;
  bindingId: string;
  op: TVOp;
  newValue: unknown;
  pineAlertName?: string | null;
  chartSymbol?: string | null;
  thesisStateChanged: boolean;
  changedNodes: string[];
}

export interface HealthResponse {
  status: string;
  uptime_seconds: number;
  ws_connections: number;
  books_loaded: string[];
  last_snapshots: Record<string, string>;
}
