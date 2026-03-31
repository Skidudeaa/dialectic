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

# Full suite (118 tests)
python3 -m pytest tools/thesis-graph/test_export.py tools/bridge/test_diff.py tools/bridge/test_push.py tools/data-fetch/test_polymarket.py tools/validation/e2e_test.py -q

# By component
python3 -m pytest tools/thesis-graph/test_export.py -q       # 22 — export/propagation
python3 -m pytest tools/bridge/test_diff.py -q               # 21 — snapshot diff
python3 -m pytest tools/bridge/test_push.py -q               # 26 — bridge script
python3 -m pytest tools/data-fetch/test_polymarket.py -q     # 41 — Polymarket fetcher
python3 -m pytest tools/validation/e2e_test.py -q            # 34 — E2E pipeline
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

### Dialectic Integration (`tools/bridge/push-to-dialectic.py`)

POSTs snapshots to Dialectic trading rooms. Token from `DIALECTIC_ROOM_TOKEN` env var. See `INTEGRATION.md` for the full spec.

### E2E Validation (`tools/validation/`)

- `mock_dialectic.py` — mock Dialectic HTTP server with schema validation, error injection, standalone + importable
- `e2e_test.py` — full pipeline tests: snapshot → diff → push → verify round trip

### Commodity Book Generator (`tools/commodity-book/bookgen.py`)

Legacy flat trigger model — 9 instruments, 9 triggers, 4 overlays. Superseded by the thesis graph engine for new work.

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
│   │   ├── test_export.py          # export + propagation tests (22)
│   │   └── lib/                    # Cytoscape.js + dagre (inlined in HTML)
│   ├── data-fetch/
│   │   ├── polymarket.py           # Polymarket Gamma API fetcher
│   │   └── test_polymarket.py      # Polymarket tests (41)
│   ├── bridge/
│   │   ├── push-to-dialectic.py    # push snapshots to Dialectic rooms
│   │   ├── diff-snapshots.py       # snapshot delta detection
│   │   ├── test_push.py           # bridge tests (26)
│   │   └── test_diff.py           # diff tests (21)
│   ├── validation/
│   │   ├── e2e_test.py            # full pipeline E2E tests (34)
│   │   └── mock_dialectic.py      # mock Dialectic server
│   └── commodity-book/
│       └── bookgen.py             # legacy commodity book generator
├── research/                        # distilled research findings
├── docs/plans/                      # implementation plans
└── docs/solutions/                  # documented solutions to past problems (bugs, security, patterns), organized by category with YAML frontmatter (module, tags, problem_type)
```

## Active Theses

| Config | Thesis | Nodes | Edges | Monthly |
|---|---|---|---|---|
| `iran-hormuz-graph.json` | Iran/Hormuz oil shock transmission | 16 | 14 | $8,000/mo |
| `trump-tariffs-graph.json` | Trump tariff escalation | 15 | 18 | $6,000/mo |

## Project Conventions

- Zero external Python dependencies (stdlib only)
- One JSON config per thesis
- HTML dashboards are generated, not hand-built
- All outputs are self-contained single-file HTML
- Tests use pytest, run with `python3 -m pytest`
- 118 tests across 5 test files
