# Dialectic

## What is this?

Dialectic is a platform where two people and an AI think together. Not the way you use ChatGPT — where you ask and it answers. Here, the AI is sitting at the table with you. It listens. It decides when to speak. It challenges you when you're lazy, synthesizes when you're stuck, and shuts up when you're on a roll.

You and a friend open a room. You start talking about whether free will exists, or whether your startup idea is any good, or what consciousness actually is. The AI watches. After a few exchanges, it jumps in — not because you asked, but because it detected that you're going in circles, or that someone asked a question nobody answered, or that the conversation just got genuinely interesting. It has two modes: a thoughtful co-thinker and a provocateur that destabilizes comfortable consensus.

Any message can become a fork point. You branch the conversation like git branches code. The resulting tree — a cladogram — shows how your ideas evolved. Shared memories persist across sessions, so the AI remembers that you changed your mind about compatibilism three weeks ago and can bring it up when it's relevant.

The AI also remembers *itself*. It extracts its own positions after each conversation, builds a model of how each human thinks, and evolves an identity document over time. It's not just smart — it's *your* interlocutor, shaped by your intellectual history together.

## What makes it different

Every other AI tool treats the AI as a servant. You prompt, it responds. Dialectic treats the AI as a participant. It has heuristics for when to speak, when to stay silent, and when to switch from helpful to adversarial. It has structured reasoning protocols — you can invoke a Steelman analysis, a Socratic descent, or a Devil's Advocate attack, and the AI facilitates multi-phase structured inquiry. Conversations have DNA fingerprints. You can make predictions, track your calibration, and see how well you actually think. You can replay any conversation in real time, seeing exactly what the AI saw when it decided to interject.

No other platform does this. Chat apps don't have AI agency. AI assistants don't have multi-party dialogue. Neither has event sourcing, thread forking, knowledge graphs, or thinking protocols.

## Quick Start

```bash
# 1. Install
cd dialectic
pip install -e .

# 2. Database
createdb dialectic
psql dialectic < schema.sql

# 3. Environment
cp .env.example .env
# Set ANTHROPIC_API_KEY (required) and OPENAI_API_KEY (optional, for fallback + embeddings)

# 4. Run the backend
PORT=8002 python run.py

# 5. Run the frontend (new terminal)
cd frontend/app && npm install && npm run dev

# 6. Open
# http://localhost:3000
```

Or use `make run` and `make frontend` for the legacy frontend at `http://localhost:3000/app.html`.

## The Full Feature Set

### The Basics
- **Real-time WebSocket messaging** between 2 humans + 1 AI
- **Heuristic interjection** — the AI decides when to speak based on 8 signals: explicit mentions, turn count, questions, information gaps, semantic novelty, stagnation, speaker imbalance, and silence logging
- **Dual persona** — "primary" (co-thinker) and "provoker" (destabilizer for lazy consensus)
- **Multi-model rooms** — add named AI personas (e.g., "Skeptic" using Haiku, "Deep Thinker" using Opus) with configurable trigger strategies (on mention, after primary, on disagreement, periodic)
- **Thread forking** — branch any message into a new conversation thread, with full ancestry traversal
- **Shared memories** — versioned, embeddable, cross-room. The AI reads relevant memories in every prompt via semantic search

### Thinking Protocols
Structured reasoning modes where the AI becomes a facilitator:
- **Steelman** (4 phases) — frame a claim, construct its strongest version, interrogate it, synthesize findings
- **Socratic Descent** (3 phases) — restate the question, demand precise definitions, trace to axiomatic bedrock
- **Devil's Advocate** (3 phases) — articulate the consensus, systematically attack it, assess what survived
- **Synthesis** (2 phases) — map all active tensions, produce a structured integration document

Each protocol writes its conclusions to shared memory automatically.

### The Third Mind
The AI isn't stateless. It evolves through dialogue:
- **Self-memory** — after each response, a background process extracts the AI's claims and positions, storing them as persistent memories. It remembers what it argued last week.
- **Evolved identity** — per-room identity document distilled after sessions. The AI knows it tends toward functionalism in Room A and empiricism in Room B. Humans can view and edit this.
- **User models** — the AI builds a model of each human's thinking style, strengths, and blind spots. It knows that you retreat to analogies under pressure and that your friend tends toward empiricism when challenged.
- **Cross-session context** — memories from other rooms are injected into every prompt, creating a web of connected thinking.

### Async Dialogue (The Slow Channel)
When only one person is online, the AI switches from participant to curator:
- **Annotator mode** — instead of arguing, it links your message to prior conversations, surfaces relevant memories, and identifies tensions with previously stated positions
- **Morning briefing** — when you come back online, get an AI-generated summary of what you missed
- **Enriched push notifications** — not just "new message" but "Alice argued against your position on X — Claude noted connections to your January discussion on Y"

### Conversation Analytics
- **Conversation DNA** — 6-dimensional fingerprint measuring tension, velocity, asymmetry, depth, divergence, and memory density
- **Archetypes** — each conversation is classified: Crucible (intense debate), Deep Dive (slow exploration), Rhizome (branching), Symposium (balanced), Forge (concept-building), Open Field (open-ended)
- **Metrics** — argument density, question resolution rate, turn balance, fork count, provoker intervention frequency

### Knowledge Graph
The system already stores graph relationships in its data model — this surfaces them:
- **Concept maps** — "show me everything we've discussed about consciousness across all my rooms"
- **Idea provenance** — trace any memory back through its version history, the message that spawned it, the thread fork that created the context
- **Contribution graphs** — who introduced ideas that became shared memories? Which memories get cited most?

### Event Replay
Every state change is an immutable event. This enables time travel:
- **State materialization** — reconstruct complete room state at any point in history
- **SSE replay stream** — re-watch conversations unfold at 1x-20x speed, with original timing
- **LLM decision replay** — see exactly what the AI saw (context, memories, prompt hash) when it made any response
- **Timeline heat map** — visualize conversation intensity over time
- **State diffing** — see what changed between any two points

### Stakes and Commitments
Conversations without stakes are entertainment. Conversations with stakes are thinking:
- **Predictions** — make testable claims with deadlines and confidence levels
- **Confidence tracking** — update your confidence as new evidence arrives
- **Calibration curves** — see how well you actually predict (Brier score). Are your 70% predictions right 70% of the time?
- **Commitment surfacing** — the AI reminds you when a conversation touches a live prediction
- **The AI predicts too** — creating genuine intellectual symmetry

### Real-Time Typing Analysis
While you type, the system pre-computes:
- Semantic novelty of your partial message (will this trigger the AI?)
- Relevant memories for context injection
- Result: 50-85% reduction in perceived AI response latency
- Fully ephemeral — nothing persisted, nothing broadcast. Opt-in per room.

### Horizontal Scaling
- **Redis pub/sub** — drop-in replacement for in-memory WebSocket broadcasting. Set `REDIS_URL` to enable. Falls back to single-server mode automatically.

## Running It

### Backend
```bash
cd dialectic
export DATABASE_URL="postgresql://localhost/dialectic"
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."  # Optional
PORT=8002 python run.py
```

### Frontend (React)
```bash
cd dialectic/frontend/app
npm install
npm run dev
# Opens on http://localhost:3000, proxies API to localhost:8002
```

### Legacy Frontend
```bash
python -m http.server 3000 --directory dialectic/frontend
# Open http://localhost:3000/app.html
```

### Tests
```bash
cd dialectic
python -m pytest tests/ -q
# 134 passed in 1.5s
```

### Multi-worker with Redis
```bash
export REDIS_URL="redis://localhost:6379"
PRODUCTION=1 WEB_CONCURRENCY=4 PORT=8002 python run.py
```

## Architecture

```
dialectic/
├── api/
│   ├── main.py                 # FastAPI server (51+ endpoints)
│   ├── token_utils.py          # Auth token extraction (header + query param)
│   ├── personas.py             # Multi-model persona CRUD
│   ├── auth/                   # JWT auth (signup, login, refresh, verify)
│   └── notifications/          # Expo push notifications
├── llm/
│   ├── orchestrator.py         # Central LLM coordinator
│   ├── providers.py            # Anthropic + OpenAI provider abstraction
│   ├── router.py               # Retry with exponential backoff + provider fallback
│   ├── heuristics.py           # 8-heuristic interjection decision engine
│   ├── prompts.py              # Layered prompt assembly (identity → protocol → room → memory)
│   ├── context.py              # Priority-based context truncation
│   ├── self_memory.py          # Post-response claim/position extraction
│   ├── identity.py             # Evolved identity documents + user thinking models
│   ├── annotator.py            # Async dialogue annotator (curator mode)
│   ├── multi_model.py          # Multi-persona coordinator + turn-taking
│   ├── protocol_library.py     # 4 thinking protocol definitions + phase instructions
│   └── protocol_manager.py     # Protocol lifecycle state machine
├── memory/
│   ├── manager.py              # Versioned memory lifecycle + novelty computation
│   ├── vector_store.py         # pgvector 1536-dim semantic search
│   ├── embeddings.py           # OpenAI text-embedding-3-small provider
│   └── cross_session.py        # Cross-room memory search, promotion, collections
├── transport/
│   ├── websocket.py            # Connection registry + broadcast
│   ├── handlers.py             # WebSocket message dispatch (20+ message types)
│   └── redis_manager.py        # Redis pub/sub drop-in for horizontal scaling
├── analytics/
│   ├── analyzer.py             # Conversation metrics engine
│   ├── dna.py                  # 6-dimensional conversation fingerprint
│   ├── knowledge_graph.py      # Materialized view + graph traversal engine
│   ├── graph_routes.py         # Knowledge graph REST endpoints
│   └── routes.py               # Analytics REST endpoints
├── replay/
│   ├── engine.py               # Event replay + state materialization
│   ├── models.py               # Snapshot, replay event, diff models
│   └── routes.py               # Replay REST + SSE endpoints
├── stakes/
│   ├── manager.py              # Commitment lifecycle + calibration curves
│   ├── detector.py             # Implicit prediction extraction via LLM
│   └── routes.py               # Stakes REST endpoints
├── tests/                      # 134 unit tests
├── models.py                   # All Pydantic models + enums
├── operations.py               # Thread fork + ancestry queries
├── schema.sql                  # PostgreSQL + pgvector schema
├── pyproject.toml              # Python package configuration
├── requirements.txt            # Python dependencies
├── run.py                      # Server entry point
├── Makefile                    # Setup/run/test shortcuts
└── frontend/
    ├── app.html                # Legacy single-file web frontend
    └── app/                    # React frontend (Vite + TypeScript)
        ├── src/
        │   ├── components/     # 27 React components
        │   ├── hooks/          # WebSocket hook with reconnection
        │   ├── stores/         # Zustand state management
        │   ├── lib/            # API client
        │   ├── types/          # TypeScript types matching backend
        │   └── styles/         # Design system (40+ CSS tokens)
        └── package.json
```

## Environment Variables

| Variable | Required | What it does |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection (e.g., `postgresql://localhost/dialectic`) |
| `ANTHROPIC_API_KEY` | Yes | Claude API key — the primary LLM |
| `OPENAI_API_KEY` | No | GPT fallback + vector embeddings for semantic search |
| `REDIS_URL` | No | Redis for multi-server WebSocket broadcasting |
| `PORT` | No | Server port (default 8000, we use 8002) |
| `PRODUCTION` | No | Set to `1` for multi-worker mode |
| `WEB_CONCURRENCY` | No | Number of uvicorn workers in production |
| `ALLOWED_ORIGINS` | No | CORS allowed origins (comma-separated) |
| `JWT_SECRET_KEY` | No | JWT signing secret (auto-generated if not set) |

## How It Works Under the Hood

### Event Sourcing
Every state change — message sent, memory created, thread forked, protocol invoked — is an immutable event in an append-only log with JSONB payloads. The `events` table is the source of truth. Everything else (messages, memories, threads) is derived state. This is what makes replay, time travel, and temporal queries possible.

### The Interjection Engine
The AI doesn't just respond when asked. It evaluates 8 heuristics after every human message:
1. **Explicit mention** (@claude) — always respond
2. **Turn threshold** — 4+ human turns without AI → probably should speak
3. **Question detection** — someone asked a question nobody answered
4. **Information gap** — the AI has relevant memories that haven't been surfaced
5. **Semantic novelty** — the topic just shifted significantly → switch to provoker mode
6. **Stagnation** — short, repetitive messages → provoke with something new
7. **Speaker imbalance** — one person is dominating → engage the quiet one
8. **Silence logging** — even when it doesn't speak, it logs what it considered (for future analysis)

### The Prompt Stack
The system prompt is assembled in layers:
```
BASE_IDENTITY (or FACILITATOR_IDENTITY during protocols)
  → Evolved Identity (per-room, built over time)
    → User Models (per-participant thinking profiles)
      → Protocol Instructions (if a protocol is active)
        → Room Context (ontology + rules)
          → Participant Preferences (aggression, metaphysics tolerance)
            → Relevant Memories (semantic search, max 20)
              → Cross-Session Context (memories from other rooms)
```

### Vector Memory
Memories have 1536-dimensional embeddings (OpenAI text-embedding-3-small). When the AI prepares to respond, it doesn't dump all memories into the prompt — it runs a semantic search against the current message to find the 20 most relevant ones. Memories can be room-scoped, user-scoped, global, or LLM-authored.

### Knowledge Graph
The system stores graph relationships implicitly: memory references link memories across rooms, thread forks create genealogy, messages reference other messages. A materialized view unifies these into a queryable graph. Concept maps, provenance tracing, and contribution analysis are all reads over existing data.

## The Tech Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, uvicorn
- **Database**: PostgreSQL with pgvector extension
- **LLM**: Anthropic Claude (primary), OpenAI GPT (fallback), with provider abstraction
- **Embeddings**: OpenAI text-embedding-3-small (1536-dim)
- **Frontend**: React 18 + TypeScript + Vite (new), single-file HTML (legacy)
- **State**: Zustand (frontend), PostgreSQL event log (backend)
- **Real-time**: WebSocket with room-based broadcasting
- **Scaling**: Optional Redis pub/sub for multi-server
- **Auth**: JWT with Argon2 password hashing
- **Search**: PostgreSQL tsvector full-text + pgvector semantic

## License

MIT
