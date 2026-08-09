# Trading Desk Web Platform v2

## Executive Summary

The current outline is strong on feature coverage but still too loose on runtime authority, data contracts, and operational behavior. The next-level version should stop thinking in terms of pages and endpoints first, and instead define a runtime system with four hard boundaries:

1. **Immutable thesis definitions** loaded from JSON configs.
2. **Mutable runtime inputs** from market feeds and manual overrides.
3. **Derived snapshots** computed only by Python.
4. **Append-only events** persisted and broadcast to clients.

That change turns the app from “FastAPI serving a React port of the old HTML” into a real trading desk runtime with deterministic state, auditable changes, and recoverable behavior.

## What Changes Immediately

### Keep

- Python as the sole propagation authority.
- FastAPI + React SPA.
- SQLite for mutable state at current scale.
- WebSocket broadcast for shared live updates.
- JSON configs as source of truth for thesis definitions.

### Change

- Replace the vague “server holds configs in memory” approach with an explicit **runtime coordinator**.
- Replace hand-wavy REST/WS payloads with **versioned schemas**.
- Replace “broadcast diff if changed” with **event and snapshot semantics**.
- Replace “call Dialectic in the fetch loop” with an **outbox worker**.
- Replace “manual overrides via websocket message” with **persisted override records** and clear precedence rules.
- Replace “maybe file watcher reload” with **explicit config reload** in prod.

### Kill

- `sys.path` hacks to import the engine.
- One giant `routes.py` / `ws.py` / `background.py` blob.
- Global shared mutable dicts with implicit ownership.
- Any shared unread/read state without user identity.
- A single default 4pm ET close rule for all markets.

## Product Definition

### Core Objective

Provide a live multi-thesis trading desk where two concurrent users can:

- monitor all theses in one place,
- inspect causal graph state and phase progression,
- evaluate scenarios against the latest runtime snapshot,
- receive durable alerts on meaningful state changes,
- annotate the system with journal entries,
- trust that all state is consistent, auditable, and recoverable.

### Non-Goals

- broker execution,
- order management,
- real P&L,
- public multi-tenant SaaS,
- in-app config editing,
- mobile-native workflows.

## Architecture Principles

### P1. Python owns truth

Every computed state comes from the Python engine. Frontend never derives authoritative node state.

### P2. Definitions are immutable, runtime is mutable

JSON thesis configs define topology and rules. Market inputs, overrides, alerts, journals, close observations, and latest snapshots live outside the files.

### P3. Full snapshot on bootstrap, incremental events thereafter

Clients should receive a complete authoritative snapshot on initial load, then consume incremental updates.

### P4. Append-only events before side effects

When state changes, persist the event and snapshot first. Notifications and external pushes happen after commit.

### P5. Shared state requires explicit conflict rules

Two users with no auth still need deterministic write semantics. Last write wins for overrides, append-only for journals, local-only unread state.

### P6. Data freshness is part of state

A live trading desk without freshness metadata is bullshit. Every thesis needs source watermarks and stale/degraded indicators.

## Refactored Runtime Model

### Static Domain: ThesisDefinition

Loaded from `books/*.json` and treated as immutable at runtime.

Fields:
- `thesisId`
- `definitionHash`
- `meta`
- `nodes`
- `edges`
- `instruments`
- `scenarios`
- `cascadePhases`
- `marketFields`
- `fetchSymbols`
- `rules`
- `provenance`

### Mutable Runtime Inputs

Separate records from definitions:
- fetched prices / market fields,
- fetched Polymarket inputs,
- manual overrides with TTL,
- close observations,
- source diagnostics and watermarks.

### Derived Snapshot

Canonical output of the engine for one thesis revision.

```json
{
  "thesisId": "iran-hormuz",
  "revision": 142,
  "generatedAt": "2026-04-12T17:04:03Z",
  "definitionHash": "sha256:...",
  "quality": {
    "status": "healthy",
    "lastSuccessAt": "2026-04-12T17:03:58Z",
    "lastAttemptAt": "2026-04-12T17:03:56Z",
    "stale": false,
    "issues": []
  },
  "watermarks": {
    "prices": "2026-04-12T17:03:56Z",
    "polymarket": "2026-04-12T17:03:57Z"
  },
  "summary": {
    "nodeCounts": {
      "fired": 2,
      "approaching": 3,
      "stable": 8,
      "gated": 2,
      "constrained": 1,
      "monitoring": 0
    },
    "phase": "Phase 2",
    "topCountdowns": []
  },
  "graph": {
    "nodes": [],
    "edges": []
  },
  "portfolio": [],
  "scenarios": {
    "catalog": []
  },
  "activeOverrides": [],
  "closeStatus": []
}
```

### Event Types

Emit durable events only for meaningful changes:
- `node.state_changed`
- `phase.changed`
- `countdown.threshold_crossed`
- `feed.health_changed`
- `override.applied`
- `override.cleared`
- `journal.created`
- `snapshot.recomputed`

Do **not** emit noisy events for every price tick that does not alter state.

## Runtime Coordinator

Introduce a single runtime service instead of scattering logic across endpoints and background tasks.

### Responsibilities

- hold loaded thesis definitions,
- hold latest committed snapshot metadata,
- schedule fetch/evaluate cycles,
- serialize per-thesis mutations,
- persist snapshots and events,
- fan out websocket updates,
- enqueue external integrations.

### Concurrency Model

- One `asyncio.Lock` per thesis.
- One scheduler loop that triggers per-thesis jobs.
- One bounded worker pool for blocking providers via `asyncio.to_thread`.
- No overlapping evaluation for the same thesis.
- Optional cross-thesis concurrency with a semaphore.

### Why this is better

The original loop makes fetching, diffing, persistence, websocket broadcast, and external push all part of one hot path. That works right until one external dependency stalls and the whole desk starts lying quietly. A coordinator plus outbox isolates that damage.

## Scheduler and Fetch Strategy

### Proposed flow per thesis

1. Scheduler wakes on interval.
2. If thesis lock is held, record skip and move on.
3. Fetch providers into a runtime input patch.
4. Merge inputs with manual overrides using precedence rules.
5. Evaluate engine on a deep-copied effective config.
6. Compute semantic diff against prior committed snapshot.
7. In one DB transaction:
   - insert fetch run,
   - upsert latest snapshot,
   - insert alert events,
   - insert outbox rows for Dialectic if needed.
8. Publish websocket messages after commit.
9. Release thesis lock.

### Precedence rules

`manual override > fresh provider input > prior provider value > static config default`

### Staleness rules

Each provider needs:
- `expectedIntervalSec`
- `staleAfterSec`
- `degradedAfterSec`

Quality state should be computed per thesis and exposed to UI.

## Manual Overrides

The current outline treats overrides as a websocket message. That is too sloppy for shared state.

### Override model

Each override record should include:
- `overrideId`
- `thesisId`
- `targetType` (`node`, `marketField`, `instrument`)
- `targetId`
- `field`
- `valueJson`
- `actor`
- `reason`
- `createdAt`
- `expiresAt` nullable
- `clearedAt` nullable
- `status` (`active`, `expired`, `cleared`)

### Rules

- Overrides are shared and visible to both users.
- Overrides are auditable and reversible.
- Scenario evaluation is separate and does **not** create overrides.
- Expired overrides are ignored automatically.
- UI must display active overrides clearly in snapshot summary.

## Scenario Evaluation

Scenario evaluation must stay read-only and revision-bound.

### Rules

- Evaluate against the latest committed snapshot revision unless caller specifies `againstRevision`.
- Scenario results do not mutate live runtime state.
- Response includes `baseRevision`, `scenarioId`, changed nodes, impact summary, and a human-readable explanation section.

That avoids the classic mess where someone clicks a scenario tab and accidentally poisons the live desk.

## Persistence Model

Use SQLite, but make it a real persistence layer instead of a glorified junk drawer.

### Tables

#### `thesis_snapshots`
Stores latest committed snapshot per thesis.

Columns:
- `thesis_id` PK
- `revision`
- `generated_at`
- `definition_hash`
- `quality_status`
- `last_success_at`
- `snapshot_json`

#### `alert_events`
Durable state transition and health events.

Columns:
- `event_id` PK
- `thesis_id`
- `revision`
- `event_type`
- `severity`
- `node_id` nullable
- `old_value_json` nullable
- `new_value_json` nullable
- `occurred_at`
- `dedupe_key` UNIQUE

Indexes:
- `(thesis_id, occurred_at DESC)`
- `(event_type, occurred_at DESC)`

#### `journal_entries`
Append-only notes.

Columns:
- `journal_id` PK
- `thesis_id`
- `created_at`
- `actor` nullable
- `entry_type`
- `node_id` nullable
- `body`
- `metadata_json`

#### `close_observations`
Tracks threshold-qualified closes.

Columns:
- `thesis_id`
- `node_id`
- `market_date`
- `threshold_key`
- `close_value`
- `captured_at`
- `source_run_id`

Primary key:
- `(thesis_id, node_id, market_date, threshold_key)`

#### `manual_overrides`
Shared runtime overrides.

Columns:
- `override_id` PK
- `thesis_id`
- `target_type`
- `target_id`
- `field`
- `value_json`
- `actor`
- `reason`
- `created_at`
- `expires_at` nullable
- `cleared_at` nullable
- `status`

#### `fetch_runs`
Operational audit log.

Columns:
- `run_id` PK
- `thesis_id`
- `started_at`
- `finished_at`
- `status`
- `diagnostics_json`
- `revision` nullable

#### `outbox`
Reliable delivery for external pushes.

Columns:
- `outbox_id` PK
- `kind`
- `thesis_id`
- `payload_json`
- `status`
- `attempts`
- `next_attempt_at`
- `last_error`
- `created_at`

### Migration strategy

Do not rely on `CREATE TABLE IF NOT EXISTS` forever. Add a tiny SQL migration runner and a `schema_migrations` table.

## Close Observation Logic

The original close-log plan is directionally right but too naive on market close semantics.

### Add config support

Each applicable node or instrument group should support:
- `closePolicy.timezone`
- `closePolicy.cutoffTime`
- `closePolicy.tradingDays`
- `closePolicy.source`
- `closePolicy.graceMinutes`

### Rules

- At most one qualified close per node per market date per threshold.
- 24/7 assets still need a daily cutoff boundary.
- Capture only if source freshness is acceptable inside the grace window.
- Store enough metadata to explain why a close counted.

## API Refactor

Version the API now. Not later, not after drift starts.

### REST surface

- `GET /api/v1/bootstrap`
  - returns thesis catalog, latest snapshots, active overrides, alert summary
- `GET /api/v1/theses`
- `GET /api/v1/theses/{thesisId}`
- `GET /api/v1/theses/{thesisId}/snapshot`
- `POST /api/v1/theses/{thesisId}/scenarios/{scenarioId}/evaluate`
- `GET /api/v1/alerts`
- `GET /api/v1/journal`
- `POST /api/v1/journal`
- `GET /api/v1/overrides`
- `POST /api/v1/overrides`
- `POST /api/v1/overrides/{overrideId}/clear`
- `POST /api/v1/admin/reload-definitions`
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`

### Design rules

- Pydantic models define all request and response contracts.
- Frontend types should be generated from OpenAPI, not handwritten.
- Scenario evaluation must be idempotent and read-only.
- Journal writes return the created record.
- Bootstrap should make first render cheap and deterministic.

## WebSocket Protocol

Define a message envelope. Otherwise it becomes ad hoc sludge.

### Envelope

```json
{
  "type": "snapshot.delta",
  "schemaVersion": 1,
  "messageId": "uuid",
  "sentAt": "2026-04-12T17:05:00Z",
  "thesisId": "iran-hormuz",
  "revision": 143,
  "payload": {}
}
```

### Server to client

- `bootstrap`
- `snapshot.full`
- `snapshot.delta`
- `alert.created`
- `override.changed`
- `runtime.status`
- `error`
- `pong`

### Client to server

- `ping`
- `subscribe`
- `override.apply`
- `override.clear`
- `scenario.evaluate` optional if you want WS-based request/response later

### Delta semantics

Do not implement generic JSON Patch on day one. Send structured deltas:
- changed nodes,
- changed summary,
- phase change,
- active override changes,
- new alerts.

## Backend Code Layout

Current unit breakdown is workable, but the file structure needs a harder spine.

```text
server/
  app.py
  config.py
  api/
    rest.py
    ws.py
    deps.py
  runtime/
    coordinator.py
    scheduler.py
    diffing.py
    registry.py
    snapshots.py
    overrides.py
  engine/
    adapter.py
    models.py
  persistence/
    migrations.py
    sqlite.py
    repositories/
      alerts.py
      journal.py
      overrides.py
      snapshots.py
      outbox.py
      closes.py
  integrations/
    dialectic.py
    market_data/
      prices.py
      polymarket.py
  observability/
    logging.py
    metrics.py
    health.py
  schemas/
    api.py
    events.py
    snapshots.py
```

### Engine packaging

No `sys.path` hacks. Extract the thesis engine into an installable internal package or proper module path.

## Frontend Refactor

The frontend should stop mirroring the old HTML file one tab at a time and start behaving like an operator console.

### Recommended frontend stack

- React + TypeScript
- React Router
- TanStack Query for REST bootstrap and mutations
- Zustand or Redux Toolkit for websocket-driven live state
- Cytoscape for graph
- Plain CSS variables or a lightweight design system, not component-library tourism

### Why not Context-only

Context is fine until live state, alerts, overrides, reconnect status, route params, and optimistic form state all pile into one provider and turn debugging into a swamp.

### Information architecture

#### Dashboard
- thesis cards
- hot node rail
- stale feed warnings
- countdowns due soon
- active overrides banner

#### Thesis Workspace
Tabs:
- Overview
- Graph
- Cascade
- Scenarios
- Portfolio
- Journal
- Provenance

#### Alerts
- durable timeline
- filters by thesis, event type, severity, time range

#### Ops
- feed health
- websocket status
- last fetch times
- snapshot revisions

### UX upgrades beyond parity

- “Why changed” drawer for every alert
- highlight nodes changed since previous revision
- pinned nodes / watchlist per browser session
- compare scenario result vs live baseline side by side
- show provenance inline for nodes and thresholds

## Alerting Model

The app should distinguish durable alerts from ephemeral UI toasts.

### Durable
Persisted in `alert_events`:
- node state changes
- phase changes
- feed degraded/stale transitions
- override applied/cleared

### Ephemeral
UI only:
- websocket disconnected
- reconnecting
- server resync required

### Severity mapping
- `critical`: fired node or high-salience phase jump
- `warning`: approaching, degraded feeds, override active
- `info`: monitoring changes, journal created, reconnect recovered

## External Integration: Dialectic

Do not place Dialectic pushes directly in the core update transaction path.

### Use outbox delivery

1. Snapshot commit inserts an outbox row.
2. Outbox worker drains pending rows.
3. Success marks delivered.
4. Failure increments attempts and schedules retry.

### Benefit

The desk remains truthful even if Dialectic is down or slow.

## Config Reload Strategy

Production should not watch the filesystem and freestyle reload config state mid-flight.

### Better approach

- Explicit `reload-definitions` admin endpoint or service restart.
- On reload, compute new `definitionHash`.
- Re-evaluate snapshots against the new definition.
- Emit `runtime.status` messages for affected theses.

### Dev mode

Filesystem watch is acceptable in local development only.

## Security and Deployment

“No auth because private droplet” is not a control. It is a hope.

### Minimum acceptable posture

Keep no app auth if you want, but require one of:
- Tailscale,
- Cloudflare Access,
- reverse proxy basic auth,
- strict IP allowlist + firewall.

### Production topology

- Nginx or Caddy serves built frontend.
- Reverse proxy `/api` and websocket traffic to uvicorn.
- FastAPI does not need to serve the SPA in production unless you explicitly want single-process simplicity.
- SQLite lives on persistent disk under `data/`.
- Daily backup of the SQLite file plus WAL checkpoint.
- systemd service for API.

## Observability

This is missing from the original plan and it will bite you.

### Structured logs

Every log line should include:
- `thesisId`
- `revision`
- `runId`
- `messageType`
- `durationMs`
- `status`

### Metrics

Track at minimum:
- fetch duration by provider and thesis,
- propagate duration by thesis,
- websocket connected clients,
- alert events per hour,
- stale theses count,
- outbox backlog,
- DB write failures.

### Health endpoints

- liveness: process up
- readiness: DB writable, runtime initialized, no fatal startup failures

## Testing Strategy

The current plan has unit tests, which is necessary but not sufficient.

### Add these test layers

#### Contract tests
Validate REST and websocket payload shapes against schemas.

#### Snapshot consistency tests
Given a fixed config and fixed input fixtures, snapshot output stays stable.

#### Diff tests
Ensure only meaningful changes create events.

#### Runtime serialization tests
Two overlapping requests for the same thesis do not corrupt revisions.

#### Outbox tests
Failed Dialectic delivery does not block snapshot commits.

#### Close-observation tests
Market-date dedupe, timezone boundaries, threshold-specific counting.

#### Browser integration tests
Open two clients, apply override in one, verify update in both.

### Acceptance benchmarks

- bootstrap API < 500 ms on warm start for current thesis set
- thesis refresh cycle < 2 s typical
- websocket event delivery < 250 ms after commit on local droplet
- reconnect recovers without page reload

## Refactored Delivery Plan

## Milestone 0: Contracts and packaging

### Goal
Define the system before building UI chrome.

### Deliverables
- extract engine into proper package
- Pydantic schemas for snapshot, events, API
- TS type generation from OpenAPI
- migration runner
- explicit config loader with `definitionHash`

### Exit gate
One golden snapshot fixture round-trips through backend schema and frontend types.

## Milestone 1: Runtime core

### Goal
Produce committed snapshots and durable events reliably.

### Deliverables
- runtime coordinator
- per-thesis scheduler and locks
- fetch providers wrapped behind adapters
- thesis snapshot repository
- alert event repository
- bootstrap API
- websocket bootstrap + delta flow

### Exit gate
Two browser clients stay in sync across a forced state change.

## Milestone 2: Read-only desk UI

### Goal
Ship the operator console before adding mutation complexity.

### Deliverables
- dashboard
- thesis workspace with overview, graph, cascade, portfolio
- alert timeline
- stale/fresh indicators
- why-changed panels

### Exit gate
Old static HTML can be retired for read-only monitoring.

## Milestone 3: Interactive workflows

### Goal
Add safe writes.

### Deliverables
- scenario evaluation
- journal create/filter
- manual overrides with TTL and clear action
- override audit trail

### Exit gate
Shared override appears on both clients and expires correctly.

## Milestone 4: Ops and integrations

### Goal
Make the system survivable.

### Deliverables
- outbox worker for Dialectic
- close observation logic
- health endpoints
- structured logs and metrics
- deployment scripts and backups

### Exit gate
External push failure does not affect runtime truth.

## Concrete Requirement Additions

Add these requirements explicitly. They are missing but important.

- **R27. Canonical snapshot schema with revision number and quality metadata**
- **R28. Manual overrides persisted with TTL, actor, and precedence rules**
- **R29. Durable event model for state changes and feed health**
- **R30. Bootstrap endpoint for deterministic first render**
- **R31. Outbox-based external delivery for Dialectic**
- **R32. Health, readiness, metrics, and structured logging**
- **R33. Config definition hashing and explicit production reload path**
- **R34. Market close policy configuration per applicable node/instrument group**
- **R35. Shared-state conflict semantics for two concurrent users**

## Final Recommendation

Do not frame this as “port the HTML dashboard to React.” Frame it as:

**Build a runtime-first trading desk platform with deterministic snapshots, durable events, and a thin operator UI on top.**

That keeps the existing engine intact, preserves your current scope, and upgrades the system where it actually matters: truth boundaries, event semantics, recoverability, and operator trust.
