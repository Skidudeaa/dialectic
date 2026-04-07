# CHANGELOG

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
- All 223 existing tests pass throughout
