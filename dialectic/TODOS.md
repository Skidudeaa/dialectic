# Dialectic — TODO List

> Updated: 2026-07-24 (Phase 1 auth fix + reconciliation against actual code state)

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

- [x] **Wire JWT auth to ALL REST endpoints** — Fixed in two passes. 2026-07-24 (commit 355e497) covered the 9 endpoints in `api/main.py`. That pass claimed "ALL" but only searched `main.py`: 4 more endpoints in mounted routers kept the identical vector and were fixed 2026-07-25 — `stakes/routes.py` (create_commitment, record_confidence, resolve_commitment) and `analytics/graph_routes.py` (concept-map). All 13 now derive user_id from `Depends(get_current_user)`.
  - The graph one was the worst of the set: `_verify_token()` accepts *any* valid room token (not the requested room) and `_verify_user_membership()` only checked the subject belonged to *some* room, so any room token + any user UUID read that user's **cross-room** concept map. Now scoped to the caller.
  - Verified live: `/openapi.json` went 14 → 1 endpoints exposing `?user_id=`.

- [x] **Harden `GET /stakes/rooms/{room_id}/calibration`** — Fixed 2026-07-25. It verified only `_verify_room_token()`, never `_verify_room_member()`, so anyone holding the room token could read any member's calibration curve without belonging to the room. Now requires a JWT and checks caller membership; when a `user_id` filter is supplied, the subject must be a member too (a clear 403 instead of a silently-empty curve, and no probing for arbitrary user IDs).
  - `user_id` **stays** a query param here, unlike the write endpoints above — it's a filter, not an identity claim, and omitting it means the whole room, which is the only view `CommitmentDashboard` actually requests. So `/openapi.json` still shows 1 endpoint with `?user_id=`, and that is now correct rather than outstanding.
  - Tests: `tests/test_calibration_endpoint.py` (3 of 5 fail against the pre-fix endpoint).
  - Files: `stakes/routes.py`, `tests/test_calibration_endpoint.py`

- [ ] **Fix cross-session routes auth** — `cross_session_routes.py` (12 endpoints) still uses hardcoded `UUID("00000000-...")` placeholders and is never mounted in main.py. This is the same modeling gap as the schema/wiring items below were — the *internal* cross-session feature works, only its REST surface doesn't. Phase 2, in progress.
  - Files: `api/cross_session_routes.py`, `api/main.py`
  - Severity: **CRITICAL**

- [x] **Apply rate limiter to auth routes** — Already wired: `app.include_router(auth_router, ..., dependencies=[Depends(check_rate_limit)])`. Verified 2026-07-24, no action needed.

- [x] **Cross-session schema migration** — Already applied: `memory_references`, `user_memory_collections`, `collection_memories` are all in `schema.sql` (since commit a08fab4, 2026-04-17). Verified 2026-07-24.

- [x] **CrossSessionContextBuilder wiring** — Already wired into `on_message`, `force_response`, and `stream_response` in `llm/orchestrator.py`. Verified 2026-07-24. (Moved here from Critical Bugs section below — same root cause as the routes item above.)

- [x] **Explain multi-device session eviction** — Fixed 2026-07-25. `MAX_SESSIONS_PER_USER = 5` evicts a user's least-recently-used session on their next login; that's intentional, but it was *silent*. The evicted device found out only when `/auth/refresh` returned a flat 401 identical to an expired token, and the app dropped to a blank sign-in form — indistinguishable from "the app is broken." Sessions now record **why** they were revoked (`user_sessions.revoked_reason`: `logout` / `evicted_by_new_login` / `password_reset`, migration 004), `/auth/refresh` returns the matching explanation in `detail` plus an `X-Session-Revoked-Reason` header, and the auth screen shows it as a notice rather than an error. An unrecognised or NULL reason (sessions revoked before the column existed) falls back to the old generic message rather than inventing one.
  - Verified end-to-end against the live service: 6 logins, then refreshing with the evicted session returned 401 + "You were signed out because you signed in on another device. Only 5 devices can be signed in at once." + the header, while a surviving session still refreshed 200.
  - Files: `api/auth/routes.py`, `migrations/004_session_revoked_reason.sql`, `schema.sql`, `stores/appStore.ts`, `App.tsx`, `components/auth/AuthScreen.tsx`, `tests/test_session_eviction.py`

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

- [x] **Cross-session schema migration** — See Security section above; already applied.
- [x] **Streaming bypass of retry/fallback** — Already fixed: `stream_response()` goes through `router.stream()` with the fallback chain. Verified 2026-07-24.
- [x] **Context truncation on all LLM paths** — Already applied: `truncated_messages` used in `stream_response`. Verified 2026-07-24.
- [x] **Wire CrossSessionContextBuilder** — See Security section above; already wired.
- [x] **httpx client leak in streaming** — Already fixed: module-level `_provider_cache` singleton in `providers.py`. Verified 2026-07-24.
- [x] **datetime.utcnow() usage** — Already gone. Zero remaining usages, verified 2026-07-24.

- [ ] **Fix ModelRouter cache invalidation** — Router cached per room_id, never invalidated. Room settings changes (model, provider) ignored until server restart. Bundle with `update_room_settings` (Phase 1 touched this endpoint for auth; invalidate the cache in the same handler rather than as a separate change).
  - Files: `llm/orchestrator.py:47-58`, `api/main.py` (`update_room_settings`)
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

- [x] **Fix multi-tab connection registry desync** — Fixed 2026-07-25. `ConnectionManager` kept a `(user_id, room_id) -> Connection` index holding one connection per user per room, while `_rooms` held them all. A second tab overwrote the first tab's entry, and closing *either* tab deleted the shared key — the surviving tab stayed in `_rooms` (kept receiving broadcasts) but every directed send to it returned False, so LLM streams and receipts silently vanished. `_rooms` is now the single source of truth; `send_to_user` fans out to all of a user's tabs; `user_joined`/`user_left` fire only on a user's first/last connection; dead sockets are evicted on send failure instead of retried forever; removal is by identity, not dataclass equality. Regression tests in `tests/test_connection_registry.py` (8 of 9 fail against the old code).
  - Files: `transport/websocket.py`, `tests/test_connection_registry.py`

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

## Open — Tooling
pass
- [ ] **Fix AutoTest watcher false positive on bare conftest.py** — Watcher runs pytest against `tests/conftest.py` in isolation, which has no test functions, gets "no tests ran," and misreports it as a failure. Confirmed on both `dialectic` and `cc-sidecar` repos, 2026-07-24. Full suites pass clean (dialectic 237/237, cc-sidecar 102/102) when run normally; this is watcher noise, not a real regression.
  - Severity: LOW (false alarm, but erodes trust in the signal)
pass
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

**Summary**: 62 items completed, 15 open (2 security, 1 critical bug, 2 data integrity, 5 performance, 6 architecture, 1 dependencies, 1 tooling), 11 vision features planned. (2026-07-24 pass: closed JWT auth wiring, reconciled 7 stale items that were already fixed in code but not checked off.)
