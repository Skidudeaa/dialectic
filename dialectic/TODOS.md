# Dialectic — TODO List

> Updated: 2026-02-20 (post deep audit — 4 agents, full codebase analysis)

---

## Completed (Jan 2026 Sprint)

- [x] Fix wildcard CORS configuration
- [x] Fix message sequence race condition (atomic INSERT...SELECT)
- [x] Move tokens from URL to WebSocket auth message
- [x] Add rate limiter class
- [x] Replace recursive ancestry query with CTE
- [x] Throttle streaming DOM updates (RAF-batched)
- [x] Add missing database indexes (8 indexes)
- [x] WebSocket connection state machine
- [x] Exponential backoff for reconnection
- [x] Fix infinite scroll race condition
- [x] Fix streaming state race conditions
- [x] Add distinctive typography (Space Grotesk)
- [x] Enhance streaming visual feedback (shimmer + cursor)
- [x] Add type hints to helper functions
- [x] Remove/gate console.log statements

## Completed (Feb 2026 Sprint)

- [x] Fix fork ancestry CTE (child fork point through recursion)
- [x] Fix memory semantic search 500 (pgvector serialization)
- [x] Fix WebSocket double-accept
- [x] Fix JWT import-time crash (lazy loading)
- [x] Fix asyncpg jsonb codec (UUID + datetime encoder)
- [x] Fix hardcoded sys.path across 11 files (pathlib resolution)
- [x] Fix room_members → room_memberships table name
- [x] Fix conn.send() in cross-session handlers
- [x] Fix empty message validation on REST endpoint
- [x] Fix provoker stream styling (frontend + backend payload)
- [x] Fix duplicate event listeners (guard flag)
- [x] Fix accumulated visibilitychange listeners
- [x] Fix XSS in thread title dropdown
- [x] Fix prepended messages order (reverse iteration)
- [x] Add health check with DB verification
- [x] Add environment validation on startup
- [x] Add production mode to run.py
- [x] Add Makefile (setup/run/frontend/db-setup/db-reset)
- [x] Add .env.example
- [x] Add missing Python deps (anthropic, tiktoken, openai)
- [x] Install pgvector + create memories tables
- [x] Build next-gen web frontend (app.html)
- [x] Write vision document (docs/VISION.md)
- [x] Add favicon
- [x] Add accessibility labels
- [x] Improve error messages (network vs API)

---

## Open — Security (CRITICAL — blocks production)

- [ ] **Wire JWT auth to ALL REST endpoints** — Core endpoints accept bare `user_id` query param with no JWT validation. Anyone with a room token can impersonate any user. Add `Depends(get_current_user)` and validate caller matches `user_id`.
  - Files: `api/main.py` (all endpoints accepting `user_id: UUID = Query(...)`)
  - Severity: **CRITICAL**

- [ ] **Fix cross-session routes auth** — Remove hardcoded `UUID("00000000-...")` placeholders. Uncomment auth dependency. Mount router in main.py.
  - Files: `api/cross_session_routes.py`, `api/main.py`
  - Severity: **CRITICAL**

- [ ] **Apply rate limiter to auth routes** — `RateLimiter` class exists but `Depends(check_rate_limit)` is never applied. Wire to auth endpoints (5/min login, 3/min signup). Fix memory leak (evict empty key lists).
  - Files: `api/main.py`, `api/auth/routes.py`
  - Severity: **HIGH**

- [ ] **Stop logging verification codes** — `logger.info(f"Verification code for {email}: {code}")` exposes one-time auth codes. Change to DEBUG or remove.
  - Files: `api/auth/routes.py:133, 377`
  - Severity: **HIGH**

- [ ] **Update python-multipart** — v0.0.6 has CVE-2024-53498 (multipart parsing DoS). Update to 0.0.12+.
  - Files: `requirements.txt`
  - Severity: **HIGH**

- [ ] **Move room tokens from URL to header** — Tokens in query params logged by proxies, browser history, Referer headers. Use Authorization header.
  - Files: Multiple REST endpoints in `api/main.py`
  - Severity: **HIGH**

- [ ] **Fix email enumeration** — forgot-password returns 404 for nonexistent emails. Return success regardless.
  - Files: `api/auth/routes.py:354-359`
  - Severity: MEDIUM

- [ ] **Add refresh token rotation** — Currently returns same refresh token on refresh. Issue new + invalidate old.
  - Files: `api/auth/routes.py:198-258`
  - Severity: MEDIUM

- [ ] **Stop sending raw exceptions to WS clients** — `str(e)` leaks table names, query structure.
  - Files: `transport/handlers.py:77-78`
  - Severity: MEDIUM

## Open — Critical Bugs

- [ ] **Apply cross-session schema migration** — `memory_references`, `user_memory_collections`, `collection_memories` tables exist in migration file but NOT in schema.sql. Cross-session code references these tables. Blocks 4+ vision features.
  - Files: `schema.sql`, `migrations/cross_session_memories.sql`
  - Severity: **CRITICAL** (blocks features)

- [ ] **Fix streaming bypass of retry/fallback** — `stream_response()` calls provider directly, bypassing `ModelRouter`. Streaming failures are unrecoverable (no retry, no fallback).
  - Files: `llm/orchestrator.py:251`
  - Severity: **HIGH**

- [ ] **Apply context truncation to all LLM paths** — `assemble_context()` only called from `stream_response()`. `on_message()` and `force_response()` risk token overflow on long conversations.
  - Files: `llm/orchestrator.py`
  - Severity: **HIGH**

- [ ] **Wire CrossSessionContextBuilder** — Fully implemented but never invoked from orchestrator. Cross-session injection is a dead feature.
  - Files: `llm/orchestrator.py`, `llm/cross_session_context.py`
  - Severity: **HIGH** (blocks vision features)

- [ ] **Fix httpx client leak in streaming** — `get_provider()` creates new `httpx.AsyncClient` per call. Streaming bypasses router cache, leaking clients.
  - Files: `llm/orchestrator.py:251`, `llm/providers.py:204-205`
  - Severity: **HIGH**

- [ ] **Fix datetime.utcnow() usage** — Deprecated since Python 3.12, returns naive datetime. Breaks with TIMESTAMPTZ columns. Present in: `orchestrator.py`, `manager.py`, `operations.py`, `websocket.py`, `handlers.py`.
  - Severity: MEDIUM

- [ ] **Fix ModelRouter cache invalidation** — Router cached per room_id, never invalidated. Room settings changes (model, provider) ignored until server restart.
  - Files: `llm/orchestrator.py:47-58`
  - Severity: MEDIUM

## Open — Data Integrity

- [ ] **Wrap multi-step operations in transactions** — Room creation, message sending, forking all perform multiple DB operations without `async with db.transaction()`.
  - Files: `api/main.py`, `transport/handlers.py`, `memory/manager.py`
  - Severity: HIGH

- [ ] **Add message sequence retry on unique violation** — Concurrent INSERTs can still collide under high concurrency.
  - Files: `transport/handlers.py`, `llm/orchestrator.py`
  - Severity: LOW

## Open — Performance

- [ ] **Fix N+1 badge count queries** — Loop over recipients fires sequential queries per user in push notification path.
  - Files: `transport/handlers.py:815-817`
  - Severity: MEDIUM

- [ ] **Fix recursive get_thread_messages in WS path** — Python-level recursion with N round-trips for depth-N forks. REST endpoint correctly uses CTE but WebSocket hot path does not.
  - Files: `operations.py:92-113`
  - Severity: MEDIUM

- [ ] **Fix synchronous push in async context** — Expo `PushClient` uses `requests.Session()` (sync), blocks event loop.
  - Files: `api/notifications/service.py:43-49`
  - Severity: MEDIUM

- [ ] **Fix brute-force memory injection** — All active room memories injected into LLM prompt regardless of relevance. `get_context_for_prompt(query=...)` exists but isn't wired.
  - Files: `memory/manager.py`, `transport/handlers.py`
  - Severity: MEDIUM

- [ ] **Fix user modifier averaging** — `_blend_user_modifiers()` averages all users' preferences. Individual differences lost.
  - Files: `llm/prompts.py`
  - Severity: LOW

## Open — Architecture

- [ ] **Proper Python packaging** — Replace 9-file sys.path + pathlib hack with `pyproject.toml` + `pip install -e .`.
  - Severity: MEDIUM

- [ ] **Add Redis pub/sub** — In-memory WebSocket registry breaks with multiple workers.
  - Files: `transport/websocket.py`
  - Severity: HIGH (blocks multi-worker production)

- [ ] **Refactor main.py** — 1400+ line god object. Split into routers.
  - Severity: MEDIUM

- [ ] **Unify JWT auth users with room users** — Two separate identity systems not linked.
  - Severity: MEDIUM

- [ ] **Remove ~208 lines of dead code** — Duplicates and unused functions.
  - Severity: LOW

- [ ] **Retire index.html** — Older frontend with incompatible design system. `app.html` is active.
  - Severity: LOW

## Open — Dependencies

- [ ] **Pin dependency ranges** — `anthropic>=0.25.0` (no upper bound, breaking changes between minors), `openai>=1.12.0` (same risk).
  - Files: `requirements.txt`
  - Severity: MEDIUM

- [ ] **Update stale deps** — fastapi 0.109→0.115+, httpx 0.26→0.28, websockets 12→14, pydantic 2.5→2.10
  - Files: `requirements.txt`
  - Severity: LOW-MEDIUM

## Open — Vision Features

See `.planning/NEXT-LEVEL-ROADMAP.md` for full prioritized plan and `.planning/VISION-NEXT.md` for strategic directions.

- [ ] Conversation Analytics (ConversationAnalyzer over event stream)
- [ ] LLM Self-Memory (post-response extraction + MemoryScope.LLM)
- [ ] Knowledge Graph Layer (materialized view + traversal API)
- [ ] Thinking Protocols (protocol state machine + prompt injection)
- [ ] Real-Time Typing Analysis (TYPING_CONTENT + debounced novelty)
- [ ] Persistent LLM Identity (EVOLVED_IDENTITY + identity distillation)
- [ ] Async Dialogue / Slow Channel (ANNOTATOR mode + presence-aware routing)
- [ ] Event Replay Engine (state_at + temporal reconstruction)
- [ ] Stakes / Commitments (Commitment entity + prediction dashboard)
- [ ] Multi-Model Rooms (N personas + turn-taking coordinator)
- [ ] Dialectic Graph UI (interactive knowledge visualization)

---

**Summary**: 54 items completed, 30 open (9 security, 7 critical bugs, 2 data integrity, 5 performance, 6 architecture, 1 dependencies), 11 vision features planned.
