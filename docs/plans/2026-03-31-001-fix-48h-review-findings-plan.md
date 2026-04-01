---
title: "fix: Resolve critical, high, and medium findings from 48-hour commit review"
type: fix
status: completed
date: 2026-03-31
deepened: 2026-03-31
---

# fix: Resolve Critical, High, and Medium Findings from 48-Hour Commit Review

## Overview

A 7-agent compound engineering review of all commits in the last 48 hours surfaced 3 critical, 6 high, and 6 medium findings across correctness, security, reliability, testing, maintainability, performance, and pattern consistency. This plan addresses the critical and high findings plus select medium items that are low-effort/high-value. Structural refactors (god-file extraction, parallel Polymarket fetch) are explicitly deferred.

## Problem Frame

The trading desk engine shipped a large body of new code in 48 hours: Polymarket fetcher, E2E validation harness, Trump tariffs thesis, snapshot export, diff detection, and Dialectic bridge. The review found:

- **C1:** Python `eval_node_state` ignores `closesRequired` on price/reversal nodes — fires immediately while the browser JS correctly gates on daily close count. Exported snapshots disagree with the live dashboard.
- **C2:** `fetch_prices` prints status to stdout, corrupting JSON when piped via `--export-state -`.
- **C3:** Zero HTML escaping on config values injected into generated HTML — stored XSS in both `thesisgraph.py` and `bookgen.py`.
- **H1-H3:** Non-atomic config write, no retry on Dialectic push, unguarded KeyError in Yahoo result parsing.
- **H4:** Mock server snapshot schema missing `"title"` key — diverges from E2E tests and `export_state`.
- **H5:** Zero unit tests for the 8-branch `eval_node_state` propagation logic.
- **H6:** `test_push.py` uses `unittest.TestCase` while all other test files use pytest.
- **M1:** `eval_scenario` recomputes `propagate(cfg)` redundantly per scenario (6-7× when 1 suffices).
- **M5:** Python-side Yahoo Finance fetch routes through allorigins.win CORS proxy unnecessarily — exposes symbol lists to third party.

## Requirements Trace

- R1. Python and JS `eval_node_state` must agree on state for nodes with `closesRequired` thresholds
- R2. `--fetch --export-state -` must produce valid JSON on stdout (no interleaved status lines)
- R3. All user-sourced text in generated HTML must be escaped to prevent XSS
- R4. Config file writes must be atomic (crash-safe)
- R5. Dialectic push must retry on transient HTTP failures (5xx, timeout, connection error)
- R6. Yahoo Finance result parsing must not crash on malformed items
- R7. Mock server, E2E tests, and export tests must agree on the snapshot schema
- R8. `eval_node_state` must have direct unit tests for all 8 node types
- R9. All test files must use pytest (no unittest.TestCase)
- R10. `eval_scenario` must not recompute base states redundantly
- R11. Python-side Yahoo fetch must not route through allorigins.win CORS proxy

## Scope Boundaries

- **In scope:** All critical (C1-C3), high (H1-H6), and select medium (M1, M5) findings
- **Deferred:** God-file extraction (M3) — large refactor, plan separately. Parallel Polymarket fetch (M4) — optimization. diff-snapshots field coverage (M6) — behavior change. Dead exception classes (L1) — cleanup. Gate dead code (L2), exit code convention (L3), fixture deduplication (L4), pipeline functions (L5), retries naming (L6), node_map rebuild (L7) — low-priority cleanup.

## Context & Research

### Relevant Code and Patterns

- `fetch_polymarket()` at `thesisgraph.py:688-708` correctly uses `file=sys.stderr` for all prints — this is the pattern `fetch_prices` should follow
- JS `evalNodeState` at `thesisgraph.py:1255-1272` has the correct `closesRequired` implementation for price nodes to port to Python
- JS reversal handler at `thesisgraph.py:1318-1331` has the correct `closesRequired` check for reversal nodes
- `polymarket.py` retry loop at lines 281-290 demonstrates the project's retry pattern
- `test_diff.py`, `test_polymarket.py`, `test_export.py` use pytest — this is the canonical test style
- `e2e_test.py:43-47` and `test_export.py:29-33` both include `"title"` in their snapshot key sets — mock_dialectic.py:29 is the outlier

### Institutional Learnings

- Project convention: zero external Python dependencies (stdlib only)
- All prints in pipeline-capable functions should use `file=sys.stderr` when stdout may carry structured data
- The `html` module (`html.escape()`) is stdlib and already available

## Key Technical Decisions

- **closesRequired in Python:** Port the JS logic but return `"approaching"` (not `"fired"`) when `closesRequired` is set and close data is unavailable. The Python evaluator runs at generation time without access to the browser's close log. This matches the JS behavior: without sufficient closes, the node is `"approaching"`, not `"fired"`. The JS comment at line 1259 confirms this was intentional design.
- **XSS fix scope:** Apply `html.escape()` to the 3 server-side template values (`__TITLE__`, `__CLAIM__`, `__AS_OF__`). For DOM-side innerHTML injection, add a single `esc()` JS helper function at the top of `JS_LOGIC` and apply it to all user-data interpolations in `renderNodeDetail`, `renderJournal`, and related functions. This is a targeted fix, not a framework migration.
- **Atomic write pattern:** Write to `path.tmp` in the same directory, then `os.replace()` over the original. `os.replace()` is atomic on POSIX and available in stdlib.
- **Retry on Dialectic push:** 3 attempts with exponential backoff (1s, 2s), retry only on 5xx status codes, `URLError`, `TimeoutError`, and `OSError`. 4xx errors are not retried.
- **allorigins.win removal (Python only):** Python is not subject to CORS. Call `query1.finance.yahoo.com` directly using the existing `urllib.request` pattern. The browser-side fetch still needs the proxy — that is unchanged.

## Open Questions

### Resolved During Planning

- **Should closesRequired default to None or 0 in Python?** → None. A missing `closesRequired` means "fire immediately on threshold breach" (matching current behavior and JS logic). Only when the field is present and > 0 does gating apply.
- **Should we deduplicate the snapshot key constants?** → Yes, but minimal: add `"title"` to `mock_dialectic.py` and rename to match `REQUIRED_SNAPSHOT_KEYS`. Full deduplication into a shared module is deferred (L4).

### Deferred to Implementation

- Exact JS lines where `esc()` needs to be applied in innerHTML — requires reading through the ~800-line JS string to identify all interpolation sites
- Whether the `html.escape()` call needs `quote=True` for attribute contexts — depends on how `__CLAIM__` is used in the template (confirmed: it appears in a `content="__CLAIM__"` attribute, so `quote=True` is needed)

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```
Phase 1: Critical Fixes (C1, C2, C3) — blocks pipeline correctness
  ├── Unit 1: fetch_prices stderr (C2) — no dependencies, 2-line fix
  ├── Unit 2: closesRequired in Python (C1) — no dependencies
  └── Unit 3: XSS escaping (C3) — no dependencies

Phase 2: Reliability Hardening (H1, H2, H3, H4) — blocks production use
  ├── Unit 4: Atomic config write (H1) — no dependencies
  ├── Unit 5: Dialectic push retry (H2) — no dependencies
  ├── Unit 6: Yahoo KeyError guard (H3) — depends on Unit 12*
  └── Unit 7: Mock schema alignment (H4) — no dependencies

  * Units 6 and 12 have a write-write conflict on fetch_prices (lines 575-610).
    Unit 12 removes the allorigins.win envelope["contents"] layer that Unit 6
    proposes to guard. Execute Unit 12 first, then scope Unit 6 to the remaining
    item["symbol"] guard only.

Phase 3: Test Coverage (H5) — blocks confidence in Phase 1-2 changes
  ├── Unit 8: eval_node_state unit tests (H5) — depends on Unit 2
  └── Unit 9: Pipeline integration tests — depends on Units 1, 2

Phase 4: Cleanup (H6, M1, M5) — improves maintainability
  ├── Unit 10: test_push.py pytest migration (H6) — no dependencies
  ├── Unit 11: eval_scenario base_states pass-through (M1) — no dependencies
  └── Unit 12: Remove allorigins.win from Python fetch (M5) — no dependencies
```

Units within each phase are independent unless noted. Cross-phase dependencies and the Unit 6/12 write-write conflict are noted in the diagram.

## Implementation Units

### Phase 1: Critical Fixes

- [x] **Unit 1: Fix stdout contamination in fetch_prices (C2)**

**Goal:** Ensure `--fetch --export-state -` produces valid JSON on stdout.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Modify: `tools/thesis-graph/thesisgraph.py` — `fetch_prices` function (~line 616, 629, 638)

**Approach:**
- Change `print(...)` to `print(..., file=sys.stderr)` on lines 616 and 629 (inside `fetch_prices()`) and line 638 (inside `update_config_file()`)
- Follow the pattern already established by `fetch_polymarket()` at lines 688-708
- Note: `update_config_file` (line 638) is only reached via `--update-config`, not `--export-state`, but should be fixed for consistency

**Patterns to follow:**
- `fetch_polymarket()` at `thesisgraph.py:688-708` — every print uses `file=sys.stderr`

**Test scenarios:**
- Happy path: Run `thesisgraph.py config.json --fetch --export-state -` and verify stdout is valid JSON (parseable by `json.loads`)
- Happy path: Verify price status lines appear on stderr, not stdout

**Verification:**
- `python3 thesisgraph.py books/iran-hormuz-graph.json --export-state - 2>/dev/null | python3 -c "import sys,json; json.load(sys.stdin)"` succeeds after `--fetch` is added

---

- [x] **Unit 2: Port closesRequired gating to Python eval_node_state (C1)**

**Goal:** Python price and reversal node evaluation respects `closesRequired` field, returning `"approaching"` instead of `"fired"` when the field is present, since Python has no close log.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tools/thesis-graph/thesisgraph.py` — `eval_node_state` function, price branch (~line 193-196) and reversal branch (~line 272-277)

**Approach:**
- **Price nodes (line 193-196):** After `current >= lvl` check, inspect `th.get("closesRequired")`. If present and > 0, return `"approaching"` instead of `"fired"`. Without a close log, Python cannot confirm the required number of closes.
- **Reversal nodes (line 272-277):** After `current <= threshold` check, inspect `node.get("closesRequired")`. If present and > 0, return `"approaching"` instead of `"fired"`.
- This aligns with the JS behavior: when `closesRequired` is set but insufficient closes are recorded, JS returns `"approaching"`. At generation time with no close log, zero closes are recorded, so `"approaching"` is always correct.
- Add a comment explaining the design: Python evaluates at generation time without browser close log state, so `closesRequired` nodes start as `"approaching"` and only transition to `"fired"` in the browser when sufficient closes are recorded.

**Patterns to follow:**
- JS price handler at `thesisgraph.py:1260-1268`
- JS reversal handler at `thesisgraph.py:1322-1326`

**Test scenarios:**
- Happy path: Price node with `current >= threshold` and no `closesRequired` → returns `"fired"` (unchanged behavior)
- Happy path: Price node with `current >= threshold` and `closesRequired: 3` → returns `"approaching"` (new gating behavior)
- Edge case: Price node with `closesRequired: 0` → treated as no gating, returns `"fired"`
- Edge case: Price node with `closesRequired: null` or field absent → returns `"fired"` (unchanged)
- Happy path: Reversal node with `current <= threshold` and no `closesRequired` → returns `"fired"` (unchanged)
- Happy path: Reversal node with `current <= threshold` and `closesRequired: 5` → returns `"approaching"` (new gating)
- Edge case: Reversal node with `closesRequired: 0` → returns `"fired"`
- Integration: Full pipeline `--export-state` with iran-hormuz config — brent node (which has `closesRequired: 3`) should export as `"approaching"` or `"stable"`, never `"fired"` at generation time

**Verification:**
- `eval_node_state` returns `"approaching"` for any threshold with `closesRequired > 0` regardless of current exceeding the level
- Export snapshot for iran-hormuz no longer shows brent as `"fired"` at generation time when `closesRequired` thresholds exist

---

- [x] **Unit 3: Add XSS escaping to HTML generation (C3)**

**Goal:** Prevent stored XSS via JSON config values in generated HTML. Covers both server-side template substitution and client-side innerHTML injection.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Modify: `tools/thesis-graph/thesisgraph.py` — `generate_html` function (~line 996-999) and `JS_LOGIC` string constant
- Modify: `tools/commodity-book/bookgen.py` — `build_situation_html`, `build_provenance_html`, and template substitution

**Approach:**
- **Server-side (thesisgraph.py):** Import `html` module. Apply `html.escape(value, quote=True)` to `__TITLE__`, `__CLAIM__`, and `__AS_OF__` before substitution. `quote=True` is needed because `__CLAIM__` appears inside a `content="..."` attribute.
- **Server-side (bookgen.py):** Same treatment for `__TITLE__`, `__CLAIM__`, `__SUBTITLE__`, and all `build_situation_html`/`build_provenance_html` interpolations.
- **Client-side JS:** Add an `esc()` helper function at the top of `JS_LOGIC` that replaces `&`, `<`, `>`, `"`, `'` with HTML entities. Apply `esc()` to every user-data interpolation in `renderNodeDetail`, `renderJournal`, `renderCascade`, `renderScenarios`, `renderPortfolio`, `renderMarketBar`, and any other innerHTML assignment sites. Walk through all template literal interpolations in the JS string to identify injection points.
- **Estimation note:** The JS audit is the largest piece of this unit — ~40 interpolation sites across ~400 lines of minified JS embedded in a Python string. Each site requires judgment about whether the value is user-sourced (escape) or code-generated (leave). Budget this unit as 3-5× the effort of other units.
- Do not change data serialization (`json.dumps` for `NODES`, `SCENARIOS`, etc.) — those are JS object literals, not HTML text.

**Patterns to follow:**
- Python stdlib `html.escape()` — no external dependencies needed
- Standard JS HTML entity escaping pattern

**Test scenarios:**
- Happy path: Config with `title: "Normal Title"` → HTML contains `Normal Title` unchanged
- Error path: Config with `title: "</title><script>alert(1)</script>"` → HTML contains escaped entities, no executable script tag
- Error path: Config with `claim: "x\" onclick=\"alert(1)"` → attribute-context injection is escaped
- Edge case: Config with `context: "<img src=x onerror=alert(1)>"` in a node → JS `esc()` prevents DOM XSS when node detail is rendered
- Happy path: bookgen.py with normal situation text → HTML renders correctly
- Error path: bookgen.py with `<script>` in situation section text → escaped in output

**Verification:**
- Generated HTML files can be searched for raw `<script>` tags from config — none present
- Browser opening the generated HTML with a crafted config does not execute injected scripts

---

### Phase 2: Reliability Hardening

- [x] **Unit 4: Atomic config file write (H1)**

**Goal:** Prevent config file corruption if the process is killed mid-write.

**Requirements:** R4

**Dependencies:** None

**Files:**
- Modify: `tools/thesis-graph/thesisgraph.py` — `update_config_file` function (~line 633-638)

**Approach:**
- Write to `config_path + ".tmp"` instead of directly to `config_path`
- After `json.dump` completes, `f.flush()` and `os.fsync(f.fileno())` to ensure data is on disk
- Use `os.replace(tmp_path, config_path)` for atomic rename (POSIX atomic, Windows atomic on same volume)
- Wrap in try/except to clean up the `.tmp` file on failure

**Patterns to follow:**
- Standard atomic-write pattern in Python stdlib

**Test scenarios:**
- Happy path: Config write succeeds — original file contains new data, no `.tmp` file remains
- Error path: Simulated write failure (e.g., mock `json.dump` to raise) — original file is unchanged, `.tmp` file is cleaned up
- Edge case: Config path with spaces or special characters — `os.replace` handles correctly

**Verification:**
- `update_config_file` never truncates the original file directly
- After successful write, no `.tmp` file remains on disk

---

- [x] **Unit 5: Add retry with backoff to Dialectic push (H2)**

**Goal:** Transient Dialectic server errors don't kill the pipeline.

**Requirements:** R5

**Dependencies:** None

**Files:**
- Modify: `tools/bridge/push-to-dialectic.py` — `push_snapshot` function (~line 116-144)
- Modify: `tools/bridge/test_push.py` — add retry tests

**Approach:**
- Wrap the `urlopen` call in a retry loop: 3 total attempts, exponential backoff (1s, 2s)
- Retry on: HTTP 5xx status (via `HTTPError`), `URLError`, `TimeoutError`, `OSError`
- Do not retry on: HTTP 4xx (client error, not transient)
- Print retry attempts to stderr with attempt number and wait duration
- Keep the existing exit code semantics (0 = success, 1 = HTTP error after retries, 2 = config/connection error)

**Patterns to follow:**
- Retry logic in `polymarket.py:281-290` — similar loop structure with attempt tracking

**Test scenarios:**
- Happy path: First attempt succeeds → normal exit 0
- Happy path: First attempt returns 503, second succeeds → exit 0 after retry
- Error path: All 3 attempts return 502 → exit 1 after exhausting retries
- Error path: First attempt returns 400 (client error) → exit 1 immediately, no retry
- Error path: Connection refused on all attempts → exit 2 after exhausting retries
- Edge case: Timeout on first attempt, success on second → exit 0

**Verification:**
- `push_snapshot` retries exactly the expected number of times on 5xx errors
- 4xx errors are not retried
- Exit codes remain consistent with existing convention

---

- [x] **Unit 6: Guard against KeyError in Yahoo Finance result parsing (H3)**

**Goal:** A single malformed item in the Yahoo Finance response doesn't crash the entire price update.

**Requirements:** R6

**Dependencies:** Unit 12 (allorigins.win removal). Units 6 and 12 both modify `fetch_prices` in the same region (lines 575-610). Unit 12 removes the `envelope["contents"]` layer, so the `.get("contents")` guard proposed here becomes unnecessary after Unit 12 lands. Execute Unit 12 first, then scope this unit to the remaining `item["symbol"]` guard only.

**Files:**
- Modify: `tools/thesis-graph/thesisgraph.py` — `fetch_prices` result processing loop (~line 603-628)

**Approach:**
- Change `item["symbol"]` (line 604) to `item.get("symbol")`
- Skip items where symbol is None with `continue`
- If Unit 12 has not yet landed: also guard `envelope["contents"]` (line 583) with `.get()`. If Unit 12 has landed, the envelope unwrap is gone and this bullet is moot.

**Patterns to follow:**
- Adjacent lines 605-606 already use `.get()` for other fields

**Test scenarios:**
- Happy path: All items have `"symbol"` key → prices update normally
- Error path: One item missing `"symbol"` → that item is skipped, other items in the batch still update
- Edge case: Empty results array → function returns gracefully with count=0

**Verification:**
- No unhandled `KeyError` can propagate from the result processing loop
- Partial fetch failures don't lose successfully fetched prices from the same batch

---

- [x] **Unit 7: Align mock server snapshot schema (H4)**

**Goal:** Mock Dialectic server validates the same schema as the E2E tests and export function.

**Requirements:** R7

**Dependencies:** None

**Files:**
- Modify: `tools/validation/mock_dialectic.py` — `REQUIRED_SNAPSHOT_KEYS` (~line 29)

**Approach:**
- Add `"title"` to `REQUIRED_SNAPSHOT_KEYS` set to match `export_state` output and E2E test expectations
- Final set: `{"v", "timestamp", "title", "nodeStates", "confluenceScores", "cascadePhase", "countdowns", "marketSnapshot", "scenarioImpacts", "portfolioSummary"}`

**Patterns to follow:**
- `test_export.py:29-33` REQUIRED_KEYS and `e2e_test.py:43-47` SNAPSHOT_KEYS — both include `"title"`

**Test scenarios:**
- Happy path: Snapshot with all 10 keys → accepted with 200
- Error path: Snapshot missing `"title"` → rejected with 400
- Happy path: Existing E2E tests still pass with the stricter validation

**Verification:**
- `REQUIRED_SNAPSHOT_KEYS` in mock_dialectic.py matches the key sets in test_export.py and e2e_test.py
- Full test suite passes: `python3 -m pytest tools/ -q`

---

### Phase 3: Test Coverage

- [x] **Unit 8: Unit tests for eval_node_state (H5)**

**Goal:** Direct unit tests for all 8 node type branches in `eval_node_state`, isolated from the full propagation pipeline.

**Requirements:** R8

**Dependencies:** Unit 2 (closesRequired changes must be in place first)

**Files:**
- Modify: `tools/thesis-graph/test_export.py` — add new test class/section for eval_node_state

**Approach:**
- Import `eval_node_state` directly (it takes a node dict, edges list, and states dict)
- Build minimal node/edge fixtures for each node type rather than loading the full iran-hormuz config
- Test each branch independently, including the new closesRequired gating from Unit 2

**Test scenarios:**
- **Event:** active state with matching condition → `"fired"`. No condition match → `"monitoring"`
- **Price:** current >= threshold, no closesRequired → `"fired"`. current >= threshold, closesRequired > 0 → `"approaching"`. current within 5% of threshold → `"approaching"`. current well below → `"stable"`. No current → `"monitoring"`
- **Indicator:** all upstream fired → `"fired"`. mixed fired/approaching → `"approaching"`. none fired → `"stable"`. No incoming edges → `"monitoring"`
- **Deadline:** date in past → `"fired"`. date within 14 days, conditions met → `"approaching"`. date within 14 days, no conditions → `"approaching"`. date far → `"stable"`
- **Gate:** always returns `"monitoring"` regardless of inputs
- **Constraint:** current > threshold → `"constrained"`. current <= threshold → `"stable"`. No data → `"monitoring"`
- **Conditional:** gatedBy node not fired → `"gated"`. constrainedBy node constrained → `"constrained"`. Both clear → falls through to normal evaluation
- **Reversal:** current <= threshold, no closesRequired → `"fired"`. current <= threshold, closesRequired > 0 → `"approaching"`. current near threshold → `"approaching"`. current far above → `"stable"`

**Verification:**
- Every node type branch in `eval_node_state` is exercised by at least one direct test
- Tests pass with the closesRequired changes from Unit 2

---

- [x] **Unit 9: Pipeline integration tests for critical fixes**

**Goal:** Integration-level tests that validate C1 and C2 fixes through the actual pipeline.

**Requirements:** R1, R2

**Dependencies:** Units 1, 2

**Files:**
- Modify: `tools/thesis-graph/test_export.py` or `tools/validation/e2e_test.py` — add integration test cases

**Approach:**
- Add a test that runs `thesisgraph.py --fetch --export-state -` as a subprocess and verifies stdout is valid JSON (catches C2 regression)
- Add a test that verifies the exported snapshot does not mark nodes with `closesRequired` as `"fired"` (catches C1 regression)
- These are subprocess-level tests matching the E2E test pattern already in `e2e_test.py`

**Test scenarios:**
- Integration: `--export-state -` output is valid JSON (no stdout contamination from fetch status)
- Integration: Snapshot `nodeStates` for nodes with `closesRequired` thresholds → never `"fired"` at generation time
- Integration: `eval_scenario` impact values are numeric (not None or missing) — basic smoke test for the untested impact math

**Verification:**
- New tests pass and would have caught both C1 and C2 before the review

---

### Phase 4: Cleanup

- [x] **Unit 10: Migrate test_push.py from unittest to pytest (H6)**

**Goal:** Consistent test framework across all 5 test files.

**Requirements:** R9

**Dependencies:** None (but Unit 5 adds retry tests — coordinate if executing in parallel)

**Files:**
- Modify: `tools/bridge/test_push.py` — rewrite from unittest.TestCase to pytest

**Approach:**
- Replace `self.assertEqual/assertIn/assertRaises` with bare `assert` and `pytest.raises`
- Replace `setUpClass/tearDownClass` with `@pytest.fixture(scope="module")` for server lifecycle (matching `e2e_test.py` pattern)
- Replace manual tempfile management with `tmp_path` fixture
- Remove the dead `tmp_path=None` parameter on `test_load_from_file`
- Replace `importlib.import_module` with direct import if possible, or keep for the hyphenated filename

**Patterns to follow:**
- `e2e_test.py` — module-scoped fixture for mock server, `tmp_path` for temp files, bare assertions

**Test scenarios:**
- Happy path: All existing test_push tests pass after migration
- Edge case: Module-scoped server fixture starts/stops correctly
- Edge case: tmp_path cleanup works for file-based tests

**Verification:**
- `python3 -m pytest tools/bridge/test_push.py -q` passes with the same test count
- No `unittest` imports remain in the file

---

- [x] **Unit 11: Pass base_states to eval_scenario (M1)**

**Goal:** Eliminate redundant `propagate(cfg)` calls — from 6-7× to 1× per invocation.

**Requirements:** R10

**Dependencies:** None

**Files:**
- Modify: `tools/thesis-graph/thesisgraph.py` — `eval_scenario` signature (~line 345) and caller in `main()` (~line 2268)

**Approach:**
- Add `base_states=None` parameter to `eval_scenario`
- When provided, use it instead of calling `propagate(cfg)` at line 370
- In `main()` at line 2268, pass the already-computed `states` variable (the only call site — `generate_html` does not call `eval_scenario`)

**Patterns to follow:**
- Standard "compute once, pass through" pattern

**Test scenarios:**
- Happy path: eval_scenario with pre-computed base_states produces identical results to current behavior
- Happy path: eval_scenario with base_states=None (default) still computes its own — backward compatible
- Integration: --export-state output is identical before and after this change

**Verification:**
- `propagate(cfg)` is called exactly once in the main pipeline path (plus once per scenario for the overridden config, which is unavoidable)
- All existing tests pass

---

- [x] **Unit 12: Remove allorigins.win proxy from Python-side Yahoo fetch (M5)**

**Goal:** Python-side price fetch calls Yahoo Finance directly, eliminating the third-party proxy from the generation-time pipeline.

**Requirements:** R11

**Dependencies:** None

**Files:**
- Modify: `tools/thesis-graph/thesisgraph.py` — `fetch_prices` function (~line 575-583)

**Approach:**
- Replace the proxy URL construction (`https://api.allorigins.win/get?url=...`) with a direct call to the Yahoo Finance spark API (`https://query1.finance.yahoo.com/v7/finance/spark?...`)
- Python is not subject to CORS restrictions — the proxy was only needed for browser-side fetch
- Keep the browser-side JS fetch unchanged (it still needs the CORS proxy)
- Adjust the response parsing to handle the direct Yahoo response shape instead of unwrapping the allorigins.win `{"contents": "..."}` envelope
- Keep the existing retry/timeout logic intact

**Patterns to follow:**
- Existing `urllib.request` usage in the same function and in `polymarket.py`

**Test scenarios:**
- Happy path: Price fetch works against real Yahoo Finance API (manual validation with `--fetch --dry-run`)
- Error path: Yahoo returns non-200 → existing retry/error handling still works
- Edge case: Symbols with special characters (futures, FX pairs) are properly URL-encoded
- Integration: Generated HTML still shows correct prices after removing the proxy from the Python path

**Verification:**
- No reference to `allorigins.win` remains in the Python code path
- Browser-side JS fetch still uses the proxy (unchanged)
- `--fetch` produces the same price updates as before

---

## System-Wide Impact

- **Interaction graph:** Unit 2 (closesRequired) changes `eval_node_state` output, which flows through `propagate` → `export_state` → snapshot JSON → `diff-snapshots` → `push-to-dialectic`. Nodes previously marked `"fired"` at generation time may now be `"approaching"`, which affects scenario impact calculations and downstream Dialectic state.
- **Error propagation:** Unit 5 (retry) and Unit 6 (KeyError guard) change how errors travel through the fetch and push pipelines. Transient failures that previously killed the pipeline will now be retried or skipped.
- **State lifecycle risks:** Unit 2 changes the initial state of `closesRequired` nodes in exported snapshots. If a Dialectic room has historical snapshots showing these nodes as `"fired"`, the next push will show them as `"approaching"` — the diff tool will flag this as a state transition.
- **API surface parity:** The browser-side JS `evalNodeState` already handles `closesRequired` correctly. After Unit 2, Python and JS agree. The browser-side Yahoo fetch still uses allorigins.win after Unit 12 — this is intentional (CORS constraint).
- **Unchanged invariants:** The snapshot schema shape, the CLI flag interface, the thesis graph JSON config format, and the Dialectic HTTP API contract are all unchanged.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unit 2 changes exported state for existing theses — Dialectic rooms may see state "regressions" | Document the change. The previous behavior was a bug — nodes were incorrectly firing. This is a correctness fix, not a regression. |
| Unit 3 (XSS escaping) could break rendering if escape is applied to JS object literals | Only escape the 3 human-readable template values and innerHTML interpolations. Do not escape `json.dumps` output used for JS constants. |
| Unit 12 (proxy removal) depends on Yahoo Finance allowing direct requests from servers | Yahoo's spark API does not require API keys and works for server-side requests. If it starts blocking, the proxy can be reinstated. Test with `--fetch --dry-run` before merging. Add HTTP status logging to the error path so users can distinguish a Yahoo 403 block from a network failure. |
| Units 6 and 12 both modify `fetch_prices` — write-write conflict | Execute Unit 12 first (removes proxy envelope). Then scope Unit 6 to the remaining `item["symbol"]` guard only. |
| Unit 10 (pytest migration) could break CI if test discovery changes | Run full suite before and after. Verify identical test count. |
| Unit 7 (mock schema) tightens validation — may reveal existing test issues | Run full suite after the change. Any new failures indicate tests were passing with invalid snapshots, which is a bug being surfaced. |

## Sources & References

- Compound engineering review report: 7-agent review completed 2026-03-31
- INTEGRATION.md: Dialectic snapshot schema specification
- JS evalNodeState: `thesisgraph.py:1243-1333`
- Python eval_node_state: `thesisgraph.py:167-283`
- Python fetch_prices: `thesisgraph.py:539-630`
- Python fetch_polymarket (stderr pattern): `thesisgraph.py:641-710`
- Push to Dialectic: `tools/bridge/push-to-dialectic.py:116-144`
- Mock server: `tools/validation/mock_dialectic.py:29-33`
