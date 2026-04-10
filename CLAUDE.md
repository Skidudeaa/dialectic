# CLAUDE.md

## What This Is

Trading Desk — a causal reasoning engine for macro trading. Models the world as a directed graph of transmission chains (oil shock → diesel → freight → employment → demand destruction), propagates data and probabilities through the graph, and generates interactive HTML dashboards for collaborative decision-making.

## Quick Start

```bash
# === Thesis Graph Engine ===

# Generate interactive causal DAG dashboard
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json -o output/iran-hormuz-graph.html

# Second thesis (Trump tariffs)
python3 tools/thesis-graph/thesisgraph.py books/trump-tariffs-graph.json -o output/trump-tariffs-graph.html

# With live prices (Yahoo Finance + Polymarket probabilities)
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json -o output/iran-hormuz-graph.html --fetch

# Export evaluated graph state as JSON (for Dialectic integration)
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --export-state snapshots/latest.json

# Fetch + export + generate HTML in one command
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state snapshots/latest.json -o output/iran-hormuz-graph.html

# Pipe snapshot to stdout for bridge scripts
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --export-state - 2>/dev/null

# Dry run (validate + propagate, no output)
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --dry-run

# === Pipeline Runner ===

# Run all active thesis books in one command (fetch → export → diff → push)
# Room IDs must be set in meta.dialecticRoomId of each book JSON.
# DIALECTIC_ROOM_TOKEN must be in the environment for push steps.
# NOTE: push-to-dialectic.py defaults to localhost:8002 (mock server).
#       For production, invoke push-to-dialectic.py directly with --dialectic-url.
python3 tools/bridge/run-all.py

# Preview what would run — no network calls, no file writes
python3 tools/bridge/run-all.py --dry-run

# Use a custom books directory (useful for testing)
python3 tools/bridge/run-all.py --books path/to/custom/books/

# Cron (Mon/Wed/Fri at 08:00) — ensure DIALECTIC_ROOM_TOKEN is in the environment:
#   0 8 * * 1,3,5 cd /path/to/tradingDesk && \
#       DIALECTIC_ROOM_TOKEN=<token> python3 tools/bridge/run-all.py \
#       >> logs/run-all.log 2>&1
# Exit codes: 0 = all OK, 1 = one or more books failed, 2 = config error

# === Polymarket Fetcher ===

# Standalone probability check
python3 tools/data-fetch/polymarket.py us-iran-april-30 --json

# === Snapshot Diff ===

# Compare two snapshots, output structured delta
python3 tools/bridge/diff-snapshots.py snapshots/old.json snapshots/new.json

# Chain: only push if something changed
python3 tools/bridge/diff-snapshots.py snapshots/old.json snapshots/new.json && \
  python3 tools/bridge/push-to-dialectic.py --snapshot snapshots/new.json --room-id <uuid>

# === E2E Validation ===

# Start mock Dialectic server for testing
python3 tools/validation/mock_dialectic.py --port 8002

# === Commodity Book (legacy flat trigger model) ===

# Generate commodity book dashboard
python3 tools/commodity-book/bookgen.py books/iran-hormuz-2026.json -o output/iran-hormuz.html

# === Tests ===

# Full suite (223 tests)
python3 -m pytest tools/thesis-graph/test_export.py tools/bridge/test_diff.py tools/bridge/test_push.py tools/bridge/test_run_all.py tools/data-fetch/test_polymarket.py tools/validation/e2e_test.py -q

# By component
python3 -m pytest tools/thesis-graph/test_export.py -q       # 76 — export/propagation
python3 -m pytest tools/bridge/test_diff.py -q               # 21 — snapshot diff
python3 -m pytest tools/bridge/test_push.py -q               # 26 — bridge script
python3 -m pytest tools/bridge/test_run_all.py -q            # 20 — multi-book runner
python3 -m pytest tools/data-fetch/test_polymarket.py -q     # 41 — Polymarket fetcher
python3 -m pytest tools/validation/e2e_test.py -q            # 39 — E2E pipeline

# === Web UI ===

# Install web layer dependencies (Python + Node.js)
pip install -r requirements.txt
cd frontend && npm install && cd ..

# Start backend (FastAPI + uvicorn)
uvicorn web.main:app --reload --port 8000

# Start frontend dev server (Vite)
cd frontend && npm run dev

# Or use Makefile shortcuts
make install    # install all deps
make dev        # start backend
make frontend   # start frontend

# Docker (production)
docker compose up --build

# Required env vars (see .env.example):
#   JWT_SECRET         — MUST override for production
#   DEV_USER_PASSWORD  — password for amo/dan accounts
#   OPENROUTER_API_KEY — enables @claude/@gpt/@compare in chat
```

## Architecture

### Thesis Graph Engine (`tools/thesis-graph/thesisgraph.py`)

The core tool. Reads a thesis graph JSON config → evaluates all nodes via topological propagation → generates a self-contained interactive HTML dashboard (~750 KB with inlined Cytoscape.js).

The graph config defines:
- **Nodes** — observable economic states (event, price, indicator, deadline, gate, constraint, conditional, reversal)
- **Edges** — causal transmission channels with mechanisms, lags, and amplification factors
- **Instruments** — portfolio positions mapped to graph nodes
- **Scenarios** — what-if overrides with probability-weighted portfolio impact
- **Cascade phases** — 5-phase crisis tracker (shock → transmission → amplification → policy response → resolution)

The generated HTML has 5 tabs:
1. **Graph** — interactive Cytoscape.js DAG, nodes colored by state (fired/approaching/stable/gated)
2. **Cascade** — "WE ARE HERE" phase tracker with signpost checklists and countdown timers
3. **Scenarios** — toggle between scenarios, see portfolio impact waterfall
4. **Portfolio** — instruments grouped by graph node with range bars and position tracking
5. **Journal** — node-linked decision audit trail

### Propagation Engine

Kahn's topological sort → evaluate each node against thresholds → propagate upstream signals downstream. Runs in Python at generation time, mirrored in browser JS for real-time recalculation on market data input changes.

Signal confluence: when multiple independent causal paths converge on the same node, the system scores convergence strength (fan-in analysis). High confluence = high confidence.

### Live Price Fetch (`--fetch`)

Two data sources, both called when `--fetch` is used:
- **Yahoo Finance** — ETFs, futures, FX, indices via v7 spark API (allorigins.win CORS proxy, no API key)
- **Polymarket** — prediction market probabilities via Gamma API (`https://gamma-api.polymarket.com`), mapped onto graph nodes with `"source": "polymarket"` feeds

### Polymarket Fetcher (`tools/data-fetch/polymarket.py`)

Standalone module and CLI. Three-pass slug matching (exact → substring → keyword). Parses `outcomePrices` for "Yes" probability. Imported dynamically by thesisgraph.py when `--fetch` runs.

### Snapshot Export (`--export-state`)

Exports evaluated graph state as structured JSON for Dialectic integration. Shape:

```json
{
  "v": 1,
  "timestamp": "2026-03-30T14:00:00Z",
  "nodeStates": {"hormuz": "fired", "brent": "approaching"},
  "confluenceScores": {"em-stress": 1.30},
  "cascadePhase": {"number": 2, "key": "transmission", "status": "STARTING"},
  "countdowns": [{"nodeId": "planting-miss", "daysRemaining": 17}],
  "marketSnapshot": {"brent": 112.57, "diesel": 5.38},
  "scenarioImpacts": {"closed-may": {"probability": 0.45, "netImpact": 12.8}},
  "portfolioSummary": {"monthlyBudget": 8000, "topPositions": [...]}
}
```

### Delta Detection (`tools/bridge/diff-snapshots.py`)

Compares two snapshot JSONs. Outputs: state transitions, confluence shifts, countdown changes, market price moves, added/removed nodes. Exit 0 = changes found, 1 = no changes, 2 = error.

### Multi-Book Runner (`tools/bridge/run-all.py`)

Orchestrates the full pipeline for all active thesis-graph books in one command:
fetch → export snapshot → diff against previous → conditional push to Dialectic.

- Discovers `books/*.json` sorted alphabetically, skips non-thesis-graph configs
- Per-book snapshot rotation: `snapshots/{book-id}-latest.json` / `{book-id}-prev.json`
- Reads `meta.dialecticRoomId` + `meta.dialecticRoomToken` from each book JSON
- Continue-on-failure: one book's error doesn't abort others; exits non-zero if any failed
- `--dry-run` prints planned run without executing

### Dialectic Integration (`tools/bridge/push-to-dialectic.py`)

POSTs snapshots to Dialectic trading rooms. Token from `DIALECTIC_ROOM_TOKEN` env var or `meta.dialecticRoomToken` in book JSON (per-book token takes precedence). See `INTEGRATION.md` for the full spec.

**Live rooms (as of 2026-04-01):**

| Book | Dialectic Room | Status |
|---|---|---|
| `iran-hormuz-graph.json` | `56ba2f1e-5c70-4290-a77d-52404f0095da` | Live — thesis state current |
| `trump-tariffs-graph.json` | `8adcabb7-817a-4802-87c6-3bfd42e6a9eb` | Live — thesis state current |

Dialectic server: `/root/DwoodAmo/dialectic` — run with `PORT=8002 python dialectic/run.py`

### E2E Validation (`tools/validation/`)

- `mock_dialectic.py` — mock Dialectic HTTP server with schema validation, error injection, standalone + importable
- `e2e_test.py` — full pipeline tests: snapshot → diff → push → verify round trip

### Commodity Book Generator (`tools/commodity-book/bookgen.py`)

Legacy flat trigger model — 9 instruments, 9 triggers, 4 overlays. Superseded by the thesis graph engine for new work.

### Web UI Backend (`web/`)

FastAPI application wrapping the CLI tools as REST endpoints + WebSocket for real-time chat. Two-analyst workspace with JWT auth (hardcoded dev users: amo, dan).

Key modules:
- `web/main.py` — App entry, CORS, route registration
- `web/auth.py` — JWT auth with scrypt password hashing, startup warning on default secret
- `web/state.py` — File-based persistence (JSON/JSONL with fcntl locks, atomic writes via temp+rename)
- `web/ws.py` — WebSocket connection manager with concurrent broadcast, 5-second send timeout
- `web/adapters/` — Thin wrappers around CLI tools (thesis, market, outcomes) with path validation
- `web/routes/` — REST + WebSocket endpoints for rooms, messages, thesis, market, predictions, journal, LLM, outcomes, health

Security features:
- Path traversal prevention on book_id and room_id (regex validation)
- Typed Pydantic models for all inputs (no raw dict endpoints)
- MessageCreate.msg_type restricted to Literal["user"] — server-only for "system"/"llm"
- LLM compare model list capped at 4

Performance:
- All blocking I/O wrapped in asyncio.to_thread()
- Thesis state cached with 60-second TTL (invalidated on price fetch)
- LLM compare runs models concurrently via asyncio.gather()
- WebSocket broadcasts fan out concurrently with per-send timeout

### Web UI Frontend (`frontend/`)

React + Vite + Tailwind SPA. Dense terminal aesthetic with 5 panels:
1. **Chat** — real-time messaging with @claude/@gpt/@compare LLM mentions, slash commands (/brief, /thesis, /diff, /predict, /watchlist), message pinning, chat export
2. **Thesis Viewer** — cascade phase tracker, node states, confluence scores, countdowns, scenarios
3. **Prediction Tracker** — create/resolve predictions with accuracy tracking
4. **Trade Journal** — log entries with direction, entry/exit prices, P&L
5. **Market Ticker** — live watchlist from book instruments

Features: Command palette (Ctrl+K), keyboard shortcuts, auto-reconnecting WebSocket with exponential backoff, auth persistence in localStorage, toast notifications for errors, XSS-safe markdown rendering.

## File Structure

```
tradingDesk/
├── CLAUDE.md                        # this file
├── README.md                        # usage guide
├── PROJECT.md                       # architecture spec
├── INTEGRATION.md                   # Dialectic integration spec
├── books/                           # thesis configs (one JSON per thesis)
│   ├── iran-hormuz-graph.json       # oil shock DAG — 16 nodes, 14 edges
│   ├── trump-tariffs-graph.json     # tariff escalation DAG — 15 nodes, 18 edges
│   └── iran-hormuz-2026.json       # legacy commodity book config
├── output/                          # generated HTML dashboards
├── snapshots/                       # exported graph state JSONs
├── tools/
│   ├── thesis-graph/
│   │   ├── thesisgraph.py          # core engine (~2200 lines)
│   │   ├── test_export.py          # export + propagation tests (76)
│   │   └── lib/                    # Cytoscape.js + dagre (inlined in HTML)
│   ├── data-fetch/
│   │   ├── polymarket.py           # Polymarket Gamma API fetcher
│   │   └── test_polymarket.py      # Polymarket tests (41)
│   ├── bridge/
│   │   ├── run-all.py              # multi-book pipeline runner
│   │   ├── push-to-dialectic.py    # push snapshots to Dialectic rooms
│   │   ├── diff-snapshots.py       # snapshot delta detection
│   │   ├── test_run_all.py        # runner tests (20)
│   │   ├── test_push.py           # bridge tests (26)
│   │   └── test_diff.py           # diff tests (21)
│   ├── validation/
│   │   ├── e2e_test.py            # full pipeline E2E tests (39)
│   │   └── mock_dialectic.py      # mock Dialectic server
│   └── commodity-book/
│       └── bookgen.py             # legacy commodity book generator
├── web/                             # FastAPI backend
│   ├── main.py                      # app entry + route registration
│   ├── auth.py                      # JWT auth (scrypt, dev users)
│   ├── state.py                     # file-based persistence (atomic writes)
│   ├── ws.py                        # WebSocket connection manager
│   ├── models.py                    # Pydantic request/response models
│   ├── test_web.py                  # web layer tests
│   ├── adapters/                    # CLI tool wrappers
│   │   ├── thesis.py               # thesisgraph adapter (cached)
│   │   ├── market.py               # Yahoo Finance + Polymarket
│   │   └── outcomes.py             # lifecycle, brief, cross-book
│   ├── routes/                      # REST + WebSocket endpoints
│   │   ├── auth.py, health.py      # auth + health check
│   │   ├── thesis.py, market.py    # data endpoints
│   │   ├── messages.py             # chat + WebSocket
│   │   ├── llm.py                  # OpenRouter LLM proxy
│   │   ├── predictions.py          # prediction tracker
│   │   ├── journal.py              # trade journal
│   │   ├── rooms.py, outcomes.py   # rooms + outcomes
│   │   └── ...
│   └── data/                        # runtime state (gitignored)
├── frontend/                        # React + Vite + Tailwind SPA
│   ├── src/
│   │   ├── pages/                   # Dashboard, Login
│   │   ├── components/              # Chat, ThesisViewer, PredictionTracker, etc.
│   │   └── lib/                     # api.ts (auth, WebSocket), types.ts
│   └── ...
├── research/                        # distilled research findings
├── docs/plans/                      # implementation plans
└── docs/solutions/                  # documented solutions to past problems (bugs, security, patterns), organized by category with YAML frontmatter (module, tags, problem_type)
```

## Active Theses

| Config | Thesis | Nodes | Edges | Monthly | Dialectic Room |
|---|---|---|---|---|---|
| `iran-hormuz-graph.json` | Iran/Hormuz oil shock transmission | 16 | 14 | $8,000/mo | `56ba2f1e` |
| `trump-tariffs-graph.json` | Trump tariff escalation | 15 | 18 | $6,000/mo | `8adcabb7` |

## Project Conventions

- CLI tools (`tools/`): zero external Python dependencies (stdlib only)
- Web layer (`web/`): minimal external deps listed in requirements.txt (FastAPI, uvicorn, python-jose, httpx)
- One JSON config per thesis
- HTML dashboards are generated, not hand-built
- All outputs are self-contained single-file HTML
- Tests use pytest, run with `python3 -m pytest`
- CLI tools: 223 tests across 6 test files
- Web layer: web/test_web.py (auth, state, routes, validation, concurrency)
