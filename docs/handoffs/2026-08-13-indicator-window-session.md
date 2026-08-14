# Handoff — the indicator-window session (2026-08-13 evening)

Started as a library evaluation, ended as a production fix. One commit,
deployed, live-verified in dialectic's own tables. This records the verdict
that should not be re-litigated, what shipped, and the operational facts that
cost time to establish.

## The question asked

"How well would `facioquo/stock-indicators-python` be implemented for use
within dialectic?"

## The verdict — don't adopt (do not re-litigate)

Four independent blockers, each verified rather than assumed:

1. **It is a .NET library wearing a Python hat.** `stock-indicators` 1.3.5 is
   pythonnet over `Skender.Stock.Indicators` and needs .NET SDK 8+ installed
   system-wide. This host has no dotnet anywhere — `/usr/bin`, `/usr/lib`,
   `/opt`, `~/.dotnet` all absent, 0 dpkg matches. It would load a CLR
   in-process inside `tradingdesk.service`'s asyncio worker, and that unit
   runs its git working tree, so a bad import is a restart-time outage.
   Upstream claims Windows/macOS testing only.
2. **`trading/tools/` is stdlib-only by written convention.** It would be the
   first dependency and the heaviest available.
3. **We already ship the capability.** `tools/data_fetch/derived_indicators.py`
   — Wilder RSI/ATR/SMA, `curveSpread`, `consecutive_closes_above` — live and
   computing hourly across all five books.
4. **It fights the architecture.** The `overlay: true` tripwire exists because
   red-team finding F3 ruled RSI-as-cause a category error. Dropping in 200+
   indicators is exactly the pressure that tripwire resists. The engine's
   scarcity is causal nodes with independent feeds, not indicator count.

**If it is ever reconsidered**, the seam is genuinely clean and worth knowing:
one `elif` in `compute_node_indicators`'s `kind` dispatch, with
`validate_derived_indicator_spec`'s `kind` whitelist as the gate. Nothing else
moves — `thesisgraph.py`, the v:2 `tvIndicators` block, `models.py:521` and
`prompts.py:491` all stay put. The cost is an adapter: the library wants
`Quote` objects (datetime + decimal OHLCV); `cfg["_ohlcv"]` is parallel
`closes`/`highs`/`lows` lists.

**The lazy alternative that was chosen instead:** ~15 lines per indicator in
the existing pure-function module, same tripwire, zero deps. pandas 2.3 /
numpy 2.0 are already installed if vectorized breadth is ever needed.

## What the evaluation found — and what shipped

`f9d125c` — *fix(trading): size the OHLCV window from the specs*

`ai-capex-unwind-graph.json` declared `sma200` on `semis-breakdown`. It was
**not** in the live snapshot. `fetch_ohlcv_for_derived` hardcoded
`range=3mo`, which Yahoo answers with **63 daily bars** (measured against
SOXX, 2026-08-14). `sma()` returns `None` below period,
`compute_node_indicators` skips `None`, and the key was dropped without a
word. It had been silently failing since the spec was written.

No library fixes this — the ceiling was the fetch window, not the math.

What landed:

- **`bars_required()` / `expected_key()`** in `derived_indicators.py`, pure
  spec introspection. `expected_key` is now the *single source* of the
  `tvIndicators` key name, used by both the writer and the new miss-detector,
  so the check cannot drift from the code it guards.
- **Per-symbol window sizing.** The smallest Yahoo `range` covering that
  symbol's longest declared period. Yahoo's `range` is discrete, not a bar
  count — `_YAHOO_RANGE_BARS` maps the ones we use.
- **Declared-but-not-produced is now loud**:
  `derived_indicators: semis-breakdown.sma200 not computed — SOXX needs 200
  closes, have 40`. Range selection kills under-fetch for known ranges, but
  thin/newly-listed symbols still under-deliver and ATR still needs
  highs/lows Yahoo may omit.
- **Close-event volume bounded.** Capped at the recent 90 bars and emitted
  once per *symbol* rather than once per *spec*. Volume is
  per-close-per-threshold, so a wider window would have multiplied the
  `close_observations` upserts every cycle. The per-spec emission was a
  pre-existing 3x amplification; live count went **270 → 90**, below the old
  63-bar baseline.

## Why per-symbol, and not a global window bump

Wilder smoothing has a long memory tail: the same RSI14 over 63 vs 251 bars
returns a different number. A blanket `range=1y` would have moved published
values on every symbol in every book. Smallest-covering-range means symbols
that never needed history keep the exact values they had.

Verified empirically, not argued: `tsm-utilization` still reads
`rsi14 56.55 / sma50 425.37` — byte-identical to the pre-change production
snapshot. Only SMH, which needed the longer window, moved: `rsi14
54.37 → 54.51`, `atr14 22.97 → 22.90`. Closer to what the chart renders, and
non-causal either way under the overlay tripwire.

## Operational facts (do not rediscover)

- **`trading/snapshots/*-latest.json` is written by `run-all.py`, NOT by the
  coordinator.** The coordinator pushes straight to dialectic. After a
  coordinator-path change, reading that file shows stale data and looks
  exactly like the fix failing. It is the wrong place to verify.
- **The right place** is dialectic's own table:
  ```bash
  psql -U root -d dialectic -tAc "
    select jsonb_pretty(trading_config->'tvIndicators'->'semis-breakdown')
    from rooms where id='6805ad0f-0d72-441d-ac1c-2cd9dc63bca3';"
  ```
  (ai-capex-unwind room. `prompts.py:491` reads the same path — this is
  literally what the LLM sees.)
- **`curl /api/health` immediately after `systemctl restart tradingdesk`
  returns empty.** That is the startup window, not a failure. Poll it; at
  ~7s it answered 200. Confirm identity from the response shape
  (`books_loaded`, `last_snapshots`), not just the status code.
- **Yahoo `range=3mo` → 63 daily bars.** Measured, not assumed. `1y` → 251.
- **Longest `closesRequired` in any book is 5** (japan-rate-shock `jgb-10y`),
  not 3 — checked before the `_CLOSE_EVENT_WINDOW = 90` comment was written.
- The journal carries a clean before/after ten seconds apart:
  `22:19:18 [766516] ohlcv SMH: 63 closes` (old PID) →
  `22:19:28 [2269428] ohlcv SMH: 251 closes (range=1y, need 200)`. The
  `(range=…, need …)` suffix only the new code emits, so it doubles as
  deploy-identity proof.

## Verification performed

- **1430 passed, 3 skipped** — full trading suite.
- **Six mutations, all killed on their targeted assertion**: fixed 3mo window,
  cap removal, date-offset break after the tail slice, silenced miss-warning,
  off-by-one in `bars_required`, removed per-symbol dedup. Applied and
  reverted by targeted edit, never `git checkout` (the tree held other
  sessions' WIP).
- **Live probe** against a *copy* of the book in the scratchpad — no tracked
  book or snapshot touched.
- **Production confirmation**: `sma200: 460.89` in `rooms.trading_config`,
  stamped `03:19:29Z`, first cycle after restart.
- `ruff --select F821,F811,F841`: 5 F841 findings, all identical at HEAD —
  pre-existing, none in the changed hunks. Zero F821.

## What remains

- **`snapshots/*-latest.json` will not carry `sma200` until `run-all.py`
  next runs.** Dialectic already has it; the on-disk copies are the lagging
  artifact. Nothing is wrong.
- **No backfill.** Existing snapshots keep their `sma200`-less history. A
  backfill was deliberately skipped — say so if the history matters.
- **`f9d125c` is unpushed**, on `claude/release-3-deliberation`. A parallel
  session landed `5019e2b docs(dialectic): map human interaction surfaces` on
  top; mine is intact underneath.
- **The 5 pre-existing F841s** in `thesisgraph.py` / `derived_indicators.py`
  were left alone — out of scope, and unrelated to this path.
