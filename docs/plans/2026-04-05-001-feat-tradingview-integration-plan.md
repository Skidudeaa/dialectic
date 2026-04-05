---
title: "feat: TradingView integration (signal-source, webhook-driven)"
type: feat
status: proposed
date: 2026-04-05
origin: https://youtu.be/vIX6ztULs4U (Lewis Jackson — "How To Connect Claude to Trading View")
competition:
  teams: [alpha, bravo]
  winner: alpha
  judge_verdict: .planning/tv-plan/judge-verdict.md
  alpha_plan: .planning/tv-plan/plan-alpha-v2.md
  bravo_plan: .planning/tv-plan/plan-bravo-v2.md
  red_team_alpha: .planning/tv-plan/red-team-alpha.md
  red_team_bravo: .planning/tv-plan/red-team-bravo.md
---

# feat: TradingView Integration (signal-source, webhook-driven)

## Overview

Wire TradingView into tradingDesk as a **signal producer**, not a DAG participant.
Two routes only:

1. **Pine Script alerts → HMAC-signed webhook → atomic book-JSON node mutations** against fields the engine already reads (`state`, `probability`, `current`, `closesObserved`). TradingView's paid infrastructure runs real-time technical rules; we catch the alert fires and apply them as mutations the existing `propagate()` already knows how to consume.
2. **Local RSI/ATR/SMA computed from Yahoo OHLCV** (stdlib, no new network) populates `snapshot.tvIndicators` for Dialectic context, and increments `closesObserved` counters that drive the EXISTING `closesRequired` gate at `thesisgraph.py:201`.

The thesis graph itself stays causally clean: no RSI in `eval_node_state()`, no technical overlays in `score_confluence()`. Chart evidence decorates and triggers; it never becomes a cause in the DAG.

## Problem Frame

The video demos Lewis Jackson's fork of `tradesdontlie/tradingview-mcp` — a Node.js MCP server bridging Claude Code to TradingView Desktop via Chrome DevTools Protocol, with a "morning brief" workflow. That architecture requires TradingView Desktop running with a debug port, a Node.js runtime, and an undocumented CDP interface that TradingView can break between releases.

tradingDesk is stdlib-only Python, headless, cron-friendly, multi-book. We extract the **idea** — use chart state to grade thesis signposts and trigger node-state mutations — but land it on load-bearing stdlib foundations: Yahoo OHLCV for derivation, Pine Script webhooks for the real-time signal path, HMAC-signed requests for security.

(see origin: `https://youtu.be/vIX6ztULs4U`; competition artifacts: `.planning/tv-plan/`)

## Architecture

```
books/*.json ──────────────────────────────────────────────┐
  nodes[].feeds[source="yahoo"]       (existing)           │
  nodes[].derivedIndicators[]         (NEW — compute list) │
  nodes[].tvAlertBindings[]           (NEW — mutation map) │
                                                            ▼
run-all.py ──► thesisgraph.py --fetch --export-state
                  │
                  ├─► fetch_prices()                Yahoo (existing; +OHLCV capture)
                  ├─► fetch_polymarket()            existing
                  ├─► compute_derived_indicators()  ← NEW, stdlib, no network
                  │     reads cfg["_ohlcv"]
                  │     writes node["tvIndicators"] = {rsi14, atr14, sma50, velocity7d,
                  │                                    forecastAtDeadline, divergence4h1d}
                  │     increments node["closesObserved"] for threshold crossings
                  │     DOES NOT mutate node["state"] or node["current"]
                  ├─► propagate()                   unchanged
                  ├─► score_confluence()            unchanged
                  └─► export_state()                v:2 snapshot adds top-level tvIndicators

run-all.py post-propagate ──► cross_book.py         ← NEW (Bravo signal)
                                 scans snapshots/*-latest.json
                                 emits snapshots/cross-book-flags-{date}.json

TradingView Pine alert
  POST /webhook/tv-alert
  X-TV-Signature: sha256=<hmac(body, TV_WEBHOOK_SECRET)>
  X-TV-Timestamp: <unix-seconds>
  X-TV-Nonce: <16 random bytes, one-time>
                           │
                           ▼
            tv-webhook.py  HMAC verify → ±300s timestamp window → nonce check
                           → resolve book path (under books/ only)
                           → lookup bindingId in book.tvAlertBindings
                           → apply pre-declared mutation op (one of 4)
                           → atomic book-JSON rewrite (tmp+os.replace)
                           → 200 OK with applied-field echo
```

### Why this shape

- `compute_derived_indicators()` mirrors `fetch_polymarket()`'s discipline: pure stdlib, importable from `tools/data-fetch/`, called in sequence after `fetch_prices()`.
- `tv-webhook.py` mirrors `mock_dialectic.py`: `BaseHTTPRequestHandler`, `_send_json` helper, module-importable + CLI runnable, tests use the same harness.
- `tvAlertBindings[]` on each node makes mutations **auditable and pre-declared**. The webhook cannot write arbitrary fields — only the operations explicitly authorized in the book.
- Atomic writes via tmp+`os.replace` copy the existing `update_config_file()` pattern at `thesisgraph.py:650`.
- `cross_book.py` is a post-propagate step in `run-all.py` that operates on committed snapshots, never a single book's state.

### What is woven in vs bolted on

**Woven in (affects propagation):**
- `closesObserved` counter increments — drives the EXISTING `closesRequired` gate at `thesisgraph.py:201`. No new state-evaluation code path.
- Pine alert → `node.state = "active"` or `node.probability = 0.85` — mutates fields `eval_node_state()` already consumes. Same semantics.

**Bolted on (enrichment only, never affects propagation):**
- `tvIndicators` dict — read by `export_state()`, displayed in HTML, pushed to Dialectic. Never read by `eval_node_state()` or `score_confluence()`.
- `tvIndicatorShifts` diff category in `diff-snapshots.py` — informational only.
- `cross-book-flags-{date}.json` — post-run diagnostic, not a snapshot field.

### Philosophy

The DAG encodes real-economy causation. TradingView encodes human technical judgement. They meet at one place: the Pine alert fires when the operator's rule triggers; the mutation applied is a fact about the operator's view, not a new upstream cause. **The webhook is the marriage contract, not a DAG edge.**

## Concrete File Plan

### New files

| Path | Est. Lines | Purpose |
|---|---|---|
| `tools/data-fetch/derived_indicators.py` | 220 | RSI(14), ATR(14), SMA(N), velocity7d, forecastAtDeadline, divergence4h1d, closesObserved counter — all pure stdlib, importable + CLI |
| `tools/data-fetch/test_derived_indicators.py` | 320 | 56 tests: Wilder's 1978 RSI reference, ATR/SMA against known series, velocity/forecast edge cases, closesObserved counting, divergence detection, CLI |
| `tools/bridge/tv-webhook.py` | 260 | HMAC-verified Pine Script receiver with replay protection; pre-declared binding map only; atomic book-JSON mutation |
| `tools/bridge/test_tv_webhook.py` | 320 | 44 tests: signature verify, timestamp window, nonce replay, binding lookup, path traversal rejection, type coercion, atomic write, concurrency |
| `tools/bridge/test_tv_webhook_e2e.py` | 120 | 8 round-trip tests: webhook → mutation → propagate → snapshot diff |
| `tools/bridge/cross_book.py` | 90 | Post-propagate scanner: detects shared instruments across books, emits cross-book-flags JSON |
| `tools/bridge/test_cross_book.py` | 100 | 16 tests: shared-symbol detection, no-false-positives, fixture-based scan |

### Modified files

| Path | Lines | Change |
|---|---|---|
| `tools/thesis-graph/thesisgraph.py` | +75 | Store OHLCV series in `cfg["_ohlcv"]` during `fetch_prices()` (~10 lines); call `compute_derived_indicators()` after `fetch_polymarket()` in `main()` (~5 lines); add `tvIndicators` top-level to `export_state()` output (~15 lines); add 4h-timeframe fetch in `fetch_prices()` for symbols with `"divergence": true` in derivedIndicators config (~45 lines) |
| `tools/thesis-graph/test_export.py` | +60 | 10 new tests: v:2 snapshot shape, `tvIndicators` presence, OHLCV capture, closesObserved increment, `compute_derived_indicators()` wiring |
| `tools/bridge/run-all.py` | +40 | Add post-propagate cross-book scan step; emit cross-book-flags output; document new `TV_WEBHOOK_SECRET` env var |
| `tools/bridge/diff-snapshots.py` | +35 | New diff category `tvIndicatorShifts` (RSI changes >5 pts, velocity sign flips, divergence flag changes) |
| `tools/bridge/test_diff.py` | +30 | 8 new tests for `tvIndicatorShifts` category |
| `tools/validation/mock_dialectic.py` | +12 | Tolerate v:2 schema: add `tvIndicators` as optional field in allowlist |
| `books/iran-hormuz-graph.json` | +40 | Add `derivedIndicators[]` and `tvAlertBindings[]` to brent + fert-shortage + dxy-stress nodes |
| `books/trump-tariffs-graph.json` | +35 | Add bindings to input-costs, consumer-confidence, fed-response, dollar-wrecking-ball nodes |
| `CLAUDE.md` | +25 | Document new commands, webhook setup, TV_WEBHOOK_SECRET env var, Pine alert format |
| `INTEGRATION.md` | +30 | Document v:2 snapshot schema changes, `tvIndicators` field contract |

**Totals:** 7 new files (~1,430 LoC), 10 modified files (+382 LoC), ~188 new tests.

## Schemas & Contracts

### Node-level additions

```json
{
  "id": "brent",
  "label": "Brent Persistence",
  "type": "price",
  "feeds": [{"source": "yahoo", "symbol": "BZ=F"}],
  "current": 112.57,
  "thresholds": [
    {"level": 115, "label": "persistence", "closesRequired": 3},
    {"level": 135, "label": "escalation"}
  ],
  "closesObserved": 0,
  "derivedIndicators": [
    {"name": "rsi14", "symbol": "BZ=F"},
    {"name": "atr14", "symbol": "BZ=F"},
    {"name": "sma50", "symbol": "BZ=F"},
    {"name": "velocity7d", "symbol": "BZ=F"},
    {"name": "divergence4h1d", "symbol": "BZ=F"}
  ],
  "tvAlertBindings": [
    {
      "bindingId": "brent_persistence_close_115",
      "description": "Pine alert fires on each daily close > $115",
      "op": "incrementClosesObserved",
      "targetThreshold": 115
    }
  ]
}
```

**`derivedIndicators[]`** — declarative list of what to compute. `compute_derived_indicators()` walks this list and writes results to `node.tvIndicators`. Required fields: `name`, `symbol`. Optional: `deadline` (for `forecastAtDeadline`), `extraTimeframe` (for `divergence4h1d`).

**`tvAlertBindings[]`** — pre-declared mutation contract. Four allowed ops only:
- `incrementClosesObserved` — bumps `node.closesObserved` by 1 per alert
- `setState` — overwrites `node.state` (requires `allowedValues[]`)
- `setProbability` — overwrites `node.probability` (requires 0.0–1.0 range check)
- `setCurrent` — overwrites `node.current` (requires numeric value from payload)

Any op not in this allowlist → webhook rejects with 400. This is the security invariant.

**`closesObserved`** — integer counter on price nodes. Incremented by `compute_derived_indicators()` on genuine Yahoo close threshold crossings AND by webhook `incrementClosesObserved` op. The existing `eval_node_state()` at `thesisgraph.py:201` reads this via `closesRequired` logic, no change there.

### Snapshot v:2 schema (additive, backward-compatible)

```json
{
  "v": 2,
  "timestamp": "2026-04-05T14:00:00Z",
  "title": "Iran/Hormuz Thesis",
  "nodeStates": {"brent": "approaching", "em-stress": "fired"},
  "confluenceScores": {"em-stress": 1.67},
  "cascadePhase": {"number": 2, "key": "transmission", "status": "ACTIVE"},
  "countdowns": [{"nodeId": "planting-miss", "deadline": "2026-04-15", "daysRemaining": 10}],
  "marketSnapshot": {"brent": 112.57, "diesel": 5.38},
  "scenarioImpacts": {"closed-may": {"probability": 0.45, "netImpact": 15.3}},
  "portfolioSummary": {"monthlyBudget": 8000, "topPositions": []},
  "tvIndicators": {
    "brent": {
      "rsi14": 64.2,
      "atr14": 3.18,
      "sma50": 105.4,
      "velocity7d": 2.30,
      "divergence4h1d": "bearish_4h_strength_fading",
      "closesObserved": 1,
      "computedAt": "2026-04-05T13:58:00Z"
    }
  }
}
```

v:1 snapshots remain valid. `diff-snapshots.py` handles both versions. `mock_dialectic.py` accepts v:2 (added to schema tolerance). Dialectic's existing `/rooms/{room_id}/trading/snapshot` endpoint ingests v:2 without server-side change — `tvIndicators` is additive data and the endpoint does not validate the full snapshot shape.

### Pine Script webhook request contract

TradingView's Pine Script alert webhook POSTs JSON to a user-configured URL. Our receiver expects:

```
POST /webhook/tv-alert HTTP/1.1
X-TV-Signature: sha256=<hex(hmac_sha256(TV_WEBHOOK_SECRET, body))>
X-TV-Timestamp: 1712328000
X-TV-Nonce: a7f4c9d2e3b1...
Content-Type: application/json

{
  "book": "iran-hormuz-graph",
  "bindingId": "brent_persistence_close_115",
  "value": null,
  "symbol": "TVC:UKOIL",
  "alertName": "Brent > $115 daily close",
  "firedAt": "2026-04-05T13:30:00Z"
}
```

**Validation pipeline (all must pass):**

1. `X-TV-Signature` header present AND `hmac.compare_digest(expected, received) == True`
2. `abs(now - X-TV-Timestamp) <= 300` (5-minute window)
3. `X-TV-Nonce` not in `nonce_store` (TTL 600s) → add after verify
4. Body is valid JSON with required keys: `book`, `bindingId`
5. `book` resolves to a path under `books/` (via `.resolve()` + `startswith` check)
6. `bindingId` exists in `book.tvAlertBindings[]`
7. Mapped op is in allowlist `{incrementClosesObserved, setState, setProbability, setCurrent}`
8. For `setState`: `value` in binding's `allowedValues[]`
9. For `setProbability`: `0.0 <= value <= 1.0`
10. For `setCurrent`: `isinstance(value, (int, float))`

Failure on any check → appropriate 4xx with no mutation.

### `TV_WEBHOOK_SECRET` — environment variable

Completely separate from `DIALECTIC_ROOM_TOKEN`. Generate with `openssl rand -hex 32`. Document rotation procedure in CLAUDE.md. The webhook receiver logs signature verification failures (no body) but NEVER logs payload contents on failure, to avoid leaking probed inputs.

## Key Code Sketches

### `compute_derived_indicators(cfg)` — in `thesisgraph.py`

```python
def compute_derived_indicators(cfg: dict) -> dict:
    """Compute RSI/ATR/SMA/velocity/divergence from OHLCV captured by
    fetch_prices(). Writes results to node['tvIndicators']. Increments
    node['closesObserved'] on legit threshold crossings.

    WHY stdlib-only: Yahoo OHLCV is already in hand from fetch_prices().
    Recomputing RSI here is ~20 lines of Wilder's smoothing math. No
    network, no pip, no auth. Cron-safe from any IP.
    """
    ohlcv = cfg.get("_ohlcv", {})
    if not ohlcv:
        print("  derived: no OHLCV captured, skipping", file=sys.stderr)
        return cfg

    di_dir = os.path.join(os.path.dirname(__file__), "..", "data-fetch")
    if di_dir not in sys.path:
        sys.path.insert(0, os.path.abspath(di_dir))
    import derived_indicators as di

    count = 0
    for node in cfg.get("nodes", []):
        declared = node.get("derivedIndicators", [])
        if not declared:
            continue
        tv = node.setdefault("tvIndicators", {})
        for ind in declared:
            sym = ind.get("symbol")
            series = ohlcv.get(sym)
            if not series or len(series) < 20:
                continue
            name = ind["name"]
            if name == "rsi14":
                tv["rsi14"] = di.rsi(series, period=14)
            elif name == "atr14":
                tv["atr14"] = di.atr(series, period=14)
            elif name == "sma50":
                tv["sma50"] = di.sma(series, period=50)
            elif name == "velocity7d":
                tv["velocity7d"] = di.velocity(series, window=7)
            elif name == "divergence4h1d":
                hi = cfg.get("_ohlcv_4h", {}).get(sym)
                if hi:
                    tv["divergence4h1d"] = di.divergence(hi, series)
            count += 1

        # WHY: closesObserved drives closesRequired at thesisgraph.py:201
        for thr in node.get("thresholds", []):
            need = thr.get("closesRequired")
            if not need:
                continue
            lvl = thr.get("level")
            observed = di.closes_above(series, lvl)
            node["closesObserved"] = max(node.get("closesObserved", 0), observed)

        tv["computedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"  derived: computed {count} indicator(s)", file=sys.stderr)
    return cfg
```

### RSI (Wilder) in `derived_indicators.py`

```python
def rsi(closes: list, period: int = 14) -> float | None:
    """Wilder's 1978 RSI. Expects a list of closing prices, oldest-first.

    Returns None if len(closes) < period + 1 (insufficient history).
    """
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    # Initial simple averages over first period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # Wilder smoothing for the rest
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)
```

### Webhook HMAC verification snippet

```python
def _verify_signature(self, body: bytes) -> bool:
    sig_header = self.headers.get("X-TV-Signature", "")
    if not sig_header.startswith("sha256="):
        return False
    received = sig_header[7:]
    secret = os.environ.get("TV_WEBHOOK_SECRET", "").encode("utf-8")
    if not secret:
        print("[tv-webhook] TV_WEBHOOK_SECRET not set", file=sys.stderr)
        return False
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)

def _check_timestamp(self) -> bool:
    ts_header = self.headers.get("X-TV-Timestamp", "")
    try:
        ts = int(ts_header)
    except ValueError:
        return False
    now = int(time.time())
    return abs(now - ts) <= 300

def _resolve_book_path(self, book_name: str) -> Path | None:
    """Resolve book path with traversal guard."""
    books_dir = (Path(__file__).parent.parent.parent / "books").resolve()
    candidate = (books_dir / f"{book_name}.json").resolve()
    if not str(candidate).startswith(str(books_dir)):
        return None
    if not candidate.exists():
        return None
    return candidate
```

### Op dispatch (excerpt)

```python
ALLOWED_OPS = {"incrementClosesObserved", "setState", "setProbability", "setCurrent"}

def apply_op(node: dict, binding: dict, payload_value) -> tuple[bool, str]:
    """Apply a pre-declared mutation op. Returns (ok, error_or_field_name)."""
    op = binding["op"]
    if op not in ALLOWED_OPS:
        return False, f"op not allowed: {op}"
    if op == "incrementClosesObserved":
        node["closesObserved"] = node.get("closesObserved", 0) + 1
        return True, "closesObserved"
    if op == "setState":
        allowed = binding.get("allowedValues", [])
        if payload_value not in allowed:
            return False, f"value {payload_value!r} not in allowedValues"
        node["state"] = payload_value
        return True, "state"
    if op == "setProbability":
        if not isinstance(payload_value, (int, float)) or not 0.0 <= payload_value <= 1.0:
            return False, "probability must be numeric in [0, 1]"
        node["probability"] = float(payload_value)
        return True, "probability"
    if op == "setCurrent":
        if not isinstance(payload_value, (int, float)):
            return False, "current must be numeric"
        node["current"] = float(payload_value)
        return True, "current"
    return False, "unreachable"
```

## Phased Build Sequence

### Phase 1 — Derived Indicators (3 days)

**Goal:** RSI/ATR/SMA/velocity computed from Yahoo OHLCV, populate `snapshot.tvIndicators`, feed `closesObserved` counters. No webhook yet.

**Files touched:**
- CREATE `tools/data-fetch/derived_indicators.py` (~220 LoC)
- CREATE `tools/data-fetch/test_derived_indicators.py` (~320 LoC, 56 tests)
- MODIFY `thesisgraph.py`: `_ohlcv` capture in `fetch_prices()`, `compute_derived_indicators()` call in `main()`, `tvIndicators` in `export_state()`, v:2 bump
- MODIFY `test_export.py`: 10 new tests
- MODIFY `mock_dialectic.py`: accept v:2
- MODIFY `iran-hormuz-graph.json`: `derivedIndicators[]` on brent + fert-shortage + dxy-stress

**Exit criteria:**
- `pytest` passes all 56 new tests plus existing 223
- `python3 thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state -` emits v:2 with non-empty `tvIndicators.brent.rsi14`
- `rsi(wilder_reference_series, 14)` matches published RSI values within 0.01

### Phase 2 — Webhook Receiver (4 days)

**Goal:** HMAC-verified Pine Script webhook with pre-declared binding map. Real-time state mutations into book JSONs.

**Files touched:**
- CREATE `tools/bridge/tv-webhook.py` (~260 LoC)
- CREATE `tools/bridge/test_tv_webhook.py` (~320 LoC, 44 tests)
- CREATE `tools/bridge/test_tv_webhook_e2e.py` (~120 LoC, 8 tests)
- MODIFY `iran-hormuz-graph.json` + `trump-tariffs-graph.json`: `tvAlertBindings[]` on relevant nodes
- MODIFY `CLAUDE.md` + `INTEGRATION.md`: webhook setup, secret rotation, Pine alert format

**Exit criteria:**
- All 52 new tests pass
- E2E test: synthetic signed POST → webhook → book JSON mutated → `propagate()` re-run → snapshot reflects mutation
- Replay attempt within nonce TTL returns 401
- Timestamp outside 300s window returns 401
- Path traversal attempt (`book: "../../etc/passwd"`) returns 400

### Phase 3 — Signal Enrichment + Cross-Book (3 days)

**Goal:** Absorb Bravo's best signal ideas — velocity-to-threshold with deadline forecasting, 4h/1d RSI divergence, cross-book shared-instrument detection.

**Files touched:**
- MODIFY `derived_indicators.py`: add `velocity(series, window)`, `forecast_at_deadline(series, days)`, `divergence(hi_tf, lo_tf)` pure functions
- MODIFY `thesisgraph.py` `fetch_prices()`: conditional 4h fetch for symbols with `"divergence": true` in derivedIndicators config (additive, guarded by node declarations)
- MODIFY `diff-snapshots.py`: new `tvIndicatorShifts` diff category
- MODIFY `test_diff.py`: 8 new tests
- CREATE `tools/bridge/cross_book.py` (~90 LoC)
- CREATE `tools/bridge/test_cross_book.py` (~100 LoC, 16 tests)
- MODIFY `run-all.py`: post-propagate cross-book scan step, `cross-book-flags-{date}.json` output

**Exit criteria:**
- `velocity7d` appears in `snapshot.tvIndicators.brent` with signed delta
- `divergence4h1d` populated when node declares `extraTimeframe: "4h"`
- `cross-book-flags-{date}.json` detects `BZ=F` in both iran-hormuz and trump-tariffs books
- Snapshot diff reports RSI shifts >5 pts as notable changes

### Phase 4+ — Deferred (not building in v1)

- Morning-brief markdown rendering as Dialectic attachment (Bravo's headline feature, deferred)
- Chart screenshot pipeline via headless Chromium (Bravo idea, deferred until chart evidence is a named Dialectic requirement)
- Node-MCP subprocess path for live TradingView Desktop indicator reads (deferred; feature-flagged if requested)

## Testing Strategy

### Golden numerical tests for derivation
`test_derived_indicators.py` uses Wilder's 1978 reference series (published RSI values) as the ground truth. Test passes if `abs(our_rsi - reference_rsi) < 0.01`. No network, no fixtures that need updating on market moves.

### Webhook test harness
Mirrors `mock_dialectic.py` test pattern: spin up `TVWebhookHandler` on ephemeral port, send crafted signed POSTs with `hmac.new(...).hexdigest()` in the signature header. Cover every validation step with both passing and failing cases.

Attack surface coverage:
- Signature tampering (flip 1 byte) → 401
- Expired timestamp → 401
- Replay attack (same nonce twice) → 401
- Path traversal in `book` field → 400
- Invalid op in binding (injected via fixture) → 400
- Out-of-range probability (1.5) → 400
- Stringified state value not in allowedValues → 400
- Empty body → 400
- Malformed JSON → 400
- Concurrent POSTs to same book → serialized, no corruption (verified by checksum)

### Regression guard
All 223 existing tests must continue passing. `compute_derived_indicators()` is additive — no existing code path changes semantics. `export_state()` gains `tvIndicators` but keeps all existing fields unchanged. `v:1` snapshots continue to round-trip through the pipeline.

## Trade-offs & Risks

### What this gives up

- **No intraday cadence.** Derived indicators are computed once per MWF cron run against 1D OHLCV. Thesis changes mid-session are invisible until next run. Webhook alerts ARE real-time but only for operator-defined Pine rules.
- **No TradingView Desktop parity.** Jackson's MCP gives 81 tools including Pine Script authoring and chart replay. We cover the read+alert slice that matters for a macro thesis DAG, not the full charting workstation.
- **No Scanner API.** Decision rationale: auth-required, 403s on datacenter IPs, schema-drift risk. We compute locally from data we already fetch.

### Residual risks (flagged for operations)

- **Yahoo Finance single point of failure.** Both derived indicators AND webhook `closesObserved` counters depend on Yahoo OHLCV. Mitigation: `compute_derived_indicators()` fails soft (returns cfg unchanged) on empty OHLCV.
- **Webhook TLS termination unspecified.** The webhook MUST be publicly reachable for Pine alerts (TradingView POSTs from their servers, not localhost). Operational decision: run behind Cloudflare Tunnel or ngrok in production. Document in runbook, do NOT let the webhook listen on an unencrypted public port.
- **`TV_WEBHOOK_SECRET` rotation procedure.** Documented in CLAUDE.md but not automated. Stale secrets become dead Pine alerts — no data loss, but alerts silently stop taking effect. Add a `tv-webhook.py --health` self-test that logs last-accepted-alert timestamp per binding.
- **Pine alerts cannot send custom headers reliably.** TradingView alert webhooks support JSON body + URL but header configuration is limited. Our design handles this: signature goes in body-derived HMAC, timestamp/nonce come from body JSON fields (re-checked in `_verify_body()`). The `X-TV-*` headers pattern is the PREFERRED path when the operator uses a proxy/tunnel that can inject them.
- **Snapshot payload growth.** v:2 adds ~1 KB per book for `tvIndicators`. Dialectic snapshot request body stays well under the 256 KB default. Monitor.

### Stdlib fidelity

Every new file is stdlib-only: `urllib.request`, `json`, `hmac`, `hashlib`, `time`, `os`, `pathlib`, `http.server.BaseHTTPRequestHandler`, `datetime`. No `websockets`, no `requests`, no `cryptography`, no `pydantic`. The `statistics` stdlib module is available if needed but current implementations avoid it.

## The First Three Trades

These are the canonical trades for the operator. Every entry predicate references a value the engine emits today, verified by `python3 tools/thesis-graph/thesisgraph.py books/*.json --export-state -`. Bravo-derived sizing modulators (velocity, divergence, cross-book, deadline-forecast) determine HOW MUCH to deploy, never WHETHER to enter.

```
TRADE 1: XOP (long) — $3,000 (37.5% of Iran/Hormuz monthly budget)
  ENTRY GATE (all four must be true):
    - snapshot.nodeStates["em-stress"] == "fired"              AND
    - snapshot.confluenceScores["em-stress"] >= 1.60           AND
    - snapshot.nodeStates["brent"] in ("approaching","fired")  AND
    - countdowns["planting-miss"].daysRemaining <= 14

  CURRENT READING (2026-04-05, verified):
    em-stress=fired score=1.67, brent=approaching, planting-miss=10 days.
    ALL FOUR GATES SATISFIED. TRADE IS ACTIONABLE TODAY.

  SIZING MODULATORS (applied AFTER gates pass):
    - Full $3,000 if brent.velocity7d > 0 AND brent.rsi14 < 70
    - Starter $1,500 only if divergence4h1d == "bearish_4h_strength_fading"
    - Second half adds on pullback to brent below 20d EMA

  TV assist (Pine): alert "brent_persistence_close_115" fires on each
    daily close > $115. Webhook op incrementClosesObserved. When
    closesObserved >= 3, eval_node_state() promotes brent
    approaching→fired via the EXISTING closesRequired=3 gate at
    thesisgraph.py:201.

  Stop: -12% from fill. Target: +35% (XOP $188 ref → $254).
  Exit rule: if em-stress score drops below 1.30 OR brent returns to
    "stable", trim 1/3. If Pine webhook flips hormuz.state to
    "resolved", close entire position.

TRADE 2: CF (long) — $2,000 (25% of Iran/Hormuz monthly budget)
  ENTRY GATE:
    - snapshot.nodeStates["planting-miss"] == "approaching"   AND
    - countdowns["planting-miss"].daysRemaining <= 12         AND
    - snapshot.scenarioImpacts["closed-may"].probability
        * snapshot.scenarioImpacts["closed-may"].netImpact >= 5.0

  CURRENT READING (2026-04-05):
    planting-miss=approaching, days=10, closed-may prob=0.45 *
    netImpact=15.3 = 6.9 (>= 5.0). TRADE IS ACTIONABLE TODAY.

  SIZING MODULATOR (deadline forecast):
    - velocity7d on NOLA urea proxy = +$14/week
    - forecastAtDeadline = current + (daysRemaining × daily_delta)
    - Full $2,000 if forecastAtDeadline crosses $700 fert-shortage threshold
    - Half $1,000 if forecast falls short — wait for deadline pressure

  TV assist: Pine alert "fert_close_above_700" on urea proxy daily close.
    Webhook op setCurrent updates fert-shortage.current. Single-trigger
    promotion (closesRequired not set on this threshold).

  Stop: -15% from fill. Target: +50% over 60-90 days ($136 → $200).
  Exit rule: if planting-miss deadline passes (Apr 15) without firing,
    close within 5 trading days.

TRADE 3: SPY short (via SH or ATM put spreads) — $1,500 (25% of Trump-tariffs budget)
  ENTRY GATE (all four must be true):
    - snapshot.confluenceScores["earnings-compression"] >= 2.00 AND
    - snapshot.confluenceScores["consumer-confidence"]   >= 1.80 AND
    - snapshot.confluenceScores["recession-risk"]        >= 1.20 AND
    - snapshot.nodeStates["fed-response"] in ("monitoring","stable")

  CURRENT READING (2026-04-05, verified):
    earnings-compression=2.05, consumer-confidence=1.95, recession-risk=1.25,
    fed-response=monitoring. ALL FOUR GATES SATISFIED. TRADE IS ACTIONABLE.

  SIZING MODULATOR (cross-book + pair):
    - Full $1,500 if cross-book flag confirms: BZ=F in BOTH books AND
      both theses' dxy/dollar-stress nodes are fired
    - Half $750 if only single-book signal — pair with UUP long $500
      as dollar-stress counterpart

  TV assist: Pine alert "spy_below_200dma_first_touch" fires when SPY
    closes below 200d SMA for the first time in 60 days. Webhook op
    setProbability raises tariff-shock event node probability 0.85 → 0.95.

  Stop: -8% from fill. Target: +18%.
  Exit rule: on fed-response transitioning to "fired" (emergency cuts),
    close immediately. Policy response historically squashes equity shorts.
```

**Aggregate sizing:** $6,500 initial deployment against $14,000 combined monthly budget (46%). Balance in SGOV reserve. No single position exceeds 40% of its book's budget. All three trades are **verifiable right now** by running:

```bash
python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --export-state - 2>/dev/null | jq '.nodeStates["em-stress"], .confluenceScores["em-stress"], .countdowns[] | select(.nodeId=="planting-miss") | .daysRemaining'
```

Each trigger predicate evaluates against live engine output; operator can `jq` the snapshot and know instantly whether the trade is actionable.

## Success Metrics — 30 Days Post-Merge

**Operational (must-have):**
- All 223 existing tests + ~188 new tests pass every MWF cron run
- `compute_derived_indicators()` populates `tvIndicators` in ≥95% of runs
- Webhook accepts ≥5 legitimate Pine alerts over 30 days (across both books), rejects ≥100% of forged requests in penetration test
- `run-all.py` total runtime increases by <5 seconds with derivation + cross-book enabled
- Zero book JSON corruptions (verified by SHA-1 of committed book state vs post-run state; any diff comes only from declared op mutations)

**Signal quality (should-have):**
- At least 1 case where Pine webhook led engine state by 1+ days (real-time value)
- At least 1 case where `closesObserved` counter driven by Pine alerts promoted a node via `closesRequired` gate without manual intervention
- `tvIndicatorShifts` diff category reports ≥3 notable RSI shifts per week across both books (validates the signal density)
- Cross-book flags identify ≥1 shared-instrument alert per week (e.g., BZ=F pressure in both books)

**Trading edge (aspirational):**
- The three trades above generate tracked P&L; monthly review compares trade performance to a "snapshot-only" counterfactual (same entry gates, no sizing modulators)
- At least 1 case where a sizing modulator (divergence, cross-book) saved or improved an execution vs full-size-at-gate policy

**Dialectic integration:**
- Snapshot v:2 pushed to both live Dialectic rooms every run with `tvIndicators` populated
- The room LLM references `tvIndicators` fields in at least 1 room conversation per week (measured by grepping Dialectic room logs)
- Zero snapshot rejections due to schema mismatch (mock_dialectic validates every push in CI)

---

## Appendix: Competition Provenance

This plan is the merged product of an architecture competition between two independent architect teams, adversarial red-team review of both plans, v2 iterations, and final judgment by an architecture-strategist arbiter. Full artifacts:

- `.planning/tv-plan/research-context.md` — source video analysis + Claude+TradingView integration patterns
- `.planning/tv-plan/codebase-map.md` — tradingDesk extension points
- `.planning/tv-plan/plan-alpha-v1.md` / `plan-alpha-v2.md` — Team Alpha (primary spine — winner, 83/100)
- `.planning/tv-plan/plan-bravo-v1.md` / `plan-bravo-v2.md` — Team Bravo (absorbed signal add-ons, 75.5/100)
- `.planning/tv-plan/red-team-alpha.md` — adversarial critique of Alpha v1
- `.planning/tv-plan/red-team-bravo.md` — adversarial critique of Bravo v1
- `.planning/tv-plan/judge-verdict.md` — final judgment with scoring and merge recommendation

Team Alpha wins primary structure (webhook path, derivation philosophy, DAG-discipline). Team Bravo's absorbed contributions: velocity-to-threshold, deadline forecast, 4h/1d RSI divergence, cross-book confluence scanning, structural (not string-match) test discipline.
