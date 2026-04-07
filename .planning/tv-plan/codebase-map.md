# tradingDesk Codebase Map — for TradingView Integration

## Core engine: `tools/thesis-graph/thesisgraph.py` (2371 lines)

Key functions and where to hook:

| Line | Function | Purpose |
|---|---|---|
| 46 | `load_config(path)` | Load thesis graph JSON |
| 58 | `validate_config(cfg)` | Validate nodes/edges, check node types |
| 145 | `topo_sort(nodes, edges)` | Kahn's topological sort |
| 168 | `eval_node_state(node, upstream_states, edges)` | Evaluate one node's state against thresholds |
| 298 | `propagate(cfg)` | Run full propagation — returns states dict |
| 313 | `score_confluence(cfg, states)` | Fan-in analysis, returns confluence dict |
| 337 | `get_current_phase(cfg)` | Cascade phase detection (5-phase tracker) |
| 357 | `eval_scenario(cfg, scenario, base_states)` | Evaluate what-if scenario |
| 425 | `export_state(cfg, states, ...)` | **Build snapshot JSON v:1** |
| 552 | `fetch_prices(cfg, retries=2)` | **Yahoo Finance fetcher — mutates cfg with prices** |
| 674 | `fetch_polymarket(cfg)` | **Polymarket probability fetcher** |
| 979 | `generate_html(cfg)` | Build Cytoscape.js dashboard |
| 2235 | `main()` | CLI entry — wires `--fetch`, `--export-state`, `--dry-run`, `-o` |
| 2293-2298 | (in main) | Where fetch_prices and fetch_polymarket are called |

### Feed schema in node definitions
```json
{ "source": "yahoo",     "symbol": "BZ=F", "label": "Brent futures" }
{ "source": "polymarket","market": "us-iran-april-30" }
{ "source": "eia",       "series": "EMD_EPD2D_PTE_NUS_DPG" }  // not yet implemented
{ "source": "manual" }                                         // human-entered
```

A TradingView feed would follow this pattern:
```json
{ "source": "tradingview", "symbol": "BINANCE:BTCUSDT", "timeframe": "1h", "indicator": "RSI" }
```

### Snapshot v:1 schema (from `export_state()`, line 425)
```
{
  "v": 1, "timestamp": ISO8601Z, "title": str,
  "nodeStates": {nodeId: "fired"|"approaching"|"stable"|"gated"},
  "confluenceScores": {nodeId: float},
  "cascadePhase": {"number": int, "key": str, "status": str},
  "countdowns": [{nodeId, label, deadline, daysRemaining}],
  "marketSnapshot": {marketFieldKey: value},
  "scenarioImpacts": {scenarioId: {probability, netImpact}},
  "portfolioSummary": {monthlyBudget, topPositions, sgovAvailable}
}
```

## Data-fetch layer: `tools/data-fetch/polymarket.py` (362 lines)

- Pure stdlib (`urllib.request`, `json`)
- 3-pass slug matching (exact → substring → keyword)
- Parses Polymarket Gamma API `outcomePrices` for "Yes" probability
- Imported dynamically by thesisgraph.py; can also be invoked as CLI: `python3 tools/data-fetch/polymarket.py <slug> --json`
- 41 tests in `test_polymarket.py`

**A TradingView fetcher would live here**: `tools/data-fetch/tradingview.py` (following the same pattern — standalone module with CLI, importable dynamically).

## Bridge/pipeline layer: `tools/bridge/`

| File | Lines | Purpose |
|---|---|---|
| `run-all.py` | 393 | Multi-book runner: discovers books/, rotates snapshots, per-book fetch→export→diff→push |
| `push-to-dialectic.py` | 240 | POST snapshot to Dialectic room with auth token |
| `diff-snapshots.py` | 207 | Compare old/new snapshots, detect state transitions/confluence shifts/countdown changes |

## Validation: `tools/validation/`

| File | Lines | Purpose |
|---|---|---|
| `mock_dialectic.py` | 253 | HTTP server with schema validation, error injection — importable + CLI |
| `e2e_test.py` | 961 | Full pipeline tests (snapshot → diff → push → verify) — 39 tests |

## Book configs: `books/`

| File | Type | Details |
|---|---|---|
| `iran-hormuz-graph.json` | thesis-graph | 16 nodes, 14 edges, $8k/mo, Dialectic room `56ba2f1e...` |
| `trump-tariffs-graph.json` | thesis-graph | 15 nodes, 18 edges, $6k/mo, Dialectic room `8adcabb7...` |
| `iran-hormuz-2026.json` | commodity-book | Legacy flat trigger model |

**Meta fields on each book**:
```json
"meta": {
  "title": "...",
  "asOf": "YYYY-MM-DD",
  "claim": "...",
  "version": "1.0.0",
  "type": "thesis-graph",
  "monthlyBudget": 8000,
  "dialecticRoomId": "uuid",
  "dialecticRoomToken": "..."
}
```

Adding TradingView could introduce new meta fields:
```json
"tradingview": {
  "watchlist": ["BINANCE:BTCUSDT", "NASDAQ:AAPL"],
  "primaryTimeframe": "4h",
  "biasRules": {...},
  "cdpPort": 9222
}
```

## Test conventions

- pytest, invoked as `python3 -m pytest <file> -q`
- Module-level tests (not class-based)
- Mock HTTP via `http.server.BaseHTTPRequestHandler` (see mock_dialectic.py pattern)
- 223 tests total across 6 files
- Zero external deps; pytest itself is the only non-stdlib

## Conventions to respect

1. **Stdlib-only Python** (zero pip deps except pytest for dev) — CLAUDE.md says this explicitly
2. **One JSON config per thesis**
3. **Generated, self-contained HTML dashboards** (Cytoscape.js inlined)
4. **Error handling**: explicit exceptions, no bare `except`, use `logging.getLogger(__name__)` not `print` for library code — `print(..., file=sys.stderr)` for CLI feedback
5. **Type hints on public functions**
6. **All outputs in `output/`** for HTML, `snapshots/` for JSON state exports
7. **Per-book snapshot rotation**: `snapshots/{book-id}-latest.json` + `{book-id}-prev.json`

## Where TradingView integration attaches

### Option A — New data source (minimal invasion)
- New file `tools/data-fetch/tradingview.py` mirroring polymarket.py pattern
- New feed source type: `{"source": "tradingview", ...}`
- New `fetch_tradingview(cfg)` function in thesisgraph.py line ~720
- Call from main() alongside fetch_prices + fetch_polymarket at line ~2295
- New test file `tools/data-fetch/test_tradingview.py`
- Book configs gain TV feeds on nodes that need chart data

### Option B — Sidecar MCP bridge (maximum power)
- Separate `tools/tradingview-bridge/` directory (Node.js if leveraging Jackson's MCP, or Python stdlib with webhook receiver)
- Own lifecycle: started by `run-all.py` as subprocess, or runs persistent
- Exports data into snapshots via a new snapshot field `tvState` or enriches `marketSnapshot`

### Option C — Morning brief mirror (feature steal)
- New `tools/brief/morning-brief.py` that reads thesis graphs + TV chart state
- Generates structured bias report per thesis
- Pushes directly into Dialectic as separate briefing (not via snapshot)
- Rules config either in book JSONs (`meta.biasRules`) or standalone `books/brief-rules.json`

### Option D — Alert webhook receiver
- `tools/bridge/tv-webhook.py`: tiny `http.server` receiver listening for TradingView Pine Script alerts
- Each received alert → mutates a node's state in the relevant thesis book JSON
- Natural fit: fires when chart crosses price thresholds already defined in thesis nodes

## Extension points summary

| tradingDesk feature | How TradingView enhances it |
|---|---|
| Node `feeds` | Add TV source for indicator values |
| `fetch_prices()` | Add `fetch_tradingview()` sibling |
| `marketSnapshot` in snapshot JSON | Enrich with TV indicator readings |
| `cascadePhases` tracker | Morning brief auto-grades signposts via chart state |
| Dialectic push | Attach chart screenshots to briefings |
| `run-all.py` pipeline | New step: TV-scan → enrich → brief → push |
| Journal tab (HTML) | Link TV chart snapshots to audit trail entries |
| Instruments (portfolio) | Pull TV OHLCV to size positions vs ATR |
