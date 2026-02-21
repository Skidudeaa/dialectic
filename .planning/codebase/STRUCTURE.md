# Codebase Structure

**Analysis Date:** 2026-01-20

## Directory Layout

```
DwoodAmo/
├── .planning/                 # Planning documents
│   └── codebase/              # GSD codebase analysis docs
├── CLAUDE.md                  # Claude Code guidance file
└── dialectic/                 # Main application
    ├── api/                   # FastAPI HTTP/WebSocket layer
    │   ├── __init__.py
    │   └── main.py            # Application entry, all routes
    ├── llm/                   # LLM orchestration layer
    │   ├── __init__.py        # Public exports
    │   ├── orchestrator.py    # Central coordinator
    │   ├── providers.py       # Anthropic/OpenAI clients
    │   ├── router.py          # Retry + fallback logic
    │   ├── heuristics.py      # Interjection decision engine
    │   └── prompts.py         # Prompt assembly
    ├── memory/                # Vector search + memory lifecycle
    │   ├── __init__.py        # Public exports
    │   ├── manager.py         # Memory CRUD + versioning
    │   ├── embeddings.py      # Embedding providers
    │   └── vector_store.py    # pgvector operations
    ├── transport/             # WebSocket management
    │   ├── __init__.py        # Public exports
    │   ├── websocket.py       # Connection registry
    │   └── handlers.py        # Message dispatch
    ├── frontend/              # Static web UI
    │   └── index.html         # Single-page application
    ├── models.py              # Pydantic models + enums
    ├── operations.py          # Fork/ancestry queries
    ├── schema.sql             # PostgreSQL DDL
    ├── requirements.txt       # Python dependencies
    ├── run.py                 # Application entry point
    └── README.md              # Project documentation
```

## Directory Purposes

**dialectic/api/:**
- Purpose: HTTP API and WebSocket endpoints
- Contains: FastAPI app, route handlers, request/response schemas
- Key files: `main.py` (712 lines, all routes and WebSocket endpoint)

**dialectic/llm/:**
- Purpose: LLM integration, provider abstraction, autonomous interjection
- Contains: Provider clients, routing logic, heuristics, prompt construction
- Key files:
  - `orchestrator.py`: Central coordinator for LLM interactions
  - `providers.py`: Anthropic + OpenAI API wrappers
  - `router.py`: Retry/fallback chain
  - `heuristics.py`: When LLM should speak
  - `prompts.py`: System prompt assembly

**dialectic/memory/:**
- Purpose: Semantic memory with vector search
- Contains: Embedding generation, pgvector queries, memory lifecycle
- Key files:
  - `manager.py`: High-level memory operations
  - `embeddings.py`: OpenAI embeddings + mock fallback
  - `vector_store.py`: pgvector search/novelty

**dialectic/transport/:**
- Purpose: Real-time WebSocket communication
- Contains: Connection registry, message types, handler dispatch
- Key files:
  - `websocket.py`: ConnectionManager, message types
  - `handlers.py`: MessageHandler for all WebSocket operations

**dialectic/frontend/:**
- Purpose: Browser-based UI
- Contains: Single HTML file with embedded CSS/JS
- Key files: `index.html` (40KB single-page app)

## Key File Locations

**Entry Points:**
- `dialectic/run.py`: Uvicorn bootstrap (starts server on 0.0.0.0:8000)
- `dialectic/api/main.py`: FastAPI app definition, lifespan context

**Configuration:**
- `dialectic/requirements.txt`: Python dependencies
- `dialectic/schema.sql`: Database schema (run via psql)
- Environment variables: DATABASE_URL, ANTHROPIC_API_KEY, OPENAI_API_KEY

**Core Logic:**
- `dialectic/models.py`: All Pydantic models, enums, event payloads
- `dialectic/operations.py`: Thread fork and ancestry resolution
- `dialectic/llm/orchestrator.py`: LLM decision and execution flow
- `dialectic/transport/handlers.py`: WebSocket message processing

**Testing:**
- No test files detected in codebase

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `vector_store.py`, `main.py`)
- Package init: `__init__.py` with public exports
- SQL schema: `schema.sql`
- Static assets: `index.html`

**Directories:**
- All lowercase, single word (e.g., `api`, `llm`, `memory`, `transport`, `frontend`)

**Classes:**
- PascalCase (e.g., `LLMOrchestrator`, `MemoryManager`, `ConnectionManager`)

**Functions:**
- snake_case (e.g., `fork_thread`, `get_thread_messages`, `_handle_send_message`)
- Private methods prefixed with underscore

**Variables:**
- snake_case (e.g., `room_id`, `thread_id`, `semantic_novelty`)
- Constants: UPPER_SNAKE_CASE (e.g., `MAX_RETRIES`, `RETRY_DELAYS`)

**Pydantic Models:**
- PascalCase for model names (e.g., `Room`, `Message`, `Memory`)
- PascalCase for payload types (e.g., `ThreadForkedPayload`, `MessageCreatedPayload`)

**Enums:**
- PascalCase for enum class (e.g., `MessageType`, `SpeakerType`)
- UPPER_SNAKE_CASE for values (e.g., `LLM_PRIMARY`, `MEMORY_ADDED`)

## Where to Add New Code

**New REST Endpoint:**
- Add route in `dialectic/api/main.py`
- Add request/response Pydantic schemas in the same file (SCHEMAS section)
- Follow existing pattern with `@app.post/get/put/delete` decorator

**New WebSocket Message Type:**
- Add type constant in `dialectic/transport/websocket.py` (MessageTypes class)
- Add handler method in `dialectic/transport/handlers.py` (MessageHandler class)
- Register handler in `handlers` dict in `MessageHandler.handle()`

**New LLM Provider:**
- Create class in `dialectic/llm/providers.py` extending `LLMProvider`
- Add to `PROVIDERS` dict and `ProviderName` enum
- Update model mappings in `dialectic/llm/router.py`

**New Domain Model:**
- Add Pydantic model in `dialectic/models.py`
- Add corresponding table in `dialectic/schema.sql`
- If has events: add EventType enum value and payload schema

**New Memory Operation:**
- Add method in `dialectic/memory/manager.py`
- Follow event sourcing pattern: create Event, execute DB operation

**Utility Functions:**
- Domain operations: `dialectic/operations.py`
- Package-specific: within the relevant package

## Special Directories

**.planning/:**
- Purpose: GSD planning and analysis documents
- Generated: By GSD tools
- Committed: Yes (documentation artifacts)

**dialectic/.git/:**
- Purpose: Git repository for dialectic subproject
- Generated: By git
- Committed: Not applicable (is the repo)

**dialectic/frontend/:**
- Purpose: Static frontend assets
- Generated: No (manually authored)
- Committed: Yes
- Note: Single 40KB index.html, served via Python http.server

---

*Structure analysis: 2026-01-20*
