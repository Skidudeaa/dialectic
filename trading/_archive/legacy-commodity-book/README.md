# Legacy Commodity Book (archived 2026-04-10)

> **Breadcrumb — this is where Trading Desk started.**
>
> Not deleted. Kept intact because it's part of why this project exists.

## What this was

`bookgen.py` (974 lines) was the original Trading Desk tool: a flat trigger-model dashboard generator. It read a single JSON config describing instruments, triggers, and overlays, and produced a self-contained interactive HTML "commodity book" for macro trade tracking.

The model was **flat**:
- 9 instruments with entry/target/stop prices
- 9 trigger conditions (threshold crossings on price/macro data)
- 4 "overlays" — editorial annotations on the chart
- No causal structure, no propagation, no scenarios, no phase tracking

You ran it like this (preserved here for historical reference):
```bash
python3 bookgen.py iran-hormuz-2026.json -o active-commodity-book.html
python3 bookgen.py iran-hormuz-2026.json -o book.html --fetch  # with live prices
python3 bookgen.py iran-hormuz-2026.json -o book.html --screenshot --publish
```

## Why it was archived

Using `bookgen.py` in anger surfaced the limitations that made the thesis-graph engine necessary. Those lessons are documented verbatim in [`research/bookgen-lessons.md`](../../research/bookgen-lessons.md) — read that file for the full migration rationale. The short version:

- **Triggers fire in isolation.** A diesel spike and a Brent spike are treated as independent events even when one *caused* the other. No way to encode transmission.
- **No scenario analysis.** You can see "trigger fired" but not "what if Hormuz reopens in May — does this trade still work?"
- **No phase awareness.** A crisis has a shape (shock → transmission → amplification → policy response → resolution). Flat triggers can't track where you are in that arc.
- **No confluence scoring.** When three independent signals converge on "recession risk," flat triggers just show three fired triggers instead of strengthening the convergent signal.
- **Scripting-only.** One-shot HTML generation with no live backend, no collaboration layer, no programmatic interface.

All five of those are solved by `tools/thesis_graph/thesisgraph.py` (2,467 lines, 76 tests) and the wider web layer.

## What survived the migration

- **JSON-as-config** philosophy — thesis-graph still reads a single JSON file per thesis
- **Self-contained HTML** output — thesis-graph still inlines Cytoscape + all assets
- **Walkthrough/validation CLI patterns** — thesis-graph kept `--dry-run`, `--validate`
- **Yahoo Finance price fetching** — reused (no CORS proxy needed in headless mode)
- **Screenshot/publish hooks** — reused conceptually in the web layer

## Contents of this archive

- `bookgen.py` — the tool (executable, will still run if copied back)
- `iran-hormuz-2026.json` — the original flat-trigger Iran/Hormuz config (top-level duplicate)
- `books/iran-hormuz-2026.json` — the same config from `books/` (identical bytes)
- `output/iran-hormuz.html` — generated dashboard (57 KB)
- `active-commodity-book.html` — default-filename generated dashboard (56 KB)
- `screenshots/active-commodity-book-*.png` — 9 scroll-position screenshots of the dashboard

## If you ever need to restore it

```bash
mkdir -p tools/commodity-book
cp _archive/legacy-commodity-book/bookgen.py tools/commodity-book/
cp _archive/legacy-commodity-book/books/iran-hormuz-2026.json books/
python3 tools/commodity-book/bookgen.py books/iran-hormuz-2026.json -o output/iran-hormuz.html
```

Everything it needs is self-contained (stdlib only, no imports from the rest of the repo).
