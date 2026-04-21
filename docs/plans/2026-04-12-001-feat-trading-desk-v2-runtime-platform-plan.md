---
title: "feat: Trading Desk v2 — runtime-first platform with deterministic snapshots and durable events"
type: feat
status: active
date: 2026-04-12
deepened: 2026-04-12
origin: tradingdesk-web-ui-v2-spec.md
supersedes: docs/plans/2026-03-31-002-feat-trading-desk-web-ui-plan.md
---

# feat: Trading Desk v2 — Runtime-First Platform

## Implementation Status (2026-04-21)

13 of 15 units shipped. Remaining: overrides (partial), scenarios.

| Milestone | Units | Status |
|---|---|---|
| M0 Contracts & Packaging | 1–5 | ✅ shipped |
| M1 Runtime Core | 6–9 | ✅ shipped |
| M2 Read-Only Desk Upgrades | 10, 11, 12 | 11 ✅ (d040326, 4fa1901); 12 ✅; 10 partial |
| M3 Interactive Workflows | 13, 14 | 14 ✅ (39851d5); 13 not started |
| M4 Engine Hardening | 15 | ✅ shipped — cumulative path-lag horizon + structured validator (658e235) |

See per-unit checkboxes below for detail. Unit 10 has override CRUD inside `repository.py`/`coordinator.py` but no dedicated `web/runtime/overrides.py` or `web/routes/v1/overrides.py`; precedence merge and expiry path are incomplete.

## Sequencing vs `2026-04-20-001` (live-data cockpit)

Two active plans share `web/runtime/coordinator.py` and the engine. To avoid merge conflict and scope drift, the tail of this plan is sequenced against the cockpit plan as follows:

**Phase A — Engine-correctness sprint (this plan, ~1 week, blocks nothing in cockpit M1):**

1. **Unit 15** (horizon propagation fix). Pure engine, no runtime overlap. `propagate_at_horizon` currently uses a per-edge filter; the cumulative-path-lag rewrite lands first so any book that relies on horizons — including the new ai-capex / china-property / japan-rates demos — produces correct results.
2. **Unit 11** (close-observation table). Touches coordinator + engine + TV adapter. Land before cockpit Unit 6 (live-tape bus) to keep TV webhook routing through the coordinator lock unchanged.

Both are strictly additive to the runtime contract — no new WS envelope types, no new REST shapes. Safe to ship independently of cockpit work.

**Phase B — Cockpit M1 starts in parallel with v2 tail (overlapping OK):**

- **Unit 10** (overrides): completes while cockpit M1 Units 1–5 (relay + FRED + calendar + curve + freshness) are in flight. Overrides route lives under `/api/v1/overrides`; cockpit M1 adds no collisions there.
- **Unit 13** (scenario evaluation): runs alongside cockpit M2. Scenario route is read-only and never touches the coordinator's mutation lock.
- **Unit 14** (health/readiness + structured logging): lands last on this plan. Cockpit M3 (agent-in-room panel) benefits from the structured log context — sequence 14 before cockpit Unit 11.

**Hard contention rule:** if a cockpit unit and a v2 tail unit both need `coordinator.py`, v2 ships first (engine correctness beats feature adds). All other files are non-overlapping per the unit specs above.

**Exit criteria for v2 plan:** all 15 units `[x]`, live rooms (hormuz, tariffs) running on the new runtime for 48 hours without coordinator restart, full test suite green.

## Overview

Rebuild the trading desk web layer from a page-first React port into a runtime-first platform. The center of the system becomes a **RuntimeCoordinator** that produces deterministic snapshots, emits durable events, and fans out structured WebSocket updates. SQLite replaces file-based JSON/JSONL persistence. The engine gets proper Python packaging (no `sys.path` hacks). The existing React frontend and chat system are preserved and evolved in place.

This is not "port the HTML dashboard to React." It is: **build a runtime that emits trustworthy snapshots and events, with a thin operator console on top.**

## Problem Frame

The v1 web layer works but has structural problems that will compound:

1. **No runtime ownership.** Fetch, diff, persistence, WebSocket broadcast, and external push are scattered across routes and adapters with no central coordinator. One stalled external dependency can silently degrade the whole desk.
2. **File-based persistence is fragile.** JSON/JSONL with fcntl locks works for append-only logs but breaks down for read-modify-write operations (journal updates, prediction resolution do full-file rewrites under exclusive locks).
3. **No durable events.** State transitions are ephemeral — if the WebSocket broadcast fails, the change is lost. No audit trail of what changed and when.
4. **No snapshot revisions.** No way to know what version of truth a client is looking at, whether it's stale, or whether a reconnecting client missed updates.
5. **Engine imports via sys.path hacks.** Four `sys.path.insert` calls in `web/main.py` to import CLI tools as bare modules. Breaks IDE navigation, complicates testing, and is fragile across environments.
6. **Split-brain engine logic.** Python and browser JS both evaluate the thesis graph with concrete mismatches (deadline nodes, gate nodes, confluence scoring, phase derivation). v2 eliminates the browser engine entirely — Python is sole authority, React is display-only.
7. **No override model.** Manual state changes are ephemeral WebSocket messages with no persistence, no TTL, no audit trail, no precedence rules.

(see origin: tradingdesk-web-ui-v2-spec.md)

## Requirements Trace

- R27. Canonical snapshot schema with revision number and quality metadata
- R28. Manual overrides persisted with TTL, actor, and precedence rules
- R29. Durable event model for state changes and feed health
- R30. Bootstrap endpoint for deterministic first render
- R31. Outbox-based external delivery for Dialectic
- R32. Health, readiness, metrics, and structured logging
- R33. Config definition hashing and explicit production reload path
- R34. Market close policy configuration per applicable node/instrument group
- R35. Shared-state conflict semantics for two concurrent users
- R36. Single canonical close-observation source (SQLite table, not node field mutation)
- R37. Engine properly packaged — no sys.path hacks
- R38. Versioned WebSocket protocol with bootstrap + delta semantics
- R39. Chat system preserved alongside thesis-event protocol
- R40. Data migration from file-based state to SQLite
- R41. Horizon propagation math fix (cumulative path lag, not per-edge filter)

## Scope Boundaries

- No broker execution, order management, or real P&L
- No public multi-tenant SaaS
- No in-app config editing (edit JSON directly)
- No mobile-native workflows
- Browser JS evaluation code is deleted — Python is sole propagation authority
- The static HTML generator (`thesisgraph.py --output`) remains functional as a build target

### Deferred to Separate Tasks

- Frontend state management upgrade (Zustand/Redux): separate PR after runtime is stable
- OpenAPI → TypeScript type generation: separate tooling PR after API v1 is locked
- Nginx/Caddy reverse proxy setup: separate deployment PR
- Dead config surface cleanup (`logic`, `additionalCondition`, `regimes`): separate refactor after v2 ships

## Context & Research

### Relevant Code and Patterns

- **Current persistence:** `web/state.py` (413 lines) — `read_json`/`write_json`/`read_jsonl`/`append_jsonl` with fcntl locks and atomic temp+rename writes
- **Current adapter pattern:** `web/adapters/` — thin wrappers isolating CLI tool interfaces from HTTP plumbing, never import FastAPI
- **Current WS manager:** `web/ws.py` (190 lines) — singleton `ConnectionManager` with 5 broadcast methods and 5-second send timeout
- **Current per-book locks:** `web/adapters/tradingview.py:43-49` — `_book_locks: Dict[str, asyncio.Lock]` for serializing concurrent webhook mutations
- **Current thesis cache:** `web/adapters/thesis.py:24-25` — `_state_cache` with 60s TTL, manual invalidation
- **Engine contract:** 12 functions called from web layer (load_config, propagate, score_confluence, get_current_phase, eval_scenario, export_state, fetch_prices, fetch_polymarket, etc.)
- **Engine mutation:** `fetch_prices` and `fetch_polymarket` mutate the cfg dict in place — must deep-copy before calling
- **Test patterns:** `test_web.py` (50 tests) and `test_tradingview.py` (100 tests) use isolated `tmp_path` state dirs, module-level `TestClient`, `autouse` fixtures for state isolation

### Institutional Learnings

- XSS in generated HTML from JSON config values — `esc()` at render time, `html.escape(quote=True)` at generation time (see `docs/solutions/security-issues/`)
- `update_config_file` uses correct atomic tmp+replace pattern — preserve this in any write-back paths

### External References

- SQLite WAL mode with `synchronous=NORMAL` is safe for process crashes (WAL protects)
- Per-operation connection pattern for `asyncio.to_thread` avoids "SQLite objects created in a thread can only be used in that same thread" errors
- Outbox pattern: snapshot commit + outbox INSERT in same transaction guarantees delivery-or-nothing
- Coordinator pattern: mutation queue with futures lets routes `await coordinator.submit()` and get back results under the per-thesis lock

## Key Technical Decisions

- **Evolve web/ in place, don't create new server/ package:** 150 existing tests keep working throughout. Add new modules (`web/runtime/`, `web/persistence/`, `web/schemas/`) alongside existing code. Migrate incrementally. (User chose this over clean-break server/ rebuild.)
- **Coordinator patches deep-copy for engine input:** Deep-copy immutable definition, patch in provider values + active overrides from SQLite, pass merged dict to `propagate()`. Engine code unchanged. Override precedence: manual override > fresh provider > prior provider > config default. (User chose this over engine-level adapter or engine signature change.)
- **SQLite close_observations table is canonical:** Both `compute_derived_indicators()` and TradingView `incrementClosesObserved` webhook INSERT into the table (with PK dedup) instead of directly mutating node fields. Engine reads count from table. Eliminates triple-counting risk. (User chose this over dual-source or TV-only.)
- **Rename + pyproject.toml for engine packaging:** Rename `tools/thesis_graph/` → `tools/thesis_graph/`, `tools/data_fetch/` → `tools/data_fetch/`. Add `pyproject.toml`, `pip install -e .`. Normal Python imports everywhere. (User chose this over shims or deferral.)
- **Chat kept alongside thesis events:** Chat messages become additional WS envelope types (`chat.message`, `chat.typing`, etc.) on the same connection. Rooms and LLM integration stay. (User chose this over separate endpoints or dropping chat.)
- **Migrate existing data to SQLite:** One-time migration script reads `web/data/` JSON/JSONL files and populates SQLite tables. Old files archived. (User chose this over fresh start or lazy migration.)
- **One asyncio.Lock per thesis, shared by all mutation paths:** Scheduler fetch, on-demand price fetch, TradingView webhook, manual override creation, and config reload all acquire the same per-thesis lock. No separate lock namespaces.
- **JSON blobs in SQLite TEXT columns for snapshots:** Snapshots are read-mostly, written atomically, consumed whole. SQLite's `json_extract()` available for ad-hoc queries. No ORM, no normalization.

## Open Questions

### Resolved During Planning

- **Engine-input merge strategy:** Coordinator deep-copies immutable definition, patches in runtime inputs. Engine code unchanged.
- **Data migration:** One-time script, old files archived.
- **Chat fate:** Kept alongside thesis events on unified WS protocol.
- **Code layout:** Evolve web/ in place.
- **Close observation canonical source:** SQLite table with PK dedup.
- **Engine packaging:** Rename + pyproject.toml.
- **Lock sharing:** Single per-thesis lock for all mutation paths.

### Deferred to Implementation

- Exact staleness thresholds for Yahoo Finance and Polymarket providers (values TBD during M1 scheduler implementation)
- `dedupe_key` format for alert events — proposed: `{thesis_id}:{event_type}:{node_id}:{revision}` but finalize during M1 event repository implementation
- Outbox retry policy constants — proposed: exponential backoff starting 30s, max 5 attempts, dead entries marked `failed`
- `runtime.status` event payload shape — finalize during M1 coordinator implementation
- Scenario `againstRevision` parameter mapping — query param vs body field, decide during M3

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                        │
│                                                                 │
│  ┌──────────┐   ┌──────────────────────────────────────────┐   │
│  │  Routes   │──>│         RuntimeCoordinator               │   │
│  │  (REST +  │   │                                          │   │
│  │   WS)     │   │  ┌────────────────────────────────────┐  │   │
│  └──────────┘   │  │  Per-Thesis Lock (asyncio.Lock)    │  │   │
│       │          │  │  ┌────────────────────────────────┐ │  │   │
│       │          │  │  │ 1. Deep-copy definition        │ │  │   │
│       │          │  │  │ 2. Patch provider values       │ │  │   │
│       │          │  │  │ 3. Overlay active overrides    │ │  │   │
│       │          │  │  │ 4. propagate(merged_cfg)       │ │  │   │
│       │          │  │  │ 5. Diff vs prior snapshot      │ │  │   │
│       │          │  │  │ 6. DB txn: snapshot + events   │ │  │   │
│       │          │  │  │    + outbox                    │ │  │   │
│       │          │  │  │ 7. WS broadcast deltas        │ │  │   │
│       │          │  │  └────────────────────────────────┘ │  │   │
│       │          │  └────────────────────────────────────┘  │   │
│       │          │                                          │   │
│       │          │  ┌──────────┐  ┌───────────────┐        │   │
│       │          │  │Scheduler │  │ Outbox Worker  │        │   │
│       │          │  │(tick per │  │ (drain pending │        │   │
│       │          │  │ thesis)  │  │  → Dialectic)  │        │   │
│       │          │  └──────────┘  └───────────────┘        │   │
│       │          └──────────────────────────────────────────┘   │
│       │                          │                              │
│       │          ┌───────────────v──────────────────┐           │
│       │          │       SQLite (WAL mode)          │           │
│       │          │  thesis_snapshots                │           │
│       │          │  alert_events                    │           │
│       │          │  journal_entries                 │           │
│       │          │  close_observations              │           │
│       │          │  manual_overrides                │           │
│       │          │  fetch_runs                      │           │
│       │          │  outbox                          │           │
│       │          │  rooms / messages / predictions  │           │
│       │          │  schema_migrations               │           │
│       │          └─────────────────────────────────┘           │
│       │                                                        │
│  ┌────v─────────────────────────────────────────────────────┐  │
│  │              WebSocket Manager                            │  │
│  │  Envelope: {v:1, type, ts, thesisId, revision, payload}  │  │
│  │  Types: bootstrap, snapshot.delta, alert.created,         │  │
│  │         override.changed, chat.message, chat.typing,      │  │
│  │         presence, tv_alert, error, ping/pong              │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Effective config construction sequence:**

```
immutable_definition (books/*.json, loaded once)
    │
    ├── deep_copy()
    │
    ├── patch: provider values (Yahoo prices, Polymarket probabilities)
    │         from latest fetch run
    │
    ├── patch: close observation counts
    │         from close_observations table (COUNT per node per threshold)
    │
    ├── overlay: active manual overrides (status='active', not expired)
    │           override.field → node[field] replacement
    │
    └── merged_cfg → propagate() → score_confluence() → export_state()
                                                              │
                                                        ThesisSnapshot
```

## Implementation Units

### Milestone 0: Contracts and Packaging

- [x] **Unit 1: Engine directory rename + pyproject.toml**

**Goal:** Eliminate `sys.path` hacks. Make all engine modules properly importable via normal Python imports.

**Requirements:** R37

**Dependencies:** None

**Files:**
- Rename: `tools/thesis_graph/` → `tools/thesis_graph/`
- Rename: `tools/data_fetch/` → `tools/data_fetch/`
- Create: `tools/thesis_graph/__init__.py` — re-export public API (propagate, score_confluence, etc.)
- Create: `tools/data_fetch/__init__.py` — re-export polymarket, derived_indicators
- Create: `tools/outcomes/__init__.py` — re-export lifecycle_monitor, cross_book, morning_brief
- Create: `tools/bridge/__init__.py` — re-export diff_snapshots, push_to_dialectic, run_all
- Rename: `tools/bridge/diff_snapshots.py` → `tools/bridge/diff_snapshots.py`
- Rename: `tools/bridge/push_to_dialectic.py` → `tools/bridge/push_to_dialectic.py`
- Rename: `tools/bridge/sign_tv_alert.py` → `tools/bridge/sign_tv_alert.py`
- Create: `pyproject.toml` — editable install with `[tool.setuptools.packages.find]`
- Modify: `web/main.py` — remove all `sys.path.insert` calls
- Modify: `web/adapters/thesis.py` — change `import thesisgraph` to `from tools.thesis_graph import thesisgraph`
- Modify: `web/adapters/market.py` — update imports
- Modify: `web/adapters/outcomes.py` — update imports
- Modify: `web/adapters/tradingview.py` — update imports
- Modify: all test files — update import paths
- Modify: `tools/bridge/run_all.py` — update internal imports
- Modify: all `.md` files referencing `thesis-graph` or `data-fetch` paths (CLAUDE.md, README.md, PROJECT.md, docs/, deploy/)
- Test: existing 505 tests must pass after rename

**Approach:**
- Rename directories and files (underscores for Python package names)
- Add `__init__.py` to each tools/ subpackage re-exporting the public API
- Add `pyproject.toml` at repo root with `[project.scripts]` entries preserving CLI entry points (`thesisgraph`, `diff-snapshots`, etc.)
- Run `pip install -e .` — all imports become standard
- Remove `sys.path.insert` calls from `web/main.py`
- Update adapter imports from bare `import thesisgraph` to `from tools.thesis_graph import thesisgraph`
- Keep existing CLI usage working via `[project.scripts]` entrypoints

**Patterns to follow:**
- `update_config_file` atomic write pattern at `thesisgraph.py:766-787`

**Test scenarios:**
- Happy path: `from tools.thesis_graph.thesisgraph import propagate` works in Python REPL
- Happy path: `pip install -e .` succeeds, `thesisgraph --help` CLI still works
- Happy path: all 505 existing tests pass without sys.path hacks
- Edge case: CLI scripts invoked directly (`python tools/thesis_graph/thesisgraph.py`) still work
- Integration: `web/adapters/thesis.py` imports resolve correctly when running `uvicorn web.main:app`

**Verification:**
- Zero `sys.path.insert` calls remain in the codebase
- `grep -r 'thesis-graph\|data-fetch' --include='*.md'` returns zero matches (all docs updated)
- All test suites pass
- CLI entry points work

---

- [x] **Unit 2: Pydantic schemas for snapshot, events, and API contracts**

**Goal:** Define the v2 data contracts as Pydantic models. These become the single source of truth for snapshot shape, event shape, API request/response, and WebSocket envelopes.

**Requirements:** R27, R29, R38

**Dependencies:** Unit 1

**Files:**
- Create: `web/schemas/__init__.py`
- Create: `web/schemas/snapshots.py` — ThesisSnapshot, SnapshotQuality, NodeState, etc.
- Create: `web/schemas/events.py` — AlertEvent, EventType enum, severity mapping
- Create: `web/schemas/api.py` — BootstrapResponse, ThesisSummary, OverrideRequest, etc.
- Create: `web/schemas/ws.py` — WSEnvelope, S2C/C2S message types
- Test: `web/schemas/test_schemas.py`

**Approach:**
- ThesisSnapshot model mirrors the spec's derived snapshot shape: thesisId, revision, generatedAt, definitionHash, quality (status, lastSuccessAt, stale, issues), watermarks, summary (nodeCounts, phase, topCountdowns), graph (nodes, edges), portfolio, scenarios, activeOverrides, closeStatus
- AlertEvent model: event_id, thesis_id, revision, event_type (enum: node.state_changed, phase.changed, countdown.threshold_crossed, feed.health_changed, override.applied, override.cleared, journal.created, snapshot.recomputed), severity (critical/warning/info), node_id, old_value_json, new_value_json, occurred_at, dedupe_key
- WSEnvelope: v (protocol version, default 1), type (discriminator), ts, thesisId, revision, payload
- Chat message types added to WS envelope: chat.message, chat.typing, chat.presence
- BootstrapResponse: thesis catalog, latest snapshots (keyed by thesisId), active overrides, recent alerts

**Patterns to follow:**
- Existing `web/models.py` Pydantic patterns (Literal types, field validation)
- Snapshot shape from `export_state()` at `thesisgraph.py:646-658`

**Test scenarios:**
- Happy path: Valid snapshot JSON round-trips through ThesisSnapshot model
- Happy path: Valid AlertEvent serializes with correct dedupe_key format
- Happy path: WSEnvelope validates type discriminator against allowed S2C/C2S types
- Edge case: Snapshot with missing optional fields (no countdowns, no scenarios) validates
- Error path: Snapshot with invalid quality.status rejects with clear error
- Error path: AlertEvent with unknown event_type rejects
- Integration: Existing `export_state()` output validates against ThesisSnapshot (may need adapter)

**Verification:**
- Golden snapshot fixture from `books/iran-hormuz-graph.json` round-trips through schema
- All event types have severity mappings

---

- [x] **Unit 3: SQLite persistence layer + migration runner**

**Goal:** Replace `web/state.py` file-based persistence with SQLite. Implement a simple migration runner and initial schema.

**Requirements:** R27, R29, R40

**Dependencies:** Unit 2

**Files:**
- Create: `web/persistence/__init__.py`
- Create: `web/persistence/connection.py` — connection factory with WAL mode, pragmas
- Create: `web/persistence/migrations.py` — schema_migrations table + SQL file runner
- Create: `web/persistence/sql/001_initial_schema.sql` — all tables
- Create: `web/persistence/repository.py` — Repository class with CRUD methods
- Test: `web/persistence/test_persistence.py`

**Approach:**
- Connection factory: `sqlite3.connect()` with WAL mode, `busy_timeout=5000`, `foreign_keys=ON`, `synchronous=NORMAL`, `row_factory=sqlite3.Row`
- Per-operation connections (not shared across threads) — each Repository method opens/closes its own connection
- Migration runner: `schema_migrations` table tracks applied versions. SQL files in `web/persistence/sql/` named `NNN_description.sql`. Runner applies pending migrations in order.
- Initial schema (001): `thesis_snapshots`, `alert_events`, `journal_entries`, `close_observations`, `manual_overrides`, `fetch_runs`, `outbox`, `rooms`, `messages`, `pins`, `predictions`, `tv_events`
- Repository methods cover all current `web/state.py` operations: rooms CRUD, messages (cursor pagination), pins, journal, predictions, TV events, plus new: snapshots, alerts, overrides, close observations, outbox
- All Repository methods are synchronous — callers wrap in `asyncio.to_thread()`

**Patterns to follow:**
- `web/state.py` ID generation (`uuid.uuid4()`) and validation (`re.fullmatch(r"[a-zA-Z0-9_-]+")`)
- Atomic snapshot+outbox INSERT in single transaction (see Key Technical Decisions)

**Test scenarios:**
- Happy path: Migration runner creates all tables on fresh DB
- Happy path: Migration runner is idempotent — running twice applies nothing the second time
- Happy path: save_snapshot → get_latest_snapshot round-trip preserves JSON content
- Happy path: append_message → list_messages returns correct order with cursor pagination
- Happy path: save_snapshot_and_enqueue → both snapshot and outbox row exist in same transaction
- Edge case: Concurrent reads during write (WAL mode) — readers see consistent pre-write state
- Edge case: get_latest_snapshot on empty table → returns None
- Error path: Invalid foreign key reference → rejected
- Integration: All current `web/state.py` operations have SQLite equivalents with matching semantics

**Verification:**
- `web/persistence/sql/001_initial_schema.sql` creates all required tables
- Repository matches the operation surface of `web/state.py`

---

- [x] **Unit 4: Data migration script**

**Goal:** One-time script that reads existing `web/data/` JSON/JSONL files and populates the SQLite database. Run once during first v2 deploy.

**Requirements:** R40

**Dependencies:** Unit 3

**Files:**
- Create: `web/persistence/migrate_from_files.py` — migration script
- Test: `web/persistence/test_migration.py`

**Approach:**
- Read `web/data/rooms.json` → INSERT into `rooms` table
- Read `web/data/rooms/{id}/messages.jsonl` → INSERT into `messages` table (per room)
- Read `web/data/rooms/{id}/pins.json` → INSERT into `pins` table
- Read `web/data/journal.jsonl` → INSERT into `journal_entries` table
- Read `web/data/predictions.jsonl` → INSERT into `predictions` table
- Read `web/data/tradingview-events.jsonl` → INSERT into `tv_events` table
- Idempotent: check if data already exists before inserting (by ID)
- Old files left in place after migration — archival is a manual operator step after verification (per CLAUDE.md global rule: "persist the new store to disk before removing/renaming the old file")
- CLI entry: `python -m web.persistence.migrate_from_files`
- Prints summary: rows migrated per table, any skipped records, verification queries to run

**Test scenarios:**
- Happy path: Rooms with messages and pins migrate correctly, IDs preserved
- Happy path: Journal entries with all fields (including linked_book_id) migrate
- Happy path: Predictions with resolution data migrate
- Happy path: TV events migrate with book_id filter working post-migration
- Edge case: Malformed JSONL lines skipped (matching current `read_jsonl` behavior)
- Edge case: Running migration twice is idempotent — no duplicates
- Edge case: Missing `web/data/` directory → graceful exit with message

**Verification:**
- All data from `web/data/` queryable via Repository after migration
- Message ordering preserved (by timestamp)
- Room-message relationships intact

---

- [x] **Unit 5: Wire persistence into existing routes**

**Goal:** Replace all `web/state.py` calls in existing routes with Repository calls wrapped in `asyncio.to_thread()`. Tests keep passing.

**Requirements:** R40

**Dependencies:** Units 3, 4

**Files:**
- Modify: `web/routes/rooms.py` — use Repository instead of state module
- Modify: `web/routes/messages.py` — use Repository for messages, pins
- Modify: `web/routes/journal.py` — use Repository
- Modify: `web/routes/predictions.py` — use Repository
- Modify: `web/routes/tradingview.py` — use Repository for TV events
- Modify: `web/main.py` — init Repository in lifespan, store on `app.state`
- Modify: `web/adapters/tradingview.py` — use Repository for TV event persistence
- Modify: `web/ws.py` — replace lazy import of `web.state.list_rooms()` in `broadcast_to_book_rooms()` with Repository query (pass Repository to ConnectionManager constructor during lifespan init)
- Modify: `web/test_web.py` — update fixtures to use in-memory SQLite
- Modify: `web/test_tradingview.py` — update fixtures to use in-memory SQLite
- Test: existing 150 web tests must pass

**Approach:**
- Repository instance created in lifespan, stored on `app.state.repo`
- Routes access via `request.app.state.repo`
- Every `state.read_json` / `state.write_json` / `state.append_jsonl` call replaced with equivalent Repository method wrapped in `asyncio.to_thread()`
- Test fixtures switch from `tmp_path` file dirs to in-memory SQLite (`:memory:`) with migrations applied
- `web/state.py` archived to `_archive/` (not deleted) once all references removed — preserves rollback path
- **Transitional invariant:** TradingView adapter's `_book_locks` dict remains the serialization mechanism for webhook mutations until Unit 6 centralizes it into the Coordinator. Do NOT remove TV locks in this unit.
- **Access pattern documentation:** Simple CRUD (rooms, messages, journal, predictions) accesses Repository directly via `request.app.state.repo`. Thesis-domain mutations will go through Coordinator (Unit 6).
- **Test isolation:** pytest fixture creates fresh `:memory:` SQLite per test, runs migrations, injects Repository as FastAPI dependency override via `app.dependency_overrides`. Matches existing `autouse=True` pattern.

**Test scenarios:**
- Happy path: All 50 test_web.py tests pass with SQLite backend
- Happy path: All 100 test_tradingview.py tests pass with SQLite backend
- Happy path: Room CRUD operations work identically to file-based version
- Happy path: Message pagination (cursor-based `before` param) works correctly
- Edge case: Concurrent prediction create + resolve doesn't lose data (existing concurrency test)
- Integration: Full flow — create room → send message → pin message → export → verify content

**Verification:**
- Zero remaining imports of `web.state` in route modules
- All 150 web tests pass
- `web/state.py` can be deleted (or archived)

---

### Milestone 1: Runtime Core

- [x] **Unit 6: RuntimeCoordinator + per-thesis scheduler**

**Goal:** Central coordinator that owns per-thesis locks, schedules periodic fetch/evaluate cycles, serializes mutations, and produces committed snapshots.

**Requirements:** R27, R33, R35

**Dependencies:** Units 3, 5

**Files:**
- Create: `web/runtime/__init__.py`
- Create: `web/runtime/coordinator.py` — RuntimeCoordinator class
- Create: `web/runtime/scheduler.py` — periodic tick loop
- Create: `web/runtime/diffing.py` — semantic diff between snapshots
- Modify: `web/main.py` — create Coordinator in lifespan, store on `app.state`
- Test: `web/runtime/test_coordinator.py`

**Approach:**
- Coordinator initialized in lifespan with: Repository, WS manager, tick interval (configurable, default 300s)
- Loads all thesis definitions from `books/*.json` at startup, computes `definitionHash` (SHA-256 of canonical JSON)
- Per-thesis `asyncio.Lock` — single lock shared by scheduler, on-demand fetch, TV webhook, and override creation
- `submit(book_id, op, payload, timeout=10.0)` → queues mutation, awaits result under lock. Timeout prevents TV webhooks from blocking indefinitely during long fetch cycles — returns 503 with Retry-After header on timeout.
- Tick loop: for each thesis, acquire lock → `_run_cycle(book_id)`:
  1. Deep-copy immutable definition
  2. Fetch providers via `asyncio.to_thread`: `fetch_prices()` + `fetch_polymarket()` on the copy. Also `fetch_ohlcv_for_derived()` + `compute_derived_indicators()` for nodes with derivedIndicators specs.
  3. **Persist raw provider values:** INSERT fetch_run with `provider_values_json` column storing the raw price/probability map. On coordinator restart, latest fetch_run's provider values hydrate the effective config — no stale prices from books/*.json.
  4. Query active overrides from SQLite
  5. Apply override precedence (override > fresh provider > prior provider > config default) to merged cfg
  6. Query close observation streak counts from SQLite (see Unit 11 for streak calculation), patch into merged cfg
  7. `propagate()` + `score_confluence()` + `get_current_phase()` + `export_state()`
  8. Semantic diff vs prior committed snapshot
  9. Single DB transaction: INSERT fetch_run, UPSERT snapshot, INSERT alert_events (with dedupe_key), INSERT outbox rows if Dialectic room configured
  10. Release lock
  11. Broadcast WS deltas
- Cycle-already-running guard: if lock is held, skip that thesis for this tick
- Continue-on-failure: one thesis error doesn't stop others
- **Restart recovery:** On startup, coordinator loads definitions from books/*.json, then queries latest fetch_run per thesis for provider_values_json. Hydrates effective configs with persisted provider values before first tick. If no fetch_run exists, first tick does a full fetch.
- Coordinator lifecycle: `start()` creates tick + drain tasks, `stop()` cancels them

**Patterns to follow:**
- Current `web/adapters/tradingview.py:43-49` per-book lock pattern (centralized into Coordinator)
- Current `web/adapters/thesis.py` engine calling pattern (load_config, propagate, etc.)

**Test scenarios:**
- Happy path: Coordinator starts, loads 2 thesis definitions, computes definitionHashes
- Happy path: Tick cycle produces committed snapshot with correct revision number
- Happy path: submit("iran-hormuz", "fetch_prices", {}) acquires lock, runs cycle, returns snapshot
- Edge case: Concurrent submits for same thesis serialize (second waits for lock)
- Edge case: Concurrent submits for different theses run in parallel
- Edge case: Tick cycle skips thesis if lock is already held
- Edge case: submit() with timeout — lock held by long fetch cycle → returns timeout error within 10s
- Edge case: 5 consecutive skipped ticks → staleness flag set on thesis quality metadata
- Edge case: Coordinator restart → hydrates effective config from latest fetch_run provider_values → snapshot matches pre-restart state for same inputs
- Error path: Fetch failure → logged, previous snapshot preserved, no crash
- Error path: One thesis fails during tick → other theses still evaluated
- Integration: Two sequential cycles with a price change → second produces diff with state transitions

**Verification:**
- Snapshots in SQLite have incrementing revision numbers
- No overlapping evaluations for the same thesis
- Coordinator shutdown is clean (no orphaned tasks)

---

- [x] **Unit 7: Durable alert events + event repository**

**Goal:** Persist meaningful state transitions as durable events in SQLite. Events survive process restarts and WebSocket disconnections.

**Requirements:** R29

**Dependencies:** Unit 6

**Files:**
- Modify: `web/runtime/diffing.py` — generate typed AlertEvent records from snapshot diffs
- Modify: `web/persistence/repository.py` — alert event CRUD (insert_events, list_events with filters)
- Modify: `web/runtime/coordinator.py` — emit events during commit transaction
- Test: `web/runtime/test_events.py`

**Approach:**
- Event types (from spec): `node.state_changed`, `phase.changed`, `countdown.threshold_crossed`, `feed.health_changed`, `override.applied`, `override.cleared`, `journal.created`, `snapshot.recomputed`
- Severity mapping: critical (fired node, high-salience phase jump), warning (approaching, degraded feed, active override), info (monitoring changes, journal, reconnect)
- `dedupe_key`: `{thesis_id}:{event_type}:{node_id or ''}:{revision}` — UNIQUE constraint prevents duplicate events
- Diffing logic: compare old vs new snapshot, generate events for each meaningful change
- Events INSERTed in same transaction as snapshot UPSERT
- Do NOT emit events for every price tick — only for state changes, phase changes, and threshold crossings

**Patterns to follow:**
- Current diff logic in `tools/bridge/diff_snapshots.py` (state transitions, confluence shifts)

**Test scenarios:**
- Happy path: Node state change (stable → approaching) generates node.state_changed event with correct severity
- Happy path: Phase change generates phase.changed event
- Happy path: Events persisted in same transaction as snapshot
- Edge case: No state changes → no events emitted (noisy ticks suppressed)
- Edge case: Duplicate event (same dedupe_key) → INSERT OR IGNORE, no error
- Error path: Malformed diff → logged, snapshot still committed
- Integration: list_events with thesis_id filter returns only relevant events, ordered by occurred_at DESC

**Verification:**
- Events persist across process restarts
- Event count matches actual state transitions (no noise)

---

- [x] **Unit 8: WebSocket protocol upgrade — bootstrap + delta + chat**

**Goal:** Versioned WebSocket protocol with structured envelopes. Bootstrap on connect, incremental deltas thereafter. Chat messages as additional envelope types.

**Requirements:** R30, R38, R39

**Dependencies:** Units 6, 7

**Files:**
- Modify: `web/ws.py` — add envelope wrapping, bootstrap send, seq tracking
- Modify: `web/routes/messages.py` — use new envelope format for all WS messages
- Create: `web/runtime/bootstrap.py` — assemble bootstrap payload from latest snapshots + overrides + alerts
- Modify: `web/runtime/coordinator.py` — broadcast deltas through WS manager with seq numbers
- Test: `web/test_ws_protocol.py`

**Approach:**
- All WS messages wrapped in envelope: `{v: 1, type, ts, thesisId, revision, payload, seq}`
- `seq`: server-assigned monotonic integer per connection, incremented on every S2C message
- On connect: server sends `bootstrap` message scoped to the room's linked thesis plus a global thesis catalog. Client gets: linked thesis snapshot + active overrides + recent alerts for that thesis, plus a lightweight catalog (IDs, titles, phases) of all theses for the dashboard sidebar. Clients needing cross-thesis data use the REST bootstrap endpoint.
- After bootstrap: state changes sent as `snapshot.delta` with changed nodes, summary, phase, overrides
- Chat messages: `chat.message`, `chat.typing`, `chat.presence` — existing chat logic preserved, just wrapped in new envelope
- LLM streaming: `llm.chunk`, `llm.done` — existing streaming preserved in envelope
- TV alerts: `tv.alert` — existing broadcast preserved in envelope
- Client reconnection: server sends full bootstrap again (no delta replay — snapshots are <5KB per thesis)
- Ping/pong keepalive: server sends `ping` every 30s, disconnects if no `pong` within 10s
- **Backward compatibility strategy:** Frontend update ships in this same unit (not deferred). The server sends only the new envelope format. This is safe because: (a) only 2 users, (b) single deployment target, (c) frontend and backend deploy atomically via the same git commit. No dual-format period needed.

**Patterns to follow:**
- Current `web/ws.py` broadcast methods (5 variants: to room, to all, to book rooms, to single, dead cleanup)
- Current `web/routes/messages.py` WS auth flow (JWT as first frame or query param)

**Test scenarios:**
- Happy path: Client connects → receives bootstrap with all thesis snapshots
- Happy path: State change → all connected clients receive snapshot.delta with incrementing seq
- Happy path: Chat message sent → all room members receive chat.message envelope
- Happy path: LLM streaming → client receives llm.chunk envelopes followed by llm.done
- Edge case: Client reconnects → receives full bootstrap (no gap recovery needed)
- Edge case: seq gap detected by client → client can re-subscribe for fresh bootstrap
- Error path: Malformed C2S message → server sends error envelope, connection stays open
- Integration: Two clients connected, one sends override → both receive override.changed + snapshot.delta

**Verification:**
- All existing chat functionality works through new envelope format
- Bootstrap payload is complete enough for first render without additional REST calls

---

- [x] **Unit 9: Bootstrap REST endpoint + versioned API prefix**

**Goal:** `GET /api/v1/bootstrap` endpoint for deterministic first render. Begin versioned API surface.

**Requirements:** R30

**Dependencies:** Units 6, 7, 8

**Files:**
- Create: `web/routes/v1/__init__.py`
- Create: `web/routes/v1/bootstrap.py` — bootstrap endpoint
- Modify: `web/main.py` — mount v1 router alongside existing unversioned routes
- Test: `web/routes/v1/test_bootstrap.py`

**Approach:**
- `GET /api/v1/bootstrap` returns: thesis catalog (IDs, titles, definitionHashes), latest snapshots per thesis, active overrides, recent alert summary (counts by severity), system status (uptime, scheduler state)
- Response validated against BootstrapResponse Pydantic model
- Existing unversioned `/api/` routes remain functional — v1 routes are additive, not replacing
- New thesis-specific endpoints under `/api/v1/theses/{thesisId}/snapshot`, etc. added incrementally
- Bootstrap response should be <500ms on warm start for current thesis set

**Patterns to follow:**
- Existing `web/routes/thesis.py` patterns for book_id validation

**Test scenarios:**
- Happy path: Bootstrap returns both theses with latest snapshot data
- Happy path: Bootstrap includes active override count and recent alert counts
- Happy path: Response validates against BootstrapResponse schema
- Edge case: No snapshots yet (fresh start) → bootstrap returns empty snapshots, thesis catalog still present
- Error path: Coordinator not initialized → 503 with clear error

**Verification:**
- Frontend can render dashboard from bootstrap response alone (no additional calls needed)
- Response time <500ms with 2 theses

---

### Milestone 2: Read-Only Desk Upgrades

- [ ] **Unit 10: Manual overrides — persistence and evaluation**

**Goal:** Persisted, auditable, TTL-bound override records with clear precedence rules. Overrides are shared between both users.

**Requirements:** R28, R35

**Dependencies:** Unit 6

**Files:**
- Create: `web/runtime/overrides.py` — override lifecycle (create, clear, expire, merge into eval)
- Modify: `web/persistence/repository.py` — override CRUD (create, list active, clear by ID, expire stale)
- Create: `web/routes/v1/overrides.py` — REST endpoints (GET/POST/clear)
- Modify: `web/runtime/coordinator.py` — query active overrides during eval cycle, apply precedence
- Test: `web/runtime/test_overrides.py`

**Approach:**
- Override record: override_id, thesis_id, target_type (node/marketField/instrument), target_id, field, value_json, actor, reason, created_at, expires_at (nullable), cleared_at (nullable), status (active/expired/cleared)
- Create: `POST /api/v1/overrides` — validates target exists in definition, persists override, triggers re-evaluation
- Clear: `POST /api/v1/overrides/{id}/clear` — sets cleared_at, triggers re-evaluation
- List: `GET /api/v1/overrides` — returns active overrides (optional thesis_id filter)
- Expiry: coordinator checks `expires_at` before each eval cycle, marks expired
- Precedence merge: during eval cycle, coordinator queries active overrides and patches them onto the deep-copied config after provider values
- Last-write-wins: if two overrides target the same field, the newer one wins. User A can clear User B's override (no permission check — 2-user private system)
- Override.applied and override.cleared events emitted
- WebSocket broadcasts `override.changed` to all clients

**Patterns to follow:**
- Current `web/adapters/tradingview.py` atomic mutation pattern

**Test scenarios:**
- Happy path: Create override → next eval cycle applies it → snapshot reflects overridden value
- Happy path: Create override with TTL → after expiry, eval cycle ignores it
- Happy path: Clear override → next eval cycle reverts to provider value
- Happy path: List overrides shows active only (not expired/cleared)
- Edge case: Two overrides on same field → newer wins
- Edge case: Override targets node that doesn't exist → 400 with validation error
- Edge case: Override expires between two eval cycles → second cycle runs without it
- Error path: Invalid target_type → 422
- Integration: User A creates override → User B sees it in bootstrap and active overrides list

**Verification:**
- Override audit trail preserved (never deleted, only status changed)
- Both users see consistent override state

---

- [x] **Unit 11: Close observation table + unified counting**

**Goal:** Single canonical close-observation source in SQLite. Both derived_indicators and TradingView webhook INSERT into the table instead of mutating node fields. Streak-based counting (not total count) preserves consecutive-close semantics.

**Requirements:** R34, R36

**Dependencies:** Unit 6

**Files:**
- Modify: `web/persistence/repository.py` — close observation CRUD (insert with PK dedup, compute streak length)
- Modify: `tools/thesis_graph/thesisgraph.py` — change `compute_derived_indicators()` (line ~1029) to stop mutating `closesObserved` and instead return close event records
- Modify: `web/runtime/coordinator.py` — receives close events from engine, INSERTs into table, computes streak, patches into effective config. Also adds a mapping function that translates engine return shape to table INSERT shape (preserving engine's stdlib-only contract).
- Modify: `web/adapters/tradingview.py` — `incrementClosesObserved` op inserts into table instead of mutating node JSON
- Modify: `web/routes/tradingview.py` — rewire TV webhook route from calling `tv_adapter.apply_webhook()` directly to `coordinator.submit()` for all mutation ops (required for single-lock guarantee)
- Modify: `web/persistence/sql/001_initial_schema.sql` — close_observations table
- Test: `web/runtime/test_close_observations.py`

**Approach:**
- **Table schema:** PK `(thesis_id, node_id, market_date, threshold_key)`. Columns include `close_value` and `qualifies` (boolean — whether close was above/below threshold). INSERT every market-date close (qualifying and non-qualifying) so streak breaks are recorded explicitly.
- **Streak calculation (not total count):** The engine's `closesRequired` gate requires CONSECUTIVE closes above threshold (contiguous tail-run that resets on any close below). A bare `COUNT(*)` of qualifying rows would over-count across streak breaks. Instead, the repository method `get_close_streak(thesis_id, node_id, threshold_key)` finds the most recent non-qualifying close date and counts only qualifying rows after it. If no non-qualifying row exists, all qualifying rows count.
- **Per-threshold to per-node mapping:** The engine reads a single `node.closesObserved` field, but the table tracks per-threshold. The coordinator resolves this by: iterating the node's thresholds highest-to-lowest, finding the first where `current >= level`, querying the streak for that threshold_key, and patching that streak count as `closesObserved`. This matches the engine's own iteration order in `eval_node_state`. Current book configs have at most one `closesRequired` threshold per node, so the mapping is 1:1 in practice.
- **Engine stdlib-only contract preserved:** `compute_derived_indicators()` returns its existing dict shape — the coordinator's mapping function translates to table INSERT shape. The engine module never imports web/persistence.
- **Atomic switch:** Both the `thesisgraph.py` mutation removal AND the TV webhook table insertion ship in the same commit. No dual-source transition period.
- **TV webhook routing:** `web/routes/tradingview.py` rewired from `tv_adapter.apply_webhook()` to `coordinator.submit(book_id, "tv_webhook", payload)`. The coordinator acquires the per-thesis lock, applies the mutation, re-propagates, and broadcasts — unifying all mutation paths under a single lock.
- Close policy per node: `closePolicy.timezone`, `closePolicy.cutoffTime`, `closePolicy.tradingDays`, `closePolicy.graceMinutes` read from node config (default: US_ET, 16:00, weekdays, 15min)

**Patterns to follow:**
- Current `tools/data_fetch/derived_indicators.py` streak detection logic (`consecutive_closes_above()` at line ~148 — contiguous tail-run semantics)

**Test scenarios:**
- Happy path: Derived indicators detects close above threshold → record inserted → streak count feeds into propagation
- Happy path: TV webhook incrementClosesObserved → same table insertion via coordinator.submit()
- Happy path: Same close from both sources → PK dedup, count = 1
- Happy path: 3 consecutive qualifying closes → streak = 3 → node fires
- Happy path: 2 qualifying closes, then 1 below threshold, then 1 qualifying → streak = 1 (not 3)
- Edge case: Close below threshold → recorded with qualifies=false, resets streak
- Edge case: Two closes on same market date for same node → PK dedup, only one counts
- Edge case: 24/7 asset → cutoff boundary correctly determines market_date
- Edge case: Node with multiple thresholds — coordinator picks the correct threshold based on current price
- Edge case: Concurrent TV webhook INSERT and coordinator fetch cycle INSERT for same PK → INSERT OR IGNORE, no error
- Error path: Invalid market_date → rejected
- Integration: Full cycle: fetch → derived_indicators → close observation → streak query → propagation → node promotion

**Verification:**
- No direct mutation of `closesObserved` on node objects anywhere in the codebase
- Streak count matches `consecutive_closes_above()` output for identical input series
- TV webhook mutations go through coordinator.submit() (single lock path confirmed)

---

- [x] **Unit 12: Outbox worker for Dialectic delivery**

**Goal:** Reliable external delivery via outbox pattern. Snapshot commit + outbox INSERT in same transaction. Worker drains pending rows and POSTs to Dialectic.

**Requirements:** R31

**Dependencies:** Unit 6

**Files:**
- Create: `web/runtime/outbox.py` — outbox drain worker
- Modify: `web/persistence/repository.py` — outbox CRUD (enqueue, get_pending, mark_sent, increment_attempt, mark_failed)
- Modify: `web/runtime/coordinator.py` — use `save_snapshot_and_enqueue()` in commit transaction, start outbox worker task
- Test: `web/runtime/test_outbox.py`

**Approach:**
- Outbox table: id, book_id, destination, payload (JSON), status (pending/sent/failed), attempts, last_error, created_at, sent_at
- `save_snapshot_and_enqueue()`: single transaction — INSERT snapshot + INSERT outbox row
- Worker: asyncio task in Coordinator. Uses `asyncio.Event` — coordinator sets the event after inserting an outbox row, worker awaits it. Fallback poll every 30s if event not set (handles recovery after crashes). Eliminates unnecessary polling between 300s tick intervals.
- Delivery: HTTP POST to Dialectic API (reuse existing `push_to_dialectic.py` HTTP logic)
- Retry: exponential backoff (30s, 60s, 120s, 240s, 480s), max 5 attempts
- Dead entries: after max attempts, marked `failed` with last_error
- Pruning: daily cleanup — delete `sent` rows older than 7 days, keep `failed` for 30 days
- Dialectic room_id and token from book config `meta.dialecticRoomId` / `meta.dialecticRoomToken` (per-book token takes precedence over env var)

**Patterns to follow:**
- Current `tools/bridge/push_to_dialectic.py` HTTP POST logic
- Current `tools/bridge/run_all.py` continue-on-failure pattern

**Test scenarios:**
- Happy path: Snapshot commit → outbox row created → worker delivers → marked sent
- Happy path: Delivery failure → attempt incremented → retried on next poll
- Happy path: Max attempts exceeded → marked failed with last_error
- Edge case: Process restart → pending outbox rows survive and are retried
- Edge case: No pending rows → worker polls and sleeps (no CPU waste)
- Edge case: Multiple pending rows → delivered in order (created_at ASC)
- Error path: Dialectic returns 500 → logged, retry scheduled
- Error path: Missing room_id or token → marked failed immediately (no retry)
- Integration: Full cycle — state change → snapshot committed → outbox → mock Dialectic receives POST

**Verification:**
- Desk truth unaffected by Dialectic downtime
- Failed deliveries visible in outbox table for operator inspection

---

### Milestone 3: Interactive Workflows

- [ ] **Unit 13: Scenario evaluation — read-only, revision-bound**

**Goal:** Scenario evaluation that is explicitly read-only and bound to a specific snapshot revision. Cannot contaminate live state.

**Requirements:** R27

**Dependencies:** Unit 6

**Files:**
- Create: `web/routes/v1/scenarios.py` — `POST /api/v1/theses/{thesisId}/scenarios/{scenarioId}/evaluate`
- Modify: `web/runtime/coordinator.py` — scenario evaluation reads from committed snapshot, not live state
- Test: `web/routes/v1/test_scenarios.py`

**Approach:**
- Request optionally includes `againstRevision` (query param) — defaults to latest committed revision
- Evaluation: load snapshot at specified revision → deep-copy → apply scenario overrides → propagate → diff against base → return
- Response: baseRevision, scenarioId, changed nodes (with before/after states), portfolio impact summary, human-readable explanation
- Read-only: scenario evaluation acquires NO locks, makes NO writes. It reads a committed snapshot (immutable) and computes a hypothetical result.
- Idempotent: same inputs always produce same outputs (deterministic engine)

**Test scenarios:**
- Happy path: Evaluate scenario → returns state transitions and portfolio impact
- Happy path: Specify againstRevision → evaluates against that specific snapshot
- Happy path: Response includes baseRevision that matches the snapshot used
- Edge case: Default (no againstRevision) → uses latest committed revision
- Edge case: againstRevision for a revision that doesn't exist → 404
- Error path: scenarioId not found in definition → 404
- Integration: Scenario result does NOT appear in next snapshot or affect live state

**Verification:**
- No writes to any table during scenario evaluation
- Live desk state unchanged after scenario evaluation

---

- [x] **Unit 14: Health, readiness, and structured logging**

**Goal:** Liveness and readiness endpoints. Structured logging with thesis context.

**Requirements:** R32

**Dependencies:** Unit 6

**Files:**
- Modify: `web/routes/health.py` — split into liveness and readiness
- Create: `web/observability/__init__.py`
- Create: `web/observability/logging.py` — structured log formatter with context fields
- Modify: `web/main.py` — configure structured logging at startup
- Test: `web/routes/test_health.py`

**Approach:**
- `GET /api/v1/health/live` → 200 if process is up (always succeeds after startup)
- `GET /api/v1/health/ready` → 200 if DB writable + coordinator initialized + at least one successful tick completed. 503 otherwise with detail.
- Structured log format: JSON lines with `thesisId`, `revision`, `runId`, `messageType`, `durationMs`, `status`
- Log context: use `logging.LoggerAdapter` or contextvars to inject thesis context into log lines during coordinator cycles
- Existing health endpoint preserved at `/api/health` for backward compatibility

**Test scenarios:**
- Happy path: Live endpoint returns 200 with uptime
- Happy path: Ready endpoint returns 200 after coordinator completes first tick
- Happy path: Structured log line contains thesisId and revision during eval cycle
- Edge case: Ready endpoint returns 503 before first tick completes
- Edge case: Ready endpoint returns 503 if DB is unwritable

**Verification:**
- Health endpoints usable by external monitoring (systemd, uptime checks)
- Log output parseable by standard JSON log tooling

---

### Milestone 4: Engine Hardening

- [x] **Unit 15: Horizon propagation fix + validation hardening**

**Goal:** Fix the mathematically wrong horizon propagation and harden config validation with structured errors.

**Requirements:** R41

**Dependencies:** Unit 1

**Files:**
- Modify: `tools/thesis_graph/thesisgraph.py` — fix `propagate_at_horizon`, harden `validate_config`
- Modify: `tools/thesis_graph/test_export.py` — add horizon and validation tests
- Test: `tools/thesis_graph/test_export.py`

**Approach:**
- **Horizon fix:** Replace edge-filtering approach with cumulative path-lag computation. For each node, compute earliest arrival time across all paths from source nodes. A node fires at horizon T only if its shortest cumulative path lag ≤ T. Two 7-day edges in series = 14 days cumulative, not 7.
- **Validation hardening:** `validate_config` returns structured errors (list of `{field, message, severity}`), never raises. Add type checking for: threshold numeric types (reject `"0.7"` strings), gatedBy/constrainedBy reference validity, scenario probability range (0-1) and type, lag format validity, feed schema by provider, duplicate instrument IDs, marketFields schema, phase status enum.
- **Test compatibility note:** Validation changes preserve the valid/invalid boundary for existing configs (return structured errors instead of raising, same verdicts). The horizon fix INTENTIONALLY changes behavior for multi-hop chains — any tests relying on the buggy per-edge filter behavior will need updating. New behavior is mathematically correct.

**Test scenarios:**
- Happy path: Two 7-day edges A→B→C — horizon at T+7 does NOT fire C
- Happy path: Two 7-day edges — horizon at T+14 fires C
- Happy path: Single 5-day edge — horizon at T+7 fires downstream node
- Happy path: Config with `strength: "0.7"` → validation error (not crash)
- Happy path: Config with invalid gatedBy reference → validation error
- Edge case: Parallel paths with different cumulative lags — shortest path determines earliest arrival
- Edge case: Diamond graph (A→B, A→C, B→D, C→D with different lags) — correct arrival time at D
- Error path: Scenario probability > 1.0 → structured validation error
- Error path: Duplicate instrument IDs → structured validation error

**Verification:**
- Horizon propagation is mathematically correct for all graph topologies
- `validate_config` never throws — returns structured errors
- All 83 existing engine tests still pass

---

## System-Wide Impact

- **Interaction graph:** The RuntimeCoordinator is the central mutation authority. All state-changing paths (scheduler tick, on-demand fetch, TV webhook, manual override, config reload) go through the Coordinator under per-thesis locks. Routes are read-mostly (bootstrap, list, query) with writes submitted via `coordinator.submit()`. WebSocket broadcasts happen after DB commit, never before.
- **Error propagation:** Fetch failures → logged, previous snapshot preserved, feed.health_changed event emitted. DB write failures → logged, broadcast skipped (no partial state). WebSocket broadcast failures → per-connection error handling (existing pattern). Outbox delivery failures → retry via outbox worker, desk truth unaffected.
- **State lifecycle:** Definitions loaded once at startup → held immutable. Runtime inputs (prices, overrides, closes) stored in SQLite. Snapshots committed atomically with events and outbox rows. Close observations deduplicated by PK. Overrides tracked with full lifecycle (active → expired/cleared).
- **API surface parity:** Existing unversioned `/api/` routes remain functional throughout migration. New `/api/v1/` routes are additive. CLI tools remain functional (engine packaging preserves CLI entry points).
- **Integration coverage:** Chat + thesis events on same WS connection. LLM streaming preserved. TV webhook → Coordinator submit → re-propagation → WS broadcast chain must be tested end-to-end. Outbox → Dialectic delivery tested against mock server.
- **Unchanged invariants:** JSON config file format (books/*.json), Dialectic API contract, TradingView webhook HMAC security (tv_webhook.py transferred unchanged), existing frontend component structure (evolved, not replaced).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Engine directory rename breaks existing cron jobs and scripts | `[project.scripts]` in pyproject.toml preserves CLI entry points. Cron commands work unchanged after `pip install -e .` |
| SQLite migration loses data from existing file-based state | Migration script is idempotent with verification. Old files archived (not deleted). Run migration in staging first. |
| Coordinator lock contention between scheduler and webhooks | Per-thesis locks (not global). Scheduler skips thesis if lock held. TV webhook submit awaits lock with timeout. |
| 150 web tests break during persistence migration | Incremental approach: wire Repository into routes one at a time, run tests after each route migration. In-memory SQLite for tests. |
| Frontend breaks on new WS envelope format | Backward compatibility: detect old-format messages and handle gracefully during transition. Frontend updated incrementally. |
| `propagate_at_horizon` fix changes existing test expectations | New behavior is mathematically correct. Add new test cases, update any tests that relied on the buggy behavior. |
| Close observation triple-counting during transition | SQLite table is canonical from day one. Remove direct `closesObserved` mutation in thesisgraph.py and TV webhook simultaneously in a single atomic commit. |
| Coordinator restart loses fetched provider values | fetch_runs table stores raw provider_values_json. Coordinator hydrates effective configs from latest fetch_run on startup. |
| TV webhook blocks on coordinator lock during long fetch cycle | submit() has 10s timeout. Returns 503 with Retry-After on timeout. TV webhooks are retryable. |
| Repository class grows to 40+ methods across 10+ domains | Acceptable for now. If it becomes unwieldy, split into domain-specific sub-repositories sharing the same connection factory. |
| Rollback needed after partial milestone deployment | web/state.py archived (not deleted) — rollback path preserved. Engine rename reversible via git. SQLite is additive — old files left in place until operator verifies. |

## Phased Delivery

### Milestone 0: Contracts and Packaging (Units 1-5)
**Exit gate:** Engine imports work without sys.path. Golden snapshot round-trips through Pydantic schemas. SQLite persistence replaces file-based state. All 505 tests pass. Existing data migrated.

### Milestone 1: Runtime Core (Units 6-9)
**Exit gate:** RuntimeCoordinator produces committed snapshots with revisions. Durable events persist. Two browser clients stay in sync across a forced state change via WebSocket bootstrap + delta. Bootstrap API returns deterministic first-render payload.

### Milestone 2: Read-Only Desk Upgrades (Units 10-12)
**Exit gate:** Manual override appears on both clients and expires correctly. Close observations counted from single canonical source. Outbox delivery survives Dialectic downtime.

### Milestone 3: Interactive Workflows (Units 13-14)
**Exit gate:** Scenario evaluation is read-only and revision-bound — does not contaminate live state. Health/readiness endpoints work for monitoring. Structured logs parseable by JSON tooling.

### Milestone 4: Engine Hardening (Unit 15)
**Exit gate:** Horizon propagation is mathematically correct for multi-hop chains. Config validation returns structured errors, never throws.

## Documentation / Operational Notes

- Update `CLAUDE.md`: document new `web/runtime/`, `web/persistence/`, `web/schemas/` modules; update file structure; update test commands
- Update `deploy/README.md`: add `pip install -e .` to install steps, document SQLite backup (WAL checkpoint + file copy), document migration script
- Update `docs/USER-MANUAL.md`: no user-facing changes (backend restructure only)
- Update `INTEGRATION.md`: document outbox-based delivery, snapshot revision numbers
- Cron job update: after engine rename, cron commands use same entry points but may need `pip install -e .` first

## Sources & References

- **Origin document:** [tradingdesk-web-ui-v2-spec.md](tradingdesk-web-ui-v2-spec.md)
- **Superseded plan:** [docs/plans/2026-03-31-002-feat-trading-desk-web-ui-plan.md](docs/plans/2026-03-31-002-feat-trading-desk-web-ui-plan.md)
- **Original requirements:** [docs/brainstorms/2026-03-31-trading-desk-web-ui-requirements.md](docs/brainstorms/2026-03-31-trading-desk-web-ui-requirements.md)
- Engine core: `tools/thesis_graph/thesisgraph.py` — propagation, export, fetch
- Current web layer: `web/main.py`, `web/state.py`, `web/ws.py`, `web/adapters/`, `web/routes/`
- Current tests: `web/test_web.py` (50), `web/test_tradingview.py` (100)
- XSS solution: `docs/solutions/security-issues/xss-in-generated-html-from-json-config-2026-03-31.md`
- Dialectic integration: `INTEGRATION.md`
