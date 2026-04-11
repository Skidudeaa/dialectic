# CHANGELOG

## 2026-04-11 — TradingView Integration (v0.3.0)

Full TradingView integration shipped across three phases. Pine Script alerts now
flow into the webapp as HMAC-signed webhook POSTs, mutate book state through a
four-op contract, broadcast to linked chat rooms in real time, and surface in a
dedicated dashboard panel.

### Phase 1 — Engine enrichment (commit a3bfc21)
- New `tools/data-fetch/derived_indicators.py` (stdlib Wilder RSI/ATR/SMA,
  schema-enforced `overlay: true` tripwire, 58 tests)
- `tools/thesis-graph/thesisgraph.py`: `fetch_ohlcv_for_derived()` (Yahoo v8
  chart per-symbol), `compute_derived_indicators()`, closesObserved auto-bump
  feeding the existing closesRequired gate in `eval_node_state`, v:2 snapshot
  gains top-level `tvIndicators` overlay key
- `tools/bridge/diff-snapshots.py`: `tvIndicatorShifts` category with material
  thresholds (RSI ≥8 pts, ATR ≥15%, SMA ≥8%)
- Both books seeded with `derivedIndicators` specs on brent, dxy-stress,
  food-spike, demand-destruction (iran-hormuz) and input-costs, usd-cny,
  auto-sector (trump-tariffs)

### Phase 2 — Webapp integration (commit 40a3d16)
- `web/tv_webhook.py` — pure HMAC/timestamp/nonce verification, thread-safe
  NonceStore with TTL
- `web/adapters/tradingview.py` — binding resolution, four-op enforcement,
  atomic book mutation, per-book asyncio locks, thesis cache invalidation
- `web/routes/tradingview.py` — `POST /api/tradingview/webhook` (HMAC-gated,
  no JWT), `GET /status /events /indicators`, `GET/POST/DELETE
  /api/thesis/{book_id}/tv-bindings` (JWT-gated), per-IP token-bucket rate
  limiter (60/min default, 429 on excess), 8 KiB body cap
- `web/ws.py` gains `broadcast_to_book_rooms()` — fans out to rooms with
  matching `linked_book_id`
- `web/state.py` gains `tradingview-events.jsonl` audit log namespace
- `frontend/src/components/TradingViewPanel.tsx` — webhook status card,
  binding CRUD, recent alert feed
- `frontend/src/components/TVIndicatorBadge.tsx` — inline RSI/ATR badges on
  ThesisViewer node rows
- 100 new tests in `web/test_tradingview.py` across auth / apply / CRUD /
  management / rate limiting
- `vite.config.ts`: `defineConfig` imported from `vitest/config` (pre-existing
  TS error blocking `npm run build`, fixed in passing)

### Phase 3 — Seed bindings + operator runbook (this commit)
- Four canonical bindings seeded across both books:
  - `brent-persistence-close-above-115` (iran-hormuz, incrementClosesObserved)
  - `hormuz-reopen-announced` (iran-hormuz, setNodeState → resolved)
  - `fert-close-above-700` (iran-hormuz, setCurrent)
  - `spy-below-200dma-first-touch` (trump-tariffs, setProbability)
- `docs/runbooks/tradingview-pine-setup.md` — full operator guide covering
  Pine Script's webhook limitations, relay architecture with a 40-line example,
  per-binding Pine snippets, secret rotation procedure, troubleshooting matrix
- `tools/bridge/sign-tv-alert.py` — stdlib CLI that reads `TV_WEBHOOK_SECRET`
  and produces curl-ready signed headers. Supports `--format curl|headers|json`
  and piping a body via stdin.

### Test counts
- Phase 1: 333 → 405 (+72)
- Phase 2: 405 → 505 (+100)
- Phase 3: 505 (data + docs only, no new tests)

### Live verification (2026-04-11)
- End-to-end round trip: `sign-tv-alert.py` → HTTP POST → HMAC verify →
  adapter apply_op → atomic book write → cache invalidate → audit log →
  broadcast. Response: `200 {"status":"ok","bookId":"iran-hormuz-graph","nodeId":"brent","op":"incrementClosesObserved","newValue":1}`
- Binding `fireCount` stamped, `lastFiredAt` ISO timestamp recorded
- `web/data/tradingview-events.jsonl` appended with the success event

### Environment
- New required env var: `TV_WEBHOOK_SECRET` (generate with
  `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`)
- Optional: `TV_WEBHOOK_RATE_LIMIT_PER_MIN` (default 60),
  `TV_WEBHOOK_NONCE_TTL_SECONDS` (default 600)

---

## 2026-04-10 — Post-v0.2.0 Hardening

### Fixes
- `marketField` sync only updates matching node→key pairs (prevented cross-contamination of unrelated nodes when price inputs changed)
- Live price flow: restored missing wiring between fetch-prices and thesis state refresh
- LLM model IDs: corrected OpenRouter model identifiers for @claude, @gpt, @gemini routing
- Streaming persistence: streamed LLM responses now persist correctly to the message log
- Static serving: SPA bundle served correctly from FastAPI

### Features
- Streaming UX for LLM responses (token-by-token display)
- Agent API endpoints exposed (room update/delete, journal update, predictions single-get)
- Frontend test suite added (api.test.ts)

### Security / Reliability
- Security hardening pass on web layer
- Reliability + performance improvements
- Test coverage expanded (web/test_web.py now 50 tests, full suite 333)

### Consolidation
- Archived empty placeholder dirs `tools/polymarket/` and `tools/signals/` to `_archive/empty-placeholders/`
- Archived orphan snapshots `test.json` and `trump-tariffs-latest.json` to `_archive/orphan-snapshots/`
- Archived `tools/commodity-book/bookgen.py` (legacy flat-trigger generator, 974 lines, superseded by thesis-graph) to `_archive/legacy-commodity-book/` with breadcrumb README. Preserved as project origin — see `research/bookgen-lessons.md` for the migration rationale
- Archived legacy `books/iran-hormuz-2026.json`, `output/iran-hormuz.html`, `active-commodity-book.html`, and 9 positional screenshots with the bookgen archive
- Updated CLAUDE.md to document `tools/outcomes/` (previously missing), correct test count (223 → 333), and replace the Commodity Book section with a Project Origin breadcrumb
- Added `docs/plans/2026-04-10-001-feat-tradingview-webapp-integration-plan.md` — re-architected Alpha v2 TradingView plan as a webapp-integrated feature (single FastAPI process, WebSocket alert broadcast, frontend UI for binding management)

---

## 2026-04-07 — Web Layer (v0.2.0)

### Phase 6: Bug Fixes
- Fixed Vite proxy pointing to wrong port (8000 → 8005)
- Fixed `/api/market/watchlist` crash — instruments is dict[nodeId, list], not flat list
- Fixed LLM error messages not appearing in chat (broadcast via WebSocket)

### Phase 7: Design Hardening
- Dense terminal aesthetic: 13px base, 1.4 line-height, all spacing tightened
- Model-colored chat badges: Claude=amber, GPT=green, Llama=purple, Gemini=blue
- Uppercase 10px monospace badges with tracking-wide for node states
- Confluence bars color-coded by severity threshold
- Table-style journal layout with columns
- 32px header, compact sidebar labels

### Phase 8: Real-Time
- Presence indicators: green dots showing online users per room
- Typing indicators: "X is typing..." with pulse animation
- Prediction broadcasts: create/resolve events sent to all rooms
- ThesisViewer auto-refreshes every 5 minutes
- User activity status tracking

### Phase 9: Power Features
- Chat commands: /brief, /thesis, /diff, /predict, /watchlist
- Message pinning with collapsible section and pin count badge
- Chat export to markdown file download
- PIN/EXPORT REST endpoints

### Phase 10: Polish
- Command palette (Ctrl+K): search rooms, panels, actions
- Keyboard shortcuts: Escape closes panels/palette
- Empty states: "Create your first room" CTA with keyboard hint
- iPad responsive: sidebar auto-closes on room select at narrow widths
- State persistence verified across backend restart

---

## 2026-04-07 — Web Layer (v0.1.0)

### Phase 1+2: Backend Foundation + API Routes
- FastAPI app with CORS, lifespan handler
- JWT auth with two hardcoded dev users (amo, dan)
- Pydantic models for all request/response types
- File-based state manager (JSON/JSONL with fcntl locking)
- WebSocket connection manager with room-scoped broadcast
- Adapters wrapping existing tools/: thesis, market, outcomes
- REST routes: thesis (books, state, scenarios, horizon, fetch-prices), market (quotes, polymarket, watchlist), outcomes (brief, trades, evaluate, cross-book, ledger), rooms (CRUD), messages (CRUD + WebSocket), LLM (chat + compare via OpenRouter), journal (CRUD), predictions (CRUD + resolve)
- Health endpoint: uptime, WS connections, books loaded, snapshot timestamps

### Phase 3: React Frontend
- Vite + React + TypeScript + Tailwind CSS v4
- Dark theme: void/surface/elevated, amber/teal accents, JetBrains Mono + Inter
- Login page with JWT auth
- Three-panel dashboard: sidebar (rooms + watchlist), center (chat), right (context panels)
- Real-time WebSocket chat with @claude/@gpt/@llama/@gemini/@compare LLM routing
- Thesis state viewer: phase indicator, node states, confluence bars, countdowns, scenarios
- Market ticker with 60s auto-refresh
- Morning brief display with refresh
- Cross-book scan panel with severity badges (HIGH/MEDIUM/LOW)
- Prediction tracker with accuracy stats and resolve buttons
- Trade journal with create form

### Phase 4: Integration & Polish
- Toast notification system (success/error/info, auto-dismiss)
- Snapshot diff on price fetch: prev/latest rotation, delta broadcast as system messages
- Thesis context injection in LLM prompts for linked rooms
- iPad responsive: auto-collapse sidebar + right panel at <1024px, overlay mode

### Phase 5: Deployment & Docs
- Docker: backend (uvicorn) + frontend (nginx) via docker-compose
- Makefile: dev, build, test, docker-up, docker-down, install
- .env.example with all env vars documented
- DECISIONS.md documenting all design choices
- All 223 CLI tests pass throughout (outcomes suite + web suite added subsequently; see 2026-04-10 entry)
