# CLAUDE.md

## What This Is

Trading Desk — a causal reasoning engine for macro trading. Models the world as a directed graph of transmission chains (oil shock → diesel → freight → employment → demand destruction), propagates data and probabilities through the graph, and generates interactive HTML dashboards for collaborative decision-making.

Two tools: the **commodity book generator** (flat trigger state machine) and the **thesis graph engine** (causal DAG with scenarios, cascade tracking, and signal confluence).

## Quick Start

```bash
# === Thesis Graph Engine ===

# Generate interactive causal DAG dashboard
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json -o output/iran-hormuz-graph.html

# With live Yahoo Finance prices
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json -o output/iran-hormuz-graph.html --fetch

# Export evaluated graph state as JSON (for Dialectic integration)
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --export-state snapshots/latest.json

# Fetch + export + generate HTML in one command
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state snapshots/latest.json -o output/iran-hormuz-graph.html

# Pipe snapshot to stdout for bridge scripts
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --export-state - 2>/dev/null

# Dry run (validate + propagate, no output)
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --dry-run

# === Snapshot Diff ===

# Compare two snapshots, output structured delta
python3 tools/bridge/diff-snapshots.py snapshots/old.json snapshots/new.json

# Chain: only push if something changed
python3 tools/bridge/diff-snapshots.py snapshots/old.json snapshots/new.json && \
  python3 tools/bridge/push-to-dialectic.py --snapshot snapshots/new.json --room-id <uuid>

# === Commodity Book (legacy flat trigger model) ===

# Generate commodity book dashboard
python3 tools/commodity-book/bookgen.py books/iran-hormuz-2026.json -o output/iran-hormuz.html

# With live prices
python3 tools/commodity-book/bookgen.py books/iran-hormuz-2026.json -o output/iran-hormuz.html --fetch

# === Tests ===

# All tests
python3 -m pytest tools/thesis-graph/test_export.py tools/bridge/test_diff.py -q

# Export tests only
python3 -m pytest tools/thesis-graph/test_export.py -q

# Diff tests only
python3 -m pytest tools/bridge/test_diff.py -q
```

## Architecture

### Thesis Graph Engine (`tools/thesis-graph/thesisgraph.py`)

The core tool. Reads a thesis graph JSON config describing a causal DAG and generates a self-contained interactive HTML dashboard with inlined Cytoscape.js.

**JSON graph config → thesisgraph.py → single-file HTML (747 KB)**

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

### Snapshot Export (`--export-state`)

Exports the evaluated graph state as structured JSON for integration with Dialectic (collaborative reasoning platform). Shape:

```json
{
  "v": 1,
  "timestamp": "2026-03-30T14:00:00Z",
  "nodeStates": {"hormuz": "fired", "brent": "approaching", ...},
  "confluenceScores": {"em-stress": 1.30},
  "cascadePhase": {"number": 2, "key": "transmission", "status": "STARTING"},
  "countdowns": [{"nodeId": "planting-miss", "daysRemaining": 17}],
  "marketSnapshot": {"brent": 112.57, "diesel": 5.38, ...},
  "scenarioImpacts": {"closed-may": {"probability": 0.45, "netImpact": 12.8}},
  "portfolioSummary": {"monthlyBudget": 8000, "topPositions": [...]}
}
```

### Delta Detection (`tools/bridge/diff-snapshots.py`)

Compares two snapshot JSONs and outputs structured deltas: state transitions, confluence shifts, countdown changes, market price moves, added/removed nodes. Exit code 0 = changes found, 1 = no changes, 2 = error.

### Commodity Book Generator (`tools/commodity-book/bookgen.py`)

The original flat trigger model — 9 instruments, 9 triggers, 4 overlays. Still functional but superseded by the thesis graph engine for new work.

### Live Price Fetch

Both generators use allorigins.win CORS proxy → Yahoo Finance v7 spark API (no API key needed). Fetches ETF/stock prices, commodity futures, and calculates curve spreads.

### Dialectic Integration

tradingDesk pushes thesis graph snapshots into Dialectic trading rooms so the LLM sees positions, triggers, and scenarios during collaborative discussions. See `INTEGRATION.md` for the full spec.

## File Structure

```
tradingDesk/
├── CLAUDE.md                     # this file
├── PROJECT.md                    # causal reasoning engine architecture
├── INTEGRATION.md                # Dialectic integration spec
├── books/                        # thesis configs
│   ├── iran-hormuz-graph.json    # causal DAG config (16 nodes, 14 edges)
│   └── iran-hormuz-2026.json    # legacy commodity book config
├── output/                       # generated HTML dashboards
├── snapshots/                    # exported graph state JSONs
├── tools/
│   ├── thesis-graph/
│   │   ├── thesisgraph.py       # causal DAG generator (2080+ lines)
│   │   ├── test_export.py       # export tests (22 tests)
│   │   └── lib/                 # Cytoscape.js + dagre (inlined in HTML)
│   ├── bridge/
│   │   ├── diff-snapshots.py    # snapshot delta detection
│   │   └── test_diff.py         # diff tests (21 tests)
│   └── commodity-book/
│       └── bookgen.py           # legacy commodity book generator
├── research/                     # archived research from planning swarms
└── docs/plans/                   # implementation plans
```

## Current Thesis

| Config | Thesis | Nodes | Monthly |
|---|---|---|---|
| `iran-hormuz-graph.json` | Iran/Hormuz oil shock transmission chains | 16 nodes, 14 edges | $8,000/mo |

## Project Conventions

- Zero external Python dependencies (stdlib only)
- One JSON config per thesis
- HTML dashboards are generated, not hand-built
- All outputs are self-contained single-file HTML
- Tests use pytest, run with `python3 -m pytest`
