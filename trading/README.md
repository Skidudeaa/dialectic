# tradingDesk

Causal reasoning engine for macro trading. Models the world as a directed graph of transmission chains, propagates market data and probabilities through the DAG, and generates interactive HTML dashboards.

Zero external Python dependencies. One JSON config per thesis. Single-file HTML output.

## Generate a Dashboard

```bash
# Iran/Hormuz thesis
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  -o output/iran-hormuz-graph.html

# Trump tariff escalation thesis
python3 tools/thesis_graph/thesisgraph.py books/trump-tariffs-graph.json \
  -o output/trump-tariffs-graph.html

# With live prices (Yahoo Finance + Polymarket probabilities)
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  -o output/iran-hormuz-graph.html --fetch

# Open in any browser — no server needed
open output/iran-hormuz-graph.html
```

The generated HTML has 5 tabs:

| Tab | What It Shows |
|---|---|
| **Graph** | Interactive Cytoscape.js DAG. Nodes colored by state: fired / approaching / stable / gated. |
| **Cascade** | "WE ARE HERE" 5-phase crisis tracker with signpost checklists and countdown timers. |
| **Scenarios** | Toggle between probability-weighted scenarios. Portfolio impact waterfall. |
| **Portfolio** | Instruments grouped by graph node. Range bars, position tracking, R:R ratios. |
| **Journal** | Node-linked decision audit trail. |

## Thesis Graph Engine

```bash
# Validate config (no output generated)
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json --dry-run

# Export evaluated graph state as JSON
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  --export-state snapshots/latest.json

# Fetch + export + generate in one command
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  --fetch --export-state snapshots/latest.json -o output/graph.html

# Pipe snapshot to stdout for scripting
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  --export-state - 2>/dev/null
```

### Propagation

Kahn's topological sort evaluates each node against thresholds and propagates upstream signals downstream. Signal confluence scores nodes where multiple independent causal paths converge — high fan-in = high confidence.

### Live Price Fetch (`--fetch`)

Pulls from two sources:
- **Yahoo Finance** — ETFs, futures, FX, indices via v7 spark API. Backend calls `query1.finance.yahoo.com` directly; generated HTML dashboards refresh through the webapp's own `/api/relay/yahoo` (no third-party proxy)
- **Polymarket** — prediction market probabilities via Gamma API, mapped onto graph nodes with `"source": "polymarket"` feeds

```bash
# Standalone Polymarket check
python3 tools/data_fetch/polymarket.py us-iran-april-30 --json
```

## Snapshot Diff

```bash
python3 tools/bridge/diff_snapshots.py snapshots/yesterday.json snapshots/today.json
```

Outputs: state transitions, confluence shifts, countdown changes, market price moves. Exit 0 = changes found, 1 = identical, 2 = error.

## Dialectic Integration

Push thesis state into Dialectic trading rooms. The LLM sees your positions, triggers, and scenarios during collaborative discussions.

```bash
# Set room token (treat as secret — grants full room access)
export DIALECTIC_ROOM_TOKEN=<your-token>

# Push a snapshot
python3 tools/bridge/push_to_dialectic.py \
  --snapshot snapshots/latest.json \
  --room-id <uuid> \
  --dialectic-url http://localhost:8002

# One-liner: fetch → evaluate → push
python3 tools/thesis_graph/thesisgraph.py books/iran-hormuz-graph.json \
  --fetch --export-state - 2>/dev/null | \
  python3 tools/bridge/push_to_dialectic.py --snapshot - --room-id <uuid>

# Diff-gated push (only push if something changed)
python3 tools/bridge/diff_snapshots.py snapshots/old.json snapshots/new.json && \
  python3 tools/bridge/push_to_dialectic.py --snapshot snapshots/new.json --room-id <uuid>
```

### Mock Dialectic Server (for testing)

```bash
# Start mock on port 8002
python3 tools/validation/mock_dialectic.py --port 8002

# In another terminal: push a snapshot to the mock
export DIALECTIC_ROOM_TOKEN=test-token
python3 tools/bridge/push_to_dialectic.py \
  --snapshot snapshots/latest.json --room-id test-room

# Check what the mock received
curl http://localhost:8002/snapshots
```

## Active Theses

| Config | Thesis | Nodes | Edges | Monthly Budget |
|---|---|---|---|---|
| `books/iran-hormuz-graph.json` | Iran/Hormuz oil shock transmission | 16 | 14 | $8,000 |
| `books/trump-tariffs-graph.json` | Trump tariff escalation | 15 | 18 | $6,000 |

## Writing a New Thesis

Create a JSON config in `books/`. Required sections:

```
meta            — title, date, claim, budget
nodes           — observable states (event, price, indicator, deadline, gate, constraint, conditional, reversal)
edges           — causal channels with mechanism, lag, strength (0-1)
instruments     — portfolio positions mapped to nodes (monthly alloc, ref, targets, stops)
scenarios       — what-if overrides with probability-weighted portfolio impact
cascadePhases   — 5-phase tracker (shock → transmission → amplification → policyResponse → resolution)
marketFields    — editable market data inputs
fetchSymbols    — Yahoo Finance symbols for --fetch
rules           — trading discipline
provenance      — sources, methodology, limitations
```

Validate with `--dry-run`, generate with `-o`, export state with `--export-state`. See the two existing configs for complete examples.

## Tests

```bash
# Full suite (118 tests)
python3 -m pytest tools/thesis_graph/test_export.py \
  tools/bridge/test_diff.py tools/bridge/test_push.py \
  tools/data_fetch/test_polymarket.py \
  tools/validation/e2e_test.py -q

# By component
python3 -m pytest tools/thesis_graph/test_export.py -q       # 22 — export/propagation
python3 -m pytest tools/bridge/test_diff.py -q               # 21 — snapshot diff
python3 -m pytest tools/bridge/test_push.py -q               # 26 — bridge script
python3 -m pytest tools/data_fetch/test_polymarket.py -q     # 41 — Polymarket fetcher
python3 -m pytest tools/validation/e2e_test.py -q            # 34 — E2E pipeline
```

## Project Structure

```
tradingDesk/
├── books/                           # Thesis configs (one JSON per thesis)
│   ├── iran-hormuz-graph.json       # Oil shock DAG — 16 nodes, 14 edges
│   ├── trump-tariffs-graph.json     # Tariff escalation DAG — 15 nodes, 18 edges
│   └── iran-hormuz-2026.json       # Legacy commodity book
├── output/                          # Generated HTML dashboards
├── snapshots/                       # Exported graph state JSONs
├── tools/
│   ├── thesis_graph/
│   │   ├── thesisgraph.py          # Core engine — config → propagation → HTML
│   │   ├── test_export.py          # Export + propagation tests
│   │   └── lib/                    # Cytoscape.js + dagre (inlined in HTML)
│   ├── data_fetch/
│   │   ├── polymarket.py           # Polymarket Gamma API fetcher
│   │   └── test_polymarket.py      # Polymarket tests
│   ├── bridge/
│   │   ├── push_to_dialectic.py    # Push snapshots to Dialectic rooms
│   │   ├── diff_snapshots.py       # Snapshot delta detection
│   │   ├── test_push.py           # Bridge tests
│   │   └── test_diff.py           # Diff tests
│   ├── validation/
│   │   ├── e2e_test.py            # Full pipeline E2E tests
│   │   └── mock_dialectic.py      # Mock Dialectic server (standalone + importable)
│   └── commodity-book/
│       └── bookgen.py             # Legacy commodity book generator
├── PROJECT.md                      # Architecture spec
├── INTEGRATION.md                  # Dialectic integration spec
└── CLAUDE.md                       # AI assistant instructions
```

## Requirements

- Python 3.10+
- pytest (tests only)
- No other dependencies
