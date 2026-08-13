# Release 1 — SDD Ledger

One branch (`codex/scene-kernel-identity-shell`), one worktree
(`.worktrees/release-1-workroom-foundation`), one gate, at most one PR.
Per Amendment 3, no task group opens a PR and no task group claims Release 1
complete. The release-level `JOURNAL.md` entry is written only after the
integrated gate in Task Group F.

---

## Task Group A — Scene and identity kernel — COMPLETE

| Task | Commit | Result |
|---|---|---|
| A1 Frontend harness + route contract | `bc76e11` | 5 tests. RED observed (unresolved module) before implementation. |
| A2 Scene model + canonical scene URLs | `fda9a01` | 10 tests. RED observed across 8 assertions. |
| A3 Navigation owns scene installation | `2c1c763` | 14 tests. Store + hook; scene set AFTER setRoom. |
| A4 House/Record rendering | `a96e683` | 18 tests. Frame composes Record inside House. |
| A5 Dialectic identity shell | `a0996da` | 1076 backend + 20 frontend. One mention definition. |
| A6 Browser proof + entry-scene fix | `7b85bd2` | 23 frontend tests. Real regression found and fixed. |

### Focused verification (observed 2026-08-12, worktree, not inherited)

- Backend: **1076 passed**, no failures or errors.
- Frontend: **23 passed** across 4 files. Lint 0. Production build 0.
- Browser (isolated fixture: backend `:8013`, preview `:4173`, DB
  `dialectic_browser`, `SCHEDULER_ENABLED=0`; **no production service touched**):
  - Bare `/` opens Home → House; switcher shows House `aria-current="page"`.
  - `/?scene=record` renders Record with the pulse hidden; **survives reload**;
    Back gives House at `/`; Forward returns to Record.
  - Ordinary room serializes `?room=<id>` with no scene param, renders no
    switcher, and refuses `?scene=house` by rendering Record.
  - No horizontal overflow at exactly **1024** or at **390**.

### Defects found and fixed during A

1. **Plan type defect (A2).** `isImplementedWorkspaceScene(requested ?? null)`
   narrows the expression, not the parameter, so `requested` stayed the full
   nine-scene union. Tests and lint passed while the build failed. Fixed by
   narrowing a local.
2. **Entry-scene drop (A6).** Boot and popstate both rebuilt the Home-root
   destination as `{ roomId: null, threadId: null }`, discarding the parsed
   scene — `/?scene=record` reloaded into House and Back/Forward could not
   return to Record. Unit tests could not see it; browser acceptance could.
   Fixed with one shared `entryDestination()` used by both call sites.
3. **Re-export binding (A1).** `export … from` re-exports without binding
   locally; the hook's own three uses would have been undefined.

### Verification hazard recorded

The PWA service worker served `index-D46m2B5a.js` from workbox precache while
the preview served `index-BvmLXY3v.js`. The first re-probe of the A6 fix read
stale code and looked like a failed fix. **Unregister the service worker and
clear caches before reading any browser result in this app.**

---

## Task Group B — House v2 semantic movement — NOT STARTED
## Task Group C — Workspace-object adapters — NOT STARTED
## Task Group D — Unified proposal envelope — NOT STARTED
## Task Group E — Current-scene local continuity — NOT STARTED
## Task Group F — Integrated Release 1 gate — NOT STARTED

No PR may open until F passes.
