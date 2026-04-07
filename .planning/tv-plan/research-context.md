# Research Context: Claude ↔ TradingView Integration

**Video source:** [How To Connect Claude to Trading View (Insanely Cool)](https://youtu.be/vIX6ztULs4U) by Lewis Jackson (@LewisWJackson)

**Note:** Supadata API rate-limited, yt-dlp bot-blocked, Innertube captions unavailable. Transcript substituted with direct analysis of the repo the video demos.

---

## What the Video Is About (Verified)

The video demonstrates **Lewis Jackson's fork** of `tradesdontlie/tradingview-mcp` — an MCP server that connects Claude Code to a locally-running TradingView Desktop app via Chrome DevTools Protocol (CDP port 9222). The fork adds a **Morning Brief workflow** that automates overnight chart analysis.

Confirming quote from Lewis Jackson's X/Twitter (@Tradesdontlie):
> "claude can now open @tradingview and look at charts for you while youre AFK in scheduled tasks, and you come back to a full report if you so choose"

### Core architecture
```
Claude Code ↔ MCP Server (stdio) ↔ CDP (port 9222) ↔ TradingView Desktop (Electron)
```
- Local-only, no TradingView servers touched
- Requires valid TradingView Desktop subscription
- TypeScript/Node.js (`@modelcontextprotocol/sdk` + `chrome-remote-interface`)

### 81 MCP tools in 8 categories

1. **Morning Brief** (new in Jackson fork) — `morning_brief`, `session_save`, `session_get`
2. **Chart Reading** — `chart_get_state`, `data_get_study_values`, `quote_get`, `data_get_ohlcv`
3. **Pine Drawings** — `data_get_pine_lines`, `_labels`, `_tables`, `_boxes`
4. **Chart Control** — `chart_set_symbol`, `_timeframe`, `_type`, `_manage_indicator`, `scroll_to_date`
5. **Pine Script Dev** — `pine_set_source`, `pine_smart_compile`, `pine_get_errors`, `pine_get_console`, `pine_save`, `pine_analyze`, `pine_check`
6. **Replay Mode** — `replay_start`, `_step`, `_autoplay`, `_trade`, `_status`, `_stop`
7. **Multi-Pane** — `pane_list`, `pane_set_layout` (2h/2v/2x2/4/6/8), `pane_focus`, `pane_set_symbol`
8. **Drawings/Alerts/UI** — `draw_shape`, `alert_create/list/delete`, `capture_screenshot`, `ui_click`, `ui_evaluate`, `batch_run`, `stream` (JSONL)

### The Morning Brief Workflow (Jackson's Addition)

Runs before each session:
1. Open TradingView with `--remote-debugging-port=9222`
2. Run `tv brief` CLI (or call `morning_brief` MCP tool)
3. Server iterates watchlist from `rules.json`, reads indicator values on each symbol
4. Applies bias criteria from rules → classifies each symbol (bullish/bearish/neutral)
5. Generates structured report with bias + key levels + watch points per symbol
6. `session_save` persists to `~/.tradingview-mcp/sessions/` for day-over-day comparison

`rules.json` schema (inferred):
```json
{
  "watchlist": ["SPY", "QQQ", "BTCUSD"],
  "bias": { "rsi_overbought": 70, "rsi_oversold": 30, ... },
  "risk": { "max_stop_distance_atr": 2.0, ... }
}
```

---

## How This Maps to tradingDesk

### The pattern worth stealing
**"LLM opens the chart tool, reads state against rules, reports structured bias."** This is exactly what tradingDesk needs to turn its *thesis graphs* into *morning briefings that grade against live chart state*.

### Where it fits in tradingDesk's existing architecture

tradingDesk is already:
- A causal DAG engine (nodes = economic states, edges = transmission channels)
- Has `--fetch` for live market data (Yahoo Finance + Polymarket)
- Exports snapshots → diffs them → pushes to Dialectic rooms
- Runs via `run-all.py` multi-book pipeline (cron Mon/Wed/Fri)
- Python stdlib-only, 223 tests

### The TradingView integration opportunity

A TradingView bridge to tradingDesk would:

1. **Enrich graph node feeds** — currently nodes get prices from Yahoo Finance. TradingView would add: indicator values (RSI, MACD, Bollinger states), multi-timeframe analysis, custom Pine Script signals.

2. **Supply chart evidence for Dialectic briefings** — when the cascade phase tracker says "WE ARE HERE: Phase 2 Transmission," push chart screenshots of the key instruments to the Dialectic room as evidence.

3. **Morning brief per thesis** — for each active thesis book, scan its mapped instruments, grade them against thesis signposts, push a structured "state of the thesis" brief into Dialectic.

4. **Pine Script alert webhooks → graph node triggers** — TradingView alerts fire when price crosses thresholds; a webhook receiver turns these into node state transitions in the thesis graph. This closes the loop between TradingView and the DAG.

5. **Chart-backed trade sizing** — when a scenario fires, pull current chart state (support/resistance, ATR) to suggest position sizing in the portfolio tab.

### Architectural constraints to respect

- **Zero-dependency Python** — tradingDesk is stdlib-only. Adding TradingView requires either (a) a separate Node.js sidecar for CDP (matches Jackson's MCP stack), (b) a thin HTTP webhook receiver in Python stdlib, or (c) subprocess shelling to an existing MCP server.
- **Self-contained HTML dashboards** — the TradingView integration shouldn't break single-file output.
- **Multi-book pipeline fit** — needs to work inside `run-all.py` per-book sequential execution.
- **Dialectic push format** — snapshot JSON schema already fixed (v:1); TradingView data must fit in the existing `marketSnapshot` field or extend snapshot schema cleanly.
- **TradingView Desktop required** — Jackson's approach requires the paid desktop app running with debug port. We may need an alternative for headless/cron use cases.

---

## Technical Reference Links

- Lewis Jackson's fork: https://github.com/LewisWJackson/tradingview-mcp-jackson
- Original by tradesdontlie: https://github.com/tradesdontlie/tradingview-mcp
- Alternative Python MCP (no desktop): https://github.com/atilaahmettaner/tradingview-mcp (uses Yahoo Finance, Reddit sentiment, no CDP dep)
- MCP Protocol spec: https://modelcontextprotocol.io
- TradingView Pine Script webhooks: https://www.tradingview.com/support/solutions/43000529348/

## Integration Pattern Decision Points

Competing teams must decide:

1. **Bridge mode** — MCP server (Claude-initiated), webhook receiver (TV-initiated), or both?
2. **Language choice** — Stay stdlib Python, or add Node.js sidecar (matches upstream Jackson MCP)?
3. **TradingView Desktop or not** — Jackson's approach requires desktop app; can we work without it using TradingView Scanner API / TradingView's lightweight-charts?
4. **Graph coupling depth** — Thin (chart screenshots as Dialectic attachments only) or deep (chart signals as first-class node feeds)?
5. **Morning brief placement** — Merge into `run-all.py` cron, or separate TV-brief command?
6. **Rules config** — Per-thesis rules inside book JSONs, or global `rules.json` like Jackson's?
