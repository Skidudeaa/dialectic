# Technology Stack

**Analysis Date:** 2026-01-20

## Languages

**Primary:**
- Python 3.x - Backend API, LLM orchestration, memory management

**Secondary:**
- JavaScript (ES6+) - Frontend single-page application (`dialectic/frontend/index.html`)
- SQL - Database schema and queries (`dialectic/schema.sql`)

## Runtime

**Environment:**
- Python 3.10+ (inferred from type hints syntax like `list[dict]`, `dict[UUID, ...]`)
- No `.python-version` or `pyproject.toml` detected

**Package Manager:**
- pip with `requirements.txt`
- Lockfile: Not present (no `requirements.lock` or `pip-tools` constraints)

## Frameworks

**Core:**
- FastAPI 0.109.0 - REST API and WebSocket server (`dialectic/api/main.py`)
- Pydantic 2.5.3 - Data validation, serialization, model definitions (`dialectic/models.py`)
- uvicorn 0.27.0 - ASGI server with auto-reload (`dialectic/run.py`)

**Database:**
- asyncpg 0.29.0 - Async PostgreSQL driver
- pgvector extension - Vector similarity search for embeddings

**HTTP Client:**
- httpx 0.26.0 - Async HTTP for LLM API calls (`dialectic/llm/providers.py`)

**WebSocket:**
- websockets 12.0 - WebSocket protocol support
- FastAPI WebSocket - Real-time bidirectional communication

**Build/Dev:**
- No build tooling detected for Python (no pytest, black, ruff in requirements)
- Frontend is vanilla JS, no bundler

## Key Dependencies

**Critical:**
- `fastapi==0.109.0` - Core web framework, handles REST + WebSocket
- `asyncpg==0.29.0` - Database connectivity, connection pooling
- `pydantic==2.5.3` - All data models inherit from BaseModel
- `httpx==0.26.0` - LLM provider API calls (Anthropic, OpenAI)

**Infrastructure:**
- `uvicorn[standard]==0.27.0` - Production-ready ASGI server
- `websockets==12.0` - WebSocket protocol implementation
- `python-multipart==0.0.6` - Form data parsing for FastAPI

## Configuration

**Environment Variables:**
| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (default: `postgresql://localhost/dialectic`) |
| `ANTHROPIC_API_KEY` | Yes | Claude API authentication |
| `OPENAI_API_KEY` | No | GPT fallback + embeddings (text-embedding-3-small) |

**Application Config:**
- Server runs on `0.0.0.0:8000` with auto-reload (`dialectic/run.py`)
- Database pool: min 2, max 10 connections (`dialectic/api/main.py:56`)
- CORS: Allows all origins (development mode) (`dialectic/api/main.py:83-89`)

**Build Configuration:**
- No build config files (pyproject.toml, setup.py, setup.cfg)
- Direct module execution: `python dialectic/run.py`

## Database

**Engine:** PostgreSQL with pgvector extension

**Schema Location:** `dialectic/schema.sql`

**Key Tables:**
- `events` - Append-only event log (event sourcing)
- `rooms` - Conversation spaces with LLM settings
- `threads` - Conversation branches (supports forking)
- `messages` - Sequential messages with speaker types
- `memories` - Versioned shared knowledge with 1536-dim embeddings
- `users` - Participants with style preferences
- `room_memberships` - Many-to-many room participation
- `memory_versions` - Version history for memories

**Vector Storage:**
- pgvector extension for semantic search
- 1536-dimension embeddings (OpenAI text-embedding-3-small compatible)
- IVFFlat index with cosine distance (`dialectic/schema.sql:115`)

## Platform Requirements

**Development:**
- Python 3.10+
- PostgreSQL 14+ with pgvector extension
- Modern browser for frontend

**Production:**
- Single-server only (in-memory WebSocket registry)
- No containerization config detected (no Dockerfile, docker-compose)
- No CI/CD configuration detected

## Default Models

**LLM Configuration (per room):**
- Primary provider: `anthropic`
- Fallback provider: `openai`
- Primary model: `claude-sonnet-4-20250514`
- Provoker model: `claude-haiku-4-20250514`

**Embedding Model:**
- OpenAI `text-embedding-3-small` (1536 dimensions)
- Falls back to mock embeddings if no API key

---

*Stack analysis: 2026-01-20*
