# Task Group C — Workspace-Object Adapters: Handoff

**For:** the next implementer, with zero context from the A/B sessions
**Branch:** `codex/scene-kernel-identity-shell` @ `f462533` — **stay on it**
**Worktree:** `.worktrees/release-1-workroom-foundation` — never `/root/DwoodAmo`
**Authority:** the consolidated plan
`docs/superpowers/plans/2026-08-12-dialectic-release-1-workroom-foundation.md`,
under the program's three-release rule
**Design:** `docs/superpowers/specs/2026-08-12-dialectic-front-end-identity-design-v2.md` §8.1–8.2

> **Do not open a PR. Do not claim Release 1 complete.** C is the third of five
> task groups. The single PR opens only after the integrated gate (F).

---

## State you are inheriting

Verified in this worktree at `f462533`, immediately before this handoff:

| | |
|---|---|
| Backend | **1083 passed** |
| Frontend | **27 passed** across 5 files |
| Lint / build | 0 / 0 |
| `ruff --select F` on `home_activity.py` | clean |

Task Group A (scene + identity kernel) and B (House v2 movement) are complete.
The SDD ledger — `2026-08-12-dialectic-release-1-sdd-ledger.md` — records both,
with every defect found and how it was proven.

### What A gives you

- `src/lib/workspaceRoute.ts` — the **only** URL grammar. `destinationFromSearch`,
  `destinationFromLocation`, `defaultWorkspaceScene`, `resolveWorkspaceScene`,
  `destinationUrl`, `entryDestination`. Scene is the third destination axis.
- `useRoomNavigation.ts` — still the **one** destination writer. It installs
  room, branch, and scene in one transaction.
- `src/types/workspace.ts` — `WORKSPACE_SCENES` (nine approved names) vs
  `IMPLEMENTED_WORKSPACE_SCENES` (`house`, `record`). An approved-but-unbuilt
  scene falls back; it never opens dead UI.
- `productIdentity.ts` — `PARTICIPANT_NAME` etc. Every user-facing label uses it.

### What B gives you

- `home_activity.py` — `MOVEMENT_KINDS` (8), `HomeActivityMovement`,
  `_MOVEMENT_SQL`, `_MOVEMENT_PER_ROOM_CAP` (12, primary bound),
  `_MOVEMENT_TOTAL_CAP` (400, backstop).
- `HouseMovement.tsx` — renders movement; navigates by room/branch.
- `HomeActivityMovement.object_id` is populated by every arm **but nothing
  addresses it yet.** That is precisely the seam C fills.

---

## What C must deliver

Spec §8.1. **Adapter-first. No universal artifact table. No new storage.**

### C1 — the `WorkspaceObject` contract

```text
id · kind · room_id · branch_id? · title · summary · status
created_at · updated_at · provenance · relationships
available_actions · review_state · source_entity · source_event
```

One backend projection shape and one TypeScript type that agree. Model it on
`HomeActivityMovement` (`home_activity.py`), which already proves the pattern:
a Pydantic model, a fenced SQL read, a mirrored TS interface.

### C2 — per-entity adapters

```text
reading_items                → Reading
messages[metadata.source=deep_dive] → Research Brief   (projection only, §8.2)
trading book + snapshot      → Thesis
commitment / prediction      → Commitment
message metadata proposal    → Proposal        (D consumes this)
memory                       → Dossier entry
Home activity item           → House movement  (already exists — reuse, don't refork)
message + event history      → Record event
```

### C3 — the twin rule (**the highest-risk item in C**)

A reading and its `reading:<domain>-<slug>` memory twin must project to
**exactly one** object carrying both `source_entity` references.

Why this will bite you: `llm/reading.py` writes the reading **and** a memory
twin with `dedup=False`, deliberately, so three-lane recall finds readings.
Production currently holds **9 readings and 9 twins — a clean 1:1 pairing**.
A naive adapter emits 18 objects and *looks correct* in every screenshot,
because each pair renders as two plausible, differently-worded entries. Only a
count assertion catches it.

**Required:** seed a reading plus its twin, assert the adapter returns 1, then
delete the dedup and confirm the count goes to 2. If that mutation does not go
red, the guard is untested — see the B lesson below.

### C4 — read-only

Adapters project. They do not write, and they do not change any entity's
lifecycle. `available_actions` describes what a surface *may* offer; it performs
nothing.

---

## Traps this branch has already paid for

**1. A mutation that kills nothing is a coverage hole, not a pass.**
In B, deleting the membership `JOIN` from one UNION arm left all five projection
tests green — the service drops rows for rooms outside the eligible map, which
**masked** the missing fence. The fix was a test that runs `_MOVEMENT_SQL`
directly (`test_movement_sql_fences_every_arm_by_itself`). C's twin dedup has
the identical shape: if a downstream `dict` keyed by reading id happens to
collapse the twin, the adapter's own dedup is untested. **Assert the guard where
it lives.**

**2. Bounds must be per-room, applied in SQL.**
B's first cut used one global `ORDER BY … LIMIT 200`. A room with 250 recent
readings consumed the entire budget and every other room projected **zero**
movement. The House still looked healthy. If C paginates or caps objects, rank
inside the partition before any global cut.

**3. The PWA service worker will serve you stale code.**
During A's browser proof, workbox served `index-D46m2B5a.js` while the preview
served `index-BvmLXY3v.js`; a working fix read as broken. **Unregister the
service worker and clear caches before believing any browser result.**

**4. `pkill -f "run.py"` matches the PRODUCTION service.**
Stop fixture backends by PID after checking `/proc/<pid>/cwd` is inside the
worktree.

**5. The plan's inlined code is not pre-verified.**
A2's `resolveWorkspaceScene` narrowed the expression `requested ?? null` rather
than the parameter; tests and lint passed while the build failed. Read the
plan's snippets as intent, compile them as code.

---

## Isolated fixture (reuse, do not rebuild)

```bash
WORKTREE_ROOT="$(git rev-parse --show-toplevel)"
cd "$WORKTREE_ROOT/dialectic"
export DATABASE_URL='postgresql://localhost/dialectic_browser'
export JWT_SECRET_KEY='browser-scene-kernel-secret-32-bytes-minimum'
export ANTHROPIC_API_KEY='browser-fixture-dummy-key'
export SIGNUPS_ENABLED=1 SCHEDULER_ENABLED=0 PORT=8013
python3 run.py
```

```bash
cd "$WORKTREE_ROOT/dialectic/frontend/app"
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run build
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run preview -- --port 4173
```

`dialectic_browser` already carries schema + migrations 013/014/015 and a
fixture account (`scene@fixture.example.com` / `scene-fixture-pw-123`), a Home
membership, and one ordinary room `11111111-1111-1111-1111-111111111111`.
`dialectic_test` carries 013/014/015 for the pg suites. **No production service
is restarted for any of this.**

---

## Definition of done for C

- [ ] `WorkspaceObject` exists once on each side and the two agree.
- [ ] Each adapter in C2 projects its entity without a new table.
- [ ] Reading + twin render as **one** object — mutation-proven.
- [ ] Adapters write nothing; no lifecycle changes.
- [ ] Backend, frontend, lint, build all green; `ruff --select F` clean.
- [ ] Ledger updated with observed counts and any defect found.
- [ ] **No PR.** Continue to D (unified proposal envelope).

## Then D, E, F

D normalizes five proposal kinds over existing message metadata **without
touching relay write paths** — `failed` must stay visible, accepted proposals
stay inspectable, duplicate acceptance stays disarmed. E persists device-local
room/branch/scene with deep links overriding. F is the one integrated gate, the
journal entry with a freshly observed backend count, and the single PR.
