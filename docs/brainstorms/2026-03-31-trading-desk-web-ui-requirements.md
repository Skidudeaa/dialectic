---
date: 2026-03-31
topic: trading-desk-web-ui
---

# Trading Desk Web UI

## Problem Frame

The trading desk engine has a working causal reasoning pipeline — graph propagation, scenario evaluation, live price fetching, Dialectic integration, 203 tests. But it's delivered as CLI scripts that generate static HTML files. There is no persistent application, no live updates, no alerts, and no unified view across theses. Two users (Amo and Dan) access it from a shared DigitalOcean droplet but must manually run commands to see current state.

The engine needs a web UI that makes it a daily-use tool: open a browser, see what's moving, get notified when things change.

## User Flow

```
                    +-----------------------+
                    |   Open browser / app  |
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    | Multi-Thesis Dashboard |
                    |  - All theses at once  |
                    |  - Hot nodes, alerts   |
                    |  - State summary cards |
                    +-----------+-----------+
                                |
                   +------------+------------+
                   |                         |
        +----------v----------+   +----------v----------+
        | Thesis Deep View    |   | Alert Feed          |
        | (full React port)   |   | - State transitions |
        | - Cytoscape graph   |   | - Price moves       |
        | - Cascade tracker   |   | - Timestamps        |
        | - Scenarios         |   | - Click to thesis   |
        | - Portfolio         |   +---------------------+
        | - Journal           |
        +---------------------+

Background (always running):
  Fetch prices (asyncio.to_thread) -> Evaluate graph -> Diff state ->
    If changed: push to Dialectic, send alerts, broadcast via WebSocket
```

## Requirements

**Multi-Thesis Dashboard**
- R1. Landing page shows all loaded theses with state summary cards (node counts by state, current cascade phase, top countdowns)
- R2. Hot nodes highlighted — any node that transitioned state in the last 24 hours (configurable). Uses server-side transition log, not per-user visit tracking.
- R3. Click a thesis card to drill into the full thesis view

**Live Data Pipeline**
- R4. Background task fetches prices (Yahoo Finance + Polymarket) on a configurable interval (default: 5 minutes). Fetch functions are synchronous — must run via `asyncio.to_thread()` to avoid blocking the FastAPI event loop.
- R5. After each fetch cycle, the engine re-evaluates all thesis graphs and diffs the state. A "cycle already running" guard prevents overlapping fetches if the interval is shorter than the cycle duration.
- R6. State changes broadcast to all connected browser clients via WebSocket in real-time
- R7. Market data inputs in the thesis view send values to the server via WebSocket. Python re-propagates and pushes the updated state back. Browser is display-only — Python is the sole propagation authority.

**Alerts & Notifications**
- R8. In-app alerts: toast notifications and an alert feed showing state transitions with timestamps
- R9. Dialectic push: automatic snapshot push to configured trading rooms when state changes (existing bridge, now automated). Snapshots must include a `thesisId` field so multi-thesis rooms can distinguish which thesis fired.

**Thesis Deep View (Full React Port)**
- R11. Interactive Cytoscape.js graph via react-cytoscapejs with node coloring by state (fired/approaching/stable/gated). The existing ~800 lines of browser JS evaluation and rendering logic are discarded — Python is the sole propagation authority, React components handle display only.
- R12. Cascade phase tracker ("WE ARE HERE") with signpost checklists and countdown timers
- R13. Scenario toggle with portfolio impact waterfall visualization
- R14. Portfolio positions with range bars, grouped by graph node
- R15. Journal with node-linked decision audit trail — add entries from the UI

**Persistence**
- R16. JSON configs remain the source of truth for thesis graph structure (nodes, edges, instruments, scenarios, cascade phases). The server loads configs into memory at startup and on file change. The web server does not write back to JSON config files — the CLI `--fetch --update-config` workflow remains the only config writer, avoiding concurrent write races.
- R17. SQLite for mutable state: alert history, journal entries, position tracking, close logs (for closesRequired), user preferences, state transition log (for R2 hot nodes)
- R18. Close logs persisted in SQLite across sessions — enables the closesRequired gating to eventually promote nodes from "approaching" to "fired" based on actual daily closes. Existing localStorage close logs from the static HTML dashboards are not migrated (accepted loss — fresh start).

**Multi-User**
- R19. Two concurrent users (Amo and Dan) can view the dashboard simultaneously via WebSocket
- R20. Shared state — both see the same theses, same prices, same alerts
- R21. No authentication required initially (private droplet, not exposed to internet). Auth is a future concern.

**Stack**
- R22. Backend: FastAPI (Python) wrapping the existing propagation engine, price fetchers, and Dialectic bridge
- R23. Frontend: React SPA built with Vite, served as static files by the same FastAPI server
- R24. Cytoscape.js via react-cytoscapejs for graph visualization
- R25. WebSocket (FastAPI native) for real-time state push to browser clients
- R26. Runs on the existing DigitalOcean droplet, accessible via browser

## Success Criteria

- Open a browser on any device, see all theses with current state — no CLI commands required
- When a price moves and triggers a state transition, both users see the change within the fetch interval without refreshing
- State transitions produce alerts: in-app toast and Dialectic room message
- The thesis deep view is at least as functional as the current generated HTML dashboards (graph, cascade, scenarios, portfolio, journal)
- Close logs accumulate over time, eventually promoting closesRequired nodes from "approaching" to "fired"

## Scope Boundaries

- **In scope:** Dashboard, live data, in-app alerts, Dialectic push, thesis views, journal, basic position tracking
- **Not in scope (v2):** Mobile push notifications / Telegram / Slack webhooks (R10 deferred — unresolved external service dependency). Broker API connections or real P&L reconciliation. Thesis config editing in the UI (edit JSON directly for now). User authentication (private droplet). Mobile-native app (responsive web is sufficient). localStorage migration from existing static HTML dashboards.

## Key Decisions

- **Full React port over serving existing HTML:** The existing 800-line browser JS mirrors the Python propagation engine independently, creating a dual-authority problem. A full React port with Python as the sole propagation authority eliminates the divergence risk. More frontend work (~5-6 weeks vs ~2 weeks) but cleaner architecture and no state synchronization bugs.
- **Python is the sole propagation authority:** All graph evaluation happens server-side. The React client is display-only — it receives state via WebSocket and renders it. User inputs (market data changes, gate toggles) are sent to the server, which re-propagates and pushes the result back.
- **Server holds configs in memory, does not mutate JSON files:** Avoids concurrent write races between the web server's polling loop and CLI `--fetch --update-config`. The server reloads from disk on startup and watches for file changes.
- **FastAPI over Flask:** Native async, built-in WebSocket support, automatic OpenAPI docs.
- **React/Vite over Next.js:** No SSR needed for a dashboard app. Vite builds to static files served by FastAPI — one server process, simpler deployment.
- **SQLite over Postgres:** Two users, single droplet, lightweight mutable state. Zero-config.
- **R10 (mobile ping) deferred to v2:** The external service dependency (Telegram/Slack) is unresolved and not load-bearing for v1 success criteria. In-app alerts + Dialectic push cover the v1 feedback loop.
- **Existing localStorage data not migrated:** Close logs, positions, and journal entries from the static HTML dashboards start fresh in SQLite. Accepted tradeoff for a clean persistence layer.
- **External deps constraint removed:** The engine core stays stdlib-compatible, but the server layer uses FastAPI, uvicorn, and any needed packages.

## Dependencies / Assumptions

- The existing propagation engine, price fetchers, and Dialectic bridge are working and tested (203 tests passing)
- The droplet has Python 3.10+ and can install pip packages
- Node.js/npm available on the droplet for the Vite build step (build-time only, not runtime)
- react-cytoscapejs provides adequate Cytoscape.js integration for the graph tab

## Outstanding Questions

### Resolve Before Planning

*None — all product decisions resolved.*

### Deferred to Planning

- [Affects R4][Technical] Background task structure: `asyncio.to_thread()` wrapping the synchronous fetch functions is the mandatory approach. The planning question is how to structure the task lifecycle (startup, shutdown, error recovery).
- [Affects R9][Technical] Snapshot schema needs a `thesisId` field for multi-thesis Dialectic rooms. This touches `export_state()`, `diff-snapshots.py`, and `INTEGRATION.md`.
- [Affects R17][Technical] SQLite schema design: close logs, journal entries, alert history, state transition log, user preferences.
- [Affects R22][Technical] FastAPI app structure: single module or split by concern (routes, background tasks, WebSocket handlers).
- [Affects R11][Needs research] react-cytoscapejs capabilities: does it support the dagre layout, edge tooltips, and node click handlers that the current Cytoscape.js setup uses?

## Next Steps

`/ce:plan` for structured implementation planning
