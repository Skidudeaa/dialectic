# Release 2 — The United Workroom: gate record

Branch `claude/release-2-united-workroom`, rebased onto `bfe694e`.
Scope is a **subset** of the program's Release 2: the scenes and the surfaces
that make them legible. Focus, Atlas, Field and exact restoration remain
Release 3, and the artifact deep-views (Reading Focus, Brief, Judgment) are
deliberately **not** built — see §2.

---

## 1. What this release is for

Release 1 shipped `workspace_objects.py` and nothing rendered it.
`api.getWorkspaceObjects()` existed and was called by no component; an ordinary
room showed no scene switcher at all, because `SceneSwitcher` returns `null`
below two choices and the frame forced Record everywhere outside Home root.

Meanwhile the product never said what it was. The signed-out screen offered
four words and three doors, one of which could not work. The empty transcript —
the state most rooms are in — named a participant that had been renamed two
task groups earlier. The only explanation of the product was a hardcoded modal.

The bar set for this work: **a brand-new user should not struggle to understand
what Dialectic is, what it does, and how to use it.**

## 2. Reconnaissance — why four scenes and not nine

Read-only against production, 2026-08-12:

| | |
|---|---|
| Rooms | 23 — only **11** hold a single message |
| Rooms with readings | 3 (13 readings) |
| Rooms with memories | 8 (425 active) |
| Rooms with a thesis | 5 |
| **Commitments · proposals · briefs** | **0 · 0 · 0** |

Two decisions follow directly, and neither is a matter of taste:

1. **Emptiness is the product's normal state.** Twelve of twenty-three rooms
   hold nothing. For most first visits the empty state *is* the room, so it is
   built as a primary surface and built first.
2. **Only scenes with a population ship.** Judgment, Brief, Field, Focus,
   Current and Atlas would render zero rows in every room in production. They
   stay approved names in `WORKSPACE_SCENES` and out of
   `IMPLEMENTED_WORKSPACE_SCENES`, which already handles the fallback.

## 3. What shipped

| Commit | |
|---|---|
| `90124d2` | The front door states the premise and asks the server which doors are open |
| `dca6ed4` | Capabilities moved onto a prefix the edge actually proxies |
| `887d849` | The empty room explains itself |
| `cb8ddf2` | One definition of who is speaking; no provider name in any copy |
| `705467b` | Bench, Library and Ledger become real scenes over Release 1's projection |
| `1595bf6` | The help modal's prose replaced by what is actually running |
| `e1d5fe1` | The rail follows the scene; the header stops eating its own title |

**One definition, three times over.** `scenesForDestination` is the single
answer to "what may this destination show", read by the router *and* the frame,
which previously held separate copies of the same rule. That pattern is the
release's recurring theme: the participant name had **three** private copies of
its mapping, and the capability map exists because prose about the system had
drifted from the system.

## 4. Verification (observed at the gate, not inherited)

- Frontend **129 passed** / 19 files · lint **0** · production build **0**
- Backend **1159 passed** · `ruff --select F` clean on every changed file
- Browser acceptance, isolated fixture (`dialectic_browser`, backend `:8013`,
  preview `:4173`), at **1024** and **390**, service worker unregistered first:
  - four scenes reachable in an ordinary room, each empty state teaching
  - populated Library renders real object cards with provenance
  - scene survives reload; Home root still offers only House and Record
  - room name legible and untruncated (106px), branch selector operable (92px),
    no header overflow
  - no horizontal overflow on any scene at either width
- **No production service restarted.** Production's PID change during this work
  was verified as the owner's 01:09 deploy (`NRestarts=0`), not this branch.

### Mutations run, each shown red and restored

| Guard | Mutation | Result |
|---|---|---|
| Capabilities delegates, not copies | replace the import with a faithful local copy | identity assertion red; **all nine behavioural tests stayed green** — which is the point |
| Capability map reads the live scheduler | substitute a hardcoded job roster | 3 tests red |
| Workspace staleness guard | drop the post-response ticket check | the in-flight-room-change test red |
| No provider name in any surface | reintroduce the old composer placeholder | red, naming the file; a comment quoting the same phrase stays green |

## 5. Defects found, and how

Three of the five were found by **looking at a screenshot after every assertion
passed**, which is the finding worth carrying forward more than any of them:

1. **`Dialecticreads it`** — JSX drops the newline between an expression and the
   next line's text. Length, presence and test-id assertions all passed; none of
   them read the words.
2. **A ghost panel.** The selected rail tab is persisted, so a stored `memory`
   kept rendering the memory panel in a room whose tab had been removed — a
   second panel with no tab to leave it by.
3. **The header collapsed its own title to zero.** The action group is 217px of
   fixed-width controls; sharing a row with the identity and running short,
   flexbox resolved it by rendering the room title and branch select at
   **width 0**. It read as cosmetic crowding. A 0×0 box satisfies every
   "fits inside the viewport" bound, which is why Release 1's overflow checks
   passed over it.
4. **A routing trap that would have shipped silently.** `/meta/capabilities` sat
   outside the one prefix list nginx proxies, so production would have answered
   with `index.html`; the client would throw and the screen would keep its
   "unknown means closed" default — *coincidentally correct today*, wrong the
   day signups open.
5. **My own phone-width fix was wrong for the desktop.** Keying the header wrap
   to a 600px media query left 1024 broken, because the header lives inside
   `.app-main` (~544px with both rails up). The browser fence failed at 1024 and
   passed at 390 — the reverse of what a phone fix predicts.

## 6. Owner rulings, 2026-08-13

Both open questions were ruled on and are now closed in code.

**The jobs are default ON — the docs were wrong.** `Job.enabled()` reads
`os.environ.get(enabled_env, "1")`, so an unset flag has *always* meant on, and
`.env.example` ships all four as `1`. Five docstrings and four `CLAUDE.md` rows
claimed "default off" — wrong in the direction that understates what ships.
Corrected, and the dangling justification rewritten: the clause explaining the
cost was written to defend an off-by-default and now reads as the reason a kill
switch exists.

**No guests, for now.** The disabled fetch was treating a symptom. `POST /users`
was unauthenticated and minted a real users row for anyone who asked, handing
back an identity with no JWT — a door onto a room you cannot use. It is now
gated on `GUEST_ACCESS_ENABLED`, failing closed like signups, and
`/auth/capabilities` reports it so the screen shows two doors instead of three
without hardcoding the answer.

A flag rather than deleted code, so re-opening is a flip. The guest-descriptor
path in `useRoomNavigation` is deliberately left in place: it also covers a
persisted tokenless state, and deleting scaffolding that a flag can revive is
how a working path gets lost.

Verified live, not only mocked: with the flag unset the route answers 403 and
the `users` row count is **unchanged (4 → 4)**. The guard is a dependency
declared *ahead of* `Depends(get_db)`, because FastAPI resolves the signature
before the body — a check inside the function would still have acquired a
connection first, which is the difference between "costs no database work" being
true and being approximately true.

## 7. Recorded, not papered over
- **No stranger has actually tried it.** Every claim above is a probe. The bar
  set for this work is about a person's comprehension, and that needs a person.
- **Not yet unified:** the Record scene has not absorbed the Insights and
  History panels into its body — they are scene-scoped rail tabs, which is
  honest but not finished.

## 8. Deploy

No migration. The release adds two read-only endpoints and frontend surfaces,
so deploy is a backend restart plus a frontend flip.

Two traps the Release 1 deploy recorded, which apply again: run `npm ci` before
building (a stale `node_modules` makes `tsc -b` fail and leaves the OLD bundle
in `dist`, so a flip ships a new release name over unchanged code), and probe
the origin past the CDN — a 200 on the old bundle can be a Cloudflare
`immutable` edge hit rather than a failed flip.
