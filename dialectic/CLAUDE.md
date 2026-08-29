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
DATABASE_URL=postgresql://localhost/dialectic_test python3 -m pytest \
  tests/test_external_operations_pg.py \
  tests/test_message_ancestry_pagination_pg.py -q
cd ../trading && python3 -m pytest web/ tools/ -q
cd ../dialectic/frontend/app && npm test -- --run && npm run lint && npm run build
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
`COMMITMENT_DETECTION_ENABLED` (implicit "I bet…" → proposal cards),
`CAIRN_TOOLS_ENABLED` (the cairn dev-memory tool group).
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
| `llm/tool_loop.py` + `llm/tools.py` | Anthropic tool loop + 19-tool registry (read-only + proposal-shaped `draft_prediction`/`propose_thesis`/`save_reading`); wired on streaming AND non-streaming paths (provoker/protocol/annotator never). `read_article` fetches article bodies via the defuddle sidecar (`defuddle_service/`, client `llm/defuddle_client.py`); the 4-tool cairn dev-memory group (`search_dev_sessions`/`recent_dev_activity`/`get_dev_session`/`search_dev_insights`) reads Amo's passive dev-session memory via `llm/cairn_client.py` (`CAIRN_URL`, group flag `CAIRN_TOOLS_ENABLED`, safe to omit — a down cairn is an is_error tool result, never a dead turn) |
| `llm/reading.py` + `api/reading_relay.py` | The reading library (`reading_items`, migration 014): human-Accept filing of articles, full-text `search_reading`, memory twin (key `reading:<domain>-<slug>`, dedup=False) so three-lane recall finds readings unchanged. `is_thin()`/`THIN_CONTENT_MIN_WORDS` (80) is the one thin-content policy every filing path shares — bot-blocked shells and cookie walls are skipped before the LLM call, in both `news_night` and `wire` |
| `llm/claim_check.py` | Claim check: human messages linking an article get a fire-and-forget defuddle fetch + Haiku verdict; only `mixed`/`misrepresented` lands a `metadata.claim_check` badge (metadata patch + MESSAGE_METADATA), every failure path silent. Env `CLAIM_CHECK_ENABLED`, default on |
| `llm/news_night.py` | `thesis_news_digest` job (05:30 America/Chicago, `NEWS_DIGEST_ENABLED`, default on): per linked room, defuddles fresh GDELT headlines (cap 3/room), Haiku-distills against the thesis snapshot, files to the reading library (source `night_shift`); the 07:00 brief renders them as "📰 Read overnight" |
| `llm/research.py` | Research mode: the composer's Research button sends a `deep_dive` WS message → the standard registry under a long ToolLoop (15 iterations / 300s vs the usual 5/60), progress on the ordinary llm_* events, brief persisted as llm_primary with `metadata.source='deep_dive'` + hoisted proposals; one active dive per room, env `DEEP_DIVE_ENABLED` (ships on, `.env.example` carries 0) |
| `llm/wire.py` | `wire_watch` job (15 min, `WIRE_ENABLED`, default on): per linked room, Haiku-scores fresh GDELT articles against the live thesis (threshold 0.7, cap 2/run); hits are filed to the reading library (source `wire`) AND posted as a facilitator interjection via `force_response` (reason `wire_interjection`, cap 4/room/day, quiet hours + `auto_interjection_enabled` honored) |
| `llm/prediction_watch.py` | `prediction_deadline_watch` job (hourly, `PREDICTION_WATCH_ENABLED`, default on): due logged predictions (linked only — the room is found via `linked_book_id`) get thesis-news evidence + one Haiku verdict, posted as an annotator `resolution_proposal` card (cap 3/run, dedup on prediction id); the human's tap relays the verdict through `api/prediction_relay.py` resolve-accept |
| `llm/reading_echo.py` | `reading_echo` job (30 min, `READING_ECHO_ENABLED`, default on): new `reading_items` are Haiku-checked against OTHER active thesis-holding rooms (cap 3/reading); a hit posts one annotator note (`metadata.source='reading_echo'`, dedup on (room, url), cap 6/room/day) + a cross-session memory reference from the origin reading's twin — a citation, never a copy; the cross_session auto-injection gate is untouched |
| `llm/thesis_drafter.py` | Claude drafts a thesis's causal DAG (builder-format, validated, one retry); consumed by the stateless draft endpoint in `api/thesis_relay.py` |
| `api/prediction_relay.py` | Human-Accept relay: proposal in message metadata → POST to tradingDesk on the tap |
| `api/external_operations.py` | Migration 018 operation leases for prediction, resolution, reading, and thesis acceptance. Claims/finalizes use short PostgreSQL transactions; stable operation keys cross the external boundary; succeeded retries replay the recorded result; the original initiating user owns the acceptance stamp. No relay holds a database connection during HTTP or model work. |
| `scheduler.py` | asyncio job scheduler — advisory lock, `scheduled_job_runs` ledger, interval buckets + wall-clock daily slots (`daily_at`/`daily_tz`) |
| `memory/manager.py` | Three-lane recall (dense + FTS + entity/speaker, RRF-fused) + versioned room memories + write-path dedup |
| `api/notifications/` | Dual-channel push: Web Push/VAPID (`webpush.py`, the live channel for the installed PWA) + Expo (dormant until a native app ships) |
| `workspace_objects.py` + `api/workspace.py` | The workspace-object projection (design v2 §8.1): seven read-only adapters — readings, research briefs, the thesis, commitments, proposals, dossier entries, the Record — plus `workspace_object_from_movement` reusing the House's own movement. **Adapters, not a table**: no new storage, no writes, and `available_actions` describes what a surface may offer without performing it. Two entities carry a memory TWIN that must fold into one object, never render twice: a reading and its `reading:<domain>-<slug>` memory (paired through `llm.reading._reading_key`, the writer's own function), and a thesis and its `THESIS_STATE_MEMORY_KEY` slot. `GET /rooms/{id}/workspace/objects` is read-only by construction — the router carries no write route, and every write stays with the entity that owns it |
| `proposal_envelope.py` | The unified proposal envelope (design v2 §8.3–8.4) over the FIVE proposal shapes already in `messages.metadata` (`proposal`, `thesis_proposal`, `reading_proposal`, `commitment_proposals[]`, `resolution_proposal`). Normalizes kind, status and the action a surface may offer; writes nothing and leaves every relay untouched. Status is derived from the room — a passed deadline or a bound book is `expired`, an article the wire already filed is `superseded` (never `failed`, which has no row at all: a relay failure deliberately leaves `accepted` false so a retry is fresh). `PROPOSAL_SLOTS` is the one slot→kind table, shared with the frontend and pinned by a contract test; `workspace_objects.proposals()` projects these envelopes rather than re-reading metadata. `acceptance_stamp()` + `ACCEPT_SLOT_SQL`/`ACCEPT_LIST_ITEM_SQL` are what every accept path writes — `accepted_by`/`accepted_at` recorded in the same patch as `accepted` (§9.3), so no proposal can be accepted by nobody |
| `transport/handlers.py` | WebSocket message routing; coordinates annotator + primary LLM |
| `transport/websocket.py` | WebSocket connection lifecycle |
| `models.py` | Pydantic data models for all entities |

### World Synapse

World Lens is an embodiment of Dialectic evidence, not a separate globe app.
Atlas House and World are available inside an ordinary room and share the one
URL-authoritative `room` / `scene` / `view` / `object` navigation transaction
with Field and Focus. Switching House/World preserves the selected object;
changing rooms deliberately clears the prior object and camera.

`GeoScope` remains append-only geographic authority. Enhanced Atlas projects
each live scope with its immutable `lineage_root_id`, so a root, historical
revision, current redraw, or causal Field mark resolves to the same current
geometry without client-side lineage inference. `field_marks.py` owns the
shared bounded `CausalGeoBinding` DTO; enhanced Atlas, Field, Focus, scope
review, and participant `world_query` consume that same identity and semantic
relation. Default Atlas remains the four-key source-compatible projection.

Causal meaning is rendered as explicit DOM text (`scope -> relation -> thesis
node -> review state`) and never as a geographic ray. A map connector is
allowed only when both endpoints are accepted geographic coordinates; a
scope-to-thesis relationship is semantic evidence, not measured geography.
The text-first scope list is authoritative even when Cesium cannot start: it
keeps provider, acquisition, source ID, exact URL, and credit visible beside
each scope rather than relying on globe-owned attribution or interaction.
React's dynamic `WorldView` import owns the complete Cesium dependency graph;
the production build fails if the app shell eagerly imports/module-preloads it
or if the service worker precaches WorldView JS/CSS. Do not reintroduce a
manual Cesium chunk without proving those emitted-artifact contracts.

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
- **Three-lane recall**: memory search fuses dense vectors (pgvector, 1024-dim Voyage `voyage-4-large`; OpenAI 1536 remains the fallback provider when `VOYAGE_API_KEY` is unset — changing provider means a column migration AND a full re-embed, since the two live in different vector spaces), Postgres FTS, and an entity/speaker lane via reciprocal rank fusion — "what did Dan say about X" ranks Dan's memories. Memories carry `speaker_user_id` (whose statement, not who saved it), shown in the LLM prompt.
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

**Amended 2026-08-13:** `013` is no longer current — **`016` is.** Verified by
querying the live DB rather than reading the migrations directory: `reading_items`
resolves (014 `reading_library` applied) and `memories.embedding` has typmod 1024
(016 `voyage_embeddings` applied); 015 is `room_watchlist`. Because 014 shipped
after the baseline was cut, **`reading_items` is not in `schema.sql`** — a fresh
DB needs the migration run, not just the baseline. The line above stays for the
history of when 012/013 landed.

**Amended 2026-08-16:** **`018_external_operations.sql` is the current source
migration.** It adds the lease ledger used to make external acceptance retries
idempotent and attributable. Apply it explicitly to existing databases before
activating this code. The local stabilization gate applied it only to
`dialectic_test`; production migration state is unchanged.

**Home Base (2026-08-12)**: one real `is_home` room is every founder's
default landing. `home_activity.py` builds the membership-intersection
activity projection (one service feeds `GET /users/me/home/activity` AND
Claude's `## Shared Home Activity` prompt layer, 2s budget, explicit
unavailable marker). `api/home.py` is the only membership door
(candidate→confirm add, nondelegable `can_manage_home`); the generic join
refuses Home; thesis create/draft/propose return 409 in Home. Frontend:
`hooks/useRoomNavigation.ts` is the ONE URL-authoritative navigation
transaction (explicit `?room=`/`&thread=`/`?scene=` URLs win; a bare `/`
restores the window's last room/branch/scene via `lib/sceneContinuity`, or
opens Home when there is nothing stored; popstate is history-neutral), `components/home/` holds the pulse + settings,
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
└── tests/                  # pytest suite, including real-Postgres tests
```

## Project Conventions

- Python 3.12, async/await throughout
- asyncpg for DB with JSONB codec registered on pool init
- All LLM calls through `ModelRouter` (retry, fallback, provider abstraction)
- JSONB columns: pass dict directly to asyncpg — pool codec handles serialization
- Message role alternation: Anthropic API requires last message to be `user` role — `prompts.py` strips trailing assistant messages before API call
- Tests: pytest + pytest-asyncio, including real-Postgres integration tests.
  A skipped PostgreSQL test is not proof: initialize `dialectic_test`, apply
  migrations through 018, and run the named PostgreSQL commands from Quick Start.

## Amendment 2026-08-15 — the volume controls (amend-beside)

Measured, not guessed: over 2026-08-08..15 the room ran **104 human messages
against 214 machine ones — 2.06 machine messages per human turn**. Four causes,
each traced to a value rather than to config, each fixed. Suite 1327.

- **The annotator was the largest single source and the engine never saw it.**
  122 of the 214. `should_annotate` required only "no other human online",
  which in a two-person room is near-permanent, so it wrote one note per
  message. Capped at `ANNOTATOR_DAILY_CAP`, counted from `messages` joined
  through `threads` — the annotation's own row is the ledger, so the cap needs
  no new plumbing (`wire._interjections_today` pattern). **Note `messages` has
  no `room_id`** — it is reachable only via `threads`. **The cap turned out not
  to be the fix** — see the second amendment below.
- **`semantic_novelty_threshold` 0.70 → 0.85** (`INTERJECTION_NOVELTY_THRESHOLD`).
  At 0.70 it was not detecting a spike, it was cutting one continuous
  distribution in half: rows that stayed silent ran 0.32–0.69 (mean 0.56),
  rows that fired ran 0.71–1.00, no gap, 26 of 28 firings hugging the line.
  Largest driver inside the engine (28 of 71 speaks).
- **`_detect_speaker_imbalance` now needs 3+ speakers**
  (`INTERJECTION_BALANCE_MIN_SPEAKERS`). It fired 13 times on windows of
  `{3,1}`, `{5,1}`, `{4,1}` — one person taking a couple of turns in a row.
  There is no quieter third party to redirect toward in a two-human room.
- **`self_model.py` queried `speaker_type = 'HUMAN'`; the stored value is
  `'human'`** (`SpeakerType.HUMAN.value` — the uppercase form is the enum
  MEMBER name). The predicate matched zero rows unconditionally, so
  `human_responded` was pinned False for every measured decision and
  `engaged_count` never left zero. The identity distillation was built
  specifically to avoid LLM self-report and was reading an instrument that
  could only answer "ignored". **71 historical rows were repaired** from the
  same 3-message window: 52 true / 19 false, i.e. **73% of the participant's
  contributions did get a reply**, recorded as 0%. Backup at
  `/root/llm_decisions_effectiveness_backup_2026-08-15.csv`.

**Shape, unfixed and deliberately so:** every rung of `InterjectionEngine.decide`
votes only YES — first match returns immediately and nothing can argue for
silence, which is reachable only by falling through all seven. Every reason
except `no_trigger` fired 100% of the time it was reached, and `confidence` is
recorded after the decision rather than used to make it. **The thresholds are
the only volume control this engine has.** Re-shaping the ladder so it can weigh
a case for silence is the real fix and was not attempted here.

Still outstanding from the same measurement: `_schedule_effectiveness_measurement`
is a fire-and-forget `asyncio.sleep(30)` task with no retry, so a restart inside
the window loses the row (the 27 remaining NULLs are legitimate — they are the
`no_trigger` silences, which say nothing and so have nothing to measure).
`human_responded` is a pure function of `messages` and would be better derived
at read time than snapshotted on a timer.

## Amendment 2026-08-15 (later) — the annotator worth gate (amend-beside)

The cap shipped above was the wrong instrument and the measurement says so:
against the same week, **`ANNOTATOR_DAILY_CAP=12` would have cut 2 of 126
annotations.** The volume was never spikes — it was a steady 8-14/room/day
baseline from annotating every message. A ceiling cannot fix a baseline.

**`should_annotate` → `prepare_annotation`**, which returns the recalled context
to build the annotation from, or `None` to stay silent. Gate and material are
one decision, so "annotate" and "have something to say" cannot come apart — a
non-`None` return is always a NON-EMPTY list.

Four conditions in ascending cost, so the expensive one runs last:
nobody else online → under the daily ceiling → **the message has substance** →
**recall finds something to connect**.

**Why recall is the right gate:** it is the annotator's own job description.
CONNECT and SURFACE both presuppose something to connect to, and `annotate()`
was already running that search — so the gate reads a signal the feature was
computing anyway, and `annotate(related=...)` takes it forward instead of
paying for the embedding twice.

Measured over the 104 human messages of 2026-08-08..15:

| | messages | |
|---|---|---|
| below the substance floor | 15 (14%) | acknowledgements — cut before recall runs |
| recall returns nothing | 34 | nothing to connect |
| **≥1 hit — the default gate** | **55 (53%)** | roughly halves annotation volume |
| ≥2 hits | 43 (41%) | `ANNOTATOR_MIN_MEMORY_HITS=2` for a stricter room |

`≥1` self-scales with the room rather than imposing a quota: the room holding
422 memories annotates often, the one holding 5 stays quiet, and that is the
feature behaving correctly. A question earns a breadcrumb at any length — "why?"
is below the 25-char floor and passes anyway. **Recall failure is treated as
stay-silent**, not annotate-blind: a degraded lane must not become noise.

Live cap is `5` in `.env` as an agreed stopgap from before the gate landed.
Now that both are live they stack, and 5 will do cutting the gate was meant to
do — relax toward 12 after observing a few days, or the gate's real effect
stays invisible.

## Amendment 2026-08-15 (Home) — the gathering room, and the dead end behind it

Home was created 2026-08-12 for exactly what it sounds like: *"the humans want
a place to gather, so general talk doesn't get lost in teh individual
threads."* It held 18 messages and went quiet on the 14th. The transcript says
why — on the 13th, *"claude lets make a thesis on this"*, which Home cannot
answer. `thesis_relay.py:93` returns 409 *"Propose it in the scheme's room"*,
`scenesForDestination` gives Home root no Bench, so the tap on a proposed
thesis resolved to the default scene and did nothing at all.

**The doctrine is kept — Home coordinates, scheme rooms own scheme work. What
changed is that Home now MAKES the scheme's room instead of naming it as
somewhere you must go.**

- **`POST /users/me/home/schemes`** (`api/home.py`) creates the room and
  carries every Home member into it in ONE statement. Authorization lives
  inside the CTE: its first term joins the caller's Home membership, so a
  non-member matches no Home and every downstream insert writes nothing —
  same 404 shape as the activity projection, which must not reveal whether
  Home exists. The thesis is NOT created here; the human still reviews the
  drafted cascade in the new room's Bench.
- **`POST /rooms` writes ZERO `room_memberships`** — it takes no caller
  identity at all. That is why `8adcabb7 Trump Tariffs Trading Room` is bound
  to a live book with **0 members**, and why `T123` / `firstRoom!` and the
  rest have none. The spawn's membership insert is therefore not a follow-up
  step that could fail separately; it is in the same statement as the room.
  **`messages` has no `room_id`** — reach it through `threads`.
- **The seed crosses a room boundary now.** `appStore.ts` clears `thesisSeed`
  on room switch deliberately, so `MessageBubble` no longer writes it; the
  seed travels as an argument to `onOpenBench` and `App.openThesisSeed` sets
  it only AFTER `navigate()` resolves. Do not hoist that.
- **The House renders the pulse `compact`.** It used to stack residents,
  needs, movement and every scheme door ahead of the transcript, so the
  default view of the shared room was a dashboard about the OTHER rooms.
  Movement and the doors live behind a `<details>`.
- **`ROOT_THREAD_TITLE`** (`api/thread_titles.py`, its own module so a router
  importing the app cannot close an import loop) replaces the literal
  `"Main"`, which was written in TWO places in `create_room` — the row and
  the `THREAD_CREATED` payload. Home's existing row was renamed; other rooms
  were deliberately left alone rather than rewriting history nobody asked to
  rewrite.
- **The morning brief stopped reading itself.** The brief posts as
  `llm_annotator` and `briefing.py`'s summary corpus had no `speaker_type`
  filter, so each night's brief summarized the previous night's. In Home —
  last window three annotator notes, zero human messages — it produced a
  brief addressed to nobody. The filter also stops `messages_missed` counting
  the machine's marginalia as messages a human missed, which gates
  night_shift's `quiet` branch and drives the push. `llm_primary` and
  `llm_provoker` stay: Claude is a participant.

Testing notes worth keeping: `idx_rooms_single_home` is a **partial unique
index**, so a fixture cannot invent a second Home — reuse the singleton.
`dialectic_test` is built from the `schema.sql` baseline and predates the auth
migrations, so it has **no `users.email`**. And `npx tsc --noEmit` at the app
root is **VACUOUS** — `tsconfig.json` carries `"files": []` with project
references only, so it checks nothing and exits 0; use `tsc -b`, which is what
caught a genuine missing import here.

Suites at this gate: backend 1340, frontend 252.

## Amendment 2026-08-15 (evening) — the curator's clock, and whose turn it is

Two more sources found by measuring the same week, both of the shape the
earlier amendments name: **a ceiling cannot fix a baseline**, and **the ladder
can only vote yes**.

- **A leftover interim timer was the loudest thing in the house.**
  `tradingdesk-bridge.timer` (`OnCalendar=*:00/30`, unit description:
  *"interim; removed when coordinator push deploys"*) was still running
  `tools/bridge/run-all.py` long after the coordinator's inline push shipped.
  Its payloads stamp **`v: 2`**, and `curator_plan` gives v1/v2 the legacy
  "alert on every receipt" branch — the v3 contract's whole point is that
  `alertEvents: []` means *nothing happened, stay quiet*. So the desk's own
  hourly v3 heartbeats were correctly silent while a redundant duplicate of
  them chattered every 30 minutes. **32 of the 35 curator alerts ever posted
  came in on v2; 3 on v3.** Timer stopped and disabled; the coordinator pushes
  all five books (9 heartbeats each that day) and is the only pusher needed.
- **The curator had no content gate at all** — `is_duplicate` is a 5/30-minute
  window and `CURATOR_DAILY_CAP` an 8/day ceiling, and a snapshot repushed
  every 30 minutes clears a clock by waiting. Japan Rate Shock took **21
  alerts in three days off one unchanged snapshot**, the model opening each
  one *"ALERT (19th confirmation — STALE, do not action)"* — it knew, and had
  no way to decline. `snapshot_fingerprint()` + `is_unchanged()` now compare
  the CAUSAL content (nodeStates, cascadePhase, countdowns, alertEvents)
  against the room's last curator alert. Deliberately excluded: `timestamp` /
  `revision` / `generatedAt` (change every push by construction, so hashing
  the payload would fingerprint the clock) and `marketSnapshot` (a fourth
  decimal place on usdJpy is not a reason to wake anyone). Compared against
  the LAST alert only, so a state that reverts and returns is news again.
  A pre-fingerprint alert reads NULL → "this is news": the opposite failure
  is a permanently muted trading room. Note the curator calls
  **`claude-sonnet-5`**, not the Haiku its docstring claims — those 21
  paragraphs were Sonnet calls.
- **`heuristics.decide` gained rung 0, the first rung that can decline.**
  A message that OPENS by addressing people who do not include us is not our
  turn. It has to outrank the explicit mention, because a message can name
  the participant while talking to someone else: *"@amo feature idea can you
  make it highlight the name … and make the @llm a different color"* fired
  rung 1 and got an answer that opened "This one's not for me to weigh in
  on." Being right about that in the reply is not the same as staying out of
  it. `llm/mentions.addresses_someone_else()` reads the **address block** —
  the leading run of `@handles` — and leaves everything else alone, so
  "hey @dialectic what do you think" still summons from mid-sentence.
  Measured over the week: **10 of 45** `@`-opening human messages. Inside the
  block a handle is ours if it *starts with* an alias (`@llmThe` — a real
  message, space lost to a fast thumb); erring toward speech is the safe
  direction for an address we misparse.

This is still not the re-shaping the earlier amendment asks for — rungs 1–7
remain yes-only. It is the one case where the room had already said whose
turn it was.

Suites at this gate: backend 1376 (1358 + 18), including six real-Postgres
contracts in `tests/test_trading_curator_pg.py` — the mocked curator tests
hand `fetchrow` a dict and so assert the shape of a query that never ran.

## Amendment 2026-08-15 — article walls and the Wire retry clock

- `defuddle.service` remains direct-first. A publisher HTTP 403 alone triggers
  one tracking-sanitized Jina Reader request inside the same 15-second budget;
  every network hop resolves and pins public addresses before a manual redirect
  can be followed. All consumers keep the existing article JSON contract.
  Pasted/model text is still not filing provenance. Keep Undici on its Node
  20-compatible major: the production unit runs `/usr/bin/node` 20.20.2.
- Wire cools extraction failures and thin shells for six hours in process
  memory, scans at most six fresh feed entries, and sends at most two readable
  articles to relevance scoring per room/run. Interactive retries ignore this
  cooldown.

## Amendment 2026-08-15 (late) — the dials were never connected

Owner, after the evening fix: *"whatever we adjusted the commentary threshold
limits aims in the 'main' thread, its not nearly tight enough."* Replaying the
week's **146 real `llm_decisions` rows** through the engine with each row's own
stored inputs (novelty, unsurfaced count, speaker balance) and the real message
stream up to the triggering message — only the rule under test varies:

| arm | speaks | of decisions |
|---|---|---|
| before this session (turn=4, novelty 0.70) | 67 | 46% |
| after the morning fix (turn=4, novelty 0.85) | 26 | 18% |
| **now** (turn=8, novelty 0.85, no stagnation) | **16** | **11%** |
| tightened further (turn=12) | 16 | 11% |

Tonight's Home window alone (41 decisions): 23 → 4.

- **`rooms.interjection_turn_threshold` and `rooms.semantic_novelty_threshold`
  reached NOTHING.** `decide()` accepted a `turn_threshold` parameter and read
  `self.turn_threshold` anyway; the orchestrator never passed one; and
  `InterjectionEngine()` is constructed with no arguments, so every room ran
  module defaults regardless of its row. The columns are stored, range-checked
  by `PATCH /rooms/{id}/config` (2–12 and 0.3–0.95), reported by
  `/auth/capabilities`, **and exposed as two sliders in
  `RoomSettingsDialog.tsx`** — "Turns before Dialectic considers joining" and
  "Topic-shift sensitivity". Dragging either did nothing. A dial that changes
  nothing is worse than no dial: it answers "we already turned that down" with
  a yes. The orchestrator already receives the whole `Room` object, so the fix
  is two arguments at the call site — the data was in hand the entire time.
- **Wiring them would have LOOSENED the rooms**, because every row said 0.70
  while `INTERJECTION_NOVELTY_THRESHOLD=0.85` was what actually ran. So the
  stored values were aligned to the shipped truth in the same step:
  `UPDATE rooms SET interjection_turn_threshold=8, semantic_novelty_threshold=0.85`
  (24 rows, one of which — a QA room — had been hand-set to 6 and had never
  taken effect), plus the `schema.sql` defaults and the `Room` model. **Run the
  UPDATE before the restart**: the ingest order is data, then code.
- **The stagnation rung is gone.** It never detected stagnation. Its docstring
  promised "short, repetitive messages"; the body tested one thing — six
  consecutive TEXT messages averaging under 100 characters — with no repetition
  test anywhere. That is ordinary chat, and all five production firings
  interrupted somebody TELLING A STORY in short beats ("I read about 2 Utah
  bro's who went to Zaire to stage a coup" / "They got caught and sentenced to
  death" / …). A sixth fired on "Dam even the AI be talking back" — the
  complaint about the noise produced more of it. `_detect_stagnation` is kept
  as a `return False` stub with the history, because a REAL stagnation detector
  (repetition, circling, no new entities) is a reasonable thing to want and
  this is where it goes. What it must not do is fire on brevity.
- **`INTERJECTION_TURN_THRESHOLD` 4 → 8.** This is the one rung with no content
  justification at all — it fires on turn COUNT. All 10 of its weekly firings
  were triggered by messages like `"Yes"`, `"N"`, `"Yep getting notification
  pushed to me"`. At 6 it fires zero times over the corpus; 8 keeps a safety
  valve without making the participant a metronome.

**What is left, and it is now the whole story:** `question_detected` is 9 of
the remaining 16 speaks. Rungs 1–7 still vote only YES. If the room wants
quieter than this, that rung is the next thing to look at — a question in a
two-human room is usually for the other human, and rung 0 only catches the ones
that say so with an `@`.

Suites at this gate: backend 1381.

## Amendment 2026-08-16 — legibility, the meta tag, and a Field a human can reach

Three asks from the room, and the finding that shaped all three: **most of
what was asked for already existed and was sitting outside the flow.**
Reconnaissance against the live DB, not the docs:

| capability | state before this work |
|---|---|
| `message_reactions` (table, pills, names, toggle) | **0 rows, ever** |
| `field_marks` confirm/contest + derived review state | 85 marks, **all `origin=inferred`, 0 human reviews ever** |
| `reading_items` (the Library) | 32 rows: `wire` 19, `night_shift` 13 — **0 human-filed** |
| mention rendering in the transcript | did not exist — `@amo` was plain text |
| `rooms.interjection_turn_threshold` / `.semantic_novelty_threshold` | stored, validated, sliders in the UI, **read by nothing** (fixed the night before) |

### Phase 1 — legibility (`865398d`)

- **`lib/mentions.ts`** decorates the SANITIZED DOM by walking text nodes, not
  by string-replacing HTML — a replace over markup lands inside an attribute
  eventually, and that is how a highlighter becomes an injection. Code and
  links are skipped; an unresolvable handle stays plain text.
- Three chip kinds: another human quiet, Dialectic amber, **you** teal and
  bolder. Not a walk-back of F1 — §16.4 forbids color encoding WHO IS
  SPEAKING; this encodes who a message is ADDRESSED TO. Weight and underline
  differ too, so the three survive grayscale.
- The **address line** (`→ Dan`) renders what rung 0 has parsed server-side
  since 2026-08-15 and never showed.
- **`GET /rooms/{id}/members`** is new and is why the @-picker works: every
  roster was `onlineUsers` + self, so a member who had never spoken and was
  not connected appeared nowhere — exactly the new third human.
  **Membership is not presence**; this route returns the former.
- The alias list now exists on both sides of the wire; `tests/test_mentions_contract.py`
  pins them by matching the Python STATEMENT, not prose about it.

### Phase 2 — the meta tag (`f6f4554`)

- `messages.metadata.tags`, fixed vocabulary `meta` / `bug` / `idea`,
  validated at the door by `proposal_intake.validate_tags`. **Not a Field
  relation**: `FIELD_RELATIONS` is the guard that stops `field_inference`
  minting relations, and product-meta is not a claim about the subject.
- **Tags ride the WS send, not the REST proposal door.** That door stores and
  logs but does **not broadcast and does not trigger the LLM** — routing a tag
  through it would make product notes invisible to everyone else.
- `GET /messages/search` grew `tag`, and `q` became **optional**: "everything
  filed under #bug" has no text to search for. One of the two is required.
- `tests/test_propose_surface_ws_door.py` asserted that door took NO client
  metadata; its docstring said a red there is a SIGNAL, not a regression to
  silence. Rewritten to the new narrower contract.

### Phase 3 — weight, votes, evidence (this commit)

- **`POST /rooms/{id}/field/marks`** — the Field's second write door, and the
  one it never had: a human can now ORIGINATE a mark, not only review one the
  inference engine proposed. The INSERT is the one correction replacements
  already used (`origin='explicit'`, `provenance='human'`).
  **`ON CONFLICT` repeats the partial index's own `WHERE dedup_key IS NOT
  NULL`** — Postgres raises `InvalidColumnReferenceError` rather than
  deduplicating otherwise. Mutation-proven.
- **The passage highlighter** anchors on `{entity, id, field}` where `field`
  is `quote:<occurrence>:<hash>`. This works only because
  `field_marks._subject_token` folds `field` into the dedup key — otherwise
  every highlight on one message would collide with the first. Anchors match
  on QUOTE TEXT, never offsets: messages are editable and markdown→HTML means
  source offsets address nothing in the DOM. A quote that no longer matches
  degrades visibly rather than painting a range on words nobody wrote.
- **Confirm/contest in the transcript.** `FieldScene`'s own comment says it
  navigates rather than reviews, and Focus is two destinations away — which
  is why the machinery had 85 marks and zero reviews. `MessageMarks` reuses
  `ReviewChip` and the existing review route; no second voting system.
- **`POST /rooms/{id}/reading/file`** — a human files a link THEY pasted,
  `source='human'`, sharing `is_thin()` with every automated path. This is the
  literal answer to "it should not give everything we paste equal weight":
  everything pasted carried the same weight because none of it became an
  object that could carry any.

**Browser acceptance earned its keep three times**, each a defect every unit
test missed: the @-picker stayed open after choosing (stale caret, would have
eaten the next Enter); a tag-only search ran, returned hits and rendered
nothing (`showResults` still gated on typed text); and the passage menu was
un-clickable because `position:absolute` trapped it in `.msg`'s stacking
context, where a later message's byline painted over it — `position:fixed`
now, dismissed on scroll.

Suites at this gate: backend **1425**, frontend **308**; browser 23/23 (Phase 1),
11/11 (Phase 2), 15/15 (Phase 3). No migration — every phase writes to columns
that already exist.

**Left deliberately undone:** `supports`/`challenges` need a second subject
(a target-picking flow, not a highlighter), so the passage menu offers only
single-subject relations. Weight is derived from confirms rather than
authored — no `weight` column, by design.


## Amendment 2026-08-17 — the three standing disciplines (amend-beside)

The room pinned three disciplines for the LLM participant after a meta
thread about research posts fragmenting discussion. They live in the prompt
layer, not in new machinery — "a discipline, not a UI feature":

- **Article → node mapping** and **falsifiable + dated ⇒ `draft_prediction`**
  ride `TOOLS_SECTION` in `llm/prompts.py` (tool-enabled primary turns only —
  provoker/protocol/forced turns never see them, which matches intent). An
  article gets sorted to a thesis node, a confluence move, or an explicit
  "touches no tracked node"; a dated falsifiable claim gets drafted, at any
  horizon, instead of narrated. The `draft_prediction` tool description in
  `llm/tools.py` carries the same trigger on the API side.
- **Meta ≠ analysis** rides `BASE_IDENTITY` — every primary turn, tools or
  not. A direct question in either mode gets a direct answer in that mode;
  no deflecting a meta question into thesis diagnostics.
- `llm/research.py`'s `RESEARCH_IDENTITY` restates the discipline for deep
  dives (research mode bypasses the evolved identity), and
  `llm/identity.py`'s `IDENTITY_DISTILLATION_PROMPT` gained a
  **Standing Commitments** section so pinned disciplines survive the
  on-disconnect rewrite instead of being compressed away under the word cap.

Pinned by `TestStandingDisciplines` in `tests/test_prompts.py`. No
migration, no new endpoints, no changes to the proposal/accept write path —
the human tap is still the only write.

## Amendment 2026-08-18 — the calibration spine: belief connects to capital (amend-beside)

Ten commits (295a28c…0875142) closed the loop the 2026-08-15 memory called
"never completed a single cycle." Prefer this over older counts above:

- **Twelve scheduled jobs**: `rss_wire` joined (900s, `RSS_WIRE_ENABLED`,
  the FIRST reader of `rooms.watchlist` — `{type:"rss", value, tag?}`
  entries; interjections flow through wire's own `_interject`, so the
  wire_interjection budget is shared BY CONSTRUCTION) and `congress_watch`
  (3600s, `CONGRESS_WATCH_ENABLED=0` — SHIPS DARK until the community
  dataset URLs are verified live; readings only, no interjection lane).
- **Twenty tools**: `propose_trade` — symbol/side/dollars/rationale + the
  forecast-XOR-discretionary gate (a paired prediction with optional
  price_cross auto-resolution spec, OR an explicit unscored-discretionary
  label; neither → refused). Accept:
  `POST /rooms/{id}/trading/trades/accept` re-validates everything,
  claims `trade:{message_id}:trade_proposal`, and makes two idempotent td
  writes prediction-first. `proposal_intake` EXCLUDES trade_proposal from
  the human raw-metadata door (it would dodge the XOR gate).
  `draft_prediction` now defaults `linked_book_id` from the room's binding
  (unlinked predictions were invisible to the deadline sweep forever) and
  accepted drafts stamp `source_type='llm', source_label='Claude'`.
- **Stakes mirror into the desk's ONE claims ledger**: `api/stakes_relay.py`
  fires from `stakes/manager.py` (the layer both doors share) —
  fire-and-forget, idempotent via `stake:{id}:*` source keys; the desk
  prediction id is never stored (every event re-POSTs the idempotent
  create and td replays the row). Commitments with no deadline or no
  stated confidence are NOT relayed. Backfill CLI:
  `trading/tools/outcomes/import_dialectic_stakes.py` (re-runnable).
- **The LLM reads its own track record**: `self_model.fetch_track_record`
  (15-min TTL) → "## Your Track Record (scored, not self-reported)" in
  render_self_awareness — Brier/BSS + the book's equity vs the unitized
  SPY benchmark. `prediction_watch._verdict` deliberately never sees it
  (the grader must not know its aggregate; pinned by an identity test).
- **The reading library grew three doors**: watchlist RSS (above);
  `POST /rooms/{id}/reading/ingest-attachment` (a dropped PDF/text —
  Capex Insider — becomes a `newsletter://` reading, content-hash
  idempotent, pypdf now in requirements); `congress://` readings. Per-source
  thin floors (`SOURCE_THIN_FLOORS`, social=25); the global 80 stands.
- **Bias controls**: `WIRE_DOMAIN_CAP=2` per scan (wire + rss_wire, one
  shared helper); stance (supports|contradicts|neutral) rides every wire
  score and persists in the reading summary; the 07:00 brief labels
  dissent COUNTER and STATES its absence when none cleared the threshold;
  one thesis-independent EXPLORATION pull per digest run
  (`NEWS_EXPLORATION_ENABLED`).
- **Bench**: PortfolioPanel (the Paper Book) pairs with OpenTradesTable as
  the cockpit's money duo; the trade card renders forecast or
  DISCRETIONARY variants. **Ledger**: TrackRecordPanel — Brier/BSS
  headline, per-source leaderboard, calibration bars, equity-vs-SPY
  sparkline. `useTradingDesk` gained the `portfolio` slice (fan-out, not
  snapshot-keyed — the book moves on fills and marks, not pushes).
- **Scoring laws live desk-side** (see trading/CLAUDE.md's same-day
  amendment): leak-safe min(deadline, resolved_at) boundary; partial
  counted-never-graded; bars-not-spot price oracle; long-only book;
  unitized benchmark. An external review mid-build drove five of those —
  adjudication recorded in the session plan
  (`/root/.claude/plans/think-outside-the-box-elegant-acorn.md`).
- Suites at this gate: dialectic backend **1727**, frontend **~350**
  (tsc -b clean; batch runs under load show timeout flakes on untouched
  files, all green in isolation); td **1602 passed, 3 skipped**.
- Still open, deliberately: Phase 8 (the laboratory — shadow books,
  competing worlds, the "How We Are Wrong" report) waits on its design
  gate: frozen policy versions before any shadow arm launches. The
  stakes relay is fire-and-forget by design; at real volume it earns a
  durable outbox (adjudicated, revisit trigger recorded).

## Amendment 2026-08-18 (late) — the Instrument Desk (amend-beside)

The UI rebuild shipped (master `2c33190`, docky-inspired, owner-ruled
"vintage instrument panel", whole app): **machined chassis with paper on
it**. Contract changes a future session must know:

- **The scene-switcher band IS the Console.** `SceneSwitcher` gained
  `signals` (running-dot LEDs per scene tile: Record unread / Bench
  alerts / Field provisional) and `instruments` (the `Console.tsx`
  cluster: seven-seg quote tiles, Polymarket LED bar, UP NEXT deadline
  countdown, the presence lamp). With `instruments` present the switcher
  renders even for a single scene.
- **`useTradingDesk` mounts ONCE, in App.tsx's RoomView** — `BenchScene`
  now takes `desk` as a prop. Entering any bound room runs the full
  fan-out + 300s quote poll in every scene (the Console's job; a
  slice-keys filter is the upgrade path).
- **The presence lamp sets `--energy-level` at runtime** (Console.tsx) —
  the token was wired-but-never-set since 2026-08-15; `energyPulse`
  keyframes now scale by the var (they previously overrode it, leaving
  the scanline faintly always-on).
- **tokens.css v3**: chassis/well surfaces, `--bezel-*`, `--led-*`,
  `--engrave`, `--font-seg` (DSEG7, self-hosted in `public/fonts/`,
  OFL license beside it, in the PWA precache). `.seg` keeps
  `letter-spacing: .1em` — without it the seven-seg decimal point
  vanishes at cockpit sizes. Paper surfaces (MessageList, MessageBubble,
  MessageInput, SignatureMark, fieldDisplay CSS) are deliberately
  untouched — the dossier sheet stays paper.
- `Console.test.tsx` carries the app's first real axe gate. Frontend
  suite 356 at this gate.

## Amendment 2026-08-20 — the connection, and the Sunday Round (amend-beside)

Three commits (`269cd54`, `49e3129`, `9084c4e`), deployed. Prefer this over
anything above that describes presence, push, or the tool timeouts.

- **`presence.py` is the ONE definition of "present right now"** — `is_present()`
  for rows already fetched, `online_sql(alias)` for queries that filter in the
  database. All four readers share it: `_should_send_push`
  (`transport/handlers.py`), both `llm/annotator.py` queries, the trading
  curator, and the presence endpoint. Before this the 90s TTL was the
  endpoint's private opinion and the other three read `status` raw — and since
  nothing resets presence at startup, one ungraceful restart could strand a row
  at `'online'` and disable that member's push, annotator and curator **for that
  room, permanently, with no error anywhere.** Mutation-proven in
  `tests/test_presence_predicate.py`.
- **`/users/me/rooms` now carries `others_present`** (one correlated subquery on
  the query it already ran). This is the only cross-room presence in the
  product; every other presence read is fenced to the current room by
  construction. `RoomList.tsx` lights the other person's initial on the room
  card, and `useRoomNavigation.ts` now polls the list (45s + `visibilitychange`)
  — without that poll every badge on the rail is frozen while you sit in a room,
  which it had been all along.
- **The history fetch depends on `isVisible`** (`App.tsx`). A push is only SENT
  to someone with no live socket to that room, so a pushed message was never
  delivered over the wire; nothing backfilled it, and a tap back into the room
  the app was already in moved none of the other deps. This one dependency also
  covers resume generally. Trading alerts and the morning brief now carry
  `thread_id`/`message_id` so they stop taking the legacy `open-room` branch.
- **The seam's timeout law is now enforced registry-wide**, not per tool:
  `tests/test_tools_registry.py` asserts every tool's asyncio guard EXCEEDS the
  HTTP timeout of the client it calls. `Tool.timeout_s` default is **14.0**
  (both tradingdesk_client and cairn_client default to 10.0);
  `QUOTES_TOOL_TIMEOUT_S` is 24.0 over a 20.0 inner.
- **The four cairn tools are fenced to `CAIRN_ALLOWED_PROJECTS`**
  (`dialectic`, `DwoodAmo`, `trading`) **at the executor**. They read Amo's
  dev-session memory for every project on this host — including somaNotes, a
  clinical product — inside rooms shared with Dan and Scott, with no room fence
  and no user fence, defaulting on. Rows with no `project` are dropped (fail
  closed), and `get_dev_session` re-checks so a known id cannot walk around it.
- **THE SUNDAY ROUND** (`llm/question_round.py`, `api/rounds.py`,
  `stakes/timeweighted.py`, `components/chat/RoundCard.tsx`). Thirteen scheduled
  jobs now. **ARMED 2026-08-20: `QUESTION_ROUND_ENABLED=1`**, first fire
  Sunday 2026-08-23 09:00 CT. `QUESTIONS_PER_ROUND` (1..10, default 5) is the
  appetite dial — four rooms qualify today, so 20 questions a Sunday.
  - **Room selection requires >= 2 MEMBERS and HUMAN traffic.** The member
    floor is a consequence of the blindness rule, not a nicety: a question
    stays sealed until both forecasters commit, so in a one-member room
    `revealed` can never become true and the round would draft questions that
    could never be read. A real one qualified on arming day ("Hi Dan!", one
    member, that member a retired account). The human-traffic condition exists
    because thirteen scheduled jobs post into rooms on their own, so
    `messages` alone keeps a dead room looking alive.
  - Forecasts are **rows in `commitment_confidence`**, never entries in message
    metadata — `schema.sql:249-259` states the rule (rows, because concurrent
    writes cannot clobber each other) and there is no array-append-into-JSONB
    idiom in this repo to make the alternative safe.
  - Each question is a `commitments` row with `category='round'` and its close
    date as the **deadline** — which is the ledger defect fixed by construction.
    A vetoed question is `status='binned'`. No migration: both columns are free
    text.
  - **Blindness is enforced in the READ** (`api/rounds._round_state`): until you
    have forecast a question, the other number is ABSENT from the response body.
    A client-side hide is not blindness. Proven in `tests/test_rounds_pg.py`.
  - **Scoring is time-weighted average Brier** (`stakes/timeweighted.py`), the
    ACE rule, with the desk's leak-safe `min(close, resolved_at)` boundary. The
    final-answer Brier rides alongside; the GAP is the interesting number.
    Same-day activity has no gap by design — the last forecast of a day governs
    that day, so a multi-day test must backdate.
  - The forecast door **refuses a post-close write (409)** rather than storing
    it and returning 200. The desk's own confidence endpoint has that bug: it
    accepts, broadcasts "updated confidence to N%", and the scorer discards it.

Checked and deliberately NOT changed: `get_thesis_news` returning
`rate_limited` is GDELT limiting this host's IP with correct exponential
backoff. Keying that cooldown per-book was proposed and refused —
`trading/web/routes/bridge.py:535` says GDELT limits by caller IP, so per-book
would draw five times the 429s.

Suites at this gate: backend **1815 passed**, 1 pre-existing failure
(`test_home_activity_pg::test_only_active_commitments_due_within_72h`, untouched
by this diff); frontend **356/356**.

## Amendment 2026-08-21 — the duel (amend-beside; prefer this over the Round section above)

Three commits (`77163f1`, `72d745b`, plus the two fixes), migration `019`
applied to prod and test, backend restarted (PID 359070 → 4126860, `/health`
200 in 4s), release `20260820211217-the-duel` symlinked and nginx reloaded.
**Fifteen scheduled jobs now.**

### Migration 019 — two columns, no backfill

`commitment_confidence` gained `peer_forecast double precision` and
`actor text NOT NULL DEFAULT 'human'` (CHECK in `('human','house')`), plus a
partial index on `actor='house'`. Every pre-existing row becomes a human
forecast with no peer guess, which is what it is. `schema.sql` is in sync.

### `stakes/house.py` is the single predicate, and here is the bug it prevents

`is_house(row)` / `split_by_actor(history)` / `record_house_forecast(...)`.
Same shape as `presence.py`, sharper reason: `api/rounds._round_state` split a
question's history on `user_id != viewer_id`, and that column is **nullable**.
A house row landing among the humans sets `revealed = True` and unseals one
person's blind forecast to the other **the instant the machine posts its own** —
no error, no log, on the one surface where a leak is the whole game.
Mutation-proven in `tests/test_rounds_pg.py::TestTheHouseIsSealedToo`.

**If you add a fourth actor, or a fifth reader of a forecast history, go
through this module.** The house writes DIRECTLY rather than through
`CommitmentManager.record_confidence`, deliberately: that path mirrors into
tradingDesk's `prediction_confidence`, whose scorer ignores `actor`.

### The scoring era changed BEFORE anything was ever scored

`_score_question` opened its window at `min(recorded_at)` — the first
FORECAST. A forecaster who opened the card late was therefore scored only
across their own shorter window, and a shorter window sits nearer the outcome,
so it is **easier**. Arriving late read as skill. The window now opens at the
question's own `created_at`. Nothing had ever resolved, so this is a fix
before first use; landing it after the first settlement would have left two
scoring eras in one table with nothing to tell them apart.

`coverage` (days_scored / window days) rides beside the Brier and must never
be folded into it — a 0.09 across a third of a question's life is not a 0.09.

### The head-to-head

`peer_delta(daily_by_actor)` → `100 × mean over CONTESTED days of (your log
score − the mean of the others')`. Antisymmetric at n=2 by construction, so it
can only say who took whose points, never that both are winning. **Contested
days only**: a day someone had not yet forecast is absence, not loss, and
`coverage` reports that separately. `LOG_CLIP = 0.01` **is the rule, not an
implementation detail** — the slider reaches 0.00, and unclipped one
certain-and-wrong call annihilates a season. The card states the clip.

### `scheduler._tick` RUNS JOBS SERIALLY — read this before adding a job

A plain `for` loop, awaiting each job. A long job blocks **every other job**.
This is why the house forecast is a bounded sweep and not an inline call
inside `question_round` (where the first draft put it): twenty tool loops at
150s each is ~50 minutes during which the silence sweep, the heartbeat and the
reconcile do not run. `house_forecast_sweep` takes 2 questions per 15 min with
a 330s run budget and is idempotent by query. What makes the delay acceptable
rather than merely cheaper is the seal: the house's number is invisible until
both humans commit, so it does not need to be there when the card lands.

### The settlement (`llm/round_close_watch.py`)

**THE LAW: it gathers evidence and SUGGESTS. It never resolves.**
`POST /rooms/{id}/rounds/{cid}/resolve` is the only write and a human's tap is
the only thing that reaches it.

**The done-set MUST be excluded in SQL, before the LIMIT.** Because THE LAW
forbids the job writing to `commitments`, a carded-but-untapped question stays
`status='active'` with a past deadline **forever**. Filtering after
`LIMIT BACKLOG_SCAN` let those rows keep their places until nothing live could
get in, and the symptom is an empty detail identical to "nothing closed this
hour". A pg test seeds a full backlog plus one live question.

`credit_line` gates on **two HUMANS**, not two forecasters: `fact_packet`
counts the house, so a "two forecasters" gate was satisfied by one person plus
the machine — and the line would then post that person's number as an ordinary
message while `_round_state` was still correctly sealing it. The API lane held;
the message lane did not.

`validate_line` pairs each number to the **name it sits beside**. Checking the
number set and the name set independently passes a line with the attributions
SWAPPED — every number the packet's own, every name the packet's own, and a
lie. The outcome word must match the outcome too.

### The Mirror (`api/mirror.py`, `MirrorPanel.tsx`)

Three JWT-only GETs onto `user_model:<user_id>` memories and their
`memory_versions` history. **The fence is the KEY, in the query**: `key =
'user_model:' || <authenticated caller>`, never a post-fetch filter, so a room
where only the OTHER person is modelled is indistinguishable from a room with
no model — in the list, in the counts, and in the 404. Verified live against
production with both users' tokens: zero cross-contaminated prose blocks.

It also requires **current membership** and `status='active'`, matching the
older single-room door at `api/main.py:1845`. Not about whose profile it is —
a model written FROM a room's conversation quotes what happened there, and
`deploy/remove_home_member.sql` exists.

`mirror` is a new **Home-root scene** (`house/atlas/mirror/record`). It entered
`WORKSPACE_SCENES` and `IMPLEMENTED_WORKSPACE_SCENES` in the same change on
purpose: the rule those two lists exist to enforce is that an approved name
must never open nothing.

### Env

`HOUSE_FORECAST_ENABLED=1` and `ROUND_CLOSE_ENABLED=1` are in `dialectic/.env`
and confirmed in `/proc/<pid>/environ`. Backup: `/root/dialectic-env-backup-20260820-preduel.txt`.

Suites at this gate: backend **1917**, frontend **369**, both in isolation.

Run CONCURRENTLY the frontend drops one:
`RoomHeader.test.tsx > toggles the explicit desktop context column` times out
at ~8.6s. Not an assertion failure and not this work -- no commit here touches
`RoomHeader.*` (last changed in `5357670`), and it passes 3/3 alone. Same
load-sensitive batch flake the 2026-08-18 amendment already records. The
backend also stretches 32s -> 137s under the same contention, which is the
tell: measure the two suites separately or the flake is the measurement.

One pre-existing lint error remains at `MessageList.tsx:247`
(`react-hooks/set-state-in-effect`), introduced 2026-08-19 in `269cd54`,
untouched by this work.

## Amendment 2026-08-22 — write_document: the participant can hand the room a file (amend-beside)

Owner, 21:38 CT, in the AI Capex room: asked the participant for a
newsletter "as a downloadable PDF"; it answered, truthfully, *"I don't have
a file-output tool."* Tool calls themselves were healthy (the 22:37 UTC
`read_article` ran `ok`); the gap was the tool that did not exist.

- **Twenty-one tools.** `write_document(title, content)` in
  `_build_dialectic_tools` — markdown → HTML (`markdown-it-py`, commonmark +
  tables, raw HTML OFF) → PDF via the host's **headless Chrome**
  (`google-chrome --headless=new --print-to-pdf`, own `--user-data-dir` per
  render so concurrent turns never fight a profile lock; override binary
  with `DIALECTIC_CHROME_BIN`). Nothing PDF-shaped was installed in Python;
  Chrome was. `llm/documents.py` is the whole module.
- **A document is an `attachments` row, not a new table** — `kind='file'`,
  `mime='application/pdf'`, **`uploader_user_id NULL` = authored by the LLM**
  (the same convention `messages.user_id` uses). **Migration `020`** drops
  the NOT NULL; `schema.sql` and `AttachmentResponse` follow. Human uploads
  still always carry their uploader.
- **The bind is two-phase and the provenance is the thread between them.**
  The tool writes the row with `message_id NULL` and returns
  `provenance={"kind":"document","attachment_id"}`; the tool loop lifts that
  onto the trace entry (the same lift `draft_prediction` uses); after
  `_persist_response` on BOTH tool paths the orchestrator calls
  `_bind_documents` → `documents.bind_documents`, whose UPDATE predicate is
  `message_id IS NULL AND uploader_user_id IS NULL AND room_id = $3` — a
  model cannot claim a human's upload or re-home a bound one. NEVER raises:
  the message is already streamed; an unbound document is a reload away, not
  a lost turn. The bound payloads ride `llm_done.attachments` (streaming) and
  `message_created.attachments` (heuristic) — the frontend already consumed
  the latter; `useDialecticSocket` now reads the former too. History is
  covered by the existing `GET /rooms/{id}/attachments?message_ids=`.
- **Timeout law**: `RENDER_TIMEOUT_S=20` inside `timeout_s=25.0` (the guard
  outlives the render, and stays under half the 60s loop budget — the
  registry test enforces both).
- `TOOLS_SECTION` gained the one-paragraph policy ("Never say you cannot
  produce a file") and the tool description tells the model the file
  attaches automatically so the reply stays a sentence, not the content
  again. `releases.ts` carries the What Changed entry (`documents`).
- Tests: `tests/test_documents.py` — real-Chrome render, the INSERT shape,
  the bind PREDICATE (asserted, not just the outcome), and one real-Postgres
  store→bind→list round-trip against migration 020.

## Amendment 2026-08-24 — the desk dependency, stated plainly (amend-beside)

Recorded during a droplet-wide service audit, so the coupling is never
rediscovered the hard way.

Dialectic is not a replacement for tradingDesk — it is a **runtime HTTP
client of it**, and both must stay deployed:

- `TRADINGDESK_URL` in `.env` points at `tradingdesk.service`
  (uvicorn `web.main:app` on :8006, working tree `/root/DwoodAmo/trading`).
  Service principal: `TRADINGDESK_USER=dialectic`.
- Everything desk-shaped flows through `llm/tradingdesk_client.py` and the
  four relays: `api/prediction_relay.py`, `api/stakes_relay.py`,
  `api/trading_relay.py`, `api/thesis_relay.py`.
- The dependency is bidirectional for auth: tradingDesk verifies Dialectic
  access tokens (the no-second-login bridge to td.somacura.org), and gated
  signup exists because of it (`api/auth/routes.py`).
- There is deliberately **no systemd `Requires`/`After` on tradingdesk** —
  if the desk is down, Dialectic keeps running and the relays surface 502s
  ("tradingDesk unreachable") per call instead of crashing rooms. Do not
  add a hard unit dependency; the soft-fail is the design.
- Operational rule: retiring or moving `tradingdesk.service` or
  `/root/DwoodAmo/trading` breaks predictions, stakes mirroring, live
  quotes/what-ifs, and thesis books in every trading room. Treat the pair
  as one deployment unit. (See also `/root/SERVICE_INVENTORY.md`.)

## Amendment 2026-08-25 — production World Synapse (amend-beside)

The `World Synapse` source contract above is active in production from
application commit `85fed38`. Migration 022 is applied; `dialectic.service`
runs the repository checkout directly; the selected PWA release is
`20260826T032052Z-world-synapse-85fed38`. Public authenticated acceptance
passed 10/10, including zero Cesium bytes in House, one lazy World bundle,
canonical Focus, complete provenance, and the collapsed full-list no-WebGL
path. Root `PLAN.md` is the zero-context runtime/rollback handoff.

The tool registry is 23 (`world_query` plus the earlier 22). No live signal
provider is configured. Do not interpret the empty `WorldSignalStore` as a
failed feed or as confirmed-empty evidence; provider activation is a separate
Phase 4 decision.

## Amendment 2026-08-26 — God's Eye parity: live signals and the sensor cockpit (amend-beside)

The owner asked for the World Lens to *"actually resemble and function like the
god's eye github project."* Two halves shipped; prefer this over the
2026-08-25 line saying no live provider is configured.

### Function — `world_adapters.py`, the adapters the substrate reserved

`world_signals.py` was complete and empty by design. It now has a producer.

- **Sixteen scheduled jobs**: `world_signals` joined (120 s,
  `WORLD_SIGNALS_ENABLED`). It polls five keyless public feeds, converts each
  into one complete `WorldSignalSnapshot`, and replaces exactly that provider
  in the process-local store. **No database write, no HTTP writer, no
  geography.** Placement through `api/geo.py` is still the only way a person
  makes a scope, so the authority ladder is untouched.
- **Providers**: `usgs` (earthquakes), `adsb` (adsb.lol live aircraft — chosen
  *because* OpenSky's written-agreement clause still excludes it), `iss`
  (wheretheiss.at), `launch` (Launch Library 2), `firms` (NASA FIRMS, **dark
  without `FIRMS_MAP_KEY`**). Each has its own `*_ENABLED` flag and its own
  `min_interval_s` floor — the job's 120 s cadence is right for aircraft and
  rude to Launch Library's ~15 requests/hour anonymous tier. Terms for all
  five are in `docs/WORLD_PROVIDERS.md`'s 2026-08-26 amendment.
- **The room fence is the coverage boundary.** A signal reaches a room only if
  it falls inside that room's own accepted geography (live scope bbox + 1.5°,
  24 rooms max). A room that has placed nothing gets nothing. The ISS is the
  one deliberate global exception and its `coverage` string says so.
- **Every failure is an evidence state, never an exception**: timeout →
  `unavailable`, 429/503 → `rate_limited`, no key → `not_configured` (and the
  adapter does not touch the network — a test fails if it does), one room's
  fetch failing → `partial`, a successful empty poll → `ok` with zero signals.
  Absence is never silently converted into zero.
- **Verified against the real feeds, not fixtures**: the live probe returned
  51 live aircraft and the ISS projected into the actual Iran/Hormuz room
  (fence `46.22,20.96 → 62.91,32.01`), USGS `ok` with zero *inside that box*,
  FIRMS `not_configured`. The probe also caught a real defect: Launch Library's
  `mode=list` omits `pad` entirely, so every launch was silently dropped for
  having no geography and the layer merely looked empty. Pinned by a test that
  asserts the URL does not ask for that mode.

### Resemble — the sensor cockpit

- **Six sensor shaders copied VERBATIM** from God's Eye View (MIT, © 2026
  Bilawal Sidhu) into `world/shaders/` — CRT, night vision, FLIR/thermal,
  noir, snow, illustrated. The GLSL is left unedited so upstream fixes re-apply
  by diff; each file carries the notice. **No dataset and no 3D model** was
  taken from that repository (its MIT grant covers code only).
- **`worldStyleStages.ts`** is upstream's `_initStages` recast as an
  instance-scoped service, because a globaled stage set outlives the viewer a
  React route unmounts. Two invariants it exists to hold: a zero-intensity
  stage is **disabled**, not merely transparent; and the animation clock runs
  only while a visible animated shader needs it — `requestRenderMode` is on, so
  an always-running rAF would quietly convert the idle globe into a
  continuously drawn one. Reduced motion never starts it.
- **`WorldHud.tsx` is ordinary DOM, deliberately.** Upstream renders its
  readouts inside the fragment shader as seven-segment glyphs — beautiful, and
  unreadable to a screen reader, unselectable, and absent exactly when WebGL
  is. Layers, source lamps, camera readout and tracked telemetry are real text
  over the canvas, and every one of them also exists in the complete list below
  the globe.
- **Click-to-track.** A scope click still opens Focus. A **signal** click only
  starts tracking: the camera follows, a trail of the *received fixes* draws
  behind it (never interpolated — the trail is evidence, not a drawing of one),
  telemetry opens in the HUD, `Esc` releases. Tracking writes nothing. Keys:
  `0`–`6` optics, `H` HUD, `Esc` release.
- **Layer-aware glyphs** in `worldSignals.ts`: an aircraft is an arrow rotated
  onto its reported track with a leader line to the ground it is over; a quake
  is a ring sized by magnitude; altitude is honoured so an airliner at FL370
  does not sit on the terrain. A contact with **no** reported track stays a
  plain point — an arrow pointing north by default would be the map inventing
  telemetry.
- The page's warm sepia filter is dropped whenever a sensor style is active:
  the shader IS the look, and tinting FLIR makes white-hot beige.

Suites at this gate: backend **2144**, frontend **597**, lint clean, `tsc -b`
clean, production build passes the lazy-Cesium/precache contract (shell
unchanged at ~768 KiB precache; Cesium stays in its own on-demand chunk).

**Not deployed by this commit.** Both units run their git working trees, so
the deploy is the usual ritual: no migration is needed (nothing here touches
the schema), then `systemctl restart dialectic` and a frontend release flip.

## Amendment 2026-08-28 — Somacura Capture / Reading Rail (local, not activated)

`feat/ipad-reading-rail` adds a native iPad Safari capture appliance and the
server/Library vertical slice. Production remains on migration 022 until the
owner separately authorizes migration 023 and deployment.

- `POST /rooms/{id}/reading/capture` accepts exact rendered Markdown after JWT,
  room-token, membership, UTF-8 byte-limit, URL, and SHA-256 verification. It
  never refetches and never calls an LLM.
- `reading_revisions` is immutable browser evidence. `capture_id` is global
  idempotency; `(captured_at, received_at, revision_id)` determines current
  order; raw/canonical URL aliases converge on one `reading_items` ID.
- A current browser artifact cannot be overwritten by legacy server refetch.
  Proposal/file routes return 409 without acceptance/provenance mutation; a
  newer browser capture is the revision door.
- The existing Library now uses room-fenced PostgreSQL FTS/filter/cursor list,
  direct detail, exact Markdown download, sanitized rendering, raw copy, and
  revision metadata. The workspace reading/twin still projects once.
- `capture-ios/` contains the MV3 no-popup WebExtension and converter-generated
  SwiftUI app/extension. App Group files are the commit point before network;
  tokens stay in shared Keychain. The checked-in signing prefix is explicitly
  unconfigured and simulator-only.
- Local gates: backend 2188 passed / 4 browser-only skipped, frontend 629,
  WebExtension 16, native XCTest 17, signed Simulator app launch, and isolated built-PWA
  search/detail/copy/download with downloaded SHA matching PostgreSQL. Physical
  iPad, registered App Group/Keychain, Simulator Safari toolbar action, migration,
  restart, frontend release, TestFlight, and production are UNVERIFIED.

## Amendment 2026-08-29 — Reading Rail master reconciliation and physical gate

Production master assigned `023_drop_orphan_tables.sql` after the Reading Rail
branch split, so browser capture revisions are migration
`024_reading_capture_revisions.sql`; numbered migration prefixes are now tested
for uniqueness. Preserve both master’s orphan-table removal and Reading Rail’s
schema additions.

A signed physical iPad Safari action committed an exact Example Domain capture
through the real shared App Group and the containing app displayed it as queued.
This closes physical extension enablement, one-tap capture, and App Group sharing.
Cross-target Keychain delivery, migration 024, backend restart, frontend release,
and production filing remain UNVERIFIED; the live server still returns 404 for
the new Library routes until activation.
