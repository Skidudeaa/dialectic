# External Integrations

**Analysis Date:** 2026-01-20

## APIs & External Services

**LLM Providers:**

**Anthropic (Primary):**
- Purpose: Main LLM for dialogue participation
- SDK/Client: Direct HTTP via httpx (`dialectic/llm/providers.py:56-124`)
- Base URL: `https://api.anthropic.com/v1`
- Auth: `ANTHROPIC_API_KEY` environment variable
- API Version: `2023-06-01`
- Models supported:
  - `claude-sonnet-4-20250514` (primary)
  - `claude-haiku-4-20250514` (provoker)
  - `claude-opus-4-5-20251101`
- Features used: Messages API, streaming

**OpenAI (Fallback + Embeddings):**
- Purpose: LLM fallback chain, text embeddings for memory search
- SDK/Client: Direct HTTP via httpx (`dialectic/llm/providers.py:126-196`)
- Base URL: `https://api.openai.com/v1`
- Auth: `OPENAI_API_KEY` environment variable
- Endpoints used:
  - `/chat/completions` - Chat completion fallback
  - `/embeddings` - Memory vector generation (`dialectic/memory/embeddings.py:35-77`)
- Models:
  - Chat: `gpt-4o`, `gpt-4o-mini`
  - Embeddings: `text-embedding-3-small` (1536 dimensions)

**Model Mapping (Anthropic to OpenAI fallback):**
```python
# From dialectic/llm/router.py:60-67
"claude-sonnet-4-20250514" -> "gpt-4o"
"claude-haiku-4-20250514" -> "gpt-4o-mini"
"claude-opus-4-5-20251101" -> "gpt-4o"
```

## Data Storage

**Database:**
- Type: PostgreSQL with pgvector extension
- Connection: `DATABASE_URL` environment variable
- Default: `postgresql://localhost/dialectic`
- Client: asyncpg with connection pooling (`dialectic/api/main.py:40-69`)
- Pool config: min_size=2, max_size=10

**File Storage:**
- None detected - all data in PostgreSQL

**Caching:**
- None detected - no Redis, memcached, or in-memory caching layer
- WebSocket connections stored in-memory (single-server limitation)

## Authentication & Identity

**Auth Provider:**
- Custom token-based authentication
- Implementation: Room-scoped tokens (`dialectic/api/main.py:98-110`)
- Token generation: UUID hex (`uuid4().hex`)
- No user authentication (users created on-the-fly)
- Room access via shared token in URL query param

**Session Storage:**
- Client-side: localStorage (`dialectic/frontend/index.html:883-899`)
- Server-side: No persistent sessions

## Monitoring & Observability

**Error Tracking:**
- None detected (no Sentry, Datadog, etc.)

**Logging:**
- Python stdlib logging (`logging.basicConfig(level=logging.INFO)`)
- Log locations:
  - `dialectic/api/main.py` - Server lifecycle, WebSocket events
  - `dialectic/llm/orchestrator.py` - LLM decision tracing
  - `dialectic/llm/router.py` - Routing attempts, latency
  - `dialectic/memory/manager.py` - Memory operations
  - `dialectic/transport/websocket.py` - Connection management

**Metrics:**
- None detected (no Prometheus, StatsD, etc.)
- LLM latency tracked in routing attempts (`dialectic/llm/router.py:88-105`)

## CI/CD & Deployment

**Hosting:**
- Not configured - designed for local/single-server deployment
- Uvicorn ASGI server with reload enabled

**CI Pipeline:**
- None detected (no GitHub Actions, CircleCI, etc.)

**Containerization:**
- None detected (no Dockerfile, docker-compose.yml)

## Environment Configuration

**Required Environment Variables:**
| Variable | Required | Description | Used In |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string | `dialectic/api/main.py:35-38` |
| `ANTHROPIC_API_KEY` | Yes | Claude API key | `dialectic/llm/providers.py:66-68` |
| `OPENAI_API_KEY` | No | GPT fallback + embeddings | `dialectic/llm/providers.py:135-137`, `dialectic/memory/embeddings.py:45-47` |

**Secrets Location:**
- Environment variables only
- No secrets management service detected

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## WebSocket Protocol

**Endpoint:** `/ws/{room_id}`

**Query Parameters:**
- `token` - Room access token
- `user_id` - User UUID
- `thread_id` (optional) - Initial thread

**Inbound Message Types:**
| Type | Purpose | Handler |
|------|---------|---------|
| `send_message` | User sends message | `_handle_send_message` |
| `typing_start` | Typing indicator on | `_handle_typing` |
| `typing_stop` | Typing indicator off | `_handle_typing` |
| `switch_thread` | Change active thread | `_handle_switch_thread` |
| `fork_thread` | Create thread branch | `_handle_fork_thread` |
| `add_memory` | Create shared memory | `_handle_add_memory` |
| `edit_memory` | Update memory content | `_handle_edit_memory` |
| `invalidate_memory` | Soft-delete memory | `_handle_invalidate_memory` |
| `ping` | Keep-alive | `_handle_ping` |

**Outbound Message Types:**
| Type | Purpose |
|------|---------|
| `message_created` | New message broadcast |
| `user_joined` | User connected to room |
| `user_left` | User disconnected |
| `user_typing` | Typing indicator |
| `thread_created` | New thread forked |
| `memory_updated` | Memory changed |
| `llm_thinking` | LLM processing indicator |
| `error` | Error notification |
| `pong` | Keep-alive response |

## REST API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/rooms` | POST | Create room |
| `/users` | POST | Create user |
| `/rooms/{id}/join` | POST | Join room |
| `/rooms/{id}/threads` | GET | List threads |
| `/rooms/{id}/memories` | GET, POST | Manage memories |
| `/rooms/{id}/memories/search` | GET | Semantic search |
| `/rooms/{id}/events` | GET | Event log |
| `/threads/{id}/messages` | GET, POST | Messages |
| `/threads/{id}/fork` | POST | Fork thread |
| `/memories/{id}` | PUT, DELETE | Edit/invalidate |
| `/ws/{room_id}` | WS | Real-time connection |
| `/health` | GET | Health check |

## LLM Retry & Fallback Strategy

**Configuration:** (`dialectic/llm/router.py`)
- Max retries per provider: 3
- Retry delays: [1.0s, 2.0s, 4.0s] (exponential backoff)
- Fallback chain:
  1. Primary provider + primary model
  2. Fallback provider + mapped model
  3. Primary provider + fallback model

**Timeout:**
- HTTP client timeout: 120 seconds (`dialectic/llm/providers.py:70,139`)

---

*Integration audit: 2026-01-20*
