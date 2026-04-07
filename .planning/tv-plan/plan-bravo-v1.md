# TEAM BRAVO: Morning Brief as First-Class Product
## TradingView Integration Plan for tradingDesk — v1

---

## 1. Executive Summary

The morning brief is not a feature — it is the product. Jackson's MCP video demonstrates one insight above all others: an LLM that reads charts before the session and delivers a structured bias report changes how a trader enters the day. The tactical problem is that his implementation is generic (any watchlist, any rules). tradingDesk's advantage is specificity: we have *thesis graphs* — causal DAGs that already encode what signals matter, which nodes gate which instruments, and what cascade phase we are in. A morning brief graded against those graphs is worth ten times a generic RSI scan.

Team Bravo builds `tools/brief/` as a standalone command that generates per-thesis *thesis briefs* — structured narrative reports comparing live chart state against each thesis's graph nodes — and pushes them to Dialectic as a separate message type from snapshot updates. Snapshots are data. Briefs are narrative. Both belong in the room, but they serve different purposes: the snapshot lets the LLM reason; the brief tells the trader what to do this morning.

**Why this beats all alternatives:**
- Thesis-specific rules (not generic watchlists) produce briefs with zero irrelevant signals
- Briefs as a distinct Dialectic message type let the room LLM distinguish "state update" from "morning recommendation"
- Loose coupling to chart source means TradingView is Day 1 but Tradestation is Day 30 if CDP breaks

---

## 2. Architecture & Rationale

### Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│  cron / run-all.py (existing)                                │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  NEW: tools/brief/morning-brief.py (orchestrator)      │  │
│  │                                                        │  │
│  │   load_book(book.json)                                 │  │
│  │       │                                                │  │
│  │       ▼                                                │  │
│  │   load_snapshot(snapshots/book-latest.json)            │  │
│  │       │                                                │  │
│  │       ▼                                                │  │
│  │   fetch_chart_state(instruments, rules)                │  │
│  │       │                                                │  │
│  │       │   ┌──────────────────────────────────────────┐ │  │
│  │       │   │  tools/brief/cdp_client.py               │ │  │
│  │       │   │  (CDP over HTTP + raw WebSocket)         │ │  │
│  │       │   │  OR Node subprocess (Jackson MCP)        │ │  │
│  │       └──►│  OR tv-http-bridge.py (webhook receiver) │ │  │
│  │           └──────────────────────────────────────────┘ │  │
│  │       │                                                │  │
│  │       ▼                                                │  │
│  │   grade_against_thesis(chart_state, snapshot, rules)   │  │
│  │       │                                                │  │
│  │       ▼                                                │  │
│  │   render_brief(graded_nodes) → brief.md + brief.json   │  │
│  │       │                                                │  │
│  │       ▼                                                │  │
│  │   push_brief_to_dialectic(brief, room_id, token)       │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘

  Screenshot artifacts → output/screenshots/{book-id}-{date}.png
  Brief JSON archives → snapshots/{book-id}-brief-{date}.json
```

### Data Flow

1. `run-all.py` calls `morning-brief.py` per book after the export step (or independently on a tighter cron)
2. `morning-brief.py` reads the book JSON (for node/instrument definitions and rules) and the latest snapshot (for current graph state — avoids re-running propagation)
3. `cdp_client.py` connects to TradingView Desktop on port 9222, iterates each instrument in the book's portfolio, reads OHLCV + indicator values, captures a screenshot per chart
4. `grade_against_thesis()` maps chart state onto graph nodes using the thesis's own thresholds — not generic rules. Brent at $112 → node `brent` is "approaching" threshold 115. RSI divergence on BZ=F → flag it. This logic lives in `tools/brief/grader.py`
5. `render_brief()` produces a Markdown brief and a parallel JSON twin. Both are artifacts
6. Screenshots saved as `output/screenshots/{book-id}-{YYYY-MM-DD}.png`
7. `push_brief_to_dialectic()` POSTs to a new endpoint: `POST /rooms/{id}/trading/brief` — separate from the snapshot endpoint so Dialectic can route differently

### Why This Matches tradingDesk Patterns

- `morning-brief.py` is a standalone CLI with `--dry-run`, `--book`, `--no-push` flags — exactly how `push-to-dialectic.py` and `diff-snapshots.py` are structured
- `cdp_client.py` mirrors `polymarket.py`: standalone importable module, CLI invocable, uses only stdlib (`http.client` for the HTTP upgrade, `socket` + manual WebSocket framing for CDP)
- Brief grading uses the existing `export_state()` snapshot as input — no re-propagation, no coupling to thesisgraph internals
- `push_brief_to_dialectic()` is a thin wrapper over the same urllib pattern as `push-to-dialectic.py`

### Loose Coupling Philosophy

The `ChartClient` protocol (abstract base in `cdp_client.py`) exposes three methods: `get_ohlcv(symbol, timeframe)`, `get_indicator(symbol, indicator, timeframe)`, `capture_screenshot(symbol)`. The CDP implementation is one concrete class. A Yahoo Finance fallback class ships in Phase 1 so the brief runs without TradingView Desktop. Tradestation, ThinkOrSwim, or any future source is a new concrete class — `morning-brief.py` never changes.

**Philosophy in one sentence:** The brief is the interface, the chart tool is a plugin, and the thesis graph is the oracle.

---

## 3. Concrete File Plan

### New Files

| Path | Est. Lines | Purpose |
|---|---|---|
| `tools/brief/morning-brief.py` | 280 | Main CLI orchestrator: loads book + snapshot, drives chart fetch, grades, renders, pushes |
| `tools/brief/cdp_client.py` | 220 | CDP WebSocket client + Yahoo Finance fallback implementing `ChartClient` protocol |
| `tools/brief/grader.py` | 160 | Maps chart state onto thesis graph nodes using book thresholds; returns per-node bias verdict |
| `tools/brief/renderer.py` | 140 | Renders brief Markdown + JSON twin from graded nodes |
| `tools/brief/push_brief.py` | 80 | POSTs brief payload to Dialectic `/rooms/{id}/trading/brief` endpoint |
| `tools/brief/test_brief.py` | 320 | All brief tests: grader unit tests, renderer golden tests, mock CDP, mock push |
| `tools/brief/__init__.py` | 5 | Package marker |
| `tools/validation/mock_dialectic_brief.py` | 120 | Extends mock_dialectic.py to handle `/trading/brief` endpoint |

### Modified Files

| Path | Lines Changed | Change |
|---|---|---|
| `tools/bridge/run-all.py` | +45 lines | Add `run_brief(book_path, book_data, snapshots_dir)` step after `run_export`; add `--no-brief` flag to skip; call `morning-brief.py` as subprocess |
| `books/iran-hormuz-graph.json` | +12 lines | Add `"tradingview": {"watchlist": [...], "primaryTimeframe": "4h", "biasRules": {...}}` to meta |
| `books/trump-tariffs-graph.json` | +12 lines | Same TV config block |
| `CLAUDE.md` | +15 lines | Document `tools/brief/` in File Structure and Quick Start |

---

## 4. Schemas & Contracts

### Brief Output — Markdown (human-readable, pushed to Dialectic)

```markdown
# Morning Brief: Iran/Hormuz Thesis — 2026-04-05 08:03 UTC

**Cascade Phase:** 2 — TRANSMISSION (STARTING)
**Overall Bias:** BEARISH OIL-SERVICES | NEUTRAL FERTILIZER | BULLISH GOLD

## Node Verdicts

| Node | Graph State | Chart Signal | Alignment | Action |
|------|-------------|--------------|-----------|--------|
| brent (BZ=F) | approaching $115 | RSI 68, below 4h EMA | APPROACHING — on watch | No new adds |
| diesel | fired >$5.38 | EIA weekly +0.08 | CONFIRMED | Hold XOP |
| dxy-stress | stable | DXY 100.2, weekly doji | NEUTRAL | Hold GLD |
| fert-shortage | approaching | CF 136 near 150 target | ON TARGET | Hold CF/NTR |

## Session Watch
- **Key level:** BZ=F $115 (brent persistence threshold). 3 closes above → escalation overlay fires
- **Planting deadline:** 10 days to Apr 15. Irreversible if missed.
- **Risk:** De-escalation node active if BZ=F closes <$95 for 5 days

## Screenshots
- BZ=F 4h: output/screenshots/iran-hormuz-graph-2026-04-05.png
```

### Brief Output — JSON Twin

```json
{
  "v": 1,
  "type": "brief",
  "bookId": "iran-hormuz-graph",
  "title": "Iran/Hormuz Thesis — Morning Brief",
  "timestamp": "2026-04-05T08:03:00Z",
  "sessionBias": "bearish-oil-services",
  "cascadePhase": {"number": 2, "key": "transmission", "status": "STARTING"},
  "nodeVerdicts": {
    "brent":       {"graphState": "approaching", "chartSignal": "rsi_68_below_4h_ema", "alignment": "approaching", "action": "no_new_adds"},
    "diesel":      {"graphState": "fired",        "chartSignal": "confirmed_above_5.38", "alignment": "confirmed",  "action": "hold"},
    "dxy-stress":  {"graphState": "stable",       "chartSignal": "dxy_100_doji",         "alignment": "neutral",   "action": "hold"},
    "fert-shortage":{"graphState": "approaching", "chartSignal": "cf_on_target",         "alignment": "on_target", "action": "hold"}
  },
  "watchPoints": [
    {"nodeId": "brent", "level": 115, "label": "persistence threshold", "closesRequired": 3},
    {"nodeId": "planting-miss", "daysRemaining": 10, "label": "irreversible deadline"}
  ],
  "screenshots": ["output/screenshots/iran-hormuz-graph-2026-04-05.png"],
  "snapshotRef": "snapshots/iran-hormuz-graph-latest.json"
}
```

### Bias Rules Config (inside book `meta.tradingview`)

```json
"tradingview": {
  "watchlist": ["BZ=F", "CF", "NTR", "GLD", "XOP", "BDRY"],
  "primaryTimeframe": "4h",
  "screenshotTimeframe": "1d",
  "biasRules": {
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "ema_period": 50,
    "atr_period": 14,
    "volume_threshold_multiplier": 1.5
  },
  "cdpPort": 9222,
  "cdpFallback": "yahoo"
}
```

### Integration Contract with `run-all.py`

`run-all.py` calls `morning-brief.py` as a subprocess after the export step:

```
python3 tools/brief/morning-brief.py \
    --book books/iran-hormuz-graph.json \
    --snapshot snapshots/iran-hormuz-graph-latest.json \
    --screenshots-dir output/screenshots/ \
    --brief-out snapshots/iran-hormuz-graph-brief-{date}.json \
    [--no-push] [--dry-run]
```

Exit codes: 0 = brief generated and pushed, 1 = brief generated but push failed, 2 = generation failed, 3 = TradingView unavailable (brief skipped, not a run failure). Exit 3 is not a failure for `run-all.py` — chart unavailability should not block snapshot updates.

### Dialectic Brief Push Payload

```
POST /rooms/{room_id}/trading/brief
Authorization: Bearer {token}
Content-Type: application/json

{
  "v": 1,
  "type": "brief",
  "bookId": "...",
  "timestamp": "...",
  "markdownContent": "# Morning Brief...",
  "structuredData": { ...brief JSON twin... },
  "screenshotPaths": ["output/screenshots/..."]
}
```

---

## 5. Key Code Sketches

### Main Brief Generator (`tools/brief/morning-brief.py`, core function)

```python
def generate_brief(
    book_path: str,
    snapshot_path: str,
    screenshots_dir: str,
    chart_client: "ChartClient",
    today: date | None = None,
) -> tuple[dict, str]:
    """
    Generate a thesis brief for one book.
    Returns (brief_json_dict, brief_markdown_str).
    """
    if today is None:
        today = date.today()

    with open(book_path) as f:
        book = json.load(f)
    with open(snapshot_path) as f:
        snapshot = json.load(f)

    meta = book.get("meta", {})
    tv_cfg = meta.get("tradingview", {})
    watchlist = tv_cfg.get("watchlist", [])
    timeframe = tv_cfg.get("primaryTimeframe", "4h")
    rules = tv_cfg.get("biasRules", {})
    book_id = Path(book_path).stem

    # Fetch chart state for each instrument in watchlist
    chart_states: dict[str, dict] = {}
    screenshots: list[str] = []

    for symbol in watchlist:
        try:
            ohlcv = chart_client.get_ohlcv(symbol, timeframe, bars=50)
            rsi = chart_client.get_indicator(symbol, "RSI", timeframe, length=14)
            ema = chart_client.get_indicator(symbol, "EMA", timeframe, length=rules.get("ema_period", 50))
            chart_states[symbol] = {
                "close": ohlcv[-1]["close"] if ohlcv else None,
                "rsi": rsi,
                "ema": ema,
                "above_ema": ohlcv[-1]["close"] > ema if (ohlcv and ema) else None,
            }
        except ChartClientError as e:
            print(f"  chart fetch failed for {symbol}: {e}", file=sys.stderr)
            chart_states[symbol] = {"error": str(e)}

        try:
            shot_path = os.path.join(
                screenshots_dir,
                f"{book_id}-{symbol.replace('/', '_').replace('=', '')}-{today.isoformat()}.png"
            )
            chart_client.capture_screenshot(symbol, shot_path)
            screenshots.append(shot_path)
        except ChartClientError:
            pass  # screenshots are non-fatal

    # Grade chart state against thesis nodes
    grader = ThesisGrader(book, snapshot)
    verdicts = grader.grade_all(chart_states, rules)

    # Determine session bias
    session_bias = compute_session_bias(verdicts, snapshot)

    # Build brief
    brief_data = {
        "v": 1,
        "type": "brief",
        "bookId": book_id,
        "title": f"{meta.get('title', book_id)} — Morning Brief",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sessionBias": session_bias,
        "cascadePhase": snapshot.get("cascadePhase", {}),
        "nodeVerdicts": verdicts,
        "watchPoints": extract_watch_points(book, snapshot),
        "screenshots": screenshots,
        "snapshotRef": snapshot_path,
    }

    brief_md = render_markdown(brief_data, book, snapshot)
    return brief_data, brief_md
```

### CDP Client Bridge (`tools/brief/cdp_client.py`)

```python
import http.client
import json
import socket
import struct
import hashlib
import base64
import os
from typing import Protocol

class ChartClientError(Exception):
    pass

class ChartClient(Protocol):
    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 50) -> list[dict]: ...
    def get_indicator(self, symbol: str, indicator: str, timeframe: str, **kw) -> float | None: ...
    def capture_screenshot(self, symbol: str, out_path: str) -> None: ...

class CDPChartClient:
    """Connect to TradingView Desktop via Chrome DevTools Protocol."""

    def __init__(self, port: int = 9222, timeout: int = 10) -> None:
        self.port = port
        self.timeout = timeout
        self._ws_sock: socket.socket | None = None
        self._msg_id = 0
        self._connect()

    def _connect(self) -> None:
        # Step 1: HTTP GET /json to discover the WebSocket debugger URL
        try:
            conn = http.client.HTTPConnection("localhost", self.port, timeout=self.timeout)
            conn.request("GET", "/json")
            resp = conn.getresponse()
            targets = json.loads(resp.read())
            conn.close()
        except (ConnectionRefusedError, OSError) as e:
            raise ChartClientError(f"CDP not reachable on port {self.port}: {e}") from e

        tv_target = next((t for t in targets if "tradingview" in t.get("url", "").lower()), None)
        if not tv_target:
            raise ChartClientError("No TradingView target found in CDP targets")

        ws_url = tv_target["webSocketDebuggerUrl"]  # ws://localhost:9222/devtools/page/{id}
        # Step 2: manual WebSocket handshake (stdlib only — no websockets lib)
        self._ws_sock = self._ws_handshake(ws_url)

    def _ws_handshake(self, ws_url: str) -> socket.socket:
        # Parse ws://host:port/path
        path = ws_url.split("localhost:9222", 1)[1]
        key = base64.b64encode(os.urandom(16)).decode()
        sock = socket.create_connection(("localhost", self.port), timeout=self.timeout)
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: localhost:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode())
        # Read until \r\n\r\n
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += sock.recv(1024)
        return sock

    def _send_cdp(self, method: str, params: dict) -> dict:
        self._msg_id += 1
        msg = json.dumps({"id": self._msg_id, "method": method, "params": params})
        payload = msg.encode()
        # WebSocket text frame: FIN=1, opcode=1, mask=1
        header = bytes([0x81])
        length = len(payload)
        if length < 126:
            header += bytes([0x80 | length])
        else:
            header += bytes([0x80 | 126, length >> 8, length & 0xFF])
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._ws_sock.sendall(header + mask + masked)
        # Read response (simplified — production needs framing loop)
        raw = self._ws_sock.recv(65536)
        # Strip WebSocket frame header (2-10 bytes), parse JSON
        frame_start = 2 if raw[1] < 126 else 4
        return json.loads(raw[frame_start:])

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 50) -> list[dict]:
        result = self._send_cdp("Runtime.evaluate", {
            "expression": f"window.__tvMCP?.getOHLCV('{symbol}', '{timeframe}', {bars})",
            "awaitPromise": True,
            "returnByValue": True,
        })
        return result.get("result", {}).get("result", {}).get("value", [])

    def get_indicator(self, symbol: str, indicator: str, timeframe: str, **kw) -> float | None:
        expr = f"window.__tvMCP?.getIndicatorValue('{symbol}', '{indicator}', '{timeframe}', {json.dumps(kw)})"
        result = self._send_cdp("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        return result.get("result", {}).get("result", {}).get("value")

    def capture_screenshot(self, symbol: str, out_path: str) -> None:
        result = self._send_cdp("Page.captureScreenshot", {"format": "png", "quality": 80})
        data = result.get("result", {}).get("data", "")
        if data:
            import base64 as b64
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(b64.b64decode(data))
```

### Brief-to-Dialectic Push (`tools/brief/push_brief.py`)

```python
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def push_brief(
    dialectic_url: str,
    room_id: str,
    token: str,
    brief_data: dict,
    brief_markdown: str,
    screenshot_paths: list[str],
    max_attempts: int = 3,
) -> int:
    """
    POST brief to Dialectic /rooms/{room_id}/trading/brief.
    Returns 0 (success), 1 (HTTP error), 2 (connection error).
    """
    url = f"{dialectic_url.rstrip('/')}/rooms/{room_id}/trading/brief"
    payload = json.dumps({
        "v": 1,
        "type": "brief",
        "bookId": brief_data.get("bookId"),
        "timestamp": brief_data.get("timestamp"),
        "markdownContent": brief_markdown,
        "structuredData": brief_data,
        "screenshotPaths": screenshot_paths,
    }, ensure_ascii=False).encode()

    for attempt in range(1, max_attempts + 1):
        req = Request(
            url, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "tradingDesk-brief/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                print(body)
                return 0
        except HTTPError as e:
            if e.code < 500:
                print(f"HTTP {e.code}: brief push failed", file=sys.stderr)
                return 1
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
                continue
            return 1
        except (URLError, OSError) as e:
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
                continue
            print(f"Connection error: {e}", file=sys.stderr)
            return 2
    return 2
```

---

## 6. Phased Build Sequence

### Phase 1 — Minimal Viable Brief (no TradingView required)

**Goal:** Generate a thesis brief from snapshot data alone, using Yahoo Finance OHLCV as the chart source, and push it to Dialectic. TradingView Desktop not required for Phase 1.

**Files touched:**
- Create `tools/brief/__init__.py`
- Create `tools/brief/grader.py` (node verdict logic using Yahoo prices)
- Create `tools/brief/renderer.py` (Markdown + JSON twin)
- Create `tools/brief/push_brief.py` (Dialectic brief endpoint)
- Create `tools/brief/morning-brief.py` (CLI, Yahoo client only)
- Create `tools/brief/test_brief.py` (grader unit tests, renderer golden tests)
- Extend `tools/validation/mock_dialectic.py` to handle `/trading/brief`

**Tests added:** 25 (grader logic for each node type, renderer output format, push round-trip with mock server, `--dry-run` output)

**Exit criteria:** `python3 tools/brief/morning-brief.py --book books/iran-hormuz-graph.json --snapshot snapshots/iran-hormuz-graph-latest.json --no-push` produces a valid brief markdown with node verdicts graded against live Yahoo prices. `python3 -m pytest tools/brief/test_brief.py -q` passes all 25 tests.

### Phase 2 — CDP Integration + Screenshots

**Goal:** Connect to TradingView Desktop, read real indicator values, capture screenshots per instrument.

**Files touched:**
- Create `tools/brief/cdp_client.py` (full CDP + Yahoo fallback)
- Update `tools/brief/morning-brief.py` to accept `--cdp-port`, auto-detect CDP vs fallback
- Add `"tradingview"` config block to `books/iran-hormuz-graph.json` and `books/trump-tariffs-graph.json`
- Extend `test_brief.py` with mock CDP tests (socket-level stub)

**Tests added:** 20 (CDP connection error handling, fallback behavior, screenshot write, `--cdp-port` flag)

**Exit criteria:** Running with TradingView Desktop open produces `output/screenshots/iran-hormuz-graph-BZF-{date}.png`. Running without Desktop falls back to Yahoo silently (exit 0, brief generated). `--dry-run` prints what would run without connecting.

### Phase 3 — `run-all.py` Integration + Cron

**Goal:** Brief runs automatically as part of the existing pipeline cron.

**Files touched:**
- Modify `tools/bridge/run-all.py`: add `run_brief()` step after `run_export()`, add `--no-brief` flag
- Update `CLAUDE.md` to document `tools/brief/`
- Update `README.md`

**Tests added:** 10 (run-all integration: brief step OK, brief step skipped on exit 3, `--no-brief` flag bypasses, brief failure does not abort other books)

**Exit criteria:** `python3 tools/bridge/run-all.py --dry-run` shows brief step for each book. Full run generates briefs and pushes them. Total test count reaches 253 (223 + 30 new).

---

## 7. Testing Strategy

### Mock CDP

`tools/brief/test_brief.py` includes a `MockCDPServer` class using `threading.Thread` + `http.server.HTTPServer` on a random port. It serves a `/json` response listing one fake TradingView target, then accepts a raw WebSocket connection and responds to `Runtime.evaluate` and `Page.captureScreenshot` CDP commands with fixture data.

This means CDP tests run in CI without TradingView Desktop. The pattern is identical to how `mock_dialectic.py` mocks the Dialectic server — a local HTTP server in a thread, torn down after each test.

### Brief Generation Golden Tests

`test_brief.py` includes golden tests: given a known snapshot JSON (fixture) and known chart state (fixture dict), `grade_all()` must return exact expected verdicts. These are deterministic because the grader logic is pure functions — no network calls. The fixture snapshots live in `tools/brief/fixtures/` as JSON files.

### Testing Without TradingView Desktop

The `ChartClient` protocol means tests can inject a `FakeChartClient` that returns canned OHLCV and indicator data. The CLI's `--cdp-port 0` (or an env var `TRADING_DESK_TEST_MODE=1`) forces the Yahoo fallback. Phase 1 is fully testable with no Desktop present. Phase 2 adds the socket-level mock for CDP-specific paths.

### Regression Guard

After Phase 3, add `test_brief.py` to the `CLAUDE.md` test suite line: `python3 -m pytest tools/brief/test_brief.py -q   # 30 — brief generation`.

---

## 8. Trade-offs & Risks

### What You Sacrifice

- **No deep graph integration.** The brief does not write back into the thesis graph's node states. Chart signals inform the human; they do not auto-fire nodes. This is intentional — automated node mutation from chart state is a footgun (false signals mutate production state). The human remains the circuit breaker.
- **Briefs are not diffs.** Unlike snapshots, briefs do not have a `diff-brief.py` companion. Day-over-day brief comparison is manual via Dialectic's conversation history. This is acceptable in Phase 1; a `diff-briefs.py` is a natural Phase 4 addition.
- **Screenshot fidelity.** CDP screenshots capture whatever is on screen. If TradingView has a wrong symbol loaded when the brief runs, the screenshot is wrong. Mitigation: the CDP client sets the symbol explicitly before screenshotting via `chart_set_symbol` CDP call.

### If TradingView Breaks Its CDP Interface

CDP is a stable protocol (Chrome devtools spec, not TradingView-specific). What breaks is the JavaScript bridge (`window.__tvMCP`) that Jackson's MCP injects. If that injection breaks: (a) the CDP client falls back to `Page.captureScreenshot` (screenshot still works), (b) indicator values fall back to Yahoo Finance. The brief degrades gracefully — no crash, no blocked pipeline. The `--cdp-fallback yahoo` flag is always available.

The real risk is TradingView removing Electron's remote debugging port support. This has not happened and would break Jackson's MCP identically. Mitigation: the `ChartClient` protocol means a TradingView Web API client (TradingView has a REST API for premium subscribers) is a drop-in replacement.

### Zero-Dep Python Constraint

The CDP WebSocket framing is 30 lines of pure stdlib (`socket`, `struct`, `hashlib`, `base64`). This is correct — RFC 6455 WebSocket frames are not complex. The constraint is preserved. If the frame parsing proves fragile under real CDP traffic (message fragmentation, multi-frame responses), the pragmatic fix is: spawn Jackson's Node.js MCP as a subprocess and talk to it via its stdio MCP interface using `subprocess.Popen`. This is a documented escape hatch, not a dependency: Node.js is already on any developer machine running Jackson's MCP. The Python code stays stdlib; we shell out to Node for one specific task. This is the same pattern tradingDesk already uses for `run_export()` — subprocess, not import.

---

## 9. The First Three Trades

```
TRADE 1: BZ=F (via XOP) LONG  $1,400/mo  entry $188  stop $171  target $210-225
  Thesis: Hormuz closure Phase 2 — diesel fired >$5.38, freight node approaching,
          brent node at $112.57 approaching $115 persistence threshold.
  Brief signal: Morning brief shows BZ=F RSI 68 (not overbought), price holding
                above 4h EMA 50. Diesel EIA weekly print +0.08. Both confirming.
                No divergence. Trend intact.
  Graph state: brent=approaching (threshold $115, 3-close required), diesel=fired,
               freight=approaching. Phase 2 STARTING. Escalation overlay not yet active.

TRADE 2: CF LONG  $800/mo  entry $136  stop $124  target $150-160
  Thesis: Hormuz handles 30% of traded fertilizer. fert-shortage node approaching
          $700 stress threshold. Planting deadline Apr 15 is 10 days out — irreversible.
  Brief signal: CF daily chart holding above 20d EMA. RSI 62 — room to run.
                NOLA urea $683 vs $700 stress threshold. One more EIA weekly
                confirms node fires. Planting window gates the trade.
  Graph state: fert-shortage=approaching ($683 vs $700 threshold),
               planting-miss deadline=10 days, conditions met if diesel holds.

TRADE 3: GLD (via GDX) LONG  $1,000/mo  entry $414.70  stop $395  target $445-460
  Thesis: DXY stress node at 100.18, approaching 102 squeeze threshold.
          Dollar demand from oil importers is petrodollar squeeze, not US strength.
          Gold-breakout overlay condition: GLD >$425.
  Brief signal: DXY 4h shows weekly doji at 100.2 — distribution, not trend.
                GLD weekly RSI 61, above all EMAs. Gold-breakout overlay not yet
                fired (GLD below $425) but brief flags it as "on watch — 2.5% from trigger."
  Graph state: dxy-stress=approaching (threshold 102), em-currency=approaching,
               gold-breakout overlay ARMED (condition: GLD >$425).
```

---

## 10. Success Metrics

**30 days post-merge, "this works" means:**

1. `run-all.py` generates briefs for both books on every Mon/Wed/Fri run without human intervention. Zero manual restarts required.

2. Both Dialectic rooms receive both a snapshot push AND a brief push on each cron run. The room history shows the two message types as distinct entries, not merged.

3. At least one brief correctly predicted a node state transition before it appeared in the snapshot. Specifically: the brief's "on watch" verdict for a node preceded the snapshot's `approaching → fired` transition by at least one session. This is the core trading edge — the brief sees it in chart state before the price crosses the snapshot threshold.

4. Screenshots are generated and stored in `output/screenshots/` with no manual cleanup required. Filenames are deterministic and do not collide across runs.

5. TradingView Desktop being closed (e.g., machine restart) does not break `run-all.py`. The brief step exits 3, `run-all.py` logs "brief skipped — CDP unavailable", snapshots and Dialectic pushes proceed normally.

6. Total test count: 253 (223 existing + 30 new). All tests pass in CI.

7. Amo can read the morning brief in the Dialectic room by 08:15 UTC and make a position decision before US pre-market open (09:30 ET = 13:30 UTC). The brief is the first message he reads, not a report he has to generate.

---

*Team Bravo — Morning Brief as First-Class Product*
*Plan version: v1 — 2026-04-05*

Now let me actually write this to the file. I'll use a Python heredoc approach via the filesystem:

The plan is fully designed. Since I need to write it to a file and my available tools are Glob, Grep, Read, WebFetch, and WebSearch (no Write or Bash tool), I need to present this as the file content in my response. The implementation agent will need to write this to `/root/tradingDesk/.planning/tv-plan/plan-bravo-v1.md`.

However — reviewing the task setup more carefully: the instruction says "You are Claude Code" running in the Claude Agent SDK. Claude Code typically has Bash access. Let me check if I'm missing a tool or if I should produce the file content inline and note the write is needed.

Given my available tools don't include a write/bash capability, I'll produce the complete file content here and note where it should be written.

---

Here is the complete content for `/root/tradingDesk/.planning/tv-plan/plan-bravo-v1.md` — this is the full build plan ready to write:

---

**TEAM BRAVO — Summary Pitch (~200 words)**

Team Bravo's core bet: the morning brief is not a feature to bolt onto the graph — it is a standalone deliverable that generates trading edge. Jackson's video proves the pattern works. tradingDesk's thesis graphs give us something Jackson's generic rules.json never can: a causal model that tells us *which chart signals matter and why*. Brent RSI is noise. Brent RSI graded against the brent node's $115 persistence threshold, with the diesel node already fired, with planting deadline 10 days out — that is a decision.

The architecture is deliberate about separation: `tools/brief/` is its own command, its own tests, its own Dialectic message type. It reads the snapshot rather than re-running propagation. It uses a `ChartClient` protocol so TradingView is Day 1 and any other chart source is a drop-in. CDP connectivity is stdlib-only WebSocket framing — 30 lines, no deps. If CDP breaks, Yahoo Finance fallback kicks in automatically, the brief still runs, the pipeline does not stall.

**Three competitive differentiators:**
1. Thesis-specific grading (not generic RSI rules) means every brief verdict is grounded in the causal model — no irrelevant signals
2. Brief as a separate Dialectic message type lets the room LLM distinguish "state data" from "session recommendation"
3. Graceful CDP degradation (exit code 3, not failure) means TradingView Desktop being offline never blocks the snapshot pipeline

**Relevant files:**
- `/root/tradingDesk/.planning/tv-plan/research-context.md` — source context
- `/root/tradingDesk/.planning/tv-plan/codebase-map.md` — extension point map
- `/root/tradingDesk/tools/bridge/run-all.py` — pipeline to extend (lines 180-293 = `run_book()`)
- `/root/tradingDesk/tools/bridge/push-to-dialectic.py` — push pattern to clone
- `/root/tradingDesk/tools/data-fetch/polymarket.py` — module pattern to follow for `cdp_client.py`
- `/root/tradingDesk/tools/validation/mock_dialectic.py` — mock server pattern for `test_brief.py`
- `/root/tradingDesk/books/iran-hormuz-graph.json` — first book to add `meta.tradingview` config
- `/root/tradingDesk/books/trump-tariffs-graph.json` — second book

The plan above contains the complete spec. The file should be written to `/root/tradingDesk/.planning/tv-plan/plan-bravo-v1.md`.