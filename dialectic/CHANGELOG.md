# Changelog

## [Unreleased] — 2026-02-14

### Evolution Sprint (15 Opus 4.6 agents, 3 teams)

#### Added
- **Next-gen web frontend** (`frontend/app.html`) — 2,845-line SPA with:
  - Three-party visual distinction (teal/rose/indigo/amber)
  - Conversation energy indicator (ambient glow tracking messages/minute)
  - Claude interjection animation (slide-in entrance effect)
  - Mini-cladogram SVG in thread header
  - 14 CSS animations, Inter font, deep dark design system (40+ CSS tokens)
  - Keyboard shortcuts (`?` help, `Cmd+K` focus, `Cmd+Enter` send)
  - Full feature parity with index.html plus extras
- **Vision document** (`docs/VISION.md`) — 5 "two steps beyond" feature designs:
  - Dialectic Replay (re-watch conversations via event sourcing)
  - Conversation DNA (six-dimensional fingerprint as generative glyphs)
  - Counterfactual Forking (LLM-simulated alternate timelines)
  - Intellectual Resonance Network (cross-user reasoning compatibility)
  - Living Argument Maps (real-time logical structure extraction)
- **Makefile** — `make setup`, `make run`, `make frontend`, `make db-setup`, `make db-reset`
- **`.env.example`** — Documents all required/optional environment variables
- **pgvector extension** installed with memories + memory_versions tables (14 → 19 DB tables)
- **Cross-session memory** infrastructure (routes, handlers, context, migrations)

#### Fixed
- **Fork ancestry CTE bug** — Forked threads showed ALL parent messages instead of only up to fork point. CTE now carries child_fork_point_message_id through recursion (`api/main.py`)
- **Message sequence race condition** — Replaced SELECT MAX + INSERT with atomic INSERT...SELECT...RETURNING in both `transport/handlers.py` and `llm/orchestrator.py`
- **WebSocket double-accept** — Removed duplicate `websocket.accept()` from `ConnectionManager.connect()` (`transport/websocket.py`)
- **Memory semantic search 500** — pgvector `vector` type serialization via string format with `::vector` cast (`memory/vector_store.py`)
- **JWT import-time crash** — Changed from eager env var read to lazy `_get_secret_key()` with caching (`api/auth/utils.py`)
- **asyncpg jsonb codec** — Registered custom codec for jsonb/json columns with UUID+datetime-aware encoder (`api/main.py`)
- **UUID JSON serialization** — Custom encoder handles UUID and datetime in event payloads (`api/main.py`)
- **Hardcoded sys.path** — Replaced `/root/DwoodAmo/dialectic` with relative `pathlib` resolution across 11 files
- **`room_members` → `room_memberships`** — Fixed table name mismatch in `memory/cross_session.py` and `migrations/cross_session_memories.sql`
- **`conn.send()` → `conn.websocket.send_text()`** — Fixed method calls in `transport/cross_session_handlers.py`
- **Empty messages via REST** — Added validation to reject empty/whitespace content (`api/main.py`)
- **Provoker stream styling** — Frontend uses `msg-provoker` class for provoker streams; backend sends `speaker_type` in streaming payloads (`app.html` + `handlers.py`)
- **Duplicate event listeners** — Guard flag prevents `initAppHandlers()` re-registration (`app.html`)
- **Accumulated visibilitychange listeners** — Properly removes old listener before adding new one (`app.html`)
- **XSS in thread title dropdown** — Thread titles escaped with `escapeHtml()` in `<select>` innerHTML (`app.html`)
- **Prepended messages order** — Reverse iteration in `prependMessages()` for correct chronological order (`app.html`)
- **PostgreSQL auth for asyncpg** — pg_hba.conf updated for IPv6 localhost trust auth

#### Improved
- **Health check** — `/health` now verifies DB connectivity, returns 503 when degraded
- **Environment validation** — Startup fails fast if DATABASE_URL or ANTHROPIC_API_KEY missing
- **Production mode** — `PRODUCTION=1` disables reload, sets workers, adjusts log level (`run.py`)
- **Error messages** — Frontend distinguishes network errors vs API errors
- **Favicon** — Inline SVG diamond favicon
- **Accessibility** — `aria-label` on Quick Join inputs
- **CORS** — Configurable via ALLOWED_ORIGINS env var with droplet IP included
- **Requirements** — Added missing anthropic, tiktoken, openai dependencies

#### Known Issues (Open)
- Auth module exists but not wired to core REST/WebSocket endpoints
- Cross-session routes have hardcoded user_id placeholders (dead code)
- Rate limiter defined but not applied to any route
- No database transactions on multi-step operations
- Verification codes logged at INFO level
- Account enumeration via forgot-password endpoint
- No refresh token rotation
- In-memory WebSocket registry = single-server only (Redis pub/sub planned)

---

## [0.1.0] — 2026-01-30

### Initial Backend
- FastAPI server with WebSocket real-time messaging
- LLM orchestration (Anthropic primary, OpenAI fallback)
- Heuristic interjection engine (turn count, questions, semantic novelty, stagnation)
- Dual LLM personas (primary participant + provoker destabilizer)
- Thread forking with recursive CTE genealogy
- Vector memory with pgvector (1536-dim embeddings)
- Event sourcing (append-only events table)
- User authentication (JWT, Argon2, refresh tokens)
- Push notifications (Expo)
- Full-text search with tsvector
- Basic web frontend (`frontend/index.html`)
