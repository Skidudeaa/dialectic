# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this monorepo is

**Dialectic** — a collaborative dialogue engine where two humans and an LLM
co-reason in real time. The LLM is a participant, not an assistant: it decides
when to speak, checks live market data with tools, remembers with attribution,
and follows up on silence. One product, three co-projects:

| Dir | What | Runtime |
|---|---|---|
| `dialectic/` | The product: FastAPI backend + React PWA | `dialectic.service`, :8002, Postgres |
| `trading/` | tradingDesk: causal-DAG thesis engine + live data service | `tradingdesk.service`, :8006 (loopback), SQLite at `/var/lib/tradingdesk/` |
| `cc-sidecar/` | Claude Code observability daemon (donor of the FSM/StateSource patterns now in dialectic's `llm/participation_fsm.py`) | optional local daemon |

`packages/` (React Native) is **frozen** — cannot reach production; the PWA is
the reach strategy. `docs/` holds the vision, quarter plan + Amendment 1, and
handoffs. `dialectic/TODOS.md` is the task board.

## Commands

```bash
# dialectic backend (port 8002; env from dialectic/.env)
cd dialectic && PORT=8002 python3 run.py
cd dialectic && python3 -m pytest tests/ -q          # 790 tests

# dialectic frontend (React app — the only live frontend)
cd dialectic/frontend/app && npm run dev

# tradingDesk
cd trading && python3 -m pytest --collect-only -q    # 1359 collected
uvicorn web.main:app --port 8006                     # see trading/README.md
```

## Deploy (house rules — read before touching production)

- **Both systemd units run their git working trees.** A restart deploys
  whatever is on disk. Never restart with uncommitted edits.
- Deploy is three independent steps, in order: **migration** (`psql`, verify
  `\d`) → **backend restart** (`systemctl restart dialectic`, verify `/health`)
  → **frontend release** (build → `/var/www/dialectic-releases/<ts>-<name>` →
  flip `/var/www/dialectic-current` symlink → `systemctl reload nginx`).
- Auth-touching changes: tradingDesk first, THEN the dialectic frontend flip.
- `journalctl --since` parses LOCAL time; app logs stamp UTC.
- tradingDesk's SPA answers unknown GETs with 200+HTML — check content-type,
  never just the status code.
- Docs are amended **beside**, never silently edited (dated stamps).

## Architecture essentials

- **Event sourcing**: append-only `events` table is the source of truth;
  everything else is derivable.
- **The LLM participant**: `llm/orchestrator.py` (three paths — @Claude
  streaming, heuristic non-streaming, forced) → `llm/tool_loop.py` over a
  12-tool registry (`llm/tools.py`; provoker/protocol/annotator never get
  tools) → `llm/self_model.py` decision log + `llm/participation_fsm.py`
  conversation state machine with confidence tiers.
- **The clock**: `dialectic/scheduler.py` — advisory-locked asyncio jobs on the
  `scheduled_job_runs` ledger (double-fire-proof), interval buckets + wall-clock
  daily slots. Jobs: trading reconcile/watchdog, morning brief
  (`llm/night_shift.py`, 07:00 CT), silence sweep (`llm/silence_sweep.py`, 60s).
- **Memory**: `memory/manager.py` — three-lane RRF recall (dense + FTS +
  speaker), write-path dedup, supersession with history.
- **The seam**: tradingDesk's coordinator pushes v3 snapshots on change +
  hourly heartbeat; dialectic pulls on a 15-min reconcile and calls bridge
  endpoints (`X-Service-Token`) for tools — read-only except two lifecycle
  writes: `POST /api/bridge/room-token` (create-thesis registers the push
  credential into `/var/lib/tradingdesk/room-tokens.env`, no restart) and
  `POST /api/bridge/room-unbind` (retire; the book survives). Auth bridge:
  shared HS256 secret; td maps dialectic JWTs via `DIALECTIC_USER_MAP`.
- **The workroom projection** (live in production since 2026-08-13):
  `dialectic/workspace_objects.py` gives readings, briefs, the thesis,
  commitments, proposals, dossier entries and the Record one read-only shape —
  **adapters over the entities that already exist, never a universal artifact
  table**. Two entities keep a deliberate memory twin that must project as one
  object (a reading + its `reading:` memory; a thesis + its
  `thesis_state_current` slot). Shipped as Release 1 with NO migration — it
  projects entities that already exist, so its deploy was a backend restart
  plus a frontend flip. `docs/superpowers/plans/…-release-1-sdd-ledger.md` is
  the canonical record of what landed and what was deliberately left open.
- **Key tables**: `events`, `rooms` (+`linked_book_id`, `trading_config`,
  `is_home`), `threads`, `messages` (+`metadata`), `memories`, `attachments`,
  `room_memberships` (+`can_manage_home`), `llm_decisions`,
  `llm_participation_state`, `scheduled_job_runs`, `web_push_subscriptions`.
  `dialectic/schema.sql` is the fresh-DB baseline; migrations numbered,
  `013` current (Home Base — live in production since 2026-08-12 with the
  two founders activated; membership changes go through `api/home.py` or
  the reviewed deploy scripts, never ad-hoc SQL).

## Amendment 2026-08-13 — corrections from the architecture map

Drawing `docs/diagrams/dialectic-architecture.drawio` meant sourcing every
label from the running code instead of from this file. Five claims above had
drifted. The originals are left in place per the amend-beside rule; **prefer
what follows.**

- **The tool registry is 15 tools, not the "12-tool registry" above.** Eight
  tradingDesk (`get_live_quotes`, `get_polymarket_odds`, `get_thesis_state`,
  `diff_thesis_last_hour`, `evaluate_scenario`, `get_open_trades`,
  `get_morning_brief`, `get_thesis_news`) + seven dialectic (`search_memories`,
  `search_transcript`, `draft_prediction`, `propose_thesis`, `read_article`,
  `save_reading`, `search_reading`). `tests/test_tools_registry.py:70` already
  asserts `len(registry.tools) == 15`. Note also that `build_registry` adds all
  fifteen **unconditionally** — its docstring's "room-scoped" claim is not what
  the code does; the persona exclusion (provoker/protocol/annotator) is enforced
  elsewhere. Kill switch: `DIALECTIC_TOOLS_ENABLED`.
- **Nine scheduled jobs, not the four listed.** Beyond reconcile/watchdog,
  morning brief and silence sweep: `scheduler_heartbeat` (600s),
  `thesis_news_digest` (05:30 CT, `llm/news_night.py`), `wire_watch` (900s,
  `llm/wire.py`), `prediction_deadline_watch` (3600s,
  `llm/prediction_watch.py`), `reading_echo` (1800s, `llm/reading_echo.py`).
  Each has its own `*_ENABLED` flag; all are registered in the `api/main.py`
  lifespan (~:254-265) and only when `db_pool` exists. Tick is 30s.
- **Migrations run to `016`, not `013`.** Verified against the live DB, not the
  file listing: `reading_items` exists (014 applied) and `memories.embedding` is
  1024-wide (016 applied). 015 is `room_watchlist`. `013` remains correct only
  as "the Home Base migration", not as "the latest one". Note `reading_items`
  (014) is therefore **absent from the `schema.sql` baseline** — a fresh DB
  needs the migrations, not just the baseline.
- **There is a third service: `defuddle.service` on :8010.** Node article
  extractor (`dialectic/defuddle_service/server.mjs`), reached via
  `llm/defuddle_client.py`, backing the `read_article` tool. Live and active;
  missing from the co-projects table above.
- **`dialectic/deploy/dialectic.service` is NOT what runs.** It describes an
  `/opt/dialectic/current` release-symlink deploy; that path does not exist on
  this host. The unit systemd actually loads is
  `/etc/systemd/system/dialectic.service`, with
  `WorkingDirectory=/root/DwoodAmo/dialectic` and
  `ExecStart=/usr/bin/python3 run.py`. **The "both units run their git working
  trees" house rule above is the accurate one** — the checked-in service file is
  the trap, and a deploy that trusted it would target a directory that isn't
  there. Tombstoned in place.

Two things checked and found **correct**, recorded so they aren't re-litigated:
the seam's "v3 push on change + hourly heartbeat" is exact
(`coordinator.py:660`, `DIALECTIC_HEARTBEAT_SECONDS = 3600.0` — and only a
*delivered* push resets the clock, so a spooled failure stays due); and
cc-sidecar really is pattern-donor only — nothing in `dialectic/` or `trading/`
imports it and no unit runs it.

One minor inconsistency, left alone deliberately: tradingDesk's **dev** port is
8000 (`Makefile`, `trading/CLAUDE.md`, and `dialectic/CLAUDE.md`'s "port 8000 is
reserved"), while `trading/README.md:14` shows 8006 for dev. Production is 8006
everywhere. The Makefile is not wrong; the README's dev line is the odd one.

## Amendment 2026-08-14 — Release 3 is live (amend-beside; prefer this over older counts)

Release 3 — Deliberation and Whole-House Intelligence — merged, pushed and
deployed 2026-08-14 (master `7535e1c`, gate ledger
`docs/superpowers/plans/2026-08-14-dialectic-release-3-deliberation-gate.md`).
What the sections above understate as of that date:

- **Migrations run to `017`** (`017_field_marks.sql`, applied to the live DB;
  the table is also appended to the `schema.sql` baseline, unlike 014's gap).
- **Ten scheduled jobs, not nine**: `field_inference` joined (1800s,
  `llm/field_inference.py`, `FIELD_INFERENCE_ENABLED`, model pinned
  `claude-haiku-4-5-20251001`). Caps 6 marks/room/run, 20/room/day, counted
  from `field_marks` rows.
- **New backend modules**: `field_marks.py` (append-only marks, review state
  DERIVED at read time; the partial dedup index is the re-assertion law — and
  note its `ON CONFLICT` must repeat the index's `WHERE dedup_key IS NOT
  NULL` predicate), `api/field.py` (the one Field write route),
  `atlas_objects.py` + `api/atlas.py` (per-viewer-fenced cross-room map,
  JWT-only), `proposal_intake.py` (server-side gate for human proposal
  metadata at the message door).
- **Scenes**: ordinary rooms are `record/bench/field/library/ledger`; Home
  root is `house/atlas/record`. Focus is a STATE riding `&object=`, not a
  scene. `judgment` remains name-only.
- **Chat is de-chatted (F1)**: full-width rows, signature marks
  (`markGlyph` in `productIdentity.ts`), no participant color coding. F2
  (typographic voices/motion) deliberately deferred — needs a
  contribution-vs-position field that doesn't exist yet.
- **Backend suite ~1300 / frontend ~233** at the Release 3 gate (the "790
  tests" in Commands above is two releases stale).

## Code style

ARCHITECTURE/WHY/TRADEOFF docstrings on non-obvious decisions. Match the
surrounding file's idioms; minimal diffs; house-style commit messages with the
`--` em-dash flourish (see `git log --oneline`).

## Amendment 2026-08-14 (late) — One App: the Bench cockpit + the C4 cull (amend-beside)

The owner's complaint ("dialectic and trading desk are STILL separate
interfaces?!") closed tonight. Prefer this over anything above that
describes the Bench as a badge panel or td as a parallel product:

- **The Bench is the trading cockpit.** A bound room renders natively: the
  causal DAG (`ThesisDag.tsx`, read-only SVG, live nodeStates overlaid on
  authored structure, client restack of the baked-diagonal layouts), market
  strip, Polymarket, alert events, hourly diff, open trades, scenario
  what-ifs (per-row Evaluate — pure hypothetical), morning brief, thesis
  news. Data: `api/trading_relay.py` — room-scoped proxies over the same
  `tradingdesk_client` calls the LLM tools use; the book id never reaches
  the browser. Hook: `useTradingDesk.ts` (tri-state slices, 409 = unbound
  = calm create state, quotes poll 300s, snapshot-stamp refetch).
- **New bridge read**: td `GET /api/bridge/structure/{thesis_id}`
  (X-Service-Token) serves builder-format nodes+edges — the one endpoint
  that lets dialectic draw the graph (snapshots carry states only).
- **Timeout law of the seam**: a proxy timeout must EXCEED the inner
  fetch's own timeout (news 25s over GDELT's 20s; quotes 25s over the
  ~18.5s cold path) or graceful empties become 502s.
- **The C4 cull executed** (fusion plan §C4, deferred since 2026-08-09):
  td's duplicated social tier is deleted; see `trading/CLAUDE.md`'s
  2026-08-14 amendment for the full list. td `/` boots the Dashboard;
  the Builder remains the deep-editing surface, reached from the Bench's
  single "Deep instrument" affordance (design v2 §12.5 satisfied — the
  "Open Full Dashboard" link is gone).
- Suites at this gate: dialectic backend 1335 (one pre-existing
  load-sensitive p95 gate flake in `test_home_activity_pg`), frontend 250;
  td backend 1377, frontend 62.

## Amendment 2026-08-25 — the World Lens: Atlas / World, and the participant's eyes (amend-beside)

`docs/WORLD_LENS_VISION.md` (60eb618) governs; Phases 0–2 of its plan
shipped tonight (0be95ae, 58d702f, 011d666, eab5178), live. Prefer this
over anything above that says Atlas is list-only or counts 21 tools.

- **Migrations run to `021`** (`021_geo_scopes.sql`, applied prod + test,
  in `schema.sql`). `geo_scopes` attaches GeoJSON geometry to rows that
  already exist via the same `{entity,id,field}` ref the Field uses.
  **Authority is a column**: `human_confirmed | source_reported |
  machine_proposed`. Append-only with supersession; the live set is DERIVED
  (`geo_scopes.LIVE_PREDICATE`: not expired, not superseded, not
  `confirmed_empty`). Owner module `geo_scopes.py`; human-only door
  `api/geo.py` (place / confirm / reject — reject INSERTS a
  `confirmed_empty` replacement). `field_marks._SUBJECT_ENTITY_TABLES`
  gained `geo_scopes` with the authority guard IN the SQL: a proposal cannot
  anchor a mark until a person confirms it.
- **Atlas has two modes over one fenced projection.** `AtlasProjection.scopes`
  rides beside nodes (nodes carry NO geo field on purpose). The `view` URL
  axis (`world[:lat,lon,alt,heading,pitch][;room=<id>]`, grammar in
  `world/worldCamera.ts`) is written only by `useRoomNavigation.navigate`.
  `WorldView.tsx` = CesiumJS behind `React.lazy`, own 4.2 MB chunk served
  with its static tree from `/cesium/`, both excluded from the PWA precache;
  keyless OSM + Re:Earth terrain, never Google tiles; `requestRenderMode`;
  the credit line is ours and always visible. The House list never leaves
  the page in World mode. A room that owns geography gets a "World ↗" door
  on its Bench (`useGeoScopes`).
- **Twenty-two tools**: `propose_geo_scope` (`llm/world.py`,
  `DIALECTIC_WORLD_ENABLED`) resolves a NAME — a Natural Earth marine region
  (`data/natural_earth/marine.json`, PD) or the exact label of a scope the
  room holds — to geometry that already exists and writes a
  `machine_proposed` row expiring in 14 days. An unknown name returns
  candidates, never a guess. Coordinates are never taken from the model.
- **Focus grew a World section** (`FocusWorld.tsx`): the scopes about the
  object with authority + source state + age; Confirm/Reject a proposal;
  "Place on" one of the room's confirmed areas; "Mark as evidence here"
  files an `evidence_attachment` mark whose subjects are the scope AND the
  object. Provider terms: `docs/WORLD_PROVIDERS.md`.
- Hormuz (`56ba2f1e`) holds the Strait polygon + TSS inbound lane
  (hand-authored, "(approx.)") and the Persian Gulf / Gulf of Oman rings,
  confirmed_by Amo via `deploy/seed_hormuz_geo.py`.
- Suites at this gate: backend **1995**, frontend **517/518**
  (`WhatsNewPanel > explains a hard word` pre-existing: the newest release
  entry carries no `[[gloss]]`). Browser-proven as Amo on production.
- Phase 3 (live feeds as FastAPI adapters, `world_query`, the
  `world_samples` sampler) waits on the vision's own gate: "only after the
  wedge feels electric" — and on the AIS terms decision.

## Amendment 2026-08-25 (late) — World Synapse is live (amend-beside)

The prior paragraph's speculative Phase 3 shape is superseded. Phase 3 means
**Synapse**, not provider feeds: House, World, Focus, Field, and the participant
share canonical scope-lineage identity and one server-owned causal binding
projection. Live provider activation moved to Phase 4 and remains gated.

- Migration `022_geo_scope_lineage.sql` is applied in production. GeoScope
  UPDATE/DELETE and successor forks are rejected in PostgreSQL; human review
  appends typed successors and events atomically.
- The participant registry is now **23 tools**. `world_query` is read-only and
  room-fenced; `propose_geo_scope` remains the sole participant geography
  writer and creates only a human-reviewed proposal from existing geometry.
- Ordinary rooms admit Atlas; House/World/Focus/Field preserve one root-stable
  object across the sole navigation writer. Causal meaning is explicit DOM
  text, never an invented geographic ray to a non-geographic thesis node.
- Cesium's complete dependency graph is lazy and outside the PWA precache. The
  production build now fails if emitted shell/SW assets regress that contract.
- Live application code `85fed38`; production backend PID `1941516`; selected
  PWA release `20260826T032052Z-world-synapse-85fed38`; authenticated public
  browser gate 10/10. Exact operational evidence and rollback coordinates are
  in root `PLAN.md` and the Phase 3 qualification ledger.
- No live WorldSignal adapter or geographic replay store is configured. That is
  a deliberate Phase 4/6 gate, not an inactive Phase 3 feature.

## Amendment 2026-08-26 — thinking protocols: four fractures closed (amend-beside)

Fracture review `4bc57d094a71f126` found four PREEXISTING defects on the
protocol path (Steelman / Socratic / Devil's Advocate / Synthesis); all
fixed in `3b1b4b1`, live (backend PID `3027133`, release
`20260827T041529Z-protocol-fractures-3b1b4b1`). Handoff:
`docs/handoffs/2026-08-26-protocol-fractures.md`. Facts a future session
should not re-derive:

- **`protocol_state` is a WS message** (`MessageTypes.PROTOCOL_STATE`),
  directed to the user after the handshake (`api/main.py`) and after every
  `switch_thread`; payload `{thread_id, protocol|null}` built by
  `transport/handlers.py::protocol_state_payload`. Lifecycle broadcasts
  (`protocol_started/phase_advanced/concluded/aborted`) are events; this is
  state, derived from `thread_protocols` via `ProtocolManager.get_active`.
  The client REPLACES `activeProtocol` with it.
- **`config.target_claim` is rendered** by `get_protocol_instructions` as a
  blockquoted "Claim under examination" section — participant data, never
  instruction. Rooms carrying no claim render unchanged.
- **The synthesis memory is the final facilitator message**, written with
  `source_message_id` by `_conclude_protocol`. `[Protocol … synthesis
  pending]` now appears only for a protocol that concluded with zero
  messages. `ProtocolDefinition.synthesis_prompt` remains defined and
  UNCONSUMED — do not assume a second synthesis call happens.
- **Deploy scripts with their own `asyncpg.connect`** must `load_dotenv`
  before importing provider code AND `set_type_codec('jsonb', …)`
  (`deploy/backfill_protocol_synthesis.py` is the reference; ran once on
  prod, 2 memories repaired, dry-run now 0).
- Suites at this gate: backend **2156**, frontend **604**.
