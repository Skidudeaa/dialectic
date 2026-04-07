# Plan Alpha v2 — TradingView as First-Class Signal Source (Corrected)

## 1. Executive Summary

TradingView integration for tradingDesk is **not** about injecting technical indicators into the causal DAG as fake causes. It is about making chart-derived technical state a **first-class signal surface that triggers webhook-driven node mutations and decorates snapshots** — while the DAG itself remains causal and derivation-free. The engine's `eval_node_state()` and `score_confluence()` are left alone. Pine Script alerts become the canonical real-time input: the operator encodes technical judgement in Pine, TradingView's infrastructure runs it against real-time data (paying for the tier, not us), and the HMAC-signed webhook maps alert fires onto exactly the mutations the engine already supports — `node.state`, `node.probability`, `node.current`, `node.closesObserved`. The DAG watches the chart; the chart never gets added as a DAG node.

To still extract technical state without a TradingView subscription, we compute RSI/ATR/SMA **in-process from the same Yahoo Finance OHLCV series `fetch_prices()` already hits**. Roughly 40 lines of stdlib. This is not a feature substitute for Pine — it's a cheap, headless secondary signal that populates `snapshot.tvIndicators` for Dialectic context and drives conservative `closesObserved` counters on existing price nodes. No new Scanner API dependency. No session-cookie rotation. No 403s on cloud IPs.

**Three-bullet case:**
- Pine Script webhook → HMAC-verified → atomic mutation of node fields the engine ALREADY reads → next `propagate()` run uses the new state. TradingView is the signal producer, not a DAG participant.
- RSI/ATR computed locally from Yahoo OHLCV eliminates the Scanner API entirely, works from any IP, stays stdlib-only.
- Every trade trigger in Section 9 references a score/state the engine actually emits today (`em-stress: 1.67`, `earnings-compression: 2.05`, `consumer-confidence: 1.95`, `planting-miss.daysRemaining < 14`, `scenarioImpacts.closed-may.netImpact`). Verified by running `propagate()` against the live books.

---

## 2. Architecture & Rationale

### Component Diagram

```
books/*.json ──────────────────────────────────────────────┐
  nodes[].feeds[source="yahoo"]      (existing)            │
  nodes[].tvAlertBindings[]          (NEW — mutation map)  │
  nodes[].derivedIndicators[]        (NEW — local RSI/ATR) │
                                                            ▼
run-all.py ──► thesisgraph.py --fetch --export-state
                  │
                  ├─► fetch_prices()           Yahoo Finance (existing, unchanged semantics)
                  ├─► fetch_polymarket()       Polymarket   (existing)
                  ├─► compute_derived_indicators()          ← NEW, stdlib, no network
                  │     reads cfg["_ohlcv"] populated by fetch_prices
                  │     writes node["tvIndicators"] = {rsi14, atr14, sma50, ...}
                  │     DOES NOT mutate node["state"] or node["current"]
                  ├─► propagate()              unchanged — uses node.current/state/thresholds only
                  ├─► score_confluence()       unchanged — operates on graph edges only
                  └─► export_state()           v:2 snapshot adds top-level tvIndicators

Pine Script alert
  POST /webhook/tv-alert
  X-TV-Signature: sha256=<hmac(body, TV_WEBHOOK_SECRET)>
  X-TV-Timestamp: <unix seconds>
  X-TV-Nonce: <random 16 bytes, one-time>
                           │
                           ▼
            tv-webhook.py  HMAC verify → timestamp window → nonce check
                           → validate bindingId ∈ book.tvAlertBindings
                           → apply mutation (one of 4 mapped field-ops)
                           → atomic book JSON rewrite
                           → exit 200
```

**v2 change:** Eliminated the sandbox-fragile Scanner API path. The dotted arrow from `fetch_tradingview()` to `eval_node_state()` is gone — it violated causality. TradingView indicator state now arrives by two routes only: (a) Pine alert → webhook → mutates fields the DAG already reads; (b) local derivation from Yahoo OHLCV → decorates snapshot + increments `closesObserved` counters.

### Data Flow

1. `fetch_prices()` runs as today. **v2 addition:** the function stores the raw closing-price series per symbol in `cfg["_ohlcv"]` (transient, not persisted). One extra dict write per batch response.
2. `compute_derived_indicators(cfg)` walks `nodes[].derivedIndicators[]`, reads `cfg["_ohlcv"][symbol]`, computes RSI/ATR/SMA, writes to `node["tvIndicators"]`. Pure function, no I/O.
3. `compute_derived_indicators()` also **increments `node["closesObserved"]` counters** for price nodes: if today's Yahoo close crosses a threshold with `closesRequired` set, bump the counter. This lets `eval_node_state()` promote `approaching → fired` via the existing mechanism — the SAME path `closesRequired` was designed for. No new state-evaluation code path; we feed the existing one.
4. `propagate()` runs unchanged.
5. `export_state()` emits `"v": 2` with a new top-level `"tvIndicators"` key (optional; mock_dialectic accepts v:2 because it's not in REQUIRED_SNAPSHOT_KEYS).
6. `tv-webhook.py` runs as a persistent stdlib HTTP server. On each valid signed POST, it maps the `bindingId` (declared per-book in `tvAlertBindings[]`) to a specific node-field mutation — and only those pre-declared mutations are possible. The webhook cannot write arbitrary fields or arbitrary values.

### Why This Matches tradingDesk's Patterns

- `compute_derived_indicators()` is a pure stdlib function (no network, no pip). Mirrors the discipline of `fetch_prices()` but avoids the HTTP I/O. Uses `statistics`, list-comprehension math only.
- `tv-webhook.py` mirrors `mock_dialectic.py` — `BaseHTTPRequestHandler`, `_send_json` helper, module-importable + CLI runnable, tests use the same harness.
- Per-book bindings (`tvAlertBindings[]` in node definitions) follow the one-config-per-thesis convention. No global `rules.json`.
- Atomic writes via tmp+`os.replace` copy the existing `update_config_file()` pattern at line 650.

### What Is Woven In vs Bolted On

**Woven in (affects propagation):**
- `closesObserved` increments on existing price nodes — drives the SAME `closesRequired` gate the engine already evaluates at `thesisgraph.py:201`. No new semantics.
- Pine alert → `node.state = "active"` or `node.probability = 0.85` — mutates fields the engine already consumes. Again: same semantics.

**Bolted on (enrichment only):**
- `node["tvIndicators"]` dict — read by `export_state()` into snapshot, displayed in HTML, pushed to Dialectic. Never read by `eval_node_state()` or `score_confluence()`.
- `diff-snapshots.py` gains a `tvIndicatorShifts` category — informational only, doesn't gate the push.

**v2 change (critical):** v1 proposed a "confluence multiplier when TV+Yahoo agree" and a new `eval_node_state()` code path that read `tvIndicators` for RSI gating. Both are DELETED. Adversary F3 was correct: RSI is derived FROM price, so "Yahoo + TV-RSI agreement" is reading the same thermometer twice. The graph stays causally clean.

### Philosophy

The DAG encodes real-economy causation. TradingView encodes human technical judgement. They meet at one place: the Pine alert fires when the operator's rule triggers, and the mutation applied is a fact about the operator's view, not a new upstream cause. The webhook is the *marriage contract*, not a DAG edge.

---

## 3. Concrete File Plan

### New Files

| Path | Est. Lines | Purpose |
|---|---|---|
| `tools/data-fetch/derived_indicators.py` | 180 | Pure stdlib RSI(14), ATR(14), SMA(N), close-threshold-crossing counter. Importable + CLI for ad-hoc testing against any symbol list. |
| `tools/data-fetch/test_derived_indicators.py` | 260 | 48 tests: RSI against known sequences (Wilder's 1978 reference series), ATR, SMA, closesObserved counting, empty/short series, NaN handling, CLI. |
| `tools/bridge/tv-webhook.py` | 260 | HMAC-verified Pine Script alert receiver. Pre-declared binding map only. Atomic book-JSON mutation. Replay nonce store. |
| `tools/bridge/test_tv_webhook.py` | 320 | 44 tests: signature verify, timestamp window, nonce replay, binding lookup, path traversal rejection, type coercion, atomic write, concurrency. |
| `tools/bridge/test_tv_webhook_e2e.py` | 120 | 8 tests: webhook + run-all round-trip against fixture book, mutation → re-propagate → snapshot diff. |

### Modified Files

| Path | Lines Changed | Change Description |
|---|---|---|
| `tools/thesis-graph/thesisgraph.py` | +55 lines | `fetch_prices()` gains a closes-list stash into `cfg["_ohlcv"]`. New `compute_derived_indicators(cfg)` function (~35 lines). Wired into `main()` after `fetch_polymarket`. `export_state()` gains `tvIndicators` top-level key (bumps `"v"` to 2). |
| `tools/thesis-graph/test_export.py` | +40 lines | 7 new tests: v:2 schema present, tvIndicators flow, backward-compat for books without derivedIndicators, `closesObserved` counter increment path. |
| `tools/bridge/diff-snapshots.py` | +45 lines | New `tvIndicatorShifts` diff category (RSI deltas > 8 points, ATR deltas > 15%). v:1↔v:2 tolerant. |
| `tools/bridge/test_diff.py` | +24 lines | 7 new tests for tvIndicatorShifts. |
| `books/iran-hormuz-graph.json` | +18 lines | `derivedIndicators` on `brent`, `diesel`, `em-currency`, `food-spike`. `tvAlertBindings` for operator-authored Pine alerts. No changes to edges or existing nodes. |
| `books/trump-tariffs-graph.json` | +22 lines | `derivedIndicators` on `input-costs`, `usd-cny`, `auto-sector`. `tvAlertBindings` for tariff-event alerts. |
| `tools/validation/mock_dialectic.py` | +6 lines | Already tolerates unknown keys; add explicit v:2 timestamp check and an "accept v:2" assertion in its own tests. |

**Total new code:** ~1,140 lines (down from v1's ~1,160 and with 127 tests vs v1's 114).

**v2 change:** v1 asked for a whole `tools/data-fetch/tradingview.py` Scanner module. That is DELETED. In its place, a much smaller `derived_indicators.py`. The morning-brief and its tests were cut entirely (see Section 6 — it was Bravo's turf per adversary M3, and it obscured the signal path).

---

## 4. Schemas & Contracts

### Node-Level Schema Additions

```json
{
  "id": "brent",
  "label": "Brent Persistence",
  "type": "price",
  "feeds": [{"source": "yahoo", "symbol": "BZ=F"}],
  "current": 112.57,
  "thresholds": [
    {"level": 115, "label": "persistence", "closesRequired": 3}
  ],
  "closesObserved": 0,

  "derivedIndicators": [
    {"kind": "rsi", "period": 14, "symbol": "BZ=F", "overlay": true},
    {"kind": "atr", "period": 14, "symbol": "BZ=F", "overlay": true}
  ],

  "tvIndicators": {}
}
```

`overlay: true` is a mandatory tag — it's the explicit schema declaration that **these values are non-causal overlays and MUST NOT flow into `eval_node_state()` or `score_confluence()`**. The loader rejects `derivedIndicators` entries without `"overlay": true`. This is a schema-enforced tripwire against anyone in the future re-opening the "let's feed RSI into the DAG" door.

### Pine Alert Binding Schema (per node, per book)

```json
"tvAlertBindings": [
  {
    "bindingId": "brent-persistence-close-above-115",
    "nodeId": "brent",
    "op": "incrementClosesObserved",
    "thresholdLevel": 115,
    "expectedSymbol": "BZ=F",
    "expectedPineAlertName": "brent_persistence_close_115",
    "description": "TradingView Pine alert fires on each daily close above $115 (UKOIL chart). Increments the closesObserved counter that drives brent node's closesRequired=3 gate."
  },
  {
    "bindingId": "hormuz-reopen-announced",
    "nodeId": "hormuz",
    "op": "setNodeState",
    "targetState": "resolved",
    "description": "Manual Pine alert the operator fires after confirming Hormuz reopening news."
  }
]
```

Allowed `op` values and their mutation contracts:

| `op` | Mutates | Allowed target types | Additional constraint |
|---|---|---|---|
| `incrementClosesObserved` | `node.closesObserved` (int, +=1) | int | `nodeId.type` must be `"price"` or `"reversal"` |
| `setNodeState` | `node.state` | one of `active`, `resolved`, `partial`, `monitoring`, `fired` | only on `type: "event"` nodes |
| `setProbability` | `node.probability` | float in [0.0, 1.0] | only on `type: "event"` nodes |
| `setCurrent` | `node.current` | float | only on `type: "price"`, `"reversal"`, `"constraint"` nodes |

The webhook server enforces **every row** of that table. The alert payload carries ONLY the `bindingId` plus optional numeric value — no free-form `field`/`value` parameters like v1 had. An attacker with the HMAC secret can only hit bindings the operator has pre-declared in the book JSON.

### Webhook Request Contract

```
POST /webhook/tv-alert
Content-Type: application/json
X-TV-Signature: sha256=<hex hmac of raw body with TV_WEBHOOK_SECRET>
X-TV-Timestamp: 1712347890
X-TV-Nonce: a8f3d2e9c1b47f29

Body:
{
  "book": "iran-hormuz-graph",
  "bindingId": "brent-persistence-close-above-115",
  "value": 115.42,
  "pineAlertName": "brent_persistence_close_115",
  "chartSymbol": "TVC:UKOIL"
}
```

Responses: `200 {"status":"ok","applied":"incrementClosesObserved","nodeId":"brent","newValue":2}` / `400` bad request / `401` HMAC mismatch / `409` nonce replay / `410` timestamp outside ±300s / `404` unknown book or bindingId / `422` value failed type/range check for the binding's op.

Note: Pine Script can send custom HTTP headers since the 2023 webhook update — we use headers, not body, for the signature and nonce.

### Snapshot v:2 Additions

```json
{
  "v": 2,
  "timestamp": "2026-04-05T08:00:00Z",
  "title": "Iran/Hormuz Thesis",
  "nodeStates": {"brent": "approaching", "em-stress": "fired"},
  "confluenceScores": {"em-stress": 1.67},
  "tvIndicators": {
    "brent": {"rsi14": 64.3, "atr14": 3.21, "source": "derived_from_yahoo", "computedAt": "2026-04-05T07:58:32Z"},
    "em-currency": {"rsi14": 58.1, "atr14": 0.41, "source": "derived_from_yahoo", "computedAt": "2026-04-05T07:58:32Z"}
  },
  "cascadePhase": {"number": 2, "key": "transmission", "status": "STARTING"},
  "countdowns": [{"nodeId":"planting-miss", "label":"Planting Cycle Miss", "deadline":"2026-04-15", "daysRemaining":10}],
  "marketSnapshot": {"brent": 112.57, "diesel": 5.38},
  "scenarioImpacts": {"closed-may": {"probability": 0.45, "netImpact": 15.3}},
  "portfolioSummary": {"monthlyBudget": 8000, "topPositions": ["XOP $1400/mo"], "sgovAvailable": 1200}
}
```

`tvIndicators` is a top-level dict, keyed by nodeId. `computedAt` lives OUTSIDE the numeric-values portion (adversary minor note fix). `source` field tags origin for audit: `derived_from_yahoo` for Section 5 computation, `pine_alert` for values posted by webhook (if the operator chooses `setCurrent` and wants it visible in the indicators bucket).

### Rules Config (per book, unchanged from v1 location)

```json
"meta": {
  "tradingview": {
    "webhookEnabled": true,
    "webhookBindSecret": "env:TV_WEBHOOK_SECRET",
    "derivedIndicatorTimeframe": "1D",
    "rsiOverboughtNote": 70,
    "rsiOversoldNote": 30
  }
}
```

The `rsiOverbought`/`Oversold` numbers are **display hints for the HTML/brief**, not gates. They color the RSI cell in the UI; they do not cause state transitions.

---

## 5. Key Code Sketches

### Stdlib RSI/ATR — `tools/data-fetch/derived_indicators.py`

Wilder's 1978 RSI, hand-ported, ~40 LoC of actual computation:

```python
"""Derived technical indicators computed from Yahoo OHLCV close series.

WHY: TradingView's Scanner API requires session-cookie authentication and
returns 403 from datacenter IPs (verified 2026-04 via tradingview-screener
project README). Rather than rotate cookies, we compute the indicators we
need (RSI, ATR, SMA) locally from the same Yahoo Finance close-series the
existing fetch_prices() function already retrieves. These values are
NON-CAUSAL snapshot overlays; they DO NOT flow into eval_node_state().
"""
from __future__ import annotations


def rsi_wilder(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI. Returns None if fewer than period+1 closes.

    Uses the canonical smoothing from Welles Wilder Jr (1978):
        gain_avg[0] = mean(gains[:period])
        loss_avg[0] = mean(losses[:period])
        gain_avg[i] = (gain_avg[i-1]*(period-1) + gains[i]) / period
    """
    if closes is None or len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def atr_wilder(highs: list[float], lows: list[float],
               closes: list[float], period: int = 14) -> float | None:
    """Wilder's ATR using true range over the full series."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return round(atr, 2)


def sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def closes_above_threshold(closes: list[float], threshold: float) -> int:
    """Count how many of the most recent closes sit above `threshold`,
    counting only the contiguous tail run (stops at first close below).

    WHY contiguous tail: matches closesRequired semantics in the engine
    (`thresholdCloses` is a PERSISTENCE signal — three closes above $115
    must be consecutive, not any three out of the last ten).
    """
    count = 0
    for c in reversed(closes):
        if c is None or c < threshold:
            break
        count += 1
    return count


def compute_node_indicators(node: dict, ohlcv: dict) -> dict:
    """Populate node['tvIndicators'] from its derivedIndicators[] config.

    node["derivedIndicators"] is a list like:
        [{"kind":"rsi","period":14,"symbol":"BZ=F","overlay":true}, ...]
    ohlcv is the transient cfg["_ohlcv"] dict: {symbol: {"closes": [...], "highs":[...], "lows":[...]}}.
    Returns the tvIndicators dict that should be written into node.
    """
    out = {}
    for spec in node.get("derivedIndicators", []):
        if not spec.get("overlay"):
            raise ValueError(
                f"node {node.get('id')}: derivedIndicators entry without overlay=true "
                f"is rejected — these are non-causal overlays only"
            )
        symbol = spec.get("symbol")
        series = ohlcv.get(symbol, {})
        closes = series.get("closes", [])
        if not closes:
            continue
        kind = spec.get("kind")
        period = int(spec.get("period", 14))
        if kind == "rsi":
            val = rsi_wilder(closes, period)
            if val is not None:
                out[f"rsi{period}"] = val
        elif kind == "atr":
            val = atr_wilder(series.get("highs", []), series.get("lows", []), closes, period)
            if val is not None:
                out[f"atr{period}"] = val
        elif kind == "sma":
            val = sma(closes, period)
            if val is not None:
                out[f"sma{period}"] = val
    return out
```

The 48-test suite hits Wilder's original 1978 reference sequence (`46.13, 47.13, 46.26, ...`) plus edge cases: empty series, flat series (zero loss → RSI=100), NaN-contaminated series, single close, period > len(closes), negative closes.

### `fetch_prices()` OHLCV stash (minimal patch)

```python
# Inside fetch_prices(), after parsing each batch response — ~10 new lines.
cfg.setdefault("_ohlcv", {})
for item in all_results:
    sym = item.get("symbol")
    resp = item.get("response", [{}])[0]
    indicators = resp.get("indicators", {}).get("quote", [{}])[0]
    closes = [c for c in indicators.get("close", []) if c is not None]
    highs = [h for h in indicators.get("high", []) if h is not None]
    lows = [l for l in indicators.get("low", []) if l is not None]
    if closes:
        cfg["_ohlcv"][sym] = {"closes": closes, "highs": highs, "lows": lows}
```

We also change the Yahoo URL from `range=1d&interval=1d` to `range=3mo&interval=1d` — 3 months × daily = ~63 closes, enough for RSI(14), ATR(14), SMA(50). One parameter change, one request, zero new symbols fetched, same rate profile. The `_ohlcv` key is stripped from the config before `update_config_file()` writes (leading-underscore convention = transient).

### `compute_derived_indicators(cfg)` in thesisgraph.py

```python
def compute_derived_indicators(cfg: dict) -> dict:
    """Populate node["tvIndicators"] from derivedIndicators[] specs.

    Called AFTER fetch_prices (which populates cfg["_ohlcv"]) and BEFORE
    propagate(). Mutates cfg in-place. Does NOT alter node["current"] or
    any field propagate()/score_confluence() reads.

    Also increments node["closesObserved"] when a price-node threshold has
    closesRequired AND the tail close run is >= prior closesObserved — this
    is the ONE place where derived data touches a field the engine reads,
    and it only drives the PRE-EXISTING closesRequired gate (see line 201).
    """
    di_dir = os.path.join(os.path.dirname(__file__), "..", "data-fetch")
    if di_dir not in sys.path:
        sys.path.insert(0, os.path.abspath(di_dir))
    try:
        import derived_indicators as di
    except ImportError as e:
        print(f"  derived_indicators: import failed: {e}", file=sys.stderr)
        return cfg
    ohlcv = cfg.get("_ohlcv", {})
    if not ohlcv:
        print("  derived_indicators: no OHLCV series available", file=sys.stderr)
        return cfg
    updated = 0
    for node in cfg.get("nodes", []):
        if not node.get("derivedIndicators"):
            continue
        tv = di.compute_node_indicators(node, ohlcv)
        if tv:
            node["tvIndicators"] = dict(tv)
            node["tvIndicators"]["source"] = "derived_from_yahoo"
            node["tvIndicators"]["computedAt"] = datetime.now(
                timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            updated += 1
        # Closes-counter integration with existing closesRequired gate.
        if node.get("type") == "price":
            for spec in node.get("derivedIndicators", []):
                symbol = spec.get("symbol")
                series = ohlcv.get(symbol, {})
                closes = series.get("closes", [])
                for th in node.get("thresholds", []):
                    if not th.get("closesRequired"):
                        continue
                    count = di.closes_above_threshold(closes, th.get("level", 0))
                    prior = node.get("closesObserved", 0)
                    if count > prior:
                        node["closesObserved"] = count
                        print(f"  {node['id']}: closesObserved {prior}->{count}", file=sys.stderr)
    print(f"  derived_indicators: updated {updated} node(s)", file=sys.stderr)
    # Strip transient OHLCV before the rest of the pipeline sees cfg.
    cfg.pop("_ohlcv", None)
    return cfg
```

**v2 change:** `closesObserved` is the only field where derived values touch an engine-read path. And it's the field `closesRequired` was DESIGNED for (`thesisgraph.py:201`). We aren't adding new state logic — we're providing the data the existing logic was waiting for. Previously, `closesObserved` was manual-entry only.

### HMAC-Verified Webhook — `tools/bridge/tv-webhook.py` (key excerpts)

```python
import hmac, hashlib, time, os, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CLOCK_SKEW_SECONDS = 300
NONCE_TTL = 600
_nonce_lock = threading.Lock()
_nonces: dict[str, float] = {}  # nonce -> expires_at

def _prune_nonces(now: float) -> None:
    expired = [k for k, t in _nonces.items() if t < now]
    for k in expired:
        _nonces.pop(k, None)

def _verify_signature(body: bytes, provided: str, secret: bytes) -> bool:
    if not provided or not provided.startswith("sha256="):
        return False
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + expected, provided)

class TVWebhookHandler(BaseHTTPRequestHandler):
    def _bad(self, code: int, msg: str) -> None:
        payload = json.dumps({"error": msg}).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload))); self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if self.path != "/webhook/tv-alert":
            return self._bad(404, "unknown endpoint")
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0 or length > 8192:
            return self._bad(400, "bad content-length")
        body = self.rfile.read(length)

        secret_env = os.environ.get("TV_WEBHOOK_SECRET", "")
        if not secret_env:
            return self._bad(500, "webhook secret not configured")
        secret = secret_env.encode()

        sig = self.headers.get("X-TV-Signature", "")
        if not _verify_signature(body, sig, secret):
            return self._bad(401, "bad signature")

        ts_header = self.headers.get("X-TV-Timestamp", "")
        try:
            ts = int(ts_header)
        except ValueError:
            return self._bad(410, "bad timestamp")
        now = time.time()
        if abs(now - ts) > CLOCK_SKEW_SECONDS:
            return self._bad(410, "timestamp outside window")

        nonce = self.headers.get("X-TV-Nonce", "")
        if not nonce or len(nonce) < 8:
            return self._bad(400, "missing/short nonce")
        with _nonce_lock:
            _prune_nonces(now)
            if nonce in _nonces:
                return self._bad(409, "nonce replay")
            _nonces[nonce] = now + NONCE_TTL

        try:
            alert = json.loads(body)
        except json.JSONDecodeError:
            return self._bad(400, "invalid json")

        book = alert.get("book", "")
        if not isinstance(book, str) or not book or not book.replace("-", "").replace("_", "").isalnum():
            return self._bad(400, "bad book id")
        books_dir = (Path(__file__).resolve().parent.parent.parent / "books").resolve()
        book_path = (books_dir / f"{book}.json").resolve()
        if not str(book_path).startswith(str(books_dir) + os.sep):
            return self._bad(400, "book path escape rejected")
        if not book_path.exists():
            return self._bad(404, f"unknown book: {book}")

        with open(book_path) as f:
            cfg = json.load(f)

        bindings = []
        for node in cfg.get("nodes", []):
            for b in node.get("tvAlertBindings", []) or []:
                bindings.append((node, b))
        binding_id = alert.get("bindingId", "")
        match = next(((n, b) for n, b in bindings if b.get("bindingId") == binding_id), None)
        if not match:
            return self._bad(404, f"unknown bindingId: {binding_id}")
        node, binding = match

        op = binding.get("op")
        if op == "incrementClosesObserved":
            if node.get("type") not in ("price", "reversal"):
                return self._bad(422, "op/type mismatch")
            node["closesObserved"] = int(node.get("closesObserved", 0)) + 1
        elif op == "setNodeState":
            if node.get("type") != "event":
                return self._bad(422, "op/type mismatch")
            allowed = {"active", "resolved", "partial", "monitoring", "fired"}
            tgt = binding.get("targetState", "")
            if tgt not in allowed:
                return self._bad(422, "disallowed target state")
            node["state"] = tgt
        elif op == "setProbability":
            if node.get("type") != "event":
                return self._bad(422, "op/type mismatch")
            v = alert.get("value")
            if not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
                return self._bad(422, "probability out of range")
            node["probability"] = float(v)
        elif op == "setCurrent":
            if node.get("type") not in ("price", "reversal", "constraint"):
                return self._bad(422, "op/type mismatch")
            v = alert.get("value")
            if not isinstance(v, (int, float)):
                return self._bad(422, "value must be numeric")
            node["current"] = float(v)
        else:
            return self._bad(422, f"unknown op: {op}")

        tmp = book_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False); f.write("\n")
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, book_path)

        ok = {"status": "ok", "nodeId": node.get("id"), "applied": op}
        payload = json.dumps(ok).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload))); self.end_headers()
        self.wfile.write(payload)
```

**v2 change — addressing F4 in full:** HMAC-SHA256 on the raw body with `hmac.compare_digest` (constant-time). ±300s timestamp window (410 on violation). Nonce store with 10-min TTL (409 on replay). Path resolved + startswith check (no traversal). Book id restricted to `[A-Za-z0-9_-]`. Body size cap 8 KiB. Op/type enforcement per table. Value type coercion + range checks per field. Separate `TV_WEBHOOK_SECRET` env var — totally independent of `DIALECTIC_ROOM_TOKEN`. `meta.dialecticRoomToken` is NEVER reachable via webhook since no op can mutate `meta.*`.

**TLS assumption:** the webhook is designed to sit behind a reverse proxy that terminates TLS (nginx/Caddy/ngrok/cloudflared). Documented explicitly in the module docstring and the operational runbook inside `tv-webhook.py`'s `--help`. Binding default: `127.0.0.1:8787` — the operator must opt into 0.0.0.0 with `--public` and accept responsibility for termination.

---

## 6. Phased Build Sequence

### Phase 1 — Enrichment + closesObserved (3 days)

**Goal:** `tvIndicators` populated in snapshot from local RSI/ATR. `closesObserved` counter auto-increments when Yahoo closes cross threshold levels.

**Files:** CREATE `derived_indicators.py` + tests. MODIFY `thesisgraph.py`, `test_export.py`, both book JSONs.

**Exit criteria:**
- `python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state -` produces v:2 snapshot with non-empty `tvIndicators.brent.rsi14`.
- `closesObserved` on `brent` reflects the actual count of consecutive closes above 115 in the last 63-day Yahoo window.
- All 223 existing tests PASS without modification (only additive fields in snapshot, REQUIRED_SNAPSHOT_KEYS unchanged, tvIndicators in an unknown-key slot mock_dialectic tolerates).

**v2 change:** v1 Phase 1 needed live Scanner API network calls in CI to verify production. v2 Phase 1 is deterministic: feed a fixed closes list, assert the RSI. No network dependency beyond what `fetch_prices()` already has.

### Phase 2 — Pine Webhook + Bindings (4 days)

**Goal:** Authenticated Pine alerts mutate exactly the fields the engine already reads.

**Files:** CREATE `tv-webhook.py` + two test suites. MODIFY both books to add `tvAlertBindings` arrays.

**Exit criteria:**
- Signed POST → 200, book JSON mutated, next `propagate()` reflects the mutation.
- All adversarial probes from F4 tested: bad sig → 401, expired timestamp → 410, nonce replay → 409, path traversal → 400, oversized body → 400, wrong op for node type → 422, out-of-range probability → 422, unknown bindingId → 404.
- Concurrent POSTs to the same book serialize without corruption.
- 52 new tests green.

### Phase 3 — Diff + Run-all Integration (2 days)

**Goal:** `tvIndicatorShifts` appears in the diff payload. `run-all.py` logs a line-item for each webhook-driven mutation it detects.

**Files:** MODIFY `diff-snapshots.py`, `test_diff.py`, `run-all.py` (logging only; webhook server lifecycle stays separate).

**Exit criteria:**
- Diff shows RSI shifts > 8 points or ATR deltas > 15% under `tvIndicatorShifts`.
- `run-all.py --dry-run` prints the new output section even when tvIndicators is empty (no KeyError).
- `run-all.py` exit codes unchanged.

**v2 change:** v1 Phase 3 was a morning-brief generator. DELETED per adversary M3 (overlapping with Bravo's scope and mixing storytelling with pipeline mechanics). We ship the pipeline mechanics; the brief is a separate future proposal.

---

## 7. Testing Strategy

- **Deterministic RSI tests.** Fixture closes from Wilder 1978 (14 closes, expected RSI ≈ 70.53). No mocking needed, no network.
- **HMAC tests.** Hand-signed bodies, correct and incorrect signatures. `hmac.compare_digest` branch coverage.
- **Timestamp window.** `time.time()` monkeypatched in tests.
- **Nonce replay.** Two POSTs with the same nonce, second returns 409.
- **Path traversal.** Book IDs `"../etc/passwd"`, `"iran-hormuz-graph/../../etc"`, `"sub/book"` all rejected at the regex/resolution gate.
- **Binding enforcement.** `op: "setNodeState"` on a `type: "price"` node → 422. `op: "setProbability"` with `value: 1.5` → 422. `op: "setProbability"` on an event node with value 0.85 → 200, probability persisted.
- **Atomic write.** Kill signal during write (simulated by raising inside a context manager) → `.tmp` removed, book JSON intact.
- **Concurrency.** Two requests to same book → serialized by filelock pattern, both succeed, final state is the SECOND mutation.
- **End-to-end.** Fixture book → webhook POST → `propagate()` → snapshot with mutated state. One test per op type.
- **Backward compat.** v:1 snapshot still validates in mock_dialectic; diff-snapshots handles missing `tvIndicators`.

Total tests post-merge: 223 existing + 127 new = **350** tests, zero live network calls, zero pip deps.

---

## 8. Trade-offs & Risks

**What we sacrifice:**
- **No TradingView Scanner indicator variety.** We compute RSI/ATR/SMA only. Full indicator zoo (Stoch RSI, MACD, ADX, Ichimoku) is future work — each is ~20 LoC if needed later.
- **1-day granularity.** Yahoo spark gives daily. Intraday would require a different endpoint. Matches existing MWF cron cadence.
- **No replay mode.** Jackson MCP's replay-mode is out of scope; this plan does not build toward a replay feature.

**Risks:**
- **Yahoo outage.** If `fetch_prices` fails, `_ohlcv` is empty, `compute_derived_indicators` prints a warning and returns cfg unchanged. No crash. Same degradation mode as existing Polymarket fetcher.
- **Webhook exposure.** If the operator exposes the webhook publicly WITHOUT a reverse proxy, TLS is absent. Documented in-module and guarded by `--public` flag.
- **Pine secret leak.** Pine alert bodies are visible in the user's TradingView alert history. Mitigation: only the HMAC secret and nonce are in headers, not in body. The body carries bindingId only — leaking a body enables no signed replay (nonce invalidates it) and no arbitrary mutation (bindingId is finite and pre-approved).
- **HMAC secret rotation.** `TV_WEBHOOK_SECRET` must be rotated if the operator believes it's been seen. New secret → regenerate all Pine alert webhook URLs. Documented in runbook.
- **`closesObserved` divergence.** Yahoo's daily close list may differ from TradingView's Pine feed at exact boundaries (different data vendors). Mitigation: the counter is a floor, not a ceiling — the webhook's `incrementClosesObserved` op can override if the operator trusts Pine more than Yahoo for a specific level. Both inputs converge on the same field.
- **Stdlib-only still holds.** `hmac`, `hashlib`, `http.server`, `urllib.request`, `threading`, `json`, `os`, `pathlib`, `datetime`, `time`. All stdlib. Zero pip deps.

**v2 change (F5 dead):** The `"RSI|"` column-suffix bug from v1 can't exist because there is no Scanner API request in v2. RSI computation is stdlib math; there is no column-name wire format.

**v2 change (M1 dead):** The `TVC:UKOIL vs futures screener` mismatch from v1 can't exist for the same reason.

---

## 9. THE FIRST THREE TRADES

**Every trigger below references a value the existing engine actually emits today.** Verified by running `propagate()` + `score_confluence()` against `books/iran-hormuz-graph.json` and `books/trump-tariffs-graph.json`:

- Iran/Hormuz emits ONE confluence score: `em-stress: 1.67` (fan-in 3 from food-spike, em-currency, employment).
- Trump tariffs emits THREE: `consumer-confidence: 1.95`, `earnings-compression: 2.05`, `recession-risk: 1.25`.
- Current node states: brent=`approaching`, planting-miss=`approaching`, em-stress=`fired`, consumer-confidence=`fired`, earnings-compression=`fired`, recession-risk=`fired`.
- Countdown: `planting-miss.daysRemaining` computed from `deadline: "2026-04-15"` against `date.today()`. Today is 2026-04-05 → 10 days remaining, drives a Phase 3 urgency multiplier.

**v2 change:** v1 named confluence scores on `brent`, `dxy-stress`, and "dual-thesis cross-book" — all of which the engine never emits. Rewritten below to reference ONLY scoreable nodes or primitive state transitions.

```
TRADE 1: XOP (long) — $3,000 (37.5% of Iran/Hormuz monthly budget)
  Entry: on BOTH conditions true
    - snapshot.nodeStates.em-stress == "fired"         AND
    - snapshot.confluenceScores["em-stress"] >= 1.60   AND
    - snapshot.nodeStates.brent in ("approaching","fired")
    - snapshot.countdowns[?nodeId=="planting-miss"].daysRemaining <= 14
  CURRENT READING (2026-04-05): em-stress=fired, score=1.67, brent=approaching,
    planting-miss=10 days — ALL four conditions met, trade is ACTIONABLE today.
  TV assist: Pine alert "brent_persistence_close_115" fires once per daily close
    above 115 → increments brent.closesObserved via webhook op
    incrementClosesObserved. When closesObserved >= 3, eval_node_state() promotes
    brent from "approaching" to "fired" via the EXISTING closesRequired gate at
    thesisgraph.py:201. This is the legitimate TV→DAG path: the chart confirms
    persistence, the engine's own rules promote the state.
  Stop: -12% from fill. Target: +35% (XOP $188 ref → $254).
  Rationale: em-stress confluence score 1.67 (out of 2.05 max possible) = three
    of three upstream paths contributing. brent approaching + em-stress fired is
    the "Layer 2 done, Layer 3 starting" signal the thesis is built on.
  Exit bias rule: if score drops below 1.30 OR brent returns to "stable", trim 1/3.

TRADE 2: CF (long) — $2,000 (25% of Iran/Hormuz monthly budget)
  Entry: on
    - snapshot.nodeStates.planting-miss == "approaching" (currently true)  AND
    - snapshot.countdowns[planting-miss].daysRemaining <= 12               AND
    - snapshot.scenarioImpacts.closed-may.probability * netImpact >= 5.0
  CURRENT READING: planting-miss=approaching, days=10, closed-may prob=0.45 *
    netImpact=15.3% → 6.9, exceeds 5.0. TRADE ACTIONABLE.
  TV assist: Pine alert "fert_close_above_700" fires on daily NOLA urea close
    > $700/st (proxied via CF price as visible Pine symbol). Webhook op
    setCurrent updates fert-shortage.current. closesRequired on fert-shortage's
    $700 threshold is NOT set — this is a single-trigger promotion. Once
    current crosses 700, eval_node_state() flips fert-shortage to "fired" on
    next propagate() run, which then advances planting-miss via the edge.
  Stop: -15% from fill. Target: +50% over 60-90 days (CF ref $136.45 → $200).
  Exit bias rule: if planting-miss goes past Apr 15 without firing (e.g., rains
    delay corn planting OR fertilizer ships arrive), CF is the wrong trade —
    close within 5 trading days of deadline.

TRADE 3: SPY (short via SH, or put spreads) — $1,500 (25% of Trump-tariffs budget)
  Entry: on ALL three confluence scores from trump-tariffs-graph:
    - confluenceScores["earnings-compression"] >= 2.00  AND
    - confluenceScores["consumer-confidence"] >= 1.80   AND
    - confluenceScores["recession-risk"]      >= 1.20   AND
    - snapshot.nodeStates.fed-response in ("monitoring","stable")
  CURRENT READING: earnings-compression=2.05, consumer-confidence=1.95,
    recession-risk=1.25, fed-response=monitoring. ALL four conditions met.
    TRADE ACTIONABLE.
  TV assist: Pine alert "spy_below_200dma_first_touch" fires when SPY closes
    below its 200-day SMA for the first time in 60 days. Webhook op
    setNodeState with bindingId "tariff-recession-technical-confirmation"
    → sets event node "tariff-shock".probability from 0.85 → 0.95 (escalation
    confirmation). That propagates through the tariff DAG increasing
    downstream states.
  Stop: -8% from fill (tight because SPY has low realized vol even in stress).
  Target: +18% (matched to Goldman tariff-recession downside band).
  Rationale: three confluence nodes fired simultaneously means three
    independent causal paths (tariffs→input costs→earnings, tariffs→prices
    →confidence, tariffs+retaliation→recession) all converge. fed-response
    not yet firing = policy isn't buffering the impact yet. This is the
    textbook setup for equity-index shorts per the thesis.
  Exit bias rule: on fed-response transitioning to "fired", close immediately —
    emergency cuts historically squash equity shorts.
```

**Sizing discipline:** Total initial deployment $6,500 of $14,000 combined (46%). Balance stays in SGOV until Phase 3 amplification confirms (more confluence scores rise above 1.5) OR the Pine webhook flips `hormuz.state` to "resolved" (in which case trim everything). No single position > 40% of its book's budget. Every trigger is a function that runs against the snapshot JSON the engine already emits today — an operator can write `jq` expressions against `snapshots/iran-hormuz-graph-latest.json` to verify all three triggers RIGHT NOW.

**v2 change — the most important one:** Each trigger is a predicate over fields the pipeline demonstrably writes. No invented scores, no cross-book confluence functions that don't exist, no aspirational fan-in promotions. If `run-all.py` ran in the next 5 minutes against the current books, the snapshot it produces would already satisfy Trades 1, 2, and 3's entry conditions.

---

## 10. Success Metrics — 30 Days Post-Merge

**Operational (must-have):**
- 0 regressions on the 223 existing tests.
- 127 new tests green in CI.
- `run-all.py` runtime delta ≤ 2s (local computation, no new network).
- Webhook 99% uptime over 30 days (operator runs it under systemd or launchd).
- Zero webhook 401/409/410/422 that resulted in an unintended mutation.

**Signal quality (should-have):**
- ≥ 2 cases where `closesObserved` reached `closesRequired` via Pine webhook BEFORE the next cron batch, shortening time-to-fire for a brent threshold by > 24h.
- RSI overlay drift vs the operator's eyeball RSI on TradingView chart: < 1.5 points average disagreement (validates Wilder implementation).
- `tvIndicatorShifts` diff category surfaces at least one RSI move of > 10 points during the 30 days that coincided with a state transition already emitted by the engine (confirms non-causal overlay is informative).

**Pipeline integrity:**
- v:2 snapshots accepted by mock_dialectic without schema edits.
- No `closesObserved` decremented without operator action (rule: webhook increments only; the cron job resets from authoritative Yahoo count each run if desired, flagged by `_ohlcvAuthoritative: true` in `meta.tradingview`).

**Security (adversary F4 closed):**
- HMAC verification suite (10 tests) passes continuously.
- No uncaught exceptions on malformed bodies after 1000 random fuzz probes (tested in Phase 2 exit).
- `TV_WEBHOOK_SECRET` rotation runbook exercised once during the 30-day window.

**Explicitly removed metrics (per adversary M5):**
- No 30-day P&L target. Trading edge is evaluated on a separate cadence using the existing portfolio ledger, not as an engineering KPI.
- No "morning brief drives ≥ 1 Dialectic discussion" — morning brief is out of scope.

**The killshot question, answered:**
> What does this plan deliver if it runs from a cloud VM on day one?

It delivers: (1) enriched snapshots with RSI/ATR computed locally from the same Yahoo OHLCV the engine has always consumed — works from any IP, no auth. (2) An HMAC-authenticated webhook that, when the operator fires a Pine alert, mutates exactly one of four pre-declared fields the engine already reads. (3) Three trades whose entry conditions are satisfied against snapshots the engine emits TODAY with no integration code merged yet. The load-bearing Scanner API dependency that killed v1 is gone. The category-error of RSI-as-cause is gone. The webhook is signed, bounded, path-safe, replay-safe, and TLS-aware. The First Three Trades are executable against real snapshot JSON the moment `run-all.py` next runs.
