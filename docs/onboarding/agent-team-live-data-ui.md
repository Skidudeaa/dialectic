# Agent-Team Onboarding — Live Data Connectors + UI Mega-Enhancement

**Audience:** An agent team (planner + specialist workers) hired to push tradingDesk from "good-enough demo" to "daily driver for two working analysts + one agent-in-the-loop."

**Scope:** Two intertwined tracks, worked in parallel:

1. **Track A — Real, live data.** Replace brittle proxy-based polling with authoritative, typed feeds. Broaden coverage (macro, rates, FX, futures curve, flow, news, econ calendar) without breaking the stdlib-only contract in `tools/`.
2. **Track B — UI mega-enhancement.** The dashboard already has 5 panels and a builder; it does not yet feel like a trading-desk cockpit. Ship the density, the keyboard-first flows, the live-tape feel, and the collaborative affordances that Amo, Dan, and the LLM-in-room actually need.

Read this whole doc before opening any file. The rest of the repo assumes you already know what's below.

---

## 1. Who the users are — and what they actually do

There are **three** users. Two humans, one agent. Design every feature for all three.

### Amo (Nick Amosson) — primary operator

- Owns the thesis graphs (`books/*.json`) and the trade ledger. Runs the droplet.
- Works in long reasoning sessions — opens the dashboard, flips between books, asks @claude/@gpt/@compare in chat, reads the morning brief, decides whether to fire or kill a trade.
- Hard preferences (see `/root/.claude/projects/-root-tradingDesk/memory/`): everything runs on the DO droplet `167.99.113.232`, never localhost; new features integrate into the FastAPI + React webapp, never parallel services; archive superseded code with breadcrumbs, don't `git rm`.

### Dan (DanWood) — collaborator

- Joins chat rooms with Amo. Reads the same thesis state. Comments, challenges, annotates.
- Does not administer the droplet. Needs the UI to explain itself — tooltips, phase tracker, signpost checklists — because he's not in the code.

### The LLM-in-room — third first-class user

- Reached via `@claude`, `@gpt`, `@gemini`, `@compare` in chat, and via the Dialectic rooms that receive snapshots from `tools/bridge/run-all.py`.
- Needs structured context: node states, confluence scores, cascade phase, countdowns, recent diffs, open trades. The snapshot JSON schema is the contract — don't degrade it.
- **Design rule:** any UI affordance the human has (fire a trade, pin a message, open a scenario) should have an agent-facing equivalent (tool call, slash command, or structured event). Parity is a load-bearing principle, not a nice-to-have.

---

## 2. Current architecture in one page

```
        books/*.json  ─────────┐
        (5 theses: hormuz,     │
         tariffs, ai-capex,    ▼
         china-property,    tools/thesis_graph/thesisgraph.py
         japan-rates)        ─ Kahn topo sort, propagation,
                              scenario probability-weighting,
                              cascade phase detection
                              ─ emits snapshot JSON + HTML dashboard
                                     │
         ┌───────────────────────────┼──────────────────────────┐
         ▼                           ▼                          ▼
 tools/data_fetch/           tools/bridge/                 web/  (FastAPI)
   polymarket.py               run-all.py                    ├─ routes/
   derived_indicators.py       diff_snapshots.py             ├─ adapters/
                               push_to_dialectic.py          └─ ws (WebSocket)
                                                                  │
                                                                  ▼
                                                           frontend/ (React 19)
                                                            Dashboard + Builder
                                                            + Welcome + Onboarding
```

Key invariants you must preserve:

- `tools/` is **stdlib-only**. No `requests`, no `pandas`, no `httpx`. Use `urllib.request`, `json`, `datetime`. Tests are `pytest` but the runtime code is standard library. This is the contract that makes `thesisgraph.py` runnable on any Python 3.10+ machine without setup.
- `web/` may use pinned deps (`requirements.txt`): FastAPI, uvicorn, python-jose, httpx. That's where third-party SDKs live.
- HTML dashboards are **generated artifacts**, single-file, ~750 KB with Cytoscape.js inlined. Don't fragment them.
- State persistence is file-based with `fcntl` locks and atomic temp+rename. No database. Keep it that way unless explicitly green-lit.
- All paths routed through `book_id` / `room_id` are **regex-validated** for traversal. Any new route you add does the same.

---

## 3. What "real, live data" means here

The word "live" is currently doing work it cannot support. Ground truth:

### What's actually live today

| Feed | Source | How | Latency | Reliability |
|---|---|---|---|---|
| ETF / futures / FX spot | Yahoo `/v7/finance/spark` | Python direct + browser via `allorigins.win` CORS proxy | 1-day bars, polled on demand | Brittle — allorigins is a free community proxy and has gone down repeatedly |
| OHLCV for derived indicators (RSI/ATR/SMA) | Yahoo `/v8/finance/chart` | Python direct (no proxy needed server-side) | Daily bars | Same Yahoo-is-unofficial risk |
| Polymarket probabilities | Gamma API `gamma-api.polymarket.com` | Direct, three-pass slug match | Real-time poll | Reasonable; official public API |
| TradingView alerts | Pine Script → webhook | HMAC-SHA256, nonce replay, rate-limited | Sub-second on bar close | Solid — this is the "real-time" channel |
| Manual indicators | Typed into book JSON | Human | Whenever Amo updates | Depends on Amo |

### What's missing (and what "mega-enhancement" unlocks)

Order of attack, highest-leverage first:

1. **Rates + macro.** No FRED (`api.stlouisfed.org/fred`). No Treasury curve, no 2s10s, no DXY with history, no CPI/PPI, no claims. The japan-rate-shock and china-property books can't resolve their own thesis without these.
2. **Futures curve + term structure.** Single-point Brent is not enough to trade the hormuz thesis. Need front/back spread, contango/backwardation, OVX. Candidates: CME direct (paid), ICE (paid), or bootstrap from Yahoo multi-contract symbols (`CL=F`, `CLM26.NYM`, etc.) as a stdlib fallback.
3. **Authoritative spot for equities/ETFs** to retire `allorigins.win`. Options: Polygon.io (paid, good free tier for delayed), Alpha Vantage (free-tier throttled), Tiingo, or a small self-hosted CORS relay on the droplet (cheapest, highest-control). **The relay is the right answer** — see §6.
4. **News + headlines.** The cascade phase tracker needs event evidence. Candidates: Benzinga, NewsAPI, Finnhub, or scraping curated RSS (Reuters world, Bloomberg markets). Use the agent-native principle: structured events into the graph, not prose into the chat.
5. **Econ calendar.** Deadlines (payrolls, FOMC, CPI prints) drive the countdown nodes in the graph. Candidates: Trading Economics API (free tier), Finnhub calendar, FRED release calendar.
6. **Options flow / positioning.** Nice-to-have for later. CBOE / Deribit for crypto. Probably out of scope for phase 1.
7. **Dialectic room bidirectional sync.** Right now `push_to_dialectic.py` is one-way. A real-time WebSocket subscription from the webapp into Dialectic rooms would let the LLM's replies surface in the tradingDesk chat without Amo copy-pasting.

**Architectural rule for every new connector:**

- Python-side fetcher lives in `tools/data_fetch/<source>.py`, stdlib only, writes typed results back into the cfg dict or returns a structured dict. Include a `__main__` CLI for standalone debugging.
- Webapp-side adapter lives in `web/adapters/<source>.py`, wraps the fetcher in `asyncio.to_thread()`, exposes a typed Pydantic model.
- Route in `web/routes/<source>.py` with JWT auth, path-validated inputs, and a WebSocket broadcast when state changes.
- Tests colocated: `tools/data_fetch/test_<source>.py` (offline, mocked network), `web/test_<source>.py` (route-level).
- Every connector declares its **freshness contract** in the snapshot output — `fetched_at`, `source`, `ttl_seconds`. The UI shows stale badges when the contract is violated.

---

## 4. What "UI mega-enhancement" means here

The current frontend is already well-scaffolded: React 19, Tailwind 4, Vite 8, five right-panel tabs, a builder, a welcome page, an onboarding tour. What it is **not yet**:

- A dense, keyboard-first cockpit you can run for 8 hours without taking your hands off the keyboard.
- A real-time tape. WebSockets exist but prices tick on poll, not push.
- A collaborative surface where Dan sees Amo's cursor and vice versa.
- A place where the LLM's state-of-the-world is visible *alongside* the human's, not behind a mention.

### Enhancement targets, in priority order

**P0 — Live tape + presence**

- Server-push for the MarketTicker: price ticks broadcast over the existing WS when connectors update. Target: under 500 ms from connector fetch to pixel change.
- Presence pills: "Dan is viewing `iran-hormuz`" / "Claude is thinking in room X." Cheap to implement on top of the existing WebSocket manager.
- Graph canvas live colors: node state changes flash briefly when the backend re-evaluates, not on page refresh.

**P0 — Command palette that actually runs the desk**

- Ctrl+K already exists. Expand it to a full command surface: `fire trade XOP_GATE`, `open thesis hormuz`, `diff last hour`, `ask @gpt why is brent flat`, `export chat`, `rotate secrets`. Every slash command and every REST endpoint gets a palette entry.
- Each palette command is **agent-callable** too — expose the same operation list as a JSON schema at `/api/commands` so the LLM can call them.

**P1 — Multi-book cockpit**

- 5 books now, not 2. The single-active-book UX doesn't scale. Options:
  - Tabbed book bar at top, Cmd+1..5 to switch.
  - Cross-book panel upgraded to a full matrix: rows = books, columns = cascade phase / top signals / open trades / P&L / last-diff-age.
  - Morning brief rendered as one scroll, not per-book.

**P1 — Density + typography**

- Default theme is already dense-terminal; push further. A single row in the ThesisViewer should show node + state + confluence + countdown + RSI/ATR + last-diff — not require a click to expand.
- Consistent iconography via `lucide-react` (already installed). Color palette encoded as Tailwind tokens, not ad hoc.

**P2 — Realtime collaboration**

- Shared cursor on the graph canvas. Selection broadcasts via WS.
- "@mention and thread" inside a node's journal, not just the room chat.
- Diff annotations: when the overnight run detects a state transition, both users see a stickied note on the affected node until acknowledged.

**P2 — Trade lifecycle surface**

- The outcomes engine (`tools/outcomes/`) already does REPAIR→TAG→CAPTURE. The UI surfaces it only as a morning-brief line. Build a full Trade Lifecycle panel: predicates per trade, which have fired, which are approaching, time-to-next-decision.
- Kill-switch button per trade, with two-step confirm and audit log entry.

**P3 — Agent-facing panel**

- Dedicated panel showing what the in-room LLM currently knows: its snapshot version, room membership, last message age, tool-call log. Makes the "third user" visible instead of implied.

### UI rules you will be held to

- **No new top-level pages without a plan doc in `docs/plans/`.** The builder and welcome pages took effort to land — don't dilute them.
- **Keyboard-first.** Every mouse action has a keystroke. Document them in-app under `?`.
- **No destructive action without a two-step.** Fire, kill, rotate, delete all double-confirm.
- **Stale data is surfaced, not hidden.** If the freshness contract is violated, the cell goes amber.
- **Accessibility is not negotiable.** Focus rings, ARIA on the graph canvas, keyboard-navigable tabs. Dan's eyes are on this screen for hours.

---

## 5. Ground rules for the agent team

### Operating

- **Work on the DO droplet, not localhost.** `167.99.113.232`. Bind `0.0.0.0`. Check `deploy/README.md` and `deploy/tradingdesk.service` for the systemd unit.
- **Integrate into the existing webapp.** Do not spin up parallel FastAPI services, do not fork the frontend, do not write standalone Python scripts that duplicate `web/adapters/`. One app.
- **Archive, don't delete.** Moving superseded code to `_archive/<category>/` with a README is the convention. See `_archive/legacy-commodity-book/` for the template.

### Coordination between agents

- Dispatch with **disjoint file ownership** and explicit "DO NOT TOUCH" lists per agent. Cross-cutting wire-up (route registration, design tokens, config) is a final commit by the coordinator — never mid-feature.
- Each agent runs its own build + tests before reporting done. "Verified" means `python3 -m pytest` green and `npm run build` green for anything they touched, plus a browser smoke on the affected panel.
- "Verified end-to-end" is **not** the same as "tests pass." If the feature depends on a race, a WebSocket event, or a scheduled job, say so explicitly — "code loaded, tests pass, WS broadcast path not reproduced with two clients."

### Code discipline

- WHY-comments on non-trivial code. `ARCHITECTURE`, `TRADEOFF`, `NOTE` only when they earn their place. Read `/root/.claude/CLAUDE.md` and `CLAUDE.md` for the repo's comment style before writing any.
- Type hints on all public Python functions. Pydantic models for all route I/O. No raw dict endpoints.
- No fabricated data. If a connector needs an API key you don't have, **raise an explicit error and document the env var** — never stub with fake responses.

### Testing

- Existing suite is 505 tests across five modules. Do not break it. Green suite is the merge gate.
- New connectors need: offline unit tests (mocked HTTP), a schema validation test, and a freshness-contract test.
- New UI components need: Vitest rendering test, interaction test for keyboard shortcut, a11y assertion with `@testing-library/jest-dom`.

### Security

- `JWT_SECRET`, `DEV_USER_PASSWORD`, `OPENROUTER_API_KEY`, `TV_WEBHOOK_SECRET`, `DIALECTIC_ROOM_TOKEN` — all env, never committed. Rotation runbook: `deploy/README.md`.
- New connectors with API keys follow the same pattern. Per-book tokens in `meta.*Token` override env, env is the fallback.
- Path-traversal regex on every route that takes an ID from the client. See existing routes for the pattern.

---

## 6. Suggested phase plan

This is a starting shape, not a mandate. Create actual plan docs in `docs/plans/` with timestamps and refine.

### Phase 1 — Retire allorigins, own the data path (1 week)

Stand up a small stdlib-only CORS relay in the webapp itself at `/api/relay/yahoo?...` with a strict allowlist of upstream hosts and paths. Frontend hits our relay, not allorigins. Python side already calls Yahoo direct — keep it. Add freshness contract metadata to every quote.

### Phase 2 — FRED + econ calendar (1-2 weeks)

`tools/data_fetch/fred.py` + `web/adapters/fred.py` + `web/routes/macro.py`. Feed the graph: nodes with `"source": "fred", "series": "T10Y2Y"` get resolved automatically. Adds real signal to japan-rate and china-property theses.

### Phase 3 — Live tape over WebSocket (1 week)

Connector fetches publish to an in-process pub/sub. WS broadcasts diff-only payloads. MarketTicker and ThesisViewer subscribe. Presence pills ride the same channel.

### Phase 4 — Command palette expansion + agent-facing operation list (1 week)

Every slash command, every fire/kill action, every panel switch becomes a palette entry and an item at `/api/commands`. Full keyboard coverage. Ship the `?` help overlay.

### Phase 5 — Multi-book cockpit (1-2 weeks)

Tabbed book bar, Cmd+digit switching, cross-book matrix panel, unified morning brief. Scales the UI to the 5-book (and growing) reality.

### Phase 6 — Trade lifecycle panel + agent-in-room panel (1-2 weeks)

Surface the outcomes engine. Surface the LLM's own state-of-the-world. Close the agent-native parity gap.

### Phase 7 — News + options flow (open-ended)

Lower priority; scope after Phase 6 lands and we see what analyst attention is actually starved for.

---

## 7. Day-one checklist for an incoming agent

1. SSH to the droplet, read `deploy/README.md`. Confirm the service is up: `systemctl status tradingdesk`.
2. `git log --oneline -30` — get a feel for the last three weeks of work.
3. Run the full test suite once: `python3 -m pytest tools/ web/ -q`. You should see 505 green.
4. Start the stack locally in a separate worktree (never on the droplet for dev): `make install && make dev`, `cd frontend && npm run dev`. Open the dashboard, log in as `amo`, flip through all five panels and all five books.
5. Read, in order: `CLAUDE.md`, `PROJECT.md`, `INTEGRATION.md`, `docs/USER-MANUAL.md`, `docs/runbooks/tradingview-pine-setup.md`, the most recent plan in `docs/plans/`.
6. Pick the smallest task in your track. Write a plan doc. Get it approved. Then ship it with a bisectable commit and a verification note that distinguishes code-passes-tests from behavior-reproduced-in-browser.

Welcome in. Build this like it's going to be on-screen for ten hours a day, because it will be.
