# World Lens truth-before-spectacle — zero-context handoff

Current **2026-08-25**. Keep source, checkout, publication, runtime, served
bytes, activation, and human qualification separate. Do not call them all
“deployed.”

## Truth ledger

| Surface | Current truth |
|---|---|
| Production checkout | `/root/DwoodAmo` is out of scope and intentionally untouched. |
| Isolated worktree | `/root/DwoodAmo/.worktrees/world-lens-truth-before-spectacle` |
| Branch | `codex/world-lens-truth-before-spectacle` |
| Safe baseline | `origin/codex/world-lens-pre-phase2.5-20260825` = `3eabd4a` preserves prior Phase 0–2 source off-host. |
| Task commits | Plan `a690fe6`; lineage `91014b8..808e17e`; review `fef716a..32e8333`; causal Field `0d2ae3c..472cc5a`; WorldSignal `48e9288..3dd9089`; participant sight `e751968`. Use `git log -12 --oneline` for any later Task 5 docs commit. |
| Push/publication | **Not pushed** unless later evidence says otherwise. The safety ref is not publication of this branch. |
| Production migration 022 | **Not applied.** Exercised only on isolated/test PostgreSQL. |
| Backend runtime | **Not restarted or loaded from this worktree.** |
| Frontend served bytes | **No release flip/nginx reload.** A local build is not served/public truth. |
| Public browser | **Unverified for this branch.** Droplet-local Playwright is isolated proof, not public delivery or physical UAT. |
| Providers | **None activated.** `world_signal_store` starts empty; no adapter, poller, public writer, or fixture data. |
| Geographic memory | **Closed.** No sample/replay table or recorder. |
| Human qualification | Physical-device and one-week ordinary-use gates remain pending. |

## What exists on this branch

1. Migration `dialectic/migrations/022_geo_scope_lineage.sql` and fresh schema
   enforce append-only `GeoScope`, one successor, typed actions, and atomic
   scope/event writes.
2. House/World/Focus share a root-stable scope inspector with exact
   room/reading/message destinations and message-thread retention.
3. Human-only causal Field binding connects accepted live geography to a
   current authenticated thesis node. Field adjudication stays append-only;
   Builder remains the sole thesis writer.
4. `dialectic/world_signals.py` owns bounded immutable snapshots. Atlas opt-in
   projection and bodyless human placement keep observations ephemeral until a
   person copies current same-room server bytes into a durable scope.
5. `world_query` composes `GeoScopeService`, `FieldMarkService` semantic roles,
   and `WorldSignalStore`; it is exact-room, read-only, bounded, and preserves
   not-configured/unavailable/unknown/empty/zero. `propose_geo_scope` remains
   the sole participant geography writer and creates a reviewed proposal only.

## Exact local verification

```bash
cd /root/DwoodAmo/.worktrees/world-lens-truth-before-spectacle/dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python -m pytest -q tests/
python -m pytest -q \
  tests/test_world_tools.py tests/test_tools_registry.py tests/test_prompts.py
psql postgresql://root@localhost/dialectic_test -v ON_ERROR_STOP=1 \
  -f migrations/022_geo_scope_lineage.sql

cd frontend/app
npm test -- --run
npm run lint
npm run build

cd ../../../
python docs/superpowers/acceptance/2026-08-25-world-lens-truth-acceptance.py
git diff --check
```

These PostgreSQL guards must execute, not skip:

```bash
cd dialectic
python -m pytest -q \
  tests/test_geo_scopes_pg.py tests/test_field_causal_concurrency_pg.py \
  tests/test_field_origination_pg.py tests/test_world_signals.py \
  tests/test_atlas_pg.py
```

Inherited frontend baseline before Task 5: one test failure
`WhatsNewPanel > explains a hard word in place` (newest release body has no
glossary marker); two lint findings at `MessageList.tsx:247` and
`HomeActivityPulse.tsx:379`. Re-run and report exact current results.

## Physical-device protocol — pending

Use the reachable public origin after a separately authorized release, never
localhost/mosh/droplet Playwright. Record device/OS, installed-PWA/browser,
viewport, network, release asset hash, and UTC time. On iPhone, iPad, and one
desktop:

1. cold-open House and enumerate all scopes/signals without World/WebGL;
2. House -> World -> House, Back/Forward, and a shared `world;room=<uuid>` URL;
3. open room/reading/message scope history; verify exact branch/message;
4. ratify, redraw, supersede; reload and verify one successor/event per act;
5. create supports/challenges/context marks; confirm, contest, correct; verify
   Builder opens the bound book but no automatic thesis edit occurs;
6. inspect a read-only signal, place it, verify ephemeral and durable rows stay
   distinct, then refresh Atlas/room projections;
7. repeat at 390px, keyboard-only, reduced motion, offline/reconnect, and
   failed/no-WebGL; the complete text list must remain usable;
8. retain screenshots, URLs, API responses, geometry, row/event counts, and
   every failure. Simulation/emulation is not physical proof.

## One-week ordinary-use protocol — pending

After provider terms and a bounded adapter are separately approved, keep a
daily ledger for seven ordinary Hormuz-use days:

- source condition/freshness/coverage, outages, reconnects, dropped/replay
  gaps, bytes/requests/cost;
- observations ignored, inspected, placed, bound, confirmed, contested,
  corrected, or superseded;
- exact discussion/Field/thesis decision changed by the layer, or “none”;
- false positives, stale/unknown cases, and any absence-as-zero confusion;
- physical-device performance, battery, thermal, and accessibility.

Pass requires at least one documented causal decision improved, no authority/
fence/unknown-as-zero breach, acceptable operations, and explicit owner
approval. “Interesting dots” is failure.

## Closed provider/memory gates

- OSM tiles: modest interactive rendering only; no SLA; bulk/offline/prefetch
  prohibited. Move provider/self-host before scale.
- AISStream: no SLA, no replay, slow-consumer loss, insufficient product/data
  terms. **Closed.**
- OpenSky: operational integration requires prior written agreement.
  **Excluded without it.**
- FIRMS: MAP_KEY + exact dataset + bounded area/day/budget + thesis selection.
  **Closed.**
- USGS: technically valid real-time GeoJSON, but thesis-unselected.
- Geographic memory/replay: closed until ordinary use proves value and a
  retention/privacy design is approved.

## Integration and rollback choices

Owner may later: (A) keep isolated; (B) push for review without activation;
(C) merge source while leaving migration/runtime/release/provider gates closed;
or (D) authorize a separate production migration/backend/frontend release.
No option is implied.

Before activation, rollback is branch deletion/revert. After migration 022,
do **not** restore UPDATE/DELETE semantics: roll code forward or restore a
validated backup under separate authorization. Frontend rollback is an exact
known-good release symlink flip. Provider rollback disables the adapter and
removes ephemeral snapshots; durable human placements remain append-only.
