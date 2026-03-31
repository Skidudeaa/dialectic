# Trading Desk

## The Problem

Every macro trader does the same thing in their head: if Hormuz closes, oil spikes. If oil spikes, diesel follows. If diesel stays above $5, truckers go underwater. If truckers go underwater, employment gets hit 3 months later. If employment gets hit while fertilizer is disrupted and planting season passes, you get a food spike that breaks emerging markets.

Everyone thinks in transmission chains. Nobody has a tool that actually maps them, tracks where you are in the cascade, enforces the logic, and tells you what to do with your portfolio at each node.

We built that tool.

---

## What It Is

A causal reasoning engine for macro trading. You model your thesis as a directed graph — nodes are observable economic states, edges are the transmission mechanisms with lags and strengths. The engine propagates signals through the graph, scores confluence where multiple paths converge, and generates an interactive HTML dashboard you can open in any browser.

It's not a trading bot. It's not a charting platform. It's a structured judgment system where the math enforces consistency: if you believe A, B, and C, then D follows with probability X and portfolio impact Y. You bring the thesis. The system makes sure you're honest about what it implies.

---

## What You Get

### The Thesis Graph

You define your macro thesis as a directed acyclic graph:

```
HORMUZ CLOSURE
    │
    ├── immediate ──→ BRENT (>$115 persistence, >$135 escalation, >$155 extreme)
    │                    │
    │                    └── 1-2 weeks ──→ DIESEL (>$5.00 demand destruction)
    │                                        │
    │                                        └── 2-4 weeks ──→ FREIGHT CRUSH
    │                                                            │
    │                                                            └── 1-3 months ──→ EMPLOYMENT
    │                                                                                   │
    │                                                                                   ├──→ DEMAND DESTRUCTION
    │                                                                                   │
    ├── 1 week ──→ FERTILIZER STRESS                                                   │
    │                 │                                                                 │
    │                 └── date-gated Apr 15 ──→ PLANTING MISS (irreversible)            │
    │                                              │                                    │
    │                                              └── 3-6 months ──→ FOOD SPIKE        │
    │                                                                    │               │
    │                                                                    └──→ EM STRESS ←┘
    │                                                                           ↑
    └── 1-2 weeks ──→ DOLLAR STRESS ──→ EM CURRENCY COLLAPSE ─────────────────┘
```

Every node has: live data feeds, threshold levels, current state (fired / approaching / stable / gated). Every edge has: the causal mechanism, estimated lag, transmission strength (0-1), and amplification factor.

The engine uses Kahn's topological sort to propagate signals through the graph. When an upstream node fires, all downstream nodes light up with estimated timing. When three independent paths converge on the same node (EM stress gets hit by food, currency, and employment simultaneously), the system scores that confluence — high fan-in means high confidence.

This isn't a model that generates predictions. It's a model that enforces the implications of your own beliefs.

### Five-Tab Interactive Dashboard

One command generates a self-contained HTML file (~750 KB, works offline, no server) with five tabs:

**Graph** — Interactive Cytoscape.js DAG. Nodes colored by state. Edges show transmission mechanisms on hover. Click any node to expand: data feeds, current values vs. thresholds, linked instruments, context notes. You see the entire thesis at a glance and immediately spot what's lit up.

**Cascade** — "WE ARE HERE" five-phase crisis tracker. Each phase has observable signposts as a checklist:

| Phase | Status | Key Signposts |
|---|---|---|
| 1. Shock | COMPLETE | VIX > 30 (31.05), oil +53%, physical shortages in AU/PH/India |
| 2. Transmission | STARTING | PMI employment negative, diesel > $5.00 ($5.38), freight margins destroyed |
| 3. Amplification | APPROACHING | Claims rising, EM currencies breaking, credit spreads |
| 4. Policy Response | WATCHING | SPR releases started (Japan 80M bbl), rate cuts not yet |
| 5. Resolution | NOT YET | — |

This is how you stop yourself from front-running Phase 4 when you're still in Phase 2. The cascade tracker makes the current state visible, not assumed.

**Scenarios** — Defined as overrides on graph nodes with probability weights:

| Scenario | P(%) | Brent | Key Impact |
|---|---|---|---|
| Hormuz reopens April 1 | 10% | $90 | XOP -12%, add VXUS, rebuild SGOV |
| Closed through May | 45% | $135 | Layer 3 activates, planting missed, EM stress accelerates |
| Kharg Island attacked | 15% | $155 | All nodes fire, full deployment |
| Selective transit continues | 30% | $115 | Current state, slow bleed, yuan tolls |

Toggle between scenarios and see the portfolio impact waterfall — per-instrument direction, estimated move, and recommended action. The probability-weighted expected portfolio value is always visible so you trade the distribution, not a single scenario.

**Portfolio** — Every instrument is positioned at a specific graph node. XOP/XLE/IXC sit at the Brent node. CF/NTR sit at the fertilizer stress node. GLD sits at dollar stress. Each instrument shows: entry price, target range, stop, monthly allocation, beta to its node, and current R:R.

Overlays only unlock when their gate conditions fire. The services trade (OIH/HAL/SLB) requires rig count confirmation AND the curve spread below 20%. The dashboard enforces this — you literally can't front-run the trade the framework says isn't ready. That was the single biggest error in our original Hormuz exchange, and the system now prevents it structurally.

Total budget allocation across two theses: $14,000/month, with $1,200/month in SGOV as deployment ammo that flows along graph edges to active nodes.

**Journal** — Decision audit trail linked to specific graph nodes. What triggered, what you did, what you chose not to do. Three months from now you can trace exactly what you thought and when — that's how you develop judgment instead of just collecting P&L.

### Live Data

One flag pulls live prices from two sources:

- **Yahoo Finance** — ETFs, futures, FX, indices, curve spreads (auto-calculates front/deferred backwardation percentage)
- **Polymarket** — prediction market probabilities mapped directly onto graph nodes (Hormuz closure probability = 68.5% from the us-iran-april-30 market)

When live data arrives, the dashboard re-evaluates every node in the browser. Change a market input and watch signals re-propagate through the graph in real time. "What happens if Brent hits $135?" — change the input, watch diesel fire, freight cascade, employment light up with a 1-3 month lag estimate.

### Gates, Constraints, and Deadlines

Not every node fires just because its upstream fires. The system models three kinds of structural barriers:

- **Gates** — a node won't fire until a gating condition is met. Services recovery is gated by rig count confirmation (flat or rising 2 consecutive weeks). Rig count is falling. The gate stays closed.
- **Constraints** — even if the gate opens, a constraint can block it. Services is constrained by curve shape (front > 20% over 6-month deferred = prompt tightness, not capex recovery). The curve is at 15%. Even if rigs turn, the constraint blocks.
- **Deadlines** — irreversible, date-gated nodes. Planting cycle miss has an April 15 deadline. If fertilizer stress persists through that date, 93 million acres of corn don't get planted. That crop is gone. The dashboard counts it down: 17 days remaining.

### Confluence Scoring

When multiple independent causal paths converge on the same node, the system scores convergence strength. EM sovereign stress is the primary confluence node — it gets hit by:

1. Food price spike (via fertilizer → planting miss → food)
2. EM currency collapse (via dollar stress → petrodollar squeeze)
3. Employment destruction (via diesel → freight → layoffs)

Three independent transmission chains arriving at the same destination. That's not correlation — it's causal convergence. Highest conviction downstream.

### Historical Analogs

Calibration against prior episodes:

| Analog | Similarity | Key Lesson |
|---|---|---|
| **2008 Oil Spike** | High | Oil $90 → $147 → $32. Employment lag: 3 months from peak. Demand destruction is the cure. |
| **1979 Iranian Revolution** | Very High | Gulf disruption + panic = 2.5x price. Deep recession + high inflation. Most direct analog. |

The 2008 template gives us the lag structure: peak-to-employment is 3 months, peak-to-collapse is 5 months. We're 4 weeks into the current crisis. The analog says employment impact arrives late June 2026.

---

## Active Theses

### Iran/Hormuz Oil Shock

16 nodes, 14 edges, $8,000/month budget. Models the full transmission chain from Strait closure through oil → diesel → freight → employment → demand destruction, with a parallel path through fertilizer → planting → food → EM stress. The planting deadline (April 15) creates an irreversible fork — if fertilizer stays elevated, that crop is gone and Layer 3 activates on a 6-month fuse.

Current state: Phase 1 (Shock) complete, Phase 2 (Transmission) starting. Hormuz effectively closed since Feb 28. Selective transit for China/Russia/India. Brent at $112.57 (+53% from pre-crisis). Diesel at $5.38 (second time in history above $5). 17 days to planting deadline.

### Trump Tariff Escalation

15 nodes, 18 edges, $6,000/month budget. Models tariff shock → input costs → retail prices → consumer confidence → employment, with parallel paths through supply chain disruption → auto sector stress and agricultural retaliation → rural economy. The Section 122 expiration on July 24 is the pivot date — trade the policy uncertainty, not the tariffs themselves.

Current state: Effective tariff rate 13.7% (highest since Smoot-Hawley). SCOTUS struck down IEEPA tariffs 6-3, Trump pivoted to Section 122. China at 34%, autos at 25%, advanced chips at 25%. PPI goods inflation at 5.8% annualized.

---

## Dialectic Integration

This is the multiplier.

tradingDesk pushes evaluated thesis state into Dialectic as structured context. The snapshot includes: every node state, confluence scores, cascade phase, countdown timers, market prices, scenario impacts, and portfolio summary — all as structured JSON that gets injected into the LLM's prompt.

### What That Means in Practice

**The LLM becomes a fully-informed third participant in your trading discussions.**

When Dan says "should we add to CF?" — the LLM doesn't guess. It responds: "Fertilizer stress is at 97.6% of threshold, 17 days to planting deadline, Kharg scenario shows CF +30%, but the probability-weighted move is lower because reopen-apr1 (10%) has CF at -8%. Current R:R at entry is 1.3:1 to low target."

When you disagree — "I think services are coming back" — the LLM points at the graph: rig count falling, gulf offshore down 39% YoY, services node gated by rig-confirm (not fired), constrained by curve shape at 15% (threshold 20%). The framework you both agreed to says don't force this trade. It's not the LLM's opinion. It's your own model enforcing your own rules back at you.

When you're asleep and Brent crosses $115, the Trading Curator drops a message in the room: "Persistence trigger approaching — $115 for 3 closes. Dan, if this holds through Wednesday, the framework says deploy $400 SGOV → XOP."

### Data Flow

```
thesisgraph.py --fetch --export-state
        │
        ▼
   Snapshot JSON (node states, confluence, cascade phase,
                   countdowns, market prices, scenarios, portfolio)
        │
        ▼
   diff-snapshots.py (only push what changed — no noise)
        │
        ▼
   push-to-dialectic.py → POST /rooms/{id}/trading/snapshot
        │
        ├─→ Stored as room-scoped memory (versioned, searchable)
        ├─→ Broadcast to connected clients (WebSocket)
        ├─→ Injected into every LLM prompt in the room
        └─→ If user offline → Trading Curator generates alert
```

Only deltas get pushed. Node fires, confluence shifts, countdown ticks, market moves past a threshold — that's an update. Brent drifts from $112.50 to $112.70 — that's noise, not pushed.

### The Trading Curator

An async alert system. When a snapshot arrives and one participant is offline, the curator generates a message in the room:

> Freight node just fired — diesel at $5.38 sustained above $5.25 demand destruction threshold for 2 weeks. This cascades to employment with a 1-3 month lag per the 2008 template. XOP position is +11.6% to low target with 1.3:1 R:R. Planting deadline: 17 days. If fertilizer stays above $700, Layer 3 activates.

You wake up, open Dialectic, and see exactly what moved while you were gone — structured, specific, grounded in the graph you built.

### What This Gets You

**Before:** You and Dan talk about markets. The LLM tries to help but has no idea about your positions, triggers, or thesis structure. You switch to a different tool to check the graph, then go back to discuss. Context is lost. The LLM gives generic macro takes.

**After:** The LLM sees the thesis graph in real-time. Every conversation about markets is grounded in your actual positions, your actual trigger levels, your actual cascade state, and your actual scenarios with probability weights. Disagreements become specific — which node, which edge, which lag estimate, which probability — instead of vibes. And the system alerts you when the world changes while you're not looking.

---

## How It Works Together

The full loop:

1. **Model your thesis** as a causal graph (JSON config — one per thesis)
2. **Generate the dashboard** — interactive HTML with graph, cascade tracker, scenarios, portfolio, journal
3. **Pull live data** — Yahoo Finance prices + Polymarket probabilities flow into graph nodes
4. **Evaluate the graph** — propagation engine fires nodes, scores confluence, updates cascade phase
5. **Export state** — structured snapshot of the entire evaluated graph
6. **Detect changes** — diff against previous snapshot, only surface what moved
7. **Push to Dialectic** — thesis state becomes LLM context in your trading room
8. **Discuss with full context** — the LLM references your graph when you talk about markets
9. **Get alerted** — when a trigger fires while you're offline, the curator tells you what happened and what the framework says to do
10. **Log decisions** — journal entries linked to specific nodes create an audit trail for developing judgment

The dashboard is always there for deep analysis — open it, change inputs, trace causality, toggle scenarios. Dialectic is for real-time collaboration where the LLM participates as an informed partner. They reinforce each other.

---

## Technical Details

- **Zero external Python dependencies** — stdlib only. Runs anywhere with Python 3.10+.
- **Single-file HTML output** — ~750 KB with inlined Cytoscape.js + dagre. Works offline, no server.
- **118 tests** across 5 test files (propagation, export, diff, bridge, E2E pipeline).
- **Propagation engine runs twice** — once in Python at generation time, once in browser JavaScript for real-time recalculation on input changes.
- **JSON config per thesis** — all thesis logic, instruments, scenarios, and rules in one file. Version-controlled, diffable, portable.

---

## The Point

Every macro trader thinks in causal chains. Nobody has a tool that maps them, propagates them, enforces their implications against a portfolio, tracks where you are in the cascade, integrates live data and prediction market probabilities, and feeds all of that into a collaborative AI-assisted discussion where the LLM actually knows what you own, what you're watching, and what the framework says to do next.

Now we do.
