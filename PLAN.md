# God's Eye x Dialectic — live production handoff

Current **2026-08-25 America/Chicago**. This is a zero-context handoff for the
production repository at `/root/DwoodAmo`. God's Eye means the World Lens / World
Synapse program, not an Epic EHR integration.

## CURRENT PRODUCTION TRUTH

| Surface | Verified state |
|---|---|
| Source | `master`; live application code `85fed388444abfaea2cabe50d1af41a902fa05c0`. Resolve the later documentation-only handoff commit with `git log -1 --format=%H -- PLAN.md`. |
| Publication | `master` is intended to be pushed to `origin/master` after this handoff is committed; verify equality before relying on it. |
| Database | Migration `022_geo_scope_lineage.sql` applied to production. Six existing scopes survived. Columns, check, unique-successor index, and reject-UPDATE/DELETE triggers verified. |
| Database backup | `/var/backups/dialectic/20260826T031404Z-5f50c122-world-synapse-before.dump`, SHA-256 `1dc4ffdb7988efb8f3397162abfedb96620cba81cbdacfb4d7c92e9fd210f5af`, PostgreSQL custom dump, mode 600. |
| Backend | `dialectic.service`, checkout `/root/DwoodAmo/dialectic`, PID `1941516`, active since `2026-08-25 22:20:53 CDT`; DB, Redis, scheduler, and public/local health green. |
| Activation | `DIALECTIC_WORLD_ENABLED` is unset and its code default is ON; the live registry contains `world_query` and `propose_geo_scope`; runtime inspection returned `world_tools_enabled=True`. |
| Frontend | `/var/www/dialectic-current` -> `/var/www/dialectic-releases/20260826T032052Z-world-synapse-85fed38`; nginx reloaded and active. |
| Served hashes | `index.html` `6f3babc16c004037dd5fca07f5be3debca4fb58aa48f9d17808556f4b59e9dcc`; `sw.js` `791bb5375305dce6b89d321f88ad212cae06be375d9b52b4fe9054325b068058`. Public bytes matched the selected release. |
| Public browser | Authenticated Chromium against `https://dialectic.somacura.org`: 10/10 checks passed; House loaded no World/Cesium bytes, World fetched one lazy JS bundle, five real Hormuz scopes and all provenance rendered, canonical Focus opened, failed WebGL retained the complete list/provenance and collapsed the canvas, no page errors/HTTP 500s. |
| Public evidence | `/var/backups/dialectic/20260826T032052Z-world-synapse-85fed38-public/`; qualified images are `public-world-globe-settled.png` and `public-world-webgl-failure.png`; `results.json` is the machine ledger. |
| Production content | Five live Hormuz scopes project publicly. One real geographic `evidence_attachment` Field mark links a reading to the Persian Gulf. There are currently **zero** geography-to-thesis-node causal bindings; no fake binding was created for qualification. |
| Providers | CesiumJS, OSM raster, optional Re:Earth terrain, and Natural Earth reference geometry are active under the provider ledger. No live `WorldSignal` provider adapter, poller, or sample/replay store is configured. |
| Human qualification | Production delivery is proven. Physical phone/tablet/desktop UAT and one week of ordinary Hormuz use remain unqualified. |

The production deployment manifest is
`/var/backups/dialectic/20260826T032052Z-world-synapse-85fed38.manifest`.

## DECISIONS WITH RATIONALE

1. **God's Eye is Dialectic's sensory body, not a second application.**
   Rejected: iframe, fork, microfrontend, or separate globe workbench. It lost
   because it would split object identity, navigation, authority, annotations,
   participant state, and mobile fallback.
2. **House and World are two views of one Atlas projection.** Rejected: make
   World the universal home screen. It lost because geography is not meaningful
   for every room and House is the complete accessible authority.
3. **One canonical object identity crosses House, World, Focus, Field, URLs,
   and participant results.** Rejected: renderer-owned marker IDs. It lost
   because they cannot preserve lineage, review, deep links, or room fences.
4. **Geographic authority is append-only lineage.** Rejected: UPDATE/DELETE
   convenience. It lost because historical evidence and the decision record
   must remain reproducible; migration 022 now enforces this in PostgreSQL.
5. **Causal meaning is a Field-owned semantic relation.** Rejected: infer map
   rays from proximity, text similarity, or model confidence. It lost because a
   thesis node has no geographic coordinate and visual proximity is not causal
   evidence.
6. **The authority ladder is observation/proposal -> human placement -> durable
   GeoScope -> explicit Field binding -> human review -> optional Builder edit.**
   Rejected: provider or model auto-write into geography/thesis. It lost because
   it collapses observation, interpretation, and authority.
7. **Cesium is genuinely lazy and excluded from the PWA precache.** Rejected:
   Rollup manual Cesium chunk ownership. It lost because it introduced eager
   shell preload, a circular lazy graph, and a 495 KB service-worker burden.
   `scripts/verify-lazy-cesium.mjs` now fails the production build on regression.
8. **Provider signals remain ephemeral until explicitly placed.** Rejected:
   store every tick as geographic memory. It lost because provider terms,
   retention, coverage, replay, privacy, and ordinary-use value are unresolved.
9. **No live signal provider was activated in this wave.** Rejected: add AIS or
   an easy decorative feed to make the globe feel alive. It lost because AIS
   lacks adequate terms/SLA/replay and an unselected feed is spectacle without
   a named causal decision.
10. **Production proof and human qualification remain separate.** Rejected:
    call a green deployment ordinary-use success. It lost because public bytes
    prove delivery, not whether the instrument changes Amo and Dan's reasoning.

## DO-NOT-RELITIGATE LIST

- Do not rebuild or embed the upstream God's Eye View app. The approved
  architecture ports bounded rendering/lifecycle patterns into Dialectic's
  existing owners.
- Do not add a second router, object store, annotation table, agent persona, or
  source-state vocabulary. `useRoomNavigation`, `GeoScope`, Field, the existing
  participant, and the evidence vocabulary are settled owners.
- Do not weaken migration 022's UPDATE/DELETE rejection or one-successor law.
  Room deletion has no product contract; design tombstones/retention before
  adding one instead of erasing authority by cascade.
- Do not infer coordinates from prose or allow an LLM/provider to create
  authoritative geometry. `propose_geo_scope` resolves only existing named
  geometry and remains human-reviewed.
- Do not convert unavailable, partial, stale, rate-limited, expired, or
  unconfigured source state into empty or zero.
- Do not auto-edit the thesis from a map interaction, signal, watch, or score.
  Builder remains the sole thesis writer.
- Do not make Cesium part of the shell or service-worker precache. Users who
  never open World pay no globe JS/GPU cost.
- Do not treat a dead globe as loss of evidence. The complete DOM list,
  provenance, selection, Focus, and actions remain usable without WebGL.
- Do not target `dialectic/deploy/dialectic.service` or `/opt/dialectic/current`
  on this host. The installed unit is `/etc/systemd/system/dialectic.service`
  and runs the production git checkout directly.
- Do not fabricate production Field bindings or reviews for a demo. A real
  causal mark must express a real human judgment through the visible product.
- Do not treat loopback browser proof as physical-device UAT or one-week use.

## OPEN QUESTIONS — ASK BEFORE DECIDING

1. **First Sense provider:** which exact Hormuz thesis question and source can
   change a decision? AISStream remains closed pending terms/license,
   redistribution, outage, replay, and slow-consumer decisions. OpenSky needs a
   written agreement. FIRMS needs a MAP_KEY plus exact dataset and causal wedge.
   USGS is technically viable but thesis-unselected.
2. **World Memory:** whether any provider observation may be retained, for how
   long, under which privacy/license class, and with what deletion/export
   policy. Do not add a sample table before this ruling.
3. **First real causal binding:** which accepted Hormuz scope genuinely
   supports, challenges, or contextualizes which current thesis node. The owner
   must make this judgment in the product; do not infer or seed it.
4. **Physical qualification:** who will execute iPhone/iPad/desktop installed-
   PWA/browser UAT and where its evidence ledger belongs.
5. **Phase 4 activation:** explicit owner approval after the selected layer
   passes source terms, coverage/absence, cost, bounded-failure, list fallback,
   and one-week protocol design.
6. **Room retirement:** tombstone and geographic evidence retention/export
   semantics before any room-deletion route or direct operation is introduced.

## REPO / ENVIRONMENT ORIENTATION

### Canonical product and design

- `docs/superpowers/specs/2026-08-25-gods-eye-dialectic-fusion-program-design.md`
  — Siamese-twin contract and Phases 3–9.
- `docs/WORLD_LENS_VISION.md` — product direction and non-negotiable authority,
  provenance, performance, and accessibility boundaries.
- `docs/WORLD_PROVIDERS.md` — source-specific terms and activation ledger.
- `docs/superpowers/qualification/2026-08-25-phase-3-world-synapse.md` — source,
  disposable-browser, production, and public evidence ledger.

### Backend owners

- `dialectic/migrations/021_geo_scopes.sql` and
  `dialectic/migrations/022_geo_scope_lineage.sql` — geographic storage and
  immutable revision law; `dialectic/schema.sql` is the fresh-DB baseline.
- `dialectic/geo_scopes.py`, `dialectic/api/geo.py` — scope projection and the
  human revision door.
- `dialectic/field_marks.py`, `dialectic/api/field.py` — causal binding DTO,
  room/thesis validation, append-only review.
- `dialectic/atlas_objects.py`, `dialectic/api/atlas.py` — viewer-fenced House /
  enhanced World projection.
- `dialectic/world_signals.py`, `dialectic/api/world_signals.py` — bounded
  ephemeral signal owner and human placement. It intentionally starts empty.
- `dialectic/llm/world.py`, `dialectic/llm/tools.py` — `world_query` read sight
  and `propose_geo_scope` reviewed proposal path.

### Frontend owners

- `dialectic/frontend/app/src/hooks/useRoomNavigation.ts` — sole destination
  writer for room/scene/view/object/camera.
- `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.tsx` —
  House list, World shell, selection, causal DOM overlay, no-WebGL fallback.
- `dialectic/frontend/app/src/components/world/WorldView.tsx` — lazy Cesium
  renderer; presentation only.
- `dialectic/frontend/app/src/components/focus/FocusWorld.tsx` — lineage,
  provenance, review, placement, and Field doors.
- `dialectic/frontend/app/scripts/verify-lazy-cesium.mjs` and `vite.config.ts` —
  emitted-build enforcement for shell/SW isolation.

### Runtime

- Backend unit: `/etc/systemd/system/dialectic.service`; loopback `127.0.0.1:8002`.
- Public origin: `https://dialectic.somacura.org`.
- Frontend releases: `/var/www/dialectic-releases`; selected by
  `/var/www/dialectic-current`.
- Environment: `dialectic/.env`, never commit or print it.
- Legacy/dead trap: checked-in `dialectic/deploy/dialectic.service` targets
  nonexistent `/opt/dialectic/current`; do not use it.
- Frozen/dead frontend paths: root mobile packages and legacy static frontend
  are not the production reach surface; the React PWA is.

### Invariants

- Every query repeats authenticated viewer/room fences server-side.
- Root/historical/current scope IDs resolve to one current live lineage object.
- Scope, successor, review, and event writes remain atomic and append-only.
- Provider credentials and inaccessible geometry never enter browser bytes,
  URLs, screenshots, or participant context.
- Default Atlas retains its compatibility shape; causal/signal payloads remain
  enhanced opt-in projection fields.
- Renderer failure may remove only spatial presentation, never evidence truth.

## CONTINUED PROGRAM — EPIC IN THE ACTUAL SENSE

Execute only after the preceding phase's hard gate; do not collapse these into
one provider-first spectacle push.

1. **Phase 4 — First Sense:** one bounded provider for one Hormuz decision,
   truthful state/freshness/coverage, explicit human placement, seven-day
   value/error ledger.
2. **Phase 5 — Causal Airspace:** deterministic belief weather, drillable
   evidence constellations, participant-directed cited tours, and a Living
   World Brief that reports only causally material change.
3. **Phase 6 — Time and World Memory:** separately approved immutable capture,
   synchronized world-time/belief-time replay, and exact decision retrospectives.
4. **Phase 7 — Competing Futures:** precommitted geographic signatures,
   falsification watches, deterministic reality comparisons, human-adjudicated
   scorecards, never automatic thesis mutation.
5. **Phase 8 — World Echoes:** viewer-fenced cross-room causal implications and
   multi-room briefs with zero inaccessible-room leakage.
6. **Phase 9 — Command and Embodiment:** shared object/camera command, voice
   through the same typed destinations, wall-scale Dark Roast command deck, then
   evaluate spatial computing as a renderer—not a new authority surface.

The endpoint is not “more dots.” It is an inspectable living causal world where
every observation answers where it came from, how old it is, what claim it bears
on, who accepted that meaning, what would falsify it, and what was believed at
the moment of decision.

## VERIFICATION

### Source and publication

```bash
cd /root/DwoodAmo
git status --short
git rev-parse HEAD
git fetch origin master
git rev-list --left-right --count origin/master...HEAD
git diff --check
```

Pass: only known unrelated untracked paths remain; after the authorized push,
the divergence is `0 0` and `origin/master` equals `HEAD`.

### Database authority

```bash
cd /root/DwoodAmo
sha256sum dialectic/migrations/022_geo_scope_lineage.sql \
  /var/backups/dialectic/20260826T031404Z-5f50c122-world-synapse-before.dump
pg_restore --list \
  /var/backups/dialectic/20260826T031404Z-5f50c122-world-synapse-before.dump \
  >/dev/null
```

Expected migration hash:
`8f6987ef923ac18eea4455abf72e5b6bdd7c3005432593487b554fff4fcb32a3`.
Inspect production `geo_scopes` with the application `DATABASE_URL` and verify
the 022 columns, check, one-successor index, reject UPDATE trigger, and reject
DELETE trigger. Never test those triggers by mutating production rows.

### Runtime and public bytes

```bash
systemctl is-active dialectic nginx
systemctl show dialectic --property=MainPID,ActiveEnterTimestamp,SubState
curl -fsS http://127.0.0.1:8002/health
curl -fsS https://dialectic.somacura.org/health
readlink -f /var/www/dialectic-current
sha256sum /var/www/dialectic-current/index.html /var/www/dialectic-current/sw.js
curl -fsS https://dialectic.somacura.org/ | sha256sum
curl -fsS https://dialectic.somacura.org/sw.js | sha256sum
journalctl -u dialectic --since '2026-08-25 22:20:53' --no-pager
```

Pass: both services active; health reports DB/Redis connected and scheduler
fresh; PID is nonzero; selected release and public/local hashes match; no new
ERROR, traceback, exception, or HTTP 500 appears.

### Code gates

```bash
cd /root/DwoodAmo/dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/ -q
cd frontend/app
npm test -- --run
npm run lint
npm run build
```

Last full results: backend `2125 passed`; frontend `580 passed`; lint passed;
production build passed; emitted lazy-Cesium gate passed. Re-run before changing
application behavior, not merely for a documentation-only commit.

### Public browser and human use

Machine proof lives in
`/var/backups/dialectic/20260826T032052Z-world-synapse-85fed38-public/results.json`.
Re-run public authenticated acceptance after any served-code change. Physical
qualification must record device/OS/browser or installed PWA, viewport,
network, selected release hash, UTC time, visible sequence, screenshots, page
errors, and failures. One-week qualification must name the causal decision each
layer changed—or `none`—every day.

### Definition of done

The Phase 3 production wave is done when source is pushed, migration 022 and its
backup are verified, the restarted backend is healthy with tools enabled, the
selected public PWA hashes match, authenticated public acceptance passes House,
World, Focus, provenance, laziness, and failed-WebGL contracts, and every
remaining provider/physical/human-use gate is stated as open rather than implied.

The whole fusion program is not done until Phases 4–9 each pass their own
provider, retention, causality, privacy, accessibility, and ordinary-use gate.

## CONFLICT RULE

If implementation reality contradicts this plan, the builder flags the contradiction and stops — no silent improvisation, no quiet re-planning.

## AMENDMENTS
