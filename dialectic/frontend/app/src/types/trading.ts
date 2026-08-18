// Trading relay contracts — shapes sampled from the LIVE tradingDesk
// payloads on 2026-08-14 (structure via /api/bridge/structure, the rest via
// the commands the LLM's tool loop exercises daily). The relay
// (api/trading_relay.py) proxies them verbatim; nothing is reshaped
// server-side, so these types ARE the desk's own vocabulary.

/** One cockpit feed's state. The spec (design v2 §12.4) demands loading,
 * no-data and failed be DISTINCT: 'empty' is a positive "nothing here"
 * (unbound room, no changes this hour), 'unavailable' is a failed fetch —
 * with the last good data retained so surfaces show stale-but-real over
 * blank. */
export interface TradingSlice<T> {
  status: 'loading' | 'ready' | 'empty' | 'unavailable';
  data?: T;
  error?: string;
  fetchedAt?: number; // Date.now() of the last successful fetch
}

export interface ThesisStructureNode {
  id: string;
  label: string;
  type: string; // event | market | policy | ... (palette key, open set)
  phase: number; // 1-5 cascade column
  state: string; // authoring-time state; live state overlays from snapshot
  context?: string;
  x: number; // persisted builder position or server phase-column fallback
  y: number;
  probability?: number | null;
  current?: unknown;
  feeds?: unknown[];
  thresholds?: unknown[];
  indicators?: unknown[];
  countdown?: boolean;
  deadline?: string | null;
  irreversible?: boolean;
  gatedBy?: string[];
  logic?: string | null;
}

export interface ThesisStructureEdge {
  source: string;
  target: string;
  mechanism: string;
  lag: string;
  strength: number;
}

export interface ThesisScenario {
  id: string;
  name?: string;
  probability?: number;
  notes?: string;
  [k: string]: unknown;
}

export interface ThesisStructure {
  id: string;
  meta: { title: string; claim?: string; dialecticRoomId?: string };
  nodes: ThesisStructureNode[];
  edges: ThesisStructureEdge[];
  scenarios: ThesisScenario[];
  cascadePhases?: Record<string, unknown>;
  instruments?: Record<string, unknown>;
}

export interface Quote {
  symbol: string;
  price: number;
  source: string;
  node_id?: string;
}

export interface PolymarketOdd {
  slug: string;
  probability: number;
}

export interface TradePredicate {
  kind: string;
  node_id?: string;
  expected?: string;
  allowed?: string[];
  path?: string;
  op?: string;
  value?: number;
  days?: number;
  load_bearing?: boolean;
}

export interface OpenTrade {
  trade_id: string;
  ticker: string;
  predicates: TradePredicate[];
  ref_price?: number;
  book?: string;
  [k: string]: unknown;
}

export interface OpenTrades {
  count: number;
  trades: OpenTrade[];
}

export interface ThesisDiff {
  hasChanges: boolean;
  stateChanges: { nodeId?: string; old?: string; new?: string; [k: string]: unknown }[];
  confluenceChanges: Record<string, unknown>;
  countdownChanges: unknown[];
  marketChanges: Record<string, unknown>;
  cascadePhaseChange: unknown;
  scenarioChanges: Record<string, unknown>;
  portfolioChanges: Record<string, unknown>;
  newNodes: string[];
  removedNodes: string[];
  tvIndicatorShifts: Record<string, unknown>;
}

export interface MorningBrief {
  book_id: string;
  brief: string;
}

export interface NewsItem {
  title: string;
  url: string;
  seendate?: string;
  domain?: string;
}

export interface ThesisNews {
  articles: NewsItem[];
  note?: string;
}

export interface ScenarioEvaluation {
  baseRevision?: number;
  scenarioId: string;
  label?: string;
  probability?: number;
  changedNodes?: Record<string, { old: string; new: string }>;
  portfolioImpact?: Record<
    string,
    { pctImpact: number; dollarImpact: number; from?: string; to?: string }
  >;
  [k: string]: unknown;
}

/** One derived position row from td's _book_view — replayed from the fill
 * ledger, priced off the desk's quote cache (fallback chain: live quote →
 * latest mark close → entry basis). */
export interface PortfolioPosition {
  symbol: string;
  qty: number;
  avg_cost: number;
  price: number;
  value: number;
  unrealized: number;
}

/** One nightly equity mark. The relay strips book_id before this reaches
 * the browser; the row shape is otherwise td's own. */
export interface PortfolioMark {
  mark_date: string;
  equity: number;
  spy_close?: number | null;
  positions?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface PortfolioBenchmarkPoint {
  mark_date: string;
  value: number;
}

/** The room's paper book, filtered out of td's all-books read by the relay.
 * `spy_baseline` is the UNITIZED benchmark — dated cash flows buy SPY units
 * at each mark — and `price_return_only` says no dividends are modeled on
 * either side of the comparison. */
export interface Portfolio {
  cash: number;
  positions: PortfolioPosition[];
  equity: number;
  inception?: string | null;
  flows?: { date: string; amount: number }[];
  marks: PortfolioMark[];
  spy_baseline: PortfolioBenchmarkPoint[];
  spy_baseline_now?: number | null;
  price_return_only?: boolean;
}

/** The v3 snapshot's alert events — shape per td's build_v3_payload:
 * [{event_type, severity, node_id, old_value, new_value}]. Typed here
 * because the snapshot type predates them. */
export interface AlertEvent {
  event_type?: string;
  severity?: string;
  node_id?: string;
  old_value?: unknown;
  new_value?: unknown;
  [k: string]: unknown;
}
