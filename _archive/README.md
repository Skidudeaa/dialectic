# _archive/

Superseded code and orphan artifacts. **Do not delete without explicit review.**

This directory is explicitly excluded from the test suite, documentation, and tooling paths. Items land here instead of `git rm` so the context of *why* something was removed survives.

## Contents

### `empty-placeholders/`

Directories that existed under `tools/` but were never populated (only `.gitkeep` files). Moved here 2026-04-10 during consolidation pass.

- **`polymarket/`** — Empty placeholder. The canonical Polymarket fetcher is `tools/data-fetch/polymarket.py` (362 lines, 41 tests). This empty directory was likely an early refactor idea that never happened.
- **`signals/`** — Empty placeholder. Not referenced anywhere in the codebase. Possibly intended for a signals pipeline that was later absorbed into `tools/thesis-graph/thesisgraph.py` propagation logic or `tools/outcomes/lifecycle_monitor.py` predicates.

### `orphan-snapshots/`

Snapshot files that no longer fit the `{book-id}-latest.json` / `{book-id}-prev.json` rotation convention established by `tools/bridge/run-all.py`. Moved here 2026-04-10.

- **`test.json`** — A lone test artifact from 2026-03-30, before the snapshot rotation convention existed. Not referenced by any test or tool.
- **`trump-tariffs-latest.json`** — Pre-graph-version naming (the active book is `trump-tariffs-graph.json`, producing `trump-tariffs-graph-latest.json`). This file is stale and superseded.

## Restoring something from here

If you need to restore anything, just `git mv` it back to its original location and rerun the test suite. Nothing in `_archive/` has import links to the live codebase, so restoring is safe.
