---
date: 2026-03-31
topic: multi-book-runner
---

# Multi-Book Runner

## Problem Frame

Running the full thesis pipeline (fetch → export → diff → conditional push) for two active theses requires two separate commands with different room IDs. As thesis count grows this becomes a maintenance tax, and automation via cron requires multiple entries that must be kept in sync. The runner collapses this to one command and moves the room-ID configuration into the book JSON where it belongs.

## Pipeline Flow

```
For each book in books/ where meta.type == "thesis-graph":

  Copy {book-id}-latest.json → {book-id}-prev.json (if exists)
              │
  ┌───────────▼──────────────────────────────────────────────┐
  │  thesisgraph.py --fetch --export-state                   │
  │  snapshots/{book-id}-latest.json                         │
  └───────────┬──────────────────────────────────────────────┘
              │
  ┌───────────▼──────────────────────────────────────────────┐
  │  diff-snapshots.py                                       │
  │  {book-id}-prev.json vs {book-id}-latest.json            │
  └───────────┬──────────────────────────────────────────────┘
              │
      changes found?
     ┌─────────┴─────────────────┐
  YES│                           │NO
  ┌──▼───────────────┐    ┌──────▼─────────────────────┐
  │ push-to-         │    │ Skip push (no changes)     │
  │ dialectic.py     │    └────────────────────────────┘
  └──────────────────┘
```

## Requirements

**Book Discovery**
- R1. `run-all.py` reads every `*.json` file in `books/` and runs each that has `meta.type == "thesis-graph"`. All other JSONs are silently skipped (covers the legacy `iran-hormuz-2026.json` commodity-book format).
- R2. Book ID is derived from the filename (e.g., `books/iran-hormuz-graph.json` → book ID `iran-hormuz-graph`). No explicit ID field required in the JSON.
- R3. Books are processed sequentially in alphabetically sorted order by filename. Sorting is enforced (not relying on filesystem order) so output is consistent across platforms and CI runs.

**Configuration**
- R4. Room ID lives in `meta.dialecticRoomId` in the book JSON. Example: `"dialecticRoomId": "3fa85f64-5717-4562-b3fc-2c963f66afa6"`. Both existing active books (`books/iran-hormuz-graph.json`, `books/trump-tariffs-graph.json`) must be updated to include this field before the runner can push to Dialectic.
- R5. Auth uses the existing `DIALECTIC_ROOM_TOKEN` environment variable — one shared token for all rooms. The room ID is obtained from the Dialectic admin (room creation response or room settings page) and stored manually in the book JSON.
- R6. If a book has no `meta.dialecticRoomId`, the runner executes the fetch + export step only, skips diff and push, and logs a warning: `[warn] iran-hormuz-graph: no dialecticRoomId — export only`. This is the intended steady-state for local-only theses, not a transitional state.

**Snapshot Management**
- R7. Snapshot filenames are per-book: `snapshots/{book-id}-latest.json`.
- R8. Before each export, the runner copies `{book-id}-latest.json` → `{book-id}-prev.json` if the latest file exists. This gives `diff-snapshots.py` a stable previous state without requiring the user to manage file names manually.
- R9. If neither prev nor latest exist (first run for a book), the runner skips the diff and push steps and logs: `[info] iran-hormuz-graph: first run — snapshot saved, no diff`.

**Failure Handling**
- R10. If any pipeline step fails for a book (non-zero exit), the runner logs the error, marks the book as failed, and continues to the next book. Subprocess stderr is passed through directly (not captured) so errors are visible immediately in the terminal and log file.
- R11. The runner exits non-zero if any book failed, so cron can detect and log failures.

**Usability**
- R12. `--dry-run` flag: validates book discovery, prints what would run for each book (book ID, room ID, snapshot paths), and exits without executing any fetches, exports, diffs, or pushes.
- R13. `--books DIR` flag: override the default `books/` directory (useful for testing with a subset of configs).
- R14. After all books complete, the runner prints a per-book status summary to stdout — one line per book, printed after subprocess output:

```
[iran-hormuz-graph]    export=OK  changed=yes  pushed=OK
[trump-tariffs-graph]  export=OK  changed=no   pushed=-
```

## Success Criteria

- `python3 tools/bridge/run-all.py` from repo root processes both active theses end-to-end with no additional arguments beyond the `DIALECTIC_ROOM_TOKEN` env var (once `dialecticRoomId` is added to both book JSONs).
- A cron entry of the form `0 8 * * 1,3,5 cd /path/to/tradingDesk && python3 tools/bridge/run-all.py >> logs/run-all.log 2>&1` works without further configuration.
- Adding a new thesis requires only creating a book JSON with `meta.type: "thesis-graph"` and `meta.dialecticRoomId` — no changes to `run-all.py`.

## Scope Boundaries

- No snapshot ring buffer (keeping last N historical snapshots) — that is a separate feature (ideation #3).
- No HTML dashboard generation — the runner is export-only by default. Users who want HTML still invoke `thesisgraph.py -o` directly.
- No parallel book processing.
- No retry / backoff logic — network errors surface as non-zero exit for that book and the runner continues.
- No per-book token support — a single `DIALECTIC_ROOM_TOKEN` only.
- No `--dialectic-url` override on the runner — `push-to-dialectic.py` accepts it directly when needed.

## Key Decisions

- **Entry point is `tools/bridge/run-all.py`**: Keeps `thesisgraph.py` clean — it is ~2200 lines of core engine and should not own orchestration logic.
- **Shared token**: One `DIALECTIC_ROOM_TOKEN` applies to all rooms. Per-room tokens deferred until Dialectic auth model is finalized.
- **Per-book snapshot naming**: Avoids collisions when two books run in sequence. Lightweight alternative to the full ring buffer — just current + previous per book.
- **Continue-on-failure**: For a cron-driven pipeline, aborting the whole run because one book had a network error is worse than reporting the error and completing the others.
- **Stderr passthrough, not captured**: Subprocess errors appear immediately in the terminal/log; the summary line is printed after all books complete.
- **No `--dialectic-url` on runner**: Eliminated as premature — both active books hit the same Dialectic instance, and `push-to-dialectic.py` already accepts the flag for one-off overrides.

## Dependencies / Assumptions

- `thesisgraph.py`, `diff-snapshots.py`, and `push-to-dialectic.py` are invoked as subprocess calls from `run-all.py`. This avoids coupling run-all to the internal APIs of those scripts and keeps each script independently testable.
- `DIALECTIC_ROOM_TOKEN` is present in the environment when a push is needed. If absent, `push-to-dialectic.py` exits 2 — run-all treats this as a book-level failure.
- `snapshots/` directory exists (already in the repo).
- Both active book JSONs require a one-time manual addition of `meta.dialecticRoomId` before end-to-end push works. This is a setup step, not a code change.

## Next Steps

→ `/ce:plan` for structured implementation planning
