# CC-Sidecar: Unified Analysis & Implementation Blueprint

**Generated 2026-03-22 by 6 parallel Opus 4.6 agents**
**Agents: Architecture Review, Hooks/Statusline Validation, Integration Analysis, Implementation Plan, Security Audit, Performance Analysis**

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Upstream API Validation](#2-upstream-api-validation)
3. [Critical Findings & Resolutions](#3-critical-findings--resolutions)
4. [Security Audit](#4-security-audit)
5. [Performance Analysis](#5-performance-analysis)
6. [Architecture Review](#6-architecture-review)
7. [Integration Recommendation](#7-integration-recommendation)
8. [Amended Schema](#8-amended-schema)
9. [Reducer State Machine](#9-reducer-state-machine)
10. [Resource Extractor](#10-resource-extractor)
11. [Repo Skeleton](#11-repo-skeleton)
12. [Component Design](#12-component-design)
13. [TUI Design](#13-tui-design)
14. [Settings Installation](#14-settings-installation)
15. [Build Order](#15-build-order)
16. [Test Plan](#16-test-plan)
17. [Key Design Decisions](#17-key-design-decisions)

---

## 1. Executive Summary

The cc-sidecar specification is architecturally sound. The three-tier source hierarchy (observed / reconciled / inferred), the hooks+statusline substrate, and the "reducer is the product" philosophy are all validated. Every upstream API claim was confirmed — all 17 hook events exist, all payload schemas match, all statusline JSON fields are real.

Five critical gaps must be resolved before implementation:

1. **Emit CLI latency** — Python subprocess startup (41ms) adds 80ms per tool call. Go binary required (~3ms).
2. **`payload_hash UNIQUE` breaks spool replay** — Must hash upstream payload only, use `INSERT OR IGNORE`.
3. **Concurrent subagent event routing** — Agent identity must be scoped to `sub:<session_id>:<agent_id>`.
4. **plan.json via CLAUDE.md is unreliable** — Demote to Tier 3; primary plan source = TaskCompleted events.
5. **No daemon lifecycle management** — Define systemd/launchd units, socket discovery, auto-start.

Additionally, the security audit identified a **CRITICAL** finding: raw event payloads store unredacted secrets (API keys, tokens, credentials). A redaction pipeline is a Phase 0 blocker.

---

## 2. Upstream API Validation

### Hook Events

All 17 events claimed in the spec exist. The spec is missing 5 newer events:

| Missing Event | Added In | Sidecar Relevance |
|---------------|----------|-------------------|
| StopFailure | v2.1.78 | Maps to RETRYING state — should handle |
| TeammateIdle | v2.1.49 | Idle-agent visibility for multi-agent teams |
| WorktreeRemove | v2.1.50 | Worktree lifecycle tracking |
| Elicitation | v2.1.49 | User input prompts — low priority for v1 |
| ElicitationResult | v2.1.49 | User input responses — low priority for v1 |

### Hook Event Payloads — All CONFIRMED

| Claim | Status | Details |
|-------|--------|---------|
| SessionStart: source + model | CONFIRMED | `"source": "startup\|resume\|clear\|compact"`, `"model": "claude-sonnet-4-6"` |
| UserPromptSubmit: prompt text | CONFIRMED | `"prompt": "User's prompt text"` |
| PreToolUse/PostToolUse: tool activity | CONFIRMED | tool_name, tool_input, tool_use_id; PostToolUse adds tool_response |
| PostToolUseFailure: error info | CONFIRMED | error, is_interrupt fields |
| SubagentStart: lifecycle | CONFIRMED | agent_id, agent_type |
| SubagentStop: summary | CONFIRMED | agent_id, agent_type, agent_transcript_path, last_assistant_message |
| InstructionsLoaded: context provenance | CONFIRMED | file_path, memory_type, load_reason, globs, trigger_file_path |
| ConfigChange: settings/skills | CONFIRMED | source (user_settings\|project_settings\|local_settings\|policy_settings\|skills), file_path |

### Statusline JSON Fields — All CONFIRMED

| Spec Claim | Actual Field(s) |
|------------|-----------------|
| total_cost_usd | `cost.total_cost_usd` |
| lines added/removed | `cost.total_lines_added`, `cost.total_lines_removed` |
| worktree info | `worktree.name`, `.path`, `.branch`, `.original_cwd`, `.original_branch` |
| context-window usage | `context_window.used_percentage`, `.remaining_percentage`, `.context_window_size`, `.total_input_tokens`, `.total_output_tokens`, `.current_usage` |
| model | `model.id`, `model.display_name` |
| session info | `session_id`, `transcript_path` |
| workspace info | `workspace.current_dir`, `.project_dir`, `cwd` |

**Additional fields not in spec:** `version`, `output_style.name`, `vim.mode`, `agent.name`, `exceeds_200k_tokens`, `cost.total_duration_ms`, `cost.total_api_duration_ms`, `rate_limits.five_hour.*`, `rate_limits.seven_day.*`

### Hook Behavior — All CONFIRMED

| Claim | Status |
|-------|--------|
| Hooks read JSON from stdin | CONFIRMED |
| Hooks return JSON to stdout for decisions | CONFIRMED — full output schema with continue, stopReason, suppressOutput, systemMessage, hookSpecificOutput |
| Settings hooks = subagent lifecycle only | CONFIRMED — SubagentStart/SubagentStop in main session |
| Frontmatter hooks = full internal observability | CONFIRMED — all events supported, Stop auto-converted to SubagentStop |
| SessionEnd time-constrained | CONFIRMED — 1.5s default, configurable via `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` |
| WorktreeCreate replaces default behavior | CONFIRMED — must print path to stdout, exit 0 = success |

### Settings Scopes — CONFIRMED (plus a 4th)

Three claimed scopes confirmed: user (`~/.claude/settings.json`), project (`.claude/settings.json`), local (`.claude/settings.local.json`). A **Managed** scope also exists (server-managed/plist/registry).

### Task → Agent Rename

Official docs state v2.1.63. Changelog evidence suggests the actual rename may have been earlier (~v2.1.49-50). `Task(...)` alias confirmed working.

### VS Code Extension

- Session list: CONFIRMED (dropdown with search and time-based browsing)
- Markdown plan view: CONFIRMED (opens as full markdown document with inline comments)
- Background subagent visibility issues: CONFIRMED (GitHub issue #26851)
- Stale indicators after compaction: PLAUSIBLE (related compaction bugs documented)

---

## 3. Critical Findings & Resolutions

### 3.1 Emit CLI Latency: Python Is Unacceptable

**Performance agent measured:**

| Approach | Latency |
|----------|---------|
| Bash stub (cat + echo to /dev/null) | 5ms |
| Go binary (estimated) | 1-3ms |
| Node.js (parse + hash + write) | 34ms |
| Python3 (parse + hash + write) | 41ms |
| Socket write alone | 0.019ms |

With Pre+Post hooks on every tool call, Python adds **80ms overhead per tool invocation**.

**Resolution:** Ship emit CLI as a **Go static binary** (~3ms). Keep daemon and TUI in Python. The socket protocol (JSON-over-Unix-socket) is language-agnostic. Alternative interim: bash+socat pipe pattern (5ms).

### 3.2 `payload_hash UNIQUE` Breaks Spool Replay

The UNIQUE constraint causes INSERT failures on replayed events unless:
- The hash covers only the upstream payload (excluding received_at, seq, emitter_version)
- Insertion uses `INSERT OR IGNORE`

If the hash covers the full envelope (including `received_at_ms`), every replay produces unique hashes and dedup is broken.

**Resolution:** Hash covers upstream payload only. Use `INSERT OR IGNORE`. Rename column to `dedup_hash`.

### 3.3 Concurrent Subagent Event Routing Is Ambiguous

When multiple Mode B subagents run concurrently, how does the reducer know which agent a `PreToolUse` event belongs to? Hook payloads carry `session_id` but agent identity comes from the `agent_id` field.

**Resolution:**
- Main-session hooks: `agent_id` absent → route to `main:<session_id>`
- Subagent frontmatter hooks: `agent_id` present → route to `sub:<session_id>:<agent_id>`
- Lifecycle-only subagents: moot (no tool events captured)
- Scope `agent_pk` to `sub:<session_id>:<agent_id>` to prevent cross-session collision

### 3.4 plan.json via CLAUDE.md Is Unreliable

No enforcement mechanism. Compaction destroys plan context. Race conditions between concurrent subagents writing. Schema drift from LLM.

**Resolution:** Demote plan.json to Tier 3 (inferred). Primary plan source = `TaskCompleted` events (Tier 1, observed). Plan.json is a supplementary signal. The sidecar must function fully without it.

### 3.5 No Daemon Lifecycle Management

The spec describes a "long-lived local daemon" with zero guidance on startup, shutdown, restart, PID files, socket discovery, or crash recovery.

**Resolution:**
- Socket/spool path: `$XDG_RUNTIME_DIR/cc-sidecar/` (Linux) or `~/Library/Caches/cc-sidecar/` (macOS)
- DB path: `$XDG_DATA_HOME/cc-sidecar/events.db`
- Provide systemd user unit (Linux) and launchd plist (macOS)
- Emit CLI auto-starts daemon if not running, or falls back to spool
- `cc-sidecar status` command for health checks

---

## 4. Security Audit

### Risk Matrix

| ID | Finding | Severity | Exploitability | Impact | Mitigation |
|----|---------|----------|----------------|--------|------------|
| S1 | Unredacted secrets in raw payloads | CRITICAL | Trivial (file read) | Credential theft | Redaction pipeline before any persistence — regex for `sk-`, `ghp_`, `Bearer`, env var patterns |
| S2 | No Unix socket auth | HIGH | Easy (local process) | Event injection | Socket permissions `0600`, `SO_PEERCRED` validation, `$XDG_RUNTIME_DIR` path |
| S3 | Unbounded spool accumulation | HIGH | Trivial | Secret accumulation, disk exhaustion | Per-PID spool files, 50MB cap, redact before spooling |
| S4 | No encryption at rest | HIGH | Easy (file copy) | Full data exfiltration | SQLCipher or `0600` file perms minimum |
| S5 | Unauthenticated WebSocket | HIGH | Easy (malicious webpage) | Remote credential theft | Bearer token from `0600` file + Origin header validation |
| S6 | XSS in UI rendering | HIGH | Moderate | Code execution in VS Code | `textContent` only, strip ANSI, strict CSP |
| S7 | Hook stdout/exit violations | HIGH | Easy (bug or compromise) | Claude Code pipeline interference | Redirect stdout to `/dev/null` on entry, `\|\| true` wrapper, 2s timeout |
| S8 | No retention/cleanup policy | MEDIUM | N/A (accumulation) | Growing attack surface | 7-day default for raw events, 30-day for sessions, auto-cleanup |
| S9 | Multi-user isolation failures | MEDIUM | Easy (shared machine) | Cross-user data leakage | `$XDG_RUNTIME_DIR` per-user paths, UID in all path derivation |
| S10 | Reducer event injection | MEDIUM | Requires socket access | UI state manipulation | Schema validation, event signing (v2) |
| S11 | SessionEnd time constraints | MEDIUM | Inherent | Data loss | Fire-and-forget spool write, no socket attempt |
| S12 | Supply chain risk | MEDIUM | Supply chain attack | Environment compromise | Minimal dependencies, checksum verification |
| S13 | Hash-based side channel | LOW | Requires DB access | Information leakage | Per-event salt in hash |
| S14 | plan.json injection | LOW | Requires workspace access | False UI state | JSON schema validation |
| S15 | Statusline data exposure | LOW | Local only | Cost/context leak | Document field sensitivity |

### Blast Radius Assessment

Without mitigations: exfiltrating the SQLite DB = every API key, every line of source code, every bash command, every prompt from every observed session. Equivalent to stealing the developer's entire working history plus credentials.

With mitigations (SQLCipher + redaction): limited to session metadata, tool names, file paths, timing data, cost figures — operationally useful but not catastrophic.

### Redaction Pipeline Specification

Must redact before any persistence (both daemon writes AND spool writes):

```
Patterns to redact:
  (sk-|pk-|pa-|ghp_|gho_|Bearer |Authorization:)[^\s'"]+  →  [REDACTED]
  export \w*(KEY|SECRET|TOKEN|PASSWORD)\w*=\S+              →  export $VAR=[REDACTED]
  High-entropy strings (>20 chars, high diversity) in known-sensitive fields
```

Field-level policy (configurable):
- `store_file_contents`: false by default (store paths only for Read/Write/Edit)
- `store_bash_output`: truncated to first 200 chars by default
- `store_prompts`: true (needed for "current user ask" display)

---

## 5. Performance Analysis

### Benchmarks (measured on this machine)

| Metric | Value | Headroom at 35 events/sec peak |
|--------|-------|-------------------------------|
| SQLite WAL individual writes | 22,977 events/sec | 656x |
| SQLite WAL batched writes (10/txn) | 67,175 events/sec | 1,919x |
| Full reducer transaction (4-table update) | 10,807 events/sec | 309x |
| Unix socket writes | 53,000 writes/sec | 1,514x |
| Concurrent SQLite reads under write load | 0.435ms avg, 0.627ms max | Comfortable for 50 clients |

### Event Throughput Estimates

| Scenario | Events/sec |
|----------|-----------|
| Single session, typical | 2-5 |
| Single session, rapid tool bursts | 6-8 |
| Single session + lifecycle events | ~10 |
| 5 concurrent background subagents | 30-35 |
| Burst peak (all subagents start) | ~50 for 1-2 seconds |

### Query Performance vs Table Size

| Events | DB Size | Recent-50 (no index) | Recent-50 (with index) | Hash lookup |
|--------|---------|---------------------|----------------------|-------------|
| 1,000 | 3.5MB | 2.03ms | — | 0.023ms |
| 10,000 | 38MB | 21.0ms | — | 0.032ms |
| 50,000 | 196MB | 92.7ms | — | 0.052ms |
| 100,000 | 392MB | 186.8ms | **0.80ms** | 0.053ms |

**The composite index on `(session_id, received_at_ms)` is mandatory.** Without it, the most common query degrades 234x at 100K rows.

### Stuck/Orphan Detection Thresholds

| Level | Threshold | Notes |
|-------|-----------|-------|
| Stuck warning | 60 seconds | No observed event from agent |
| Stuck alert | 120 seconds | High confidence |
| Orphaned | 300 seconds | Or survived compaction without lifecycle close |
| Bash extension | 180 seconds | Long-running commands are common |
| Timer interval | 10 seconds | Scanning 27 agents costs <0.1ms |

### WebSocket Fan-Out

- Full state push: 5-15KB per update, 0.04-0.1ms serialization
- Recommendation: full state push for v1, 200ms trailing-edge debounce
- Immediate bypass for alerts and agent state transitions (finished, stuck, orphaned)
- Memory per client: ~25-80KB. 50 clients = ~4MB total.

### Git Operations

- `git status --porcelain`: 11.6ms (this repo), up to 500ms on large monorepos
- `git diff HEAD -- <single_file>`: 2.7ms
- Recommendation: track dirty paths from Write/Edit events, 2-second debounce, diff only touched files
- Run in separate thread (`asyncio.to_thread`)

---

## 6. Architecture Review

### Source Hierarchy Assessment

The three-tier hierarchy (observed → reconciled → inferred) is sound. Identified gaps:

| Finding | Severity | Resolution |
|---------|----------|------------|
| Tier collapse post-compaction — agent state becomes inferred but isn't tagged as such | IMPORTANT | Downgrade state_source to "inferred" after PostCompact, apply shorter stuck timeout |
| Reconciled tier lacks timestamps | MINOR | Add `reconciled_at_ms` column to files table |
| Multi-tier badge composition undefined | MINOR | Badge individual fields at lowest-confidence tier |

### State Machine Assessment

| Finding | Severity | Resolution |
|---------|----------|------------|
| Missing `awaiting_perm` exit transition (no PermissionGranted event) | IMPORTANT | Document implicit transition via subsequent PreToolUse |
| No `blocked → running_tool` recovery transition | MINOR | Add explicit transition on PreToolUse |
| Concurrent subagent event routing ambiguous | CRITICAL | Route via agent_id presence (see §3.3) |
| `compacting` as state destroys prior state | MINOR | Model as `is_compacting` boolean flag |
| Stuck detector non-deterministic on replay | CRITICAL | Use received_at_ms timestamps, not wall-clock |

### Data Model Assessment

| Finding | Severity | Resolution |
|---------|----------|------------|
| `payload_hash UNIQUE` breaks replay | CRITICAL | See §3.2 |
| Unbounded TEXT for large payloads | IMPORTANT | Truncate >100KB, add payload_size column |
| Missing secondary indexes | IMPORTANT | See §8 |
| `sessions.source` conflates creation and lifecycle | MINOR | Keep original source, add compaction_count + last_compacted_at_ms |
| No foreign key constraints | MINOR | Enable or add post-replay consistency check |
| `agent_pk` cross-session collision | IMPORTANT | Scope to sub:<session_id>:<agent_id> |

### Reducer Idempotency Assessment

| Finding | Severity | Resolution |
|---------|----------|------------|
| SubagentStart upsert key ambiguity | IMPORTANT | Scope agent_pk, define explicit upsert semantics |
| PreToolUse creates duplicates on replay | IMPORTANT | Use INSERT OR IGNORE, never INSERT OR REPLACE |
| Stuck detector non-deterministic on replay | CRITICAL | Use event timestamps, accept live alerts as non-reproducible |
| Out-of-order compact events break state | MINOR | Process events in mono_seq order |

### Missing Components

| Finding | Severity | Resolution |
|---------|----------|------------|
| No daemon lifecycle management | CRITICAL | See §3.5 |
| No schema migration strategy | IMPORTANT | PRAGMA user_version + ordered migrations |
| Multi-user DB scope undefined | MINOR | User-scoped DB, project-scoped plan.json only |
| UI socket discovery undefined | IMPORTANT | Well-known path at $XDG_RUNTIME_DIR |
| No retention/GC policy | IMPORTANT | 7d raw, 30d sessions, 1h incremental vacuum |
| No health check endpoint | MINOR | `cc-sidecar status` command |
| Stop hook unhandled by reducer | MINOR | Add Stop → idle transition |
| No reducer error handling | MINOR | Dead-letter table for unparseable events |

### Subagent Visibility Assessment

| Finding | Severity | Resolution |
|---------|----------|------------|
| lifecycle_only insufficient for "what is Claude doing now" | IMPORTANT | Show "limited visibility" badge, infer file ownership from fs changes |
| Frontmatter hook maintenance burden | IMPORTANT | Provide cc-sidecar scaffold-subagent generator, add PermissionRequest to snippet |
| Nested subagents not modeled | IMPORTANT | Add parent_agent_pk to agents table |

---

## 7. Integration Recommendation

**Option B: Monorepo sibling** — unanimous recommendation.

```
DwoodAmo/
  dialectic/           # Existing, unchanged
  cc-sidecar/          # NEW: Go emit CLI + Python daemon + Python TUI
  packages/
    sidecar-dashboard/ # FUTURE: React/Vite/TS web UI (Phase 3+)
```

### Reusable Patterns from Dialectic

| Pattern | Source | Applicability |
|---------|--------|---------------|
| Event sourcing (append-only events table) | dialectic/schema.sql:7-16 | Identical pattern |
| Replay engine (state_at() materializer) | dialectic/replay/engine.py | Same reducer concept |
| WebSocket transport (ConnectionManager) | dialectic/transport/websocket.py | Same broadcast pattern |
| OrchestrationResult (decision traces) | dialectic/llm/orchestrator.py:36-46 | Observability recording pattern |
| InterjectionEngine (cascading heuristics with considered logging) | dialectic/llm/heuristics.py:56-186 | Stuck/orphan detection pattern |
| Zustand stores (typed state + persist) | dialectic/frontend/app/src/stores/appStore.ts | Future web dashboard |
| TextPatternExtractor (from Cairn) | /root/cairn/shared/patterns.py | Tier 3 transcript parsing |
| RetryPolicy / CircuitBreaker (from Cairn) | /root/cairn/shared/retry.py | Daemon resilience |

### Technology Decisions

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Emit CLI | **Go** | 3ms vs Python 41ms — hottest path in system |
| Daemon | **Python** (asyncio + aiosqlite) | Matches existing skills, adequate throughput |
| TUI | **Python** (Textual) | Same runtime as daemon, rich widget system |
| Database | **SQLite WAL** | Zero-setup, 22K writes/sec, concurrent readers |
| Web dashboard | **React/Vite/TS** (future) | Matches existing frontend stack |

---

## 8. Amended Schema

Incorporating corrections from all agents:

```sql
-- cc-sidecar SQLite schema
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA auto_vacuum = INCREMENTAL;

-- ============================================================
-- Raw event log: append-only source of truth
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at_ms INTEGER NOT NULL,
  mono_seq INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  agent_id TEXT,                       -- NULL for main agent
  source_kind TEXT NOT NULL,           -- hook | statusline | git | transcript
  event_name TEXT NOT NULL,
  payload_json TEXT NOT NULL,          -- REDACTED before storage
  payload_size INTEGER NOT NULL,       -- original pre-truncation size in bytes
  dedup_hash TEXT NOT NULL UNIQUE,     -- SHA-256 of upstream payload only (excl. envelope)
  emitter_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_re_session_time ON raw_events(session_id, received_at_ms);
CREATE INDEX IF NOT EXISTS idx_re_session_event ON raw_events(session_id, event_name);

-- ============================================================
-- Session metadata
-- ============================================================
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  source TEXT,                         -- startup | resume | clear (original creation only)
  model TEXT,
  cwd TEXT,
  project_dir TEXT,
  started_at_ms INTEGER,
  last_seen_at_ms INTEGER,
  ended_at_ms INTEGER,
  end_reason TEXT,
  context_used_pct REAL,
  context_remaining_pct REAL,
  total_cost_usd REAL DEFAULT 0.0,
  total_duration_ms INTEGER,
  total_lines_added INTEGER,
  total_lines_removed INTEGER,
  compaction_count INTEGER DEFAULT 0,
  last_compacted_at_ms INTEGER,
  worktree_path TEXT,
  worktree_branch TEXT
);

-- ============================================================
-- Agent state (derived by reducer)
-- ============================================================
CREATE TABLE IF NOT EXISTS agents (
  agent_pk TEXT PRIMARY KEY,           -- main:<session_id> or sub:<session_id>:<agent_id>
  session_id TEXT NOT NULL,
  agent_id TEXT,
  parent_agent_pk TEXT,                -- for nested subagents (nullable)
  agent_type TEXT NOT NULL,
  state TEXT NOT NULL,                 -- idle | running_tool | awaiting_perm | blocked | retrying | compacting | finished | orphaned
  state_source TEXT NOT NULL,          -- observed | inferred
  is_compacting INTEGER DEFAULT 0,    -- flag (preserves underlying state)
  started_at_ms INTEGER,
  last_event_at_ms INTEGER,
  stopped_at_ms INTEGER,
  last_tool_name TEXT,
  last_resource TEXT,
  last_summary TEXT,
  visibility_mode TEXT NOT NULL        -- full | lifecycle_only
);

CREATE INDEX IF NOT EXISTS idx_agents_session ON agents(session_id);

-- ============================================================
-- Tool calls (derived by reducer)
-- ============================================================
CREATE TABLE IF NOT EXISTS tool_calls (
  tool_use_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  agent_pk TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  status TEXT NOT NULL,                -- started | success | failure | denied
  started_at_ms INTEGER NOT NULL,
  ended_at_ms INTEGER,
  input_summary TEXT,                  -- REDACTED one-liner (not raw JSON)
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_tc_agent ON tool_calls(agent_pk, started_at_ms);
CREATE INDEX IF NOT EXISTS idx_tc_session ON tool_calls(session_id, started_at_ms);

-- ============================================================
-- Task/plan tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  description TEXT,
  owner_agent_pk TEXT,
  status TEXT NOT NULL,                -- planned | running | blocked | completed | unknown
  status_source TEXT NOT NULL,         -- observed | custom_plan | inferred
  created_at_ms INTEGER,
  completed_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);

-- ============================================================
-- File ownership and diff tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS files (
  session_id TEXT NOT NULL,
  path TEXT NOT NULL,
  last_writer_agent_pk TEXT,
  ownership_source TEXT NOT NULL,      -- observed | inferred | unknown
  added_lines INTEGER,
  removed_lines INTEGER,
  git_status TEXT,
  last_changed_at_ms INTEGER,
  reconciled_at_ms INTEGER,            -- when last git reconciliation ran
  PRIMARY KEY (session_id, path)
);

CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);

-- ============================================================
-- Alerts
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  severity TEXT NOT NULL,              -- info | warn | error
  kind TEXT NOT NULL,                  -- permission_denied | stuck | orphaned | compaction | config_change | skill_change
  message TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  resolved_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(session_id, resolved_at_ms);

-- ============================================================
-- Dead letter queue for unparseable events
-- ============================================================
CREATE TABLE IF NOT EXISTS dead_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at_ms INTEGER NOT NULL,
  raw_payload TEXT NOT NULL,
  parse_error TEXT NOT NULL
);
```

Notable changes from original spec:
- `dedup_hash` replaces `payload_hash` (clearer name, upstream-only scope)
- Scoped `agent_pk` format: `sub:<session_id>:<agent_id>`
- `parent_agent_pk` for nested subagents
- `is_compacting` boolean flag (not a state enum value)
- `payload_size` column for truncation tracking
- `input_summary` (redacted one-liner) replaces `input_json`/`output_json` in tool_calls
- `last_compacted_at_ms` + `compaction_count` on sessions
- `reconciled_at_ms` on files
- Mandatory composite indexes on all query-critical paths
- `dead_events` table for reducer error handling

---

## 9. Reducer State Machine

### Agent States

```
IDLE            — waiting for next action
RUNNING_TOOL    — tool execution in progress
AWAITING_PERM   — permission prompt displayed, waiting on human
BLOCKED         — permission denied or repeated failure
RETRYING        — StopFailure (rate limit, server error), will retry
COMPACTING      — context compaction in progress (modeled as flag is_compacting)
FINISHED        — agent completed (SubagentStop, Stop, SessionEnd)
ORPHANED        — no events for 5+ minutes, presumed lost
```

### State Diagram

```
                        SessionStart
                            |
                            v
    +-------------------> IDLE <-------------------+
    |                    /  |  \                    |
    |     PreToolUse    /   |   \   Stop/End        |
    |                  v    |    v                  |
    |          RUNNING_TOOL |  FINISHED             |
    |            |    |     |                       |
    |  PostToolUse    |     |                       |
    |  PostToolUseFail|     |                       |
    |            |    |     |                       |
    |            v    |     |                       |
    |          IDLE   |     |                       |
    |                 |     |                       |
    |    PermissionReq|     |                       |
    |                 v     |                       |
    |         AWAITING_PERM |                       |
    |            |    |     |                       |
    |   (allowed)|    |(denied)                     |
    |            v    v     |                       |
    |     RUNNING  BLOCKED  |                       |
    |      _TOOL     |      |                       |
    |                |      |                       |
    |     (retry)    |      |                       |
    |       |        |      |                       |
    |       v        |      |                       |
    |    RETRYING ----+------+                      |
    |       |                                       |
    |       +---------------------------------------+
    |
    |    (is_compacting flag set on PreCompact,
    |     cleared on PostCompact — underlying state preserved)
    |
    |    (timeout 5min, no events)
    |       |
    |       v
    |    ORPHANED
    +-------+  (can resurrect on any new event)
```

### Transition Table

```python
TRANSITIONS = {
    # From IDLE
    (IDLE, "PreToolUse"):           RUNNING_TOOL,
    (IDLE, "Stop"):                 FINISHED,
    (IDLE, "SessionEnd"):           FINISHED,
    (IDLE, "SubagentStart"):        IDLE,      # spawns child, parent stays idle

    # From RUNNING_TOOL
    (RUNNING_TOOL, "PostToolUse"):          IDLE,
    (RUNNING_TOOL, "PostToolUseFailure"):   IDLE,
    (RUNNING_TOOL, "PermissionRequest"):    AWAITING_PERM,
    (RUNNING_TOOL, "PreToolUse"):           RUNNING_TOOL,  # new tool replaces
    (RUNNING_TOOL, "Stop"):                 FINISHED,

    # From AWAITING_PERM
    (AWAITING_PERM, "PreToolUse"):          RUNNING_TOOL,  # permission granted
    (AWAITING_PERM, "PostToolUse"):         IDLE,          # granted inline
    (AWAITING_PERM, "PostToolUseFailure"):  BLOCKED,       # denied

    # From BLOCKED
    (BLOCKED, "PreToolUse"):    RUNNING_TOOL,  # pivoted to different approach
    (BLOCKED, "Stop"):          FINISHED,

    # From RETRYING (after StopFailure)
    (RETRYING, "PreToolUse"):   RUNNING_TOOL,
    (RETRYING, "Stop"):         FINISHED,
    (RETRYING, "StopFailure"):  RETRYING,

    # From FINISHED (can resume)
    (FINISHED, "SessionStart"):     IDLE,      # session resume
    (FINISHED, "PreToolUse"):       RUNNING_TOOL,

    # From ORPHANED (can resurrect)
    (ORPHANED, "PreToolUse"):       RUNNING_TOOL,
    (ORPHANED, "PostToolUse"):      IDLE,
    (ORPHANED, "SessionStart"):     IDLE,
}

# Compaction handled separately via is_compacting flag:
# PreCompact  → set is_compacting = 1 (preserve underlying state)
# PostCompact → set is_compacting = 0, downgrade state_source to "inferred"
# SessionStart(source=compact) → set is_compacting = 0, state → IDLE
```

### Edge Cases

| Scenario | Handling |
|----------|----------|
| Missing SubagentStop | Orphan timer fires at 300s, transitions to ORPHANED, generates alert |
| Compaction mid-tool | is_compacting flag set, underlying state preserved. PostCompact clears flag, downgrades state_source to "inferred" |
| Duplicate events | `INSERT OR IGNORE` on dedup_hash. Reducer never sees duplicates. |
| Out-of-order spool replay | Sort spool events by mono_seq before feeding to reducer |
| StopFailure (rate limit) | Transitions to RETRYING. Remains until new PreToolUse or orphan timeout. |
| Unknown event type | Stored in raw_events, not fed to reducer, no state change |
| Malformed event | Stored in dead_events table, alert generated |
| PermissionRequest then long wait | Stays in AWAITING_PERM. Stuck detector uses longer threshold for human-wait states. |

---

## 10. Resource Extractor

Turn raw tool payloads into one-line truth:

| Tool | Resource Format | Example |
|------|----------------|---------|
| Read | `path[:line-range]` | `src/models.py:10-50` |
| Write | `path` | `src/new_file.py` |
| Edit | `path` | `src/models.py` |
| Bash | truncated command (60 chars) | `npm test --coverage...` |
| Glob | `pattern in path` | `**/*.py in src/` |
| Grep | `/pattern/ in glob` | `/TODO/ in *.ts` |
| Agent/Task | `type: 'prompt snippet...'` | `Explore: 'Find all test...'` |
| WebFetch | `fetch: hostname` | `fetch: api.example.com` |
| WebSearch | `search: 'query'` | `search: 'SQLite WAL mode'` |
| mcp__server__tool | `mcp:server/tool(key_arg)` | `mcp:github/search_code(query)` |
| Unknown | tool name as-is | `CustomTool` |

Task tool name is normalized to Agent before extraction.

---

## 11. Repo Skeleton

```
cc-sidecar/
├── BLUEPRINT.md                       # This document
├── CLAUDE.md                          # Claude Code instructions for this project
├── pyproject.toml                     # Python package (daemon + TUI)
├── schema.sql                         # SQLite DDL
│
├── cmd/                               # Go emit CLI
│   └── cc-sidecar-emit/
│       ├── main.go                    # Entry point
│       ├── envelope.go                # Wrap with metadata
│       ├── socket.go                  # Unix socket writer
│       ├── spool.go                   # Spool file fallback
│       ├── redact.go                  # Secret redaction
│       └── go.mod
│
├── cc_sidecar/                        # Python package
│   ├── __init__.py
│   ├── models.py                      # Pydantic models, enums, event schemas
│   ├── constants.py                   # Paths, socket name, version, timeouts
│   │
│   ├── daemon/
│   │   ├── __init__.py
│   │   ├── server.py                  # Main loop: socket + WS server
│   │   ├── ingest.py                  # Normalize → redact → dedup → insert → reduce → broadcast
│   │   ├── spool.py                   # Spool reader/replayer
│   │   ├── timers.py                  # Stuck/orphan detection
│   │   └── redact.py                  # Python redaction (mirrors Go version)
│   │
│   ├── reducer/
│   │   ├── __init__.py
│   │   ├── machine.py                 # AgentStateMachine, transitions
│   │   ├── states.py                  # AgentState enum, transition table
│   │   └── extractor.py              # Resource extraction from tool payloads
│   │
│   ├── store/
│   │   ├── __init__.py
│   │   ├── database.py                # Connection, WAL setup, migrations
│   │   └── queries.py                 # Named query functions
│   │
│   ├── tui/
│   │   ├── __init__.py
│   │   ├── app.py                     # Textual App, screen layout
│   │   ├── styles.css                 # Textual CSS
│   │   └── widgets/
│   │       ├── __init__.py
│   │       ├── session_bar.py         # Model, cwd, context %, cost, compactions
│   │       ├── agent_list.py          # Agent table with state badges
│   │       ├── alert_feed.py          # Scrolling alert log
│   │       └── event_timeline.py      # Filterable event stream
│   │
│   └── install/
│       ├── __init__.py
│       └── cli.py                     # Generate settings.json entries
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # Factories, fixtures, temp DB
│   ├── test_emit.py
│   ├── test_ingest.py
│   ├── test_reducer.py
│   ├── test_extractor.py
│   ├── test_spool.py
│   ├── test_store.py
│   ├── test_redact.py
│   └── test_integration.py
│
└── scripts/
    ├── statusline.sh                  # Statusline script
    └── generate_fixtures.py           # Generate test event fixtures
```

---

## 12. Component Design

### cc-sidecar-emit (Go binary)

**Purpose:** Fire-and-forget event emitter called by hooks.

**Algorithm:**
1. Read all of stdin (JSON from Claude Code hook)
2. Parse JSON. If parse fails, wrap raw text in `{"_raw": "..."}`
3. Apply redaction pipeline (regex scrub of secrets)
4. Wrap with envelope: `received_at`, `mono_seq`, `emitter_version`, `hook_event`, `is_subagent`
5. Normalize tool name (Task → Agent)
6. Compute `dedup_hash` over upstream payload only (SHA-256)
7. Try Unix socket write at `$XDG_RUNTIME_DIR/cc-sidecar/daemon.sock` (200ms timeout)
8. On socket failure: append to per-PID spool file `$XDG_RUNTIME_DIR/cc-sidecar/spool/<session_id>-<pid>.jsonl`
9. Write nothing to stdout. Exit 0.

**Hard rules:**
- Stdout redirected to /dev/null on entry
- Exit 0 always, even on total failure
- Never return hook decision fields
- 2-second internal timeout maximum
- Spool files capped at 50MB per file

### cc-sidecard (Python daemon)

**Startup sequence:**
1. Create runtime directories (`$XDG_RUNTIME_DIR/cc-sidecar/`, `$XDG_DATA_HOME/cc-sidecar/`)
2. Open/create SQLite database with WAL mode
3. Apply schema migrations (idempotent)
4. Replay pending spool files (sorted by mono_seq, batched transactions)
5. Bind Unix socket (permissions 0600)
6. Start WebSocket server on localhost (random port, advertised via token file)
7. Start orphan detection timer (10-second interval)
8. Write PID file
9. Enter asyncio event loop

**Ingestion pipeline:**
Normalize → Redact → Dedup → Insert → Reduce → Broadcast

**Stuck/orphan detection:**
- Hybrid: check on each event receipt AND on 10-second timer
- 60s warn / 120s alert / 300s orphan
- 180s extension for Bash tool (long-running commands)
- No stuck marking for awaiting_perm (expected human wait)

**WebSocket server:**
- Bearer token auth from 0600 file
- Origin header validation
- Full state push on connect
- 200ms trailing-edge debounce, immediate for alerts
- localhost binding only

### cc-sidecar-tui (Python, Textual)

**Layout:**
```
+------------------------------------------------------------------+
| SESSION BAR                                                       |
| [Opus 4.6] ~/project  ctx: ████░░░░░░ 42%  $1.23  C:2  agents:3 |
+------------------------------------------------------------------+
| AGENT LIST                                                        |
| ID        State         Elapsed  Tool   Resource          Source  |
| main      running_tool  0:03     Bash   npm test          [obs]   |
| sub:a1    awaiting_perm 0:12     Write  src/new.py        [obs]   |
| sub:b2    finished      1:45     --     --                [obs]   |
| sub:c3    running       2:30     --     --                [life]  |
+------------------------------------------------------------------+
| ALERTS                                                            |
| [14:23:01] ORPHAN sub:c3 no events for 5m                        |
| [14:22:15] COMPACTION session abc (3rd)                           |
+------------------------------------------------------------------+
| TIMELINE (filterable by event/tool/agent)                         |
| 14:23:05 PreToolUse  Bash   "npm test"           main    [obs]   |
| 14:23:04 PostToolUse Read   src/models.py:1-50   main    [obs]   |
| 14:23:02 SubagentStart       Explore              sub:a1  [obs]   |
+------------------------------------------------------------------+
```

State colors: idle=dim white, running_tool=green, awaiting_perm=yellow, blocked=red, retrying=orange, compacting=cyan, finished=grey, orphaned=red+blink

Source badges: `[obs]` = observed, `[rec]` = reconciled, `[inf]` = inferred, `[life]` = lifecycle_only

---

## 13. TUI Design

See §12 for layout. Key interaction rules:

- Single click on agent row → filters timeline to that agent
- Single click on timeline event → shows event detail in tooltip/panel
- `f` key → toggle timeline filter bar
- `p` key → pause/resume live scrolling
- `q` key → quit
- `r` key → force refresh from daemon
- Context % progress bar: green <70%, yellow 70-89%, red ≥90%
- Maximum 500 timeline rows in memory, older events available via scroll

---

## 14. Settings Installation

The `cc-sidecar-install` command generates Claude Code settings.json entries. All hooks use the Go binary, `async: true`, 5-second timeout:

```json
{
  "hooks": {
    "SessionStart":       [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "UserPromptSubmit":   [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "PreToolUse":         [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "PermissionRequest":  [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "PostToolUse":        [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "PostToolUseFailure": [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "Notification":       [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "SubagentStart":      [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "SubagentStop":       [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "TaskCompleted":      [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "ConfigChange":       [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "InstructionsLoaded": [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "PreCompact":         [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "PostCompact":        [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "Stop":               [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "StopFailure":        [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}],
    "SessionEnd":         [{"hooks": [{"type": "command", "command": "cc-sidecar-emit", "async": true, "timeout": 5}]}]
  }
}
```

Statusline via shared state file (daemon writes `~/.cc-sidecar/statusline.json`, script reads):
```json
{
  "statusLine": {
    "type": "command",
    "command": "cat ~/.cc-sidecar/statusline.json 2>/dev/null"
  }
}
```

### Custom subagent frontmatter template

For Mode B (full telemetry) custom subagents:

```yaml
---
name: my-custom-agent
description: Description here
hooks:
  PreToolUse:
    - matcher: ".*"
      hooks:
        - type: command
          command: "cc-sidecar-emit --subagent"
  PostToolUse:
    - matcher: ".*"
      hooks:
        - type: command
          command: "cc-sidecar-emit --subagent"
  PostToolUseFailure:
    - matcher: ".*"
      hooks:
        - type: command
          command: "cc-sidecar-emit --subagent"
  PermissionRequest:
    - hooks:
        - type: command
          command: "cc-sidecar-emit --subagent"
  Stop:
    - hooks:
        - type: command
          command: "cc-sidecar-emit --subagent"
---
```

---

## 15. Build Order

### Phase 0: Security Foundation (before any code)
1. Design redaction pipeline (regex patterns, field-level policies)
2. Define file permission and path conventions ($XDG_RUNTIME_DIR, 0600)
3. Design emit CLI stdout/exit safety wrapper

### Phase 1a: Core Foundation (Days 1-3)
4. Go emit CLI (read stdin, wrap envelope, redact, socket write, spool fallback)
5. SQLite schema with corrected indexes, dedup_hash, scoped agent_pk
6. Python store layer (database.py, queries.py)
7. Reducer state machine (states.py, machine.py, extractor.py)

### Phase 1b: Daemon (Days 3-5)
8. Unix socket listener with SO_PEERCRED + 0600 permissions
9. Ingest pipeline: normalize → redact → dedup → insert → reduce → broadcast
10. Spool replay (sorted by mono_seq, batched transactions)
11. Stuck/orphan detection (60s/120s/300s, 10s timer)
12. WebSocket server with bearer token auth + Origin validation + 200ms debounce

### Phase 1c: TUI + Installation (Days 5-8)
13. Textual TUI (session bar, agent list, alert feed, event timeline)
14. Settings installer (cc-sidecar-install generates hook JSON)
15. Statusline via shared state file

### Phase 1d: Tests + Polish (Days 8-10)
16. All 9 spec test cases + unit tests
17. Integration test: emit → socket → daemon → DB → WS → TUI verify
18. Manual testing with live Claude Code session

### Phase 2 (future)
- File diff ownership, Bash/test parser, alert engine

### Phase 3 (future)
- VS Code webview extension, deep links, multi-session filter

### Phase 4 (future)
- plan.json contract, custom subagent hook bundle, context provenance pane

### Phase 5 (future)
- Transcript indexing, historical analytics, plugin packaging

---

## 16. Test Plan

### Mandatory Tests from Spec

1. **Out-of-order event replay** — Events arriving out of mono_seq order produce correct final state
2. **Duplicate event replay** — Duplicate mono_seq events silently dropped via dedup_hash
3. **Missing SubagentStop** — Agent transitions to ORPHANED after 300s timeout
4. **Compaction mid-run** — is_compacting flag set/cleared, underlying state preserved
5. **Session resume after compaction** — SessionStart(source=compact) resumes correctly
6. **Background permission denial** — PostToolUseFailure after PermissionRequest transitions to BLOCKED
7. **Multiple concurrent agents** — Independent state machines per agent_pk
8. **Null/absent statusline fields** — Graceful defaults, no crashes
9. **Task/Agent alias handling** — Both tool names produce identical normalized events

### Additional Unit Tests

**Emit CLI:** envelope wrapping, socket failure → spool, never writes stdout, always exits 0, handles invalid JSON, --subagent flag, agent_id detection, redaction applied

**Reducer:** all state transitions, unknown events logged, edge transitions (FINISHED → IDLE on resume), is_compacting flag preservation, state_source downgrade post-compaction

**Extractor:** all tool types (Read, Write, Edit, Bash, Glob, Grep, Agent, WebFetch, WebSearch, mcp__*), unknown tools, truncation, path shortening

**Store:** WAL mode enabled, schema idempotent, INSERT OR IGNORE dedup, concurrent reads under write load

**Redaction:** API key patterns, env var patterns, bearer tokens, high-entropy strings, field-level policy enforcement

**Integration:** full pipeline emit → socket → daemon → DB → WS → verify state

---

## 17. Key Design Decisions

| Question | Resolution | Deciding Agent |
|----------|-----------|----------------|
| Emit CLI language | **Go** (3ms vs Python 41ms) | Performance |
| Daemon language | **Python** (asyncio + aiosqlite) | Integration + Implementation |
| TUI framework | **Textual** (Python, rich widgets) | Implementation |
| Database | **SQLite WAL** (22K writes/sec, zero setup) | Performance |
| Dedup strategy | `INSERT OR IGNORE` on `dedup_hash` (upstream payload only) | Architecture |
| agent_pk format | `main:<session_id>` or `sub:<session_id>:<agent_id>` | Architecture |
| Compacting model | Boolean flag `is_compacting`, not state enum | Architecture |
| plan.json role | Tier 3 supplement, not primary source | Architecture |
| Encryption at rest | Required (SQLCipher or 0600 minimum) | Security |
| Redaction | Phase 0 blocker, before any persistence | Security |
| WebSocket auth | Bearer token from 0600 file + Origin validation | Security |
| Statusline transport | Shared state file (daemon writes, script `cat`s) | Performance |
| Stuck thresholds | 60s warn / 120s alert / 300s orphan | Performance |
| WebSocket debounce | 200ms trailing-edge, immediate for alerts | Performance |
| Repo location | Monorepo sibling at `DwoodAmo/cc-sidecar/` | Integration |
| Payload storage | Redacted, truncate >100KB, store payload_size | Security + Performance |
| Spool strategy | Per-PID files, 50MB cap, redact before spooling | Security |
| Socket path | `$XDG_RUNTIME_DIR/cc-sidecar/daemon.sock` | Security |
| DB path | `$XDG_DATA_HOME/cc-sidecar/events.db` | Security |
| Retention | 7-day raw events, 30-day sessions, hourly incremental vacuum | Architecture + Security |
