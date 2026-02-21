# Codebase Concerns

**Analysis Date:** 2026-01-20

## Tech Debt

**Hardcoded sys.path manipulation:**
- Issue: Multiple files use `sys.path.insert(0, '/root/DwoodAmo/dialectic')` for imports
- Files: `dialectic/api/main.py:12`, `dialectic/transport/handlers.py:8`, `dialectic/llm/orchestrator.py:9`, `dialectic/llm/heuristics.py:7`, `dialectic/llm/prompts.py:6`, `dialectic/memory/manager.py:9`
- Impact: Breaks portability; code fails if cloned to different path
- Fix approach: Convert to proper Python package with `__init__.py` and relative imports, or use `PYTHONPATH`

**In-memory WebSocket connection registry:**
- Issue: `ConnectionManager` stores connections in memory dictionaries
- Files: `dialectic/transport/websocket.py:33-41`
- Impact: Cannot scale horizontally; all users must connect to same server instance
- Fix approach: Replace with Redis pub/sub for connection state and message broadcast

**Duplicate code between REST and WebSocket handlers:**
- Issue: Message creation logic duplicated between `api/main.py:377-429` and `transport/handlers.py:67-163`
- Files: `dialectic/api/main.py`, `dialectic/transport/handlers.py`
- Impact: Bug fixes must be applied in two places; risk of drift
- Fix approach: Extract shared message creation service used by both handlers

**Lazy provider initialization in orchestrator:**
- Issue: `ModelRouter` instances cached per room in `_routers` dict, never cleaned up
- Files: `dialectic/llm/orchestrator.py:47-58`
- Impact: Memory leak for long-running servers with many rooms
- Fix approach: Add TTL-based eviction or use LRU cache with max size

**Overly permissive CORS configuration:**
- Issue: CORS middleware allows all origins, methods, and headers
- Files: `dialectic/api/main.py:83-89`
- Impact: Security vulnerability in production
- Fix approach: Configure specific allowed origins from environment variable

## Known Bugs

**Race condition in message sequence numbering:**
- Symptoms: Potential duplicate sequence numbers under concurrent writes
- Files: `dialectic/api/main.py:394-398`, `dialectic/transport/handlers.py:91-95`, `dialectic/llm/orchestrator.py:207-211`
- Trigger: Two users send messages to same thread simultaneously
- Workaround: Database UNIQUE constraint on (thread_id, sequence) prevents corruption but causes failed inserts

**Silent embedding failures:**
- Symptoms: Memories saved without embeddings; semantic search returns incomplete results
- Files: `dialectic/memory/manager.py:314-320`
- Trigger: OpenAI embedding API failure or timeout
- Workaround: None; embeddings silently fail and log error only

**WebSocket disconnect not awaited properly in exception handler:**
- Symptoms: Potential unfinished async operations on client disconnect
- Files: `dialectic/api/main.py:660-662`
- Trigger: WebSocket error during message processing
- Workaround: Connection cleanup still runs but may miss broadcasts

## Security Considerations

**Room tokens stored in plain text:**
- Risk: Database compromise exposes all room access tokens
- Files: `dialectic/schema.sql:26`, `dialectic/api/main.py:203-204`
- Current mitigation: None
- Recommendations: Hash tokens; store only hash, compare against hashed input

**No rate limiting:**
- Risk: DoS attacks via message flooding or room creation spam
- Files: `dialectic/api/main.py` (all endpoints)
- Current mitigation: None
- Recommendations: Add rate limiting middleware (slowapi or similar)

**API keys in environment variables:**
- Risk: Keys logged or exposed in process listings
- Files: `dialectic/llm/providers.py:66-68`, `dialectic/llm/providers.py:135-137`, `dialectic/memory/embeddings.py:45-47`
- Current mitigation: Environment variables (standard practice)
- Recommendations: Consider secrets manager for production; ensure no logging of env vars

**No input validation on message content:**
- Risk: XSS if content rendered in frontend; prompt injection via user content
- Files: `dialectic/transport/handlers.py:70`
- Current mitigation: Content stripped of leading/trailing whitespace only
- Recommendations: Add content length limits; sanitize for frontend rendering

**User ID passed via query parameter:**
- Risk: User impersonation by changing user_id in WebSocket connection
- Files: `dialectic/api/main.py:613`
- Current mitigation: Room membership check (line 627-632)
- Recommendations: Use session tokens instead of user IDs

## Performance Bottlenecks

**Recursive thread ancestry queries:**
- Problem: `get_thread_messages` recursively fetches entire ancestor chain
- Files: `dialectic/operations.py:75-115`
- Cause: Recursive async function with N queries for N-level deep threads
- Improvement path: Use recursive CTE in single SQL query

**LLM always triggered after every message:**
- Problem: `_trigger_llm` called after every human message regardless of decision
- Files: `dialectic/transport/handlers.py:172`
- Cause: LLM thinking indicator broadcast even when LLM decides not to respond
- Improvement path: Move broadcast inside orchestrator after positive decision

**Full room data loaded for every LLM invocation:**
- Problem: Room, thread, all users, all messages, all memories fetched per message
- Files: `dialectic/transport/handlers.py:188-205`
- Cause: No caching; fresh queries every time
- Improvement path: Cache room/user data; lazy-load messages with pagination

**No connection pooling configuration:**
- Problem: Fixed pool size (2-10) regardless of load
- Files: `dialectic/api/main.py:56`
- Cause: Hardcoded pool parameters
- Improvement path: Make pool size configurable via environment variables

## Fragile Areas

**LLM provider initialization:**
- Files: `dialectic/llm/providers.py:56-70`, `dialectic/llm/providers.py:126-139`
- Why fragile: Throws EnvironmentError if API keys missing; fails at instantiation not startup
- Safe modification: Add lazy initialization or startup health check
- Test coverage: No tests exist

**Thread fork logic:**
- Files: `dialectic/operations.py:12-72`
- Why fragile: Complex state (parent_thread_id, fork_point_message_id, fork_memory_version) must all be consistent
- Safe modification: Add database transaction; validate fork point exists in source thread
- Test coverage: No tests exist

**Message type detection heuristics:**
- Files: `dialectic/llm/orchestrator.py:288-301`
- Why fragile: Simple string matching on LLM output; easily breaks with format changes
- Safe modification: Consider structured output or more robust parsing
- Test coverage: No tests exist

**Interjection decision engine:**
- Files: `dialectic/llm/heuristics.py:24-132`
- Why fragile: Multiple interacting rules with edge cases (stagnation detection depends on message count and length)
- Safe modification: Add comprehensive unit tests before changing rules
- Test coverage: No tests exist

## Scaling Limits

**In-memory connection registry:**
- Current capacity: Single server
- Limit: Cannot horizontally scale WebSocket connections
- Scaling path: Redis pub/sub for cross-server broadcasts; sticky sessions or connection state in Redis

**pgvector IVFFlat index:**
- Current capacity: Good for ~100K vectors
- Limit: Performance degrades with millions of memories
- Scaling path: Consider HNSW index; partition by room; or move to dedicated vector DB

**Event log growth:**
- Current capacity: Unbounded append-only
- Limit: Query performance degrades; storage costs grow
- Scaling path: Add archival strategy; partition by time; summarize old events

## Dependencies at Risk

**httpx without connection limits:**
- Risk: Unbounded concurrent connections to LLM providers
- Impact: Provider rate limits hit; potential connection exhaustion
- Migration plan: Add connection pool limits in httpx.AsyncClient

**pgvector extension requirement:**
- Risk: Tied to PostgreSQL; requires extension installation
- Impact: Complicates deployment; not available on all managed Postgres
- Migration plan: Abstract vector store interface; support Pinecone/Qdrant as alternatives

## Missing Critical Features

**No authentication system:**
- Problem: Users self-identify; no verification
- Blocks: Production deployment; multi-tenant security

**No test suite:**
- Problem: Zero test files found
- Blocks: Safe refactoring; regression detection

**No database migrations:**
- Problem: Only raw schema.sql; no migration tool
- Blocks: Schema evolution without data loss

**No logging aggregation:**
- Problem: Logs go to stdout only
- Blocks: Production debugging; observability

**No graceful shutdown:**
- Problem: No signal handlers for SIGTERM
- Blocks: Zero-downtime deployments; clean connection closure

## Test Coverage Gaps

**No test files exist:**
- What's not tested: Entire codebase (100% gap)
- Files: All files in `dialectic/`
- Risk: Regressions undetected; refactoring unsafe; no documentation of expected behavior
- Priority: High - foundational gap

**Critical untested paths:**
- LLM provider fallback chain (`dialectic/llm/router.py`)
- Thread ancestry traversal (`dialectic/operations.py`)
- Memory versioning and conflict detection (`dialectic/memory/manager.py`)
- WebSocket message handling (`dialectic/transport/handlers.py`)
- Interjection decision logic (`dialectic/llm/heuristics.py`)

---

*Concerns audit: 2026-01-20*
