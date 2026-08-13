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

## Task Group B — House v2 semantic movement — COMPLETE

| Task | Commit | Result |
|---|---|---|
| B1–B3 Movement projection (8 kinds, fenced) | `743d743` | 6 pg tests. 1082 backend. |
| B (frontend) House reads movement | `08347c0` | 27 frontend tests. |

### Observed
- Backend **1082 passed**; frontend **27 passed**; lint 0; build 0.
- **p95 re-measured, not inherited** (the 150 ms target predates these arms):
  25 rooms / 200 movement items → median **6.0 ms**, p95 **9.3 ms**.
  Capped at 200 total / 12 per room.

### The fence mutation that killed nothing
Deleting the `JOIN er` from the `reading_filed` arm left all five projection
tests green: the service drops rows for rooms outside the eligible map
(`bucket is None`), which **masks** a missing fence in any single UNION arm.
Added `test_movement_sql_fences_every_arm_by_itself`, which runs `_MOVEMENT_SQL`
directly; the same mutation now fails with
`unfenced rows leaked: ['reading_filed']`. A guard the pipeline shadows must be
asserted where it lives.

### Design decisions worth carrying
- Wire is its own kind; `reading_filed` excludes `source='wire'` so one article
  cannot move the House twice.
- Only `claim_warning`, `prediction_review`, `commitment_due` set
  `requires_judgment` — marking arrivals as judgment turns a House into a nag.
- The component navigates by room/branch, never by the server's `destination`
  string, so it does not become a second destination writer.
### Post-B self-review (2026-08-12)

A review of B against its own claims found one real defect, now fixed in
`f462533`: the global `LIMIT` ran before per-room slicing, so a room with 250
recent readings consumed the whole budget and every other room projected **zero**
movement (measured: Loud 12, Quiet 0, with a per-room cap of 12 that had never
bound anything). Ranking moved into SQL via `row_number() PARTITION BY room_id`;
the total cap rose 200 → 400 so per-room binds first at realistic scale — at 200
it still truncated 17 of 25 rooms, the same bug wearing a smaller number.

Re-measured after the fix: 25/25 rooms carry movement, 300 items, median 13.7 ms,
p95 **25.6 ms** against the 150 ms target. Fence mutation still kills.

Also checked and found sound: Pydantic's `movement` default is per-instance (not
a shared list); `movement` is in the response schema and the existing API
fixtures still validate against the defaulted field; `to_prompt_section` renders
movement, so human House and Dialectic context stay projection-identical; every
UNION arm supplies a non-null `object_id`, so the React key cannot collide.

Baseline at handoff: **1083 backend**, **27 frontend**, lint 0, build 0.

## Task Group C — Workspace-object adapters — COMPLETE

Handoff: `2026-08-12-dialectic-release-1-taskgroup-c-handoff.md`

| Task | Commit | Result |
|---|---|---|
| C1–C4 Adapters, contract, endpoint, mirror | `f4c0d7b` | 1114 backend (+31), 33 frontend (+6). RED observed before implementation (unresolved module). |

### Observed (this worktree, 2026-08-12 — not inherited)

- Backend **1114 passed**; frontend **33 passed** across 6 files; lint 0; build 0.
  `ruff --select F` clean on every changed file. (`api/main.py` carries 9
  pre-existing F401s, identical at `HEAD` — not introduced here.)
- **Replayed against production, read-only** (`repeatable_read`, `readonly`):
  23 rooms in **135 ms** total. 13 readings → **13 objects, 13 twins absorbed,
  0 leaked into the Dossier**; 124 Dossier entries still projected, so the
  guard does not fight the feature it protects. A naive adapter emits 26.
- Busy-room projection **measured fresh**, not inherited: 400 messages / 120
  readings + twins / 60 memories / 40 commitments / 300 events → 411 objects,
  median **16.6 ms**, p95 **30.2 ms** against the 150 ms design target.

### The twin rule — three mutations, all red

| Mutation | Killed |
|---|---|
| Drop `key NOT LIKE 'reading:%'` from the dossier statement | 3 tests, incl. the direct-SQL one |
| Stop absorbing the twin in the reading adapter | the `source_entity` assertion |
| Drop the `thesis_state_current` exclusion | the second-twin test |

Guarded twice on purpose: the reading adapter pairs through
`llm.reading._reading_key` — the **writer's own function**, so the pairing
cannot drift from the rule that produced the key — and the dossier excludes the
whole namespace in SQL, asserted by running `_DOSSIER_SQL` directly. That
second assertion exists because of B's lesson: a guard the pipeline can shadow
must be tested where it lives.

### Defects and findings

1. **A SECOND twin, previously unnamed.** `api/trading_ingest.py` upserts a
   `thesis_state_current` memory that shadows `rooms.trading_config` — the same
   two-rows-one-thing shape as the reading twin, and it would have rendered as
   a Dossier entry beside the Thesis it describes. The thesis adapter folds it
   in; the dossier excludes it. The key is now one constant (`trading_ingest`),
   read by all three call sites.
2. **§8.2's "Research question" is not projectable.** `llm/research.py` sends
   the question over `DEEP_DIVE_STARTED` and never persists it, so no durable
   row carries it. C projects the brief that does exist and records the gap —
   carrying the question needs a write, which Release 1 does not make.
3. **The 72-hour judgment window had no single definition.** Extracted to
   `home_activity.COMMITMENT_DUE_WINDOW`, used by both movement arms and the
   commitment adapter, so the House and the workroom cannot disagree about what
   a human owes.
4. **`dialectic_test` was missing `rooms.linked_book_id`** (present in
   `schema.sql:626` and in production). Added to the test DB; the thesis
   adapter could not otherwise be tested at all.
5. **Production holds zero proposals and zero research briefs today** (checked
   all five metadata slots + `deep_dive`). The empty projection is correct, not
   a bug — but it means **D's envelope has no production population to replay
   against**, and fixtures are the only coverage until one exists.

### Design decisions worth carrying

- `status` is the entity's own lifecycle; `review_state` is what a human still
  owes. They are separate axes — a reading has a `source` and owes nothing.
  `failed` is in the vocabulary though C cannot produce it, because D reuses it
  and a failed human-authorized write must stay visible (§5.1, §8.4).
- Proposal kind lives in `provenance.detail`, and the exact metadata slot in
  `source_entity[0].field` — so **D reads a coordinate, never re-parses an id
  string**.
- **One row in several roles is not a twin.** A message projects as a Record
  event AND a Brief AND its Proposals; collapsing that would delete the
  Record's copy because a higher-order artifact summarized it, which §6.4
  forbids outright. Written into the module header so it is not "fixed" later.
- Bounds are per kind inside each statement (B's starvation lesson), and the
  Record is bounded **per source** so a chatty event log cannot evict the
  transcript from its own Record.
- Read-only is asserted structurally, not promised: the router carries no write
  route, and a pg test counts every touched table and every memory status
  before and after a build.
- The TS mirror is pinned by `tests/test_workspace_contract.py`, which reads
  the real `.ts` file. Mutation-checked four ways — field added on one side
  only, field removed on the other, vocabulary reordered (all red) — and a
  comment quoting a field name leaves it green, so it reads statements, not
  prose.

Baseline at handoff: **1114 backend**, **33 frontend**, lint 0, build 0.

## Task Group D — Unified proposal envelope — COMPLETE

| Task | Commit | Result |
|---|---|---|
| D1–D4 Envelope, lifecycle, disarming, migration safety | `47c57df` | 1138 backend (+24), 49 frontend (+16). RED observed before implementation. |

### Observed (this worktree, 2026-08-12 — not inherited)

- Backend **1138 passed**; frontend **49 passed** across 8 files; lint 0; build 0;
  `ruff --select F` clean on every changed file.
- Envelope projection measured: 120 carriers (capped to 50) × 4 slots →
  **200 envelopes**, 50 supersessions detected against a 200-reading library,
  median **4.7 ms**, p95 **6.2 ms**.
- **The production replay is inconclusive and says so**: production holds zero
  proposals, so "C and D disagree in 0 rooms" is a fact about an empty set.
  The fixture suite is the only real coverage until a proposal exists.

### D3 — duplicate disarming, driven through the real relay

`test_accepting_through_the_relay_disarms_the_envelope` calls
`api.prediction_relay.accept_prediction` against a real connection with the
desk stubbed: envelope `proposed` with `accept` → relay writes → envelope
`accepted`, `accept` gone, `inspect` kept (§8.4) → second call raises **409**
and the desk was posted to exactly **once**. Stamping the flag by hand would
have proved only that the envelope agrees with my own copy of the relay's rule.

### Status derivation — every rule points at a column

| Status | Derived from | Kind |
|---|---|---|
| `accepted` | the stored flag the relay stamps | all |
| `expired` | deadline before today | prediction_draft |
| `expired` | the room already holds `linked_book_id` (§12.2) | thesis_proposal |
| `superseded` | the article is already in `reading_items` | reading_draft |
| `proposed` | otherwise | all |

`superseded` is deliberately not `failed`: the two demand opposite responses,
and reporting "already filed" as a failure sends a human to retry a write that
has already happened.

### What the storage cannot say — recorded, not faked

1. **`failed` has no row, on purpose.** A relay failure leaves the accepted flag
   FALSE so a retry is a fresh accept rather than a conflict. Failure is
   therefore a CLIENT-held state over the same envelope; it stays in the
   vocabulary because dropping it is how a failed write becomes an invisible
   one (§5.1, §9.3). The card keeps its action after a failure, so a human is
   never stranded.
2. **`dismissed` has no row either** — nothing in the shipped UI dismisses a
   proposal.
3. **§9.3's "preserve the accepting human" is only half met.** `accepted_by` /
   `accepted_at` are real for `reading_draft` (`reading_items.saved_by_user_id`)
   and `commitment_proposal` (`commitments.created_by_user_id`), both joined on
   a real `source_message_id` FK. The two tradingDesk-crossing kinds —
   `prediction_draft`, `prediction_resolution` — write **only a boolean and log
   no event**, so their accepting human is preserved nowhere. Null, never a
   guess. Closing it means an event on the relay write path, which Release 1's
   "relays untouched" rule forbids: **for Release 2 or an owner ruling.**
4. **`thesis_draft` is named but stored nowhere.** A thesis draft lives in the
   Create Thesis panel's own flow and never reaches message metadata. Kept in
   the vocabulary so a future writer does not invent a sixth name; asserted by a
   test so nobody reads its absence as breakage.
5. **The commitment acceptance join is correct but unexercised in production.**
   The card sends `source_message_id` and the handler stores it, but both
   production commitments predate the card and carry NULL — verified rather
   than assumed.

### The defect D found in C

Collapsing the two proposal parses into one exposed a dangling link C had
shipped: the Research Brief built its proposal relationships from the **kind**
(`proposal:<mid>:prediction_draft`) while a proposal's id is built from the
metadata **slot** (`proposal:<mid>:proposal`). Three of four links pointed at
ids that did not exist, and nothing complained because no surface had followed
one yet. Fixed at the source, and
`test_every_relationship_id_resolves_to_a_real_object` now walks every
relationship id in a full projection — mutation-checked by reinstating the
kind-keyed form, which turns it red.

### Design decisions worth carrying

- **One definition of a proposal.** `workspace_objects.proposals()` projects
  D's envelopes instead of re-reading metadata; the slot table, the SQL and the
  status rules all live in `proposal_envelope.py`. A production replay confirms
  C and D emit identical ids room by room.
- **The client derives only message-local facts** — which slots are proposals,
  the stored flag, the transient `failed`. `expired` and `superseded` need joins
  the browser does not have and come from the projection, so the rule is not
  copied into a place that cannot evaluate it. The slot table it *does* share is
  pinned by `test_the_metadata_slot_table_has_one_definition` (mutation-checked).
- The spec's "rejected or dismissed" is ONE state under ONE name. Two names for
  one state is how a surface ends up rendering both.
- A `claim_check` is a nudge, not a decision, and is excluded from the slot
  table — asserted at the normalizer AND at the rendered component, because
  "every metadata badge is a proposal" is the easy wrong generalization here.

Baseline at handoff: **1138 backend**, **49 frontend**, lint 0, build 0.

## Task Group E — Current-scene local continuity — COMPLETE

| Task | Commit | Result |
|---|---|---|
| E1–E3 Persistence, precedence, fallback | `a99b8b8` | 75 frontend (+26), 1138 backend. RED observed before implementation. |

### Observed (this worktree, 2026-08-13 — not inherited)

- Frontend **75 passed** across 10 files; backend **1138 passed**; lint 0; build 0.

### E2 — the precedence, proven twice

The rule lives in a pure function (`chooseEntryDestination`) so an ordering
this consequential is provable without mounting anything, and again on the
mounted hook, because only the wiring can show that boot actually consults it:

```text
deep link / notification  >  local restoration  >  Home → House
```

| Case | Result |
|---|---|
| notification entry `/?room=<id>` over stored state | the notified room wins |
| explicit `?room=&thread=` over stored state | the URL wins |
| `/?scene=record` over a restored House | the URL wins — a scene alone is an explicit request |
| bare `/` with stored state | restores room + branch + scene |
| bare `/` with nothing stored | Home → House |

### E3 — the fallback is silent, and structurally so

A restored room the user has lost is dropped **before** navigation is asked
for it, by validating the candidate against the room list the caller already
holds. This is not politeness: refusal is *visible* — the hook surfaces "that
room is no longer available to you" — and saying that about a room nobody
requested announces both that the room exists and that they were removed from
it. The mirror case is asserted too: an explicitly requested lost room still
says so out loud, because there the user asked.

### The defect E found, older than this branch

`denied()` set the access error **before** navigating to Home, and the
corrective navigation ends in a successful install — which clears the error.
So a user who followed a link to a room they had lost was bounced to Home
with **no explanation at all**, while the code plainly intends to give one.
The message now lands after the correction. Verified pre-existing rather than
assumed: the E diff touches no other `accessError` line, and the wiped-message
ordering is present at `HEAD`.

### Wiring mutations — all three red

| Mutation | Killed |
|---|---|
| Revert the access-error ordering fix | the explicit-refusal test |
| Boot stops consulting local restoration | the bare-URL restore test |
| Remember the REQUESTED destination, not the installed one | the ghost-branch test |

The third matters most: navigating to a branch that no longer exists lands on
the room root, and storing the *request* would re-restore into a fallback on
every reload — a store that quietly disagrees with where the app actually is.

### Design decisions worth carrying

- **Continuity proposes; it never installs.** `useRoomNavigation` remains the
  single destination writer (§5.7). A continuity module that wrote room or
  scene state would be exactly the second writer the design forbids, and the
  two would race at boot.
- **Two storage tiers ARE window locality** (§15.4). `sessionStorage` is
  per-window and survives reload, so it is the "stable window identity" the
  spec asks for; `localStorage` holds the installation's most recent scene for
  a window with no history of its own. Nothing synchronizes through the server,
  and the module contains no API call by construction.
- **A scene alone is an explicit request.** `/?scene=record` had to outrank a
  restored House, or the one URL a user can type to override their restored
  scene would be the one URL that silently does not work.
- **Home root is remembered as Home, with its scene.** Home + Record is a place
  the user chose; restoring them to Home + House would undo that choice on
  every reload.
- **Sign-out forgets.** On a shared device the next person gets Home and no
  record of which rooms the last one was in — asserted by checking the stored
  blob no longer contains the room id, not merely that the key was removed.

Baseline at handoff: **1138 backend**, **75 frontend**, lint 0, build 0.

## Task Group F — Integrated Release 1 gate — PASSED

| Task | Commit | Result |
|---|---|---|
| F3 defect found in the browser | `c3b28a2` | Restored URL now replaced; harness kept. |

### F1 — fresh verification (observed 2026-08-13, America/Chicago)

| | |
|---|---|
| Backend | **1138 passed** — exactly one summary line, no `failed`/`error`/interrupted |
| Frontend | **77 passed** across 10 files |
| Lint | 0 |
| Production build | 0 |

### F2 — exit-gate checklist

- [x] Bare `/` opens Home → House — *browser, `data-workspace-scene="house"`, switcher `aria-current` House*
- [x] Home → Record has a canonical URL surviving reload and Back/Forward — *browser, in-document history*
- [x] Ordinary room and branch default URLs unchanged — *`?room=<id>`, no scene param, no switcher*
- [x] House movement never exceeds the all-members intersection — **mutation re-proven at the gate**
- [x] Human House and Dialectic Home context are projection-identical — one service, asserted in `test_home_movement_pg`
- [x] Proposal types share one authority grammar without breaking existing write paths — **relay-driven disarming re-proven**
- [x] Reading/memory twins render once — **mutation re-proven at the gate**
- [x] Home pulse/table, messages, proposals, drawers, exactly-1024 desktop behavior operational — *browser*
- [x] Home projection p95 **measured**: 25 rooms / 300 items, median 12.0 ms, **p95 15.2 ms** against 150 ms
- [x] Backend, frontend, lint, build, static architecture, isolated browser acceptance

### Mutation re-proofs at the gate (red, then restored green)

| Guard | Mutation | Killed |
|---|---|---|
| Movement fence (B) | drop `JOIN er` from the `reading_filed` arm | `test_movement_sql_fences_every_arm_by_itself` |
| Reading twin (C) | drop `key NOT LIKE 'reading:%'` | 3 tests, incl. the direct-SQL one |
| Proposal authority (D) | stop reading the relay's accepted stamp | relay-disarming + accepting-human |

### Static architecture

- `ruff --select F`: **80 on master, 80 at HEAD** — this release introduced none.
- One destination writer: `setRoom`/`setThread`/`setWorkspaceScene` and
  `history.pushState`/`replaceState` appear in `useRoomNavigation.ts` **only**.
  (A first pass flagged `App.tsx` — that was a local variable named `pushState`,
  not a history call. Looked before reporting.)
- Projections contain **zero** `INSERT`/`UPDATE`/`DELETE`.
- **Migrations added by this release: none.** Everything projects entities that
  already exist, so deploy is backend restart → frontend flip, with no DB step.

### F3 — isolated browser acceptance: **16/16**

`dialectic_browser` on :8013, preview :4173, `SCHEDULER_ENABLED=0`, five widths
(1600 / 1200 / exactly 1024 / 820 / 390). Fixture processes were stopped by PID
only after `/proc/<pid>/cwd` was confirmed inside the worktree — a production
backend running from `/root/DwoodAmo/dialectic` was correctly left alone, and
production stayed `active` and healthy throughout. Harness kept at
`docs/superpowers/acceptance/2026-08-13-release-1-browser-acceptance.py`.

**The defect the browser found (`c3b28a2`).** A bare `/` restored the room
correctly and left the address bar reading `/`. Every unit test agreed with it,
because they asserted state rather than the URL. In a URL-authoritative app the
screen and the address disagreeing means a URL nobody can copy, share or reload
into the same place. A restored destination now installs with `replace` — never
`push`, so Back still leaves — while a deep link keeps `none`.

**The harness was wrong three times before it was right**, and each correction
is recorded beside the check it fixes:

1. It guessed `[data-scene]` / `.home-pulse` and reported the House missing
   while it was plainly on screen — the real markers are
   `data-workspace-scene` and `.home-house`, and a bare `[aria-current]`
   selector grabs the room rail's before the switcher's.
2. It compared card text case-sensitively while the CSS uppercases it, so it
   called the proposal cards absent while a button inside one was present —
   two contradictory readings in the same check, which is the tell.
3. It drove Back with cross-document `goto()`s, which re-boots the app and
   exercises restoration instead of history.

None of the three was a product defect. A probe that never reaches the code
proves nothing about it.

### F4 — journal

One release-level entry appended to `JOURNAL.md`, dated `2026-08-13` derived in
`America/Chicago`, carrying the observed backend integer (1138).

### Handoff

```text
CHANGES: Scene/identity, House movement, workspace adapters/proposals, and current-scene continuity
VERIFIED: Full Release 1 backend/frontend/static/browser gate with observed results
UNVERIFIED: Real-device macOS/Windows/iOS/Android checks not performed
NEXT: Release 2 — Artifact Workroom
```

### Carried forward to Release 2 / owner ruling

1. **§9.3's accepting human is not preserved** for `prediction_draft` and
   `prediction_resolution` — the relays write a boolean and log no event.
   Closing it means a write on the relay path, which Release 1 forbids.
2. **§8.2's research question is never persisted** — it travels over
   `DEEP_DIVE_STARTED` and is gone. The Brief projects what survives.
3. **`failed` and `dismissed` have no row**, deliberately for `failed`. Both are
   client-held today.
4. **Production carries zero proposals**, so D's envelope has fixture coverage
   only until one exists.

