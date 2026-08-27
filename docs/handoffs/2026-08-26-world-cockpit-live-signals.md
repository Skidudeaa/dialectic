# Handoff — the World cockpit and its live signals went to production

**Date:** 2026-08-26 (America/Chicago)
**Commits:** `a8fe8ee` (the build) and `0ebd535` (three reviewed fixes), on
`master`, pushed to `origin/master`.
**Live from:** backend PID `2832622` (started 19:27:37 CDT); PWA release
`20260827T003007Z-world-cockpit-0ebd535`.

## What the owner asked for

> "i need god's eye implementation in dialectic to actually resemble and
> function like the god's eye github project"

God's Eye View's claim is that *the sources are public and the data is real*.
A World with no feed cannot satisfy that, so this work opened the Phase 4
provider gate deliberately and per-provider, and rebuilt the globe's chrome to
match. Both halves are live.

## The function half — `dialectic/world_adapters.py`

`world_signals.py` was a complete, deliberately empty substrate. It now has a
producer: **`world_signals`, the sixteenth scheduled job**, 120 s, master
switch `WORLD_SIGNALS_ENABLED`.

| Provider | Feed | Key | Poll floor | Flag |
|---|---|---|---|---|
| `usgs` | earthquakes, `all_day.geojson` | none | 5 min | `WORLD_SIGNALS_USGS_ENABLED` |
| `adsb` | live aircraft, adsb.lol | none | job cadence | `WORLD_SIGNALS_ADSB_ENABLED` |
| `iss` | the ISS, wheretheiss.at | none | job cadence | `WORLD_SIGNALS_ISS_ENABLED` |
| `launch` | Launch Library 2 | none | 30 min | `WORLD_SIGNALS_LAUNCH_ENABLED` |
| `firms` | NASA FIRMS VIIRS fires | **`FIRMS_MAP_KEY`** | 10 min | `WORLD_SIGNALS_FIRMS_ENABLED` |

**None of these flags are in the live `.env`.** They default ON, which is why
everything polls. Add them explicitly if you want a switch you can flip
without a code change. `FIRMS_MAP_KEY` is unset, so fires report
`not_configured` and never touch the network.

Laws this module obeys, and which a future session must not quietly relax:

- **It writes no database row and creates no geography.** Placement through
  `api/geo.py` remains the only door from observation to authority.
- **The room fence is the coverage boundary.** A signal is offered to a room
  only if it falls inside that room's own *accepted* scopes (live bbox + 1.5°,
  24 rooms max). A room that has placed nothing receives nothing. The ISS is
  the one deliberate global exception and its `coverage` string says so.
- **Absence is never silently zero.** Timeout → `unavailable`; 429/503 →
  `rate_limited`; no key → `not_configured` *without touching the network*, and
  a test fails if it does; one room's fetch failing → `partial`; a successful
  empty poll → `ok` with zero signals.
- **Per-provider poll floors exist because 120 s is right for aircraft and rude
  to a ~15 requests/hour anonymous tier.** Do not collapse them into the job
  interval.

## The resemble half — the cockpit

- **Six sensor shaders copied verbatim** from God's Eye View (MIT, © 2026
  Bilawal Sidhu) into `world/shaders/`. The GLSL is unedited so upstream fixes
  re-apply by diff. **Code only** — no dataset, no 3D model, no provider data
  came from that repository; its MIT grant does not cover those.
- `worldStyleStages.ts` is upstream's `_initStages` recast instance-scoped,
  because a globaled stage set outlives the viewer a React route unmounts. Two
  invariants: a zero-intensity stage is **disabled**, not merely transparent;
  and the animation clock runs only while a visible animated shader needs it —
  `requestRenderMode` is on, so a permanently running rAF silently converts the
  idle globe into a continuously drawn one.
- **`WorldHud.tsx` is ordinary DOM on purpose.** Upstream draws its readouts
  inside the fragment shader as seven-segment glyphs — unreadable to a screen
  reader and absent exactly when WebGL is. Every number in the HUD also exists
  in the complete text list below the globe.
- **Click-to-track.** A scope click opens Focus. A **signal** click only starts
  tracking — camera follows, trail of the *received fixes* (never interpolated),
  telemetry in the HUD, `Esc` releases. Tracking writes nothing.
- Keys: `0`–`6` optics, `H` HUD, `Esc` release.

## The review, and what it caught

`/fracture-review` against `a8fe8ee` returned **FIX** with three findings, all
`introduced`, all now fixed in `0ebd535` and each **mutation-proven** (revert
the cure, its own coverage goes red, negative controls stay green):

1. **BLOCKER — the job aborted whenever two room queries returned the same
   provider `source_id`.** The per-fence adapters appended one observation per
   contact *per fence*; two copies collide on
   `world_signal:<provider>:<source_id>`, which carries no room; the snapshot
   validator raises, from inside `build_snapshot`, *outside* the try guarding
   the store write. `adsb` is second in `ADAPTERS`, so `iss`, `launch` and
   `firms` never polled. **It needed duplicate source_ids across room queries,
   not merely two rooms** — the ADS-B query is a *circle* around each room's
   centroid, so two rooms a few hundred nautical miles apart hear the same
   aircraft even when their boxes do not intersect. Fixed by
   `_dedupe_by_source`; identity and room-containment semantics unchanged.
2. **DEFECT — a 74 px decorative reticle swallowed clicks at the globe's
   centre.** `.world-hud` sets `pointer-events:none`, and the next rule restores
   it for every direct child. Fixed on `.hud-reticle` alone.
3. **DEFECT — Space reset the optics.** `Number(' ')` is `0`, not `NaN`, so the
   Space bar passed a `Number.isInteger` guard as style index 0 — while
   scrolling the list under the globe, which is what Space is for. `styleForKey`
   now demands a single ASCII digit before converting.

The re-review against the fixed tree is **CLEAR**:
`/root/.cache/fracture-review/DwoodAmo-99a2f07ae1/d9af77e185cb94a9/review.json`
(the finding ledger is `…/4c75bf3d17b2e9d3/review.json`).

## Verification that actually reached production

- Backend `/health` 200: `db connected`, `scheduler fresh`.
- The restarted process ran the `00:28Z` bucket: **96 live aircraft, the ISS,
  `usgs` ok, `firms` not_configured**, `rooms: 1`.
- All eight scheduled jobs that fired in the following 15 minutes: **0 errors**.
- The public site serves `index-DnrFvhtq.js`, `application/javascript`,
  matching the release. The Cesium chunk loads on demand (4.19 MB) and the
  service worker precaches it **0** times.
- Both fixes confirmed **in the served artifacts, not the tree**:
  `hud-reticle{…pointer-events:none…}` in the shipped CSS and `^[0-9]$` in the
  shipped WorldView chunk.
- Suites: backend **2150**, frontend **602**, lint and `tsc -b` clean, build
  passes the lazy-Cesium precache contract.

## Things a fresh instance would otherwise get wrong

- **The backend restarted at 17:52 CDT on 2026-08-26 without being asked**, and
  picked up `world_adapters.py` while it was still uncommitted and pre-fix. The
  job ran live for ~90 minutes on that code. It never hit the blocker only
  because exactly one room qualifies (`"rooms": 1`) — precisely the condition
  the blocker needed a second room to break. Tree and process now agree. If you
  see a restart you did not cause, check `scheduled_job_runs` before assuming
  the running code is what you last committed.
- **Only the Iran/Hormuz room lights up today** (fence
  `46.22,20.96 → 62.91,32.01`). Every other room has placed no geography, so an
  empty World there is correct, not broken.
- **Probe the real feeds, not fixtures.** The live probe caught what every
  fixture missed: Launch Library's `mode=list` omits `pad`, so launches were
  silently dropped for having no geography and the layer merely *looked* empty.
- **`packages/mobile/.env` is tracked in this PUBLIC repo.** It holds only
  `EXPO_PUBLIC_API_URL=http://localhost:8000` — no secret — but `packages/` is
  frozen and nobody has ruled on removing it.

## Not done, deliberately

- **AISStream and OpenSky remain CLOSED/EXCLUDED.** OpenSky's written-agreement
  clause was not worked around; adsb.lol was chosen instead. AISStream's terms
  decision is still outstanding.
- `adsb.lol` was listed "not selected, requires its own terms review" in the
  provider ledger. It was activated on the owner's instruction, and
  `docs/WORLD_PROVIDERS.md`'s 2026-08-26 amendment records exactly that.
- The scheduler runs jobs **serially**. With many placed rooms, `adsb` and
  `firms` loop per-room sequentially; at the 24-room cap and a slow provider
  that is minutes of blocked tick. Not reachable at one room, not fixed, and
  the next thing to look at if room count grows.
- `scripts/world-hud-hittest.mjs` is a real-browser check (jsdom cannot lay out
  or hit test). It resolves puppeteer from the ambient install and is **not**
  wired into `npm test`, to avoid adding a dependency to the PWA build. Run it
  by hand: `node scripts/world-hud-hittest.mjs`.

## Rollback

```bash
# frontend
ln -sfn /var/www/dialectic-releases/20260826T032052Z-world-synapse-85fed38 \
        /var/www/dialectic-current && systemctl reload nginx
# backend (no migration was applied, so nothing to unwind in the database)
git revert 0ebd535 a8fe8ee && systemctl restart dialectic
```

No migration accompanied either commit; `schema.sql` and `migrations/` are
untouched across the whole range.
