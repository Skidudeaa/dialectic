# tradingDesk — Project Plan

## What This Is

A thesis-driven judgment toolkit for commodity and macro trading. Not an execution engine, not a portfolio tracker, not a trading bot. A system that organizes thesis-driven positions, tracks escalation triggers, integrates prediction market probabilities, and enforces discipline through structured decision frameworks.

The commodity book HTML is the seed. Everything grows from that pattern: JSON config → Python generator → self-contained interactive HTML dashboard.

## Core Thesis

The market doesn't reward information. It rewards judgment — knowing what to do with information before everyone else figures it out. tradingDesk exists to sharpen that judgment by:

1. Forcing structured thinking (triggers, not narratives)
2. Integrating signals from different domains (commodity prices, prediction markets, macro data, positioning)
3. Making the decision framework auditable (journal, trigger logs, snapshot history)
4. Challenging assumptions (constraint triggers that BLOCK action, not just trigger it)

---

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │         JSON Book Configs            │
                    │  (iran-hormuz.json, china-trade.json)│
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │        Market Snapshot Engine         │
                    │  tools/data-fetch/fetch.py            │
                    │                                       │
                    │  Yahoo Finance ─┐                     │
                    │  Polymarket ────┤                     │
                    │  Kalshi ────────┤→ snapshots/         │
                    │  FRED ──────────┤   YYYY-MM-DD.json   │
                    │  EIA ───────────┤                     │
                    │  CFTC COT ─────┘                     │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │        Signal Evaluation Engine       │
                    │  tools/signals/check.py               │
                    │                                       │
                    │  Loads config + snapshot               │
                    │  Evaluates all triggers                │
                    │  Detects state changes                 │
                    │  Emits alerts (email/Telegram/webhook) │
                    │  Archives signal report                │
                    └──────────────┬──────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│  Commodity Book  │  │ Polymarket       │  │ Master Dashboard     │
│  (per thesis)    │  │ Tracker          │  │ (multi-book view)    │
│  bookgen.py      │  │ polytracker.py   │  │ mastergen.py         │
│                  │  │                  │  │                      │
│  4 tabs:         │  │  Event tracking  │  │  Cross-book exposure │
│  Dashboard       │  │  Probability     │  │  Sector concentration│
│  Book            │  │  timeseries      │  │  Aggregate P&L       │
│  Triggers        │  │  Crude oil       │  │  Shared SGOV ledger  │
│  Journal         │  │  synthetic chain │  │  Conflict detection  │
└─────────────────┘  │  Iran/geopolitics│  └──────────────────────┘
                     │  Cross-ref with  │
                     │  trigger states  │
                     └──────────────────┘
```

All outputs are **self-contained HTML files**. No web server. No database. State in localStorage + exportable JSON. This is intentional — the HTML file is both the tool and the artifact.

---

## Phased Build Plan

### Phase 1: Foundation (immediate)

**Goal:** Clean up bookgen.py for extensibility, add Polymarket tracker, add multi-source data fetch.

**1a. Extract JS/CSS from bookgen.py**
The #1 maintainability problem: ~40KB of minified JS and ~700 lines of CSS are inlined as Python string constants. Extract to:
```
tools/commodity-book/
  bookgen.py          # generator (reads template files)
  template.js         # extracted JS logic (~500 lines, formatted)
  template.css        # extracted CSS (~700 lines, formatted)
  iran-hormuz-2026.json
```
bookgen.py reads and injects them at generation time. Same output, but now the JS/CSS can be edited with proper tooling.

**1b. Polymarket Tracker** (`tools/polymarket/`)
New generator: `polytracker.py` — takes a JSON config of tracked events/markets and generates a self-contained HTML dashboard.

Config example:
```json
{
  "title": "Polymarket — Iran/Oil/Trump",
  "watchlist": [
    {"slug": "will-us-forces-enter-iran-by-april-30", "alias": "US in Iran (Apr 30)"},
    {"slug": "crude-oil-cl-hit-120-high-by-end-of-march", "alias": "CL $120 Mar"}
  ],
  "events": [
    {"slug": "crude-oil-prices-march", "alias": "Crude Oil Strikes (29 markets)"}
  ],
  "refreshInterval": 300
}
```

Dashboard features:
- Event cards with current probability, 24h/1wk change, volume
- Price history sparklines (CLOB API `/prices-history`)
- The crude oil 29-market event rendered as a **synthetic options chain** — strike prices on Y axis, probabilities on X axis
- Cross-reference panel linking Polymarket odds to commodity book triggers (e.g., "Polymarket says 4.7% chance CL hits $120 this month — your Brent persistence trigger needs $115 for 3 closes")
- Auto-refresh via allorigins.win CORS proxy to Gamma API (no auth needed)

**Also track Kalshi** (server-side fetch during generation):
- CPI monthly predictions (KXCPI)
- Fed funds rate after FOMC (KXFED)
- GDP growth predictions (KXGDP)
These are the most valuable prediction market signals for macro positioning.

**1c. Multi-source data fetcher** (`tools/data-fetch/fetch.py`)
Single script that pulls from all sources and writes a timestamped snapshot:

```bash
python3 tools/data-fetch/fetch.py -o snapshots/2026-03-30.json
```

Sources (Phase 1):
| Source | Data | Auth | CORS |
|---|---|---|---|
| Yahoo Finance v7/v8 | Prices, futures, curves | None | Proxy |
| Polymarket Gamma | Geopolitical probabilities | None | Proxy |
| Kalshi | CPI/Fed/GDP predictions | None | Server only |
| FRED | Macro series (rates, breakevens, credit spreads) | Free key | Proxy |
| EIA v2 | Diesel, crude inventory | Free key | Direct |
| CFTC COT (Socrata) | Speculative positioning | None | Direct |
| BLS | Employment, CPI | None | Direct |

Output: `snapshots/YYYY-MM-DD.json` with all data normalized into a flat structure that bookgen.py and polytracker.py can consume.

**1d. Wire snapshot into bookgen.py**
New flag: `bookgen.py config.json --snapshot snapshots/2026-03-30.json -o book.html`
Merges snapshot data into market fields and instrument prices before generating.

---

### Phase 2: Signal Engine

**Goal:** Headless trigger evaluation with push notifications.

`tools/signals/check.py` — loads a book config + latest snapshot, evaluates all triggers, compares against previous state, emits alerts on changes.

```bash
# Manual check
python3 tools/signals/check.py tools/commodity-book/iran-hormuz-2026.json \
  --snapshot snapshots/2026-03-30.json

# Output:
# APPROACHING: Brent Persistence — $112.57 / $115 (97.9%)
# APPROACHING: Fertilizer Stress — $683 / $700 (97.6%)
# BLOCKED: Rig Confirmation — rigs still falling (543)
# STABLE: 6 other triggers unchanged

# With notifications
python3 tools/signals/check.py config.json --snapshot latest \
  --notify telegram --notify email
```

Run manually 3x/week (Mon/Wed/Fri per execution rules) or put on a cron.

Future: composite triggers (AND/OR logic), relative triggers (rate of change), time-windowed conditions.

---

### Phase 3: Multi-Book Aggregation

**Goal:** Run multiple thesis books simultaneously with cross-book risk awareness.

New configs:
```
books/
  iran-hormuz-2026.json      # existing
  agriculture-shock-2026.json # fertilizer cascade thesis
  master.json                 # references both, defines cross-book rules
```

Master dashboard (generated by `mastergen.py` or `bookgen.py --multi`):
- Tab per book (renders same 4-tab layout within each)
- Aggregate tab: total exposure by sector, shared instrument overlap, net SGOV deployment, conflict detection (book A says buy CF, book B says sell CF)
- Single unified journal across all books

---

### Phase 4: Enhanced Journal

**Goal:** Turn the journal from a trade log into a decision audit trail.

Each entry captures:
1. What triggered the action (trigger ID, market data snapshot)
2. What the action was (deploy, hold, trim, close)
3. What the alternative was (what you chose NOT to do)
4. Outcome (filled in later: P&L, whether trigger thesis played out)

Analytics:
- Win rate by trigger type
- Average R-multiple by setup type
- Trigger accuracy (how often a fired trigger led to a profitable action)
- "Edge Finder" — cross-reference all journal metadata to surface patterns

Journal data stored as append-only JSONL (one file per book). HTML dashboard renders it. The JSONL file is the durable record.

---

### Phase 5: Historical Analysis

**Goal:** Backtest trigger accuracy against archived snapshots.

With snapshots archived daily:
- "Would trigger X have fired on date Y?"
- "What was the P&L outcome 30/60/90 days after trigger Z fired?"
- Trigger threshold calibration: "If I set Brent persistence at $110 instead of $115, how many more signals would have fired?"
- Overlay trigger accuracy chart in the dashboard

---

## Data Source Registry

### Tier 1: Primary (already integrated or Phase 1)

| Source | What | Key | Browser | Server |
|---|---|---|---|---|
| Yahoo Finance v7/v8 | Prices, futures, curves, ETFs | None | via allorigins | Direct |
| Polymarket Gamma | Event probabilities, volumes | None | via allorigins | Direct |
| Polymarket CLOB | Price history, orderbook | None | via allorigins | Direct |
| Kalshi | CPI/Fed/GDP predictions | None | No | Direct |
| EIA v2 | Diesel, crude inventory, NG | Free key | Direct (CORS) | Direct |
| FRED | 810K+ economic series | Free key | via allorigins | Direct |
| CFTC COT (Socrata) | Speculative positioning | None | Direct (CORS) | Direct |
| BLS | Employment, CPI | None | Direct (CORS) | Direct |

### Tier 2: Supplemental (Phase 2+)

| Source | What | Key | Browser | Server |
|---|---|---|---|---|
| ECB Data Portal | EUR/USD, European rates | None | Direct (CORS) | Direct |
| USDA Socrata | Fertilizer prices by region | None | Direct (CORS) | Direct |
| Finnhub | Equity quotes backup | Free key | Direct (CORS) | Direct |
| Twelve Data | Equity/FX backup | Free key | Direct (CORS) | Direct |

### Dead/Skip

| Source | Why |
|---|---|
| IEX Cloud | Defunct as of March 2026 |
| Polygon.io | 5 calls/min free tier — useless |
| Alpha Vantage | 25 calls/day — too restrictive |
| CNN Fear & Greed | Bot detection blocks automated access |
| Reddit/Twitter APIs | Paid-only or heavily restricted |
| CME/ICE direct | Expensive commercial subscriptions |
| Metaculus | Auth-gated now |

---

## What NOT to Build

- **Web server for the dashboard** — the HTML file IS the server
- **Automated execution** — you trade manually. That's correct for judgment-driven strategies
- **Database** — JSON files + localStorage for 1-2 users
- **Docker/containers** — bare Python files, run directly
- **Real-time streaming** — snapshot-based is fine for judgment (3x/week review cadence)
- **Mobile app** — the HTML is responsive enough
- **User accounts / auth** — single-user tool
- **Backtesting engine** — not Backtrader or QuantConnect. Just replay trigger evaluation against snapshots

---

## File Structure (target)

```
tradingDesk/
├── PROJECT.md                    # this file
├── CLAUDE.md                     # project context for Claude Code
├── .gitignore
│
├── books/                        # book configs (one per thesis)
│   ├── iran-hormuz-2026.json
│   ├── agriculture-shock-2026.json  (future)
│   └── master.json                  (future)
│
├── snapshots/                    # timestamped market data
│   ├── 2026-03-30.json
│   └── ...
│
├── output/                       # generated HTML dashboards
│   ├── iran-hormuz.html
│   ├── polymarket-tracker.html
│   └── master.html              (future)
│
├── tools/
│   ├── commodity-book/
│   │   ├── bookgen.py           # commodity book generator
│   │   ├── template.js          # extracted JS (Phase 1a)
│   │   └── template.css         # extracted CSS (Phase 1a)
│   │
│   ├── polymarket/
│   │   ├── polytracker.py       # Polymarket tracker generator (Phase 1b)
│   │   └── watchlist.json       # tracked events config
│   │
│   ├── data-fetch/
│   │   └── fetch.py             # multi-source data fetcher (Phase 1c)
│   │
│   └── signals/
│       └── check.py             # headless trigger evaluator (Phase 2)
│
├── journal/                     # append-only decision logs
│   └── iran-hormuz.jsonl        (Phase 4)
│
└── research/                    # research outputs (from swarm agents)
    ├── polymarket-api.md
    ├── macro-employment-thesis.md
    ├── fertilizer-cascade.md
    ├── data-apis.md
    ├── platform-architecture.md
    └── bookgen-analysis.md
```

---

## Immediate Next Steps

1. **Extract JS/CSS** from bookgen.py into separate template files
2. **Build polytracker.py** — Polymarket tracker with synthetic options chain view
3. **Build fetch.py** — multi-source data fetcher writing snapshots
4. **Move iran-hormuz-2026.json** to `books/` and update bookgen.py paths
5. **Archive research** — write the 6 swarm outputs to `research/`
6. **Restructure repo** to match target file structure

---

## Research Summary (from 6 parallel swarm agents, March 29-30, 2026)

### Polymarket API
- **Free, no auth** for read-only market data
- Gamma API for discovery (events, volumes, metadata) + CLOB API for depth (orderbook, price history)
- Active Iran/oil markets: "US forces enter Iran by Apr 30" = 68.5% Yes ($8.2M vol), crude oil 29-strike synthetic chain
- Browser needs CORS proxy; server-side direct
- Best open-source reference: `polymarket-intelligence` (FastAPI + React)

### Oil → Employment Thesis (Hamilton)
- Oil shocks account for 20-25% of cyclical employment variability (2x monetary policy)
- 2008 template: oil peaked July 11 → catastrophic job losses by October (3-month lag)
- Current: U.S. PMI employment negative for first time in 12 months, Australia PMI collapsed to 47.0, diesel at $5.38 above all demand destruction thresholds ($4.75/$5.00/$5.25)
- DXY strengthening from dollar funding stress, not U.S. strength — classic petrodollar squeeze

### Fertilizer Cascade
- Hormuz carries ~30% of global fertilizer exports (50% of urea + sulfur)
- NOLA urea: $516 pre-war → $822.50/t retail (Mar 25) — the $700 trigger has effectively fired
- **April 15 critical date**: if Hormuz closed through mid-April, corn belt nitrogen application structurally impaired
- WFP: 45M additional people at acute food insecurity risk

### EM Sovereign Risk
- Egypt CDS ~314 bps (from 270 pre-war); $8B external balance deterioration, $1.4B hot money flight in 8 days
- Pakistan KSE-100 dropped 9.57% on Mar 2; schools closed, 4-day work week
- Bangladesh force majeure on LNG; fuel reserves depleting
- EM bond issuance effectively frozen
- Iran collecting Hormuz tolls in yuan via Kunlun Bank (confirmed)

### Platform Architecture
- tradingDesk is a thesis-driven judgment toolkit (unique niche — not Backtrader, not TradingView)
- Keep HTML-first pattern (TiddlyWiki proves it scales)
- JSON config is already more expressive than Pine Script for macro trading
- Evolution: data pipeline → signal engine → multi-book → journal → historical

### Bookgen Analysis
- 969 lines, zero external Python dependencies, clean pipeline
- Main weakness: JS/CSS inlined as Python string constants
- Extension points clear: new tabs, new data sources, multi-book mode
- Trigger system handles numeric thresholds, binary toggles, constraints, reversals, alt-metrics
- Missing: AND logic, time-windowed conditions, relative triggers, cross-instrument conditions

### Data APIs
- Yahoo Finance v7/v8 still working, primary source for prices/futures/curves
- **Kalshi is the most valuable new addition** — CPI/Fed/GDP prediction markets with real money
- CFTC COT: free, CORS-enabled, browser-fetchable positioning data (net speculative crude/gold/FX)
- FRED: 810K+ series, needs CORS proxy for browser
- EIA: CORS-enabled with free key (diesel, inventory)
- BLS: CORS-enabled, no key (employment, CPI)
- Dead: IEX Cloud, Polygon.io free tier, CNN Fear & Greed
