# tradingDesk — Project Plan

## What This Is

A causal reasoning engine for macro trading. You model the world as a directed graph of transmission chains — oil shock → diesel → freight → employment → demand destruction — and the system propagates data, probabilities, and portfolio impact through that graph in real time.

Not a dashboard generator. Not a portfolio tracker. A **structured notebook for expert judgment** where the math enforces consistency: if you believe A, B, and C, then D follows with probability X and portfolio impact Y.

The thesis IS the graph. The portfolio IS a set of positions at specific nodes. The triggers ARE threshold crossings that propagate downstream. Prediction markets ARE probability weights on the graph. Historical analogs ARE calibration for the transmission lags.

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      THESIS GRAPH                           │
│                                                             │
│  A directed acyclic graph where:                            │
│  • Nodes = observable economic states                       │
│  • Edges = causal transmission channels with lags           │
│  • Each node has: data feeds, thresholds, instruments       │
│  • Each edge has: mechanism, strength, estimated lag         │
│                                                             │
│  ┌──────────┐    3d     ┌──────┐   2wk    ┌────────┐      │
│  │ HORMUZ   │──────────→│BRENT │─────────→│ DIESEL │      │
│  │ closure  │           │>$130 │          │>$6/gal │      │
│  └────┬─────┘           └──┬───┘          └───┬────┘      │
│       │                    │                   │            │
│       │ 1wk          1mo  │              4wk  │            │
│       ▼                    ▼                   ▼            │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ FERT     │    │ DXY FUNDING  │    │ FREIGHT      │      │
│  │ SHORTAGE │    │ STRESS       │    │ CRUSH        │      │
│  │ >$700/mt │    │ DXY > 102    │    │ +40% cost    │      │
│  └────┬─────┘    └──────┬───────┘    └──────┬───────┘      │
│       │                 │                    │              │
│       │ DATE-GATED      │               1-3mo│              │
│       ▼ Apr 15          ▼                    ▼              │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ PLANTING │    │ EM CURRENCY  │    │ EMPLOYMENT   │      │
│  │ MISS     │    │ COLLAPSE     │    │ DESTRUCTION  │      │
│  └────┬─────┘    └──────┬───────┘    └──────┬───────┘      │
│       │                 │                    │              │
│       │  3-6mo          │                    │              │
│       ▼                 ▼                    ▼              │
│  ┌──────────┐    ┌────────────────────────────────┐        │
│  │ FOOD     │───→│   EM SOVEREIGN STRESS          │←───────│
│  │ SPIKE    │    │   (3 paths converge = strong)  │        │
│  └──────────┘    └────────────────────────────────┘        │
│                         SIGNAL CONFLUENCE                   │
└─────────────────────────────────────────────────────────────┘
```

### The Five Layers

**1. Thesis Graph** — the causal DAG
- Nodes are observable states with data feeds (Yahoo, EIA, FRED, Polymarket)
- Edges are transmission channels with mechanisms, amplification factors, and time lags
- When a node crosses its threshold, downstream nodes light up as "approaching" based on estimated lag
- Signal confluence: when multiple independent paths reach the same node, that's a stronger signal (fan-in analysis)

**2. Cascade Tracker** — "we are HERE"
- Five crisis phases: Shock → Transmission → Amplification → Policy Response → Resolution
- Each phase has observable signposts (checklist-based, not ML)
- Leading vs. lagging indicators at each level
- The 2008 template as calibration: peak-to-employment lag was 3 months
- Current state: Phase 1 (physical shortages) COMPLETE, Phase 2 (transmission) STARTING

**3. Scenario Engine** — "what if"
- Scenarios defined as overrides on graph nodes: "Hormuz reopens April 1" sets hormuz.state = resolved
- Propagate through the graph using conditional probabilities
- Bayesian belief propagation: P(planting miss) cascades down from P(US enters Iran) = 68.5%
- Portfolio impact per scenario: factor betas × scenario shocks = waterfall chart
- Side-by-side scenario comparison

**4. Probability Overlay** — prediction markets on the graph
- Polymarket/Kalshi probabilities mapped onto specific graph nodes
- Not a separate tracker — integrated into the graph as node probability weights
- The crude oil 29-strike event is a probability distribution on the "brent" node
- Kalshi CPI/Fed/GDP predictions weight the macro transmission path
- Disagreement detection: when your estimate diverges from the market

**5. Portfolio Layer** — instruments at graph nodes
- Each instrument is positioned at one or more graph nodes
- XOP at "brent" node, CF/NTR at "fert-shortage" node, GLD at "dxy-stress" node
- Portfolio stress test: propagate scenario through graph → compute position impact
- The commodity book becomes a VIEW of positions mapped onto the graph
- SGOV deployments are MOVES along the graph — capital flowing from reserve to active nodes

---

## Graph Definition Schema

The JSON config replaces flat trigger lists with a graph definition:

```json
{
  "meta": {
    "title": "Iran/Hormuz Thesis — March 2026",
    "asOf": "2026-03-29",
    "claim": "Oil shock transmits through diesel→freight→employment (Layer 2) and fertilizer→food→EM (Layer 3). Services lag. Don't front-run."
  },

  "nodes": [
    {
      "id": "hormuz",
      "label": "Hormuz Closure",
      "type": "event",
      "phase": 1,
      "state": "active",
      "feeds": [{"source": "polymarket", "market": "us-iran-april-30"}],
      "probability": 0.685,
      "indicators": [
        {"label": "Tanker transit", "feed": "manual", "value": "-70%", "status": "red"},
        {"label": "Ships anchored", "feed": "manual", "value": "150+", "status": "red"}
      ]
    },
    {
      "id": "brent",
      "label": "Brent Persistence",
      "type": "price",
      "phase": 1,
      "feeds": [{"source": "yahoo", "symbol": "BZ=F"}],
      "current": 112.57,
      "thresholds": [
        {"level": 115, "label": "persistence", "closesRequired": 3},
        {"level": 135, "label": "escalation"},
        {"level": 155, "label": "extreme"}
      ],
      "regimes": {
        "base": {"max": 114.99, "color": "#6E8FAD"},
        "elevated": {"min": 115, "max": 134.99, "color": "#E69A4C"},
        "escalation": {"min": 135, "max": 154.99, "color": "#E05555"},
        "extreme": {"min": 155, "color": "#D32F2F"}
      }
    },
    {
      "id": "diesel",
      "label": "Diesel Stress",
      "type": "price",
      "phase": 2,
      "feeds": [{"source": "eia", "series": "EMD_EPD2D_PTE_NUS_DPG"}],
      "current": 5.38,
      "thresholds": [
        {"level": 4.75, "label": "GDP drag begins"},
        {"level": 5.00, "label": "demand destruction"},
        {"level": 5.25, "label": "recession probability >40%"},
        {"level": 5.50, "label": "sustained stress", "durationRequired": "2 weeks"}
      ],
      "context": "Second time in history diesel crossed $5. Crack spread doubled: $30→$70/bbl."
    },
    {
      "id": "freight",
      "label": "Freight Crush",
      "type": "indicator",
      "phase": 2,
      "feeds": [
        {"source": "yahoo", "symbol": "BDRY", "label": "Baltic Dry"},
        {"source": "yahoo", "symbol": "BWET", "label": "Tanker ETF"}
      ],
      "indicators": [
        {"label": "Owner-op margin", "feed": "manual", "value": "-$0.20/mile", "status": "red"},
        {"label": "Fuel surcharge recovery", "feed": "manual", "value": "60-70%", "status": "amber"}
      ],
      "context": "CDL Life: $5.38 diesel is 'the nail in the coffin' for owner-operators."
    },
    {
      "id": "employment",
      "label": "Employment Destruction",
      "type": "indicator",
      "phase": 2,
      "feeds": [
        {"source": "fred", "series": "ICSA", "label": "Initial Claims"},
        {"source": "bls", "series": "CES0000000001", "label": "NFP"},
        {"source": "yahoo", "symbol": "^PMI", "label": "PMI"}
      ],
      "indicators": [
        {"label": "PMI employment", "value": "negative (first time in 12mo)", "status": "red"},
        {"label": "Australia PMI", "value": "47.0 (from 52.4)", "status": "red"}
      ],
      "historicalLag": "3 months from oil peak (2008 template)"
    },
    {
      "id": "fert-shortage",
      "label": "Fertilizer Stress",
      "type": "price",
      "phase": 1,
      "feeds": [{"source": "usda", "dataset": "nola-urea"}],
      "current": 683,
      "thresholds": [
        {"level": 700, "label": "stress threshold"},
        {"level": 822, "label": "retail already here (Mar 25 USDA)"}
      ],
      "context": "Hormuz handles ~30% of traded fertilizer. Urea up 28-50%. CF is #1 S&P performer in March."
    },
    {
      "id": "planting-miss",
      "label": "Planting Cycle Miss",
      "type": "deadline",
      "phase": 3,
      "deadline": "2026-04-15",
      "conditions": ["fert-shortage.active", "diesel.above_5.50"],
      "logic": "any",
      "irreversible": true,
      "countdown": true,
      "context": "US corn belt: mid-April to mid-May window. 93M acres. Nitrogen is the limiting nutrient. If missed, that crop is gone."
    },
    {
      "id": "food-spike",
      "label": "Food Price Spike",
      "type": "indicator",
      "phase": 3,
      "feeds": [
        {"source": "yahoo", "symbol": "ZW=F", "label": "Wheat"},
        {"source": "yahoo", "symbol": "ZC=F", "label": "Corn"},
        {"source": "fred", "series": "CPIUFDSL", "label": "Food CPI"}
      ],
      "lag": "6-12 months from fertilizer spike"
    },
    {
      "id": "dxy-stress",
      "label": "Dollar Funding Stress",
      "type": "indicator",
      "phase": 2,
      "feeds": [
        {"source": "yahoo", "symbol": "DX-Y.NYB", "label": "DXY"},
        {"source": "fred", "series": "DTWEXBGS", "label": "Trade-Weighted USD"}
      ],
      "current": 100.18,
      "thresholds": [{"level": 102, "label": "squeeze intensifies"}],
      "context": "DXY strengthening from oil-import dollar demand, not US strength. Classic petrodollar squeeze."
    },
    {
      "id": "em-currency",
      "label": "EM Currency Collapse",
      "type": "indicator",
      "phase": 2,
      "feeds": [
        {"source": "yahoo", "symbol": "USDZAR=X", "label": "USD/ZAR"},
        {"source": "yahoo", "symbol": "USDINR=X", "label": "USD/INR"},
        {"source": "yahoo", "symbol": "USDEGP=X", "label": "USD/EGP"}
      ]
    },
    {
      "id": "em-stress",
      "label": "EM Sovereign Stress",
      "type": "indicator",
      "phase": 3,
      "feeds": [{"source": "fred", "series": "BAMLHE00EHYIOAS", "label": "EM HY OAS"}],
      "confluence": ["food-spike", "em-currency", "employment"],
      "indicators": [
        {"label": "Egypt CDS", "value": "~314 bps (+44 from pre-war)", "status": "amber"},
        {"label": "EM bond issuance", "value": "frozen", "status": "red"},
        {"label": "Hot money flight", "value": "$1.4B in 8 days (Egypt)", "status": "red"}
      ],
      "context": "3 independent paths converge here. Signal confluence = high confidence downstream."
    },
    {
      "id": "demand-destruction",
      "label": "Demand Destruction",
      "type": "indicator",
      "phase": 3,
      "feeds": [
        {"source": "yahoo", "symbol": "CL=F", "label": "WTI (collapse signal)"},
        {"source": "fred", "series": "VIXCLS", "label": "VIX"}
      ],
      "context": "2008 template: oil collapsed from $147→$32 in 5 months as demand was destroyed. The cure for high prices is high prices."
    },
    {
      "id": "curve",
      "label": "Curve Shape",
      "type": "constraint",
      "feeds": [{"source": "yahoo", "symbols": ["BZK26.NYM", "BZV26.NYM"]}],
      "current": 15,
      "threshold": 20,
      "constrains": ["services"],
      "context": "Front > 20% over 6m deferred = prompt tightness, not capex recovery. Blocks services."
    },
    {
      "id": "rig-confirm",
      "label": "Rig Confirmation",
      "type": "gate",
      "feeds": [{"source": "manual", "label": "Baker Hughes (Fridays)"}],
      "current": 543,
      "condition": "flat or rising 2 consecutive weeks",
      "gates": ["services"],
      "context": "Gulf offshore down 39%. SLB/HAL guiding activity lower. Do NOT force this trade."
    },
    {
      "id": "services",
      "label": "Services Recovery",
      "type": "conditional",
      "gatedBy": ["rig-confirm"],
      "constrainedBy": ["curve"],
      "context": "The single biggest error in the original exchange: front-running a services boom that the operating data don't support."
    },
    {
      "id": "de-escalation",
      "label": "De-escalation",
      "type": "reversal",
      "feeds": [{"source": "yahoo", "symbol": "BZ=F"}],
      "threshold": 95,
      "closesRequired": 5,
      "additionalCondition": "restored Hormuz traffic",
      "action": "Cut XOP 1/3, CF/NTR 1/4, close tankers, rebuild VXUS + SGOV",
      "context": "Don't buy the dip in services. Add IXC/XLE first, then XOP, only restore OIH after activity data."
    }
  ],

  "edges": [
    {"from": "hormuz", "to": "brent", "mechanism": "20% global seaborne oil disrupted", "lag": "immediate", "strength": 0.95},
    {"from": "hormuz", "to": "fert-shortage", "mechanism": "30% of traded fertilizer, 50% of urea+sulfur", "lag": "1 week", "strength": 0.90},
    {"from": "hormuz", "to": "dxy-stress", "mechanism": "oil-import dollar demand surge", "lag": "1-2 weeks", "strength": 0.70},
    {"from": "brent", "to": "diesel", "mechanism": "crack spread transmission", "lag": "1-2 weeks", "strength": 0.85, "amplification": 1.2},
    {"from": "diesel", "to": "freight", "mechanism": "fuel = 20-30% of carrier opex", "lag": "2-4 weeks", "strength": 0.80},
    {"from": "freight", "to": "employment", "mechanism": "margin destruction → capacity exits → layoffs", "lag": "1-3 months", "strength": 0.75},
    {"from": "fert-shortage", "to": "planting-miss", "mechanism": "nitrogen unavailable for corn belt", "lag": "date-gated Apr 15", "strength": 0.85},
    {"from": "planting-miss", "to": "food-spike", "mechanism": "yield loss 10-30% on corn", "lag": "3-6 months", "strength": 0.80},
    {"from": "food-spike", "to": "em-stress", "mechanism": "food = 30-50% of CPI in vulnerable EMs", "lag": "1-3 months", "strength": 0.75},
    {"from": "dxy-stress", "to": "em-currency", "mechanism": "dollar squeeze on oil importers", "lag": "2-4 weeks", "strength": 0.80},
    {"from": "em-currency", "to": "em-stress", "mechanism": "FX depreciation + dollar debt amplification", "lag": "1-2 months", "strength": 0.70},
    {"from": "employment", "to": "em-stress", "mechanism": "global demand contraction hits EM exports", "lag": "2-3 months", "strength": 0.60},
    {"from": "employment", "to": "demand-destruction", "mechanism": "Hamilton: oil shocks paid in employment", "lag": "2-4 months", "strength": 0.70},
    {"from": "demand-destruction", "to": "de-escalation", "mechanism": "the cure for high prices is high prices", "lag": "1-3 months", "strength": 0.50}
  ],

  "instruments": {
    "brent": [
      {"id": "XOP", "monthly": 1400, "role": "high-beta E&P", "beta": 0.7, "ref": 188.18, "targetLow": 210, "targetHigh": 225, "stop": 171},
      {"id": "XLE", "monthly": 1200, "role": "large-cap energy", "beta": 0.5, "ref": 61.52, "targetLow": 68, "targetHigh": 72, "stop": 56},
      {"id": "IXC", "monthly": 800, "role": "global energy", "beta": 0.4, "ref": 58.26, "targetLow": 64, "targetHigh": 68, "stop": 53}
    ],
    "fert-shortage": [
      {"id": "CF", "monthly": 800, "role": "nitrogen/fertilizer torque", "beta": 0.6, "ref": 136.45, "targetLow": 150, "targetHigh": 160, "stop": 124},
      {"id": "NTR", "monthly": 600, "role": "potash/nitrogen/phosphate", "beta": 0.5, "ref": 75.65, "targetLow": 82, "targetHigh": 88, "stop": 69}
    ],
    "dxy-stress": [
      {"id": "GLD", "monthly": 1000, "role": "gold hedge (anti-dollar)", "beta": -0.5, "ref": 414.70, "targetLow": 445, "targetHigh": 460, "stop": 395}
    ],
    "em-stress": [
      {"id": "VXUS", "monthly": 600, "role": "small ex-US (vulnerable)", "beta": -0.3, "ref": 74.69, "targetLow": 78, "targetHigh": 81, "stop": 71}
    ],
    "reserve": [
      {"id": "SGOV", "monthly": 1200, "role": "deployment ammo", "isReserve": true, "ref": 100.65},
      {"id": "STIP", "monthly": 400, "role": "near-term inflation hedge", "ref": 103.12}
    ],
    "services": [
      {"id": "OIH", "overlay": true, "condition": "rig-confirm AND NOT curve-constraint", "ref": 416.20, "targetLow": 460, "targetHigh": 500, "stop": 378}
    ]
  },

  "scenarios": [
    {
      "id": "reopen-apr1",
      "name": "Hormuz reopens April 1",
      "probability": 0.10,
      "overrides": {"hormuz": "resolved", "brent": 90},
      "notes": "Best case. Traffic resumes, oil normalizes in 4-6 weeks. Fertilizer still elevated short-term."
    },
    {
      "id": "closed-may",
      "name": "Closed through May",
      "probability": 0.45,
      "overrides": {"hormuz": "active", "brent": 135, "planting-miss": "fired", "diesel": 6.50},
      "notes": "Layer 3 activates. Corn planting missed. Food cascade begins. EM stress accelerates."
    },
    {
      "id": "kharg-strike",
      "name": "Kharg Island attacked",
      "probability": 0.15,
      "overrides": {"hormuz": "active", "brent": 155, "fert-shortage": 900},
      "notes": "Extreme scenario. Goldman peak case. All nodes fire. Full deployment."
    },
    {
      "id": "selective-reopen",
      "name": "Selective transit continues",
      "probability": 0.30,
      "overrides": {"hormuz": "partial", "brent": 115, "fert-shortage": 720},
      "notes": "Current state. China/India/Russia get access. West doesn't. Yuan tolls. Slow bleed."
    }
  ],

  "analogs": [
    {
      "id": "2008",
      "name": "2008 Oil Spike",
      "similarity": "high",
      "startDate": "2008-01-01",
      "peakDate": "2008-07-11",
      "keyLags": {
        "peak-to-employment": "3 months",
        "peak-to-oil-collapse": "5 months",
        "peak-to-recession-declaration": "5 months"
      },
      "notes": "Oil $90→$147→$32. Employment -712K/month by Oct-Mar. Demand destruction was the cure."
    },
    {
      "id": "1979",
      "name": "1979 Iranian Revolution",
      "similarity": "very high",
      "notes": "Gulf disruption + panic. 2.5x price increase. Deep recession + high inflation. Most direct analog."
    }
  ],

  "cascadePhases": {
    "shock": {
      "label": "Phase 1: Shock",
      "status": "COMPLETE",
      "signposts": [
        {"text": "VIX > 30", "status": "fired", "value": 31.05},
        {"text": "Oil +40% from pre-crisis", "status": "fired", "value": "+53%"},
        {"text": "Physical shortages reported", "status": "fired", "value": "608 AU stations, PH emergency, India panic"},
        {"text": "Safe haven flows (gold, USD)", "status": "fired"}
      ]
    },
    "transmission": {
      "label": "Phase 2: Transmission",
      "status": "STARTING",
      "signposts": [
        {"text": "PMI employment declining", "status": "fired", "value": "first negative in 12mo"},
        {"text": "Diesel above demand destruction threshold", "status": "fired", "value": "$5.38 > $5.00"},
        {"text": "Australia PMI contraction", "status": "fired", "value": "47.0"},
        {"text": "Consumer confidence declining", "status": "approaching"},
        {"text": "Initial claims rising", "status": "monitoring"},
        {"text": "Freight indices deteriorating", "status": "fired", "value": "owner-ops losing money"}
      ]
    },
    "amplification": {
      "label": "Phase 3: Amplification",
      "status": "APPROACHING",
      "signposts": [
        {"text": "Unemployment claims rising sustained", "status": "monitoring"},
        {"text": "Bank lending standards tightening", "status": "monitoring"},
        {"text": "EM currencies breaking", "status": "approaching"},
        {"text": "Corporate earnings warnings", "status": "monitoring"},
        {"text": "Credit spreads blow out", "status": "monitoring"}
      ],
      "estimatedTiming": "Q3-Q4 2026 based on 2008 template (3-month lag from oil peak)"
    },
    "policyResponse": {
      "label": "Phase 4: Policy Response",
      "status": "WATCHING",
      "signposts": [
        {"text": "Emergency rate cuts", "status": "not yet"},
        {"text": "SPR releases", "status": "fired", "value": "Japan 80M bbl record release"},
        {"text": "International coordination", "status": "partial"},
        {"text": "Fiscal stimulus", "status": "not yet"}
      ]
    },
    "resolution": {
      "label": "Phase 5: Resolution",
      "status": "NOT YET",
      "signposts": [
        {"text": "PMI bottoms and turns", "status": "not yet"},
        {"text": "Credit growth resumes", "status": "not yet"},
        {"text": "Commodity prices stabilize at new level", "status": "not yet"}
      ]
    }
  }
}
```

---

## What the Generator Produces

A single self-contained HTML file with an interactive thesis graph. The generator (`thesisgraph.py`) reads the graph config + market snapshot and produces:

### Main View: The Graph
- Interactive DAG visualization (Cytoscape.js or vis.js, inlined)
- Nodes colored by status: green (stable) → amber (approaching) → red (fired) → gray (gated/blocked)
- Edges show transmission mechanism on hover, thickness proportional to strength
- Pulsing animation on nodes receiving propagation from upstream
- Click any node → expand to show: data feeds, current values, thresholds, instruments, context
- Confluence badges on nodes where multiple paths converge

### Cascade Tracker Panel
- "WE ARE HERE" indicator with the 5-phase checklist
- Signposts as a vertical timeline, checkmarks for fired, clocks for approaching
- Historical analog overlay: "In 2008, this phase lasted 3 months. We are 4 weeks in."
- Countdown timers for date-gated triggers (April 15: 16 days)

### Scenario Comparison Panel
- Toggle between defined scenarios
- Graph nodes light up differently per scenario
- Portfolio impact waterfall: "Under 'closed through May': XOP +22%, CF +18%, VXUS -12%, net: +$X"
- Probability-weighted expected portfolio impact across all scenarios

### Portfolio View
- Instruments grouped by graph node (not flat list)
- Range bars, position tracking, P&L — same as current commodity book
- But now you can see WHERE in the graph each position sits
- SGOV deployments shown as capital flowing along graph edges to active nodes

### Prediction Market Overlay
- Polymarket/Kalshi probabilities displayed on graph nodes
- The crude oil 29-strike event rendered as a probability distribution on the "brent" node
- Kalshi CPI/Fed/GDP predictions on the macro transmission nodes
- Divergence alerts: "Your estimate: 45%. Market says: 68.5%. Gap: 23.5pp"

### Journal
- Entries linked to specific graph nodes ("logged at: fert-shortage node")
- Decision audit trail: what triggered, what you did, what you chose not to do
- Auto-log when node states change

---

## Build Phases

### Phase 1: Graph Engine Core

Extract and extend bookgen.py:
- Define the graph schema (above)
- Build `thesisgraph.py` — reads graph config + snapshot → generates HTML with interactive DAG
- Choose graph viz library (Cytoscape.js likely — 400KB but handles DAGs well, can be inlined)
- Implement node state evaluation (threshold crossing, date-gating, constraint blocking)
- Implement edge propagation (when upstream fires, downstream shows estimated lag)
- Render cascade phase tracker with signpost checklist
- Keep the commodity book as a "portfolio view" tab within the same HTML

### Phase 2: Data Pipeline + Probability

Build `fetch.py` — multi-source data fetcher:
- Yahoo Finance (prices, futures, curves, ETFs)
- Polymarket Gamma + CLOB (geopolitical probabilities, price history)
- Kalshi (CPI/Fed/GDP predictions)
- FRED (macro series, financial stress indices)
- EIA (diesel, inventory)
- CFTC COT (speculative positioning)
- BLS (employment, CPI)

Wire Polymarket/Kalshi probabilities as node probability weights.
Implement divergence detection (your estimate vs. market).

### Phase 3: Scenario Engine

Implement scenario definitions as graph node overrides.
Build portfolio stress test: factor betas × scenario shocks.
Render scenario comparison panel with portfolio impact waterfall.
Probability-weighted expected value across scenarios.

### Phase 4: Signal Engine + Notifications

Headless trigger evaluation (`check.py`):
- Load graph config + latest snapshot
- Evaluate all nodes
- Detect state changes
- Compute cascade propagation
- Push alerts on state changes (email/Telegram/webhook)

Run on cron or manually 3x/week per execution rules.

### Phase 5: Historical Analog + Journal

Historical episode library as JSON.
DTW similarity matching against current state.
Analog-based forward projection ("2008 template says employment hits in X weeks").
Enhanced journal with node-linked entries and decision audit trail.

---

## Technical Choices

| Component | Choice | Why |
|---|---|---|
| Graph viz (browser) | Cytoscape.js | Best DAG layout, interactive, can inline (~400KB) |
| Bayesian inference | pgmpy or hand-rolled enumeration | Network is small enough (<20 nodes) for brute force |
| Historical matching | dtw-python or tslearn | Standard DTW for time series similarity |
| Portfolio stress | NumPy matrix multiply | Factor betas × scenario shocks |
| Data fetch | urllib + json (stdlib) | Zero external Python dependencies (like bookgen.py) |
| State persistence | localStorage + JSON export | Same pattern as current commodity book |
| Output format | Single self-contained HTML | The HTML IS the tool. No server. |

---

## What NOT to Build

- Web server, database, Docker, mobile app, user auth
- Automated execution (you trade manually — correct for judgment strategies)
- Full Bayesian network library (pgmpy at generation time if needed; browser just renders)
- ML-based regime detection (threshold rubrics beat ML on rare events)
- Real-time streaming (snapshot-based, 3x/week review cadence)
- Separate Polymarket tracker (probabilities live ON the graph, not in a different tool)

---

## Key Insight

> "The system should be primarily a structured notebook for expert judgment, not an autonomous prediction engine. The math enforces consistency and propagates your estimates — it does not generate them. The human specifies the scenario structure, estimates the conditional probabilities, identifies the relevant analogs, and decides which indicators matter. The system ensures that if you believe A, B, and C, then D follows with probability X and portfolio impact Y."
>
> This is how Shell's scenario planning works — the models serve the narrative, not the other way around. The scenario engine is a tool for thinking, not a crystal ball.
