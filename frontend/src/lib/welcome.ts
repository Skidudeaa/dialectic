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

// Day-in-the-life vignettes. These are concrete and reference the real
// thesis ids, binding ids, and room names; do not water them down.
export const USE_CASES: readonly UseCaseDef[] = [
  {
    id: "morning",
    time: "08:00 ET",
    title: "Morning brief — what changed overnight?",
    body:
      "Cron kicks run-all.py: every active book fetches, exports a snapshot, diffs against last night, and pushes only on change. /brief in your room paints the delta — phase advance on iran-hormuz-graph, two new approaching nodes on trump-tariffs-graph, one cross-book recession signal that aligned. You read it before the kettle boils.",
  },
  {
    id: "brent",
    time: "10:42 ET",
    title: "Brent crosses $115 — the desk moves with it",
    body:
      "Pine Script fires brent-persistence-close-above-115 at the desk. The signed webhook lands, incrementClosesObserved bumps the counter, and on the third qualifying close brent flips to fired. Both your screens update inside a second. You and Dan are arguing in chat about whether to add to XOP — @claude already sees the new state and weighs in without you pasting anything.",
  },
  {
    id: "planting",
    time: "14:00 ET",
    title: "Planting deadline approaches",
    body:
      "Countdown on planting-miss pulses amber: 17 days. The fert-shortage scenario probability bumps. Dialectic curator drops a short alert into the trump-tariffs room: \"CF setup is 3 of 4 confluence signals; planting-miss countdown < 21d.\" You don't need to be at your desk to see it.",
  },
  {
    id: "cross",
    time: "16:30 ET",
    title: "Cross-book correlation detected",
    body:
      "Both books register independent recession signals — em-stress confluence on iran-hormuz-graph and consumer-deterioration on trump-tariffs-graph cross thresholds within the same hour. The Cross-Book panel surfaces it, ranks the alignment, and links straight to the contributing nodes in each viewer.",
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
