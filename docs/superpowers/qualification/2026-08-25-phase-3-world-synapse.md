# Phase 3 World Synapse Qualification

Date: 2026-08-25 America/Chicago
Result: **LOCAL SOURCE + DISPOSABLE BROWSER QUALIFIED; NOT PRODUCTION-LIVE**

This is the Phase 3 boundary defined by
`docs/superpowers/plans/2026-08-25-phase-3-world-synapse.md`. “Epic” means
ambitious/crazy-awesome integration; no electronic-record integration is in
scope.

## Exact checkout and dirty boundary

- Worktree: `/root/DwoodAmo/.worktrees/world-lens-truth-before-spectacle`
- Branch: `codex/world-lens-truth-before-spectacle`
- Qualification base `HEAD`: `4bc03f166fffb791bda0737874b697dc5c3c3245`
- Phase 3 implementation commits through that base:
  `d7b7ff7`, `e67931e`, `fa4db17`, `3be3e28`, `43c887d`, `7cc5958`,
  `4bc03f1`
- The final qualification ran with a deliberate six-file independent-review
  remediation patch: causal mark creation refreshes enhanced Atlas, every
  live-scope row renders complete source provenance, and the browser harness
  requires that provenance in a forced no-WebGL Synapse.
- Canonical SHA-256 of that six-file source/harness patch:
  `8073e33af0ed62529e83e3d14a4bdf692095f8e36aa54419c8cd6b22c88ad2e5`
- `JOURNAL.md`, `dialectic/CLAUDE.md`, and this ledger were updated only after
  the successful run and do not alter qualified runtime behavior.

No schema or migration file changed in Phase 3.

## Source gates

| Gate | Exact result |
|---|---|
| Targeted backend + real PostgreSQL | `57 passed in 5.48s`; no skips in `test_field_marks_pg.py`, `test_atlas_pg.py`, `test_atlas_api.py`, or `test_world_tools.py` |
| Targeted fused frontend | `9` files, `106 passed` |
| Full backend | `2125 passed in 45.68s` with `DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test` |
| Full frontend | `64` files, `580 passed` |
| ESLint | `npm run lint` passed with zero errors/warnings |
| Production build | `tsc -b && vite build` passed; PWA service worker generated; existing large-chunk advisory only |
| Diff whitespace | `git diff --check` passed on the final source and documentation diff |
| Scope-word hygiene | Phase 3 diff contains no prohibited integration vocabulary or stealth stub; broad source scan returns only longstanding legitimate HTML `placeholder` attributes/comments |

The frontend suite emits jsdom's known informational canvas message because
the optional `canvas` package is not installed; all 580 tests pass.

## Disposable browser qualification

Command:

```bash
python3 docs/superpowers/acceptance/2026-08-25-world-lens-truth-acceptance.py
```

Final result: **64/64 passed**.

Evidence directory (preserved):
`/tmp/dialectic-world-lens-acceptance-1910419_543346580`

- `results.json` — 64 checks, 0 failed
- `backend.log` — no HTTP 500, runtime reset marker, or ASGI exception
- `preview.log` — ephemeral loopback Vite preview, stopped after the run
- `synapse-desktop.png` — 1280 x 900
- `synapse-webgl-failure.png` — 1280 x 900
- `world-390-reduced.png` — 390 x 844
- `world-webgl-failure.png` — 1280 x 900

The harness cloned `dialectic_test` into a uniquely named database, applied
migration 022 idempotently, performed every named write through visible UI,
stopped both loopback child processes, and dropped the disposable database.
It did not mutate `dialectic_test` or production.

Qualified visible sequence:

1. Place signal, Ratify, Redraw, bind to thesis node, and Confirm through UI.
2. Open World evidence from Field in the same ordinary room while preserving
   the exact Field mark in Focus.
3. Resolve the historical evidence binding to the current redraw; select the
   one real Cesium entity with `properties.selected=true`.
4. Preserve room/object/Focus across House and World, causal-relation
   navigation, Back, and Forward.
5. Copy the same URL into a forced no-WebGL context and retain Focus, literal
   causal semantics, selected row, complete list, keyboard traversal, and the
   exact provider/acquisition/source-ID/URL/credit chain.
6. Supersede through UI and prove the retired scope leaves the live projection.

## Screenshot inspection

All four screenshots were opened at original resolution.

- Live 1280 x 900: the 340px Focus rail leaves a usable globe, not a sliver;
  the selected current point is larger and outlined, while Focus retains the
  exact confirmed Field mark.
- Synapse no-WebGL 1280 x 900: literal scope -> Supports -> thesis node ->
  Confirmed text is clean and readable; no connector can be mistaken for
  measured geography. The selected row also says `Selected` and carries an
  amber border, so state is not color-only. Provider, acquisition, source ID,
  exact URL, and credit remain legible directly below that selected row.
- 390 x 844 reduced-motion: no horizontal overflow; the Place target measures
  44px and action, metadata, source, and error text measure at least 12px.
- Post-retirement no-WebGL 1280 x 900: only the two unrelated live scopes
  remain; the full list, signal source condition, and controls remain visible.

## Truth surfaces

| Surface | Status | Evidence |
|---|---|---|
| Source checkout | QUALIFIED | Commits + patch hash above |
| Local PostgreSQL | QUALIFIED | 57 targeted + 2125 full tests |
| Local production build | QUALIFIED | Build passed in source gate and browser harness |
| Disposable loopback browser | QUALIFIED | 64/64 and evidence directory above |
| Local migration exercise | QUALIFIED | Migration 022 idempotent in disposable clone; clone dropped |
| Production migration state | **NOT PERFORMED** | No production database access or mutation authorized |
| Production runtime / PID | **NOT PERFORMED** | No service inspection, restart, or deployment authorized |
| Production served asset | **NOT PERFORMED** | No release directory or symlink changed |
| Public-browser delivery | **NOT PERFORMED** | Loopback Chromium is not public delivery proof |
| Real provider configuration | **NOT PERFORMED** | Fixture snapshot only; provider gates remain closed |
| Activation | **NOT PERFORMED** | No feature/runtime activation performed |
| Physical-device proof | **NOT PERFORMED** | No managed or physical device observed |
| Ordinary-use / human qualification | **NOT PERFORMED** | No Amo/Dan longitudinal use observed |

Phase 3 therefore works in source, real local PostgreSQL, a production build,
and a disposable browser. It is not truthful to call it deployed, publicly
served, provider-live, activated, or human-qualified.
