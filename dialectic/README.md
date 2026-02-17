# Dialectic

*A shared thinking space where two humans and an LLM co-reason together.*

The LLM isn't an assistant you query — it's a participant that challenges, synthesizes, and provokes. It decides when to speak based on configurable heuristics. Conversations fork like biological evolution, creating a living tree of ideas.

## Quick Start

### 1. Install dependencies

```bash
cd dialectic
pip install -r requirements.txt
```

### 2. Set up PostgreSQL

```bash
# Create database and install pgvector
createdb dialectic
psql dialectic -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql dialectic < schema.sql

# Apply migrations
psql dialectic < migrations/add_indexes.sql
psql dialectic < migrations/cross_session_memories.sql
```

Or use the Makefile:
```bash
make db-setup
```

### 3. Set environment variables

```bash
export DATABASE_URL="postgresql://postgres@localhost/dialectic"
export ANTHROPIC_API_KEY="sk-ant-..."
export JWT_SECRET_KEY="your-secret-key-here"
export OPENAI_API_KEY="sk-..."  # Optional — enables fallback + embeddings
```

See `.env.example` for all options.

### 4. Run

```bash
# Start the backend (port 8000)
python run.py

# Serve the frontend (port 3000, separate terminal)
python -m http.server 3000 --directory frontend
```

Or: `make run` and `make frontend`

### 5. Open

- **New frontend**: http://localhost:3000/app.html
- **Classic frontend**: http://localhost:3000/index.html
- **API docs**: http://localhost:8000/docs

## What Makes This Different

| Feature | ChatGPT/Claude.ai | Slack/Discord | Dialectic |
|---------|-------------------|---------------|-----------|
| LLM decides when to speak | No | No | Yes — heuristic interjection engine |
| Dual LLM personas | No | No | Yes — participant + provoker |
| Conversation forking | No | No | Yes — cladogram visualization |
| Philosophical calibration | No | No | Yes — aggression, metaphysics tolerance |
| Multi-party real-time | No | Yes | Yes — 2 humans + 1 LLM |
| Event sourcing | No | No | Yes — full temporal queries + replay |

## Architecture

```
dialectic/
├── api/
│   ├── main.py              # FastAPI server (REST + WebSocket)
│   ├── auth/                # JWT auth (signup, login, refresh, biometric)
│   ├── notifications/       # Push notifications (Expo)
│   └── cross_session_routes.py  # Cross-room memory API
├── llm/
│   ├── orchestrator.py      # Central LLM coordinator
│   ├── providers.py         # Anthropic + OpenAI abstraction
│   ├── router.py            # Retry with exponential backoff + fallback chain
│   ├── heuristics.py        # Interjection decision engine
│   ├── prompts.py           # Layered prompt assembly
│   └── context.py           # Smart context truncation with priority scoring
├── memory/
│   ├── manager.py           # Versioned memory lifecycle
│   ├── vector_store.py      # pgvector semantic search
│   ├── embeddings.py        # OpenAI embedding provider
│   └── cross_session.py     # Cross-room memory operations
├── transport/
│   ├── websocket.py         # Connection registry + broadcast
│   └── handlers.py          # WebSocket message dispatch
├── models.py                # Pydantic models + event types
├── operations.py            # Fork genealogy queries
├── schema.sql               # PostgreSQL + pgvector schema (19 tables)
├── frontend/
│   ├── app.html             # Next-gen web frontend (dark theme, 3-party UI)
│   └── index.html           # Classic web frontend
├── docs/
│   └── VISION.md            # Future feature designs
├── Makefile                 # Setup/run/db commands
├── run.py                   # Entry point
└── requirements.txt
```

## API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check (verifies DB) |
| `/auth/signup` | POST | Create account |
| `/auth/login` | POST | Login (returns JWT) |
| `/auth/refresh` | POST | Refresh access token |
| `/rooms` | POST | Create room |
| `/rooms/{id}/join` | POST | Join room |
| `/rooms/{id}/threads` | GET | List threads |
| `/rooms/{id}/genealogy` | GET | Thread fork tree |
| `/rooms/{id}/memories` | GET/POST | Manage shared memories |
| `/rooms/{id}/settings` | GET/PATCH | LLM heuristic settings |
| `/rooms/{id}/presence` | GET | Online users |
| `/rooms/{id}/events` | GET | Event log |
| `/threads/{id}/messages` | GET/POST | Messages (with pagination) |
| `/threads/{id}/fork` | POST | Fork thread from message |
| `/messages/search` | GET | Full-text search |
| `/ws/{room_id}` | WS | Real-time connection |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Yes | Claude API key (primary LLM) |
| `JWT_SECRET_KEY` | Yes | Secret for JWT token signing |
| `OPENAI_API_KEY` | No | GPT fallback + vector embeddings |
| `ALLOWED_ORIGINS` | No | CORS origins (comma-separated) |
| `PRODUCTION` | No | Set to `1` for production mode |
| `WEB_CONCURRENCY` | No | Uvicorn workers in production |

## Key Design Decisions

- **Event Sourcing**: All state changes in append-only `events` table — enables replay and temporal queries
- **Heuristic Interjection**: LLM speaks based on turn count (4+), questions, semantic novelty, stagnation
- **Dual Persona**: "Primary" (co-thinker) vs "Provoker" (destabilizer for stale conversations)
- **Fork Genealogy**: Recursive CTE builds full conversation tree in single SQL query
- **Vector Memory**: pgvector for 1536-dim semantic search over shared memories
- **Smart Context**: Priority scoring preserves the most relevant messages within token limits

## Vision

See `docs/VISION.md` for planned features:
- **Dialectic Replay** — re-watch conversations unfold
- **Conversation DNA** — visual fingerprints for dialogue character
- **Counterfactual Forking** — "what if?" alternate timelines
- **Intellectual Resonance** — who reasons well together
- **Living Argument Maps** — real-time logical structure extraction
