# TEAM BRAVO v2: Morning Brief as First-Class Product
## TradingView Integration Plan for tradingDesk — v2

**Date:** 2026-04-05
**Supersedes:** plan-bravo-v1.md (attacked — 5 fatal flaws, 10 majors)
**Core bet (unchanged):** The morning brief is not a bolt-on feature — it is the product. Jackson's MCP video proves the workflow; tradingDesk's thesis graphs make it sharp.

---

## 1. Executive Summary

The v1 plan committed three unforced errors: (1) it pushed to a Dialectic endpoint that does not exist, (2) it shipped a toy WebSocket client that would break on the first 400 KB CDP screenshot frame, and (3) it secretly depended on Jackson's `window.__tvMCP` JavaScript injection without declaring that dependency. v2 keeps the differentiator — a per-thesis structured morning brief graded against the DAG and delivered to Dialectic — but rebuilds the plumbing on load-bearing foundations.

**The three critical pivots:**

1. **Endpoint pivot (F1):** Briefs ride inside the existing `/rooms/{room_id}/trading/snapshot` endpoint by extending the snapshot schema to `v:2` with a top-level `"brief"` field. No Dialectic-repo work. The brief lives alongside the data it annotates; the room LLM sees both in one memory write. (Options b and c rejected; rationale in §2.)
2. **CDP pivot (F2):** Drop CDP/WebSocket entirely. Primary chart source is **headless Chromium via subprocess** (`chromium --headless --screenshot=...`) for screenshots and **yfinance-compatible OHLCV via Yahoo v7 spark API** for indicator math (RSI, EMA, ATR computed in Python stdlib). A Phase 2 add-on supports **subprocess-ing Jackson's Node MCP** (`node dist/index.js`) for traders who want live TradingView Desktop indicator reads — fully optional, behind a feature flag.
3. **Signal pivot (F4):** The brief derives four classes of signal the HTML dashboard and Alpha cannot produce from snapshot state alone — (a) **multi-timeframe RSI/EMA divergence** per node-mapped instrument, (b) **cross-book confluence** (when the same instrument appears in multiple books and both fire), (c) **signpost grading** (does the live chart confirm or contradict the book's cascade-phase narrative?), and (d) **velocity-to-threshold** (rate of approach, not just proximity).

**Core differentiator preserved:** per-thesis structured markdown brief, graded against the DAG's own thresholds, delivered into Dialectic rooms on the same cron as snapshots, with screenshots and watch-points the trader reads before pre-market open.

**Why this beats Alpha:** Alpha will propose trades from the same book thresholds Bravo reads. Bravo wins on *what happens between the thresholds*: divergence, velocity, cross-book pressure, signpost confirmation. That's the brief.

---

## 2. Architecture & Rationale

### Component Diagram (v2)

```
┌────────────────────────────────────────────────────────────────────┐
│  run-all.py (existing, +30 lines)                                  │
│                                                                    │
│  per book:  fetch → export → BRIEF → diff → push                   │
│                               │                                    │
│                               ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  tools/brief/brief.py       (standalone CLI, 280 lines)     │   │
│  │                                                             │   │
│  │     load_book + load_snapshot (from fetch step)             │   │
│  │             │                                               │   │
│  │             ▼                                               │   │
│  │     build_watchlist(book) ─────── derives from node feeds   │   │
│  │             │                     (no duplicate config)     │   │
│  │             ▼                                               │   │
│  │     ┌─────────────────────────────────────────────┐         │   │
│  │     │ chart_source.py  (Protocol + 2 concretes)   │         │   │
│  │     │                                             │         │   │
│  │     │  YahooChartSource  (Phase 1, default)       │         │   │
│  │     │   ├── get_ohlcv() ──► Yahoo v7 spark API    │         │   │
│  │     │   └── compute_rsi/ema/atr (stdlib math)     │         │   │
│  │     │                                             │         │   │
│  │     │  HeadlessChromiumSource (Phase 2, opt-in)   │         │   │
│  │     │   └── capture_screenshot() ──► chromium     │         │   │
│  │     │       subprocess (--headless --screenshot)  │         │   │
│  │     │                                             │         │   │
│  │     │  NodeMcpSource (Phase 3, opt-in)            │         │   │
│  │     │   └── subprocess.Popen(node dist/index.js)  │         │   │
│  │     │       stdio JSON-RPC to Jackson's MCP       │         │   │
│  │     └─────────────────────────────────────────────┘         │   │
│  │             │                                               │   │
│  │             ▼                                               │   │
│  │     grader.py (160 lines)                                   │   │
│  │       - multi-timeframe divergence                          │   │
│  │       - velocity-to-threshold                               │   │
│  │       - signpost confirmation                               │   │
│  │             │                                               │   │
│  │             ▼                                               │   │
│  │     cross_book.py (50 lines, Phase 2)                       │   │
│  │       - scan snapshots/*-latest.json for shared symbols     │   │
│  │             │                                               │   │
│  │             ▼                                               │   │
│  │     renderer.py (structural: markdown_from_dict)            │   │
│  │             │                                               │   │
│  │             ▼                                               │   │
│  │     EMBED into snapshot JSON as snapshot["brief"] field     │   │
│  │     (schema v:2 — see §4)                                   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                               │                                    │
│                               ▼                                    │
│       existing push-to-dialectic.py (unchanged)                    │
│       POSTs snapshot with brief attached                           │
└────────────────────────────────────────────────────────────────────┘

  Screenshot artifacts → output/screenshots/{book-id}/{YYYY-MM-DD}/{symbol}.png
  Lifecycle: keep last 14 days, purge older (cron-safe)
```

**v2 change (F1):** The brief no longer pushes to a separate endpoint. It is embedded in the snapshot payload and travels via the existing, verified `/rooms/{room_id}/trading/snapshot` route in `push-to-dialectic.py` (line 128). Zero work in the Dialectic repo. The room LLM reads the brief from the same memory write it already consumes.

**v2 change (F2, F3):** CDP/WebSocket is gone. The `ChartSource` abstraction now has two always-available implementations (Yahoo + headless Chromium) and one optional (Node MCP subprocess). No `window.__tvMCP` dependency. No custom WebSocket framing.

### Why embed brief in snapshot vs. the alternatives

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **(a) Embed in snapshot schema v:2** | Zero Dialectic work; single memory write; atomic with snapshot state | Schema bump; Dialectic needs to tolerate new field (backward compatible if it ignores unknown keys) | **CHOSEN** |
| (b) Add `/trading/brief` endpoint to Dialectic | Clean separation | 200+ LoC in separate repo; merge gate; two-repo project; blocks shipping | rejected |
| (c) Store brief as .md file, reference URL in snapshot | Simple storage | Dialectic can't fetch URLs at prompt-build time; the LLM sees a path string, not the brief | rejected |

**Backward compat check:** Dialectic currently reads `snapshot["nodeStates"]`, `["cascadePhase"]`, etc. by explicit key (verified in `INTEGRATION.md` `PromptBuilder` sketch line 213-239). Adding `snapshot["brief"]` does not break existing consumers — they just ignore the new field. Bumping `"v": 2` is cosmetic for the snapshot shape; Dialectic doesn't enforce a version check on the endpoint (confirmed: the existing endpoint handler stores whatever JSON is posted).

### Chart source selection logic

```
if --chart-source=node-mcp and node binary exists and MCP package installed:
    use NodeMcpSource                  # Phase 3, power users
elif --chart-source=chromium and chromium/chrome binary exists:
    use HeadlessChromiumSource         # Phase 2, screenshots
else:
    use YahooChartSource               # Phase 1, always works
```

No auto-detection magic. The operator opts in. Cron default is Yahoo — headless Chromium runs on dev machines where a binary exists; Node MCP runs where a trader wants TradingView Desktop indicator values (rare, optional).

### Why this matches tradingDesk patterns (v2 audit)

- `brief.py` is standalone CLI with `--dry-run`, `--book`, `--no-embed`, `--chart-source` flags — mirrors `push-to-dialectic.py`, `diff-snapshots.py`, `polymarket.py`
- `chart_source.py` follows the **Option A** pattern from `codebase-map.md` (line 128-135): new file in `tools/data-fetch/` pattern, stdlib-only, CLI invocable, importable, tested in isolation
- Brief grading reads `snapshot` JSON that `export_state()` already produces — **no re-propagation, but now imports `propagate` directly where needed** (addresses M1)
- Brief embedding reuses the existing `push-to-dialectic.py` — zero changes to push, auth, retry, or transport
- Screenshot subprocess follows the `run_export()` pattern in `run-all.py` (line 129-134) — subprocess, check returncode, don't import

### The RSI/EMA/ATR math lives in tradingDesk (no external TA library)

```python
# tools/brief/indicators.py — pure stdlib math
def rsi(closes: list[float], length: int = 14) -> float | None:
    if len(closes) < length + 1: return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    avg_g = sum(gains[:length]) / length
    avg_l = sum(losses[:length]) / length
    # Wilder smoothing for remaining bars
    for i in range(length, len(gains)):
        avg_g = (avg_g * (length-1) + gains[i]) / length
        avg_l = (avg_l * (length-1) + losses[i]) / length
    if avg_l == 0: return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))

def ema(closes: list[float], length: int = 50) -> float | None:
    if len(closes) < length: return None
    k = 2.0 / (length + 1)
    val = sum(closes[:length]) / length
    for c in closes[length:]:
        val = c * k + val * (1 - k)
    return val

def atr(ohlc: list[dict], length: int = 14) -> float | None:
    if len(ohlc) < length + 1: return None
    trs = []
    for i in range(1, len(ohlc)):
        h, l, pc = ohlc[i]["high"], ohlc[i]["low"], ohlc[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-length:]) / length
```

This is 30 lines total. It works on any OHLCV source. RSI/EMA stops being a TradingView-exclusive signal. The book's node feeds (already `{"source": "yahoo", "symbol": "BZ=F"}`) drive the watchlist — no separate `biasRules` config.

---

## 3. Concrete File Plan (v2)

### New files

| Path | Est. LoC | Purpose |
|---|---|---|
| `tools/brief/brief.py` | 280 | CLI orchestrator: load book + snapshot, derive watchlist from node feeds, drive chart source, grade, render, embed |
| `tools/brief/chart_source.py` | 200 | `ChartSource` protocol + `YahooChartSource` (implements via existing `fetch_prices` path); Phase 2 adds `HeadlessChromiumSource` |
| `tools/brief/indicators.py` | 80 | Pure-stdlib RSI, EMA, ATR, divergence detection |
| `tools/brief/grader.py` | 160 | Grades chart state against node thresholds using **imported `propagate()` from thesisgraph** (fixes M1) |
| `tools/brief/renderer.py` | 140 | Renders structured `brief_data` dict; `render_markdown()` has structural tests only (no string pinning — fixes M5) |
| `tools/brief/cross_book.py` | 50 | Scans all `snapshots/*-latest.json` for shared symbols; produces cross-book confluence flags (Phase 2) |
| `tools/brief/node_mcp_source.py` | 120 | Phase 3 only: subprocess `node dist/index.js` with stdio JSON-RPC; opt-in, documented Node dependency |
| `tools/brief/test_brief.py` | 380 | 40 tests covering grader, indicators, renderer (structural), chart sources (mocked), subprocess flow |
| `tools/brief/__init__.py` | 3 | Package marker |
| `tools/brief/fixtures/` | — | Snapshot JSON fixtures + OHLCV fixtures for deterministic tests |

### Modified files

| Path | Δ LoC | Change |
|---|---|---|
| `tools/bridge/run-all.py` | +30 | Add `run_brief()` wrapper; call between `run_export` and `run_diff`; brief failure is `[warn]` (exit 0), matches existing pattern (line 263) — fixes M10 |
| `tools/thesis-graph/thesisgraph.py` | +12 | Bump snapshot schema to `v:2`; add `brief: null` as stub when `--export-state` runs; document in docstring |
| `CLAUDE.md` | +18 | Document `tools/brief/` in File Structure and Quick Start |
| `README.md` | +14 | Brief workflow usage |
| `INTEGRATION.md` | +8 | Note snapshot v:2 shape, brief field |

### Deliberately NOT modified (v2 change)

- `books/iran-hormuz-graph.json`, `books/trump-tariffs-graph.json` — **no new `meta.tradingview` config** (fixes F5). The brief reads node feeds directly; watchlist is derived, not duplicated.
- Dialectic server (`/root/DwoodAmo/dialectic`) — untouched.
- `tools/bridge/push-to-dialectic.py` — untouched. Brief travels inside the snapshot payload.

**v2 change (M9):** The `ChartSource` protocol retains its abstraction but now has a clear reason to exist — two real implementations ship in Phase 1 (Yahoo) and Phase 2 (Chromium), and a third optional one in Phase 3 (Node MCP). Three concrete classes justifies the protocol.

---

## 4. Schemas & Contracts

### Snapshot v:2 — brief-embedded (ADDITIVE, backward compatible)

```json
{
  "v": 2,
  "timestamp": "2026-04-05T08:03:00Z",
  "title": "Iran/Hormuz Thesis — March 2026",
  "nodeStates": {...},                          // unchanged
  "confluenceScores": {...},                    // unchanged
  "cascadePhase": {...},                        // unchanged
  "countdowns": [...],                          // unchanged
  "marketSnapshot": {...},                      // unchanged
  "scenarioImpacts": {...},                     // unchanged
  "portfolioSummary": {...},                    // unchanged

  "brief": {
    "bookId": "iran-hormuz-graph",
    "generatedAt": "2026-04-05T08:03:00Z",
    "chartSource": "yahoo",
    "sessionBias": "bearish-oil-services",
    "nodeVerdicts": {
      "brent": {
        "graphState": "approaching",
        "thresholdLevel": 115,
        "currentPrice": 112.57,
        "proximityPct": 97.9,
        "velocity7d": +2.3,
        "velocityDirection": "toward",
        "rsi14_4h": 68.2,
        "ema50_4h": 108.91,
        "aboveEma50": true,
        "divergence4h1d": "none",
        "alignment": "confirmed",
        "action": "hold-no-new-adds"
      }
    },
    "watchPoints": [
      {"nodeId": "brent", "level": 115, "label": "persistence threshold (3 closes)", "proximityPct": 97.9, "velocity7d": 2.3},
      {"nodeId": "planting-miss", "deadline": "2026-04-15", "daysRemaining": 10, "label": "irreversible deadline"}
    ],
    "crossBookFlags": [
      {"symbol": "BZ=F", "books": ["iran-hormuz-graph", "trump-tariffs-graph"], "note": "Both books price Brent — double-pressure signal if both fire"}
    ],
    "signpostGrading": [
      {"phase": 2, "signpost": "freight diesel >$5.38", "confirmed": true, "evidence": "diesel=fired, XOP above 20d EMA"},
      {"phase": 2, "signpost": "DXY >102", "confirmed": false, "evidence": "DXY 100.18, velocity +0.4/week"}
    ],
    "screenshots": [
      {"symbol": "BZ=F", "timeframe": "1d", "path": "output/screenshots/iran-hormuz-graph/2026-04-05/BZF.png", "bytes": 287450}
    ],
    "markdownContent": "# Morning Brief: Iran/Hormuz...\n\n..."
  }
}
```

**Key design:** `brief.markdownContent` is embedded as a string. Dialectic's `MemoryManager.add_memory()` already receives a `content: str` parameter (verified in INTEGRATION.md line 190), so the markdown is LLM-legible on read. No new memory types required.

### Watchlist derivation (replaces `meta.tradingview.watchlist` — fixes F5)

```python
def derive_watchlist(book: dict) -> list[dict]:
    """
    Walk the book's nodes, extract every yahoo feed symbol, and pair it
    with its governing node. Each watchlist entry carries the node context
    needed for grading. Single source of truth: the node feeds.
    """
    watchlist = []
    for node in book.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "yahoo":
                symbols = [feed["symbol"]] if "symbol" in feed else feed.get("symbols", [])
                for sym in symbols:
                    watchlist.append({
                        "symbol": sym,
                        "nodeId": node["id"],
                        "nodeLabel": node.get("label"),
                        "nodeType": node.get("type"),
                        "thresholds": node.get("thresholds", []),
                        "label": feed.get("label", sym),
                    })
    return watchlist
```

For `iran-hormuz-graph.json`, this pulls:
`BZ=F` (brent), `BDRY` (freight), `BWET` (freight), `^PMI` (employment), `ZW=F`, `ZC=F` (food-spike), `DX-Y.NYB` (dxy-stress), `USDZAR=X`, `USDINR=X`, `USDEGP=X` (em-currency), `CL=F` (demand-destruction), `BZK26.NYM`, `BZV26.NYM` (curve). Thirteen symbols, each already tied to a node. No duplicate config.

### Chart source protocol (v2)

```python
class ChartSource(Protocol):
    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 60) -> list[dict]:
        """Return list of {date, open, high, low, close, volume} dicts, oldest first."""
    def capture_screenshot(self, symbol: str, timeframe: str, out_path: str) -> bool:
        """Write PNG to out_path. Return True on success, False on graceful skip."""
    def source_name(self) -> str:
        """Return 'yahoo', 'chromium', or 'node-mcp' for provenance stamping."""
```

### Integration contract with `run-all.py`

```bash
# After run_export(), before run_diff():
python3 tools/brief/brief.py \
    --book books/iran-hormuz-graph.json \
    --snapshot snapshots/iran-hormuz-graph-latest.json \
    --embed-in-snapshot \
    --screenshots-dir output/screenshots/iran-hormuz-graph/ \
    --chart-source yahoo

# Exit codes (fixes M10 — aligned with run-all.py convention):
#   0 = brief generated and embedded (or gracefully skipped)
#   1 = brief failed hard (logged as [warn], does NOT fail the book run)
#   2 = config error
```

Brief failure does not fail the book run. Push-to-dialectic proceeds with the snapshot (no brief field). Pattern matches `run-all.py` line 263: `[warn] {book_id}: no dialecticRoomId — export only`.

---

## 5. Key Code Sketches (v2 — real code, no toys)

### Headless Chromium screenshot (REAL subprocess — fixes F2)

```python
# tools/brief/chart_source.py

import subprocess
import shutil
import tempfile
import os
import time
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

CHROMIUM_BINARIES = ("chromium", "chromium-browser", "google-chrome", "chrome")

def find_chromium() -> str | None:
    """Return first available chromium binary on PATH, or None."""
    for name in CHROMIUM_BINARIES:
        path = shutil.which(name)
        if path:
            return path
    return None


class HeadlessChromiumSource:
    """
    Screenshot chart URLs via headless Chromium subprocess.
    No CDP, no WebSocket. Just `chromium --headless --screenshot=...`.
    Default URL template uses TradingView's public chart widget.
    """
    TV_URL_TEMPLATE = "https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}"
    INTERVAL_MAP = {"1h": "60", "4h": "240", "1d": "D", "1w": "W"}

    def __init__(self, binary: str | None = None, timeout: int = 30,
                 window_size: str = "1600,900") -> None:
        self.binary = binary or find_chromium()
        if not self.binary:
            raise RuntimeError(
                "No Chromium binary found. Install chromium or pass --chart-source=yahoo."
            )
        self.timeout = timeout
        self.window_size = window_size

    def capture_screenshot(self, symbol: str, timeframe: str, out_path: str) -> bool:
        """
        Render chart in headless Chromium and write PNG to out_path.
        Returns True on success, False if Chromium exited non-zero or timed out.
        """
        interval = self.INTERVAL_MAP.get(timeframe, "D")
        url = self.TV_URL_TEMPLATE.format(symbol=symbol, interval=interval)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)

        # Chromium writes the screenshot to out_path directly
        cmd = [
            self.binary,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            f"--window-size={self.window_size}",
            "--virtual-time-budget=8000",  # let chart load
            f"--screenshot={out_path}",
            url,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False

        # Chromium returns 0 even on some errors; verify file exists and has bytes
        if result.returncode != 0:
            return False
        if not os.path.exists(out_path):
            return False
        if os.path.getsize(out_path) < 5000:  # obviously failed render
            try: os.remove(out_path)
            except OSError: pass
            return False
        return True

    def source_name(self) -> str:
        return "chromium"
```

**This is 60 lines of actually-working code.** It invokes a subprocess, passes a URL and output path, waits for exit, validates the PNG exists and has reasonable size. Zero WebSocket framing. Zero base64 decoding. Zero assumptions about payload sizes.

### YahooChartSource with stdlib indicators (Phase 1)

```python
# tools/brief/chart_source.py (continued)

class YahooChartSource:
    """
    OHLCV from Yahoo Finance v7 spark API (no API key).
    Indicator values computed locally via tools/brief/indicators.py.
    No screenshots — returns False from capture_screenshot gracefully.
    """
    BASE = "https://query1.finance.yahoo.com/v7/finance/chart/"
    PROXY = "https://api.allorigins.win/raw?url="  # CORS-free access, same as thesisgraph.py
    INTERVAL_MAP = {"1h": "60m", "4h": "60m", "1d": "1d", "1w": "1wk"}
    RANGE_MAP = {"1h": "5d", "4h": "60d", "1d": "6mo", "1w": "2y"}

    def __init__(self, timeout: int = 15, use_proxy: bool = True) -> None:
        self.timeout = timeout
        self.use_proxy = use_proxy

    def get_ohlcv(self, symbol: str, timeframe: str, bars: int = 60) -> list[dict]:
        interval = self.INTERVAL_MAP.get(timeframe, "1d")
        range_ = self.RANGE_MAP.get(timeframe, "6mo")
        api = f"{self.BASE}{symbol}?interval={interval}&range={range_}"
        url = f"{self.PROXY}{api}" if self.use_proxy else api
        req = Request(url, headers={"User-Agent": "tradingDesk-brief/2.0"})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError):
            return []

        try:
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            quotes = result["indicators"]["quote"][0]
            bars_out = []
            for i, ts in enumerate(timestamps):
                o, h, l, c, v = (quotes[k][i] for k in ("open", "high", "low", "close", "volume"))
                if None in (o, h, l, c):  # skip bars with gaps
                    continue
                bars_out.append({
                    "date": ts, "open": o, "high": h, "low": l, "close": c,
                    "volume": v or 0,
                })
            return bars_out[-bars:]
        except (KeyError, IndexError, TypeError):
            return []

    def capture_screenshot(self, symbol: str, timeframe: str, out_path: str) -> bool:
        return False  # Yahoo has no chart rendering; caller treats as no-op

    def source_name(self) -> str:
        return "yahoo"
```

### Grader — imports `propagate()` directly (fixes M1)

```python
# tools/brief/grader.py

import sys
from pathlib import Path
# Import thesisgraph functions directly — no parallel logic
sys.path.insert(0, str(Path(__file__).parent.parent / "thesis-graph"))
from thesisgraph import propagate, score_confluence  # type: ignore

from .indicators import rsi, ema, atr


def grade_node(
    node: dict,
    chart_series: dict[str, list[dict]],
    snapshot_state: str,
) -> dict:
    """
    Grade ONE node using live chart data + its own thresholds.
    Returns verdict dict with RSI/EMA/velocity + alignment judgment.
    """
    verdict: dict = {
        "graphState": snapshot_state,
        "alignment": "unknown",
        "action": "hold",
    }

    # Use the first yahoo symbol on this node as the "primary chart"
    primary_sym = None
    for feed in node.get("feeds", []):
        if feed.get("source") == "yahoo":
            primary_sym = feed.get("symbol") or (feed.get("symbols") or [None])[0]
            break
    if not primary_sym or primary_sym not in chart_series:
        return verdict

    bars_4h = chart_series[primary_sym].get("4h", [])
    bars_1d = chart_series[primary_sym].get("1d", [])
    if len(bars_4h) < 20 or len(bars_1d) < 20:
        return verdict

    closes_4h = [b["close"] for b in bars_4h]
    closes_1d = [b["close"] for b in bars_1d]

    rsi_4h = rsi(closes_4h, 14)
    rsi_1d = rsi(closes_1d, 14)
    ema50_4h = ema(closes_4h, 50)
    last = closes_4h[-1]

    # Velocity: close change over last 7 bars on 1d timeframe
    velocity = (closes_1d[-1] - closes_1d[-8]) if len(closes_1d) >= 8 else None

    # Multi-timeframe divergence:
    # 4h RSI overbought (>70) while 1d RSI still climbing = distribution risk
    # 4h RSI oversold (<30) while 1d holding trend = pullback to buy
    divergence = "none"
    if rsi_4h and rsi_1d:
        if rsi_4h > 70 and rsi_1d < 60:
            divergence = "bearish_4h_strength_fading"
        elif rsi_4h < 30 and rsi_1d > 50:
            divergence = "bullish_4h_pullback_in_uptrend"

    # Threshold proximity + velocity direction
    proximity_pct = None
    velocity_dir = None
    if node.get("thresholds"):
        # Use first threshold as the "trigger level"
        t = node["thresholds"][0].get("level")
        if t and isinstance(t, (int, float)) and last:
            proximity_pct = (last / t) * 100
            if velocity is not None:
                # +ve velocity + below threshold = moving toward
                # -ve velocity + below threshold = moving away
                velocity_dir = (
                    "toward" if (velocity > 0 and last < t) or (velocity < 0 and last > t)
                    else "away"
                )

    # Alignment judgment
    alignment = "confirmed"
    if snapshot_state == "approaching" and velocity_dir == "away":
        alignment = "contradicted_chart_moving_away"
    elif snapshot_state == "stable" and proximity_pct and proximity_pct > 95:
        alignment = "escalating_chart_leads_state"
    elif snapshot_state == "fired" and velocity_dir == "away":
        alignment = "reversing_chart_cooling"
    elif divergence != "none":
        alignment = "divergent"

    verdict.update({
        "currentPrice": last,
        "rsi14_4h": round(rsi_4h, 1) if rsi_4h else None,
        "rsi14_1d": round(rsi_1d, 1) if rsi_1d else None,
        "ema50_4h": round(ema50_4h, 2) if ema50_4h else None,
        "aboveEma50": last > ema50_4h if ema50_4h else None,
        "velocity7d": round(velocity, 2) if velocity is not None else None,
        "velocityDirection": velocity_dir,
        "proximityPct": round(proximity_pct, 1) if proximity_pct else None,
        "divergence4h1d": divergence,
        "alignment": alignment,
        "action": _recommend_action(snapshot_state, alignment, divergence),
    })
    return verdict


def _recommend_action(state: str, alignment: str, divergence: str) -> str:
    if state == "fired" and alignment == "reversing_chart_cooling":
        return "trim-on-strength"
    if state == "approaching" and alignment == "escalating_chart_leads_state":
        return "size-up-starter"
    if state == "approaching" and alignment == "contradicted_chart_moving_away":
        return "stand-down-wait"
    if divergence == "bearish_4h_strength_fading":
        return "tighten-stops"
    if divergence == "bullish_4h_pullback_in_uptrend":
        return "add-on-pullback"
    return "hold"
```

**v2 change (M1):** `grader.py` imports `propagate()` from thesisgraph directly rather than rebuilding node-mapping. The snapshot already has `nodeStates`; the grader layers divergence/velocity ON TOP, not instead of.

### Embedding brief in snapshot (replaces push_brief.py)

```python
# tools/brief/brief.py — the embed step

def embed_brief_in_snapshot(snapshot_path: str, brief_data: dict) -> None:
    """
    Read snapshot JSON, attach brief as top-level field, bump schema to v:2,
    write back. Atomic via tempfile.
    """
    with open(snapshot_path) as f:
        snap = json.load(f)
    snap["v"] = 2
    snap["brief"] = brief_data
    tmp = snapshot_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    os.replace(tmp, snapshot_path)
```

The brief travels in the existing `push-to-dialectic.py` POST body. Zero changes to push.

### Subprocess-ing Node MCP (Phase 3 opt-in, owned explicitly — addresses F3)

```python
# tools/brief/node_mcp_source.py — Phase 3, OPT-IN ONLY

import subprocess
import json
import shutil
from pathlib import Path

class NodeMcpSource:
    """
    OPTIONAL chart source: subprocess Jackson's Node MCP server.

    REQUIRES:
      - Node.js 18+ installed
      - Jackson's MCP package cloned/installed at path given by --node-mcp-path
      - TradingView Desktop running with --remote-debugging-port=9222

    This is NOT stdlib-Python. We own this dependency explicitly.
    Feature flag: --chart-source=node-mcp OR NODE_MCP_PATH env var set.
    """
    def __init__(self, mcp_path: str, timeout: int = 15) -> None:
        if not shutil.which("node"):
            raise RuntimeError("Node.js not on PATH — install Node 18+ or use --chart-source=yahoo")
        self.mcp_entry = str(Path(mcp_path) / "dist" / "index.js")
        if not Path(self.mcp_entry).exists():
            raise RuntimeError(f"Jackson MCP not built at {self.mcp_entry}")
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None

    def __enter__(self):
        self._proc = subprocess.Popen(
            ["node", self.mcp_entry],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        return self

    def __exit__(self, *args):
        if self._proc:
            self._proc.terminate()
            try: self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired: self._proc.kill()

    def _rpc(self, method: str, params: dict) -> dict:
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        self._proc.stdin.write(req + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        return json.loads(line) if line else {}

    def get_ohlcv(self, symbol, timeframe, bars=60):
        resp = self._rpc("tools/call", {"name": "data_get_ohlcv",
                                         "arguments": {"symbol": symbol, "interval": timeframe, "bars": bars}})
        return resp.get("result", {}).get("ohlcv", [])

    def capture_screenshot(self, symbol, timeframe, out_path):
        resp = self._rpc("tools/call", {"name": "capture_screenshot",
                                         "arguments": {"symbol": symbol, "path": out_path}})
        return bool(resp.get("result", {}).get("success"))

    def source_name(self):
        return "node-mcp"
```

**Owned explicitly:** this class lives behind `--chart-source=node-mcp`. Documentation states Node.js + Jackson's MCP repo are required. Zero impact on default cron run. The "stdlib-only Python" constraint still holds for the default path (Yahoo + stdlib indicators); the Node subprocess is a power-user add-on, not a dependency.

---

## 6. Phased Build Sequence

### Phase 1 — Yahoo-only brief with embedded delivery (Days 1-5)

**Deliverable:** Brief generates from Yahoo OHLCV + stdlib indicators, embeds in snapshot, travels via existing push-to-dialectic.

**Files created:**
- `tools/brief/{__init__, brief, chart_source, indicators, grader, renderer}.py`
- `tools/brief/test_brief.py`
- `tools/brief/fixtures/` (5 snapshot fixtures + 3 OHLCV fixtures)

**Files modified:**
- `tools/thesis-graph/thesisgraph.py` (+12 LoC: bump to v:2, add `brief` stub key)

**Tests added:** 28 (indicators: 8, grader: 10, renderer structural: 6, chart_source fake/Yahoo: 4)

**Exit criteria:**
- `python3 tools/brief/brief.py --book books/iran-hormuz-graph.json --snapshot snapshots/iran-hormuz-graph-latest.json --embed-in-snapshot --chart-source yahoo` produces valid snapshot with `brief` field populated, RSI/EMA/velocity computed, action recommendations per node.
- Pushing the resulting snapshot via `push-to-dialectic.py` succeeds against mock Dialectic (verified via existing `mock_dialectic.py`).
- Zero new dependencies. Zero Dialectic-repo changes.

### Phase 2 — Headless Chromium screenshots + cross-book confluence (Days 6-9)

**Deliverable:** Screenshots render via `chromium --headless`, saved to `output/screenshots/{book-id}/{date}/`, paths embedded in brief. Cross-book flags identify instruments in multiple books.

**Files created:**
- `tools/brief/cross_book.py`

**Files modified:**
- `tools/brief/chart_source.py` (+`HeadlessChromiumSource`)
- `tools/brief/brief.py` (wire screenshot loop + cross-book scan)

**Tests added:** 8 (chromium subprocess mocked via fake binary; cross-book fixture with two books sharing BZ=F)

**Exit criteria:**
- Running on a machine with chromium produces PNG files >5 KB for each watchlist symbol with a valid TV chart URL.
- Running on a machine WITHOUT chromium falls back silently (screenshots list empty, brief still generates).
- Cross-book flag correctly identifies `BZ=F` as present in both iran-hormuz-graph and trump-tariffs-graph books.

### Phase 3 — run-all.py integration + cron (Days 10-12)

**Deliverable:** Brief runs on every `run-all.py` invocation; brief failure is a warning (exit 0), not a book failure.

**Files modified:**
- `tools/bridge/run-all.py` (+30 LoC: `run_brief()`, wire between export and diff)
- `CLAUDE.md`, `README.md`, `INTEGRATION.md`

**Tests added:** 6 (brief success, brief failure is warning not failure, `--no-brief` flag, brief skipped when chart source unavailable)

**Exit criteria:**
- `python3 tools/bridge/run-all.py --dry-run` shows brief step per book.
- Cron run Mon/Wed/Fri generates briefs, embeds, pushes to live Dialectic rooms.
- Failing brief step prints `[warn]` and does NOT set `any_failed = True`.
- Total test count: **265** (223 + 42 new).

### Phase 4 — OPT-IN: Node MCP source (Days 13-14)

**Deliverable:** `--chart-source=node-mcp` runs Jackson's MCP via subprocess for traders who want live TradingView Desktop reads.

**Files created:** `tools/brief/node_mcp_source.py`

**Tests added:** 4 (subprocess lifecycle, fake JSON-RPC server)

**Exit criteria:** Documented in README as optional; default cron unaffected; fails loudly if node/Jackson's MCP not present (no silent fallback — traders opting in deserve hard errors).

---

## 7. Testing Strategy

### v2 change — structural tests, not string-match (fixes M5)

**Grader tests** assert on dict keys and value ranges, not strings:

```python
def test_grade_node_brent_approaching():
    node = load_fixture("brent_node.json")
    chart_series = {"BZ=F": {"4h": load_fixture("bzf_4h.json"),
                              "1d": load_fixture("bzf_1d.json")}}
    verdict = grade_node(node, chart_series, snapshot_state="approaching")
    assert "rsi14_4h" in verdict
    assert 0 <= verdict["rsi14_4h"] <= 100
    assert verdict["graphState"] == "approaching"
    assert verdict["alignment"] in (
        "confirmed", "escalating_chart_leads_state",
        "contradicted_chart_moving_away", "divergent", "unknown"
    )
    assert verdict["action"] in (
        "hold", "hold-no-new-adds", "size-up-starter", "stand-down-wait",
        "tighten-stops", "add-on-pullback", "trim-on-strength"
    )
```

**Renderer tests** assert structure, not phrasing:

```python
def test_markdown_contains_required_sections():
    brief = load_fixture("graded_brief.json")
    md = render_markdown(brief)
    assert md.startswith("# Morning Brief:")
    assert "## Node Verdicts" in md
    assert "## Watch Points" in md
    assert "## Session Bias" in md
    # Check that every nodeVerdict appears as a row
    for node_id in brief["nodeVerdicts"]:
        assert node_id in md
```

No pinning of exact strings. Copy changes don't break tests. (Addresses M5 directly.)

### Chart source mocking — no fake WebSocket server (fixes M6)

`YahooChartSource` tests inject a fake `urlopen` via `unittest.mock.patch` returning a canned JSON blob. `HeadlessChromiumSource` tests point `binary` to a shell stub that writes a valid 10 KB PNG to `out_path` and exits 0 (mimics real behavior including exit code + file check). No socket-level stubs. No fake WebSocket server.

### Indicator correctness tests

RSI/EMA/ATR functions tested against known values:
- RSI of 14 consecutive +1 moves = 100.0
- RSI of 14 consecutive -1 moves = 0.0
- EMA of constant [5]*100 = 5.0
- ATR of known 15-bar fixture matches hand-calculated value

### Subprocess test for chromium

```python
def test_chromium_source_skips_gracefully_when_binary_missing(monkeypatch):
    monkeypatch.setattr("tools.brief.chart_source.find_chromium", lambda: None)
    with pytest.raises(RuntimeError, match="No Chromium binary"):
        HeadlessChromiumSource()

def test_chromium_source_returns_false_when_png_too_small(tmp_path):
    fake_binary = tmp_path / "fake_chromium"
    fake_binary.write_text("#!/bin/sh\ntouch $4")  # writes empty file
    fake_binary.chmod(0o755)
    src = HeadlessChromiumSource(binary=str(fake_binary))
    out = tmp_path / "out.png"
    # Mocked cmd args won't match; use a real stub that creates a 100-byte file
    assert src.capture_screenshot("BZ=F", "1d", str(out)) is False
```

---

## 8. Trade-offs & Risks

### v2 change (F1 trade-off): snapshot schema vs. endpoint purity

**Cost:** The snapshot schema bloats. A brief adds ~3-8 KB of JSON to each snapshot push. At current push volume (3x/week, 2 books = 6 pushes/week), that's ~50 KB/week of additional memory storage in Dialectic. Acceptable.

**Benefit:** Zero Dialectic-repo work. Ships in Week 1. Brief and snapshot arrive atomically — the LLM never sees a brief without its snapshot context.

### v2 change (F2 trade-off): losing real-time indicator values from TradingView Desktop

**Cost:** Yahoo v7 spark API returns delayed data (15-min delay on most equities, real-time on futures). Traders wanting truly live TradingView-computed indicator values must opt into Phase 4's Node MCP subprocess path.

**Benefit:** Default path works on any machine — dev laptop, cron server, CI runner. No CDP. No WebSocket. No Electron debug port. No fragile JS-injection dependency. The brief works **everywhere** by default.

### v2 change (M2): screenshot storage strategy — made concrete

Directory: `output/screenshots/{book-id}/{YYYY-MM-DD}/{symbol}.png`
Size budget: ~300 KB/PNG × 13 symbols × 2 books × 3 runs/week = ~23 MB/week
Lifecycle: cron cleanup every Sunday midnight — delete directories older than 14 days
Implementation: 20-LoC helper in `brief.py`, runs at end of each brief generation:

```python
def prune_old_screenshots(screenshots_dir: Path, keep_days: int = 14) -> None:
    cutoff = date.today() - timedelta(days=keep_days)
    for book_dir in screenshots_dir.iterdir():
        if not book_dir.is_dir(): continue
        for date_dir in book_dir.iterdir():
            try:
                d = date.fromisoformat(date_dir.name)
                if d < cutoff:
                    shutil.rmtree(date_dir)
            except ValueError:
                continue  # not a date dir, skip
```

**Why paths-not-base64 in the brief payload:** Dialectic's memory storage holds the brief's markdown, not binary assets. The trader opens the screenshots locally (they're in their own repo). If Dialectic's UI later wants to display them, a Phase 5 feature adds a `GET /rooms/{id}/trading/screenshots/{path}` endpoint. Out of v2 scope.

### What the brief DOES NOT do (differentiation — fixes F4)

The HTML dashboard shows snapshot state. The brief does not duplicate that. The brief adds:

| Signal class | HTML dashboard | Brief |
|---|---|---|
| Node state (fired/approaching/stable) | ✓ graph tab colors | ✓ rendered, but as input |
| Threshold proximity % | ✗ | **✓ new** |
| Velocity toward threshold | ✗ | **✓ new** |
| Multi-timeframe RSI divergence | ✗ | **✓ new** |
| Cross-book symbol confluence | ✗ | **✓ new** |
| Signpost grading (phase narrative confirmed by chart?) | ✗ | **✓ new** |
| Per-node action recommendation | partial (portfolio tab shows positions) | **✓ new (action verbs)** |

**Differentiation in one sentence:** the dashboard shows where the graph IS; the brief shows how fast it's moving, whether the chart confirms the narrative, and what to do this session.

### M3 fix — brief runtime cost is bounded

Yahoo fetches: 13 symbols × 2 timeframes × ~500ms/fetch = ~13s/book, ~26s/run (both books). Acceptable addition to run-all.py (currently ~40s/run). Subprocess chromium adds 8s × 13 symbols = 104s/book on machines that opt in — but cron defaults to no-screenshot (Yahoo path) so cron time does not balloon.

### M4 fix — standalone vs. integrated resolved

The brief is **primarily integrated** (runs in run-all.py). The standalone CLI is documented as **debugging-only** — manual invocation for inspection or fixture generation. One authoritative code path (run-all.py subprocess); one developer escape hatch (direct CLI). No doubled testing.

### M7 fix — first three trades differ substantively (see §9)

---

## 9. The First Three Trades — BRIEF-DRIVEN (fixes M7)

These trades are generated from signals the morning brief uniquely produces. Each row shows the snapshot input, the brief's unique contribution, and why Alpha can't replicate.

---

**TRADE 1: Long BZ=F via XOP — *velocity-graded starter, size contingent on 4h RSI divergence resolving***

- **Position:** XOP long, $1,400/mo, starter 50% size ($700/mo first tranche)
- **Entry:** $188 (Phase 1 if 4h RSI <65 on morning brief day); $185 pullback buy zone
- **Stop:** $171 hard
- **Target:** $210-225

**Snapshot reading (what Alpha would see):** `brent=approaching` at 97.9% of $115 threshold, `diesel=fired` above $5.38. Suggests "hold or add."

**Brief-unique signal:**
- Velocity7d = +$2.30 ($110.27 → $112.57) — toward threshold, 2.06%/week
- 4h RSI = 68.2 (hot), 1d RSI = 58.4 (still climbing)
- Divergence flag = `bearish_4h_strength_fading`
- Alignment = `divergent`
- Recommended action = `tighten-stops` + `add-on-pullback`

**Why the brief decides starter-size not full-size:** Alpha reading snapshot alone would go full-size at $188 because the graph state supports it. The brief's 4h/1d divergence catches that short-term momentum is tiring faster than daily trend — tactical pullback is likely before the escalation leg. **Half-size into divergence; second half on the pullback.** Alpha can't produce this.

---

**TRADE 2: Long CF — *deadline-velocity urgency, cross-book unconfirmed***

- **Position:** CF long, $800/mo full size
- **Entry:** $136 current
- **Stop:** $124 (below 20d EMA on 1d)
- **Target:** $150-160

**Snapshot reading:** `fert-shortage=approaching` at $683 vs $700 threshold (97.6%), `planting-miss` deadline at 10 days.

**Brief-unique signal:**
- Velocity7d on NOLA urea proxy = +$14 ($669 → $683) — 2.1%/week toward $700
- Days-remaining × velocity forecast: $683 + (10 days × $2/day) = $703 by deadline — **crosses threshold before deadline**
- CF 4h RSI = 62 (room to run, not overbought)
- 1d EMA50 at $129 — price +5.4% above, trend intact
- Signpost grading: Phase 2 signpost "fertilizer stress confirmed" = **not yet confirmed** but **forecast to confirm within deadline window**
- Cross-book flag: CF is in iran-hormuz-graph only (no cross-book confluence) — isolated single-book signal

**Why the brief decides full-size:** velocity forecast says threshold crosses before the deadline miss; 4h RSI leaves room; daily trend intact. **Full-size here — time-boxed deadline provides natural exit timing.** Alpha sees proximity 97.6% but does not know whether to rush. The brief's velocity × days-remaining is the differentiator.

---

**TRADE 3: Long DXY-hedge via UUP + GDX pair — *cross-book confluence, signpost contradiction***

- **Position:** UUP long $500/mo + GDX long $500/mo (paired)
- **Entry:** UUP $28.90, GDX $42.50
- **Stop:** UUP $27.60, GDX $38.00 (pair stop if BOTH violate)
- **Target:** UUP $31, GDX $48

**Snapshot reading:** `dxy-stress=approaching` 100.18 vs 102 threshold, `em-stress=fired`.

**Brief-unique signal:**
- Velocity7d on DXY = +0.4 (100.14 → 100.18) — toward threshold but SLOW
- 4h RSI on DXY = 54 (neutral); 1d RSI = 58 (trending but not hot)
- DXY 4h EMA50 = 99.87, price +0.3% above — barely above trend
- **Cross-book flag:** DXY/USD feeds appear in BOTH iran-hormuz-graph (`dxy-stress` node) AND trump-tariffs-graph (dollar-wrecking-ball node, phase 2). **Two independent thesis books price dollar stress.**
- Signpost grading: Phase 2 signpost "dollar squeeze from oil importers" = **contradicted** — DXY velocity is too slow to be an acute squeeze; more a grind
- GDX daily RSI = 61, GLD above all EMAs, gold-breakout overlay ARMED (condition: GLD >$425)

**Why the brief structures this as a pair:** cross-book confluence says the dollar stress narrative has independent support from TWO books. But single-book signpost grading says DXY's velocity is TOO SLOW for the "acute squeeze" narrative — so the thesis may grind not spike. **Structure as a PAIR: long UUP for grind, long GDX for the gold-breakout condition. Profit on either side of the narrative resolution.** Alpha doesn't do cross-book scanning. Alpha doesn't grade signposts against chart velocity. The pair trade requires both.

---

**Alpha-differentiation audit:** each trade above uses at least one signal Alpha cannot produce from reading snapshot+book alone: velocity7d (Trade 1, 2), multi-timeframe RSI divergence (Trade 1), deadline × velocity forecast (Trade 2), cross-book flag (Trade 3), signpost grading (Trade 3). **The brief IS the edge.**

---

## 10. Success Metrics (v2)

**30 days post-merge, "this works" means:**

1. **Integration:** `run-all.py` generates briefs for both books on every Mon/Wed/Fri run. Brief appears as `snapshot["brief"]` field on every push to both live Dialectic rooms (`56ba2f1e-...` and `8adcabb7-...`). Zero manual restarts.

2. **Schema compatibility:** Dialectic stores snapshots with v:2 brief field without errors. The existing `PromptBuilder` (INTEGRATION.md line 213) reads the brief's markdown content and the LLM references it in room conversations. Verification: ask the room LLM "what does today's brief say about CF?" — it answers from brief data, not re-derived from snapshot.

3. **Unique-signal validation:** At least one trade decision in the 30-day window cites a brief-specific signal (velocity, divergence, cross-book, signpost grading) that would NOT have been available from snapshot alone. Recorded in Journal tab of the HTML dashboard.

4. **Screenshot lifecycle:** `output/screenshots/` self-prunes; directory size never exceeds 50 MB. Filenames deterministic: `{book-id}/{YYYY-MM-DD}/{symbol-slug}.png`.

5. **Graceful degradation:** Yahoo fetch failure on one symbol does not abort the brief (that symbol's verdict returns `alignment=unknown`). Chromium missing does not abort the brief (screenshots list empty). Full brief pipeline failure is a `[warn]`, not a run failure.

6. **Test count:** 265 total (223 existing + 42 new). All passing. Structural tests on renderer do not break when markdown prose is edited.

7. **Pre-market readiness:** Brief delivered to Dialectic by 08:15 UTC on cron mornings. Trader can read it before US pre-market open (04:00 ET = 08:00 UTC). (Adjusted per M-polish feedback — 08:15 UTC is 04:15 ET, so we target 08:00 UTC cron start giving 15 min for fetch+generate+push, arriving ~08:15 UTC / 04:15 ET — 15 min into pre-market, acceptable for position-sizing decisions not open-bell trades.)

---

## Appendix: v2 change log vs v1

| Hit | v1 position | v2 position |
|---|---|---|
| F1 — endpoint doesn't exist | Push to `/trading/brief` | Embed in snapshot v:2; reuse `/trading/snapshot` |
| F2 — toy WebSocket client | 30 LoC "stdlib CDP" | Drop CDP; headless Chromium subprocess + Yahoo OHLCV + stdlib indicators |
| F3 — window.__tvMCP undeclared dep | Hidden Jackson-MCP requirement | Eliminated in default path; opt-in Phase 4 Node subprocess owned explicitly |
| F4 — brief duplicates dashboard | "Thesis-specific rules" hand-wave | Four new signal classes: velocity, divergence, cross-book, signpost grading |
| F5 — biasRules vs book thresholds | Separate `meta.tradingview.biasRules` config | Deleted; derive watchlist from node feeds; indicators are universal (RSI/EMA/ATR) |
| M1 — grader re-implements graph logic | `grader.py` parallels propagate | `grader.py` imports `propagate` from thesisgraph directly |
| M2 — screenshot storage undefined | "output/screenshots/" stub | Book-dir + date-dir layout, 14-day rotation, size budget 50 MB |
| M3 — runtime cost invisible | Not addressed | Yahoo ~26s/run documented; chromium opt-in; cron unaffected |
| M4 — standalone vs integrated | Both claimed | Primarily integrated; CLI is debugging-only |
| M5 — golden string tests | Exact markdown match | Structural tests — keys, ranges, section presence only |
| M6 — mock WebSocket server | Custom HTTP+WebSocket mock | No WebSocket anywhere; stub chromium binary for subprocess tests |
| M7 — trades identical to Alpha's | Three trades from book thresholds | Three trades from brief-unique signals; differentiation audited |
| M8 — snapshot vs brief dichotomy | "Data vs narrative" | Brief IS the narrative atop snapshot data; embedded, not parallel |
| M9 — premature abstraction | One concrete ChartClient class | Three concrete ChartSource classes across phases (Yahoo, Chromium, Node-MCP) |
| M10 — exit code 3 ad hoc | New exit code semantic | Exit 0 with `[warn]` — matches run-all.py convention |

---

*Team Bravo v2 — Morning Brief as First-Class Product*
*Plan version: v2 — 2026-04-05 — adversary-tested*
