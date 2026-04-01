---
title: "feat: Trading Desk web UI — FastAPI + React dashboard with live data"
type: feat
status: active
date: 2026-03-31
origin: docs/brainstorms/2026-03-31-trading-desk-web-ui-requirements.md
---

# feat: Trading Desk Web UI

## Overview

Replace the CLI-driven static HTML dashboard generation with a live web application. FastAPI backend wraps the existing Python propagation engine, a React SPA provides the frontend, WebSocket pushes real-time state updates, and SQLite persists mutable state. Two users on a shared DigitalOcean droplet.

## Problem Frame

The trading desk engine works — propagation, scenarios, price fetching, Dialectic bridge, 203 tests. But it's delivered as CLI scripts generating static HTML files. No persistent application, no live updates, no alerts, no unified multi-thesis view. (see origin: docs/brainstorms/2026-03-31-trading-desk-web-ui-requirements.md)

## Requirements Trace

- R1. Multi-thesis dashboard with state summary cards
- R2. Hot nodes (transitioned in last 24h, configurable)
- R3. Drill into thesis deep view
- R4. Background fetch on configurable interval (default 5min), via asyncio.to_thread
- R5. Re-evaluate + diff after each fetch, with cycle-already-running guard
- R6. WebSocket broadcast of state changes
- R7. Market data inputs → server re-propagates → pushes result (Python is sole authority)
- R8. In-app toast alerts + alert feed
- R9. Dialectic auto-push with thesisId in snapshot
- R11-R15. Full React port of graph, cascade, scenarios, portfolio, journal tabs
- R16. JSON configs as source of truth; server loads into memory, does not mutate files
- R17. SQLite for mutable state
- R18. Close log persistence in SQLite
- R19-R21. Two concurrent users, shared state, no auth
- R22-R26. FastAPI + React/Vite + react-cytoscapejs + WebSocket + DO droplet

## Scope Boundaries

- No mobile push notifications (v2)
- No broker API / real P&L
- No thesis config editing in UI
- No auth (private droplet)
- No localStorage migration from static HTML dashboards

## Context & Research

### Relevant Code and Patterns

- **Engine API surface:** `propagate(cfg)`, `score_confluence(cfg, states)`, `eval_scenario(cfg, scenario, base_states)`, `export_state(...)` are pure computation — clean API boundaries. `fetch_prices(cfg)` and `fetch_polymarket(cfg)` mutate cfg in place — need clone-before-mutate for concurrent access.
- **Config structure:** `books/*.json` with top-level keys: meta, nodes, edges, instruments, scenarios, analogs, cascadePhases, marketFields, fetchSymbols, rules, provenance
- **State colors:** `fired:#E05555, approaching:#E69A4C, stable:#6E8FAD, gated:#555555, constrained:#AD7FA8, monitoring:#777777` — defined in CSS (line 1073) and JS STATE_COLORS (line 1264)
- **generate_html (lines 979-2060):** ~1080 lines of CSS+JS+HTML template — this is what React replaces
- **Test patterns:** Direct function imports via `from thesisgraph import propagate, ...`

### External References

- FastAPI WebSocket: ConnectionManager pattern with broadcast, lifespan context manager for background tasks
- react-cytoscapejs 2.0.0: Supports dagre layout via `cytoscape-dagre` extension registration. Node click handlers via `cy` callback prop. Dynamic element updates via props.
- SQLite: `asyncio.to_thread` + stdlib `sqlite3` (zero-dep approach). WAL mode for concurrent reads+writes.
- SPA serving: Mount `/assets` static, catch-all `/{path}` returns index.html. API routes MUST be defined BEFORE catch-all.

## Key Technical Decisions

- **Python is sole propagation authority:** All graph evaluation server-side. React is display-only. User inputs sent via WebSocket, server re-propagates and pushes result. Eliminates dual-engine divergence. (see origin: Key Decisions)
- **asyncio.to_thread for blocking fetch:** `fetch_prices` and `fetch_polymarket` use `urllib.request.urlopen` + `time.sleep`. Wrapping in `asyncio.to_thread(run_fetch_cycle)` keeps existing code unchanged while not blocking the event loop.
- **Server holds configs in memory:** Load from `books/*.json` at startup and on file change. No write-back during polling — avoids concurrent write races with CLI workflow.
- **Clone cfg before mutation:** Background fetch clones cfg via `copy.deepcopy` before calling `fetch_prices`/`fetch_polymarket`, since these mutate in place.
- **SQLite via asyncio.to_thread + stdlib sqlite3:** Zero new deps for persistence. WAL mode for concurrent access. Wrap sync sqlite3 calls in `asyncio.to_thread`.
- **API prefix `/api/`:** All REST and WebSocket endpoints under `/api/`. SPA catch-all AFTER API routes.

## Open Questions

### Resolved During Planning

- **Background task approach:** `asyncio.to_thread` wrapping synchronous fetch functions, launched via FastAPI `lifespan` context manager. `asyncio.create_task` for the polling loop.
- **react-cytoscapejs for dagre:** Confirmed — register `cytoscape-dagre` extension, pass layout config `{name: 'dagre', rankDir: 'TB'}`. Node events via `cy` callback.
- **SQLite thread safety:** WAL mode + busy_timeout=5000ms. Sync functions wrapped in `asyncio.to_thread`.

### Deferred to Implementation

- Exact SQLite table schemas — design during Unit 3 implementation
- Vite chunk splitting strategy — default Vite config is likely sufficient
- Specific React component library (if any) for UI chrome — decide during frontend scaffold

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```
Browser (React SPA)                    Server (FastAPI + uvicorn)
========================               =====================================
                                       
 /                                      Lifespan:
 ├─ Dashboard ─── GET /api/theses ────>   load configs from books/*.json
 │   (summary     GET /api/state  ────>   init SQLite (WAL mode)
 │    cards)                               start fetch_loop task
 │                                     
 ├─ /thesis/:id                         fetch_loop (asyncio.create_task):
 │   ├─ GraphTab ── WS /api/ws ──────>   while True:
 │   ├─ CascadeTab                         cfg_copy = deepcopy(cfg)
 │   ├─ ScenariosTab                       await to_thread(fetch_prices, cfg_copy)
 │   ├─ PortfolioTab                       await to_thread(fetch_polymarket, cfg_copy)
 │   └─ JournalTab                         states = propagate(cfg_copy)
 │                                         diff = compare(old_states, states)
 ├─ /alerts                                if diff:
 │   (alert feed)                            broadcast(diff) via WebSocket
 │                                           save alert to SQLite
 └─ WebSocket ◄─── broadcast ─────────      push to Dialectic
     (state updates,                       await asyncio.sleep(interval)
      alert toasts)                    
                                       REST API:
                                         GET  /api/theses
                                         GET  /api/theses/:id/state
                                         POST /api/theses/:id/scenario/:sid
                                         GET  /api/alerts
                                         POST /api/journal
                                         GET  /api/journal/:thesisId
                                       
                                       WebSocket:
                                         /api/ws — broadcast state + alerts
                                         client → server: market data overrides
                                       
                                       Static:
                                         /assets/* — Vite build output
                                         /* catch-all — index.html (SPA routing)
```

## Phased Delivery

### Phase 1: Backend Foundation
Units 1-5. Result: FastAPI server running with REST API, background fetch loop, WebSocket broadcasting state changes. Testable via curl/wscat.

### Phase 2: React Frontend
Units 6-10. Result: Full React SPA with dashboard, thesis deep view (all 5 tabs), alert feed. Usable app.

### Phase 3: Integration
Units 11-12. Result: Automated Dialectic push, close log persistence. Production-ready.

## Implementation Units

### Phase 1: Backend Foundation

- [ ] **Unit 1: Project scaffolding**

**Goal:** Directory structure, Python package setup, Vite React scaffold, development workflow.

**Requirements:** R22, R23, R26

**Dependencies:** None

**Files:**
- Create: `server/` — Python package root
- Create: `server/__init__.py`
- Create: `server/app.py` — FastAPI application factory
- Create: `server/config.py` — settings (fetch interval, DB path, books directory)
- Create: `frontend/` — Vite React project root
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/main.tsx`
- Create: `requirements.txt` — fastapi, uvicorn[standard]

**Approach:**
- FastAPI app with lifespan context manager (not deprecated `on_event`)
- Vite React project with TypeScript
- `requirements.txt` for Python deps, `package.json` for frontend
- Development: uvicorn with `--reload`, Vite dev server with proxy to FastAPI
- Production: `npm run build` → FastAPI serves `frontend/dist/`

**Test expectation:** none — pure scaffolding

**Verification:**
- `uvicorn server.app:app` starts without error
- `npm run dev` (in frontend/) serves React app
- `GET /` returns a response

---

- [ ] **Unit 2: Engine adapter module**

**Goal:** Clean import layer between FastAPI and the existing thesisgraph.py engine. Manages config lifecycle and provides thread-safe access to engine functions.

**Requirements:** R4, R5, R7, R16

**Dependencies:** Unit 1

**Files:**
- Create: `server/engine.py` — adapter module
- Test: `server/test_engine.py`

**Approach:**
- Load all JSON configs from `books/` at init
- Store configs in a dict keyed by thesis ID (derived from filename)
- `get_thesis_state(thesis_id)` → runs propagate + score_confluence + get_current_phase, returns a structured result
- `run_fetch_cycle(thesis_id)` → deepcopy cfg, call fetch_prices + fetch_polymarket, propagate, return (new_cfg, states, diff)
- `evaluate_scenario(thesis_id, scenario_id, base_states)` → runs eval_scenario
- Thread-safe: each fetch cycle works on a deepcopy. State updates are atomic dict replacements.
- Import thesisgraph functions directly: `from tools.thesis_graph.thesisgraph import propagate, score_confluence, ...` (may need sys.path adjustment)

**Patterns to follow:**
- `test_export.py` line 16-24 — direct function imports from thesisgraph

**Test scenarios:**
- Happy path: Load iran-hormuz config → get_thesis_state returns states dict with all node IDs
- Happy path: evaluate_scenario returns new_states and impact dict with numeric values
- Edge case: Unknown thesis_id → raises appropriate error
- Edge case: Config with validation warnings → loads successfully with warnings logged
- Integration: get_thesis_state output matches direct propagate() call on the same config

**Verification:**
- All engine functions accessible via clean Python API without touching thesisgraph.py internals

---

- [ ] **Unit 3: SQLite schema + data access**

**Goal:** Persistence layer for mutable state — alerts, journal, close logs, preferences.

**Requirements:** R17, R18

**Dependencies:** Unit 1

**Files:**
- Create: `server/db.py` — schema init, CRUD functions
- Test: `server/test_db.py`

**Approach:**
- Tables: `alerts` (id, thesis_id, node_id, old_state, new_state, timestamp), `journal` (id, thesis_id, date, type, text, node_id), `close_logs` (id, thesis_id, node_id, date, value, threshold_level), `preferences` (key, value_json)
- Init: create tables if not exist, set WAL mode + busy_timeout
- All DB functions are synchronous, called via `asyncio.to_thread` from async code
- Database file: `data/trading.db` (gitignored)

**Test scenarios:**
- Happy path: Insert alert → query alerts by thesis_id → returns inserted alert
- Happy path: Insert journal entry → query by thesis_id → returns entry with correct fields
- Happy path: Insert close log → query by node_id → returns close count
- Edge case: Query empty table → returns empty list
- Edge case: Concurrent writes (WAL mode) → both succeed

**Verification:**
- Schema creates cleanly on fresh database
- CRUD operations work for all four tables

---

- [ ] **Unit 4: REST API endpoints**

**Goal:** HTTP API for frontend to fetch thesis state, scenarios, alerts, and journal.

**Requirements:** R1, R3, R8, R15

**Dependencies:** Units 2, 3

**Files:**
- Create: `server/routes.py` — API route definitions
- Modify: `server/app.py` — include router
- Test: `server/test_routes.py`

**Approach:**
- `GET /api/theses` → list all loaded thesis configs with summary (node count, meta info)
- `GET /api/theses/{id}/state` → full evaluated state (states, confluence, phase, countdowns, scenarios, instruments)
- `POST /api/theses/{id}/scenario/{sid}` → evaluate one scenario, return states + impact
- `GET /api/alerts` → recent alerts from SQLite, optional thesis_id filter
- `GET /api/journal/{thesis_id}` → journal entries from SQLite
- `POST /api/journal/{thesis_id}` → add journal entry
- All async endpoints, DB calls via asyncio.to_thread

**Patterns to follow:**
- `export_state()` output shape for the state endpoint — match the snapshot schema

**Test scenarios:**
- Happy path: GET /api/theses → returns list with iran-hormuz and trump-tariffs
- Happy path: GET /api/theses/iran-hormuz/state → returns states dict, confluence scores, cascade phase
- Happy path: POST /api/journal/iran-hormuz with entry data → 201, entry persisted
- Error path: GET /api/theses/nonexistent/state → 404
- Error path: POST /api/journal with missing fields → 422

**Verification:**
- All endpoints return correct status codes and response shapes
- State endpoint output is structurally compatible with the existing snapshot schema

---

- [ ] **Unit 5: Background fetch loop + WebSocket broadcast**

**Goal:** Periodic price fetching that pushes state changes to all connected browsers.

**Requirements:** R4, R5, R6, R8, R9

**Dependencies:** Units 2, 3, 4

**Files:**
- Create: `server/ws.py` — ConnectionManager + WebSocket endpoint
- Create: `server/background.py` — fetch loop coroutine
- Modify: `server/app.py` — lifespan wiring
- Test: `server/test_ws.py`

**Approach:**
- ConnectionManager class: connect/disconnect/broadcast pattern (FastAPI docs pattern)
- Background loop via `asyncio.create_task` in lifespan:
  - For each thesis: deepcopy cfg → `asyncio.to_thread(fetch_prices)` → `asyncio.to_thread(fetch_polymarket)` → propagate → diff against previous states
  - If diff has changes: broadcast via WebSocket, save alerts to SQLite, trigger Dialectic push (Unit 11)
  - Cycle-already-running guard: skip if previous cycle not complete
  - `await asyncio.sleep(interval)` between cycles
- WebSocket endpoint `/api/ws`:
  - On connect: send current state for all theses (initial payload)
  - Server pushes: state diffs, new alerts
  - Client sends: market data overrides → server re-propagates for that thesis → broadcasts result
- Broadcast errors per-connection (one dead connection doesn't kill others)

**Test scenarios:**
- Happy path: WebSocket connects → receives initial state payload
- Happy path: State change during fetch cycle → all connected clients receive diff
- Happy path: Client sends market override → server re-propagates → broadcasts updated state
- Edge case: Client disconnects during broadcast → other clients unaffected
- Edge case: Fetch cycle takes longer than interval → next cycle skipped (guard)
- Error path: Fetch fails (network error) → logged, previous state preserved, no crash

**Verification:**
- WebSocket endpoint accepts connections and sends initial state
- Background loop runs without blocking the event loop
- State changes are broadcast to all connected clients

---

### Phase 2: React Frontend

- [ ] **Unit 6: React app shell + WebSocket hook**

**Goal:** React routing, layout, WebSocket connection management, shared state.

**Requirements:** R3, R6, R19

**Dependencies:** Unit 5

**Files:**
- Create: `frontend/src/hooks/useWebSocket.ts` — WebSocket connection hook
- Create: `frontend/src/context/ThesisContext.tsx` — shared state provider
- Create: `frontend/src/components/Layout.tsx` — app shell with nav
- Modify: `frontend/src/App.tsx` — routes setup
- Create: `frontend/src/types.ts` — TypeScript types matching API response shapes

**Approach:**
- React Router: `/` (dashboard), `/thesis/:id` (deep view with tab param), `/alerts`
- WebSocket hook: connects on mount, reconnects on disconnect, parses JSON messages, dispatches to state
- Context provider: holds thesis states, alerts, connection status. Updated by WebSocket messages.
- Layout: minimal nav bar with thesis links + alerts badge

**Test expectation:** none — UI scaffolding, tested via integration with Units 7-10

**Verification:**
- App renders, routes work, WebSocket connects to backend

---

- [ ] **Unit 7: Multi-thesis dashboard**

**Goal:** Landing page showing all theses with state summary cards and hot nodes.

**Requirements:** R1, R2

**Dependencies:** Unit 6

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/components/ThesisCard.tsx`
- Create: `frontend/src/components/HotNodes.tsx`

**Approach:**
- Fetch thesis list + state on mount via REST API
- ThesisCard: thesis title, node count by state (colored badges), current cascade phase, top countdown
- HotNodes: nodes that transitioned in last 24h (from alert history), sorted by recency
- Click thesis card → navigate to `/thesis/:id`
- Live updates via WebSocket context — cards update when state changes arrive

**Test scenarios:**
- Happy path: Two thesis cards rendered with correct node state counts
- Happy path: Hot node appears when a state transition alert exists within 24h
- Edge case: No alerts in 24h → "No recent activity" message
- Integration: WebSocket state update → card re-renders with new state counts

**Verification:**
- Dashboard shows both theses with current state
- Clicking a card navigates to the thesis deep view

---

- [ ] **Unit 8: Graph tab (react-cytoscapejs)**

**Goal:** Interactive DAG visualization with node coloring, click-to-inspect, and live state updates.

**Requirements:** R11

**Dependencies:** Unit 6

**Files:**
- Create: `frontend/src/components/thesis/GraphTab.tsx`
- Create: `frontend/src/components/thesis/NodeDetail.tsx`

**Approach:**
- react-cytoscapejs with cytoscape-dagre layout registered
- Elements built from thesis nodes/edges: `{data: {id, label, type, state}, ...}`
- Stylesheet: node colors from STATE_COLORS map, edge styles matching current CSS
- Node click → open NodeDetail panel showing context, thresholds, feeds, indicators, action
- Edge hover → tooltip with mechanism + lag
- State updates via context → elements array updates → Cytoscape re-renders affected nodes
- dagre layout: `{name: 'dagre', rankDir: 'TB', nodeSep: 50, rankSep: 80}`

**Patterns to follow:**
- Existing Cytoscape config in thesisgraph.py `initGraph()` (line 1384-1442) — node shapes, edge styles, layout params

**Test scenarios:**
- Happy path: Graph renders with correct number of nodes and edges for iran-hormuz (16 nodes, 14 edges)
- Happy path: Node colors match state (fired=red, approaching=amber, stable=blue-gray)
- Happy path: Click node → NodeDetail panel shows context, thresholds, feeds
- Integration: WebSocket state update → node color changes in real time

**Verification:**
- Graph visually matches the current static HTML dashboard layout
- Node interaction (click, hover) works

---

- [ ] **Unit 9: Remaining thesis tabs (cascade, scenarios, portfolio, journal)**

**Goal:** Full feature parity with the existing HTML dashboard for all non-graph tabs.

**Requirements:** R12, R13, R14, R15

**Dependencies:** Unit 6

**Files:**
- Create: `frontend/src/components/thesis/CascadeTab.tsx`
- Create: `frontend/src/components/thesis/ScenariosTab.tsx`
- Create: `frontend/src/components/thesis/PortfolioTab.tsx`
- Create: `frontend/src/components/thesis/JournalTab.tsx`
- Create: `frontend/src/pages/ThesisView.tsx` — tab container

**Approach:**
- **CascadeTab:** Phase timeline with "WE ARE HERE" marker, signpost checklists with status icons, countdown timers, historical analogs
- **ScenariosTab:** Scenario pills (click to select), state transition diff, portfolio impact waterfall. Calls `POST /api/theses/:id/scenario/:sid` for each scenario eval.
- **PortfolioTab:** Instruments grouped by graph node, range bars showing position vs range, state badge per group
- **JournalTab:** Entry list with date/type/text/node filters. Add entry form → `POST /api/journal/:thesisId`. Node tag linking.
- All tabs receive state from ThesisContext (WebSocket-driven)

**Test scenarios:**
- Happy path: CascadeTab renders 5 phases with correct status indicators for iran-hormuz
- Happy path: ScenariosTab shows 4 scenario pills, clicking one shows state transitions and impact
- Happy path: PortfolioTab groups instruments by node with correct state colors
- Happy path: JournalTab add entry → appears in list immediately
- Edge case: Empty journal → "No entries yet" message
- Integration: Scenario eval response matches export_state scenarioImpacts shape

**Verification:**
- Each tab renders content equivalent to the current static HTML dashboard
- Journal entries persist via API and appear after page reload

---

- [ ] **Unit 10: Alert feed + toast notifications**

**Goal:** Alert timeline page and in-app toast notifications on state transitions.

**Requirements:** R8

**Dependencies:** Units 6, 7

**Files:**
- Create: `frontend/src/pages/AlertFeed.tsx`
- Create: `frontend/src/components/Toast.tsx`

**Approach:**
- AlertFeed page: list of state transitions from `GET /api/alerts`, grouped by date, filterable by thesis
- Toast component: appears on WebSocket alert broadcast, auto-dismisses after 5s, click navigates to thesis
- Alert badge in nav bar showing unread count (since last viewed)

**Test scenarios:**
- Happy path: Alert feed shows state transitions with thesis name, node label, old→new state, timestamp
- Happy path: WebSocket alert → toast appears with node name and transition
- Happy path: Click toast → navigates to the relevant thesis view
- Edge case: Multiple rapid alerts → toasts queue, don't overlap

**Verification:**
- Alerts appear in real-time when state changes
- Alert feed page loads historical alerts from the database

---

### Phase 3: Integration

- [ ] **Unit 11: Dialectic auto-push on state change**

**Goal:** When the background fetch loop detects state changes, automatically push snapshots to configured Dialectic rooms.

**Requirements:** R9

**Dependencies:** Unit 5

**Files:**
- Modify: `server/background.py` — add Dialectic push to the fetch loop
- Modify: `tools/thesis-graph/thesisgraph.py` — add thesisId to export_state output
- Test: `server/test_background.py`

**Approach:**
- Add `"thesisId"` field to `export_state()` output, derived from `meta.get("id")` or the config filename
- After diff detects changes, call `push_to_dialectic` (existing bridge script) via asyncio.to_thread
- Dialectic URL and room IDs configured in server/config.py or per-thesis in the JSON config
- Requires DIALECTIC_ROOM_TOKEN env var (existing pattern)

**Test scenarios:**
- Happy path: State change triggers Dialectic push with snapshot containing thesisId
- Happy path: No state change → no push (existing diff behavior)
- Error path: Dialectic push fails (network error) → logged, does not crash fetch loop
- Edge case: Multiple theses change in same cycle → each gets its own push

**Verification:**
- Snapshot JSON includes thesisId field
- Dialectic push fires automatically on state transitions

---

- [ ] **Unit 12: Close log persistence**

**Goal:** Persist daily close observations in SQLite so closesRequired nodes can eventually promote from "approaching" to "fired".

**Requirements:** R18

**Dependencies:** Units 3, 5

**Files:**
- Modify: `server/background.py` — record close observations after each fetch
- Modify: `server/engine.py` — feed close logs into propagation
- Modify: `server/db.py` — close log queries
- Test: `server/test_close_logs.py`

**Approach:**
- After each price fetch, for each thesis: check if current time is after market close (configurable, default 4pm ET). If so, record one close log entry per price node per day.
- Close log entry: (thesis_id, node_id, date, value, threshold_level)
- Before propagation, query close logs for relevant nodes and inject close count into the evaluation
- Modify engine adapter: if a node has closesRequired, count close logs at or above the threshold level. If count >= closesRequired, the node can fire (override the "approaching" fallback in eval_node_state).

**Test scenarios:**
- Happy path: Price above threshold recorded as close log entry → next propagation with 3+ entries → node fires
- Happy path: Price below threshold → no close log entry for that threshold
- Edge case: Multiple closes on same day → deduplicated (one per node per day)
- Edge case: Node with closesRequired: 3, only 2 closes recorded → stays "approaching"
- Integration: Full cycle: fetch → close log → propagate → node promotion

**Verification:**
- Close logs accumulate over days
- Node with sufficient close logs transitions from "approaching" to "fired"

---

## System-Wide Impact

- **Interaction graph:** The background fetch loop is the central coordinator — it touches the engine adapter, SQLite (alerts, close logs), WebSocket manager (broadcast), and Dialectic bridge (push). A failure in any downstream system must not crash the loop.
- **Error propagation:** Fetch failures → logged, state preserved. DB write failures → logged, broadcast continues. WebSocket broadcast failures → per-connection error handling, other clients unaffected. Dialectic push failures → logged (existing retry logic), does not block the cycle.
- **State lifecycle:** Config loaded at startup → held in memory. Price updates applied to deepcopy → if successful, atomic swap of the in-memory state. SQLite alerts/journal are append-only. Close logs are deduplicated per node per day.
- **API surface parity:** The CLI tools (`thesisgraph.py --export-state`, `diff-snapshots.py`, `push-to-dialectic.py`) remain functional. The web server is an additional consumer, not a replacement.
- **Unchanged invariants:** JSON config file format, snapshot schema (except adding thesisId), Dialectic API contract, existing test suite (203 tests).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| react-cytoscapejs dagre layout doesn't match existing visual output | Research confirms dagre support. Port existing layout params (nodeSep, rankSep, rankDir) from initGraph(). Verify visually during Unit 8. |
| Background fetch blocks event loop despite asyncio.to_thread | fetch_prices and fetch_polymarket are wrapped entirely in to_thread — the entire synchronous call chain runs off the event loop. Verify with a connected WebSocket client during fetch. |
| Yahoo Finance starts blocking direct server requests (no proxy) | Existing fetch_prices already calls Yahoo directly (proxy removed in today's review fixes). If Yahoo blocks, can reinstate allorigins.win as fallback. |
| SQLite concurrent access under WebSocket + background writes | WAL mode + busy_timeout=5000ms handles this for 2 users. If issues arise, move to write-serialized pattern. |
| Frontend scope creep — full React port of 5 tabs is substantial | Phase 2 is the bulk of the work. Each tab is a separate unit. Ship dashboard + graph tab first, iterate on remaining tabs. |

## Documentation / Operational Notes

- Update CLAUDE.md: add `server/` and `frontend/` to file structure, document new dev workflow
- Update INTEGRATION.md: document thesisId addition to snapshot schema
- Create deployment guide: how to run on the droplet (uvicorn behind nginx, npm run build for frontend)
- Add `data/` to .gitignore (SQLite database)

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-31-trading-desk-web-ui-requirements.md](docs/brainstorms/2026-03-31-trading-desk-web-ui-requirements.md)
- Engine core: `tools/thesis-graph/thesisgraph.py` — propagation (lines 145-310), export (lines 425-546), fetch (lines 552-742)
- Existing graph config: `books/iran-hormuz-graph.json` (16 nodes, 14 edges)
- FastAPI WebSocket docs: ConnectionManager broadcast pattern
- react-cytoscapejs: dagre via `Cytoscape.use(dagre)`, events via `cy` callback prop
- Existing test patterns: `tools/thesis-graph/test_export.py`
