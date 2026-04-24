---
title: "feat: Live data + cockpit UX — make Trading Desk a daily-driver"
type: feat
status: active
date: 2026-04-20
origin: docs/onboarding/agent-team-live-data-ui.md
related:
  - docs/plans/2026-04-12-001-feat-trading-desk-v2-runtime-platform-plan.md
---

# feat: Live Data + Cockpit UX

## Overview

Close the gap between "good-enough demo" and "daily driver for two analysts + one agent-in-the-loop." Two intertwined tracks:

- **Track A — Live, trustworthy data.** Retire the brittle `allorigins.win` proxy. Add FRED (rates/macro), an econ calendar, futures-curve bootstrapping, and a CORS relay we own. Every connector declares a freshness contract; stale cells surface amber.
- **Track B — Cockpit UX.** Push the dashboard from a polling dashboard into a push-driven, keyboard-first, multi-book cockpit. Expand Ctrl+K into a real runtime surface, ship live-tape WS broadcasts, presence pills, a cross-book matrix, and an agent-in-room panel so the LLM's state-of-the-world is visible alongside the humans'.

This plan is **additive to v2 (`2026-04-12-001`)** and does not replace it. v2 owns the runtime, persistence, and snapshot/event contracts. This plan rides on top of those contracts and adds what v2 was never scoped to build.

## Problem Frame

The v2 rebuild landed M0 + M1 + Unit 12, plus cosmetic polish (builder, onboarding, welcome). What it did not do:

1. **Data the desk can trust for an 8-hour session.** `allorigins.win` has gone down repeatedly; Yahoo is unofficial; Polymarket is the only probability feed. The `japan-rate-shock` and `china-property-cascade` books were seeded for a demo but cannot resolve their own theses because FRED, curve spread, and macro series don't exist as connectors.
2. **Push-driven market view.** WebSockets exist for chat and thesis deltas but prices still tick on poll. The MarketTicker feels like a polling widget, not a tape.
3. **Runtime-grade Ctrl+K.** The command palette exists as a panel-jumper. It does not fire trades, open theses, run diffs, or expose an `/api/commands` schema the LLM can call.
4. **Multi-book scaling.** The UI was built around 1–2 active books. There are now 5. Single-active-book patterns (sidebar selector, one morning brief per book) dilute instead of scale.
5. **Agent-native parity gap.** Snapshots push one-way to Dialectic. The LLM's room membership, last-message age, and tool-call log are not visible in the UI. Any UI affordance (fire, pin, open scenario) should have a structured agent-callable equivalent.
6. **Trade lifecycle buried.** `tools/outcomes/` does REPAIR → TAG → CAPTURE. The UI surfaces it only as a morning-brief line. No dedicated panel, no per-trade predicate view, no kill-switch.

## Requirements Trace

- **R42.** Every live data source declares a freshness contract (`fetched_at`, `source`, `ttl_seconds`) in the snapshot; UI surfaces stale cells as amber.
- **R43.** Browser market fetches go through a webapp-owned CORS relay with a strict upstream allowlist. `allorigins.win` is deleted from the codebase.
- **R44.** FRED connector (rates, macro) with stdlib-only fetcher, webapp adapter, and route. Books can declare `"source": "fred", "series": "<id>"` feeds.
- **R45.** Econ calendar connector feeding deadline nodes (FOMC, CPI, payrolls) with countdown math.
- **R46.** Futures-curve bootstrap from multi-contract Yahoo symbols (front/back, contango/backwardation, OVX) — no paid feed required.
- **R47.** Push-driven MarketTicker. Connector fetches publish to an in-process pub/sub; WS broadcasts diff-only payloads. Target <500ms from fetch to pixel change.
- **R48.** Ctrl+K command palette expanded into a runtime surface: fire trade, open thesis, diff last hour, ask mention, export, rotate. Every palette command is exposed at `/api/commands` as JSON schema for LLM tool calls.
- **R49.** Multi-book cockpit: tabbed book bar, Cmd+1..5 switching, cross-book matrix panel (phase / signals / trades / P&L / last-diff-age per row).
- **R50.** Presence pills on WS: "Dan is viewing `iran-hormuz`", "Claude is thinking in room X".
- **R51.** Trade lifecycle panel surfacing `tools/outcomes/` per-trade predicates with fire/approach timers and two-step kill-switch.
- **R52.** Agent-in-room panel showing snapshot version, room membership, last message age, and tool-call log for the LLM.
- **R53.** Keyboard coverage of every mouse action, documented in-app under `?`.
- **R54.** Every destructive action (fire, kill, rotate, delete) requires two-step confirmation and writes an audit row.

## Scope Boundaries

- No broker execution, no real P&L. Position tracking stays in the journal.
- No options flow, no Deribit, no CBOE in this plan. Deferred.
- No mobile-native workflows.
- No new top-level pages. Builder and Welcome stay as-is; work rides inside existing panels.
- **Does not touch v2 runtime contracts.** Bootstrap payload, snapshot shape, event shape are already locked. Only extensions (new adapter namespaces, new WS envelope types) are in scope.
- **Does not finish v2 tail units** (10, 11, 13, 14, 15). Those remain in the v2 plan and ship independently.

### Deferred to later plans

- News + headlines feed (Benzinga/NewsAPI/RSS). Probably next plan after this.
- Options flow / positioning. Same.
- Shared cursor on graph canvas. Too much lift; defer until live tape is proven.
- Dialectic room bidirectional WS sync. Outbox already covers one-way; two-way is a separate scope.

## Context & Research

### Relevant code and patterns

- **Current fetchers:** `tools/data_fetch/polymarket.py`, `tools/data_fetch/derived_indicators.py` — stdlib-only, three-pass slug matching for Polymarket, Wilder RSI/ATR/SMA from Yahoo v8 for derived.
- **Current WS manager:** `web/ws.py` — singleton `ConnectionManager` with 5 broadcast methods and 5s send timeout. Already envelope-aware after v2 Unit 8.
- **Current market adapter:** `web/adapters/market.py` — wraps `fetch_prices` and `fetch_polymarket`. Both mutate the cfg dict in place; must deep-copy before calling.
- **Current coordinator cycle:** `web/runtime/coordinator.py` — per-thesis lock, tick loop, diff, WS broadcast. Any new live-data connector hooks into the same cycle.
- **Command palette today:** frontend `Ctrl+K` panel jumper. Needs extension, not rewrite.

### Institutional learnings referenced

- Everything runs on the DO droplet `167.99.113.232`, bind `0.0.0.0`. No localhost-only services.
- New features integrate into the existing FastAPI + React webapp. No parallel services.
- Archive superseded code under `_archive/<category>/` with a README, don't `git rm`.
- `tools/` stays stdlib-only. Third-party deps live in `web/`.

### External references

- Agent-team brief: `docs/onboarding/agent-team-live-data-ui.md` — narrative source for this plan.
- FRED API: `https://api.stlouisfed.org/fred/` — requires free API key (`FRED_API_KEY` env).
- Yahoo v8 chart API: already used server-side in `derived_indicators.py`. Relay reuses that path.

## Key Technical Decisions

- **CORS relay > swapping to a paid feed.** Stdlib relay on our droplet is cheapest, highest-control, and removes the allorigins dependency. Paid equity feeds (Polygon, Alpha Vantage) are a later-stage investment.
- **In-process pub/sub > Redis.** Live-tape fan-out within one process is simpler than adding a broker. If we later shard workers, revisit.
- **Command registry is the agent-native surface.** `/api/commands` JSON schema is consumed both by the palette UI and by LLM tool-call bindings. Single source of truth beats two registries.
- **Freshness contract is schema-enforced.** Missing `fetched_at` on a quote raises. UI doesn't have to guess staleness; coordinator marks it.

## High-Level Technical Design

```
                books/*.json  ─────┐
                (5 theses)         │
                                   ▼
     ┌─────────────── web/runtime/coordinator.py ───────────────┐
     │                                                           │
     │   tick loop → fetch providers → propagate → commit        │
     │                                                           │
     └───┬──────────────────┬───────────────┬────────────────────┘
         │                  │               │
  provider fetches     pub/sub bus      WS manager
  (tools/data_fetch/)  (new: web/          (envelopes)
  ┌────────────────┐    runtime/          │
  │ polymarket     │    live_bus.py)      │
  │ derived_ind.   │                      │
  │ yahoo (relay)  │  ◀── fetch events ──┤
  │ fred (NEW)     │                      │
  │ econ_cal (NEW) │                      │
  │ curve (NEW)    │                      ▼
  └────────────────┘             React SPA (frontend/)
                                 - MarketTicker (live)
                                 - Cmd+K palette → /api/commands
                                 - Cross-book matrix
                                 - Trade lifecycle panel
                                 - Agent-in-room panel
```

## Implementation Units

### Milestone 1: Own the data path

- [x] **Unit 1: CORS relay + retire allorigins** (shipped — 18179b7)

**Goal:** Stdlib-only relay at `/api/relay/yahoo` with strict allowlist. Frontend stops hitting `allorigins.win`.

**Requirements:** R42, R43

**Files:**
- Create: `web/routes/relay.py` — single GET endpoint, allowlisted host/path prefixes, pass-through caching headers
- Modify: `frontend/src/lib/market.ts` (or equivalent) — point Yahoo fetches at `/api/relay/yahoo`
- Delete: all `allorigins.win` references in the frontend
- Test: `web/test_relay.py` — allowlist enforcement, malformed URL rejection, upstream 5xx passthrough

**Approach:** Allowlist = `query1.finance.yahoo.com` + specific path prefixes (`/v7/finance/spark`, `/v8/finance/chart`). Reject anything else with 400. No auth required (publicly-queryable data), but apply per-IP rate limit identical to TV webhook (60/min). Cache-Control: `public, max-age=30`.

---

- [ ] **Unit 2: FRED connector**

**Goal:** Pull Treasury curve, DXY, CPI, PPI, initial claims from FRED. Feed graph nodes with `"source": "fred"`.

**Requirements:** R42, R44

**Files:**
- Create: `tools/data_fetch/fred.py` — stdlib fetcher with API key from `FRED_API_KEY` env
- Create: `tools/data_fetch/test_fred.py` — offline tests with mocked HTTP
- Create: `web/adapters/fred.py` — async wrapper, freshness contract
- Modify: `tools/thesis_graph/thesisgraph.py` — `fetch_prices` dispatches `source=fred` to the FRED adapter
- Modify: `books/japan-rate-shock-graph.json` + `books/china-property-cascade-graph.json` — replace hand-typed values with live FRED series

**Approach:** Series-by-ID fetch via `https://api.stlouisfed.org/fred/series/observations?series_id=<id>&api_key=<key>&file_type=json&sort_order=desc&limit=1`. Persist into the same snapshot field as a Yahoo price. Declare `ttl_seconds=3600` (FRED is end-of-day data).

---

- [ ] **Unit 3: Econ calendar connector**

**Goal:** Populate deadline-node countdowns (FOMC, CPI, payrolls) from a free calendar source.

**Requirements:** R42, R45

**Files:**
- Create: `tools/data_fetch/econ_calendar.py`
- Create: `web/adapters/econ_calendar.py`
- Modify: books that have deadline nodes — swap hand-coded dates for calendar lookup

**Approach:** Evaluate Finnhub free-tier calendar first (requires `FINNHUB_API_KEY`). Fall back to FRED release calendar if Finnhub's free tier proves restrictive. Cache aggressively — calendar data updates at most weekly.

---

- [ ] **Unit 4: Futures-curve bootstrap**

**Goal:** Front/back spread, contango/backwardation for Brent and CL from Yahoo multi-contract symbols.

**Requirements:** R42, R46

**Files:**
- Modify: `tools/data_fetch/derived_indicators.py` — new function `compute_curve_spread(front_symbol, back_symbol)` returning overlay metrics
- Modify: `books/iran-hormuz-graph.json` — add curve-spread indicator alongside Brent spot

**Approach:** Fetch `CL=F` + `CLM26.NYM` (or equivalent back-month); compute front/back diff and label as contango/backwardation. Overlay-only (schema tripwire enforces — must not flow into `eval_node_state`).

---

- [x] **Unit 5: Freshness contract schema + UI staleness badges** (this commit)

**Goal:** Every provider writes `fetched_at` / `source` / `ttl_seconds` into the snapshot. Frontend surfaces amber badges when TTL is exceeded.

**Requirements:** R42

**Files:**
- Modify: `web/schemas/snapshots.py` — add `Freshness` model, attach to node `feed` blocks
- Modify: `web/runtime/coordinator.py` — write `fetched_at` at the moment of successful fetch; compute staleness at commit time
- Modify: `frontend/src/components/ThesisViewer.tsx` + `MarketTicker.tsx` — amber badge on stale cells
- Test: `web/schemas/test_freshness.py`

---

### Milestone 2: Cockpit UX

- [ ] **Unit 6: Push-driven MarketTicker via in-process pub/sub**

**Goal:** Coordinator publishes price-change events to an in-process bus; WS manager subscribes; clients see pixel updates within 500ms.

**Requirements:** R47

**Files:**
- Create: `web/runtime/live_bus.py` — asyncio `Queue`-based fan-out, per-thesis channels
- Modify: `web/runtime/coordinator.py` — publish on commit, diff-only payload
- Modify: `web/ws.py` — new `price.tick` envelope type; subscribers filter by thesis
- Modify: `frontend/src/components/MarketTicker.tsx` — listen for `price.tick`, apply delta
- Test: `web/runtime/test_live_bus.py`

---

- [ ] **Unit 7: Command palette expansion + `/api/commands` registry**

**Goal:** Every slash command, fire/kill action, panel switch becomes a palette entry + a JSON-schema command at `/api/commands`.

**Requirements:** R48, R53

**Files:**
- Create: `web/routes/v1/commands.py` — GET `/api/v1/commands` returns JSON-schema-per-command
- Create: `web/runtime/command_registry.py` — single registry imported by palette route and LLM tool dispatcher
- Modify: `frontend/src/components/CommandPalette.tsx` — fetch from `/api/v1/commands`, render, keybind
- Modify: `frontend/src/components/Help.tsx` — `?` overlay rendering palette + shortcuts
- Test: `web/routes/v1/test_commands.py` — schema validation per command, LLM can introspect

**Approach:** Registry entry = `{id, title, description, category, schema (Pydantic-derived), handler}`. Palette renders `title + category`. LLM reads `id + schema + description`. One handler dispatches both.

---

- [ ] **Unit 8: Multi-book cockpit — tab bar + Cmd+digit + cross-book matrix**

**Goal:** Five books fit into the UI without dilution. Cross-book matrix replaces per-book scrollthrough.

**Requirements:** R49

**Files:**
- Create: `frontend/src/components/BookTabBar.tsx`
- Create: `frontend/src/components/CrossBookMatrix.tsx` — row per book, columns: phase / top signals / open trades / last-diff-age
- Modify: `frontend/src/pages/Dashboard.tsx` — Cmd+1..5 keybinds, TabBar at top
- Modify: `web/routes/v1/bootstrap.py` — ensure cross-book summary ships in bootstrap payload (already does per v2 Unit 9, just verify the shape matches)

---

- [ ] **Unit 9: Presence pills**

**Goal:** See who else is in a room and what they're viewing. Include the agent as a first-class presence entry.

**Requirements:** R50, R52

**Files:**
- Modify: `web/ws.py` — new `presence.changed` envelope type with `{user_id, book_id, last_activity}`
- Modify: `web/routes/messages.py` WS handler — emit presence on connect/disconnect/book-switch
- Create: `frontend/src/components/PresencePills.tsx` — rendered in header

---

### Milestone 3: Trade lifecycle + agent-in-room

- [ ] **Unit 10: Trade lifecycle panel**

**Goal:** Surface `tools/outcomes/` predicates per trade. Fire-timer, approach-timer, two-step kill-switch.

**Requirements:** R51, R54

**Files:**
- Create: `web/routes/v1/trades.py` — GET open trades + predicates, POST kill-switch with two-step confirmation token
- Modify: `web/adapters/outcomes.py` — expose predicate state per trade (already has lifecycle_monitor; just needs a per-trade view)
- Create: `frontend/src/components/TradeLifecyclePanel.tsx` — new right-panel tab
- Test: `web/routes/v1/test_trades.py`

---

- [ ] **Unit 11: Agent-in-room panel**

**Goal:** Make the LLM's state-of-the-world visible. Snapshot version in use, room membership, last message age, tool-call log.

**Requirements:** R52

**Files:**
- Create: `frontend/src/components/AgentInRoomPanel.tsx`
- Modify: `web/routes/llm.py` — expose agent session metadata (last tool-call timestamp, current snapshot revision, active model)
- Modify: `web/runtime/coordinator.py` — stamp agent tool-calls with the snapshot revision they ran against

---

- [ ] **Unit 12: Audit log + destructive action two-step**

**Goal:** Every fire, kill, rotate, delete writes an audit row and requires a confirmation token that expires in 30s.

**Requirements:** R54

**Files:**
- Modify: `web/persistence/sql/` — new migration `002_audit_log.sql`
- Modify: `web/persistence/repository.py` — audit CRUD
- Modify: every destructive route — wrap in `require_confirmation_token` dependency
- Create: `frontend/src/components/ConfirmDialog.tsx` — two-step UI

---

## Phased Delivery

- **M1 (Own the data path)** — Units 1–5, ~2–3 weeks. **Hard prerequisite**: nothing in M2/M3 is worth shipping on top of brittle data.
- **M2 (Cockpit UX)** — Units 6–9, ~2–3 weeks. Can run in parallel with M1 Unit 4–5 once relay is in.
- **M3 (Lifecycle + agent parity)** — Units 10–12, ~2 weeks.

Total envelope: 6–8 weeks. Hard gate at end of M1: do a full-trading-day dry run on one book (hormuz) with the new data stack. If amber badges never trip during the session, M1 is done.

## Documentation / Operational Notes

- **Env vars to document in `.env.example`:** `FRED_API_KEY`, `FINNHUB_API_KEY`.
- **Runbook:** new `docs/runbooks/freshness-contract.md` explaining what amber means and how to fix it.
- **User manual:** update `docs/USER-MANUAL.md` with command palette cheat-sheet and presence pill meaning.
- **Subsumes:** `docs/onboarding/agent-team-live-data-ui.md` — keep as origin reference, do not delete.

## Risks & Dependencies

- **FRED / Finnhub free tiers.** Rate limits. Mitigation: aggressive caching, single fetch per cycle, freshness TTL aligned with update cadence.
- **Pub/sub fan-out overhead at >50 concurrent clients.** Not a concern today (two users) but revisit if Dan invites more collaborators.
- **Command registry as LLM tool surface.** If the JSON-schema shape drifts, LLM tool-calls break silently. Contract test in CI that validates every command's schema round-trips.
- **Destructive action UX friction.** Two-step on every fire/kill will slow power-users. Offer a "sticky confirm" option for the current session after first use.

## Sources & References

- `docs/onboarding/agent-team-live-data-ui.md` — narrative origin
- `docs/plans/2026-04-12-001-feat-trading-desk-v2-runtime-platform-plan.md` — underlying runtime
- `CLAUDE.md` — project conventions (stdlib-only tools, droplet-first, archive-not-delete)
- Memory: `/root/.claude/projects/-root-tradingDesk/memory/` — user preferences
