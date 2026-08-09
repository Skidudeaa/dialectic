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

// Structured message payloads (kind !== "text"). Carried in Message.meta.
export interface ArticleMeta {
  source: string;
  title: string;
  take: string;
}
export interface CodeExhibitMeta {
  fn: string;
  lang: string;
  code: string;
}

export type MessageKind = "text" | "article" | "code";

export interface Message {
  id: string;
  room_id: string;
  user: string;
  content: string;
  msg_type: "user" | "llm" | "system";
  model: string | null;
  ts: string;
  // kind discriminates structured entries; meta carries the kind's payload.
  // Optional for back-compat with older messages / the classic chat view.
  kind?: MessageKind;
  meta?: ArticleMeta | CodeExhibitMeta | null;
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
  /** Dialectic room that discusses this book, if one is linked. The join key
   *  the "Open Full Dashboard" deep link resolves against. */
  dialecticRoomId?: string | null;
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
  // Cockpit Unit 5: per-source freshness, keyed by source name
  // (yahoo / polymarket / derived / fred / econ). UI paints amber when
  // Date.now() - Date.parse(fetchedAt) > ttlSeconds*1000.
  feedFreshness?: Record<string, {
    source: string;
    fetchedAt: string;
    ttlSeconds: number;
    detail?: string;
  }>;
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

// ── Trade lifecycle panel (Unit 10) ──────────────────────────────────────

export type TradePredicateState = "fired" | "approaching" | "stable" | "inactive";

export interface TradePredicate {
  id: string;
  kind: "state" | "state_set" | "threshold" | "countdown";
  description: string;
  state: TradePredicateState;
  actual: number | string | null;
  note: string;
  load_bearing: boolean;
  is_flipped: boolean;
  node_id: string | null;
  path: string | null;
  expected: string | null;
  allowed: string[] | null;
  op: string | null;
  value: number;
  days: number;
}

export interface OpenTradeSummary {
  trade_id: string;
  ticker: string;
  book: string;
  ref_price: number | null;
  direction: string;
  predicate_count: number;
  fired_count: number;
  approaching_count: number;
  error: string | null;
  snapshot_timestamp?: string;
}

export interface OpenTradeDetail {
  trade_id: string;
  ticker: string;
  book: string;
  ref_price: number | null;
  direction: string;
  predicates: TradePredicate[];
  fire_timer_hours: number | null;
  approach_timer_hours: number | null;
  fired_count: number;
  approaching_count: number;
  snapshot_timestamp: string;
}

export interface KillConfirmIssued {
  confirm_required: true;
  confirm_token: string;
  expires_at: number;
  ttl_seconds: number;
}

export interface KillResult {
  trade_id: string;
  killed_at: string;
  actor: string;
  reason: string;
}

export interface WSMessage {
  type: "message" | "llm_chunk" | "llm_done" | "system" | "state_update" | "error" | "typing" | "presence" | "presence.changed" | "tv-alert" | "bootstrap" | "price.tick";
  payload: Record<string, unknown>;
  ts: string;
  user: string;
  // v2 envelope fields (additive — existing fields preserved)
  v?: number;
  thesisId?: string;
  revision?: number;
  seq?: number;
}

// ── Global presence pills (Unit 9) ───────────────────────────────────────

export interface PresenceUser {
  user_id: string;
  book_id: string | null;
  last_activity: string; // ISO 8601
  kind: "human" | "agent";
  status?: "thinking" | "idle";
}

export interface PresencePayload {
  users: PresenceUser[];
  generated_at: string;
}

// Payload carried by the price.tick WebSocket message (Unit 6)
export interface PriceTickPayload {
  type: "price.tick";
  thesis_id: string;
  revision: number;
  // symbol -> { prev, curr, ... } — curr is null if the symbol dropped out
  changes: Record<string, {
    prev: number | null;
    curr: number | null;
  }>;
  freshness?: Record<string, {
    source: string;
    fetchedAt: string;
    ttlSeconds: number;
    detail?: string;
  }>;
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

// ── Agent-in-room panel (Unit 11) ───────────────────────────────────────

/** One row in the ring buffer of recent LLM calls. Populated server-side by
 *  record_agent_call() in web/routes/llm.py. `snapshot_revision` is the
 *  thesis revision the agent was reasoning against at call time; null when
 *  the room has no linked book or the coordinator never committed yet. */
export interface AgentCallRow {
  ts: string;
  model: string;
  prompt_first_80: string;
  tool_calls: string[];
  latency_ms: number;
  status: "success" | "error" | "pending" | string;
  room_id: string | null;
  thesis_id: string | null;
  snapshot_revision: number | null;
}

export interface AgentLogResponse {
  rows: AgentCallRow[];
  count: number;
  fetchedAt: string;
}

export interface AgentState {
  thesis_id: string | null;
  snapshot_revision: number | null;
  default_model: string;
  last_call_ts: string | null;
  last_call_status: string | null;
  last_call_model: string | null;
}


// ── Thesis Builder Types ────────────────────────────────────────────────

export interface BuilderNode {
  id: string;
  label: string;
  type: "event" | "price" | "indicator" | "gate" | "deadline" | "conditional" | "reversal" | "constraint";
  phase: number;
  state: "monitoring" | "active" | "fired" | "approaching" | "stable" | "resolved" | "partial";
  context: string;
  x: number;
  y: number;
  probability?: number | null;
  current?: number | null;
  feeds: BuilderFeed[];
  thresholds: BuilderThreshold[];
  indicators: BuilderIndicator[];
  countdown: boolean;
  deadline?: string | null;
  irreversible: boolean;
  gatedBy: string[];
  logic?: string | null;
}

export interface BuilderFeed {
  source: "yahoo" | "polymarket" | "fred" | "eia" | "bls" | "usda" | "manual";
  symbol?: string;
  market?: string;
  series?: string;
  label?: string;
}

export interface BuilderThreshold {
  level: number;
  label: string;
  durationRequired?: string;
}

export interface BuilderIndicator {
  label: string;
  feed: string;
  value: string;
  status: "red" | "amber" | "green" | "grey";
}

export interface BuilderEdge {
  source: string;
  target: string;
  mechanism: string;
  lag: string;
  strength: number;
}

export interface BuilderInstrument {
  id: string;
  monthly: number;
  role: string;
  beta: number;
  ref: number;
  targetLow?: number | null;
  targetHigh?: number | null;
  stop?: number | null;
}

export interface BuilderScenario {
  id: string;
  name: string;
  probability: number;
  notes: string;
  overrides: Record<string, unknown>;
  portfolioImpact: Record<string, unknown>;
}

export interface BuilderMeta {
  title: string;
  claim: string;
  monthlyBudget: number;
  asOf: string;
}

export interface BuilderBook {
  id?: string;
  meta: BuilderMeta;
  nodes: BuilderNode[];
  edges: BuilderEdge[];
  instruments: Record<string, BuilderInstrument[]>;
  scenarios: BuilderScenario[];
  cascadePhases: Record<string, unknown>;
  rules: string[];
}
