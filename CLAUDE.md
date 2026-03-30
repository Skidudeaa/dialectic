# CLAUDE.md

## What This Is

Trading Desk — an active commodity book and portfolio management toolkit. Generates interactive HTML dashboards from JSON configs for tracking positions, escalation triggers, and trade execution.

## Quick Start

```bash
# Generate HTML dashboard from config
python3 tools/commodity-book/bookgen.py tools/commodity-book/iran-hormuz-2026.json -o book.html

# With live Yahoo Finance prices
python3 tools/commodity-book/bookgen.py tools/commodity-book/iran-hormuz-2026.json -o book.html --fetch

# Full pipeline (generate + validate + screenshot + publish to Reading Room)
python3 tools/commodity-book/bookgen.py tools/commodity-book/iran-hormuz-2026.json \
  -o book.html --fetch --validate --screenshot --publish --username amo
```

## Architecture

### Commodity Book Generator (`tools/commodity-book/bookgen.py`)

Transforms a declarative JSON config into a complete interactive HTML trading dashboard.

**JSON config → bookgen.py → single-file HTML dashboard**

The generated HTML has 4 tabs:
1. **Dashboard** — stats bar (book value, P&L, return, SGOV available), action summary, market data inputs, execution rules
2. **Book** — instrument cards with position entry, P&L, range bars (stop→current→target), SGOV deployment ledger, overlay categories
3. **Triggers** — 9-type escalation trigger state machine with close-date logging, binary toggles, constraint indicators
4. **Journal** — typed entries (trade/review/trigger/note/setup), filter chips, auto-logging, export/import JSON

### JSON Config Schema

See `bookgen.py walkthrough` for full schema docs. Key sections:
- `instruments[]` — core portfolio (ticker, monthly allocation, targets, stops)
- `triggers[]` — escalation triggers (numeric thresholds, binary toggles, constraints)
- `overlays[]` — conditional instruments unlocked by triggers
- `marketFields[]` — editable market data inputs
- `fetchSymbols` — Yahoo Finance symbol mappings for live price fetch
- `rules[]` — execution rules (HTML strings)
- `situationUpdate` — current intelligence briefing
- `provenance` — sources, methodology, limitations

### Live Price Fetch

Uses allorigins.win CORS proxy → Yahoo Finance v7 spark API (no API key needed). Fetches ETF/stock prices, commodity futures (BZ=F, CL=F, GC=F), and calculates curve spreads from Brent deferred months.

### Integration with Reading Room

The `--publish` flag uploads the generated HTML as an article to the Reading Room platform. Requires `--username` and `RR_PASSWORD` env var.

## Current Books

| Config | Thesis | Monthly |
|---|---|---|
| `iran-hormuz-2026.json` | Iran/Hormuz crisis — overweight producers, fertilizer, gold; services capped | $8,000/mo |

## Project Conventions

- One JSON config per thesis/book
- bookgen.py is the single generator — all HTML dashboards are generated, not hand-built
- Screenshots use the infographic-gen skill's `screenshot.py` script
