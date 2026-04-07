# Red Team Report: Plan Alpha v1

## Executive Verdict

Alpha's plan is an architecturally tidy document built on a load-bearing technical claim that is wrong, a trade-sizing section that cites a confluence score for a node that the existing engine will literally never score, and a philosophical thesis ("RSI belongs in the DAG") that injects category errors into a causal graph. Two of the three proposed phases (Phase 2 deep propagation, Phase 3 webhook + morning brief) rest on premises the codebase's current `eval_node_state()` and `score_confluence()` actively refute. The only genuinely salvageable piece is the Phase 1 enrichment shim — but even there, the "First Three Trades" section would not be executable from day one because the triggers reference scores the engine never emits.

---

## Fatal Flaws

### F1. The Scanner API requires authentication for real-time data — Alpha claims "no auth required"

**Plan claim:** "No auth required for public symbols" (plan-alpha-v1.md:308), "stdlib `urllib` POST works headless in cron" (line 8).

**Evidence:** `tradingview-screener`, the most-used reverse-engineered wrapper, documents: *"To access real-time data, you need to pass your session cookies, as even free real-time data requires authentication."* 403 Forbidden errors on `scanner.tradingview.com/{market}/scan` are a documented, recurring failure mode on datacenter/cloud IPs (PythonAnywhere forum threads 30334 and 30466). TradingView's own support docs state there is no public API for retrieving indicator values programmatically.

**Consequences:** On first cron run from any datacenter or cloud VM, `fetch_tradingview()` will return empty. Phase 1 exit criterion "produces v:2 snapshot with non-empty `tvIndicators` for brent node" (line 504) fails day one. Phase 2's deep integration depends entirely on data Phase 1 fetches, so it collapses. The 46 Phase 1 tests pass against **fixtures** (line 576) and hide the failure until production. Alpha's own hedge (line 598) admits TV can "block the scanner endpoint any time" but writes fallback as dead code — Phase 2 tests can't verify behavior in production when the fallback fires.

**Remediation:** Either (a) add session-cookie auth handling with documented rotation (breaks stdlib-only), or (b) pivot to an official alternative (chart-img REST, paid TradingView integration, or compute technical indicators from Yahoo OHLCV in-process).

---

### F2. The "First Three Trades" reference a confluence score on a node that `score_confluence()` cannot score

**Plan claim:** "Confluence score ≥1.5 on brent node from Yahoo+TV agreement" (line 619), "dxy-stress (iran-hormuz) + reserve-currency (trump-tariffs) confluence score ≥1.3" (line 638).

**Evidence from `tools/thesis-graph/thesisgraph.py:313-334`:**
```python
def score_confluence(cfg: dict, states: dict) -> dict:
    """Score fan-in nodes. Returns {nodeId: score} for nodes with fan-in >= 2."""
    ...
    for nid, incoming in fan_in.items():
        if len(incoming) < 2:   # <-- HARD GATE
            continue
```

The current Iran/Hormuz graph fan-in distribution (verified by running against `books/iran-hormuz-graph.json`):
- `brent`: fan-in=1 (NOT SCORED)
- `dxy-stress`: fan-in=1 (NOT SCORED)
- `demand-destruction`: fan-in=1 (NOT SCORED)
- `em-stress`: fan-in=3 (ONLY scored node, max possible = 2.05, current = 1.67)

Alpha cites a "≥1.5" threshold that is within the score range of the only scoreable node (`em-stress`), but it does so on three nodes that `score_confluence()` **will never emit a key for**. These aren't aspirational — trade 1's entry logic depends on it at line 619, and trade 3's entry depends on "dual-thesis confluence" across books that `score_confluence()` also does not compute (it operates per-config, never across books — see line 313, signature takes single `cfg`).

**Consequences:** The "TV signal" triggers are decorative. No code path in the existing engine would generate them. Operators would wait forever for signals the system cannot emit under the cited names.

**Remediation:** Either (a) change `score_confluence()` to treat TV indicator agreement as virtual fan-in (breaks the causal-edges model, see F3), (b) add graph edges from new TV indicator nodes (contaminates the DAG), or (c) rewrite "First Three Trades" to reference actual scoreable nodes — `em-stress` is the only one in Iran/Hormuz.

---

### F3. Adding RSI as a graph input makes technical indicators a cause in the DAG — a category error

**Plan claim:** "Chart evidence should change your graph state" (line 67); `score_confluence()` gets a multiplier when "Yahoo price AND TV RSI signals agree" (line 58).

**Evidence:** The thesis graph's edges encode causal transmission (CLAUDE.md: "oil shock → diesel → freight → employment → demand destruction"). An edge from X to Y asserts "X causes Y in the real economy with mechanism M." The `closesRequired` field (thesisgraph.py:201) represents "the market needs to hold the level for N days to confirm persistence" — a statement about price regime, not technical overlays.

RSI is a derived statistic *about* a price series. RSI does not cause Brent to persist above $115 — Brent persistence causes RSI to rise. Making RSI an input to `brent`'s state reverses the causal arrow. "Yahoo+TV agreement" (line 58) is just "two sources pricing the same asset agree" — it does not add independent evidence. It is reading the same thermometer twice and claiming higher confidence.

**Consequences:** The graph loses causal interpretability. A node fired because RSI > 70 looks identical in output to one fired by economic transmission, but they are epistemically different. Phase 2 adds noise-dressed-as-signal into the field that drives the morning brief. Alpha's own "Bolted on (enrichment only)" list (lines 60-63) internally contradicts the "Woven in (affects propagation)" list (lines 55-58) — the plan wants both, and they are incompatible in a causal DAG.

**Remediation:** Keep TV indicators as snapshot enrichment (Phase 1 only). Tag them "non-causal overlay" in node JSON schema. Never let them mutate `nodeStates` or `confluenceScores`. Decorate HTML and drive alerting, but do not flow through `propagate()`.

---

### F4. Webhook security model is breakable and couples TV alerts to Dialectic token hygiene

**Plan claim:** Webhook receiver in `tools/bridge/tv-webhook.py` accepts Pine Script POSTs with token-in-body auth (line 402-405), mutates book JSON directly (lines 426-444).

**Evidence:** The receiver writes to `books/*.json` based on attacker-supplied `alert["book"]`, `alert["node"]`, `alert["field"]`, `alert["value"]` with validation limited to a four-field allowlist. Book JSONs currently contain `meta.dialecticRoomToken` (iran-hormuz-graph.json:10 — `"a28b98fa6a74425c927fa64e4f614817"`). The webhook gives any token-holder arbitrary write access to those files.

**Attack surface:**
1. **Token-leak chain.** TradingView logs alert bodies in user-visible alert history. If the shared secret leaks from there, an attacker can flip any node to "fired" and trigger malicious snapshot pushes to real Dialectic rooms — `dialecticRoomToken` is already in the book JSON, so the attacker only needs to mutate state to trigger the push that uses it.
2. **Path traversal.** `book_path = books_dir / f"{alert['book']}.json"` (line 420) never calls `.resolve()` or validates the book name is a simple identifier.
3. **Field injection.** `alert["value"]` is written directly into JSON; the allowlist only covers field names, not value types. Injecting a stringified object as `"state": {...}` passes validation but corrupts `export_state()` serialization.
4. **No replay protection.** No nonce, no timestamp window. A captured POST can be replayed indefinitely.
5. **TLS unaddressed.** Line 596 says "run on non-public port with firewall" — but TradingView's Pine Script webhooks POST from TradingView's servers, requiring public reachability. Cannot be both public AND firewalled.

**Remediation:** (a) HMAC-signed bodies via `hmac.compare_digest()`. (b) Validate book path is under `books/`. (c) Type-check `alert["value"]` per field. (d) Timestamp window. (e) Document TLS termination or require reverse proxy. (f) Separate `TV_WEBHOOK_TOKEN` scope from `DIALECTIC_ROOM_TOKEN`.

---

### F5. The column-name and timeframe format is wrong

**Plan claim:** "Column name format: `\"RSI\"` (appended as `\"RSI|\"` in API call for 1D), `\"RSI|60\"` for 1H" (line 128). Code at line 324: `tv_columns = [f"{col}|" if "|" not in col else col for col in all_columns]`.

**Evidence from reverse-engineered wrappers (`python-tradingview-ta`):** The actual format is:
- 1D (default): **no suffix** — just `"RSI"` (not `"RSI|"`)
- 1H: `"RSI|60"`
- 1W: `"RSI|1W"`
- 1M: `"RSI|1M"`

Alpha's proposed code appends `"|"` (pipe with empty suffix) to every 1D column. Against the real API this will likely return nulls for every column or 400 on the request — `"RSI|"` is not a valid column name. The bug is in both the prose contract (line 128) AND the code sketch (line 324), so a downstream implementer reading the plan would write the wrong code twice.

**Consequences:** Phase 1 ships, tests pass against fixtures captured via a hand-crafted request that doesn't use the `f"{col}|"` pattern, production never returns indicator values, no one notices because Phase 2 "gracefully falls back."

**Remediation required:** Correct to `tv_columns = [col if "|" in col else col for col in all_columns]` (i.e., no suffix for default 1D) and update line 128 contract text accordingly.

---

## Major Concerns

### M1. `TVC:UKOIL` is not on the futures screener

Alpha's book-edit example uses `"symbol": "TVC:UKOIL", "screener": "futures"` (line 109, 465). TVC (TradingView Continuous) is its own exchange prefix for CFDs/indices. The `futures` screener contains CME/ICE symbols like `NYMEX:CL1!`, `ICEEUR:BRN1!`. Using a TVC symbol against the futures screener will return empty. The plan has never tested this specific (symbol, screener) combination against the live API.

**Remediation:** Either use `screener="cfd"` with `TVC:UKOIL`, or use `screener="futures"` with `ICEEUR:BRN1!`. Document screener-symbol pairing rules.

### M2. Phase 2's confluence-multiplier breaks 223 existing tests

Alpha promises "All 241 tests pass" at Phase 2 exit (line 524), including "no regressions" on 223 existing tests. But extending `score_confluence()` to add a Yahoo+TV multiplier will change scores emitted by existing test fixtures that currently assert exact values. `test_export.py` has 76 tests, many of which snapshot the confluence dict (`em-stress: 1.67` etc). Any multiplier changes those numbers.

**Remediation:** Make the confluence extension opt-in via a config flag in `meta.tradingview.confluenceMultiplierEnabled` so existing tests are unaffected.

### M3. Phase 3 morning-brief overlaps with Bravo's thunder and duplicates Phase 1 outputs

The research context (research-context.md:35-52) explicitly identifies "Morning Brief workflow" as Jackson's video's centerpiece. Alpha's Phase 3 builds a morning-brief.py that consumes the snapshot + TV indicators and emits a Dialectic-formatted brief. This is a second push to the Dialectic room on top of the existing snapshot push. It's also the main product Bravo is likely targeting (Bravo is the competing plan). Phase 3 is either (a) stealing Bravo's feature scope, or (b) a phase that should be scoped out as a separate proposal.

**Remediation:** Drop Phase 3 from Alpha. Scope Phase 1+2 as the pure "deep integration" pitch. Let a separate design handle morning-brief holistically (it's worth its own plan, not a tacked-on phase).

### M4. "Zero external deps" is only true if you believe assertion about `hmac`

Plan lists `hmac` (line 602) as a stdlib module for webhook verification, but the actual code sketch (lines 371-450) does not use it — it uses plain string comparison on `alert.get("token")`. The claim of zero-dep is true of the modules listed; the code sketch doesn't match the claim.

**Remediation:** Either use `hmac.compare_digest()` for constant-time token comparison (trivial fix) or drop `hmac` from the "stdlib modules used" list.

### M5. Phase 3 exit criteria include a hallucinated trade performance metric

"The three trades above collectively +8% or better over 30 days" (line 660) is listed under "Trading edge (aspirational)" but scoped as a 30-day post-merge success metric. 30 days is too short to evaluate macro trades with holding periods of weeks-to-months (explicitly stated as the design target on line 584). This is a trading KPI masquerading as an engineering KPI, and it sets up the project to be judged a failure for reasons outside Alpha's control.

**Remediation:** Remove trading P&L from the engineering success metrics. Keep "operational" and "signal quality" sections, drop "trading edge."

### M6. The three book-node edits are mechanical, not justified

"Add TV feeds to `brent` node (RSI + ATR on BZ=F futures equiv)" (line 90) is asserted without explaining *why* brent's state evaluation would improve with RSI. The existing `brent` node already has a `closesRequired: 3` on the $115 threshold (iran-hormuz-graph.json:38) — that mechanism is strictly superior to an RSI overlay for this thesis (persistence is the object of measurement, not overbought-ness).

**Remediation:** For each TV feed added to an existing node, write one sentence explaining what question the TV indicator answers that the existing Yahoo price + thresholds structure cannot answer. If you can't justify it node-by-node, drop it.

### M7. The fan-in `em-stress` is ignored — the actual scoreable node

`em-stress` is the only node in Iran/Hormuz that `score_confluence()` can score (fan-in=3), and it has genuine causal fan-in from three independent paths (`food-spike`, `em-currency`, `employment`). Alpha's plan never proposes TV feeds for any of these three upstream nodes, which is where TV could actually contribute (e.g., daily RSI on EM ETFs for `em-currency`, on food commodity futures for `food-spike`).

**Remediation:** Retarget Phase 1 TV feeds at the upstream-of-em-stress nodes, not at brent/dxy-stress/demand-destruction.

### M8. Phase 1 test count is suspicious

220 lines for 40 tests = 5.5 lines/test. `test_polymarket.py` is 41 tests in roughly the same file-size band, so the proportion is right. But 40 tests for a ~280-line module is a test-per-7-lines-of-code ratio that suggests heavy CLI fuzz and surface validation rather than behavioral coverage. Without an outline of what the 40 tests actually verify, it's impossible to tell if core cases are covered or if the count is padded.

**Remediation:** List the 40 test cases in the plan, grouped by behavior (happy path, network errors, malformed response, column parsing, screener routing, etc).

---

## Minor Polish

- Line 24 diagram: "triggers run-all.py step (optional)" is vague — specify the trigger mechanism.
- Line 130: `fetchedAt` is not an indicator value; move it out of the `tvIndicators` indicator-values dict.
- Line 278: `node.setdefault(...).update(...)` pattern overwrites `fetchedAt` per loop iteration; harmless but confusing.
- Line 594: "18 POSTs/week" underestimates real count — Pine Script webhooks add arbitrary additional POSTs.
- Line 643: "stops enforced by the graph's own `eval_node_state()` logic" is false. `eval_node_state()` evaluates price against thresholds, it does not enforce stop orders.
- Plan never says where `tv-morning-brief.py` outputs persist or what the rotation policy is.
- No mention of TradingView's Sunday maintenance window and how `fetch_tradingview()` degrades during it.

---

## What Alpha Got Right (Steel-Man)

- **Holds the stdlib-only line.** No Node.js sidecar, no pip installs. Right architectural starting position.
- **Correctly mirrors `fetch_polymarket` pattern.** Dynamic import, `cfg` mutation return, stderr feedback. If Scanner API worked as claimed, this is the right shape.
- **v:2 backward-compat is verified correct.** `mock_dialectic.py`'s `REQUIRED_SNAPSHOT_KEYS` does not include `tvIndicators`, so adding it as optional passes validation unchanged (claim on lines 160-161 is true).
- **Per-book rules placement is correct.** Rules in `meta.tradingview` respects one-config-per-thesis convention.
- **Phased order would be sensible** (enrichment → propagation → webhook) if Phase 1 weren't built on sand.
- **Section 8 self-awareness** correctly names schema drift, rate limits, and webhook-auth weakness as risks — but proposed mitigations don't address them adequately.

---

## The Killshot Question

> **If `scanner.tradingview.com/futures/scan` returns 403 on day one from the production cron host, what does this plan deliver?**

If the answer is "a 280-line module with 40 fixture-backed tests that produces no live data, a Phase 2 that degrades to pre-TV propagation logic, and a Phase 3 webhook that still works because Pine Script alerts are independent of the Scanner API" — then Alpha is spending ~1,160 LoC and 114 tests to ship a webhook receiver with a vestigial scanner module as dead code. If that's the real goal, scope down to just the webhook and say so.

If the answer is "the whole pipeline collapses" — Alpha has concentrated 100% of the plan's risk in a single unverified API claim (F1) that takes two minutes to falsify and is documented as unreliable in public forums.

Either way: the Scanner API is not the foundation the plan claims. The deep-integration philosophy is independently wrong even if the API worked (F3). The First Three Trades cannot execute against the confluence scores the engine emits (F2). The plan is roughly 30% wrong, and the 30% is load-bearing.
