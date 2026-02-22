# Dialectic

*A collaborative intelligence platform where two humans and an LLM co-reason together in real-time.*

The LLM isn't an assistant you query — it's a participant that challenges, synthesizes, and provokes. It decides when to speak based on configurable heuristics. Conversations fork like biological evolution. The LLM remembers its own positions, evolves an identity through dialogue, and structures reasoning through formal protocols.

## Quick Start

### 1. Install

```bash
cd dialectic
pip install -e .
```

### 2. Set up PostgreSQL

```bash
createdb dialectic
psql dialectic < schema.sql
```

Or: `make db-setup`

### 3. Set environment variables

```bash
cp .env.example .env
# Edit .env with your keys:
#   DATABASE_URL="postgresql://localhost/dialectic"
#   ANTHROPIC_API_KEY="sk-ant-..."
#   OPENAI_API_KEY="sk-..."    # Optional — enables fallback + embeddings
```

### 4. Run

```bash
# Backend (port 8002)
PORT=8002 python run.py

# Frontend (port 3000, separate terminal)
python -m http.server 3000 --directory frontend
```

Or: `make run` and `make frontend`

### 5. Open

- **App**: http://localhost:3000/app.html
- **API docs**: http://localhost:8002/docs
- **Health**: http://localhost:8002/health

---

## What Dialectic Can Do

### Core Dialogue
- **Heuristic interjection** — LLM decides when to speak (turn count, questions, semantic novelty, stagnation)
- **Dual LLM personas** — "primary" (co-thinker) vs "provoker" (destabilizer for stale conversations)
- **Thread forking** — any message becomes a branch point; cladogram visualization
- **Shared memories** — versioned, embeddable, cross-room; the LLM reads them in every prompt
- **Real-time WebSocket** — presence, typing indicators, streaming responses

### Thinking Protocols
Four structured reasoning modes the LLM facilitates:
- **Steelman** (4 phases) — construct the strongest version of a claim, then interrogate it
- **Socratic Descent** (3 phases) — demand definitions, trace to axiomatic bedrock
- **Devil's Advocate** (3 phases) — systematically attack the emerging consensus
- **Synthesis** (2 phases) — map tensions, produce structured integration document

Invoke via WebSocket: `{"type": "invoke_protocol", "payload": {"protocol_type": "steelman", "config": {"target_claim": "..."}}}`

### LLM Intelligence
- **Self-Memory** — the LLM extracts and remembers its own positions across sessions
- **Persistent Identity** — per-room evolved identity document + per-user thinking models
- **Cross-Session Context** — memories from other rooms injected into every prompt
- **Smart Memory Injection** — semantic search for the 20 most relevant memories (not brute-force)

### Async Dialogue (Slow Channel)
- **Annotator mode** — when the other user is offline, the LLM becomes a librarian/curator
- **Morning briefing** — LLM summarizes what you missed while away
- **Enriched push notifications** — contextual summaries, not just "new message"

### Conversation Analytics
- **Conversation DNA** — 6-dimensional fingerprint (tension, velocity, asymmetry, depth, divergence, memory density)
- **Archetypes** — Crucible, Deep Dive, Rhizome, Symposium, Forge, Open Field
- **Thread analytics** — argument density, question resolution, turn balance, fork count

### Knowledge Graph
- **Concept maps** — "show me everything about X across all rooms"
- **Idea provenance** — trace any memory back to the message and thread that created it
- **Contribution graphs** — who introduced ideas that became shared memories

### Event Replay
- **Time travel** — materialize room state at any point in history
- **SSE replay stream** — re-watch conversations unfold at 1x-20x speed
- **LLM decision replay** — reconstruct what the LLM saw when it made any response
- **Timeline heat map** — dense red = intense exchange, sparse blue = reflection

### Stakes / Commitments
- **Predictions** — make testable claims with deadlines and confidence levels
- **Calibration curves** — track how well you predict (Brier score)
- **Commitment surfacing** — the LLM reminds you of relevant active predictions
- **LLM predictions** — the LLM itself makes predictions, creating intellectual symmetry

### Real-Time Typing Analysis
- **Pre-computed novelty** — embedding computed while you type (500ms debounce)
- **Pre-fetched memories** — relevant memories ready before you hit send
- **50-85% latency reduction** — on the pre-LLM pipeline
- **Privacy preserving** — ephemeral only, never persisted or broadcast

---

## Architecture

```
dialectic/
├── api/
│   ├── main.py                 # FastAPI server (51 endpoints)
│   ├── auth/                   # JWT auth (signup, login, refresh)
│   └── notifications/          # Push notifications (Expo)
├── llm/
│   ├── orchestrator.py         # Central LLM coordinator
│   ├── providers.py            # Anthropic + OpenAI abstraction
│   ├── router.py               # Retry + exponential backoff + fallback chain
│   ├── heuristics.py           # Interjection decision engine
│   ├── prompts.py              # Layered prompt assembly
│   ├── context.py              # Smart context truncation
│   ├── self_memory.py          # Post-response claim extraction
│   ├── identity.py             # Evolved identity + user models
│   ├── annotator.py            # Async dialogue annotator mode
│   ├── protocol_library.py     # 4 thinking protocol definitions
│   └── protocol_manager.py     # Protocol state machine
├── memory/
│   ├── manager.py              # Versioned memory lifecycle
│   ├── vector_store.py         # pgvector semantic search
│   ├── embeddings.py           # OpenAI embedding provider
│   └── cross_session.py        # Cross-room memory operations
├── transport/
│   ├── websocket.py            # Connection registry + broadcast
│   └── handlers.py             # WebSocket message dispatch
├── analytics/
│   ├── analyzer.py             # Conversation metrics + DNA
│   ├── dna.py                  # 6-dimensional fingerprint
│   ├── knowledge_graph.py      # Materialized view + graph traversal
│   └── routes.py               # Analytics + graph REST endpoints
├── replay/
│   ├── engine.py               # Event replay + state materialization
│   ├── models.py               # Snapshot + replay event models
│   └── routes.py               # Replay REST + SSE endpoints
├── stakes/
│   ├── manager.py              # Commitment lifecycle + calibration
│   ├── detector.py             # Implicit prediction extraction
│   └── routes.py               # Stakes REST endpoints
├── tests/                      # 109 unit tests
├── models.py                   # Pydantic models + enums
├── operations.py               # Fork genealogy queries
├── schema.sql                  # PostgreSQL + pgvector (24 tables)
├── pyproject.toml              # Package config
├── frontend/
│   └── app.html                # Web frontend (dark theme, 3-party UI)
├── run.py                      # Entry point
└── requirements.txt
```

## API Endpoints (51 total)

### Core
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check + DB verification |
| `/rooms` | POST | Create room |
| `/rooms/{id}/join` | POST | Join room |
| `/rooms/{id}/threads` | GET | List threads |
| `/rooms/{id}/genealogy` | GET | Thread fork tree |
| `/rooms/{id}/memories` | GET/POST | Shared memories |
| `/rooms/{id}/settings` | GET/PATCH | LLM heuristic settings |
| `/rooms/{id}/presence` | GET | Online users |
| `/rooms/{id}/events` | GET | Event log |
| `/rooms/{id}/identity` | GET/PUT | LLM's evolved identity |
| `/rooms/{id}/briefing` | GET | Morning briefing (what you missed) |
| `/rooms/{id}/user-models/{uid}` | GET | LLM's model of your thinking |
| `/threads/{id}/messages` | GET/POST | Messages with pagination |
| `/threads/{id}/fork` | POST | Fork thread |
| `/messages/search` | GET | Full-text search |
| `/ws/{room_id}` | WS | Real-time WebSocket |

### Analytics & Graph
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/analytics/threads/{id}` | GET | Thread metrics |
| `/analytics/rooms/{id}` | GET | Room aggregate metrics |
| `/analytics/threads/{id}/dna` | GET | Thread DNA fingerprint |
| `/analytics/rooms/{id}/dna` | GET | Room DNA fingerprint |
| `/graph/concept-map` | GET | Cross-room concept map |
| `/graph/memories/{id}/provenance` | GET | Idea provenance trace |
| `/graph/rooms/{id}/contributions` | GET | Contribution graph |
| `/graph/refresh` | POST | Refresh knowledge graph |

### Replay
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/replay/rooms/{id}/state` | GET | Room state at any event sequence |
| `/replay/rooms/{id}/stream` | GET | SSE replay stream |
| `/replay/rooms/{id}/diff` | GET | Changes between two points |
| `/replay/rooms/{id}/timeline` | GET | Event density heat map |
| `/replay/messages/{id}/llm-context` | GET | LLM decision reconstruction |

### Stakes
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/stakes/rooms/{id}/commitments` | GET/POST | List/create predictions |
| `/stakes/commitments/{id}` | GET | Commitment with confidence history |
| `/stakes/commitments/{id}/confidence` | POST | Record confidence level |
| `/stakes/commitments/{id}/resolve` | POST | Resolve prediction |
| `/stakes/rooms/{id}/calibration` | GET | Calibration curve + Brier score |
| `/stakes/rooms/{id}/commitments/expiring` | GET | Approaching deadlines |

### Auth & Notifications
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/auth/signup` | POST | Create account |
| `/auth/login` | POST | Login (JWT) |
| `/auth/refresh` | POST | Refresh token |
| `/auth/verify-email` | POST | Email verification |
| `/auth/forgot-password` | POST | Password reset |
| `/notifications/push-token` | POST | Register push token |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Yes | Claude API key (primary LLM) |
| `OPENAI_API_KEY` | No | GPT fallback + vector embeddings |
| `JWT_SECRET_KEY` | No | JWT signing secret (auto-generated) |
| `PORT` | No | Server port (default 8000) |
| `ALLOWED_ORIGINS` | No | CORS origins (comma-separated) |
| `PRODUCTION` | No | Set to `1` for production mode |

## Tests

```bash
cd dialectic
python -m pytest tests/ -q
# 109 passed in 1.7s
```

## Key Design Decisions

- **Event Sourcing** — append-only `events` table enables replay, temporal queries, and full audit trail
- **Heuristic Interjection** — LLM speaks based on turn count, questions, semantic novelty, stagnation
- **Dual Persona** — "primary" (co-thinker) vs "provoker" (destabilizer)
- **LLM Self-Memory** — extracts and remembers its own positions across context windows
- **Thinking Protocols** — structured multi-phase reasoning with LLM as facilitator
- **Fork Genealogy** — recursive CTE builds conversation trees in a single SQL query
- **Vector Memory** — pgvector 1536-dim semantic search with cross-room references
- **Knowledge Graph** — materialized view over memory references, thread forks, message chains
- **Annotator Mode** — LLM becomes librarian/curator when other user is offline
- **Typing Analysis** — pre-computes novelty + memories while you type for faster responses

## Roadmap

See `.planning/NEXT-LEVEL-ROADMAP.md` for the full plan. Remaining:
- Enhanced heuristics (Inner Thoughts 8-heuristic framework)
- Multi-model rooms (N named LLM personas with turn-taking)
- Dialectic Graph UI (interactive knowledge visualization)
- Redis pub/sub for horizontal scaling
- Frontend migration to component framework
