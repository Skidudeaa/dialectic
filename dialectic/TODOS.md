# Dialectic — TODO List

> Updated: 2026-02-14 (post QA sprint with 15 agents)

---

## Completed (Previous Sprint — Jan 2026)

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
- [x] Replace deprecated datetime.utcnow()
- [x] Add type hints to helper functions
- [x] Remove/gate console.log statements

## Completed (This Sprint — Feb 2026)

- [x] Fix fork ancestry CTE (child fork point through recursion)
- [x] Fix memory semantic search 500 (pgvector serialization)
- [x] Fix WebSocket double-accept
- [x] Fix JWT import-time crash (lazy loading)
- [x] Fix asyncpg jsonb codec (UUID + datetime encoder)
- [x] Fix hardcoded sys.path across 11 files
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

## Open — Security (blocks production deployment)

- [ ] **Wire auth to core endpoints** — Add `Depends(get_current_user)` to all REST endpoints in main.py. Validate JWT in WebSocket handshake instead of trusting client-provided user_id.
  - Files: `api/main.py` (all endpoints), WebSocket handler
  - Severity: CRITICAL

- [ ] **Fix cross-session routes auth** — Remove hardcoded `UUID("00000000-...")` placeholders. Uncomment auth dependency. Mount router in main.py.
  - Files: `api/cross_session_routes.py`, `api/main.py`
  - Severity: CRITICAL

- [ ] **Apply rate limiter to routes** — `RateLimiter` class exists but `Depends(check_rate_limit)` is never used. Apply to auth endpoints (5/min login, 3/min signup). Fix memory leak (evict keys when timestamp list is empty).
  - Files: `api/main.py`
  - Severity: HIGH

- [ ] **Stop logging verification codes** — `logger.info(f"Verification code for {email}: {code}")` in routes.py. Change to DEBUG or remove entirely. Implement email delivery.
  - Files: `api/auth/routes.py:133, 377`
  - Severity: HIGH

- [ ] **Fix account enumeration** — forgot-password returns 404 for nonexistent emails, leaking which emails are registered. Return success regardless.
  - Files: `api/auth/routes.py:354-359`
  - Severity: MEDIUM

- [ ] **Add refresh token rotation** — Currently returns the same refresh token on refresh. Issue new token and invalidate old.
  - Files: `api/auth/routes.py:198-258`
  - Severity: MEDIUM

## Open — Data Integrity

- [ ] **Wrap multi-step operations in transactions** — Room creation, message sending, forking, user creation all perform multiple DB operations without `async with db.transaction()`. Partial failures leave inconsistent state.
  - Files: `api/main.py`, `transport/handlers.py`, `memory/manager.py`
  - Severity: HIGH

- [ ] **Add message sequence retry on unique violation** — Atomic INSERT...SELECT fixes most races but two concurrent INSERTs can still collide under high concurrency. Add retry logic or use PostgreSQL sequence per thread.
  - Files: `transport/handlers.py`, `llm/orchestrator.py`
  - Severity: LOW

## Open — Architecture

- [ ] **Add Redis pub/sub for horizontal scaling** — In-memory WebSocket connection registry breaks with multiple uvicorn workers. Each worker's connections are invisible to others.
  - Files: `transport/websocket.py`
  - Severity: HIGH (blocks multi-worker production)

- [ ] **Refactor main.py** — 1400+ line god object. Split into routers: rooms, threads, messages, memories, events, presence.
  - Files: `api/main.py`
  - Severity: MEDIUM

- [ ] **Unify JWT auth users with room users** — Two separate identity systems. JWT users (from /auth/signup) and room users (from /users) are not linked. Notification endpoints check JWT identity but core endpoints use room tokens.
  - Files: `api/main.py`, `api/auth/`, `api/notifications/`
  - Severity: MEDIUM

- [ ] **Remove ~208 lines of dead code** — Duplicates and unused functions identified in previous audit.
  - Severity: LOW

## Open — Features (from VISION.md)

- [ ] **Dialectic Replay** — Re-watch conversations in real-time using event sourcing SSE endpoint
- [ ] **Conversation DNA** — Six-dimensional fingerprint rendered as generative glyphs
- [ ] **Counterfactual Forking** — "What if?" ghost threads with LLM-simulated alternate timelines
- [ ] **Intellectual Resonance Network** — Cross-user reasoning compatibility scoring
- [ ] **Living Argument Maps** — Real-time logical structure extraction into force-directed graphs

---

**Summary**: 43 items completed, 12 open (6 security, 2 data integrity, 4 architecture), 5 vision features planned.
