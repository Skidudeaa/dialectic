# CLAUDE.md

## What This Is

Dialectic — a collaborative dialogue engine where two humans and an LLM co-reason in real time. The LLM is a participant (not an assistant): it decides when to speak, challenges when you're lazy, synthesizes when you're stuck. Built for Amo and Dan's trading room — the LLM sees the live thesis state from tradingDesk and reasons about positions, triggers, and risk alongside them.

## Quick Start

```bash
# Run the server (port 8002 — port 8000 is reserved)
PORT=8002 python dialectic/run.py

# Serve the frontend (separate terminal) — the React app is the ONLY live
# frontend; legacy frontend/app.html and frontend/index.html are retired.
cd dialectic/frontend/app && npm run dev   # http://localhost:3000

# Production: https://dialectic.somacura.org (nginx serves the built app from
# /var/www/dialectic-current; deploy = release dir + symlink flip, see memory)

# Database setup (first time only)
createdb dialectic
psql dialectic < dialectic/schema.sql

# Run tests
cd dialectic && python3 -m pytest tests/ -q
```

## Required Environment Variables

```bash
export DATABASE_URL="postgresql://localhost/dialectic"
export ANTHROPIC_API_KEY="sk-ant-..."
export JWT_SECRET_KEY="<32+ char secret>"

# Optional: enables LLM fallback + vector embeddings
export OPENAI_API_KEY="sk-..."
```

These can live in `dialectic/.env` (auto-loaded by `run.py` via python-dotenv). The `.env` file is gitignored — never commit it.

## Architecture

### Core Modules

| Module | Purpose |
|---|---|
| `api/main.py` | FastAPI server, REST endpoints, WebSocket handler |
| `llm/orchestrator.py` | Central coordinator for all LLM interactions |
| `llm/heuristics.py` | Interjection decision engine (question/turn/novelty/stagnation) |
| `llm/prompts.py` | Layered system prompt: identity + room rules + memories + thesis state |
| `llm/trading_curator.py` | Offline alert engine — fires when snapshot arrives, user is away |
| `llm/self_model.py` | LLM self-awareness: tracks participation decisions, evolves identity doc |
| `memory/manager.py` | Three-lane recall (dense + FTS + entity/speaker, RRF-fused) + versioned room memories + write-path dedup |
| `api/notifications/` | Dual-channel push: Web Push/VAPID (`webpush.py`, the live channel for the installed PWA) + Expo (dormant until a native app ships) |
| `transport/handlers.py` | WebSocket message routing; coordinates annotator + primary LLM |
| `transport/websocket.py` | WebSocket connection lifecycle |
| `models.py` | Pydantic data models for all entities |

### Trading Integration

tradingDesk pushes thesis graph state to `POST /rooms/{room_id}/trading/snapshot`. On each push:
1. Snapshot stored as JSONB in `rooms.trading_config`
2. Formatted summary upserted as `thesis_state_current` room memory (searchable)
3. `TRADING_SNAPSHOT_RECEIVED` event logged
4. If any member is offline: `TradingCuratorEngine` generates a context annotation
5. Connected clients receive `trading_update` WebSocket event

The thesis state is injected into every LLM system prompt via `_build_trading_context()` in `llm/prompts.py`. The LLM sees: cascade phase, fired/approaching nodes, confluence scores, countdowns, scenario probabilities, and portfolio summary.

**Live trading rooms:**

| Room | ID | Thesis |
|---|---|---|
| Iran/Hormuz Trading Room | `56ba2f1e-5c70-4290-a77d-52404f0095da` | Oil shock cascade |
| Trump Tariffs Trading Room | `8adcabb7-817a-4802-87c6-3bfd42e6a9eb` | Tariff escalation |

**Push command** (from tradingDesk):
```bash
python3 tools/bridge/run-all.py   # pushes all active theses
```

### LLM Pipeline

Two paths run concurrently on each human message:

1. **Annotator path** (always, when other user is offline): `AnnotatorEngine` → `Haiku` → structured context annotation ("Connected to / Tension detected / For when Dan returns")
2. **Primary LLM path** (heuristic-gated): `InterjectionEngine` decides whether to speak → `Sonnet` → streamed response with full thesis context

The annotator fires even when the primary LLM fires — both produce messages. The annotator provides context for the offline user; the primary LLM answers the online user's live question.

### Key Design Patterns

- **Event sourcing**: All state changes in `events` table (append-only)
- **Heuristic interjection**: LLM speaks on: `@llm` mention, 4+ turns, question detected, semantic novelty, stagnation
- **Two LLM modes**: `llm_primary` (Sonnet, equal participant) and `llm_provoker` (Haiku, destabilizer)
- **Self-model**: LLM extracts its own positions post-response, builds identity doc + per-user model in memories
- **Three-lane recall**: memory search fuses dense vectors (pgvector, 1536-dim OpenAI), Postgres FTS, and an entity/speaker lane via reciprocal rank fusion — "what did Dan say about X" ranks Dan's memories. Memories carry `speaker_user_id` (whose statement, not who saved it), shown in the LLM prompt.
- **Write-path dedup**: `add_memory` runs cosine + trigram passes; a same-speaker restatement supersedes the old fact (status `superseded`, validity window closed, `MEMORY_SUPERSEDED` event), cross-speaker confirmation keeps the original. System-managed slots (identity docs, protocol synthesis, thesis state) opt out with `dedup=False`. Ported from the verified July 2026 agent-memory research (`docs/research/agent-memory-2026-07/`).

## Database

PostgreSQL with pgvector. Key tables: `rooms`, `threads`, `messages`, `memories`, `events`, `user_presence`, `llm_decisions`, `room_memberships`.

Apply migrations in order when setting up a new DB:
```bash
psql dialectic < schema.sql
psql dialectic < migrations/001_llm_self_model.sql
psql dialectic < migrations/002_add_trading_config.sql
```

`schema.sql` is the fresh-database baseline and already contains 002, 003, 004
and cross_session_memories. **Existing** databases need later migrations applied
explicitly — e.g. `psql dialectic < migrations/004_session_revoked_reason.sql`
(adds `user_sessions.revoked_reason`; applied to the live DB 2026-07-25).
Migration 006 (`006_memory_recall_lanes.sql`: pg_trgm, `speaker_user_id`,
FTS/trigram indexes, supersession columns) applied to the live DB 2026-08-08;
the `schema.sql` baseline includes it.

## File Structure

```
dialectic/
├── CLAUDE.md               # this file
├── README.md               # user-facing overview
├── run.py                  # server entry point (loads .env, starts uvicorn)
├── models.py               # Pydantic models for all entities
├── operations.py           # thread ancestry queries (CTE)
├── schema.sql              # full DB schema
├── requirements.txt        # Python dependencies
├── .env                    # secrets — gitignored
├── api/
│   ├── main.py             # FastAPI app, all endpoints (~1400 lines)
│   ├── token_utils.py      # room token extraction (header + query param)
│   └── auth/               # JWT auth endpoints
├── llm/
│   ├── orchestrator.py     # LLM coordinator (streaming + non-streaming)
│   ├── heuristics.py       # interjection decision engine
│   ├── prompts.py          # system prompt assembly + thesis context injection
│   ├── trading_curator.py  # offline trading alerts
│   ├── self_model.py       # LLM self-awareness + user models
│   ├── annotator.py        # async context annotations
│   └── providers.py        # Anthropic + OpenAI API wrappers
├── memory/
│   └── manager.py          # memory CRUD + vector search
├── transport/
│   ├── handlers.py         # WebSocket message dispatch
│   └── websocket.py        # connection lifecycle
├── frontend/
│   ├── app/                # React (Vite + TS) SPA — the live frontend (PWA)
│   └── app.html            # RETIRED single-file SPA (kept for history only)
├── migrations/             # incremental DB changes
└── tests/                  # pytest test suite (299 tests)
```

## Project Conventions

- Python 3.12, async/await throughout
- asyncpg for DB with JSONB codec registered on pool init
- All LLM calls through `ModelRouter` (retry, fallback, provider abstraction)
- JSONB columns: pass dict directly to asyncpg — pool codec handles serialization
- Message role alternation: Anthropic API requires last message to be `user` role — `prompts.py` strips trailing assistant messages before API call
- Tests: pytest + pytest-asyncio, 299 tests, incl. real-Postgres integration tests (test_memory_recall_pg.py needs `createdb dialectic_test && psql dialectic_test -f schema.sql`; skips cleanly without it)
