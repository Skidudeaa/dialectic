# World Lens: Truth Before Spectacle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:subagent-driven-development` and execute every task with TDD,
> per-task review, and a final whole-branch review.

**Goal:** Turn the deployed geography-aware Atlas into an honest causal
observatory: every geographic assertion has reviewable authority and lineage,
every causal interpretation names a thesis node and survives Field
adjudication, and future live observations enter through a distinct fenced
`WorldSignal` contract rather than masquerading as durable `GeoScope` rows.

**Architecture:** `GeoScope` remains the durable geographic place/boundary;
append-only successor rows carry review actions and preserve complete lineage.
`FieldMark` remains the durable human-adjudicated interpretation, extended with
explicit thesis-node references. `WorldSignal` is a separate ephemeral,
read-only projection fenced by the same eligible-room set as Atlas; a human
placement copies its server-owned geometry/provenance into a durable
`source_reported` `GeoScope`. The participant may inspect this state but never
mutates a thesis. Existing tradingDesk Builder remains the only thesis editor
and every change there remains a deliberate human act.

**Tech stack:** PostgreSQL, Python 3.12, FastAPI, Pydantic, React 19,
TypeScript, Vitest, CesiumJS, existing Field/Atlas/Trading relay contracts.

## Global Constraints

- Preserve House as the complete list-first/no-WebGL representation; World is
  the existing `view` URL axis and never becomes a scene or router.
- `useRoomNavigation` remains the sole destination writer.
- Never accept client/model-generated coordinates for a durable scope. Redraw
  geometry is human-authored; signal placement copies a server-held signal.
- Never UPDATE or DELETE `geo_scopes`; migration 022 enforces this in the
  database. Correction, rejection, supersession, redraw, and ratification all
  append a successor.
- Source condition, freshness, review decision, and authority remain separate
  response axes. Preserve legacy `source_state='confirmed_empty'` rows as
  history, but do not use that provider-state value for new human rejection.
- One scope may have at most one direct successor. Review writes lock the live
  target and return HTTP 409 to a losing concurrent writer.
- Scope insertion, successor insertion, and the corresponding full-fidelity
  event write are atomic.
- A machine proposal cannot anchor a Field mark or causal binding until a
  human confirms it.
- A causal binding is a Field mark with relation `supports`, `challenges`, or
  `context`, with one live accepted `geo_scopes` subject and one room subject
  whose field is exactly `thesis_node:<book-id>:<node-id>`.
- Book ID is part of the thesis-node reference so rebinding a room never
  silently retargets old evidence. The backend validates the current bound
  book and node through the existing authenticated structure bridge.
- No automatic thesis mutation is introduced. Confirmed causal evidence may
  deep-link to Builder; only a human Builder save changes the thesis.
- `WorldSignal` has its own ID, liveness, status, freshness, coverage, and
  response collection. It is never inserted per poll and never serialized as
  `GeoScope` before human placement.
- No live provider is activated by this plan. Provider adapters and geographic
  memory remain behind recorded physical-device and ordinary-use gates.
- Preserve unrelated worktree artifacts. Do not restart production services,
  apply production migration 022, flip the PWA, or merge/push the feature
  branch without the separate finishing/deployment choice.
- Python changes carry type hints. Errors fail loudly; no silent fallbacks,
  compatibility shims, mock production data, or one-use abstraction layers.

---

### Task 1: Enforce append-only authority and expose exact scope lineage

**Files:**
- Create: `dialectic/migrations/022_geo_scope_lineage.sql`
- Modify: `dialectic/schema.sql`
- Modify: `dialectic/geo_scopes.py`
- Modify: `dialectic/api/geo.py`
- Modify: `dialectic/deploy/seed_hormuz_geo.py`
- Test: `dialectic/tests/test_geo_scopes_pg.py`
- Test: `dialectic/tests/test_geo_api.py`

**Interfaces:**
- Add nullable `revision_action` and `review_note` columns. New writes use
  `place | propose | confirm | reject | redraw | supersede | ratify |
  place_signal`; legacy rows derive action from authority/supersession and
  `confirmed_empty` without rewriting history.
- Add a partial unique index on non-null `supersedes_id` and database triggers
  that reject UPDATE/DELETE on `geo_scopes`.
- `GeoScope` gains server-derived `review_state` (`accepted | proposed |
  rejected | superseded`) and nested `freshness` (`current | stale | expired |
  unknown | not_applicable`, with observation/retrieval/expiry timestamps).
- Add `GET /rooms/{room}/geo/{scope}/review`, returning the root ID, current
  successor, ordered full lineage, and a server-derived subject destination;
  message destinations include their owning thread ID.
- Add `POST .../{scope}/ratify`, `/redraw`, and `/supersede`. The server copies
  subject/provenance for every successor; redraw accepts only replacement
  label/geometry/note. Existing confirm/reject become locked atomic successor
  writes and new rejection uses `revision_action='reject'`, not
  `source_state='confirmed_empty'`.
- Remove the seed script's default Amo identity. It requires explicit
  `--confirmed-by` and an acknowledgement that the named human inspected the
  geometry; reruns remain mechanically idempotent.

- [ ] Add failing PostgreSQL tests for mutation triggers, single-successor
  uniqueness/concurrency, source/freshness/review separation, legacy rejection
  derivation, ratification, redraw, supersession, full lineage, and exact event
  payloads.
- [ ] Add failing API tests for room/reading/message history, message thread
  resolution, membership/token fences, server-owned subject copying, stale
  target 409, malformed redraw geometry, and atomic rollback on event failure.
- [ ] Run the focused tests red and record the expected failures.
- [ ] Implement migration, service, routes, seed hardening, and transaction
  boundaries with one canonical aliased live predicate shared by Atlas and
  Field subject resolution.
- [ ] Run focused tests green, then the full backend suite with zero skipped
  geo/World guard tests.
- [ ] Append the behavioral decisions and off-host safety ref to `JOURNAL.md`.
- [ ] Commit Task 1.

### Task 2: Make scope review/history universal and list-first

**Files:**
- Modify: `dialectic/frontend/app/src/types/geo.ts`
- Modify: `dialectic/frontend/app/src/lib/api.ts`
- Modify: `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/focus/FocusSurface.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/focus/FocusWorld.tsx`
- Create: `dialectic/frontend/app/src/components/workspace/focus/ScopeReview.tsx`
- Modify focused navigation, Atlas, Focus, and World tests.

**Interfaces:**
- Globe and “On the map” selection navigate to the existing object axis as
  `geo_scope:<root-id>`; no new route or state owner.
- `FocusSurface` recognizes a geo-scope object and loads the review projection.
- `ScopeReview` shows current placement, resolved subject destination, separate
  authority/source/freshness/review chips, then complete dated lineage with
  actor, action, note, provenance, and geometry summary.
- Live proposals offer Confirm/Reject; accepted placements offer Ratify when
  no human act is recorded, Redraw, and Supersede. Guests get read-only state.
  After a write, retain the root scope ID and refresh both review and Atlas.
- `FocusWorld` keeps placement and causal work but delegates scope review to
  the single inspector. New reading placement supersedes the selected prior
  placement when correcting it instead of creating an accidental sibling.

- [ ] Write failing contract/navigation tests proving room, reading, and
  message scopes all open the same inspector and message subjects retain the
  exact thread/message destination.
- [ ] Write failing component tests for full history, legacy rejection,
  ratify/redraw/supersede actions, guest read-only behavior, refresh semantics,
  and complete operation with the lazy globe absent.
- [ ] Run the focused tests red.
- [ ] Implement the shared inspector and API/type/navigation changes while
  preserving the Dark Roast and list-first presentation.
- [ ] Run focused tests green, then frontend test/lint/build gates. Record the
  pre-existing `WhatsNewPanel` failure exactly if it remains.
- [ ] Append the UI/navigation decision to `JOURNAL.md` and commit Task 2.

### Task 3: Bind geographic evidence to a thesis through Field

**Files:**
- Modify: `dialectic/field_marks.py`
- Modify: `dialectic/api/field.py`
- Modify: `dialectic/frontend/app/src/types/workspace.ts`
- Modify: `dialectic/frontend/app/src/components/workspace/focus/ScopeReview.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/fieldDisplay.ts`
- Modify relevant backend/contract/frontend tests.

**Interfaces:**
- Add `context` to `FIELD_RELATIONS` and the mirrored TypeScript vocabulary.
- Permit a `rooms` Field subject only with exact field grammar
  `thesis_node:<book-id>:<node-id>` and only for causal relations.
- A causal mark has exactly two semantic roles independent of subject order:
  the accepted live geo scope is the evidence; the room-field reference is
  the target thesis node. Payload stores the node label for historical display,
  never as authority.
- Before insertion, the backend proves the room is currently bound to the
  named book and the named node exists in the authenticated trading structure.
  Wrong room/book/node, proposed/rejected/expired scope, or unavailable bridge
  fails with no mark and no event.
- `ScopeReview` offers supports/challenges/context plus an existing thesis-node
  picker. The resulting mark immediately uses normal Field review. Field and
  Focus render the source scope, relation, node label, review state, and a
  Builder deep link; no relation depends on subject array order.

- [ ] Write failing real-Postgres tests for every validation boundary and for
  confirm/contest/correct preserving the causal subjects and attribution.
- [ ] Write failing frontend tests for node selection/payload, unavailable
  proposal action, display of adjudicated bindings, and Builder navigation.
- [ ] Run focused tests red.
- [ ] Implement the backend and frontend changes without adding a thesis
  mutation relay or database migration.
- [ ] Run focused tests green, full backend, and frontend test/lint/build gates.
- [ ] Append the causal-binding decision to `JOURNAL.md` and commit Task 3.

### Task 4: Introduce fenced ephemeral WorldSignal and durable placement

**Files:**
- Create: `dialectic/world_signals.py`
- Modify: `dialectic/atlas_objects.py`
- Modify: `dialectic/api/atlas.py`
- Modify: `dialectic/api/geo.py`
- Modify: `dialectic/frontend/app/src/types/geo.ts`
- Modify: `dialectic/frontend/app/src/types/atlas.ts`
- Modify: `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/world/WorldView.tsx`
- Modify focused backend and frontend tests.

**Interfaces:**
- `WorldSignal` IDs are `world_signal:<provider>:<source-id>` and include
  room/layer, server-owned geometry/provenance, source condition, freshness,
  coverage, observation/retrieval/expiry times, and read-only label/details.
- The in-process snapshot owner accepts bounded replacement snapshots from
  future adapters. No public writer exists and no provider/mock data is
  registered in production by this task.
- `GET /users/me/atlas?signals=1` adds separate `signals` and
  `signal_sources`; it fences snapshots through the same eligible-room IDs as
  nodes/scopes. Default Atlas responses remain source-compatible and signal
  source absence is explicitly `not_configured`, never inferred from `[]`.
- World renders current signals and a complete text list separately from
  scopes. Ephemeral signals are read-only: no Confirm/Reject and no row-backed
  Focus actions.
- `POST /rooms/{room}/world-signals/{signal-id}/place` copies the currently
  live server-held signal into one durable `source_reported` scope with
  `revision_action='place_signal'`, `created_by` set to the human, subject
  `{entity:'rooms', id:room, field:'world_signal:<provider>:<source-id>'}`, and
  intact provider/source/credit/observed timestamps. Expired, missing, or
  cross-room signals fail without a row/event.

- [ ] Write failing backend tests for member/nonmember fencing, status versus
  freshness, expiry, bounded replacement, explicit not-configured state,
  read-only API shape, and provenance-preserving durable placement.
- [ ] Write failing frontend tests proving signals render separately, expose
  no scope review actions, remain visible in the no-WebGL list, and refresh to
  the durable scope after placement.
- [ ] Run focused tests red.
- [ ] Implement the domain contract, fenced projection, placement route, and
  renderer/list integration without activating a provider.
- [ ] Run focused tests green, then backend and frontend gates.
- [ ] Append the WorldSignal boundary to `JOURNAL.md` and commit Task 4.

### Task 5: Add participant sight and close the qualification ledger

**Files:**
- Modify: `dialectic/llm/world.py`
- Modify: `dialectic/llm/tools.py`
- Modify: `dialectic/llm/prompts.py`
- Modify: `dialectic/tests/test_world_tools.py`
- Modify: `docs/WORLD_PROVIDERS.md`
- Modify: `docs/WORLD_LENS_VISION.md`
- Replace: `PLAN.md`
- Modify: `JOURNAL.md`
- Add or modify isolated browser acceptance under `docs/superpowers/acceptance/`.

**Interfaces:**
- Add a read-only `world_query` participant tool over the current room. It can
  resolve a durable scope by exact label/ID, report current scope authority,
  review state, source condition, freshness, lineage summary, and associated
  causal Field bindings. When signal snapshots exist it reports their explicit
  source status/coverage; unknown is never zero. It never writes or invents
  geometry.
- Existing `propose_geo_scope` remains the only participant geography writer
  and clearly states where humans review proposals.
- Use the existing encoded World URL for “show me”; do not add `world_show` or
  a second camera serialization.
- Root `PLAN.md` becomes the zero-context current-state handoff with correct
  test paths/commands, separate checkout/commit/push/runtime/public/UAT truth,
  the exact physical-device and one-week ordinary-use protocol, and explicit
  closed gates for providers and geographic memory.
- Provider ledger records current OSM operating limits, AIS no-SLA/no-replay
  and unresolved terms, OpenSky written-agreement exclusion, exact FIRMS key/
  dataset requirement, and USGS as technically valid but thesis-unselected.

- [ ] Write failing tool tests for exact scope lookup, causal-binding output,
  status/freshness separation, provisional language, membership/room fence,
  timeout ordering, and unknown-not-zero.
- [ ] Run focused tests red, implement the participant query, then run them
  green and verify registry/persona contracts.
- [ ] Build an isolated authenticated browser acceptance covering House ↔
  World ↔ review, room/reading/message scope history, ratify/redraw/supersede,
  causal mark creation and Field adjudication, signal read-only/placement with
  a test-only server snapshot, 390 px, keyboard, reduced motion, and failed
  WebGL. Never touch production data.
- [ ] Run backend full suite; frontend tests, lint, build; migration apply on
  the test database; browser acceptance; `git diff --check`; and docs guard if
  present. Record every exact result and known exception.
- [ ] Update the provider/vision/current-state documents and `JOURNAL.md`; do
  not claim physical-device use or the one-week gate occurred.
- [ ] Commit Task 5.

## Definition of Done

- The five tasks are committed and each task review plus final whole-branch
  review has no unresolved Critical/Important issue.
- Migration 022 applies to the test database; append-only, single-successor,
  transaction, fence, and causal-binding guards are executed, not skipped.
- Backend full suite passes. Frontend test/lint/build passes except only an
  exact, explicitly unchanged pre-existing failure if independently verified.
- Isolated authenticated browser acceptance proves the full software loop at
  desktop and 390 px without production mutation.
- The branch remains isolated. Production migration/restart/release, branch
  merge/publication, real human ratification, physical-device acceptance, one
  week ordinary use, provider activation, and geographic memory are reported
  as distinct pending gates unless separately executed with evidence.

