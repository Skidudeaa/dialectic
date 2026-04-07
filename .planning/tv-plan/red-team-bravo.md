# Red Team: Adversarial Review of Plan Bravo v1

**Target:** `/root/tradingDesk/.planning/tv-plan/plan-bravo-v1.md`
**Review date:** 2026-04-05
**Reviewer role:** Falsify the premises, break the assumptions, destroy the decisions.

---

## Executive Verdict

Bravo's plan is a narrative-first feature dressed as product strategy: it chooses "loose coupling" to the thesis graph so aggressively that the graph becomes advisory rather than load-bearing — producing a brief that restates data the HTML dashboard already shows, styled as a markdown report, pushed to an endpoint Dialectic does not expose. The CDP WebSocket client is presented as 30 lines of "preserved stdlib constraint" but is a toy framing loop that cannot survive a single `Page.captureScreenshot` response, and the bias rules config duplicates thresholds the books already define. The 20% that is wrong — the endpoint, the CDP framing, the rules duplication, the "edge" claim — destroys the plan as planned.

---

## Fatal Flaws

### F1. Dialectic has NO `/trading/brief` endpoint. Bravo pushes to a URL that does not exist.

Bravo's push code posts to `POST /rooms/{room_id}/trading/brief` (plan line 202, push_brief.py line 440). I verified the actual Dialectic server at `/root/DwoodAmo/dialectic/api/main.py`:

- Line 1183: `@app.post("/rooms/{room_id}/trading/snapshot", response_model=TradingSnapshotResponse)` — the ONLY trading endpoint.
- A grep across `/root/DwoodAmo/dialectic` for `trading/brief` returns zero matches in any route handler.

This is not a minor oversight. The "separate Dialectic message type" that Bravo's entire architectural differentiator depends on (plan line 15, "Briefs as a distinct Dialectic message type let the room LLM distinguish 'state update' from 'morning recommendation'") is *fiction*. To ship this plan, Dialectic itself needs:

- New Pydantic model `TradingBriefRequest` (doesn't exist)
- New SQL table or memory type for briefs (doesn't exist)
- New POST handler with auth middleware (doesn't exist)
- New downstream LLM-context formatter (doesn't exist)

The plan's "Modified Files" table (line 100-107) shows changes ONLY to tradingDesk, not Dialectic. Bravo is pushing to a 404. Exit code 1 on every run.

**Remediation:** Either (a) downgrade briefs to use the existing `/trading/snapshot` endpoint with a `type: "brief"` field embedded in the snapshot JSON (breaks snapshot schema v:1) or (b) add 200+ lines of Dialectic server work to the plan. Neither is trivial. Option (a) contradicts the "separate message type" differentiator. Option (b) makes this a two-repo project that Bravo didn't scope.

---

### F2. CDP WebSocket framing is a toy implementation that breaks on the first real payload.

Bravo claims "RFC 6455 WebSocket frames are not complex" (plan line 570) and provides a 5-line send/recv loop at `_send_cdp()` (plan line 374-392). Verify against RFC 6455:

**Bug 1 — receive frame parsing assumes single-frame, length-fits-in-2-bytes:**
```python
raw = self._ws_sock.recv(65536)
frame_start = 2 if raw[1] < 126 else 4  # plan line 391
```
`Page.captureScreenshot` returns base64-encoded PNG. A TradingView chart screenshot at typical resolution is 100-400 KB base64 = 130-520 KB payload. Per RFC 6455, payloads with length ≥ 65536 use an **8-byte extended length** (0x7F marker), not 2. Bravo's `frame_start = 4` is wrong — it should be `2 + 8 = 10` for large payloads.

**Bug 2 — no fragmentation handling:**
RFC 6455 allows servers to fragment messages. Chrome DevTools does this in practice for large responses. Bravo's code does a single `recv(65536)` and treats the buffer as one complete frame. Fragmented messages will cause JSON parse errors, and `recv(65536)` may return less than one frame's worth of data on a loaded socket.

**Bug 3 — no continuation opcode handling:**
Opcode 0x0 (continuation) is not parsed. Bravo's hardcoded `header = bytes([0x81])` (line 379) is send-only and doesn't handle receiving fragmented binary frames.

**Bug 4 — masking bit on receive is not checked:**
Server-to-client frames MUST NOT be masked (RFC 6455 §5.1). Bravo doesn't validate this. A misbehaving peer can corrupt the parser.

**Bug 5 — no ping/pong handling:**
CDP connections over WebSocket send periodic control frames. Bravo's recv loop treats these as data frames, corrupting the JSON decoder.

Jackson's upstream MCP uses `chrome-remote-interface` in Node.js precisely because correct CDP-over-WebSocket is ~500 LoC minimum with proper framing, masking, control-frame handling, and reconnection. Bravo's "30 lines" claim (line 570) is dangerously optimistic. This will not work on first attempt and the "pragmatic fix" (subprocess Node — line 571) contradicts the stdlib promise.

**Remediation:** Either commit to the subprocess-to-Node path from Day 1 (abandon stdlib pretense) or add 200-300 LoC of correct WebSocket framing with tests against a real CDP endpoint, not a `MockCDPServer` that echoes canned responses.

---

### F3. `window.__tvMCP` does not exist without Jackson's MCP running. Bravo's CDP calls hit a global that's never defined.

Bravo's CDP client calls `window.__tvMCP?.getOHLCV(...)` and `window.__tvMCP?.getIndicatorValue(...)` (plan line 396, 403). These are the **JavaScript bridge that Jackson's MCP server injects** into the TradingView Electron context. Without Jackson's MCP running, `window.__tvMCP` is undefined and the optional-chain returns `undefined` on every call. Bravo's code then returns `[]` and `None` (line 400, 405) — silently wrong data, not a visible failure.

The plan says in Phase 2 "Connect to TradingView Desktop, read real indicator values" (line 505) but never acknowledges that `window.__tvMCP` is Jackson-provided. It is not native to TradingView Desktop.

Bravo has three paths out, each bad:

1. **Run Jackson's MCP alongside** — then the "stdlib Python" constraint is dead because Node.js is now a required runtime dependency.
2. **Re-implement `window.__tvMCP` in tradingDesk** — now you're porting Jackson's injected JavaScript harness. The "Jackson's MCP video demonstrates one insight" (line 7) becomes "we fork and re-implement Jackson's entire injection layer." That's the opposite of loose coupling.
3. **Use raw TradingView internals directly** — there is no public JS API. Reverse-engineering TV's internal state via DOM traversal is fragile and undocumented.

**Remediation:** Either adopt Jackson's MCP as a subprocess dependency and drop the stdlib claim, or abandon CDP entirely and use Pine Script alert webhooks (Alpha's likely path). Bravo's current plan secretly depends on a component it never lists.

---

### F4. The "brief" adds no signal beyond the HTML dashboard — it's a restatement.

The brief's "node verdicts" table (plan line 123-128) shows: node name, graph state, chart signal, alignment, action. Compare to what the existing HTML dashboard (`tools/thesis-graph/thesisgraph.py`, `generate_html` at line 979) already produces:

- **Graph tab:** nodes colored by state (fired/approaching/stable/gated) — that's the "Graph State" column.
- **Portfolio tab:** instruments grouped by node with range bars — that's the "Action" column.
- **Cascade tab:** "WE ARE HERE" phase tracker — that's the header.
- **Journal tab:** decision audit trail — that's the "watch points."

Strip marketing from Bravo's brief. What's NEW?

- RSI values per symbol (plan line 257). tradingDesk doesn't track RSI today. True new signal.
- "Alignment" judgment (plan line 281). But the grader (tools/brief/grader.py, 160 lines, line 93) is a deterministic function — its output is derivable from snapshot + RSI, which is derivable from Yahoo OHLCV, which can be added to the dashboard in 20 lines.
- "Session Watch" bullets (plan line 130-133). These are just countdowns + thresholds from the book JSON, already shown in the Cascade tab.

Core question: does a trader need a Dialectic-pushed markdown restatement of what they could see in `output/iran-hormuz-graph.html` opened at 8:03 UTC? The plan's success metric #3 (line 617) claims "at least one brief correctly predicted a node state transition before it appeared in the snapshot" — but if the brief and snapshot both consume the same Yahoo OHLCV + snapshot state, the brief CANNOT see something the snapshot can't. They share inputs. The only edge is the RSI/EMA augmentation, which is a 20-line feature not a 1,005-line module.

**This is the premise failure.** Bravo argues the morning brief is "the product" (plan line 7). But the brief is a view of the data, not a source of new data. The HTML dashboard is already the "product" and Dan/Amo already read it.

**Remediation:** Either (a) make the brief derive signals the dashboard can't (multi-timeframe divergences, cross-book confluence, intraday velocity) or (b) kill the brief and add RSI/EMA to the HTML as a new panel — a 30-line change in `generate_html`.

---

### F5. Two sources of truth for thresholds. They WILL drift.

tradingDesk books already define full threshold/regime logic per node. From `books/iran-hormuz-graph.json`:

- `brent` node: thresholds `[{level: 115, closesRequired: 3}, {level: 135}, {level: 155}]` with four regimes (base/elevated/escalation/extreme) — line 37-47
- `diesel` node: thresholds with `durationRequired: "2 weeks"` — line 57-62
- `fert-shortage` node: thresholds with labels — line 104-107
- `dxy-stress` node: threshold `{level: 102}` — line 145

Bravo adds `meta.tradingview.biasRules` (plan line 168-178) with:
```json
{"rsi_overbought": 70, "rsi_oversold": 30, "ema_period": 50, "atr_period": 14, "volume_threshold_multiplier": 1.5}
```

This is a DIFFERENT config file (well, same file, different section). When the trader decides that Brent's persistence threshold is now 118 not 115, they update `nodes.brent.thresholds[0].level`. But does the brief know? The grader reads thresholds from the book's `nodes` array, while the "RSI bias" rules live in `meta.tradingview`. Six months from now someone will add a per-node RSI override and the two configs will disagree on what "overbought" means for Brent vs CF.

Worse: Bravo's brief *grades against the book's existing thresholds* (plan line 65: "thesis's own thresholds — not generic rules") AND adds generic RSI rules. Which wins when they conflict? The grader code (line 93-96 summary, full logic in grader.py not shown) must reconcile. This reconciliation logic is an invisible third source of truth.

**Remediation:** Drop `biasRules` entirely. Put RSI/EMA thresholds *on the node* as a new feed type (following the codebase-map suggestion: `{"source": "tradingview", "symbol": "BZ=F", "indicator": "RSI", "overbought": 70}`). One config file, one location per node.

---

## Major Concerns

### M1. "Loose coupling" is a euphemism for "parallel system that duplicates graph logic."

Plan line 73-74: "Brief grading uses the existing `export_state()` snapshot as input — no re-propagation, no coupling to thesisgraph internals." But look at what `grader.py` (160 lines) must do:

- Re-derive node threshold status from snapshot (already in `nodeStates`)
- Map instruments to nodes (already in book's `instruments` section)
- Compute "alignment" between chart signal and graph state (new logic)
- Determine "action" per node (new logic)

The first two are thesisgraph logic re-implemented. The propagation engine (thesisgraph.py `propagate()` at line 298, `score_confluence()` at 313) already returns everything Bravo re-computes. By refusing to "couple" to thesisgraph, Bravo rebuilds mapping tables in a parallel module. When `propagate()` changes semantics (e.g. new node type "conditional"), the grader silently falls out of sync.

**Remediation:** Import thesisgraph functions directly. `from thesisgraph import propagate, score_confluence` — it's stdlib. The "loose coupling" is a cop-out that creates future drift.

---

### M2. Screenshot storage breaks the self-contained HTML dashboard model.

Plan line 56: "Screenshot artifacts → output/screenshots/{book-id}-{date}.png" and line 619 success metric 4: "Screenshots are generated and stored in `output/screenshots/` with no manual cleanup required."

tradingDesk's architectural invariant (CLAUDE.md, Project Conventions): "All outputs are self-contained single-file HTML." The brief-as-markdown with external PNG references violates this. Worse:

- **Size growth unbounded:** Each run writes 1 PNG per watchlist instrument. 6 instruments × 2 books × 3x/week = 36 PNGs/week = ~15MB/week at 400KB each. No rotation, no cleanup.
- **Dialectic can't render PNGs:** The brief payload includes `"screenshotPaths": ["output/screenshots/..."]` (plan line 213) — filesystem paths. Dialectic's LLM sees the path string, not the image. Why send the path if it can't be fetched? The LLM sees "output/screenshots/foo.png" as literal text.
- **Test file explosion:** If screenshots are "first-class artifacts" they need golden-image comparison tests. None in the plan.

**Remediation:** Either base64-embed PNGs in the brief JSON (payload size explodes, Dialectic POST 413 at ~10MB) or drop screenshots from the brief entirely. The plan mentions neither path tradeoff.

---

### M3. `run-all.py` integration is under-specified. Brief runtime cost is invisible.

Plan line 104: "`tools/bridge/run-all.py` | +45 lines | Add `run_brief(...)` step after `run_export`". Look at the actual file:

- Line 180-293: `run_book()` is sequential per book
- Line 238: `run_export` is the fetch+export step
- Line 269: `run_diff` compares snapshots
- Line 282: `run_push` sends to Dialectic

Adding a `run_brief` step between export and diff means each cron run now blocks on CDP connection attempts. If TradingView Desktop isn't running (common on headless servers — the typical cron target), Bravo says exit code 3 is non-fatal (plan line 197). But CDP connection timeout is 10 seconds (cdp_client.py line 328). 6 symbols × 10s timeout × 2 books = up to 120 seconds of blocking before falling through to the Yahoo fallback. Cron run time roughly doubles.

Also: Bravo's `--no-brief` flag (plan line 523) is a "skip the new thing" switch. But the plan also says the brief is "the product" (line 7). If the product's opt-out is a new CLI flag, it's a feature, not the product.

**Remediation:** Make `run_brief` asynchronous (background thread or separate cron entry) so snapshot pipeline latency isn't coupled to CDP availability. Document the additional runtime cost in CLAUDE.md.

---

### M4. "Standalone AND integrated" is a contradiction.

Plan line 15: "Loose coupling to chart source means TradingView is Day 1 but Tradestation is Day 30." But also plan line 70: "Why This Matches tradingDesk Patterns" with `run-all.py` integration. These are in tension:

- **If standalone:** the brief is a separate CLI run ad-hoc. No `run-all.py` integration needed. Why touch run-all.py at all?
- **If integrated:** the brief is a pipeline step. Then it's not standalone — it's a dependency of run-all.py with its own exit codes and failure modes cascading back.

The plan wants both: standalone command for flexibility, integrated into cron for automation. Fine in theory. But the cost is: two code paths (standalone CLI vs subprocess call from run-all.py), two failure modes to test, two entry points to document. Plan Phase 1 builds standalone, Phase 3 integrates, but the testing doubling isn't costed in the 30 test number (line 500, 514, 527).

**Remediation:** Pick one. If integrated, the CLI entry point is for debugging only. If standalone, abandon the `run-all.py` hook and rely on separate cron entries.

---

### M5. Golden tests will break on every phrasing change.

Plan line 542: "given a known snapshot JSON (fixture) and known chart state (fixture dict), `grade_all()` must return exact expected verdicts." Golden tests on `renderer.py` output (plan line 95) are brittle by construction:

- Change "APPROACHING — on watch" to "APPROACHING (on watch)" → test fails
- Add a cascade phase emoji → test fails
- Reorder watchPoints → test fails

Markdown renderers are prose generators. Prose golden tests are a maintenance trap. Every copy change is a test churn.

**Remediation:** Test the structured `brief_data` dict (deterministic, machine-readable) and test `render_markdown()` only for required-field presence (does output contain "cascadePhase"? does it contain a table?). Do NOT pin exact output strings.

---

### M6. "Mock CDP" with HTTP + canned WebSocket is not a real test.

Plan line 536-539: `MockCDPServer` uses `threading.Thread + http.server.HTTPServer` to serve a `/json` response and accept "a raw WebSocket connection and responds to `Runtime.evaluate` and `Page.captureScreenshot` CDP commands with fixture data."

Problems:

1. `http.server.HTTPServer` doesn't natively accept WebSocket upgrades. You'd need a custom handler with manual WebSocket handshake response. That's the same 30+ lines of framing code Bravo claims is trivial — doubled (server-side + client-side).
2. The mock doesn't exercise the CDP spec. It echoes canned responses. The client bug in F2 (fragmentation, large payloads) will never trigger because the mock never sends a 400 KB screenshot.
3. "socket-level stub" (plan line 513) is vague — is this a real socket or a unittest.mock? The mock's fidelity determines whether tests catch the framing bugs.

**Remediation:** Test against a real headless Chromium via `chrome --remote-debugging-port=9223 --headless`. The mock approach lets framing bugs slip through and ship broken.

---

### M7. First three trades are NOT differentiated from what Alpha could propose.

The three trades (plan line 577-605) are derived from:
- `brent` node approaching $115 (already in `iran-hormuz-graph.json` at line 37)
- `diesel` fired >$5.38 (line 57-62)
- `fert-shortage` approaching (line 104-107)
- `planting-miss` deadline Apr 15 (line 115)
- `dxy-stress` approaching 102 (line 145)

These are 100% restatements of the book's existing node states and thresholds. ANY plan reading the same book gets the same three trades. The "Brief signal" rows (RSI 68, above 4h EMA 50, etc.) are the only differentiation — and those are the RSI/EMA numbers that could be added to the HTML dashboard as a 30-line panel (see F4).

The competition is "winner gets trade rights — originality matters." If Alpha proposes identical trades because the source data is identical, Bravo's differentiation is the RSI/EMA overlay, which is not a plan's worth of work.

**Remediation:** Either derive trades from a signal Bravo's architecture uniquely produces (e.g., cross-book confluence: "diesel fired in Hormuz AND tariff-escalation approaching in Trump — double pressure on freight"), or acknowledge the trades are derivative and Bravo wins on execution quality not signal originality.

---

### M8. "Brief as narrative, snapshot as data" is false dichotomy.

Plan line 11: "Snapshots are data. Briefs are narrative. Both belong in the room, but they serve different purposes." But the snapshot JSON (schema in codebase-map.md line 37-49) includes `cascadePhase.status`, `countdowns[].label`, `scenarioImpacts[].probability` — all of which are *narrative* fields for the LLM to consume. The snapshot is ALREADY narrative-ready.

And the brief JSON twin (plan line 141-163) is... a JSON dict. Structured. Data. The only "narrative" is the markdown rendering, which any Dialectic LLM can generate from the snapshot on-demand with a prompt.

**Remediation:** Abandon the dichotomy. If the brief's value is "pre-rendered markdown for human consumption," say that honestly. The snapshot-vs-brief framing is marketing.

---

### M9. `ChartClient` protocol is speculative abstraction with one real consumer.

Plan line 79: "The CDP implementation is one concrete class. A Yahoo Finance fallback class ships in Phase 1 so the brief runs without TradingView Desktop. Tradestation, ThinkOrSwim, or any future source is a new concrete class." That's three potential implementations; one exists (CDP, half-broken per F2). The "Yahoo fallback" in Phase 1 (plan line 489) isn't a ChartClient implementation — it's the Yahoo fetcher tradingDesk already has, renamed.

Abstraction audit: The `ChartClient` protocol exists to satisfy Bravo's "loose coupling" narrative. But if Yahoo (stdlib, already in the codebase) is the default and CDP is the optional upgrade, then two concrete classes is too few to justify a protocol abstraction. One consumer = premature abstraction.

**Remediation:** Ship only CDPChartClient with a Yahoo fallback as an `except` branch. No protocol. If Tradestation becomes real in 6 months, refactor then.

---

### M10. Exit code 3 "not a failure" contradicts run-all.py convention.

Plan line 197: "Exit 3 = TradingView unavailable (brief skipped, not a run failure). Exit 3 is not a failure for `run-all.py`."

But `run-all.py` (line 389) maps exit codes: "0 = all books succeeded, 1 = one or more books failed, 2 = configuration error." There's no precedent for exit code 3 in the tradingDesk convention. Bravo is introducing a new exit code semantic that run-all.py must learn to interpret. The +45 lines to run-all.py (plan line 104) must include this special-case handling.

**Remediation:** Use exit code 0 with a stderr "skipped" log line, matching run-all.py's existing "[warn]" pattern (e.g. line 263: `[warn] {book_id}: no dialecticRoomId — export only`).

---

## Minor Polish

- **Plan line 272:** Screenshot path uses `symbol.replace('/', '_').replace('=', '')` — inconsistent with snapshot-name convention. Define a canonical slug helper.
- **Plan line 443:** `"markdownContent"` payload field has no size limit check. Large briefs with embedded images could exceed Dialectic's request body limit.
- **Plan line 234:** `today = date.today()` uses local timezone. Cron runs in UTC — filename dates could differ from snapshot timestamps on east-of-UTC systems.
- **Plan line 267:** `chart_states[symbol] = {"error": str(e)}` silently persists into the brief. The LLM sees "error": "CDP connection refused" as a node state and may misinterpret.
- **Plan line 571:** "Node.js is already on any developer machine running Jackson's MCP" — assumes developer machine. Cron target is a server.
- **Plan line 96:** `test_brief.py | 320 lines` — 320 lines for 30 tests = ~10 lines per test including setup. Too thin for CDP mocking.
- **Plan line 405:** `get_indicator` returns `.get("value")` with no type coercion. RSI from JS is a number; from TV internals could be NaN/null/string.
- **Plan line 407:** `capture_screenshot` hardcodes `"quality": 80` — but PNG doesn't use quality (that's JPEG). The param is silently ignored.
- **Plan line 564-565:** "CDP is a stable protocol" — true, but the `window.__tvMCP` injection Bravo depends on is NOT part of CDP stability (see F3).
- **Plan line 625:** "Amo can read the morning brief in the Dialectic room by 08:15 UTC and make a position decision before US pre-market open (09:30 ET = 13:30 UTC)" — 08:15 UTC is 04:15 ET. Pre-market begins 04:00 ET. Brief is ALREADY 15 minutes late.

---

## What Bravo Got Right (Steel-Man)

- **Separate `tools/brief/` directory** is the correct module boundary. The codebase-map.md explicitly suggests this (line 141: "Option C — Morning brief mirror").
- **Reading snapshots rather than re-propagating** is good discipline — avoids duplicating thesis graph execution.
- **Per-book rules living in `meta.tradingview`** (even if duplicative — see F5) follows the existing pattern of `meta.dialecticRoomId` and `meta.dialecticRoomToken` — consistent with tradingDesk conventions.
- **Graceful CDP degradation** (plan line 565: "brief degrades gracefully — no crash, no blocked pipeline") is sound engineering instinct. The implementation doesn't match the promise, but the instinct is right.
- **Phased build with clear exit criteria** (Phases 1/2/3) is well-structured. Phase 1 delivers value without TradingView Desktop, which is correctly noted.
- **Retry logic with exponential backoff** in `push_brief` (plan line 451) mirrors the existing `push-to-dialectic.py` pattern — good consistency.

---

## The Killshot Question

**"Show me the Dialectic server pull request that creates `/rooms/{id}/trading/brief`, and show me the single successful `recv()` of a 400 KB base64 PNG from your CDP client — if you can't, your plan pushes to a 404 with a framing library that breaks on its first real payload, and the whole 'morning brief as the product' thesis evaporates."**

If Bravo cannot produce both (and they can't — Dialectic doesn't have the endpoint, and a 30-line WebSocket framer cannot handle fragmented 400 KB frames with 8-byte extended length), then the plan is two weeks of building scaffolding around a load-bearing assumption that doesn't hold. The brief exists, technically. It can be rendered, technically. But the push fails and the screenshots are corrupted or path-only, so what arrives in the Dialectic room is nothing, or markdown text with broken image refs. Not a product. Not even a feature. A demo that runs once locally and breaks when it touches the network boundary it was designed to cross.

---

**Relevant files:**
- `/root/tradingDesk/.planning/tv-plan/plan-bravo-v1.md` — target of review
- `/root/tradingDesk/.planning/tv-plan/codebase-map.md` — extension point map
- `/root/tradingDesk/tools/bridge/push-to-dialectic.py` — verified push pattern (lines 117-184)
- `/root/tradingDesk/tools/bridge/run-all.py` — verified pipeline integration point (lines 180-293)
- `/root/tradingDesk/books/iran-hormuz-graph.json` — verified existing threshold config (lines 37-47, 57-62, 104-107, 145)
- `/root/DwoodAmo/dialectic/api/main.py` line 1183 — verified `/trading/snapshot` is the ONLY trading endpoint
- `/root/DwoodAmo/dialectic/api/trading.py` — verified no `/trading/brief` handler exists
