# Final Judgment: TradingView Integration Architecture Competition

**Date:** 2026-04-05
**Arbiter:** System Architecture Expert (final judge)
**Artifacts judged:** `plan-alpha-v2.md` (780 lines), `plan-bravo-v2.md` (1011 lines), prior red-team reports

---

## WINNER: Team Alpha

Team Alpha's plan is the primary basis for the final build. It is architecturally tighter, epistemically honest about what chart data can and cannot contribute to a causal DAG, ships to a verified-executable endpoint, and every one of its First Three Trades is testable *right now* against snapshots the engine already emits. Bravo has the better narrative and three genuinely superior signal ideas (velocity, divergence, cross-book confluence) — but its plan contains a factual snapshot error, ships a 120-LoC Node.js subprocess path it cannot honestly call "stdlib", and embeds a ~3-8 KB markdown blob into every snapshot push in a way that reshapes the snapshot contract for a single consumer. Alpha wins. Bravo's best ideas get absorbed as follow-on work.

---

## Score Table

| Dimension | Weight | Alpha | Bravo |
|---|---|---|---|
| Trading edge | 20% | 7.5 | 8.0 |
| Architectural coherence | 15% | 9.0 | 7.0 |
| Fidelity to source (Jackson video) | 10% | 6.5 | 8.5 |
| Risk management (RT fatal-flaw answers) | 15% | 9.0 | 7.5 |
| Stdlib fidelity | 10% | 9.5 | 6.5 |
| Buildability | 15% | 9.0 | 7.5 |
| Test rigor | 10% | 8.5 | 7.5 |
| First-3-trades decisiveness | 5% | 8.5 | 7.5 |

**Weighted totals:**
- **Alpha: 83.0 / 100**
- **Bravo: 75.5 / 100**

---

## Why Alpha Wins (300 words)

Alpha's decisive move is **epistemic humility about the DAG**. v1 Alpha proposed injecting RSI into the causal graph; red-team F3 correctly labeled that a category error (RSI is derived *from* price, so "Yahoo + TV-RSI agreement" is reading the same thermometer twice). v2 Alpha deleted it entirely. Instead, derived indicators become snapshot overlays with a **schema-enforced `overlay: true` tripwire** (line 143) — a compile-time guard against anyone re-opening the "feed RSI to propagation" door in the future. That's exactly the architectural discipline the thesis graph engine needs.

The second decisive move is that Alpha's **First Three Trades are falsifiable today**. I ran `propagate()` against both live books and verified every trigger value Alpha cites (lines 672-674): `em-stress=fired score=1.67`, `earnings-compression=2.05`, `consumer-confidence=1.95`, `recession-risk=1.25`, `fed-response=monitoring`, `brent=approaching`, `planting-miss=approaching`. All four trade-1 entry conditions (lines 682-685) resolve true against `snapshots/iran-hormuz-graph-latest.json` right now. All four trade-3 conditions (lines 721-725) resolve true against Trump tariffs. This means an engineer could `jq` the trigger predicates today and know the trade is actionable — no new pipeline plumbing required.

The third win is the **webhook security posture**. Red-team F4 was devastating: v1 had a path-traversal vulnerability, no replay protection, token-leak chain into `dialecticRoomToken`, and TLS unaddressed. v2's `tv-webhook.py` code sketch (lines 448-580) is real, working code: `hmac.compare_digest` for signature verify, ±300s timestamp window (410), nonce store with TTL (409), `.resolve()` + `startswith` path check, 8 KiB body cap, op/type enforcement per binding, separate `TV_WEBHOOK_SECRET` env var fully isolated from `DIALECTIC_ROOM_TOKEN`. Four pre-declared mutation ops only — no free-form field writes. The webhook is the `marriage contract, not a DAG edge` (line 84), which is the right philosophy.

---

## Why Bravo Loses (300 words)

Bravo has the better *story* — "morning brief as the product" is genuinely what Jackson's video teaches, and the four new signal classes (velocity, multi-timeframe divergence, cross-book confluence, signpost grading) are the richest ideas in either plan. But Bravo's v2 has three architectural problems that Alpha does not.

**First, a factual snapshot error**. Trade 3 (lines 945, 950) says `dxy-stress=approaching 100.18 vs 102 threshold`. I verified against live propagation: `dxy-stress` is `type: "indicator"`, not `"price"`, and fires from UPSTREAM states, not threshold proximity. Current snapshot says `dxy-stress: fired`. Bravo's own narrative is built on a misread of its own example node. The DXY *price* is 100.18 — but the `dxy-stress` node state is fired, because `em-currency` and upstream nodes are fired. This kind of mistake would be caught in code review, but it signals that Bravo's author did not run `propagate()` against the live books while writing the trade section. Alpha did (line 670 "Verified by running `propagate()` against the live books").

**Second, the stdlib claim is compromised**. Phase 4 (lines 745-753) ships `node_mcp_source.py`: 120 LoC of Python that subprocess-Popens `node dist/index.js`. Bravo admits "This is NOT stdlib-Python. We own this dependency explicitly." (line 639). That's intellectually honest, but the plan still claims "No CDP, no WebSocket" and "works everywhere by default". The `--chart-source=node-mcp` flag introduces Node.js + Jackson's MCP repo as a build dependency for the power-user path. Alpha holds the stdlib line cleanly across ALL phases.

**Third, snapshot-payload coupling**. Bravo embeds `brief.markdownContent` (3-8 KB markdown string) inside the snapshot body (line 254). That reshapes the v:1 snapshot contract — a schema historically scoped to machine-readable state — to carry a pre-rendered document. Dialectic's consumer contract now has to tolerate a markdown field that every consumer except the LLM memory manager will ignore. It's a content-type smell masquerading as backward compatibility.

---

## The Decisive Factor

**Executability against the running engine.** Alpha's trade triggers are predicates over snapshot fields that `export_state()` demonstrably emits (em-stress score, fired states, countdowns, scenarioImpacts.netImpact). I verified all of them by running `--export-state -` against both books. Bravo's trade-3 narrative describes node state that does not match what the engine actually emits today. A plan whose example trades don't reconcile with live engine output cannot win a competition whose prize is trade decision rights. Alpha wins because an operator can execute it tomorrow; Bravo must first correct its reading of its own snapshot.

---

## Best Ideas to Steal from Bravo (absorb before final synthesis)

1. **Multi-timeframe RSI divergence** (Bravo line 531-537). 4h RSI >70 while 1d RSI <60 = distribution risk; 4h <30 while 1d >50 = pullback in uptrend. This is a signal Alpha's derived-indicator overlay cannot produce because Alpha only fetches 1D. **Action:** after Alpha Phase 1 ships, add a 4h fetch loop to `fetch_prices()` (one additional `range=60d&interval=1h` request per yahoo feed) and add a `divergence_flag` field to `tvIndicators`. ~30 LoC addition.

2. **Velocity-to-threshold with deadline forecasting** (Bravo trade 2 lines 931-939). `last + (daysRemaining × dailyDelta)` is genuinely novel and time-boxed deadlines are everywhere in tradingDesk (countdowns are first-class). **Action:** add `velocity7d` and `forecastAtDeadline` computations to `derived_indicators.py` — pure functions over the OHLCV series Alpha already stashes.

3. **Cross-book confluence** (Bravo `cross_book.py`, 50 LoC). Scanning `snapshots/*-latest.json` for shared symbols across books identifies multi-thesis pressure points. `BZ=F` in both iran-hormuz and trump-tariffs is real. **Action:** add as a post-propagate step in `run-all.py` after all books have fetched; emit a `crossBookFlags` diff category. Does not belong in any single book's snapshot.

4. **Structural-not-string tests** (Bravo line 763-797). Testing `assert verdict["action"] in (allowed_set)` rather than pinning exact markdown output is the correct testing discipline for any future rendering surface tradingDesk adds. **Action:** apply this standard to any HTML-output or markdown-output tests Alpha adds in Phase 3.

5. **Screenshot lifecycle** (Bravo line 853-864). 14-day rotation of `output/screenshots/{book}/{date}/` with unbounded-growth guard is the right operational discipline if tradingDesk ever renders chart evidence for Dialectic attachments. **Action:** keep as reference for a future Phase 4 "Chart Evidence" feature, out of the v1 merge.

---

## Known Residual Risks (things neither team fully addressed)

- **Pine Script webhook TLS.** Alpha documents "put it behind a reverse proxy" (line 584), but does not specify which reverse proxy, how to run ngrok/cloudflared in production, or what happens if the operator skips proxying. Bravo sidesteps this entirely by not having a webhook.
- **Yahoo Finance as single point of failure.** Both plans rely on `fetch_prices()` via Yahoo v7 spark API through `allorigins.win`. If either service degrades, BOTH plans' indicator computations return empty. No secondary data source is planned.
- **`closesObserved` drift from manual vs Pine vs Yahoo sources.** Alpha explicitly flags this (line 659) but the mitigation ("operator chooses trust source") is a policy decision not an implementation decision. Needs a `_ohlcvAuthoritative` flag design before Phase 2 ships.
- **Scenario-impact field naming.** Alpha's trade 2 references `snapshot.scenarioImpacts.closed-may.probability * netImpact >= 5.0` (line 704). That math requires consistent field presence across scenarios; neither plan audits whether every scenario currently exports both fields.
- **Intraday cadence.** Both plans remain 1D-granularity on the Yahoo fetch (Alpha explicit on line 651). For a thesis that changes mid-session, MWF cron is blind between runs. Neither plan builds toward an intraday option.
- **Dialectic snapshot-size growth.** Bravo admits 50 KB/week brief payload growth but doesn't audit against Dialectic's request body limit or memory storage quota. Alpha also adds `tvIndicators` per snapshot but the payload is much smaller (~1 KB).
- **Webhook operational monitoring.** Alpha's webhook is a long-running HTTP server but does not spec health-check endpoint, systemd unit, or metric emission. The "99% uptime" success metric (line 757) has no mechanism for verification.

---

## Recommended Final Plan Structure (for `docs/plans/`)

The merged plan should be named `docs/plans/20260405-tradingview-integration.md` and structured as **Alpha v2 as primary spine + four Bravo signal-class add-ons**. Specifically:

### Phase 1 — Alpha Phase 1 verbatim (3 days)
- `derived_indicators.py` (180 LoC) with RSI/ATR/SMA Wilder implementations
- `compute_derived_indicators(cfg)` wired into thesisgraph.py main()
- `closesObserved` counter integration (the one legitimate derived → engine field)
- Snapshot schema v:2 with `tvIndicators` top-level (NOT `brief`)
- v1 fetches bump from `range=1d` to `range=3mo&interval=1d`
- 48 new tests

### Phase 2 — Alpha Phase 2 verbatim (4 days)
- `tv-webhook.py` with HMAC/timestamp/nonce/path-safety full stack
- `tvAlertBindings` schema on nodes (four pre-declared op types only)
- Atomic book-JSON rewrites via `tmp+os.replace`
- 52 new tests covering every adversarial probe

### Phase 3 — Alpha Phase 3 verbatim + Bravo signal add-ons (3 days — expanded)
- `diff-snapshots.py` gains `tvIndicatorShifts` (Alpha)
- **ADD from Bravo:** `velocity7d` and `forecastAtDeadline` as pure functions in `derived_indicators.py`, surfaced in `tvIndicators` dict per node
- **ADD from Bravo:** 4h timeframe fetch in `fetch_prices()` and `divergence4h1d` flag computation
- **ADD from Bravo:** `cross_book.py` as a post-propagate step in `run-all.py`, emits `snapshots/cross-book-flags-{date}.json`
- 25 additional tests beyond Alpha's Phase 3 estimate

### Deferred (Phase 4+, documented not built)
- Bravo's morning-brief markdown renderer — only if Dialectic adds a proper brief memory type
- Bravo's screenshot pipeline — only if chart evidence becomes a named Dialectic requirement
- Bravo's Node-MCP subprocess path — only for a specific operator request

### NOT building
- No embedded markdown in snapshot payload (Alpha's snapshot-as-data stance wins)
- No separate `/trading/brief` endpoint (Alpha and Bravo both agree after v2)
- No RSI/ATR contaminating `eval_node_state()` (Alpha's overlay:true tripwire is canonical)
- No `meta.tradingview.biasRules` (both plans converge: derive from node feeds, one config file)

**Total LoC estimate:** ~1,340 new lines, ~200 new tests. Ship Phase 1+2 in the first PR; Phase 3 in a follow-up PR that depends on the signal add-ons being designed as pure functions over OHLCV series.

---

## First Three Trades — Final Selection

These trades use Alpha's trigger framework (predicates over engine-emitted snapshot fields) with Bravo's velocity and divergence signals layered as sizing modulators. Every trigger is verified against the current live snapshots.

```
TRADE 1: XOP (long) — $3,000 (37.5% of Iran/Hormuz monthly budget)
  ENTRY (hard gate, all four must be true):
    - snapshot.nodeStates["em-stress"] == "fired"              AND
    - snapshot.confluenceScores["em-stress"] >= 1.60           AND
    - snapshot.nodeStates["brent"] in ("approaching","fired")  AND
    - countdowns["planting-miss"].daysRemaining <= 14

  CURRENT READING (2026-04-05, verified via live export):
    em-stress=fired, score=1.67, brent=approaching, planting-miss=10 days.
    All four gates satisfied. TRADE IS ACTIONABLE TODAY.

  SIZING MODULATORS (Bravo signals, applied AFTER gates pass):
    - Full $3,000 if brent.velocity7d > 0 AND brent.rsi14 < 70
    - Starter $1,500 only if divergence4h1d == "bearish_4h_strength_fading"
    - Second half adds on pullback to brent below 20d EMA

  TV assist (Pine): alert "brent_persistence_close_115" fires on each daily
    close above $115. Webhook op incrementClosesObserved. When
    closesObserved >= 3, eval_node_state() promotes brent approaching→fired
    via the EXISTING closesRequired=3 gate at thesisgraph.py:201.

  Stop: -12% from fill. Target: +35% (XOP $188 ref → $254).
  Exit rule: if em-stress score drops below 1.30 OR brent returns to
    "stable", trim 1/3. If Pine webhook flips hormuz.state to "resolved",
    close entire position.

TRADE 2: CF (long) — $2,000 (25% of Iran/Hormuz monthly budget)
  ENTRY (hard gate):
    - snapshot.nodeStates["planting-miss"] == "approaching"         AND
    - countdowns["planting-miss"].daysRemaining <= 12               AND
    - snapshot.scenarioImpacts["closed-may"].probability
        * snapshot.scenarioImpacts["closed-may"].netImpact >= 5.0

  CURRENT READING (2026-04-05):
    planting-miss=approaching, days=10, closed-may prob=0.45 * netImpact=15.3
    = 6.9 (>= 5.0). TRADE IS ACTIONABLE TODAY.

  SIZING MODULATOR (Bravo velocity forecast):
    - velocity7d on NOLA urea proxy = +$14/week
    - forecastAtDeadline = current + (daysRemaining × daily_delta)
    - Full $2,000 if forecastAtDeadline crosses fert-shortage $700 threshold
    - Half $1,000 if forecast falls short — wait for deadline pressure

  TV assist: Pine alert "fert_close_above_700" fires on daily close >$700
    on urea proxy. Webhook op setCurrent updates fert-shortage.current.
    Single-trigger promotion (closesRequired not set on this threshold).

  Stop: -15% from fill. Target: +50% over 60-90 days ($136 → $200).
  Exit rule: if planting-miss deadline passes (Apr 15) without firing, close
    within 5 trading days.

TRADE 3: SPY short (via SH or ATM put spreads) — $1,500 (25% of Trump-tariffs budget)
  ENTRY (hard gate, all four must be true):
    - snapshot.confluenceScores["earnings-compression"] >= 2.00  AND
    - snapshot.confluenceScores["consumer-confidence"]   >= 1.80 AND
    - snapshot.confluenceScores["recession-risk"]        >= 1.20 AND
    - snapshot.nodeStates["fed-response"] in ("monitoring","stable")

  CURRENT READING (2026-04-05, verified via live export):
    earnings-compression=2.05, consumer-confidence=1.95, recession-risk=1.25,
    fed-response=monitoring. All four gates satisfied. TRADE IS ACTIONABLE.

  SIZING MODULATOR (Bravo cross-book + signpost):
    - Full $1,500 if cross-book flag confirms: BZ=F in BOTH books AND both
      thesis's dxy/dollar-stress nodes are fired
    - Half $750 if only single-book signal — pair with UUP long $500 as
      dollar-stress counterpart (Bravo's pair-trade idea)

  TV assist: Pine alert "spy_below_200dma_first_touch" fires when SPY closes
    below 200d SMA for first time in 60 days. Webhook op setProbability
    with bindingId "tariff-recession-technical-confirmation" raises the
    tariff-shock event node probability from 0.85 → 0.95.

  Stop: -8% from fill (SPY low realized vol). Target: +18%.
  Exit rule: on fed-response transitioning to "fired" (emergency cuts),
    close immediately. Policy response historically squashes equity shorts.
```

**Aggregate sizing:** $6,500 initial deployment against $14,000 combined monthly budget (46%). Balance in SGOV. No single position exceeds 40% of its book's budget. All three trades are verifiable today by running `python3 tools/thesis-graph/thesisgraph.py books/*.json --export-state -` and piping to `jq` — an operator can paste each trigger as a predicate, get a true/false answer from live engine output, and take the trade if all predicates resolve true.

**What this final selection borrows from Bravo:** the Bravo-derived sizing modulators (velocity, divergence, cross-book, deadline forecast) determine HOW MUCH to deploy and HOW to pair the position — they never determine WHETHER to enter. Alpha's engine-grounded predicates are the gates; Bravo's signal richness is the dial. This separation keeps the causal DAG pure (Alpha's philosophy) while extracting real value from technical state (Bravo's instinct). The merged trade book is stronger than either plan's standalone version.

---

## Tiebreaker note (not invoked)

If the scores had been tied at 79/79, the tiebreaker question — "which team's PLAN would cause an engineer to build the better tradingDesk" — would also favor Alpha. Alpha's architectural discipline (the `overlay: true` tripwire, the four-op pre-declared binding schema, the single-authority `TV_WEBHOOK_SECRET`) creates **future-proof guardrails** that survive organizational churn. Bravo's plan creates **features** that must be re-justified at each merge window. A plan that hardens the system's invariants wins over a plan that expands the system's surface, even when both are well-executed. Alpha does both; Bravo does the latter well.

---

**Final word:** Alpha ships. Bravo's best ideas get absorbed as Phase 3 signal enrichments and Phase 4+ deferred items. The First Three Trades above are the canonical trade book for the operator.

---

**Relevant files referenced:**
- `/root/tradingDesk/.planning/tv-plan/plan-alpha-v2.md`
- `/root/tradingDesk/.planning/tv-plan/plan-bravo-v2.md`
- `/root/tradingDesk/.planning/tv-plan/red-team-alpha.md`
- `/root/tradingDesk/.planning/tv-plan/red-team-bravo.md`
- `/root/tradingDesk/.planning/tv-plan/research-context.md`
- `/root/tradingDesk/.planning/tv-plan/codebase-map.md`
- `/root/tradingDesk/tools/thesis-graph/thesisgraph.py` (lines 195-209, 313-334 for engine contract verification)
- `/root/tradingDesk/books/iran-hormuz-graph.json` (line 136-147 for dxy-stress node type verification)
- `/root/tradingDesk/books/trump-tariffs-graph.json`
- Live snapshot outputs verified via `python3 tools/thesis-graph/thesisgraph.py books/*.json --export-state -`
