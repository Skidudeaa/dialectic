# CLAUDE.md — cc-sidecar

## Project Overview

**cc-sidecar** is a passive, event-sourced observability sidecar for Claude Code. It answers four questions truthfully at all times: what Claude is doing now, what changed, what is blocked, and what context is currently in play.

## Architecture

Three feeds: structured hook events, statusline heartbeats, and repo/worktree reconciliation. No ANSI scraping. No fake progress percentages.

- **cc-sidecar-emit** (Go): Fire-and-forget CLI called by hooks. Reads stdin JSON, redacts secrets, wraps with envelope, writes to Unix socket or spool file. Exits 0 always. Never writes to stdout.
- **cc-sidecard** (Python): Long-lived local daemon. Unix socket listener → ingest pipeline → SQLite (WAL) → reducer state machine → WebSocket broadcast.
- **cc-sidecar-tui** (Python/Textual): Terminal dashboard. Connects to daemon WebSocket for live state.

## Commands

```bash
# Build the Go emit binary
cd cc-sidecar/cmd/cc-sidecar-emit && go build -o cc-sidecar-emit .

# Run the daemon
cd cc-sidecar && python -m cc_sidecar.daemon.server

# Run the TUI
cd cc-sidecar && python -m cc_sidecar.tui.app

# Install hooks into Claude Code settings
cd cc-sidecar && python -m cc_sidecar.install.cli

# Run tests
cd cc-sidecar && python -m pytest tests/ -q
```

## Source-of-Truth Hierarchy

- **Tier 1 (observed):** hook events, statusline snapshots
- **Tier 2 (reconciled):** git status/diff, fs watchers
- **Tier 3 (inferred):** transcript parsing, ownership heuristics, stuck/orphan detection

Every UI element must show its source tier as a badge: `[obs]`, `[rec]`, or `[inf]`.

## Key Design Rules

1. The reducer is the product. The UI is paint over reducer truth.
2. Never label a state "success" unless you have explicit evidence.
3. SubagentStop means "finished responding," not "succeeded."
4. Built-in subagents are lifecycle-only (no per-tool visibility). Design around that.
5. plan.json is Tier 3 — the sidecar must function fully without it.
6. Redact secrets before any persistence (both daemon writes AND spool writes).
7. The emit CLI must never block or interfere with Claude Code. Exit 0 always.
8. Task and Agent tool names are aliases — normalize to "Agent."

## Database

SQLite with WAL mode at `$XDG_DATA_HOME/cc-sidecar/events.db`. Schema in `schema.sql`.

## Security Posture

- Localhost only, no cloud telemetry
- Socket permissions 0600, $XDG_RUNTIME_DIR paths
- Redaction pipeline for API keys, tokens, env vars before storage
- WebSocket bearer token auth + Origin validation
- Payload truncation >100KB
