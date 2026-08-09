# Iran/Hormuz — June 2026 Re-vintage (change record & rationale)

*Date: 2026-06-05. Covers commits `95d64ed → a03ee7e`. Source material:
[`hormuzClosureTrumpTrades.md`](../hormuzClosureTrumpTrades.md).*

## What this was

`hormuzClosureTrumpTrades.md` is an untracked, fact-checked June 3 2026 rewrite
of an external energy/Hormuz trading newsletter. It was prose sitting entirely
outside the graph engine — the *same thesis* as `books/iran-hormuz-graph.json`,
three months later and structurally evolved past what the book modelled. So it
served as both a **re-vintage prompt** (the book had drifted to a March vintage)
and a **feature-gap map** (rates, GDELT signal, private-credit contagion).

This work grounded the live book in that doc, engine-honestly, and pushed the
result to the live Dialectic room.

## What shipped (in priority order #5 → #1 → #2 → #3)

- **#5 Re-vintage to June 3.** `meta`/`asOf` → 2026-06-03, v1.1.0. `hormuz`
  context rewritten to current reality (~10 transits/day vs 95, UAE left OPEC,
  Qatar LNG force majeure). `brent` context corrected per the doc's Sec 1/6 —
  the mid-May peak (~$116) then ~15% retrace to ~$99, and **energy equities are
  no longer lagging** (XLE top holdings +23–28% YTD). `planting-miss` updated
  (window closed). Scenarios re-vintaged (resolution odds repriced up,
  0.10→0.18; closure 0.45→0.42; sum still 1.0). Cascade pointer advanced
  (transmission→ACTIVE, amplification→STARTING with a private-credit signpost).

- **#1 Two-stage kill-switch on the `hormuz` event.** The doc's core insight:
  a political reopening *headline* is not commercial reality, and must not
  collapse the thesis. Implemented as two TV bindings on the event state machine:
  - `hormuz-reopen-announced` → sets **`partial`** (a headline → amplification
    decays, thesis does NOT collapse)
  - `hormuz-commercial-reopen-confirmed` (new) → sets **`resolved`** only on
    carriers/insurers returning + transits recovering toward ~95/day — the real
    trade exit.

- **#2 GDELT watch node.** New `reopening-pressure` indicator fed by the dormant
  GDELT connector (`standardQuery: iran-hormuz-event`) — the doc's #1 watch
  signal (political-optimism-vs-commercial-reality gap). Watch-only by design.

- **#3 Rates leg.** Activated the dormant Treasury connector. New
  `rates-term-premium` price node (`brent → rates-term-premium`, 10Y feed) for
  the doc's Sec 4 cost-of-capital channel, plus a `growth-scare-yields-fall`
  reversal for the Sec 9 invalidation (yields fall if the disruption resolves
  into a growth scare).

Result: **19 nodes / 16 edges**, `em-stress` confluence preserved at **2.05**.

## The key design decision (engine-honest, not as first sketched)

Reading the actual eval semantics changed the design away from the obvious sketch:

- **Gate nodes always return `monitoring`** in Python eval — they never
  auto-fire. A `commercial-reopening` *gate* would have been inert.
- **Reversal eval ignores `gatedBy`** (only `current`/`threshold`/`closesRequired`
  matter). Adding `de-escalation.gatedBy` would have been silently no-op'd.
- **Indicator eval ignores `current`** — only incoming edge states drive it, so a
  GDELT-fed node's value can't drive its state.

So the two-stage reopening lives on the **event state machine** (`partial` vs
`resolved`), which the engine genuinely honours — not on an inert gate. The GDELT
node is a watch-only indicator (its `current` displays but doesn't propagate),
and the rates nodes are `price`/`reversal` types whose `current` the engine does
read.

## Verification

- Full suite **1113 passed, 2 skipped**; engine validate **0 warnings**.
- Scenario probabilities sum to 1.0; `closed-may` kept above the `5.0`
  load-bearing lifecycle predicate (`lifecycle_monitor.py:697`).
- HTML regenerates clean; TV adapter validates both two-stage bindings on the
  real book.
- Live-data probes: **Treasury 10Y = 4.47% pulls end-to-end**; GDELT functional
  but rate-limited; FRED/EIA gated on API keys.

Committed in two clean layers so each diff is self-contained: cockpit WIP
(`95d64ed`) first, then the re-vintage (`337b74b`), the source doc (`56f3e3a`),
and the published snapshot (`a03ee7e`).

## What's live in the room — and caveats

Pushed to Dialectic room `56ba2f1e` (`memory_id 7f4f22f0-f299-4dda-a505-1dbe76d80373`).
Two honest gaps in what's live:

- `reopening-pressure` (GDELT) landed **valueless** — GDELT was rate-limited
  through every attempt. Its threshold calibration is still a TODO.
- FRED/EIA nodes show **book values, not live** — no API keys in the run env.
  Only Yahoo prices + the Treasury 10Y are live-refreshed.

## Notable signal

`closed-may` netImpact compressed **14.4 → 5.4** — not a bug. netImpact is
computed from *state transitions* relative to the base, and the June base has
already progressed (`planting-miss` fired, oil cascade fired), so the
"prolonged closure" scenario adds less *marginal* upside than in March. It still
clears the 5.0 gate, but the margin is thin: the prolonged-closure trade has
less left in it.

## Follow-ups

- One clean GDELT fetch → calibrate `reopening-pressure` and promote it from
  watch-only to a firing constraint.
- Set `FRED_API_KEY` / `EIA_API_KEY` and re-push for a fully-live snapshot.
- **Big bet (separate session):** the private-credit → private-equity contagion
  (doc Sec 8) as net-new nodes inside `ai-capex-unwind-graph.json` + a cross-book
  link to this book's `em-stress`, with the QQQ bear-put-spread as the repo's
  first deliberate cross-book hedge.
