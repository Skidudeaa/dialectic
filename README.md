# tradingDesk

A causal reasoning engine for macro trading. Models transmission chains as a directed graph, propagates market data through the DAG, and generates interactive HTML dashboards for collaborative decision-making.

Built for two traders (Amo and Dan) to develop independent market judgment through structured tools — not narratives.

## What It Does

You define a thesis as a causal graph:

```
Hormuz Closure → Brent Price → Diesel → Freight Cost → Employment → Demand Destruction
                → Fertilizer Shortage → Planting Miss → Food Spike → EM Sovereign Stress
```

The engine evaluates which nodes have fired, which are approaching their thresholds, where multiple paths converge (signal confluence), and what each scenario implies for your portfolio. Then it generates an interactive HTML dashboard you can open in any browser — no server needed.

It also pushes thesis state into [Dialectic](https://github.com/your-repo/dialectic) so the LLM sees your positions and triggers when you and Dan discuss markets.

## Quick Start

```bash
# Generate the thesis graph dashboard
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json \
  -o output/iran-hormuz-graph.html

# With live Yahoo Finance prices
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json \
  -o output/iran-hormuz-graph.html --fetch

# Open in browser
open output/iran-hormuz-graph.html
```

## Core Tools

### Thesis Graph Engine

Reads a JSON graph config → evaluates all nodes via topological propagation → generates a self-contained HTML dashboard (747 KB with inlined Cytoscape.js).

```bash
# Generate dashboard
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json -o output/graph.html

# Dry run (validate + show propagation results, no output)
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --dry-run

# Export evaluated state as JSON
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --export-state snapshots/latest.json

# Fetch live prices + export + generate
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json \
  --fetch --export-state snapshots/latest.json -o output/graph.html
```

The generated HTML has 5 interactive tabs:
- **Graph** — Cytoscape.js DAG with nodes colored by state (fired/approaching/stable/gated)
- **Cascade** — "WE ARE HERE" phase tracker with signpost checklists and countdown timers
- **Scenarios** — toggle between scenarios, see portfolio impact waterfall
- **Portfolio** — instruments grouped by graph node with range bars and position tracking
- **Journal** — decision audit trail linked to graph nodes

### Snapshot Diff

Compare two snapshots to see what changed:

```bash
python3 tools/bridge/diff-snapshots.py snapshots/yesterday.json snapshots/today.json
```

Outputs state transitions, confluence shifts, countdown changes, and market price moves. Exit code 0 if changes found, 1 if identical.

### Dialectic Integration

Push thesis state into Dialectic trading rooms so the LLM sees your positions and triggers during collaborative discussions:

```bash
# One-liner: fetch → evaluate → push to Dialectic
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json \
  --fetch --export-state - 2>/dev/null | \
  DIALECTIC_ROOM_TOKEN=xxx python3 tools/bridge/push-to-dialectic.py \
  --snapshot - --room-id <uuid>
```

When Dan says "should we add to CF?", the LLM responds with: *"Fertilizer stress node is at 97.6% of threshold. 17 days to planting deadline. The Kharg scenario shows CF +7.2%."*

When you're offline and Brent crosses $115, the Trading Curator drops: *"Brent persistence trigger approaching. Dan, if this holds through Wednesday, the framework says deploy $400 SGOV into XOP."*

### Commodity Book (legacy)

The original flat trigger model — 9 instruments, 9 triggers, 4 overlays:

```bash
python3 tools/commodity-book/bookgen.py books/iran-hormuz-2026.json -o output/book.html --fetch
```

## Graph Config

The thesis is defined in a JSON file. Key sections:

| Section | What It Contains |
|---|---|
| `nodes` | Observable economic states (16 in Iran/Hormuz thesis) |
| `edges` | Causal transmission channels with lags and strengths |
| `instruments` | Portfolio positions mapped to graph nodes |
| `scenarios` | What-if overrides with probability-weighted impact |
| `cascadePhases` | 5-phase crisis tracker with signpost checklists |
| `marketFields` | Editable market data inputs |
| `fetchSymbols` | Yahoo Finance symbols for live price fetch |

See `books/iran-hormuz-graph.json` for the complete example.

## Tests

```bash
# All tests (69 total)
python3 -m pytest tools/thesis-graph/test_export.py tools/bridge/test_diff.py tools/bridge/test_push.py -q

# Export tests only
python3 -m pytest tools/thesis-graph/test_export.py -q

# Diff tests
python3 -m pytest tools/bridge/test_diff.py -q

# Bridge script tests
python3 -m pytest tools/bridge/test_push.py -q
```

## Project Structure

```
tradingDesk/
├── books/                        # Thesis configs (one JSON per thesis)
│   ├── iran-hormuz-graph.json    # Causal DAG: 16 nodes, 14 edges
│   └── iran-hormuz-2026.json    # Legacy commodity book
├── output/                       # Generated HTML dashboards
├── snapshots/                    # Exported graph state JSONs
├── tools/
│   ├── thesis-graph/
│   │   ├── thesisgraph.py       # Causal DAG generator
│   │   ├── test_export.py       # Export tests
│   │   └── lib/                 # Cytoscape.js + dagre
│   ├── bridge/
│   │   ├── push-to-dialectic.py # Bridge to Dialectic
│   │   ├── diff-snapshots.py    # Snapshot delta detection
│   │   ├── test_push.py         # Bridge tests
│   │   └── test_diff.py         # Diff tests
│   └── commodity-book/
│       └── bookgen.py           # Legacy commodity book generator
├── research/                     # Archived research from planning
├── docs/plans/                   # Implementation plans
├── PROJECT.md                    # Architecture spec
└── INTEGRATION.md                # Dialectic integration spec
```

## Requirements

- Python 3.10+
- No external dependencies (stdlib only)

## Philosophy

The market doesn't reward information. It rewards judgment. tradingDesk exists to sharpen judgment by forcing structured thinking — triggers not narratives, transmission chains not vibes, scenarios not predictions.

The thesis IS the graph. The portfolio IS positions at specific nodes. The system ensures that if you believe A, B, and C, then D follows with probability X and portfolio impact Y.
