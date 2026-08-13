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

Feature flags (optional, all default ON): `SCHEDULER_ENABLED`,
`NIGHT_SHIFT_ENABLED` (7am CT brief), `PARTICIPATION_SWEEP_ENABLED` (60s
silence follow-ups), `DIALECTIC_TOOLS_ENABLED`, `DIALECTIC_VISION_ENABLED`,
`COMMITMENT_DETECTION_ENABLED` (implicit "I bet…" → proposal cards).
`SIGNUPS_ENABLED` must stay `0` — invite-only since the auth bridge.

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
| `llm/participation_fsm.py` | Conversation state machine (engaged/awaiting-human/question-pending/ignored/dormant) + StateSource confidence tiers; ported from cc-sidecar's reducer |
| `llm/silence_sweep.py` | 60s scheduler job: one capped follow-up when a question goes unanswered (10min, 3/day, quiet 23:00–07:00 CT) |
| `llm/briefing.py` | Shared morning-brief builder (endpoint + night-shift job) |
| `llm/night_shift.py` | `morning_brief` job registration — posts + pushes per room 07:00 America/Chicago |
| `llm/tool_loop.py` + `llm/tools.py` | Anthropic tool loop + 15-tool registry (read-only + proposal-shaped `draft_prediction`/`propose_thesis`/`save_reading`); wired on streaming AND non-streaming paths (provoker/protocol/annotator never). `read_article` fetches article bodies via the defuddle sidecar (`defuddle_service/`, client `llm/defuddle_client.py`) |
| `llm/reading.py` + `api/reading_relay.py` | The reading library (`reading_items`, migration 014): human-Accept filing of articles, full-text `search_reading`, memory twin (key `reading:<domain>-<slug>`, dedup=False) so three-lane recall finds readings unchanged. `is_thin()`/`THIN_CONTENT_MIN_WORDS` (80) is the one thin-content policy every filing path shares — bot-blocked shells and cookie walls are skipped before the LLM call, in both `news_night` and `wire` |
| `llm/claim_check.py` | Claim check: human messages linking an article get a fire-and-forget defuddle fetch + Haiku verdict; only `mixed`/`misrepresented` lands a `metadata.claim_check` badge (metadata patch + MESSAGE_METADATA), every failure path silent. Env `CLAIM_CHECK_ENABLED`, default on |
| `llm/news_night.py` | `thesis_news_digest` job (05:30 America/Chicago, `NEWS_DIGEST_ENABLED`, default off): per linked room, defuddles fresh GDELT headlines (cap 3/room), Haiku-distills against the thesis snapshot, files to the reading library (source `night_shift`); the 07:00 brief renders them as "📰 Read overnight" |
| `llm/research.py` | Research mode: the composer's Research button sends a `deep_dive` WS message → the standard registry under a long ToolLoop (15 iterations / 300s vs the usual 5/60), progress on the ordinary llm_* events, brief persisted as llm_primary with `metadata.source='deep_dive'` + hoisted proposals; one active dive per room, env `DEEP_DIVE_ENABLED` (ships on, `.env.example` carries 0) |
| `llm/wire.py` | `wire_watch` job (15 min, `WIRE_ENABLED`, default off): per linked room, Haiku-scores fresh GDELT articles against the live thesis (threshold 0.7, cap 2/run); hits are filed to the reading library (source `wire`) AND posted as a facilitator interjection via `force_response` (reason `wire_interjection`, cap 4/room/day, quiet hours + `auto_interjection_enabled` honored) |
| `llm/prediction_watch.py` | `prediction_deadline_watch` job (hourly, `PREDICTION_WATCH_ENABLED`, default off): due logged predictions (linked only — the room is found via `linked_book_id`) get thesis-news evidence + one Haiku verdict, posted as an annotator `resolution_proposal` card (cap 3/run, dedup on prediction id); the human's tap relays the verdict through `api/prediction_relay.py` resolve-accept |
| `llm/reading_echo.py` | `reading_echo` job (30 min, `READING_ECHO_ENABLED`, default off): new `reading_items` are Haiku-checked against OTHER active thesis-holding rooms (cap 3/reading); a hit posts one annotator note (`metadata.source='reading_echo'`, dedup on (room, url), cap 6/room/day) + a cross-session memory reference from the origin reading's twin — a citation, never a copy; the cross_session auto-injection gate is untouched |
| `llm/thesis_drafter.py` | Claude drafts a thesis's causal DAG (builder-format, validated, one retry); consumed by the stateless draft endpoint in `api/thesis_relay.py` |
| `api/prediction_relay.py` | Human-Accept relay: proposal in message metadata → POST to tradingDesk on the tap |
| `scheduler.py` | asyncio job scheduler — advisory lock, `scheduled_job_runs` ledger, interval buckets + wall-clock daily slots (`daily_at`/`daily_tz`) |
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

**Creating a thesis from a room**: the trading panel's empty state offers a
Create Thesis form → `POST /rooms/{room_id}/trading/thesis`
(`api/thesis_relay.py`): registers the room token on td's bridge (runtime
file, no desk restart), creates the book on td born bound via
`meta.dialecticRoomId` (named `*-graph` per convention), sets
`rooms.linked_book_id`, logs `THESIS_CREATED`. By default the form first
calls `POST .../trading/thesis/draft` — Claude drafts the cascade
(`llm/thesis_drafter.py`), the human reviews it phase-grouped in the
panel, and Accept carries it through create. The desk adopts the book at
runtime and runs its first cycle immediately, so the panel fills within
seconds. Refinement happens on the deep surface — the success state
deep-links into td's Builder.

**Retiring**: `DELETE /rooms/{room_id}/trading/thesis` — td unbinds first
(book survives, loses `dialecticRoomId` + push token via
`POST /api/bridge/room-unbind`), then dialectic clears `linked_book_id` +
`trading_config`, invalidates the `thesis_state_current` memory, logs
`THESIS_RETIRED`. The room can birth a successor immediately. Mid-argument,
the LLM can call `propose_thesis` (proposal-only) — the chat card seeds the
create form via `metadata.thesis_proposal`.

The thesis state is injected into every LLM system prompt via `_build_trading_context()` in `llm/prompts.py`. The LLM sees: cascade phase, fired/approaching nodes, confluence scores, countdowns, scenario probabilities, and portfolio summary.

**Live trading rooms** (all five thesis books bound as of 2026-08-09; the
binding lives in `rooms.linked_book_id` + each book's `meta.dialecticRoomId`):

| Room | ID | Thesis |
|---|---|---|
| Iran/Hormuz Trading Room | `56ba2f1e-5c70-4290-a77d-52404f0095da` | Oil shock cascade |
| Trump Tariffs Trading Room | `8adcabb7-817a-4802-87c6-3bfd42e6a9eb` | Tariff escalation |
| AI Capex Unwind Trading Room | `6805ad0f-0d72-441d-ac1c-2cd9dc63bca3` | AI capex unwind |
| China Property Cascade Trading Room | `e1ff2cca-04ed-4b50-8c38-c0df78520e21` | Property cascade |
| Japan Rate Shock Trading Room | `b9f3b9d2-1d00-4179-957b-284b7cd4a8ad` | Rate shock |

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
the `schema.sql` baseline includes it. Migrations 012 (personal memory
promotions) and 013 (Home Base: `rooms.is_home`, `can_manage_home`, the
singleton Home bootstrap) are applied to the live DB; `013` is current.

**Home Base (2026-08-12)**: one real `is_home` room is every founder's
default landing. `home_activity.py` builds the membership-intersection
activity projection (one service feeds `GET /users/me/home/activity` AND
Claude's `## Shared Home Activity` prompt layer, 2s budget, explicit
unavailable marker). `api/home.py` is the only membership door
(candidate→confirm add, nondelegable `can_manage_home`); the generic join
refuses Home; thesis create/draft/propose return 409 in Home. Frontend:
`hooks/useRoomNavigation.ts` is the ONE URL-authoritative navigation
transaction (bare `/` = Home root; explicit `?room=`/`&thread=` URLs win;
popstate is history-neutral), `components/home/` holds the pulse + settings,
`BranchTree` renders genealogy in rail and Branches panel alike. Founder
activation (`deploy/activate_home_founders.sql`) and member removal
(`deploy/remove_home_member.sql`) are reviewed operator scripts — never UI.

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
└── tests/                  # pytest test suite (913 tests)
```

## Project Conventions

- Python 3.12, async/await throughout
- asyncpg for DB with JSONB codec registered on pool init
- All LLM calls through `ModelRouter` (retry, fallback, provider abstraction)
- JSONB columns: pass dict directly to asyncpg — pool codec handles serialization
- Message role alternation: Anthropic API requires last message to be `user` role — `prompts.py` strips trailing assistant messages before API call
- Tests: pytest + pytest-asyncio, 913 tests, incl. real-Postgres integration tests (test_memory_recall_pg.py needs `createdb dialectic_test && psql dialectic_test -f schema.sql`; skips cleanly without it)
