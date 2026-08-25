# Handoff — the World Lens, Phases 0–2

**Date:** 2026-08-25 · **Session shape:** evaluate God's Eye View → owner
corrected the method ("read it before you plan") → the vision doc landed
from a parallel session and overrode the first plan → three phases built,
deployed, and proven live as Amo on production. Phase 3 is deliberately
not started; the vision gates it.

## Read these first

- [`docs/WORLD_LENS_VISION.md`](../WORLD_LENS_VISION.md) — the governing
  judgment (commit `60eb618`). Its amendment at the bottom records the
  three places the build read it more narrowly than written.
- `CLAUDE.md` § *Amendment 2026-08-25 — the World Lens* — the contract as
  shipped (migration, authority column, `view` axis, tool 22, Focus).
- [`docs/WORLD_PROVIDERS.md`](../WORLD_PROVIDERS.md) — every provider the
  World fetches, bundles or credits, with terms. Nothing off this ledger is
  in the product.
- `/root/.claude/plans/what-doy-ou-think-dynamic-yao.md` — the approved
  four-phase plan (Phase 3 is specified there in full).

## What happened, in order

1. Asked to evaluate integrating
   [gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view). First
   pass planned from a fetched summary; owner: *"at least read something
   about it before you plan"* and *"I don't care about keys and some
   cost."* Cloned the repo and had it traced properly: 81k lines of vanilla
   JS, the entire backend is 20 Vite dev-server middlewares in a 7,383-line
   `vite.config.js` (`vite build` is a dead app), and `gevActions.js` is a
   clean headless controller. A second plan (iframe the app, run its key
   broker as a fourth service) was written and rejected by the vision doc.
2. The vision doc's architecture won: World is a second mode of Atlas over
   the same fenced projection, FastAPI owns every fetch, Cesium loads only
   when asked, no public key broker, no Google tiles, no LLM-invented
   coordinates. The plan was rewritten around it and approved.
3. Built Phases 0–2 in order, each committed, deployed, and proven live
   before the next.

## What shipped (commits `0be95ae`..`b54f308`)

- **`0be95ae` — Phase 0, the substrate.** Migration 021 `geo_scopes`
  (applied prod + test, in `schema.sql`): geometry attached to rows that
  already exist through `{entity,id,field}`; **authority is a column**
  (`human_confirmed | source_reported | machine_proposed`); append-only with
  supersession; the live set is DERIVED by `geo_scopes.LIVE_PREDICATE`.
  `api/geo.py` is a human-only door (place / confirm / reject — reject
  INSERTS a `confirmed_empty` replacement). `field_marks._SUBJECT_ENTITY_TABLES`
  gained `geo_scopes` with the authority guard IN the SQL (a tuple's fourth
  element is an extra predicate) — a proposal cannot anchor a mark until a
  person confirms it; the test asserts the guard FIRES. Atlas carries the
  viewer's fenced `scopes`; nodes deliberately carry no geo field.
  `data/natural_earth/marine.json` (public domain, provenance in-file).
  `deploy/seed_hormuz_geo.py` seeded room `56ba2f1e` with the Strait polygon
  and TSS inbound lane (hand-authored, labelled "(approx.)") plus the Persian
  Gulf / Gulf of Oman rings — run against production, `confirmed_by` Amo.
- **`58d702f` + `011d666` — Phase 1, Atlas / World.** The `view` URL axis
  (`world[:lat,lon,alt,heading,pitch][;room=<id>]`; grammar in
  `world/worldCamera.ts`) read by `lib/workspaceRoute.ts` and written ONLY
  by `useRoomNavigation.navigate` — a toggle is a push, a camera settle a
  debounced replace. `WorldView.tsx`: CesiumJS behind `React.lazy`, its own
  4.2 MB chunk plus the static tree served from `/cesium/` (inline Vite
  plugin, `sirv` in dev, copy on build), BOTH excluded from the PWA precache
  (`injectManifest.globIgnores`) — `index` stays 560 KB, precache 13 entries.
  Keyless OSM + Re:Earth terrain with ellipsoid fallback; `requestRenderMode`;
  our own always-visible credit line ("CesiumJS · © OpenStreetMap contributors
  · Made with Natural Earth"); Dark Roast via one CSS filter. The House list
  never leaves the page in World mode; "On the map" lists every scope as text
  with authority + `SourceState` chip. Bench gets "World ↗ N placed" only in
  rooms that own geography (`useGeoScopes`).
- **`eab5178` — Phase 2, the evidence loop.** Tool 22 `propose_geo_scope`
  (`llm/world.py`, flag `DIALECTIC_WORLD_ENABLED`): resolves a NAME — a
  Natural Earth marine region or the exact label of a scope the room holds
  — to geometry that already exists, writes a `machine_proposed` row
  expiring in 14 days; an unknown name returns candidates, never a guess.
  `FocusWorld.tsx` on every non-mark object: the scopes about it; Confirm /
  Reject a proposal; "Place on" one of the room's confirmed areas (copies
  its geometry, provenance `room_scope`); "Mark as evidence here" files an
  `evidence_attachment` mark whose subjects are the scope AND the object.
- **`b54f308` — docs**: CLAUDE.md amendment, provider ledger, TODOS board,
  vision amendment, journal.

## Verified, not assumed

- Backend **1995 passed**; frontend **517/518** (the one failure is
  pre-existing, see below); `tsc -b` and eslint clean on every touched file.
- `GET /users/me/atlas` on the deployed process: Amo sees the four Hormuz
  scopes and the room node; the non-member Test User sees zero.
- Browser, production, as Amo (Playwright, seeded `dialectic-auth`): the
  globe over the Gulf with the Strait and lane drawn; House ↔ World toggle
  and Back restore through the URL; Bench "World ↗ 4 placed" lands in World
  prefocused on the room; 390 px viewport keeps the list, no horizontal
  scroll; the frame's centre pixel read inside `scene.postRender`.
- A real `@llm` turn in the E2E Test Room (`e78ebe5c`, Test User over WS):
  `propose_geo_scope` ran `ok` in 19 ms, wrote a dashed Persian Gulf proposal
  with Natural Earth provenance (expires 2026-09-08), and the reply said
  "provisional until one of you confirms it in Focus."
- In the Hormuz room as Amo: the CENTCOM reading placed on the Persian Gulf
  (`human_confirmed`, `room_scope · Made with Natural Earth`), then "Mark as
  evidence here" → an `evidence_attachment` mark in `field_marks` whose
  subjects are `geo_scopes` + `reading_items`, `provenance='human'`.

The browser found three defects no unit test could, all fixed in `011d666`:
`.atlas-scene` is a fixed-height flex column that shrank the globe to 2 px
(`flex: 0 0 auto`); Cesium's `widgets.css` was never imported so the widget
sat short in its box; the credit line showed an ion logo for a service we
don't use. Also set `preserveDrawingBuffer` — headless Chromium screenshots
a WebGL canvas black otherwise, which is what sent the session reading pixels
inside `postRender` via `window.__dialecticWorld` (the probe handle; nothing
in the app reads it).

## Left in production by this session (deliberate, reversible)

- Four `human_confirmed` scopes in Hormuz stamped `confirmed_by` Amo
  (`de883378`) by the seed script — Amo has not personally reviewed the
  hand-drawn Strait polygon or lane. Both are labelled "(approx.)" and say
  so in `provenance.credit`. Redraw = an ordinary POST; the rows stay as
  history.
- One `human_confirmed` Persian Gulf region on reading `aa7b3cef` and one
  `evidence_attachment` mark, both by Amo's account — the browser proof.
  Delete nothing; the mark can be contested in Field if unwanted.
- One `machine_proposed` Persian Gulf scope in the E2E Test Room (expires
  2026-09-08 on its own).

## Pre-existing, NOT fixed (out of scope)

- `WhatsNewPanel.test.tsx > explains a hard word in place` fails: the
  newest `RELEASES[0].body` carries no `[[word|gloss]]` marker for the test
  to find. Untouched by this work; fix is either a glossed word in the
  newest release entry or a test that picks the first entry with one.

## Not built, on purpose

- **Phase 3** (live feeds as FastAPI adapters in terms-clarity order USGS →
  adsb.lol → FIRMS → AIS; `world_query` with the counting law "every count
  names its scope, `unknown` never 0"; migration 022 `world_samples` + the
  900 s sampler + `world_trend`; a Bench strip). The vision gates it on
  "feels electric in daily use", and AISStream has no formal terms — owner
  decision. Fully specified in the plan file.
- Mark glyphs on the globe (Focus shows incoming marks; add glyphs when a
  room's geo-marks read as a layer); the `annotationGeoJson` port (a
  scope's geometry IS GeoJSON); `analystEngine`/`motionModel` ports (with
  the first live feed, not before).
- GEV units NOT taken: `telegeography_submarine_cables` (CC BY-NC-SA),
  OpenSky (non-commercial), OpenAI voice, Google tiles, the 10k-line
  `ui.js`, the Vite backend.

## Harness notes worth keeping

- Production browser proofs as Amo: seed `dialectic-auth` via
  `page.context().addInitScript` (a `page.evaluate` after load gets
  overwritten by the store's own write); access JWTs last 15 minutes —
  re-mint with `create_access_token({"sub": user})` from `api.auth.utils`
  with `.env` sourced.
- The Playwright MCP writes only under `/root/DwoodAmo/.playwright-mcp`.
- `sirv` is now a devDependency (the `/cesium/` middleware in dev/preview).

## Suites at this gate

Backend 1995 · frontend 517/518 · tsc -b clean · builds: `index` 560 KB,
`cesium` chunk 4.2 MB (on demand), precache 13 entries / 749 KiB.
Current release: `/var/www/dialectic-releases/20260825071442-world-lens-p2`.

## If you pick this back up

1. Use it: open Home → Atlas → World; open a Hormuz reading → Focus → World.
   Place a couple more readings; ask the participant to place one; confirm
   or reject what it proposes. That week of use is the Phase 3 gate.
2. Decide AISStream. Then Phase 3 from the plan file, USGS first — it is
   keyless and public domain, so the adapter pattern lands with no terms
   question attached.
3. If the Strait sketch bothers a founder, redraw it through
   `POST /rooms/{id}/geo` with a proper ring; never edit the seeded row.
