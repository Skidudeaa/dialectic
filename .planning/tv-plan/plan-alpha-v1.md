# Plan Alpha v1 — Deep Graph Integration: TradingView as 4th Data Source

## 1. Executive Summary

TradingView integration for tradingDesk is not about bolting chart screenshots onto reports. It is about making chart-derived technical indicators — RSI, ATR, MACD signal, volume — first-class inputs into the causal DAG propagation engine. Every thesis node that today pulls a price from Yahoo Finance can optionally also pull chart state from TradingView's scanner API. That chart state flows through `fetch_tradingview()` the same way `fetch_polymarket()` flows — it mutates `cfg` before propagation runs, so the graph state is computed against richer evidence. The reverse channel — Pine Script alerts firing webhook calls that mutate node state in real time — closes the loop: the chart watches the thesis, and the thesis watches the chart simultaneously.

**Three-bullet case:**
- Scanner API (no desktop, no CDP, stdlib `urllib` POST) works headless in cron — the whole pipeline stays Python-only
- Chart indicators as node inputs change graph propagation results, not just the snapshot attachment
- Pine Script webhook receiver turns TradingView alerts into live node state mutations, eliminating manual intervention lag

---

## 2. Architecture & Rationale

### Component Diagram

```
books/*.json  ──────────────────────────────────────────┐
  nodes[].feeds[source="tradingview"]                   │
                                                         ▼
run-all.py ──► thesisgraph.py ──► fetch_prices()       [Yahoo Finance]
                              ──► fetch_polymarket()    [Polymarket Gamma API]
                              ──► fetch_tradingview()   [TV Scanner POST API]  ← NEW
                              ──► propagate()           [uses all 3 feed types]
                              ──► export_state()        [snapshot v:2 with tvIndicators]
                              ──► diff-snapshots.py
                              ──► push-to-dialectic.py

Pine Script alert (TV) ──► POST /webhook/alert ──► tv-webhook.py ──► atomic book JSON write
                                                                    ──► triggers run-all.py step (optional)

tv-morning-brief.py ──► reads latest snapshot ──► grades signposts vs TV indicator state
                    ──► pushes structured brief to Dialectic room (separate from snapshot)
```

### Data Flow

1. `run-all.py` calls `thesisgraph.py --fetch --export-state` per book
2. `thesisgraph.py` calls three fetch functions in sequence: Yahoo (prices) → Polymarket (probabilities) → TradingView (indicator values)
3. `fetch_tradingview(cfg)` scans `nodes[].feeds` for `source="tradingview"` entries, collects (symbol, screener, indicator) tuples, batches them into POST requests to `scanner.tradingview.com/{screener}/scan`, writes results back into `node["tvIndicators"]` dict
4. `propagate(cfg)` runs — `eval_node_state()` is extended to read `node["tvIndicators"]` for nodes with TV feeds. RSI > 70 on a price node can promote it to "approaching"; RSI + MACD signal cross = "fired"
5. `export_state()` emits `"v": 2` snapshot with new `tvIndicators` top-level key
6. Separately, `tv-webhook.py` (persistent process) receives Pine Script POST alerts and atomically writes node state overrides into book JSON — the next run picks them up
7. `tv-morning-brief.py` reads the latest snapshot + TV indicator readings and generates a Dialectic-formatted brief per thesis

### Why This Approach Matches tradingDesk's Patterns

The existing pattern: `fetch_polymarket()` lives in `tools/data-fetch/`, is imported dynamically by `thesisgraph.py` via `sys.path` insert, mutates `cfg`, runs alongside `fetch_prices()`. `fetch_tradingview()` is the exact same pattern. Same module structure, same import mechanism, same cfg mutation return, same `print(..., file=sys.stderr)` feedback style, same no-bare-except discipline.

The node feed schema already has `"source"` as the discriminator field. Adding `"tradingview"` as a new source requires zero changes to `validate_config()` — we just add `"tradingview"` handling in the new module. The scanner API requires a POST not a GET, but that's one extra line in `urllib.request`.

### What Is Woven Into the Graph vs Bolted On

**Woven in (affects propagation):**
- TV indicator values stored in `node["tvIndicators"]` — read by `eval_node_state()` extension
- New node state evaluation path: `"price"` nodes can use TV RSI as a secondary confirmation gate (`closesRequired` analog but for RSI threshold crossings)
- Confluence scoring extended: when `score_confluence()` sees a node has both Yahoo price AND TV RSI signals agreeing, confluence score gets a multiplier

**Bolted on (enrichment only, doesn't affect propagation):**
- `tvIndicators` in snapshot JSON — flows to Dialectic as extra context
- Morning brief — reads computed state, doesn't change it
- Webhook receiver — mutates book JSON directly, but that mutation is just changing `node["state"]` or `node["probability"]`, which propagation already handles

### Philosophy

Chart evidence should change your graph state, not just decorate it.

---

## 3. Concrete File Plan

### New Files

| Path | Est. Lines | Purpose |
|---|---|---|
| `tools/data-fetch/tradingview.py` | 280 | TV scanner fetch module: POST to scanner API, parse indicator columns, return by symbol. Mirrors polymarket.py exactly. CLI standalone. |
| `tools/data-fetch/test_tradingview.py` | 220 | 40 tests: mock HTTP, column parsing, multi-symbol batch, screener routing, error handling, CLI |
| `tools/bridge/tv-webhook.py` | 180 | Pine Script alert webhook receiver: BaseHTTPRequestHandler, parse alert JSON, atomic node state write to book JSON |
| `tools/bridge/test_tv_webhook.py` | 160 | 28 tests: receipt parsing, atomic write, concurrent requests, bad auth, malformed payload |
| `tools/bridge/tv-morning-brief.py` | 200 | Per-thesis morning brief generator: reads snapshot + TV indicators, grades signposts, outputs Dialectic-formatted brief |
| `tools/bridge/test_tv_morning_brief.py` | 120 | 22 tests: brief generation, signpost grading, Dialectic push format |

### Modified Files

| Path | Lines Changed | Change Description |
|---|---|---|
| `tools/thesis-graph/thesisgraph.py` | +65 lines | Add `fetch_tradingview(cfg)` function (~50 lines) at line ~745 (after `fetch_polymarket`). Add call in `main()` at line ~2299 (3rd fetch step). Add `tvIndicators` to `export_state()` output at line ~530. Extend `eval_node_state()` for `"price"` nodes to check `node.get("tvIndicators")` for RSI confirmation gate (~12 lines at line ~200). |
| `tools/thesis-graph/test_export.py` | +30 lines | 6 new tests for `tvIndicators` in snapshot output, v:2 schema, TV-feed node state evaluation |
| `books/iran-hormuz-graph.json` | +12 lines | Add TV feeds to `brent` node (RSI + ATR on BZ=F futures equiv), `dxy-stress` node (DXY RSI), `demand-destruction` node (WTI RSI collapse signal) |
| `books/trump-tariffs-graph.json` | +10 lines | Add TV feeds to `input-costs` node (XLI RSI), `consumer-confidence` node (SPY RSI on daily) |
| `tools/validation/mock_dialectic.py` | +8 lines | Update `REQUIRED_SNAPSHOT_KEYS` to tolerate `"v": 2` schema (add `tvIndicators` as optional, not required) |

---

## 4. Schemas & Contracts

### Extended Node Feed Schema for TV Sources

```json
{
  "id": "brent",
  "label": "Brent Persistence",
  "type": "price",
  "feeds": [
    {"source": "yahoo", "symbol": "BZ=F"},
    {
      "source": "tradingview",
      "symbol": "TVC:UKOIL",
      "screener": "futures",
      "timeframe": "1D",
      "indicators": ["RSI", "ATR", "MACD.macd", "MACD.signal"],
      "thresholds": {
        "RSI": {"approaching": 60, "fired": 70},
        "MACD.macd": {"crossAboveSignal": true}
      }
    }
  ],
  "tvIndicators": {}
}
```

The `tvIndicators` field starts empty in the book JSON. `fetch_tradingview()` populates it at runtime (not persisted back unless `--update-config` is passed). The `thresholds` sub-object defines when TV indicator readings should influence node state evaluation.

Valid `screener` values: `"america"` (US equities), `"forex"`, `"futures"`, `"crypto"`, `"cfd"`.

Column name format: `"RSI"` (appended as `"RSI|"` in API call for 1D), `"RSI|60"` for 1H.

### Snapshot v:2 Additions

```json
{
  "v": 2,
  "timestamp": "2026-04-05T08:00:00Z",
  "title": "Iran/Hormuz Thesis",
  "nodeStates": {"brent": "approaching"},
  "confluenceScores": {"em-stress": 1.45},
  "tvIndicators": {
    "brent": {
      "RSI": 68.4,
      "ATR": 3.21,
      "MACD.macd": 1.23,
      "MACD.signal": 0.88,
      "fetchedAt": "2026-04-05T07:58:32Z"
    },
    "dxy-stress": {
      "RSI": 54.1,
      "ATR": 0.41,
      "fetchedAt": "2026-04-05T07:58:33Z"
    }
  },
  "cascadePhase": {"number": 2, "key": "transmission", "status": "ACTIVE"},
  "countdowns": [],
  "marketSnapshot": {"brent": 112.57},
  "scenarioImpacts": {},
  "portfolioSummary": {}
}
```

Backward compatibility: `"v": 1` snapshots (no `tvIndicators`) continue to work in `diff-snapshots.py` and `push-to-dialectic.py`. The diff script gains a new optional diff category `tvIndicatorShifts`. The mock Dialectic server accepts both versions.

### Pine Script Webhook Payload Contract

TradingView Pine Script alert webhooks POST JSON to a URL you configure. The contract `tv-webhook.py` accepts:

```json
{
  "book": "iran-hormuz-graph",
  "node": "brent",
  "field": "state",
  "value": "active",
  "indicator": "RSI",
  "indicatorValue": 71.3,
  "symbol": "TVC:UKOIL",
  "timeframe": "1D",
  "alertName": "Brent RSI > 70 — escalation zone",
  "timestamp": "2026-04-05T08:15:00Z",
  "token": "webhook-secret-from-env"
}
```

Required fields: `book`, `node`, `field`, `value`, `token`.
Optional: `indicator`, `indicatorValue`, `symbol`, `timeframe`, `alertName`, `timestamp`.

The `token` field must match `TV_WEBHOOK_TOKEN` environment variable — 401 on mismatch.

`field` is restricted to: `"state"`, `"probability"`, `"current"` — any other field rejected with 400.

### Rules Config (in book JSON meta, not global)

```json
"meta": {
  "tradingview": {
    "primaryTimeframe": "1D",
    "defaultScreener": "futures",
    "biasRules": {
      "rsi_overbought": 70,
      "rsi_oversold": 30,
      "macd_crossover_weight": 0.3
    },
    "webhookEnabled": true
  }
}
```

Rules live per-book in `meta.tradingview`. No global `rules.json` — this respects the existing convention of one-config-per-thesis and avoids a new global state file that would complicate multi-thesis operation.

---

## 5. Key Code Sketches

### `fetch_tradingview(cfg)` — in `thesisgraph.py`

```python
def fetch_tradingview(cfg: dict) -> dict:
    """Fetch indicator values from TradingView scanner API for nodes with
    tradingview feeds. Mutates cfg by populating node["tvIndicators"].

    WHY separate from fetch_prices: TradingView provides technical indicator
    readings (RSI, ATR, MACD) that are dimensionally different from prices
    and require a POST to the screener API with explicit column requests.
    Different API, different semantics, different node field updated.
    """
    tv_dir = os.path.join(os.path.dirname(__file__), "..", "data-fetch")
    tv_dir = os.path.abspath(tv_dir)

    if not os.path.isfile(os.path.join(tv_dir, "tradingview.py")):
        print("  tradingview: module not found, skipping", file=sys.stderr)
        return cfg

    if tv_dir not in sys.path:
        sys.path.insert(0, tv_dir)

    try:
        import tradingview as tv
    except ImportError as e:
        print(f"  tradingview: import failed: {e}", file=sys.stderr)
        return cfg

    # Collect (symbol, screener, indicators, node_id) from all TV feeds
    requests_by_screener: dict = {}  # screener -> list of {symbol, indicators, node_ids}
    node_map = {n["id"]: n for n in cfg.get("nodes", [])}

    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") != "tradingview":
                continue
            symbol = feed.get("symbol")
            screener = feed.get("screener", cfg.get("meta", {}).get(
                "tradingview", {}).get("defaultScreener", "america"))
            indicators = feed.get("indicators", ["RSI", "close", "ATR"])
            if not symbol:
                continue
            key = (symbol, tuple(sorted(indicators)))
            requests_by_screener.setdefault(screener, {})[key] = {
                "symbol": symbol,
                "indicators": indicators,
                "node_ids": requests_by_screener.get(screener, {}).get(
                    key, {}).get("node_ids", []) + [node["id"]],
            }

    if not requests_by_screener:
        print("  tradingview: no tradingview feeds found, skipping", file=sys.stderr)
        return cfg

    total_nodes = sum(len(v) for v in requests_by_screener.values())
    print(f"  tradingview: fetching {total_nodes} symbol(s)...", file=sys.stderr)

    count = 0
    for screener, sym_map in requests_by_screener.items():
        results = tv.fetch_indicators(
            screener=screener,
            requests=list(sym_map.values()),
        )
        for symbol, indicator_values in results.items():
            # Find all nodes that use this symbol in a TV feed
            for node in cfg.get("nodes", []):
                for feed in node.get("feeds", []):
                    if feed.get("source") == "tradingview" and feed.get("symbol") == symbol:
                        node.setdefault("tvIndicators", {}).update(indicator_values)
                        node["tvIndicators"]["fetchedAt"] = datetime.now(
                            timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        print(f"  tradingview: {node['id']}: RSI={indicator_values.get('RSI', '?'):.1f}",
                              file=sys.stderr)
                        count += 1

    print(f"  tradingview: updated {count} node(s)", file=sys.stderr)
    return cfg
```

### `fetch_indicators()` — in `tools/data-fetch/tradingview.py`

```python
def fetch_indicators(
    screener: str,
    requests: list,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> dict:
    """POST to TradingView scanner API and return indicator values by symbol.

    screener: 'america' | 'forex' | 'futures' | 'crypto' | 'cfd'
    requests: [{"symbol": "NASDAQ:AAPL", "indicators": ["RSI", "close", "ATR"]}]
    Returns: {"NASDAQ:AAPL": {"RSI": 63.4, "close": 189.50, "ATR": 3.21}}

    WHY POST to scanner.tradingview.com: this is the same endpoint used by
    TradingView's own screener page. No auth required for public symbols.
    Column names map directly to TradingView's internal field names.
    Timeframe suffix format: "RSI|" = 1D (default), "RSI|60" = 1H.
    """
    # Deduplicate symbols and collect union of requested indicators
    sym_indicators: dict = {}
    for req in requests:
        sym = req["symbol"]
        for ind in req.get("indicators", ["RSI", "close", "ATR"]):
            sym_indicators.setdefault(sym, set()).add(ind)

    if not sym_indicators:
        return {}

    # All columns needed (union across all symbols)
    all_columns = sorted({ind for inds in sym_indicators.values() for ind in inds})
    # TradingView column name format: "RSI|" for 1D default timeframe
    tv_columns = [f"{col}|" if "|" not in col else col for col in all_columns]

    payload = {
        "symbols": {
            "tickers": list(sym_indicators.keys()),
            "query": {"types": []},
        },
        "columns": tv_columns,
    }
    url = f"{SCANNER_BASE}/{screener.lower()}/scan"
    body = json.dumps(payload).encode("utf-8")

    for attempt in range(1, retries + 1):
        try:
            req = Request(url, data=body, headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (tradingDesk/tv-fetcher)",
            })
            with urlopen(req, timeout=timeout) as resp:
                raw = json.loads(resp.read())
                break
        except (URLError, TimeoutError, OSError) as e:
            if attempt < retries:
                print(f"  tradingview: retry {attempt}/{retries}: {e}", file=sys.stderr)
                time.sleep(RETRY_DELAY)
            else:
                print(f"  tradingview: scanner failed after {retries} attempts: {e}",
                      file=sys.stderr)
                return {}
        except Exception as e:
            print(f"  tradingview: unexpected error: {e}", file=sys.stderr)
            return {}

    # Parse response: {"data": [{"s": "NASDAQ:AAPL", "d": [63.4, 3.21, 189.50]}]}
    results = {}
    for item in raw.get("data", []):
        sym = item.get("s")
        values = item.get("d", [])
        if not sym or len(values) != len(all_columns):
            continue
        results[sym] = {col: values[i] for i, col in enumerate(all_columns)
                        if values[i] is not None}
    return results
```

### Pine Script Webhook Receiver — `tools/bridge/tv-webhook.py`

```python
class TVWebhookHandler(BaseHTTPRequestHandler):
    """Receive Pine Script alert POSTs and mutate thesis book JSON nodes.

    WHY BaseHTTPRequestHandler: zero-dep stdlib pattern matching mock_dialectic.py.
    The handler is stateless — each request opens the book JSON, applies the
    mutation atomically, and returns. No in-memory state between requests.
    """
    def log_message(self, format: str, *args) -> None:
        print(f"[tv-webhook] {format % args}", file=sys.stderr)

    def _send_json(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "empty body"})
            return
        try:
            alert = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return

        # Auth: token in payload (Pine Script doesn't support headers reliably)
        expected_token = os.environ.get("TV_WEBHOOK_TOKEN", "")
        if expected_token and alert.get("token") != expected_token:
            self._send_json(401, {"error": "invalid token"})
            return

        # Validate required fields
        for field in ("book", "node", "field", "value"):
            if field not in alert:
                self._send_json(400, {"error": f"missing field: {field}"})
                return

        allowed_fields = {"state", "probability", "current"}
        if alert["field"] not in allowed_fields:
            self._send_json(400, {"error": f"field must be one of {sorted(allowed_fields)}"})
            return

        # Resolve book path
        books_dir = ROOT / "books"
        book_path = books_dir / f"{alert['book']}.json"
        if not book_path.exists():
            self._send_json(404, {"error": f"book not found: {alert['book']}"})
            return

        # Apply mutation atomically (os.replace pattern from update_config_file)
        try:
            with open(book_path) as f:
                cfg = json.load(f)
            node_map = {n["id"]: n for n in cfg.get("nodes", [])}
            if alert["node"] not in node_map:
                self._send_json(404, {"error": f"node not found: {alert['node']}"})
                return
            old_val = node_map[alert["node"]].get(alert["field"])
            node_map[alert["node"]][alert["field"]] = alert["value"]
            tmp = str(book_path) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, book_path)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return

        self.log_message("Alert: %s/%s.%s = %s (was %s)",
                         alert["book"], alert["node"], alert["field"],
                         alert["value"], old_val)
        self._send_json(200, {"status": "ok", "book": alert["book"],
                              "node": alert["node"], "applied": alert["field"]})
```

### Thesis Node with TV Feeds (Iran/Hormuz `brent` node)

```json
{
  "id": "brent",
  "label": "Brent Persistence",
  "type": "price",
  "phase": 1,
  "feeds": [
    {"source": "yahoo", "symbol": "BZ=F"},
    {
      "source": "tradingview",
      "symbol": "TVC:UKOIL",
      "screener": "futures",
      "timeframe": "1D",
      "indicators": ["RSI", "ATR", "MACD.macd", "MACD.signal"],
      "thresholds": {
        "RSI": {"approaching": 60, "fired": 70},
        "MACD.macd": {"crossAboveSignal": true}
      }
    }
  ],
  "current": 112.57,
  "tvIndicators": {},
  "thresholds": [
    {"level": 115, "label": "persistence", "closesRequired": 3},
    {"level": 135, "label": "escalation"},
    {"level": 155, "label": "extreme"}
  ]
}
```

---

## 6. Phased Build Sequence

### Phase 1 — Scanner Fetch (Minimal Viable, 2-3 days)

**Goal:** TradingView RSI/ATR data flows into the graph snapshot. No behavior change in propagation — pure enrichment. Prove the data path works end-to-end in cron.

**Files touched:**
- CREATE `tools/data-fetch/tradingview.py` (~280 lines)
- CREATE `tools/data-fetch/test_tradingview.py` (~220 lines, 40 tests)
- MODIFY `tools/thesis-graph/thesisgraph.py`: add `fetch_tradingview()` function + call in main() + `tvIndicators` in export_state()
- MODIFY `tools/thesis-graph/test_export.py`: 6 new tests for v:2 snapshot schema
- MODIFY `books/iran-hormuz-graph.json`: add TV feeds to `brent` and `dxy-stress` nodes

**Tests added:** 46 total (40 new in test_tradingview.py, 6 in test_export.py)

**Exit criteria:**
- `python3 -m pytest tools/data-fetch/test_tradingview.py -q` passes all 40 tests
- `python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state -` produces v:2 snapshot with non-empty `tvIndicators` for brent node
- Existing 223 tests continue to pass (no regressions)

### Phase 2 — Deep Propagation Integration (3-4 days)

**Goal:** TV indicators change graph state. RSI threshold crossings promote price nodes from `stable` → `approaching` → `fired`. Confluence scoring multiplier for TV+Yahoo agreement. TV indicator diffs added to diff-snapshots output.

**Files touched:**
- MODIFY `tools/thesis-graph/thesisgraph.py`: extend `eval_node_state()` for price nodes to read `tvIndicators` thresholds; extend `score_confluence()` for TV signal weighting
- MODIFY `tools/bridge/diff-snapshots.py`: add `tvIndicatorShifts` diff category
- MODIFY `tools/bridge/test_diff.py`: 8 new tests for TV indicator diffs
- MODIFY `tools/thesis-graph/test_export.py`: 10 new tests for propagation behavior with TV feeds
- MODIFY `books/trump-tariffs-graph.json`: add TV feeds to `input-costs` and `consumer-confidence` nodes

**Tests added:** 18 total

**Exit criteria:**
- Node state changes when RSI crosses configured threshold (tested with mock TV response)
- Confluence score increases when Yahoo price signal and TV RSI signal agree
- Snapshot diff detects RSI shifts of >5 points as notable changes
- All 241 tests pass

### Phase 3 — Webhook Receiver + Morning Brief (4-5 days)

**Goal:** Bidirectional link complete. Pine Script alerts write node states in real time. Morning brief generates per-thesis bias reports using TV indicator + graph state.

**Files touched:**
- CREATE `tools/bridge/tv-webhook.py` (~180 lines) — Pine Script alert receiver, atomic book JSON mutation
- CREATE `tools/bridge/test_tv_webhook.py` (~160 lines, 28 tests)
- CREATE `tools/bridge/tv-morning-brief.py` (~200 lines) — per-thesis brief from latest snapshot + TV indicators
- CREATE `tools/bridge/test_tv_morning_brief.py` (~120 lines, 22 tests)
- MODIFY `tools/bridge/run-all.py`: optional `--with-brief` flag that runs `tv-morning-brief.py` per book after diff step
- Update CLAUDE.md with new commands

**Tests added:** 50 total

**Exit criteria:**
- Webhook receiver accepts TradingView Pine Script alert payloads, mutates node state atomically, responds 200 with applied-field echo
- Invalid token → 401; unknown book → 404; malformed payload → 400
- Morning brief generates markdown report listing per-node bias (RSI/MACD evidence), cascade phase verdict, top watch-items
- `run-all.py --with-brief` produces `output/{book-id}-brief-{date}.md` per book and pushes to Dialectic as a separate message

---

## 7. Testing Strategy

### Mocking the TradingView Scanner API

`tradingview.py` wraps all HTTP I/O in a `_make_request(url, body)` private function returning raw bytes. Tests monkeypatch `tradingview._make_request` with a factory that returns pre-recorded scanner API responses. This is the exact pattern `test_polymarket.py` uses (line 15-40) — no subprocess, no real network, no TradingView install required.

Fixture files live in `tools/data-fetch/fixtures/tv_scanner_futures.json`, `tv_scanner_america.json`, etc. Each fixture contains the raw scanner JSON response for a known (symbol, columns) request, captured once from the live API and committed as a regression anchor.

### Webhook Test Suite

`test_tv_webhook.py` imports `TVWebhookHandler` and starts it on a test socket (same pattern as `mock_dialectic.py` test harness). Test cases:
- Valid payload with correct token → 200, book JSON mutated, `.tmp` file cleaned up
- Invalid token → 401, no mutation
- Missing required field → 400
- Unknown book → 404
- Unknown node → 404
- Disallowed field (not in `{state, probability, current}`) → 400
- Malformed JSON → 400
- Atomic write: verify original book JSON intact if `os.fsync` raises mid-write
- Concurrent requests to same book: both writes succeed serially, no corruption
- Empty body → 400

### Golden Tests for Morning Brief

`test_tv_morning_brief.py` uses committed fixture snapshots + fixture TV indicator states. Asserts brief markdown output exactly matches a golden file. On legitimate content changes, golden file is updated atomically.

### Running Without TradingView Data

All TV-dependent tests use fixtures. The full 223-test suite + 114 new tests (337 total) runs in CI with zero network calls, zero TV Desktop dependency. An optional `test_tradingview_live.py` tier (5 tests) hits the real scanner API but is gated behind `TV_LIVE_TESTS=1` env var — only runs manually or in a weekly smoke-test cron.

---

## 8. Trade-offs & Risks

### What We Sacrifice

**End-of-day granularity.** The scanner API provides 1D/1H indicator snapshots, not tick-by-tick. RSI on 1D updates once per day. This is appropriate for a macro thesis graph (holding periods weeks-months) but inadequate for intraday scalping. This is a deliberate fit to tradingDesk's existing MWF cron cadence.

**Yahoo Finance is not replaced.** Yahoo remains the canonical `node.current` price source. TradingView supplements with indicator context. This is conservative but correct — Yahoo's spark API has reliably served prices throughout this project's history. Replacing it introduces a new single point of failure.

**No replay mode, no Pine Script authoring.** Jackson's MCP has 81 tools covering full TradingView control. We adopt only the read+alert subset that matters for a macro thesis DAG. Chart authoring stays in TradingView Desktop; Pine Script remains a manual craft.

### Risks and Degradation Modes

**Scanner API schema drift.** TradingView changes column names occasionally (e.g., `MACD.macd` → `MACD_macd`). Our fetcher logs the failed columns but keeps running — nodes simply don't get TV enrichment until fixtures are updated. Breaking change detection: a weekly `test_tradingview_live.py` CI job diffs live responses against fixtures and opens a PR on drift.

**Scanner rate limits.** TV scanner is public but not infinite. We batch all symbols per screener into one POST, budget ≤6 POSTs per run (one per screener) × 3 runs/week = 18 POSTs/week. Well under any plausible rate limit.

**Pine Script webhook auth is weak.** Pine Script alerts can't send custom HTTP headers. Our only auth is a shared secret in the POST body. Mitigation: run webhook receiver on a non-public port with a firewall; require the secret to be 32+ random bytes.

**Undocumented API = moving target.** TV can change or block the scanner endpoint any time. Risk is contained: if scanner breaks, node states fall back to pre-TV propagation logic — the graph continues to function, just with less context.

### Zero-Dependency Python Constraint

Every new file is stdlib-only. `urllib.request` for HTTP (existing pattern), `http.server.BaseHTTPRequestHandler` for webhook (matches `mock_dialectic.py`), `json`, `os`, `datetime`, `hmac` (for webhook secret verification). No Node.js sidecar. No CDP WebSocket. No Chrome. The whole integration runs on a Raspberry Pi.

---

## 9. THE FIRST THREE TRADES

Selected from existing Iran/Hormuz and Trump tariffs thesis material, with specific TV signal triggers that `fetch_tradingview()` would detect.

```
TRADE 1: XOP (long) — $3,200 (40% of Iran/Hormuz monthly budget)
  Entry: on TV signal confirmation below
  Stop: -12% from entry ($3.20 below fill)
  Target: +35% (XOP $180 → $243 equivalent move)
  Thesis: Brent persistence above $115 triggers oil-equity reflex; XOP beta to Brent ~1.4x
  TV signal: TVC:UKOIL RSI(1D) > 65 AND MACD.macd > MACD.signal for 2 consecutive closes
  Confluence: hormuz node (fired, prob=0.685) → brent node (RSI approaching fired)
              → demand-destruction node (not yet fired, lag in transmission)
              Confluence score ≥1.5 on brent node from Yahoo+TV agreement

TRADE 2: CF (long) — $2,000 (25% of Iran/Hormuz monthly budget)
  Entry: on TV signal
  Stop: -15% from entry
  Target: +50% over 60-90 days
  Thesis: Fertilizer stress from oil→nitrogen fertilizer cost transmission; planting-miss
          deadline 10-17 days out per iran-hormuz-graph.json countdowns[]
  TV signal: NYSE:CF RSI(1D) crosses above 55 from below AND weekly close above 200DMA
  Confluence: Layer 3 cascade phase (fertilizer → food → EM) per thesis claim.
              Planting-miss countdown < 14 days → urgency multiplier on CF position

TRADE 3: GLD (long) — $1,500 (25% of Trump-tariffs monthly budget)
  Entry: on TV signal
  Stop: -8% from entry
  Target: +18% (de-dollarization flow)
  Thesis: Tariff-shock uncertainty + Hormuz DXY stress → anti-dollar bid. Dual-thesis
          confluence: both iran-hormuz-graph AND trump-tariffs-graph nodes align
  TV signal: TVC:DXY RSI(1D) breaks below 45 AND GLD weekly close > prior 4-week high
  Confluence: dxy-stress (iran-hormuz) + reserve-currency (trump-tariffs) confluence
              score ≥1.3. Scenario "closed-may" (prob=0.45, netImpact=+12.8%) fires
              at same time → triple-signal anti-dollar conviction
```

**Sizing discipline:** Total initial deployment = $6,700 of $14,000 combined monthly budget (48%). Reserve balance in SGOV waits for Phase 2 confluence escalations. No position exceeds 40% of a single thesis budget. All stops set BEFORE entry fills — enforced by the graph's own `eval_node_state()` logic mapping stop levels to `thresholds[]`.

---

## 10. Success Metrics — 30 Days Post-Merge

**Operational (must-have):**
- Scanner API fetched successfully in ≥95% of MWF cron runs (3 runs × 2 books × 4 weeks = 24 runs, ≤1 allowed failure)
- Zero regressions: all existing 223 tests + 114 new TV tests pass every run
- `run-all.py` total runtime increases by <8 seconds with TV fetch enabled (vs pre-TV baseline)

**Signal quality (should-have):**
- At least 3 node state transitions in 30 days where TV RSI signal LED the Yahoo price signal by 1+ days (early-warning value)
- At least 1 case where TV+Yahoo confluence caught a false positive that Yahoo alone would have fired (noise reduction)
- Morning brief pushed to Dialectic rooms every MWF morning with zero manual edits required

**Trading edge (aspirational):**
- The three trades above collectively +8% or better over 30 days
- If losses occur: post-mortem identifies TV signal flaw, updates `biasRules` in book JSON, and the adjusted rules prevent the same loss pattern in simulated replay
- At least 1 pine script webhook fires and triggers a thesis graph node state change that would have been missed by cron alone

**Dialectic integration:**
- Snapshot v:2 `tvIndicators` field consistently present in pushes
- Morning brief drives ≥1 Dialectic room discussion per week (operator engagement metric)
- No snapshot rejections from schema drift (mock_dialectic test bed validates every push before production)
