# Handoff — the Instrument Desk session (2026-08-18/19)

Zero-context authority for the UI rebuild session. Everything below is
DEPLOYED and PUSHED; nothing is in flight. Verify current truth before
acting — do not redeploy merely to "apply" this document.

## What shipped (three commits, all live)

| Commit | What | Release dir |
|---|---|---|
| `2c33190` | **The Instrument Desk** — docky-inspired hardware rebuild: tokens v3 (chassis/well/bezel/LED/engrave/seven-seg), THE CONSOLE in the switcher tray, cockpit bezel retheme, energyPulse fix | `20260818222045-instrument-desk` |
| `19d27e5` | **Scene identity** — per-scene accents/mastheads/silhouettes after the owner's correction *"every page/tab/view feels the same… I don't know where I am"* | `20260818233…-scene-identity` |
| `50025eb` | **Material depth** — brushed chassis grain, faceplate screws, scene-tinted lighting (tray backlight + content wash), DAG as 540px glass hero, bigger seven-seg | `202608190006…-material-depth` (current symlink) |

Also: `d5a2928` landed a PREVIOUS session's stranded PLAN.md/JOURNAL.md
handoff rewrite (not this session's work — just unstranded).

Design lineage: docky (github.com/josejuanqm/docky) = a tray of
heterogeneous tiles — navigation + live widgets + dividers + running-dot
LEDs. Owner rulings: **vintage instrument panel** register, **whole
dialectic app** scope, td frontend untouched. Core metaphor: **machined
chassis with paper on it** — the dossier sheet is sacred.

## The contracts a future session must know

- **`SceneSwitcher` is the Console tray**: new props `signals`
  (per-scene `{count, tone}` running-dot LEDs) and `instruments`
  (ReactNode, right-aligned cluster). With `instruments` present it
  renders even for one scene. Labels/hints/glyphs live in
  `workspace/sceneIdentity.ts` (react-refresh forbids constant exports
  from component files).
- **`useTradingDesk` mounts ONCE in App.tsx RoomView**; `BenchScene`
  takes `desk` as a prop. Every bound-room entry runs the 8-route
  fan-out + 300s quote poll in every scene — the Console's job;
  a slice-keys filter on the hook is the named upgrade path.
- **`Console.tsx`** owns the presence lamp (ARMED/THINKING/STREAMING/
  RESEARCH) and is the ONE writer of `--energy-level`/`--energy-color`
  (documentElement). `energyPulse` keyframes scale by the var now —
  they previously hard-coded opacity and overrode the off state
  (scanline faintly always-on since 2026-08-15).
- **Scene accents** are set per `.workspace-scene-*` in
  `WorkspaceSceneFrame.css` (`--scene-accent`/`--scene-tint`): house
  sage, record cream, bench amber, field plum, library steel, ledger
  gold, atlas teal. Active tray tile, masthead, tray backlight, content
  wash and module-header rules all inherit them. Silhouettes: Library =
  two-up steel index cards, Ledger = gold-ruled book, Field = plum
  marginalia, Bench = DAG-first (cockpit above the lifecycle panel).
- **`.seg` / `.cockpit-chip-value` keep `letter-spacing: .1em`** —
  without it the DSEG7 decimal point vanishes (569.77 read as 56977;
  caught only by screenshot). DSEG7 self-hosted at `public/fonts/` with
  its OFL license, in the PWA precache via vite `includeAssets`.
- **Never touch** (paper law): `MessageList.css`, `MessageBubble.css`,
  `MessageInput.css`, `PassageMarker.css`, `SignatureMark.css`,
  `fieldDisplay.css`.
- `Console.test.tsx` = the app's first real axe gate. Suite **356/356**
  at every gate this session (two chat-file failures in one batch run
  were the documented under-load flake — green in isolation and in the
  rerun).

## The harness recipe (reused twice, works)

Isolated backend `:8013` on `dialectic_browser` + `vite preview :4173`:

```bash
cd dialectic && DATABASE_URL="postgresql://root@localhost/dialectic_browser" PORT=8013 \
  SCHEDULER_ENABLED=0 NIGHT_SHIFT_ENABLED=0 PARTICIPATION_SWEEP_ENABLED=0 WIRE_ENABLED=0 \
  RSS_WIRE_ENABLED=0 NEWS_DIGEST_ENABLED=0 PREDICTION_WATCH_ENABLED=0 READING_ECHO_ENABLED=0 \
  FIELD_INFERENCE_ENABLED=0 /usr/bin/python3 run.py &
cd frontend/app && DIALECTIC_BACKEND_URL=http://localhost:8013 npm run preview &
# probe via http://localhost:4173 (NOT 127.0.0.1 — vite binds ::1)
# login scene@fixture.example.com / scene-fixture-pw-123, room 11111111-1111-1111-1111-111111111111
# kill: fuser -k 8013/tcp; fuser -k 4173/tcp
```

To see the BOUND cockpit: copy prod's Iran/Hormuz `trading_config` +
`linked_book_id='iran-hormuz-graph'` onto the fixture room (reads hit
real td, read-only), and **REVERT after**
(`UPDATE rooms SET linked_book_id=NULL, trading_config=NULL WHERE id='11111111-…'`).
Left reverted at session end — verify if paranoid.

## Gotchas / honest edges

- **Installed PWAs lag one focus cycle** after any flip (old SW serves
  old precache, then self-reloads once). "It looks unchanged" right
  after a deploy is this, not a failed deploy. Edge verified fresh:
  index DYNAMIC/no-cache, sw.js BYPASS/no-store.
- The Bench lifecycle panel is now BELOW the graph — not gone.
- The Bench tab's alert LED clears only when `alertEvents` empties, not
  on "seen" — could get noisy; a seen-stamp is the obvious refinement.
- The Record unread signal is a session-local ref (count of messages
  arrived while not on Record) — resets on room switch by design.
- Post-deploy sweep after all three flips: 291 journal lines, zero
  warn/error, relay all INFO, live owner session healthy on the new
  bundle.

## Owner temperature

First pass landed "underwhelming"; the correction that mattered:
*"every page/tab/view feels the same. the hierarchy is a mess."* The
scene-identity + material passes answer it. **Lesson recorded in memory:
the complaint was differentiation and wayfinding, never finish.**

## Next moves, in rough order of value

1. **Owner reaction pass** — walk the five scenes on their device; the
   next correction decides direction.
2. **Per-scene right rail** — the rail (RightPanel/MemoryPanel) sits
   outside `.workspace-scene`, so scene accents don't reach it; needs
   the accent lifted to AppLayout or a data-scene attr on the grid.
3. **Spatial Atlas** — a real map view (projection already carries
   nodes+edges); AtlasScene is deliberately list-first today.
4. Bench-tab alert LED seen-stamp (above).
5. `useTradingDesk` slice-keys filter if the every-scene fan-out ever
   matters (marked `ponytail:` at the lift in App.tsx).

Memory: `~/.claude/projects/-root-DwoodAmo/memory/instrument-desk-2026-08-18.md`
holds the same facts plus the harness recipe. dialectic/CLAUDE.md carries
the 2026-08-18 (late) amendment — note it predates `19d27e5`/`50025eb`;
this handoff is the fuller record.
