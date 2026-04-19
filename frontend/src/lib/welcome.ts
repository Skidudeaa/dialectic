// welcome.ts — constants and types for the /welcome evergreen guide page.
// Net-new only; nothing here is consumed by the rest of the app.

export interface TocSection {
  id: string;
  label: string;
}

// Source of truth for the in-page table of contents. Keep in sync with the
// section ids rendered in pages/Welcome.tsx.
export const WELCOME_SECTIONS: readonly TocSection[] = [
  { id: "hero", label: "Trading Desk" },
  { id: "what", label: "What this is" },
  { id: "workspace", label: "The workspace" },
  { id: "engine", label: "Causal graph engine" },
  { id: "data", label: "Live data fetch" },
  { id: "tradingview", label: "TradingView" },
  { id: "builder", label: "Thesis Builder" },
  { id: "dialectic", label: "Dialectic" },
  { id: "outbox", label: "Outbox & observability" },
  { id: "llm", label: "LLM in chat" },
  { id: "stories", label: "A day on the desk" },
  { id: "cookbook", label: "Cookbook" },
  { id: "isnt", label: "What it isn't" },
  { id: "architecture", label: "Architecture" },
  { id: "roadmap", label: "What's coming" },
  { id: "links", label: "Quick links" },
] as const;

export interface PanelDef {
  id: string;
  title: string;
  tagline: string;
  bullets: readonly string[];
  // grid placement on the workspace diagram (col-start, col-span, row-start, row-span)
  col: [number, number];
  row: [number, number];
  accent: "amber" | "teal" | "purple" | "blue" | "green";
}

// The five-panel workspace, laid out to mirror the real dashboard geometry:
// chat dominates center, thesis on the right, a left rail with watchlist,
// brief/journal/predictions stacked under the right column.
export const PANELS: readonly PanelDef[] = [
  {
    id: "chat",
    title: "Chat",
    tagline: "Two analysts and three LLMs in one room.",
    bullets: [
      "@claude / @gpt / @gemini / @compare mentions",
      "Slash commands: /brief, /thesis, /diff, /predict, /watchlist",
      "Pin messages, export the room as markdown",
    ],
    col: [2, 2],
    row: [1, 2],
    accent: "amber",
  },
  {
    id: "thesis",
    title: "Thesis Viewer",
    tagline: "The causal graph as a panel, not a wall of HTML.",
    bullets: [
      "Cascade phase tracker with signpost checklist",
      "Node states colored fired / approaching / stable / gated",
      "Scenarios + countdowns + confluence scores live",
    ],
    col: [4, 1],
    row: [1, 2],
    accent: "teal",
  },
  {
    id: "predictions",
    title: "Prediction Tracker",
    tagline: "Calibrate by writing it down before the move.",
    bullets: [
      "Resolve YES/NO with timestamp",
      "Per-user accuracy stats roll up across rooms",
      "Spawned inline from chat with /predict",
    ],
    col: [1, 1],
    row: [1, 1],
    accent: "purple",
  },
  {
    id: "journal",
    title: "Trade Journal",
    tagline: "Every entry, every exit, every P&L line.",
    bullets: [
      "Direction, size, entry/exit price, realized P&L",
      "Per-room and per-book filters",
      "Feeds the canonical trade ledger downstream",
    ],
    col: [1, 1],
    row: [2, 1],
    accent: "green",
  },
  {
    id: "ticker",
    title: "Market Ticker",
    tagline: "Live watchlist that follows your book.",
    bullets: [
      "Auto-populated from the linked book's instruments",
      "Yahoo v8 + Polymarket prices, refreshed on fetch",
      "Color-coded against threshold proximity",
    ],
    col: [1, 1],
    row: [3, 1],
    accent: "blue",
  },
] as const;

export interface FeatureDef {
  id: string;
  icon: string; // lucide icon name resolved in component
  title: string;
  status: "live" | "soon";
  summary: string;
  details: readonly string[];
}

export const FEATURES: readonly FeatureDef[] = [
  {
    id: "engine",
    icon: "GitBranch",
    title: "Causal graph engine",
    status: "live",
    summary:
      "Stdlib Python evaluates each thesis as a directed graph. Topological sort, threshold checks, signal propagation, fan-in confluence scoring.",
    details: [
      "Kahn's algorithm orders nodes; each node evaluates fired / approaching / stable / gated against its thresholds.",
      "When multiple causal paths converge on the same node, confluence weighting raises confidence.",
      "Same evaluator runs in Python at generation time and mirrored in the browser for what-if scenarios.",
    ],
  },
  {
    id: "data",
    icon: "Activity",
    title: "Live data fetch",
    status: "live",
    summary:
      "Two providers, no API keys. Yahoo Finance v7 spark for prices, Polymarket Gamma API for prediction-market probabilities.",
    details: [
      "Three-pass slug matching on Polymarket (exact, substring, keyword) so seasonal markets keep resolving.",
      "Stdlib Wilder RSI / ATR / SMA computed from Yahoo OHLCV per-node, written as overlay-only tvIndicators.",
      "Schema-enforced overlay: true tripwire — derived values never flow into eval_node_state or score_confluence.",
    ],
  },
  {
    id: "tradingview",
    icon: "Webhook",
    title: "TradingView integration",
    status: "live",
    summary:
      "Pine Script alerts fire signed webhooks at the desk. Four pre-declared mutation ops, strict node-type gates, per-IP rate limits.",
    details: [
      "HMAC-SHA256 signed bodies, ±300s timestamp window, 600s nonce replay store, 8 KiB body cap.",
      "Ops: incrementClosesObserved, setNodeState, setProbability, setCurrent.",
      "Canonical bindings include brent-persistence-close-above-115, fert-close-above-700, spy-below-200dma-first-touch.",
    ],
  },
  {
    id: "builder",
    icon: "PenTool",
    title: "Thesis Builder",
    status: "live",
    summary:
      "Visual graph editor for thesis configs. Drag nodes, draw edges, validate, import/export — without hand-writing JSON.",
    details: [
      "Canvas built on the same Cytoscape topology the runtime uses, so what you draw is what propagates.",
      "Inline validation surfaces missing thresholds, dangling edges, and instrument/node link breaks.",
      "Export ships a clean JSON config that drops straight into books/ and runs end-to-end.",
    ],
  },
  {
    id: "dialectic",
    icon: "MessagesSquare",
    title: "Dialectic integration",
    status: "live",
    summary:
      "Push thesis state into Dialectic rooms so the LLM sees positions, triggers, and confluence on every turn.",
    details: [
      "Iran/Hormuz and Trump Tariffs rooms wired live; one snapshot per thesis revision.",
      "Trading Curator drops alerts into rooms when triggers fire and you're offline.",
      "Per-room memories are versioned, embedded, and recallable so LLM context stays grounded.",
    ],
  },
  {
    id: "outbox",
    icon: "Inbox",
    title: "Outbox & observability",
    status: "live",
    summary:
      "External pushes are queued, not in-band. If Dialectic is slow or down, the desk stays truthful and replays later.",
    details: [
      "Per-room outbox badge surfaces queue depth; manual Drain now button replays on demand.",
      "Failed deliveries increment attempts and reschedule; success marks delivered.",
      "Audit log at web/data/tradingview-events.jsonl persists every webhook attempt — success, auth fail, rate limit.",
    ],
  },
  {
    id: "llm",
    icon: "Bot",
    title: "LLM in chat",
    status: "live",
    summary:
      "Three models on tap, shared context, side-by-side compare. The model sees the live thesis state in every prompt.",
    details: [
      "@claude is Anthropic Claude, @gpt is OpenAI, @gemini is Google — routed through OpenRouter.",
      "@compare runs all three concurrently and streams the answers in parallel for direct A/B/C reads.",
      "Slash commands stay terse: /brief for the morning brief, /diff for what moved, /predict to log a prediction.",
    ],
  },
] as const;

export interface UseCaseDef {
  id: string;
  time: string;
  title: string;
  body: string;
}

// Day-in-the-life vignettes. Concrete journal entries — timestamp + verb,
// no connective tissue, end on a decision. Real thesis ids and bindings.
export const USE_CASES: readonly UseCaseDef[] = [
  {
    id: "morning",
    time: "08:02 ET",
    title: "Opened dashboard, /brief'd",
    body:
      "Overnight cron fired run-all.py at 07:55. iran-hormuz-graph advanced from amplification to policy-response phase; two trump-tariffs-graph nodes flipped to approaching; em-stress + consumer-deterioration aligned cross-book. Decision: hold XOP, add to SH on the open.",
  },
  {
    id: "brent",
    time: "10:42 ET",
    title: "brent-persistence-close-above-115 fired",
    body:
      "Third qualifying close lands. incrementClosesObserved → 3. brent flips to fired, em-stress confluence jumps from 0.92 to 1.30. @compare ran in chat in 4s. Decision: added 25% to XOP at $148.20, journaled the entry.",
  },
  {
    id: "planting",
    time: "14:00 ET",
    title: "Argued planting-miss EV with Dan",
    body:
      "planting-miss countdown pulsed at 17d. Argued with Dan via @compare on whether the CF setup justifies sizing up. @claude flagged the un-priced fert-shortage probability shift; @gpt countered on USDA report risk. Decision: held CF flat, set Polymarket alert at 0.55.",
  },
  {
    id: "cross",
    time: "16:30 ET",
    title: "Cross-book recession alignment surfaced",
    body:
      "Cross-Book panel ranked iran-hormuz em-stress + trump-tariffs consumer-deterioration as a concurrent recession signal inside the same hour. Clicked through to both contributing nodes. Decision: trimmed risk-on book 10%, kept SH thesis intact.",
  },
] as const;

export interface RoadmapItem {
  id: string;
  title: string;
  spec: string; // section heading from tradingdesk-web-ui-v2-spec.md
  body: string;
}

// Drawn from tradingdesk-web-ui-v2-spec.md. Keep these honest — direction, not promise.
export const ROADMAP: readonly RoadmapItem[] = [
  {
    id: "coordinator",
    title: "Runtime coordinator",
    spec: "§ Runtime Coordinator (lines 178–202)",
    body:
      "One service holds loaded definitions, schedules per-thesis fetch/evaluate cycles, serializes mutations behind per-thesis asyncio locks, and fans out websocket updates only after commit. Stops a slow Dialectic from quietly poisoning the desk.",
  },
  {
    id: "events",
    title: "Append-only events + snapshots",
    spec: "§ Refactored Runtime Model (lines 89–177)",
    body:
      "Immutable thesis defs, mutable runtime inputs, derived snapshots, and a durable event log per thesis revision. node.state_changed, phase.changed, override.applied are recorded once and replayable forever.",
  },
  {
    id: "outbox-worker",
    title: "Outbox worker for Dialectic",
    spec: "§ External Integration: Dialectic (lines 610–624)",
    body:
      "Snapshot commit inserts an outbox row; a separate worker drains. Success marks delivered, failure backs off. The desk stays truthful even when external systems aren't.",
  },
  {
    id: "freshness",
    title: "Watermarks & freshness as first-class state",
    spec: "§ Architecture Principles P6 (lines 86–88) and § Staleness rules (227–233)",
    body:
      "Every provider declares expectedIntervalSec, staleAfterSec, degradedAfterSec. Quality state is computed per thesis and shown in the UI — a live trading desk without freshness metadata is bullshit, per the spec.",
  },
  {
    id: "overrides",
    title: "Persisted manual overrides with TTL",
    spec: "§ Manual Overrides (lines 236–262)",
    body:
      "Overrides become real records — actor, reason, expiresAt, audit trail — not throwaway WebSocket messages. Both users see the same active set, scenarios stay separate from live state.",
  },
  {
    id: "clients",
    title: "Multi-platform clients",
    spec: "Implied by § Frontend Refactor + product direction",
    body:
      "Web stays the canonical operator console. iOS / Android / Windows / Mac wrappers ride the bootstrap + delta WebSocket protocol so the desk is one tap away when you're not at the keyboard.",
  },
] as const;

// External quick links — only GitHub allowed per scope. In-app links use
// react-router-dom relative routes.
export const EXTERNAL_LINKS = {
  tradingDeskRepo: "https://github.com/Skidudeaa/tradingDesk",
  dialecticRepo: "https://github.com/Skidudeaa/dialectic",
} as const;

// ─────────────────────────────────────────────────────────────────────────
// COOKBOOK
//
// Concrete recipes the user can lift and run. Every snippet is real:
// real binding ids, real book names, real slash commands. No invented
// tickers or fake bindings — Amo will spot it.

export type RecipeSurface =
  | "CHAT"
  | "THESIS"
  | "TV"
  | "BUILDER"
  | "OUTCOMES";

export interface RecipeDef {
  id: string;
  surface: RecipeSurface;
  title: string;
  /** Snippet to copy. Multi-line, exact. */
  snippet: string;
  /** Display language hint — drives the "Copy as" label. Default: text. */
  lang?: "text" | "pine" | "json" | "bash";
  /** One-line "why it matters". */
  why: string;
}

export const RECIPES: readonly RecipeDef[] = [
  // ── CHAT (5) ─────────────────────────────────────────────────────
  {
    id: "chat-pressure-test",
    surface: "CHAT",
    title: "Pressure-test a thesis",
    snippet:
      "@compare are you actually convinced the dxy-stress confluence is real, or is this just three correlated symptoms?",
    why: "Forces the three models to disagree out loud. The disagreements are the signal.",
  },
  {
    id: "chat-pre-mortem",
    surface: "CHAT",
    title: "Pre-mortem a trade",
    snippet:
      "@claude argue against the XOP long given Brent at $90 vs the $115 trigger",
    why: "Best way to find the hole in your own thesis is to make the LLM defend the other side.",
  },
  {
    id: "chat-calibrate",
    surface: "CHAT",
    title: "Calibrate a prediction",
    snippet: "/predict 70% — Brent closes above $100 by Friday",
    why: "Forces a number on a guess. Per-user accuracy stats roll up across rooms.",
  },
  {
    id: "chat-diff",
    surface: "CHAT",
    title: "Compare daily delta",
    snippet: "/diff",
    why: "Shows you exactly what changed since the last cron run — phase advances, new approaching nodes, price moves.",
  },
  {
    id: "chat-cross-book",
    surface: "CHAT",
    title: "Cross-book sweep",
    snippet:
      "@gpt which two books have the strongest recession-aligned signal right now?",
    why: "GPT cross-references all loaded snapshots. Cheaper than reading five thesis viewers.",
  },

  // ── THESIS (3) ──────────────────────────────────────────────────
  {
    id: "thesis-em-stress",
    surface: "THESIS",
    title: "Hover em-stress in iran-hormuz",
    snippet:
      "Open Thesis Viewer → iran-hormuz-graph → hover the em-stress node",
    lang: "text",
    why: "The tooltip shows every upstream contributor and its weighted contribution to the confluence score.",
  },
  {
    id: "thesis-cascade-compare",
    surface: "THESIS",
    title: "Compare cascade phases across books",
    snippet:
      "Switch the book selector: iran-hormuz-graph → trump-tariffs-graph → japan-rate-shock-graph",
    lang: "text",
    why: "Watch the WE ARE HERE marker move. Three books in different phases means three different trades.",
  },
  {
    id: "thesis-derived",
    surface: "THESIS",
    title: "Inspect a node's derivedIndicators",
    snippet:
      "Open ai-capex-unwind-graph → expand the smh node → check the RSI/ATR badges",
    lang: "text",
    why: "Wilder RSI/ATR/SMA from Yahoo OHLCV are overlay-only. They never feed eval_node_state — that's a tripwire, not a convention.",
  },

  // ── TRADINGVIEW (3) ─────────────────────────────────────────────
  {
    id: "tv-brent",
    surface: "TV",
    title: "Brent persistence, 3 closes ≥ 115",
    snippet:
      'alertcondition(\n  close > 115 and close[1] > 115 and close[2] > 115,\n  "brent-persistence",\n  "{\\"book\\":\\"iran-hormuz-graph\\",\\"bindingId\\":\\"brent-persistence-close-above-115\\",\\"value\\":\\"{{close}}\\"}"\n)',
    lang: "pine",
    why: "Pine fires; webhook lands signed; incrementClosesObserved bumps; on the third close brent flips to fired.",
  },
  {
    id: "tv-vix",
    surface: "TV",
    title: "VIX spike → japan-rate-shock",
    snippet:
      'alertcondition(\n  close > 25,\n  "vix-spike",\n  "{\\"book\\":\\"japan-rate-shock-graph\\",\\"bindingId\\":\\"vix-spike-above-25\\",\\"value\\":\\"{{close}}\\"}"\n)',
    lang: "pine",
    why: "Drops a setCurrent on the volatility node. Useful when the carry-unwind thesis needs a vol confirmation leg.",
  },
  {
    id: "tv-smh",
    surface: "TV",
    title: "SMH break of 50dma → ai-capex-unwind",
    snippet:
      'alertcondition(\n  ta.crossunder(close, ta.sma(close, 50)),\n  "smh-50dma",\n  "{\\"book\\":\\"ai-capex-unwind-graph\\",\\"bindingId\\":\\"smh-50dma-break\\",\\"value\\":\\"{{close}}\\"}"\n)',
    lang: "pine",
    why: "First-touch technical confirmation of the AI capex deceleration thesis. Cheap signal, high signal-to-noise on the daily.",
  },

  // ── BUILDER (2) ─────────────────────────────────────────────────
  {
    id: "builder-deadline",
    surface: "BUILDER",
    title: "Add a deadline node",
    snippet:
      '{\n  "id": "planting-miss",\n  "type": "deadline",\n  "label": "US corn planting cutoff",\n  "deadline": "2026-05-25",\n  "thresholds": { "approachingDays": 30, "firedDays": 0 }\n}',
    lang: "json",
    why: "Drop into nodes[] of any book JSON. Countdown pulses amber once approachingDays hits, fires when the date passes.",
  },
  {
    id: "builder-wire",
    surface: "BUILDER",
    title: "Wire two nodes",
    snippet:
      "1. Drag from output port of node A to body of node B.\n2. Click the new edge.\n3. Set mechanism (causal sentence), lag (hours/days), amplification (0.0–2.0).",
    lang: "text",
    why: "Edges aren't decoration — propagation reads mechanism, lag, and amp every cycle. Be precise on lag; that's where macro trades live or die.",
  },

  // ── OUTCOMES (2) ────────────────────────────────────────────────
  {
    id: "out-brief",
    surface: "OUTCOMES",
    title: "Daily morning brief",
    snippet:
      "/brief                        # in your active room, any time after 08:00 ET",
    lang: "text",
    why: "Cron picks up the snapshot at 07:55. /brief renders state + cross-book signals + ledger summary in one paste. Read it before the kettle boils.",
  },
  {
    id: "out-outbox",
    surface: "OUTCOMES",
    title: "Drain the outbox manually",
    snippet:
      'curl -X POST "$URL/api/bridge/outbox/replay" \\\n  -H "Authorization: Bearer $TOKEN" \\\n  -d \'{}\'',
    lang: "bash",
    why: "Use when Dialectic was slow / down and you need to flush queued snapshots immediately instead of waiting for the next worker tick.",
  },
] as const;

// ─────────────────────────────────────────────────────────────────────────
// WHAT THIS ISN'T — sets scope. One line each, no prose.

export interface NegativeDef {
  id: string;
  title: string;
  detail: string;
}

export const NEGATIVES: readonly NegativeDef[] = [
  {
    id: "not-daytrading",
    title: "Not a daytrading tool",
    detail: "Graphs evaluate every few minutes, not every tick.",
  },
  {
    id: "not-tracker",
    title: "Not a portfolio tracker",
    detail: "No broker integration, no real fills, no live P&L.",
  },
  {
    id: "not-backtester",
    title: "Not a backtester",
    detail: "Propagation is rule-driven, not stat-driven.",
  },
  {
    id: "not-saas",
    title: "Not a multi-tenant SaaS",
    detail: "Built for two analysts. No auth scaffolding for n+1.",
  },
  {
    id: "not-intraday",
    title: "Not for one-off intraday plays",
    detail: "If the trade isn't tied to a thesis node, it doesn't belong here.",
  },
] as const;
