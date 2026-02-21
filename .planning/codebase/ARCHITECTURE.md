# Architecture

**Analysis Date:** 2026-01-20

## Pattern Overview

**Overall:** Event-Sourced Layered Monolith with Real-Time Transport

**Key Characteristics:**
- Event sourcing with append-only `events` table as source of truth
- Layered architecture: API -> Handlers -> Domain -> Data
- Real-time communication via WebSocket with room-based message routing
- Heuristic-driven LLM interjection (autonomous participant, not assistant)
- Fork-based conversation branching with memory versioning

## Layers

**API Layer:**
- Purpose: HTTP/WebSocket entry points, request validation, auth
- Location: `dialectic/api/`
- Contains: FastAPI routes, Pydantic request/response schemas, CORS config
- Depends on: All other layers (orchestrates domain operations)
- Used by: Frontend clients, external HTTP consumers
- Key file: `dialectic/api/main.py`

**Transport Layer:**
- Purpose: WebSocket connection management and message dispatch
- Location: `dialectic/transport/`
- Contains: Connection registry, inbound/outbound message types, handler dispatch
- Depends on: LLM Layer, Memory Layer, Domain Models
- Used by: API Layer (WebSocket endpoint)
- Key files: `dialectic/transport/websocket.py`, `dialectic/transport/handlers.py`

**LLM Layer:**
- Purpose: LLM orchestration, provider abstraction, interjection logic
- Location: `dialectic/llm/`
- Contains: Provider clients (Anthropic/OpenAI), retry/fallback routing, heuristics engine, prompt assembly
- Depends on: Domain Models
- Used by: Transport Layer (MessageHandler)
- Key files: `dialectic/llm/orchestrator.py`, `dialectic/llm/providers.py`, `dialectic/llm/router.py`, `dialectic/llm/heuristics.py`, `dialectic/llm/prompts.py`

**Memory Layer:**
- Purpose: Vector search, embedding generation, memory lifecycle
- Location: `dialectic/memory/`
- Contains: Embedding providers (OpenAI), pgvector operations, memory CRUD with versioning
- Depends on: Domain Models, Database
- Used by: Transport Layer, LLM Layer
- Key files: `dialectic/memory/manager.py`, `dialectic/memory/embeddings.py`, `dialectic/memory/vector_store.py`

**Domain Layer:**
- Purpose: Core business logic and data models
- Location: `dialectic/` (root)
- Contains: Pydantic models, enums, event payloads, fork/ancestry operations
- Depends on: Nothing (pure domain)
- Used by: All other layers
- Key files: `dialectic/models.py`, `dialectic/operations.py`

**Data Layer:**
- Purpose: PostgreSQL with pgvector, asyncpg connection pooling
- Location: Schema at `dialectic/schema.sql`, pool management in `dialectic/api/main.py`
- Contains: DDL for events, rooms, threads, messages, memories, memory_versions
- Depends on: PostgreSQL + pgvector extension
- Used by: All layers via dependency injection

## Data Flow

**Human Message Flow:**

1. Client sends `send_message` via WebSocket to `/ws/{room_id}`
2. `MessageHandler._handle_send_message()` creates Message + Event records
3. Message is broadcast to all room connections via `ConnectionManager.broadcast()`
4. Semantic novelty computed via `MemoryManager.compute_message_novelty()`
5. `LLMOrchestrator.on_message()` evaluates interjection heuristics
6. If triggered, `PromptBuilder.build()` assembles prompt with room context, user modifiers, memories
7. `ModelRouter.route()` executes request with retry + provider fallback
8. LLM response persisted as new Message + Event, broadcast to room

**Thread Fork Flow:**

1. Client sends `fork_thread` WebSocket message
2. `operations.fork_thread()` captures current memory version
3. New Thread record created with `parent_thread_id` and `fork_point_message_id`
4. Fork event logged to `events` table
5. Broadcast notifies all room users

**Memory Operation Flow:**

1. Client sends `add_memory`/`edit_memory`/`invalidate_memory`
2. `MemoryManager` creates/updates Memory record with version tracking
3. Embedding generated via `EmbeddingProvider.embed()`
4. `VectorStore.upsert_embedding()` stores in pgvector column
5. Event logged, broadcast sent to room

**State Management:**
- Primary state in PostgreSQL (events table as source of truth)
- Derived state in `rooms`, `threads`, `messages`, `memories` tables
- Transient state in `ConnectionManager` (in-memory WebSocket registry)
- No client-side persistent state (all operations hit server)

## Key Abstractions

**Event (Event Sourcing):**
- Purpose: Immutable record of all state changes
- Examples: `dialectic/models.py` (Event, EventType enum)
- Pattern: Append-only log with monotonic sequence, payload per event type

**Room:**
- Purpose: Conversation space containing threads, users, memories
- Examples: `dialectic/models.py` (Room model)
- Pattern: Container with configurable LLM settings (provider, model, thresholds)

**Thread:**
- Purpose: Linear conversation branch, supports forking
- Examples: `dialectic/models.py` (Thread model), `dialectic/operations.py` (fork_thread, get_thread_messages)
- Pattern: Tree structure via `parent_thread_id`, fork ancestry via `fork_point_message_id`

**Memory:**
- Purpose: Versioned shared knowledge injected into LLM prompts
- Examples: `dialectic/models.py` (Memory, MemoryScope, MemoryStatus)
- Pattern: Soft delete (invalidation), version history in `memory_versions` table

**InterjectionDecision:**
- Purpose: Explicit decision object for LLM participation triggers
- Examples: `dialectic/llm/heuristics.py` (InterjectionDecision, InterjectionEngine)
- Pattern: Rule-based triggers (turn threshold, question detection, semantic novelty, stagnation)

**OrchestrationResult:**
- Purpose: Full trace of LLM interaction for observability
- Examples: `dialectic/llm/orchestrator.py` (OrchestrationResult)
- Pattern: Includes decision, routing attempts, prompt used, response

## Entry Points

**HTTP API:**
- Location: `dialectic/api/main.py`
- Triggers: HTTP requests to REST endpoints
- Responsibilities: Room/user CRUD, thread listing, message retrieval, memory operations

**WebSocket:**
- Location: `dialectic/api/main.py` (`websocket_endpoint`)
- Triggers: WebSocket connections to `/ws/{room_id}`
- Responsibilities: Real-time messaging, typing indicators, LLM interjection

**Application Bootstrap:**
- Location: `dialectic/run.py`
- Triggers: `python run.py` or uvicorn import of `api.main:app`
- Responsibilities: Start uvicorn server, database pool initialization via lifespan context

## Error Handling

**Strategy:** Exception-based with graceful degradation

**Patterns:**
- WebSocket handlers: try/catch with `_send_error()` to client, connection cleanup on disconnect
- LLM routing: Retry with exponential backoff (1s, 2s, 4s), provider fallback chain, system message on total failure
- Database: asyncpg pool with automatic connection recovery
- Embeddings: Fallback to mock embeddings if no OPENAI_API_KEY

## Cross-Cutting Concerns

**Logging:** Python `logging` module, INFO level by default, structured via logger name per module

**Validation:** Pydantic models for all request/response schemas, runtime type checking

**Authentication:** Room token-based (simple bearer), verified via `verify_room_token()` helper

**Observability:** Events table captures full audit trail, `/rooms/{room_id}/events` endpoint for replay

---

*Architecture analysis: 2026-01-20*
