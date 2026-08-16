# Dialectic — Current Release Authority

**Current release:** Big-Bang Production Stabilization

**Implementation authority:**
[`docs/superpowers/plans/2026-08-15-dialectic-big-bang-stabilization.md`](docs/superpowers/plans/2026-08-15-dialectic-big-bang-stabilization.md)

**Approved design:**
[`docs/superpowers/specs/2026-08-15-dialectic-big-bang-stabilization-design.md`](docs/superpowers/specs/2026-08-15-dialectic-big-bang-stabilization-design.md)

| Boundary | Current state |
|---|---|
| Design and implementation slices | Approved and implemented locally on `codex/dialectic-big-bang-stabilization-2026-08-15` |
| Integrated local gate | Complete 2026-08-16; exact counts, browser widths, screenshots, and red-green mutation ledger are in `JOURNAL.md` |
| PostgreSQL migration 018 | Applied to `dialectic_test` only; production unchanged |
| tradingDesk SQLite migration 006 | Exercised against isolated test databases only; production unchanged |
| Service/runtime/frontend | Production services, unit installation, restarts, and served assets unchanged |
| Activation | Requires a new explicit authorization after the integrated gate |
| Device proof | Five-width Playwright gate is local; real iPad/phone proof remains pending |

Releases 1–3 below are shipped history, not the active implementation queue.
Unfinished product work lives in `dialectic/TODOS.md`; durable decisions and
verification facts live in `JOURNAL.md` and git.

---

# Historical Release 3 — Deliberation and Whole-House Intelligence

Handoff for a fresh implementer with zero context. You cannot ask the author
anything. Everything you need is here or named here.

**Repo:** `/root/DwoodAmo` (monorepo). **Product:** `dialectic/`.
**Baseline at handoff (observed 2026-08-13, not inherited):** backend **1174
passed**, frontend **131 passed** / 19 files, lint 0, production build 0.
**Production:** master `a37725e`, backend PID 2048720 (as observed
2026-08-13), frontend release `20260813T222747Z-release-2-united-workroom`.

**Revision note (2026-08-13, second revision, same day):** supersedes the
497-line first draft in place. What changed: three factual corrections
(migration numbering, two citations), one latent code bug scheduled for
repair, the four owner-level open questions resolved into ratified rulings
(§3), and the implementation plan (§5) — task groups, architecture, build
order — added. The first draft had fences but no road; this one has both.

**Authority documents**, in precedence order:

1. Owner rulings recorded in `## AMENDMENTS` at the end of this file.
2. This file (§3's ratified rulings carry owner authority — see §3 preamble).
3. `docs/superpowers/plans/2026-08-12-dialectic-living-workroom-program.md`
   §"Release 3" — the scope and exit gate.
4. `docs/superpowers/specs/2026-08-12-dialectic-front-end-identity-design-v2.md`
   §14 (deliberation/inference), §15 (restoration), §16–17 (identity, a11y).
5. `docs/superpowers/plans/2026-08-12-dialectic-release-1-sdd-ledger.md` and
   `docs/superpowers/plans/2026-08-13-dialectic-release-2-united-workroom-gate.md`
   — what the two shipped releases decided, proved, and left open.

Releases 1 and 2 are **shipped and live in production**. This is the third and
final release of the program.

---

## 1. DECISIONS WITH RATIONALE

### 1.1 Task-group structure, one branch, no PR

**Decision.** One branch (`claude/release-3-deliberation`), task groups that
commit independently, one integrated gate at the end, then **merge to master
directly — no pull request**.

**Rejected:** the program document's "one branch, one pull request".
**Why it lost:** the owner ruled on 2026-08-13 "we don't do PR's". Release 2
was merged by fast-forward with no PR under that ruling. Owner ruling outranks
the program doc.

**Rejected:** a PR per task group. **Why it lost:** the program forbids
intermediate merge gates; both prior releases held to one gate and it worked.

### 1.2 Field starts as projection + one narrow marks table, not a reasoning database

**Decision.** The Field derives its reasoning objects from rows that already
exist — `messages` (+`metadata`), `events`, `references_message_id` reply
links, thesis structure in `rooms.trading_config`, branch genealogy, memory
supersession chains — using the adapter pattern Release 1 established, **plus
one narrow, room-local, append-only table (`field_marks`, migration 017) for
inferred provisional relationships and human corrections**. See §3 Ruling R1
for why the table exists and §5 TG-A for its design.

**Rejected:** build the durable reasoning-object store / compiler first.
**Why it lost:** spec §14.6 says this in as many words ("Do not build the
compiler first"), and lists a prerequisite order whose items 1–3 (workspace
object adapters, proposal normalization, source/provenance links) are
**shipped**, item 4 (object-centered scenes) is partially shipped (5 of 9
scenes), and item 5 — "local, reversible inferred relationships" — is exactly
what `field_marks` is and exactly where Release 3 starts.

**Rejected:** projection-only with no table at all. **Why it lost:** measured
production population (§6.6): 0 stored claim_checks, 2 reply references. A
deterministic-only Field is nearly empty in every room, and §14.5's
corrections must persist somewhere or the six human actions are cosmetic.

### 1.3 The three epistemic dimensions stay independent

**Decision.** `origin` (explicit | inferred), `review` (provisional |
confirmed | contested | superseded) and `deliberative_status` (active |
accepted | rejected | resolved | withdrawn) are three separate fields with
three separate vocabularies.

**Rejected:** one `status` enum flattening them. **Why it lost:** spec §14.2
requires independence, and "confirmed" must never imply "true" — collapsing
them makes that confusion structural rather than merely possible. Release 1
hit the same shape and kept `status` (entity lifecycle) separate from
`review_state` (what a human owes); follow that precedent, in
`dialectic/workspace_objects.py`.

### 1.4 Atlas is a semantic structure with a spatial view, not a graph engine

**Decision.** Build the list/tree representation first and make it complete.
Any spatial view is a second rendering of the same data and must carry
identical meaning.

**Rejected:** force-directed / freeform graph. **Why it lost:** the program's
Release 3 scope forbids it outright ("No force-directed or freeform graph
chaos"), and the design spec's §22 hard-prohibition list includes freeform
graph chaos.

### 1.5 Exact restoration extends the existing continuity module

**Decision.** Extend `dialectic/frontend/app/src/lib/sceneContinuity.ts`. It
already stores room + branch + scene per window (sessionStorage) with an
installation-wide fallback (localStorage), and already implements the
precedence `deep link / notification > local restoration > Home → House`.

**Rejected:** a new restoration store. **Why it lost:** it would be a second
answer to "where does this window resume", and the two would race at boot.

**Binding constraint:** `useRoomNavigation.ts` is the ONE destination writer.
Continuity **proposes** a destination and never installs one. Breaking this
re-introduces the competing-effect bugs that predate Release 1.

### 1.6 Every new projection is bounded per partition, in SQL

**Decision.** Field, Atlas and any long-lived room projection get caps applied
inside the statement, ranked within the partition before any global cut.

**Rejected:** a single global `ORDER BY … LIMIT`. **Why it lost:** Release 1
shipped exactly that and a room with 250 recent readings consumed the whole
budget, projecting **zero** movement for every other room while the House
still looked healthy. Existing precedents to copy:
`home_activity._MOVEMENT_PER_ROOM_CAP` (12) / `_MOVEMENT_TOTAL_CAP` (400),
`workspace_objects._PER_KIND_CAP` (50) / `_RECORD_CAP` (100, per source),
`proposal_envelope.PROPOSAL_CARRIER_CAP` (50).

### 1.7 Accessibility is verified with a real tool, added for this release

**Decision.** Add an automated a11y check (axe-core injected into the
Playwright harness — §7.4) — there is **none installed today**; `package.json`
has no axe dependency. Automated checks cover contrast, roles, focus order,
and name/role/value; they do **not** cover "no hover-only action" or "no
color-only meaning", which need explicit assertions you write.

**Arbitrary — safe to change:** axe-core specifically. What is *not*
arbitrary is that a11y claims must come from a tool plus explicit assertions,
not from reading the code.

### 1.8 Verification counts are re-observed at the gate, never inherited

**Decision.** The integrated gate re-runs everything and records fresh
numbers, including re-running every mutation proof from Releases 1 and 2.

**Rejected:** citing the task groups' own numbers. **Why it lost:** Release
2's branch recorded 1159 backend; on the merged tree it was 1162, because a
finishing commit landed after the gate was written. Inherited counts are
stale the moment anything else lands. (This document's own history proves the
rule twice: R1 gate 1138 → R2 gate 1159 → this baseline 1174.)

### 1.9 Deploy is backend-first, then the frontend flip

**Decision.** Migration, then backend restart, then the frontend symlink flip.

**Rejected:** frontend-first. **Why it lost:** a new frontend calling
endpoints a stale backend lacks produces 404s (or worse, the SPA fallback's
HTML with a 200). Backend changes in both prior releases were purely
additive, so an old frontend against a new backend is safe; the reverse is
not. `git log 7f512dd` records this hazard from the Release 2 deploy. Release
3 adds the program's first migration (017) — it is additive (one new table),
so the same ordering holds.

### 1.10 `field_marks` is append-only; review state is derived, never stored

**Decision.** No code path UPDATEs or DELETEs a mark. Human actions write new
rows; the review axis (provisional/confirmed/contested/superseded) is
**derived at read time** from review rows + successor lineage. The partial
unique index on `(room_id, dedup_key)` is the structural guarantee that a
human-corrected mark is never re-asserted by the inference job — rows are
never deleted, so a corrected mark's dedup key stays occupied forever and the
job's re-insert hits `ON CONFLICT DO NOTHING`. The prompt-side "do not
re-assert" digest is advisory; the index is the law.

**Rejected:** a stored review column with UPDATEs. **Why it lost:** violates
append-only and can go stale against its own history.
**Rejected:** two tables (inferences, corrections). **Why it lost:** two
fences, two caps, two write paths for one conceptual object; Ruling R1 chose
one narrow table.
**Rejected:** a Postgres trigger enforcing append-only. **Why it lost:** the
house has zero triggers; a pg test asserts the invariant instead (§7.3).

### 1.11 Human proposals reuse the message+metadata path

**Decision.** The propose surface (§3 Ruling R2, §5 TG-C) writes a normal
message whose `metadata` carries the proposal block, validated server-side.
`proposal_envelope.py` already normalizes exactly this shape;
`acceptance_stamp()` and the accept endpoints already handle the rest.

**Rejected:** a proposals table. **Why it lost:** the do-not-relitigate rule
"one contract, five stored shapes, no new storage" — the envelope exists
precisely so stored shapes don't multiply.

### 1.12 De-chat ships in two stages, grammar first

**Decision.** Stage F1 (gate-passing): remove bubble containers and
left/right alignment from primary surfaces; full-width contribution rows;
restrained signature marks (`AMO A / DAN D / DIALECTIC )`); provider names
out of primary controls. Stage F2 (skippable at gate if time presses): the
three typographic voices (serif/grotesk/mono, spec §16.5) and
motion-explains-causality (§16.8). See §3 Ruling R3.

**Rejected:** all-at-once recomposition. **Why it lost:** the surface is used
daily by both humans; F1 alone satisfies the exit gate's letter ("primary
surfaces no longer resemble generic chat"), so F2 riding behind it converts
an all-or-nothing risk into a staged one.

### 1.13 Real-device acceptance is an owner-run guided checklist

**Decision.** The builder prepares a ~10-minute per-device checklist (§7.6);
the owner runs it on real macOS / Windows / iPhone/iPad / Android; results
are recorded **verbatim** in the gate ledger. See §3 Ruling R4.

**Rejected:** emulation-only. **Why it lost:** the exit gate names real
devices; emulation stays as the builder's pre-check, not the record.

### 1.14 Guest access stays off — settled, not open

**Decision.** `GUEST_ACCESS_ENABLED` stays unset (= off, failing closed).
Nothing in Release 3 may assume a guest can reach a scene; the workroom
projection sits behind `get_current_user` and guests 401 on every scene.

**Settled by:** the Release 2 gate's owner ruling ("no guests for now"),
recorded in `docs/superpowers/plans/2026-08-13-…-release-2-…-gate.md` §6.
The first draft of this file listed this as an open question; it never was.

### 1.15 The `judgment` scene stays name-only this release

**Decision.** `judgment` remains in `WORKSPACE_SCENES` (approved name space)
and out of `IMPLEMENTED_WORKSPACE_SCENES`. It was Release 2 scope, was
deliberately not built there (its population — commitments — is 0 in
production), and is absent from the program's Release 3 scope. The
approved-name/implemented-list split (§2 item 10) handles it safely.
Recorded so nobody wonders; changing this needs an amendment.

### 1.16 Fix the thesis event predicate casing while it is free

**Decision.** `workspace_objects.py:218` matches
`event_type = 'THESIS_CREATED'`; the enum value (`models.py` `EventType`) is
lowercase `thesis_created`. Verified 2026-08-13: **zero** events of either
casing exist in production, so the fix is free now and expensive after events
accumulate. TG-A fixes it to lowercase. All-new event types are lowercase.

### 1.17 The program's first migration is numbered 017

**Decision.** `dialectic/migrations/017_field_marks.sql`. On-disk migrations
run 001–016 (`014_reading_library`, `015_room_watchlist`,
`016_voyage_embeddings` — all applied to the live DB). The first draft of
this file said "013 was the last applied"; minting 014 would collide.
**Also:** append the new table to `schema.sql` in the same commit — 014's
`reading_items` is absent from the baseline and that gap is a recorded trap
(dialectic/CLAUDE.md amendment); do not repeat it.

### 1.18 Tapping a workspace object selects it into Focus, product-wide

**Decision.** Object tap = select into Focus (the `&object=` URL axis);
"Open branch" becomes an action inside Focus. This changes Release 2's card
behavior (tap currently jumps to the branch — `App.tsx:517`
`openWorkspaceObject`). One interaction grammar everywhere; spec §7.4 makes
Focus THE inspection mechanism.

**Fallback if the owner objects on sight:** Focus-on-tap in the Field scene
only, R2 scenes unchanged. Owner-visible change — flag it in the gate demo.

### 1.19 The inference model is pinned by name

**Decision.** `llm/field_inference.py` pins
`FIELD_MODEL = "claude-haiku-4-5-20251001"`. Structure extraction over ≤30
messages is claim-check-grade work, not judgment. Note: `reading_echo.py:72`'s
`BACKGROUND_MODEL` has already drifted once (docstring says Haiku-grade, the
constant now reads `"claude-sonnet-5"`) — which is why this plan names the
exact string instead of "the usual background model". If mark quality
disappoints, bumping the constant is a one-line amendment.

### 1.20 Provisional marks map to generic `review_state='none'`

**Decision.** In `workspace_object_from_field_mark()` (the pure adapter, §5
TG-A), a provisional inferred mark maps to the generic projection's
`review_state='none'`, **not** `awaiting_human`. §14.3 marks are invitations;
routing every provisional inference into "Needs you" buries the proposals
that §9.4 puts there. The full three-axis state lives in the Field's own
projection; the generic mapping is lossy by design and documented in the
function. If the owner wants provisional visibility at House level, that is a
digest line ("3 unconfirmed marks") — a later, separate ask.

---

## 2. DO-NOT-RELITIGATE LIST

Settled. Do not revisit even if it looks wrong; if reality contradicts one,
use the Conflict Rule (§8) — flag and stop.

1. **`useRoomNavigation.ts` is the only destination writer.** Only it calls
   `setRoom`/`setThread`/`setWorkspaceScene` and `history.pushState`/
   `replaceState`. The Release 3 `object` axis extends `RoomDestination` and
   is installed the same way. *Settled by:* prior stale-closure and
   history-order regressions that this consolidation fixed.

2. **No universal artifact table.** Workspace objects are adapters over
   entities that already own their storage and lifecycle. *Settled by:* spec
   §19.4 and §8.1; Release 1 shipped seven adapters with zero new tables.
   (`field_marks` is not a counterexample: it is a new **entity** with its
   own narrow lifecycle, not a universal store — see item 14.)

3. **Projections never write.** `workspace_objects.py`,
   `proposal_envelope.py` and `api/workspace.py` contain no
   `INSERT`/`UPDATE`/`DELETE`; the workspace router exposes no write route.
   *Settled by:* an entity's write path stays with the entity that owns it.

4. **Reading + memory twin project as ONE object.** `llm/reading.py`
   deliberately writes a reading *and* a `reading:<domain>-<slug>` memory
   twin (`dedup=False`) so three-lane recall finds readings. A naive adapter
   emits both and **looks correct in every screenshot**. Same rule for a
   thesis and its `thesis_state_current` memory. *Settled by:*
   mutation-proven guards in `tests/test_workspace_objects_pg.py`; removing
   either kills tests.

5. **Bounds are per-partition, applied in SQL.** See §1.6. *Settled by:* a
   shipped production defect.

6. **Proposals: one contract, five stored shapes, no new storage.**
   `proposal_envelope.PROPOSAL_SLOTS` is the single slot→kind table, shared
   with the frontend and pinned by `tests/test_workspace_contract.py`, which
   reads the real `.ts` file. *Settled by:* the frontend previously held
   three private copies of a similar mapping and they drifted.

7. **`claim_check` is not a proposal.** It is a nudge, not a decision, and
   must never acquire an Accept button. *Settled by:* explicit exclusion from
   the slot table, asserted at both the normalizer and the rendered
   component.

8. **Acceptance records who, in the same patch that records that.**
   `proposal_envelope.acceptance_stamp()` + `ACCEPT_SLOT_SQL` /
   `ACCEPT_LIST_ITEM_SQL`. One event, one write — a second write could be
   interrupted and leave a proposal accepted by nobody. Field reviews follow
   the same rule (§5 TG-A). *Settled by:* owner approval 2026-08-13 and spec
   §9.3.

9. **`failed` stays in the proposal vocabulary** even though no row can hold
   it. A relay failure deliberately leaves `accepted` false so a retry is a
   fresh accept rather than a conflict; failure is client-held. Dropping it
   from the vocabulary is how a failed write becomes an invisible one.
   *Settled by:* spec §5.1 / §8.4.

10. **An approved-but-unbuilt scene falls back; it never opens dead UI.**
    `WORKSPACE_SCENES` (9 approved names) vs `IMPLEMENTED_WORKSPACE_SCENES`
    (at handoff: `house, record, bench, library, ledger`). Adding `field` or
    `atlas` to the implemented list is what makes it routable — do it only
    when the scene actually renders. `focus` and `judgment` stay OUT of the
    implemented list this release (§1.15; Focus is a state, not a scene —
    §5 TG-B). *Settled by:* the program forbids shipping a scene name that
    opens nothing.

11. **Restoration falls back silently for a lost room.** The candidate is
    validated against the caller's own room list *before* navigation is
    asked, so no access error fires for a room nobody requested — an error
    there would announce both that the room exists and that the user was
    removed from it. An explicitly requested lost room still refuses out
    loud. *Settled by:* Release-1 SDD ledger §E3 / spec §15.3. (The first
    draft cited "spec §E3"; no such section exists in the spec — §E3 is the
    Release 1 documents' label.)

12. **No Docker. No framework rewrite. No CRDT editor. No native app. No
    order placement.** *Settled by:* standing owner preference (Docker);
    spec §19.1 (no framework rewrite) and §21 (CRDT, native apps, order
    placement all deferred/non-goals). (The first draft cited §22 for all of
    these; §22 is the visual-grammar prohibition list.)

13. **Docs are amended beside, never silently edited** — dated stamps.

14. **`field_marks` must never grow into the reasoning compiler.** No
    cross-room rows, no global model pass, no ontology management. Room-local
    and reversible is the entire license (§14.6 item 5); the compiler is
    explicitly deferred until relationships "have proven useful in daily
    work". *Settled by:* spec §14.6, §19.4, §21.

15. **`api/workspace.py` stays write-free.** Field reviews get their own
    router (`api/field.py`). *Settled by:* the workspace router's own header
    contract ("read-only is a property of the router, not a promise in a
    docstring") and item 3.

16. **Append-only means append-only.** No code path UPDATEs or DELETEs a
    `field_marks` row; state changes are later rows; derivation happens at
    read time. *Settled by:* §1.10; a pg test asserts it (§7.3).

---

## 3. RATIFIED RULINGS (2026-08-13)

The first draft parked these as "ask the owner" open questions. They were put
to the owner with evidence and recommendations on 2026-08-13; the owner
ratified them by approving the revision plan that contains them. Each lists
what overriding costs; an override is a dated entry in `## AMENDMENTS`, and
the builder must re-plan the affected task group before continuing.

### R1 — Field storage: one narrow marks table (was Open Question 3.1)

**Ruling.** Release 3 introduces the program's first new table:
`field_marks` (migration 017) — room-local, append-only, holding **both**
LLM-inferred provisional relationships and attributable human
corrections/ratifications. Design in §5 TG-A.

**Why.** Spec §14.5 makes corrections first-class, attributable, and
persistent ("inform future room-specific inference") — a projection cannot
remember that a human said "these are different definitions". And the
measured production population (§6.6: 0 claim_checks, 2 reply references)
means a projection-only Field is nearly empty — the program's promised
inferred candidates (support/challenge, tension, synthesis) require LLM
inference, and inferred rows need durable, stable-ID storage the moment they
are born, or corrections have nothing stable to target. §14.6 forbids only
the **global** compiler; a room-local reversible table is its item 5, i.e.
the prescribed next step.

**Cost of overriding.** Option (a) projection-only: TG-A shrinks, but §14.5
is deferred beyond the program's final release and the six human actions
become cosmetic. Option (c) full reasoning store: violates §14.6 and §21 —
not available without amending the spec itself.

### R2 — The propose surface is Release 3 scope (was Open Question 3.2)

**Ruling.** TG-C builds a minimal propose surface ("Make a move") in
ordinary rooms.

**Why.** Production holds **zero proposals** because there is no place to
propose from. The owner mentioned on 2026-08-13 that a parallel agent might
hold this work; a full sweep the same day (all branches, all worktrees,
commit grep, file grep) found **no trace of it anywhere in this repo** —
only acceptance-side UI exists. The gap blocks three things at once:
proposals existing in production, the envelope carrying real data, and
`acceptance_stamp()` ever executing outside tests. Without it, Field's
human-ratification pipeline demos against fixtures forever.

**Cost of overriding.** Dropping TG-C keeps the release's core intact but
ships the program's final release with its proposal machinery production-dry;
record the gap in the gate ledger if overridden.

### R3 — De-chat is a staged full recomposition (was Open Question 3.4)

**Ruling.** As §1.12: F1 grammar (gate-passing), F2 voices+motion
(skippable at gate). The exit gate line "primary surfaces no longer resemble
generic chat" is satisfied by F1.

**Cost of overriding.** Deferring F1 entirely means amending the exit gate —
the program's final release would ship looking like chat, which §16.1 and
§22 items 1–2 exist to prevent.

### R4 — Real-device acceptance is an owner-run checklist (was Open Question 3.3)

**Ruling.** As §1.13; checklist template in §7.6. The builder cannot reach
real devices from this environment; the owner is the acceptance instrument,
and their reported results are recorded verbatim.

**Cost of overriding.** Emulation-only requires amending the exit gate's
real-device line.

---

## 4. OPEN QUESTIONS — ASK BEFORE DECIDING

Stop and ask the owner. Do not improvise.

**4.1 Housekeeping: a stray room in production.**
Room `eeffa8f1-9d5a-4d31-981d-b5cf0a0627e8`, named `probe-do-not-create`,
created 2026-08-13 by a mistaken probe. 1 thread, 2 events, **0 members, 0
messages**, invisible to everyone because Home's projection is
membership-fenced. Harmless but junk. Deleting anything in production needs
an explicit owner yes; ask at the gate (§5 TG-H), not before — it blocks
nothing.

(That is the whole list. The first draft's other six questions are resolved:
3.1→R1, 3.2→R2, 3.3→R4, 3.4→R3, 3.5→§1.14, 3.7→the gate runbook pushes
master, so the two commits pending at handoff ride along.)

---

## 5. IMPLEMENTATION PLAN

### 5.0 How to run the build

- **Orchestration mode.** The orchestrating session specs each task group,
  launches builder subagents with **disjoint file ownership and explicit
  DO-NOT-TOUCH lists** (stated per TG below), then proofreads every diff
  itself, fixes what needs fixing, and owns all commits. Builders run their
  own verification before reporting; their reports are claims to verify
  against the tree.
- **Branch** `claude/release-3-deliberation` off master. Per-TG commits with
  house-style messages. Shared/wire-up files (`api/main.py` registrations,
  `App.tsx` scene wiring) land last within each TG's commit so feature
  commits stay bisectable.
- **No production service is restarted during the build.** All browser work
  runs the isolated fixture (§7.1). Deploy happens once, at TG-H.
- **Dependency order:** A → B; C after A (copies its router precedent); D and
  E anytime after A; F after B and C exist (it restyles their surfaces);
  G after A and D (it seeds their tables); H last. B, C, D, E can run as
  parallel builders once A lands — their file sets are disjoint by
  construction.
- **The contract seam crosses A/B deliberately:** TG-A owns the one-line
  addition of `'field_mark'` to BOTH `WORKSPACE_OBJECT_KINDS` (python) and
  its TS mirror tuple — the existing order-pinned contract test forces the
  pairing into one commit. TG-B owns every other frontend file, including
  the new `FIELD_*` TS mirrors and the contract-test additions that pin
  them.

### 5.1 TG-A — Field backend: migration, projection, inference, reviews

**Owns:** `dialectic/migrations/017_field_marks.sql`, `dialectic/schema.sql`
(append), `dialectic/field_marks.py` (new), `dialectic/api/field.py` (new),
`dialectic/llm/field_inference.py` (new), `dialectic/models.py` (EventType
additions), `dialectic/workspace_objects.py` (kind tuple, pure adapter
function, the :218 casing fix), `dialectic/llm/research.py` (research-question
persistence), `frontend/app/src/types/workspace.ts` (ONLY the one-line
`'field_mark'` kind-tuple mirror), `api/main.py` (router + pool + job
registration — wire-up, last), tests: `test_field_marks_pg.py`,
`test_field_api.py`, `test_field_inference.py` (new), plus the required edits
in `test_workspace_objects_pg.py` and `test_workspace_contract.py`'s
kind-tuple expectations.
**Do not touch:** `proposal_envelope.py`, `api/workspace.py` (read its
header; your router lives beside it, not in it), `home_activity.py`, all
other frontend files.

**Migration `017_field_marks.sql`** — one table, two row species
(`mark_kind`: `relation` = an asserted reasoning relationship; `review` = a
human action on a prior mark). Replacement content from correct/split/merge
is written as NEW relation rows (origin `explicit`) in the same transaction,
linked by lineage:

```sql
CREATE TABLE IF NOT EXISTS field_marks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    thread_id UUID REFERENCES threads(id) ON DELETE SET NULL,  -- NULL = room-wide
    mark_kind TEXT NOT NULL CHECK (mark_kind IN ('relation','review')),
    relation TEXT,   -- §14.3 vocabulary; comment-documented, contract-pinned, no CHECK (the list may grow)
    action TEXT CHECK (action IN ('confirm','contest','correct','supersede','split','merge')),
    origin TEXT CHECK (origin IN ('explicit','inferred')),
    deliberative_status TEXT NOT NULL DEFAULT 'active'
        CHECK (deliberative_status IN ('active','accepted','rejected','resolved','withdrawn')),
    subjects JSONB NOT NULL DEFAULT '[]',  -- array of {entity,id,field} — exactly WorkspaceSourceRef
    target_mark_id UUID REFERENCES field_marks(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}',   -- quote/span, note, merge_group, action extras
    supersedes_id UUID REFERENCES field_marks(id),  -- replacement → what it replaces
    caused_by_id  UUID REFERENCES field_marks(id),  -- replacement → the review row that caused it
    actor_user_id UUID REFERENCES users(id),        -- NULL = Dialectic
    provenance TEXT NOT NULL,                       -- 'field_inference' | 'human'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dedup_key TEXT,                                 -- inference idempotency; set on ALL relation rows, NULL on reviews
    CONSTRAINT relation_iff_relation CHECK ((mark_kind='relation') = (relation IS NOT NULL)),
    CONSTRAINT action_iff_review     CHECK ((mark_kind='review')   = (action   IS NOT NULL)),
    CONSTRAINT review_has_target     CHECK (mark_kind <> 'review' OR target_mark_id IS NOT NULL),
    CONSTRAINT review_has_actor      CHECK (mark_kind <> 'review' OR actor_user_id  IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_field_marks_dedup
    ON field_marks (room_id, dedup_key) WHERE dedup_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_field_marks_room     ON field_marks (room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_field_marks_target   ON field_marks (target_mark_id);
CREATE INDEX IF NOT EXISTS idx_field_marks_subjects ON field_marks USING GIN (subjects jsonb_path_ops);
```

**`field_marks.py`** (header in the `workspace_objects.py:1–39` style: the
marks metaphor — proofreader's marks on the room's reasoning — plus the
append-only invariant):
- Vocabularies, all order-pinned tuples: `FIELD_RELATIONS` (11 — §14.3's ten
  with support/challenge split: `contribution_type, claim_group, supports,
  challenges, repeated_definition, possible_contradiction, emerging_position,
  evidence_attachment, branch_candidate, unanswered_question,
  candidate_synthesis`), `FIELD_ACTIONS` (6), `FIELD_ORIGINS` (2),
  `FIELD_REVIEW_STATES` (`provisional, confirmed, contested, superseded`),
  `FIELD_DELIBERATIVE_STATUSES` (5). **§14.4's human-only judgments are
  structurally unwritable: none of them is in `FIELD_RELATIONS`.** State
  that as the guard, in a comment, not a TODO.
- Models: `FieldReview` (id, action, actor_user_id, note, created_at),
  `FieldMark` (id `field_mark:<uuid>`, room_id, thread_id, relation, origin,
  review *derived*, deliberative_status, subjects: list[WorkspaceSourceRef],
  title, payload, supersedes_id, caused_by_id, actor_user_id, provenance,
  created_at, reviews: list[FieldReview]), `FieldProjection` (generated_at,
  room_id, marks).
- `FieldMarkService.build(room_id)`: ONE statement fenced on `room_id`
  (house rule), cap **500** rows in the SQL itself, review rows joined by
  `target_mark_id`; derivation and lineage anchoring in Python. Read-only by
  construction.
- **Derived review rule:** a relation row is `superseded` if any successor
  names it via `supersedes_id` OR its latest review ∈ {supersede, correct,
  split, merge}; else `contested`/`confirmed` per its latest confirm/contest
  review; else `provisional` (for inferred) — an explicit human relation with
  no reviews also derives `provisional`-equivalent display; its `origin`
  axis already says a human asserted it (§14.2: the axes stay independent;
  confirmed-at-birth is not a thing).
- **Ordering rule (anti-reshuffle made concrete):** sort key
  `(root_anchor.created_at, root_anchor.id, own.created_at, own.id)` where
  root_anchor = follow `supersedes_id` to the chain head. New marks append;
  a correction's replacement renders **in its ancestor's position**;
  confirms restyle in place. Nothing ever re-sorts on update — contrast
  `WorkspaceObjectService.build()`'s newest-first re-sort
  (`workspace_objects.py:352`), which the Field must NOT copy.
- Reconciliation with the generic projection: add `'field_mark'` to
  `WORKSPACE_OBJECT_KINDS` (+ TS mirror) and ship a pure
  `workspace_object_from_field_mark(mark)` mirroring
  `workspace_object_from_movement` (`workspace_objects.py:718`), but do
  **NOT** add an adapter to `WorkspaceObjectService.build()` this release.
  Mapping (documented in the function): `status` := derived review;
  `provenance.origin` := 'dialectic' for inferred / 'human' for explicit,
  `detail` := relation; `review_state` := confirmed→`accepted`, everything
  else→`none` (§1.20). Lossy by design; Atlas is the likely first consumer.

**`api/field.py`** (module-level `_db_pool` + `set_field_db_pool` + `get_db`
idiom; `_authorize` copied from `api/workspace.py:50` — both credentials,
JWT + `X-Room-Token`; registered in `api/main.py` beside the workspace
router; all paths under `/rooms/…` so **no nginx or vite.config.ts edit is
needed** — the workspace router proved this path):
- `GET /rooms/{room_id}/field` → `FieldProjection` (marks with derived
  review + inline review history — Focus needs both).
- `POST /rooms/{room_id}/field/marks/{mark_id}/review` — body `{action,
  note?, replacement?: {relation, subjects, title, payload},
  replacements?: […], merge_ids?: […]}` → 200 `{review, replacements, mark}`.
  Action semantics: confirm/contest = one review row (latest wins); correct
  = review + 1 replacement (`supersedes_id`=target, `caused_by_id`=review);
  split = review + N replacements; merge = one review row per merged source
  (shared `payload.merge_group`) + one replacement whose
  `payload.merged_ids` lists them; supersede = review alone (how "this
  question is already answered" retires an `unanswered_question`).
  **All writes in ONE transaction; on any failure nothing lands.**
  Attribution follows `acceptance_stamp` (`proposal_envelope.py:127`): who +
  when written in the same insert as the action — no review can be "by
  nobody". Validation: target must be `mark_kind='relation'` and belong to
  the room (404); correct/split/merge/supersede on an already-superseded
  target → 409; repeat confirm/contest matching the current latest state →
  409 naming the state; replacement subjects re-validated against the room
  (422) — client payloads are documents, not trust boundaries.
- Events, lowercase, payload always a dict (`events.payload` is NOT NULL):
  `field_mark_inferred` (one per inserted inference row),
  `field_mark_reviewed` (one per review action; payload: action, target
  id(s), replacement id(s), actor).

**`llm/field_inference.py`** (template: `llm/reading_echo.py` — flags, caps,
dedup, event+row transaction, per-room try/except, own pool connections):
- `Job("field_inference", 1800, run, enabled_env="FIELD_INFERENCE_ENABLED")`,
  default ON (house pattern), registered in the `api/main.py` lifespan
  beside the other nine jobs.
- Per active room (message in 48h): **cheap gate before any LLM spend** —
  skip if no new messages since the room's newest mark and since last run;
  skip if daily cap hit. Idle days cost ≈ zero calls.
- Inputs: last 30 non-deleted messages, the room's active marks (compact),
  and the **correction digest** — every review row with action ∈ {contest,
  correct, supersede, split, merge} + its target's relation/subjects/title,
  rendered as "the humans have ruled on these; do not re-assert" (§14.5's
  "inform future room-specific inference").
- One call, `FIELD_MODEL` (§1.19), max_tokens ~1500, temp 0.2, tolerant
  JSON parse. Output: candidate marks `{relation, subjects, title, quote}`.
- **Hard validation, not prompt trust:** relation ∈ `FIELD_RELATIONS`;
  every subject resolves to a real row IN THIS ROOM via fenced SQL — the
  model cannot mint provenance (exit gate: "fully sourced"). Then INSERT
  `origin='inferred'`, `provenance='field_inference'`, actor NULL,
  `dedup_key = relation + '|' + sorted("entity:id[#field]" list)`,
  `ON CONFLICT (room_id, dedup_key) DO NOTHING`.
- Caps: `FIELD_INFERENCE_ROOM_CAP` 6 marks/room/run,
  `FIELD_INFERENCE_DAILY_CAP` 20 marks/room/day, counted from `field_marks`
  rows — the row count IS the budget.
- No WS push this release: the scene refetches on entry and after reviews.
  Deferred deliberately; do not add a broadcast path.

**Small repairs riding along:** the §1.16 casing fix; persist the research
question into the deep-dive message's metadata at write time in
`llm/research.py` (Release 1 ledger carried-forward: §8.2's "Research
question" currently travels over `DEEP_DIVE_STARTED` and is lost).

**Done when:** migration applies to a fresh `dialectic_test` (baseline +
001–017); all three new test files pass against real Postgres; the two
edited test files pass; mutation proofs red-then-green (§7.3); ruff F clean
on new files; backend suite one clean "N passed".

### 5.2 TG-B — Field + Focus frontend

**Owns (all under `frontend/app/src/`):** `types/workspace.ts` (except the
kind-tuple line TG-A owns), `types/index.ts` (`RoomDestination`),
`lib/workspaceRoute.ts`, `lib/api.ts` (add `getFieldMarks`,
`postFieldReview`), `hooks/useFieldMarks.ts` (new),
`components/workspace/scenes/FieldScene.tsx` (+css, new),
`components/workspace/focus/*` (new), `components/workspace/SceneSwitcher.tsx`
(label), `App.tsx` (sceneContent + Focus render — wire-up, last), frontend
tests for all of it.
**Do not touch:** backend files, `MessageBubble.tsx`/chat components (TG-F),
`sceneContinuity.ts` (TG-E), `useRoomNavigation.ts` internals (extend
`RoomDestination`; the hook passes the axis through — if its internals need
more than pass-through, stop and flag).

- **Scene wiring = the four coordinated edits:**
  `IMPLEMENTED_WORKSPACE_SCENES` += `'field'`; `SCENE_LABELS` +=
  `field: 'Field'` (total Record — omission is a build error by design);
  `scenesForDestination` ordinary room →
  `['record','bench','field','library','ledger']` (THE one definition; Home
  root unchanged — Home holds no Field); `App.tsx` `sceneContent.field`.
- **Data:** `useFieldMarks(roomId, enabled)` — copy `useWorkspaceObjects.ts`
  wholesale (three-state discriminated union loading|unavailable|ready,
  request-ticket ref, microtask before first setState) + a `refresh()`
  invoked after every review POST.
- **Layout — editorial bands, no graph engine (§16.7):** fixed-order
  sections grouped by relation: Positions (emerging_position) · Claims
  (claim_group, contribution_type) · Tensions (possible_contradiction,
  challenges — rendered between their two subjects as an indented
  cross-rule) · Questions (unanswered_question) · Definitions
  (repeated_definition) · Evidence (evidence_attachment) · Syntheses
  (candidate_synthesis) · Branches (branch_candidate). Support/challenge
  edges render as indented lines under their subject row ("— supports →
  <claim title>"). Plain rows, hairline rules, indentation; **not rounded
  cards**. Subject titles resolve client-side from the generic projection by
  object id (a Map) — a mark referencing a reading shows the reading's title
  but the reading stays ONE object; no second projection.
- **Provisional encoding (§16.4, never color-only):** inferred+provisional →
  dashed left rule + ~0.72 opacity + a literal "provisional" chip;
  confirmed → solid + oxidized-copper accent + "confirmed"; contested →
  oxblood underline + "contested"; superseded → collapsed behind a
  per-lineage "history" disclosure, never deleted from view.
- **Stable order:** sections fixed; within a section, TG-A's anchor
  ordering. Confirming restyles in place; correcting swaps content at the
  same ordinal. A browser assertion checks DOM order before/after a review.
- **Empty state that teaches** (SceneEmpty's four-question contract): what
  the Field is (the room's reasoning laid out), what lands here (positions,
  claims, tensions, questions), how (Dialectic pencils provisional marks in
  a lighter hand as the conversation grows), what you can do (your confirm
  makes a mark solid; your contest puts it on notice; nothing Dialectic
  marks outranks what you say). No fake action button — the on-ramp is
  talking.
- **Focus — a state, not a tab:** `RoomDestination` gains
  `object?: string | null`; `destinationFromSearch`/`destinationUrl` carry
  `&object=<workspace object id>`; installed ONLY via
  `useRoomNavigation.navigate`; unknown object id renders Focus's own
  unavailable state, never a 404. `'focus'` stays OUT of
  `IMPLEMENTED_WORKSPACE_SCENES` — a permanent Focus tab is precisely the
  "generic permanent tab" §7.4 says Focus replaces. Desktop: right column
  inside the scene frame's content area; mobile: full-surface takeover with
  back = `navigate({…, object: null})`.
- **Focus components** (`components/workspace/focus/`): `FocusSurface`
  (dispatch by kind), `FocusHeader` (title in propositional serif — §16.5),
  `FocusAxes` (three axes as text labels), `FocusSources` (provenance mono
  list; each ref navigates via the caller's `navigate`, never a server
  destination string), `FocusStructure` (incoming/outgoing marks by
  relation; provisional = dashed + label), `FocusHistory` (review rows +
  supersession lineage), `FocusActions` (confirm/contest one-tap with note
  field; correct/split/merge open a minimal editor; gated on membership).
  §7.4's ten reveal items scoped honestly: 6 buildable in full (state,
  sources, relationships, open questions, proposal state, actions), 3
  partial (evidence, branch variants, revision history), checks
  render-if-present (`metadata.claim_check`; 0 in prod today).
- **Tap behavior:** object tap = select into Focus product-wide (§1.18);
  "Open branch" becomes a Focus action.

**Done when:** frontend suite + lint + `npm run build` clean; the contract
test pins the new FIELD_* vocabularies; `workspaceRoute` tests cover the
`object` axis round-trip; sceneCopy test covers the Field empty state; a
FocusSurface render test asserts the state LABELS exist (not color-only).

### 5.3 TG-C — The propose surface

**Owns:** the composer area of `components/chat/` (a new `ProposeMenu`/
"Make a move" affordance + its styles/tests), the message-create path's
server-side validation block for human proposal metadata, `lib/api.ts` if a
parameter is needed.
**Do not touch:** `proposal_envelope.py` (its slot table is the contract —
you conform to it, not it to you), `MessageBubble.tsx` acceptance cards
(TG-F restyles them), `field_marks` anything.

- "Make a move" in ordinary rooms opens a minimal form for the proposal
  kinds the envelope already normalizes (prediction draft, thesis proposal,
  reading draft, commitment proposal — mirror `PROPOSAL_SLOTS`; leave
  resolution proposals to the LLM flow that owns them).
- Submitting writes a **normal message** whose `metadata` carries the
  proposal block (§1.11) — validated server-side against the same shapes the
  envelope parses; reject unknown kinds and malformed payloads at the door.
  The envelope, the proposal cards, and `acceptance_stamp()` then work
  unchanged — that is the entire point.
- The affordance must not depend on hover (§17.4) and must be reachable at
  phone width.

**Done when:** a human-authored proposal round-trips in the isolated fixture:
compose → message lands with metadata → envelope projects it → the OTHER
fixture user accepts it → `accepted_by` stamps. Covered by one pg/API test
plus one browser-acceptance scenario (§7.3).

### 5.4 TG-D — Atlas

**Owns:** `dialectic/atlas_objects.py` (new), its route (new file
`dialectic/api/atlas.py`), `frontend/app/src/components/workspace/scenes/AtlasScene.tsx`
(+css, new), `hooks/useAtlas.ts` (new), `lib/api.ts` (add `getAtlas`),
`lib/workspaceRoute.ts` (ONLY the Home-root scene-list line), tests
`test_atlas_pg.py`, `test_atlas_api.py` (new), frontend tests.
**Do not touch:** `home_activity.py` (read it; its fence is the model, but
Atlas's fence is deliberately different — see below), `field_marks.py`
internals (consume `workspace_object_from_field_mark` if useful).

- **Authorization is per-viewer, not all-members-intersection.** House shows
  a shared surface, so it is fenced to the all-members intersection; Atlas
  is personal navigation, so its fence is **the caller's own memberships**
  — exactly "Atlas authorization matches source-room authorization" from the
  exit gate. Every arm of every SQL statement is fenced by the caller's
  eligible-room array, in the SQL, per-partition capped (§1.6).
- **Nodes:** rooms, branches, theses, readings, briefs, commitments,
  unresolved work (open questions from field_marks + due commitments).
  **Edges — real provenance only:** branch genealogy
  (`threads.parent_thread_id`), Echo citations (`memory_references` — the
  one durable cross-room edge table, 7 rows in prod), reading →
  `source_message_id`, thesis ↔ room binding (`linked_book_id`), memory
  supersession chains (`superseded_by_memory_id`). **Contradictions ship as
  labeled derived proxies** (supersession chains + `claim_check` verdicts
  where present) — the vocabulary reserves richer kinds; do not invent edges
  the rows cannot back.
- **Endpoint:** `GET /users/me/atlas` — JWT only, no room token (it is
  cross-room by construction, fenced by memberships). The `users` nginx
  prefix is already proxied; **no nginx edit**. Response: a typed
  `AtlasProjection` (nodes + edges + generated_at), per-kind caps in SQL.
- **Frontend:** AtlasScene, list/tree first and complete — grouped rooms →
  branches → artifacts, plus cross-cutting groups (Echoes, shared sources,
  unresolved work). Joins the Home-root scene list:
  `['house','atlas','record']`. Every node navigates via `navigate()`
  (rooms/branches → destinations; objects → `object` axis). Any later
  spatial view is a second rendering of this same projection (§1.4) — not
  this release unless time is spare after the gate list is green.
- **The two-user test, by value:** a pg fixture with two users of
  overlapping-but-different memberships asserts — with sentinel CONTENT, not
  just ids — that neither's atlas carries a title from a room the other
  alone belongs to (the `OTHER-ROOM-SENTINEL` pattern from
  `test_workspace_objects_pg.py`).

**Done when:** pg + API tests green incl. the two-user fence by value;
browser scenario renders a populated Atlas in the fixture and navigates one
node of each group; p95 measured at TG-G seed scale.

### 5.5 TG-E — Exact restoration

**Owns:** `lib/sceneContinuity.ts`, `stores/appStore.ts` (the `setRoom`
reset + any store plumbing), the App-level draft/reply wiring (`App.tsx`
sections that hold `replyToId` and composer state — coordinate with TG-B's
App.tsx wire-up; land after it), their tests.
**Do not touch:** `useRoomNavigation.ts` (continuity **proposes**; the hook
installs), `workspaceRoute.ts` (TG-B/TG-D own their lines).

- **Payload v2, versioned:** `StoredScene` gains `v: 2` and `objectId,
  focusMode, inspectorTab, fieldViewport, recordScroll, openProposal,
  composerDraft, replyToId` (the §15.2 list). A v1 blob (no `v`) restores
  its four fields and defaults the rest — never a parse failure; continuity
  may never be the reason a boot fails (the module's own rule).
- **Tiers stay as they are** (§15.4): sessionStorage = window locality,
  localStorage = installation fallback; no server sync, no API call in the
  module, devices and profiles independent.
- **Reconcile, don't replay (§15.5):** restored `objectId`/`replyToId` are
  validated against server truth after boot — a missing object falls back
  object → scene → room → Home → House (nearest valid parent, silently for
  anything not explicitly requested — §2 item 11); scroll/viewport clamp to
  content bounds; **a restored composer draft stays local until sent**;
  proposal status, access rights and artifact revisions are rebuilt from the
  server, never from the blob.
- **Per-room state resets:** `appStore.setRoom` already resets
  `workspaceScene` on room change; the new axes (selected object, focus
  mode, inspector tab, scroll) reset in the same place, or they bleed across
  rooms (a flagged hazard, found in exploration).
- **Sign-out forgets:** extend `forgetScene()` to clear every v2 field.
  Deep links and notifications still override restoration — the precedence
  chain is already implemented and tested; extend its tests, don't rewrite
  it.

**Done when:** unit tests cover v1→v2 degradation, each fallback tier, and
the reconcile rules; the browser scenarios in §7.3 (kill-and-reopen restores
the exact spot; deep link overrides; draft survives reload but is not sent)
pass in the fixture.

### 5.6 TG-F — Identity, de-chat, accessibility

**Owns:** `components/chat/MessageBubble.tsx` + chat CSS,
`components/chat/MessageList.tsx` styling, identity tokens/CSS, new
signature-mark component, `package.json` (axe devDependency — then
`npm ci`), the a11y/grayscale additions to the browser harness.
**Do not touch:** scene/Focus components (TG-B), composer logic (TG-C —
restyle only), continuity (TG-E).

- **F1 — grammar (gate-passing):** primary surfaces lose bubble containers
  and left/right alignment; contributions render as full-width rows with
  restrained signature marks (`AMO A / DAN D / DIALECTIC )`), hairline
  separation, no participant color coding (color does not encode
  participants — §16.4); provider names out of primary controls (provenance
  and diagnostics keep them). Proposal/acceptance cards inside messages keep
  their function; restyle their chrome to match.
- **F2 — voices and motion (skippable at gate):** propositional serif /
  operational grotesk / provenance mono applied per §16.5; motion only where
  it explains causality (§16.8), inside the disallowed-list (no ambient
  anything, no thinking theater); reduced-motion retains all meaning.
- **a11y (§7.4 of the spec, 11 items):** axe-core injected into the
  Playwright harness (§7.4 below) at every checked width + explicit
  assertions: no action reachable only by hover; every state distinction
  carries a text label (the chips TG-B ships make provisional encoding
  pass); keyboard walk of Field → Focus → review action; visible focus.
- **Grayscale check:** render key screens with a grayscale CSS filter in
  the harness, screenshot, and LOOK at them (measurement is not render):
  still recognizably Dialectic without the wordmark; human-only rooms too.

**Done when:** F1 shipped and proven at the five widths; axe passes or every
violation is triaged in writing; the grayscale screenshots are in the gate
ledger; frontend suite/lint/build clean after `npm ci`.

### 5.7 TG-G — Seed + performance

**Owns:** `docs/superpowers/acceptance/seed_release3.py` (new),
`docs/superpowers/acceptance/perf_release3.py` (new).
**Do not touch:** production. Everything runs against `dialectic_browser`
(or a dedicated seed DB) — **never** the `dialectic` database.

- Seed at scale: ~50 rooms, ~2k messages, ~500 memories (with supersession
  chains), ~100 readings (+twins, via the writer's own key function), ~200
  `field_marks` including lineage chains and reviews, echo references,
  commitments. Deterministic UUIDs, frozen timestamps (the
  `test_workspace_objects_pg.py` `_uid`/`_d` idiom).
- Measure p95 over ~100 timed requests each: `GET /rooms/{id}/workspace/objects`,
  `GET /rooms/{id}/field`, `GET /users/me/atlas`, Home activity — against
  the **150 ms** design target (§20.4; House measured p95 ≈ 51 ms at R1
  seed scale — do not regress it). Record observed numbers, at seed scale,
  in the gate ledger. Let the fixture backend warm up before measuring — a
  probe minutes after restart measures the warm-up, not the code.

**Done when:** the numbers are recorded and either meet the target or carry
a written analysis + owner flag (Conflict Rule if structurally unmeetable).

### 5.8 TG-H — Integrated gate, merge, deploy

Run by the orchestrator, not a subagent. In order:

1. Fresh full verification (§7.1): backend suite, frontend suite, lint,
   `npm ci` + production build, `ruff --select F` on changed files (count ≤
   master's 80 pre-existing).
2. Re-prove **every** R1/R2 mutation guard red-then-green, plus the new
   ones (§7.3) — targeted edits, never `git checkout`.
3. Isolated browser acceptance (§7.1 fixture), extended with the Release 3
   scenarios (§7.3 list), screenshots looked at, service workers
   unregistered first.
4. a11y + grayscale + widths (TG-F artifacts re-run fresh).
5. Perf numbers re-observed at seed scale (TG-G).
6. Owner device checklist (§7.6) — results verbatim into the ledger.
   **Ask §4.1 (stray room) here.**
7. Write the gate ledger + a release-level `JOURNAL.md` entry: observed
   backend integer, date derived in `America/Chicago`.
8. Merge to master (ff if possible), push origin — the two commits pending
   at handoff ride along.
9. Deploy, three steps, in order: `psql dialectic -f
   dialectic/migrations/017_field_marks.sql`, verify with `\d field_marks`;
   `systemctl restart dialectic`, poll `/health` to a real 200 (unit-active
   is not serving); frontend `npm ci && npm run build` →
   `/var/www/dialectic-releases/<UTC-ts>-release-3-deliberation` → flip
   `/var/www/dialectic-current` symlink → `systemctl reload nginx` → probe
   origin past Cloudflare (`curl --resolve dialectic.somacura.org:443:127.0.0.1`)
   and confirm the served bundle hash changed.
10. Post-deploy: watch `journalctl -u dialectic` (local-time `--since`; app
    logs stamp UTC) through one `field_inference` cycle; confirm caps hold
    and no error lines; delete the stray room only if the owner said yes.

---

## 6. REPO / ENVIRONMENT ORIENTATION

### 6.1 What the monorepo is

Dialectic — two humans and an LLM co-reasoning in real time. The LLM is a
participant, not an assistant: it decides when to speak, checks live market
data with tools, remembers with attribution, follows up on silence.

| Dir | What | Runtime |
|---|---|---|
| `dialectic/` | The product: FastAPI backend + React PWA | `dialectic.service`, :8002, Postgres |
| `trading/` | tradingDesk: causal-DAG thesis engine | `tradingdesk.service`, :8006 loopback, SQLite |
| `cc-sidecar/` | Claude Code observability daemon | optional local |

(There is also `defuddle.service` on :8010 — the Node article extractor
behind the `read_article` tool. Not touched by this release.)

### 6.2 Modules that matter for Release 3

**Backend (`dialectic/`)**

- `workspace_objects.py` — seven read-only adapters plus
  `workspace_object_from_movement`. **The pattern Field and Atlas follow.**
  Read its 39-line header first: the twin rule, what is *not* a twin, why
  bounds are per-kind. Known repair: line 218's `'THESIS_CREATED'` (§1.16).
- `proposal_envelope.py` — one contract over five stored proposal shapes;
  `PROPOSAL_SLOTS`, `acceptance_stamp()` (:127 — the attribution model for
  Field reviews too), status derivation from room state.
- `home_activity.py` — the House projection; membership-intersection privacy
  fence; `_MOVEMENT_SQL` is the model for a fenced multi-source UNION.
  (Atlas's fence is per-viewer instead — §5.4 says why.)
- `api/workspace.py` — read-only endpoints, two credentials
  (JWT + `X-Room-Token`), no write route; `_authorize` at :50 is the
  copy-source for new routers.
- `api/capabilities.py` — what the server reports about open doors. **Its
  routes live under `/auth/…` and `/rooms/…` on purpose** — see 6.4. Its
  header records which background jobs default OFF in this deployment
  (reading_echo, wire, news digest, prediction watch are named "mostly
  OFF") — check the live flag before designing around a job's data.
- `api/main.py` — app, routers, WebSocket, lifespan (pool codec
  registration — a bare `asyncpg.connect` has no codec and returns JSONB as
  text; scheduler job registration ~:254-265; router + pool wiring ~:210,
  :361).
- `models.py` — `EventType` enum: **all values lowercase on the wire.**
- `llm/reading_echo.py` — the scheduled-job template (flags, caps, dedup,
  event+row transaction, per-room try/except). `BACKGROUND_MODEL` at :72.
- `llm/orchestrator.py`, `llm/tools.py`, `llm/tool_loop.py` — the
  participant. `memory/manager.py` — three-lane recall. `scheduler.py` —
  advisory-locked jobs on the `scheduled_job_runs` ledger.

**Frontend (`dialectic/frontend/app/src/`)**

- `hooks/useRoomNavigation.ts` — THE destination writer. Do not add a
  second. `types/index.ts:18` `RoomDestination` is the shape the `object`
  axis extends.
- `lib/workspaceRoute.ts` — the URL grammar (pure, unit-testable);
  `scenesForDestination()` is the ONE scene-list definition.
- `lib/sceneContinuity.ts` — device-local restoration; proposes, never
  installs; the v2 payload lands here (§5.5).
- `types/workspace.ts` — scene vocabulary (`WORKSPACE_SCENES` :9,
  `IMPLEMENTED_WORKSPACE_SCENES` :34) + the TS mirrors **pinned to the
  Python models by `dialectic/tests/test_workspace_contract.py`**, which
  parses this file.
- `hooks/useWorkspaceObjects.ts` — the three-state fetch idiom every new
  hook copies. `stores/appStore.ts` — zustand persist (`partialize` :399:
  auth + current room only); `setRoom` resets per-room state (:201).
- `components/workspace/` — `WorkspaceSceneFrame` (emits
  `data-workspace-scene`, the harness's marker), `SceneSwitcher`,
  `WorkspaceObjectList`, `SceneEmpty` (empty ≠ unavailable ≠ loading),
  `scenes/`. Where Field/Focus/Atlas go.
- `components/chat/MessageBubble.tsx` — renders proposal cards through
  `lib/proposalEnvelope.ts`; TG-F's de-chat target.

### 6.3 Legacy / dead — do not build on these

- `packages/` (React Native: mobile, app, macos, windows) — **frozen**.
  Cannot reach production; WS handshake, room tokens and auth contract are
  all wrong. The PWA is the reach strategy.
- `dialectic/frontend/app.html` and `frontend/index.html` — **retired**
  legacy single-file SPA. The React app under `frontend/app/` is the only
  live frontend.
- `.worktrees/production-stabilization`, `.worktrees/release-1-*`,
  `.worktrees/release-2-*` — completed work, already merged to master. Do
  not develop in them.
- `backup/pre-rebase-2026-08-12` — a backup branch.
- `dialectic/deploy/dialectic.service` — describes an `/opt/dialectic`
  deploy that does not exist on this host. The real unit is
  `/etc/systemd/system/dialectic.service`, WorkingDirectory
  `/root/DwoodAmo/dialectic`. The working tree IS production after a
  restart.

### 6.4 Environment assumptions

- **Production backend runs the git working tree** at
  `/root/DwoodAmo/dialectic` via `dialectic.service` on :8002. **A restart
  deploys whatever is on disk** — never restart with uncommitted edits.
- **Frontend** is a release directory plus a symlink:
  `/var/www/dialectic-releases/<UTC-ts>-<name>` ← `/var/www/dialectic-current`.
  Flip with `ln -sfn`, then `systemctl reload nginx`.
- **nginx proxies ONE hardcoded prefix list** to the backend:
  `auth|rooms|threads|users|health|analytics|graph|replay|stakes|messages|memories|personas|notifications|attachments`.
  **`/api/` is NOT in it.** A request to an unproxied path returns the SPA's
  `index.html` with **HTTP 200**. Check `content-type`, never status. A new
  backend prefix requires editing both nginx AND `vite.config.ts` (the dev
  and preview proxy mirrors the list). Release 3 needs no new prefix: field
  routes live under `/rooms/`, atlas under `/users/`.
- **Cloudflare** fronts the site. `/assets/` is served
  `immutable, max-age=31536000`, so an old bundle can return 200 from the
  edge long after a clean flip. Probe origin with
  `curl --resolve dialectic.somacura.org:443:127.0.0.1` to see the truth.
  The HTML is `no-cache` / `DYNAMIC`, so the entry point turns over
  immediately.
- **Databases** (user is `root`, not `postgres`): `dialectic` (production),
  `dialectic_test` (pytest; some pg tests skip cleanly without it),
  `dialectic_browser` (browser fixture).
- **Browser fixture:** backend on :8013 against `dialectic_browser` with
  `SCHEDULER_ENABLED=0`, frontend via `vite preview` on :4173 built with
  `DIALECTIC_BACKEND_URL=http://localhost:8013`. Fixture account
  `scene@fixture.example.com` / `scene-fixture-pw-123`. **No production
  service is restarted for any of this.**
- **Playwright** is available to `python3` (`from playwright.sync_api
  import sync_playwright`). Pin `timezone_id="America/Chicago"` — headless
  Chromium defaults to UTC and the app's clock is Chicago.
- **Migrations** are numbered under `dialectic/migrations/`; **016 was the
  last applied** (014 `reading_library`, 015 `room_watchlist`, 016
  `voyage_embeddings` — all live in the production DB). The program's first
  new migration is **017** (§1.17). `schema.sql` is the fresh-DB baseline
  but 014's `reading_items` is absent from it — a fresh DB needs baseline +
  migrations, and 017's table must be appended to the baseline in the same
  commit.
- `journalctl --since` parses **local** time; app logs stamp **UTC**.

### 6.5 Invariants that must not break

- The House projection never exceeds the **all-members intersection**. Every
  arm of `_MOVEMENT_SQL` is fenced by the eligible-room array; the fence is
  the entire privacy invariant, and it must hold **in the SQL**, not only in
  the Python that consumes it. (Atlas's per-viewer fence must hold the same
  way — in the SQL.)
- Human House and Dialectic's Home context come from **one service**, so
  they cannot diverge.
- Personal memory grants are personal; they never leak into House — or into
  Atlas.
- Home cannot own a trading thesis; one thesis per ordinary room.
- The Record is never rewritten by interpretation, and is not deleted
  because a higher-order artifact summarizes it. Field marks INTERPRET the
  Record; they never touch it.
- High-consequence state stays **proposal-only and human-ratified**.
  Dialectic prepares the move; a human's tap makes it real. Field inference
  can never write a §14.4 judgment (the vocabulary guard, §5.1).
- Two credentials on every room endpoint: JWT **and** `X-Room-Token`.

### 6.6 Production population inventory (observed 2026-08-13, psql)

Design against these numbers, not hopes: 23 rooms (11 with a single
message) · 296 messages · 5,938 events · 425 memories (real supersession
chains) · 13 readings (+13 twins, 0 orphans) · 5 theses · **0 proposals ·
0 commitments · 0 briefs** · **0 stored `claim_check` keys** · **2**
messages with `references_message_id` · metadata sources: trading_curator
18, night_shift 14, reading_echo 9 · `memory_references` (Echo citations):
**7 rows** · thesis events of any casing: **0**. The R2 lesson stands:
"emptiness is the product's normal state" — every new scene ships a real
population or an empty state that teaches, and the Field's population plan
is the inference job, not wishful metadata.

---

## 7. VERIFICATION

### 7.1 Per-step commands

```bash
# Backend suite (must end in exactly one "N passed", no failed/error line)
cd /root/DwoodAmo/dialectic && python3 -m pytest tests/ -q

# Undefined names in changed files (catches NameErrors no test can reach)
python3 -m ruff check --select F <changed files>
# Whole-tree count must not exceed master's; 80 pre-existing at handoff.

# Frontend
cd /root/DwoodAmo/dialectic/frontend/app
npm ci          # REQUIRED before build after any dependency change
npx vitest run
npm run lint
npm run build   # tsc -b runs here; tests+lint can pass while the build fails
```

**Isolated browser acceptance** — never against production:

```bash
cd /root/DwoodAmo/dialectic
DATABASE_URL='postgresql://localhost/dialectic_browser' \
JWT_SECRET_KEY='browser-scene-kernel-secret-32-bytes-minimum' \
ANTHROPIC_API_KEY='browser-fixture-dummy-key' \
SIGNUPS_ENABLED=1 SCHEDULER_ENABLED=0 PORT=8013 python3 run.py &

cd frontend/app
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run build
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run preview -- --port 4173 --host 127.0.0.1 &
```

Existing harness to copy:
`docs/superpowers/acceptance/2026-08-13-release-1-browser-acceptance.py`
(fresh context per scenario, service workers unregistered + caches cleared
before anything is believed, `timezone_id="America/Chicago"`, real DOM
markers not guessed selectors, nonzero-size before any fit bound). Stop
fixture processes **by PID, after confirming `/proc/<pid>/cwd` is inside
your worktree** — a bare `pkill -f run.py` matches the production service.

### 7.2 Traps that have already cost time here

- **A probe that never reaches the code proves nothing.** The Release 1
  acceptance harness was wrong three times before it was right: guessed
  selectors reported a surface missing while it was on screen; a
  case-sensitive text check failed against CSS-uppercased labels; and Back
  driven by cross-document `goto()` re-boots the app and tests restoration
  instead of history. Before reporting a failure, prove the code ran.
- **Never probe a mutating endpoint to prove it refuses.** On 2026-08-13 a
  `POST /rooms` sent to check reachability **created a room in production**
  (§4.1 is its ghost). Read the route's dependencies instead.
- **A mutation that kills no test is a coverage hole, not a pass.** Every
  guard claimed "mutation-proven" must be shown red with the guard removed
  and green when restored — reverted by targeted edit, **never
  `git checkout`** (that discards the real work alongside the mutation).
- **A layout assertion on a hidden element passes vacuously** — a 0×0 box
  satisfies every `<=` bound. Assert nonzero size first.
- **Measurement is not render.** Take the screenshot and look at it. Three
  of Release 2's five gate defects were found only this way.
- **The PWA service worker serves stale bundles.** Unregister service
  workers and clear caches in every browser context before believing a
  result.
- **A stale `node_modules` fails `tsc -b` and leaves the OLD bundle in
  `dist/`**, so a flip ships a new release name over unchanged code. Run
  `npm ci`, then confirm the built bundle hash differs from the served one.
- **A performance probe right after process start measures warm-up, not
  code.** Let the fixture settle; prefer the second reading.

### 7.3 Release 3 test plan (new files and required edits)

- **`tests/test_field_marks_pg.py`** (template:
  `test_workspace_objects_pg.py`, including its JSONB-codec fixture and
  rollback-transaction workroom). Fixtures: one room with a confirm chain,
  a contest, a correct (with replacement), a split, a merge; a second room
  as the fence. Assert: id uniqueness/stability across two builds; derived
  review for all six actions; **anchor ordering unchanged after inserting a
  review** (the no-reshuffle test); replacement occupies its ancestor's
  ordinal; room fencing by value; `build()` writes nothing (count-snapshot
  across tables + `field_marks`); **the dedup index blocks re-assertion
  after contest AND after correct** — mutation target: remove
  `ON CONFLICT DO NOTHING` from the inference insert and the test must go
  red with `UniqueViolation`, proving the guard lives at the DB, not in
  code; append-only asserted (no UPDATE/DELETE statements in the module's
  SQL, plus a row-content before/after check through a review action).
- **`test_workspace_objects_pg.py` edits:** `_TOUCHED_TABLES` +=
  `"field_marks"`; unit-test `workspace_object_from_field_mark` including
  the provisional→`'none'` mapping (§1.20).
- **`test_workspace_contract.py` edits:** the five `FIELD_*` vocabularies
  join the order-pinned parametrize; `FieldMark`/`FieldReview`/
  `FieldProjection` TS↔Pydantic parity; `WORKSPACE_OBJECT_KINDS` pin now
  includes `field_mark`. (Remember this file's own warning: source-text
  assertions are mutation-checked in both directions.)
- **`tests/test_field_api.py`** (template: the workspace API test's
  auth-statement-matched mocks): 401/403 both-credential matrix; six-action
  happy paths; 409 already-superseded; 409 repeat confirm; 404 foreign
  target; 422 foreign-room replacement subject; the `field_mark_reviewed`
  event lands in the same transaction; a mid-split failure leaves zero rows;
  **the router exposes no write route beyond the one POST**.
- **`tests/test_field_inference.py`** (template: reading_echo's tests;
  provider mocked): invalid relation dropped; foreign-room subject dropped;
  caps honored; **the §14.5 test** — contest a mark, run the job with the
  model returning the identical candidate, assert 0 inserts; the
  no-new-messages gate spends no LLM call; kill switch honored.
- **`tests/test_atlas_pg.py` / `test_atlas_api.py`:** the two-user fence by
  value (§5.4); per-kind caps (insert cap+10 of one kind, others still
  present); every edge's endpoints resolve to real rows; JWT-only auth.
- **TG-C tests:** server-side validation rejects unknown kinds/malformed
  payloads; the full human propose→accept round-trip in pg.
- **Frontend tests:** `useFieldMarks` (copy `useWorkspaceObjects.test`);
  `workspaceRoute` `object`-axis round-trip + `field`/`atlas` scene lists;
  sceneCopy for Field + Atlas empty states; FocusSurface state labels
  present; continuity v1→v2 degradation + reconcile rules.
- **Browser acceptance additions** (extend the R1 harness): Field reachable
  in an ordinary room; empty state teaches; a seeded provisional mark
  renders dashed + labeled "provisional"; confirm flips styling **without
  reordering** (DOM-order assertion before/after); `&object=` deep link
  opens Focus and survives reload; a review action round-trips; Atlas
  renders and navigates; compose→accept proposal round-trip; restoration
  kill-and-reopen to the exact spot; draft survives reload unsent;
  de-chatted room at all five widths; screenshots at every step, looked at.

### 7.4 a11y harness

Vendor `axe.min.js` from the `axe-core` npm package (devDependency);
in the Python harness `page.add_script_tag(path=…)` then evaluate
`axe.run()` per checked surface/width; fail on violations at
`serious`/`critical`, triage the rest in writing. Plus the two explicit
assertions no tool covers: no hover-only action (walk every actionable
element for a non-hover path), no color-only meaning (every state chip's
text label present — §7.3's Focus/Field label tests).

### 7.5 Seed + performance method

§5.7. Numbers recorded at seed scale, warm process, ~100 samples per
endpoint, p95 vs 150 ms, in the gate ledger next to the seed parameters.

### 7.6 Owner device checklist (template — TG-H fills exact URLs)

Per device (macOS Safari/Chrome, Windows Chrome/Edge, iPhone Safari, iPad
Safari, Android Chrome), ~10 minutes: install/open the PWA → sign in → open
a room, switch to Field, select an object into Focus → kill the app →
reopen: lands on the exact object (restoration) → follow a deep link from a
notification or pasted URL: it overrides restoration → type a draft, reload:
draft present, unsent → rotate/resize: no horizontal overflow, drawers
reachable, no hover-required action → grayscale glance (device grayscale
mode or squint test): still reads as Dialectic. Owner reports PASS/FAIL +
notes per line; recorded verbatim.

### 7.7 Definition of done

Release 3 is complete when **all** hold and are recorded with observed
values (owning task group in brackets):

- [ ] Field and Focus render provisional reasoning objects that are
      **visibly provisional and fully sourced**; origin / review /
      deliberative status are three independent dimensions; confirmation
      cannot be read as truth. [TG-A/B]
- [ ] High-consequence state remains proposal-only and human-ratified;
      §14.4 judgments are structurally unwritable by inference. [TG-A]
- [ ] Ordinary updates do not reshuffle the whole Field (DOM-order proof).
      [TG-A/B]
- [ ] Human corrections persist, are attributable, and demonstrably
      suppress re-assertion (the §14.5 test). [TG-A]
- [ ] A human can create a proposal in production UI, and another human's
      acceptance stamps who. [TG-C]
- [ ] Atlas navigates rooms, branches, artifacts, evidence, predictions,
      Echoes, contradictions (labeled proxies), shared sources and
      unresolved work; **every edge backed by real provenance**; the
      list/tree carries the full meaning; **Atlas authorization matches
      source-room authorization** (two-user fixture, by value). [TG-D]
- [ ] Exact restoration covers room, branch, scene, selected object,
      Focus/workbench state, viewport/scroll, open proposal, composer draft
      and reply target; deep links and notifications still override;
      devices and browser profiles stay independent; fallback chain
      object → scene → room → Home → House; stale transient state is
      reconciled, not replayed. [TG-E]
- [ ] Grayscale screens remain recognizable as Dialectic without the
      wordmark; human-only rooms still look like Dialectic. [TG-F]
- [ ] Primary surfaces no longer resemble generic chat (F1 shipped; F2
      status recorded either way). [TG-F]
- [ ] Accessibility: semantic DOM, selectable text, keyboard navigation,
      visible focus, contrast, reduced motion, **no color-only meaning, no
      hover-only action** — tool-verified plus explicit assertions. [TG-F]
- [ ] Proven at large desktop, 1200, **exactly 1024**, tablet and phone
      widths. [TG-F/H]
- [ ] House, Atlas, Field and long-lived room projections are **bounded**,
      with p95 measured at seed scale against the 150 ms target and the
      numbers recorded. [TG-G]
- [ ] Every Release 1 and 2 mutation guard re-proven red-then-green at the
      gate, plus the new Release 3 guards. [TG-H]
- [ ] Fresh backend tests, frontend tests, lint, production build, static
      architecture checks, isolated browser acceptance, a11y checks,
      performance checks and real-device checks (§7.6) all recorded. [TG-H]
- [ ] A release-level `JOURNAL.md` entry with the **observed** backend
      integer and a date derived in `America/Chicago`. [TG-H]
- [ ] Merged to master directly, pushed. **No pull request.** [TG-H]

---

## 8. CONFLICT RULE

**If implementation reality contradicts this plan, the builder flags the
contradiction and stops — no silent improvisation, no quiet re-planning.**

---

## AMENDMENTS

AMENDED 2026-08-13: Owner addressed §4.1 mid-build, verbatim: "b stray room
probe do not create in production you are clear to build it as wwell" —
read as clearance on the (b) open-question item (the stray room) and a green
light to proceed with the full build, because the owner named the room and
the question list directly. The exact disposal action (deleting room
`eeffa8f1-9d5a-4d31-981d-b5cf0a0627e8` from production) will still be
confirmed in one line at the TG-H gate before any production delete — the
wording is ambiguous between "cleared to proceed" and "cleared to delete",
and a production delete needs the unambiguous form.

AMENDED 2026-08-13: Owner relayed the human-interaction surface audit
(`docs/audits/2026-08-13-dialectic-human-interaction-surface-audit.md`, 794
lines, commit 5019e2b — landed on this branch from a parallel session) with
"take this into account with the current build". Disposition, because the
audit's own follow-through in `dialectic/TODOS.md` states that PLAN.md
remains the authority for Release 3: (1) the audit's canonical topology and
authority-loop asks (D12 Make a Move, Focus as universal inspector, Field
review/history, Atlas, restoration, a11y) are what this plan already builds
— no scope change; its P0 "branchless workspace-object taps do nothing" is
closed by §1.18's tap→Focus. (2) The two owner-named "remove immediately"
items (T02 fake Math.random() latency, T04 inert new-case +) were removed
in rider commit e234212 on this branch; they go live at tradingDesk's next
deploy, which is NOT part of Release 3's deploy plan. (3) Everything else
(invitations/verification/recovery delivery, membership/presence/permission
separation, tradingDesk consolidation, A25 URL-fragment token) stays on the
TODOS.md board — post-release work, not silently folded in. Also noted:
three parallel-session commits (f9d125c, 5019e2b, 7d79bd6) now ride this
branch and will reach master at the gate merge.

AMENDED 2026-08-14 (conflict-rule resolution, forced ordering): §5.8 lists
the owner device checklist as step 6, before merge (8) and deploy (9) — but
the checklist's content (§7.6: open the PWA, switch to Field, Focus an
object) cannot execute before the deploy: production carries no Release 3
surface until the flip, and the isolated fixture is loopback-only,
unreachable from any real device. No alternative order exists, so the gate
runs: mechanical verification → ledger → merge → deploy → owner checklist
immediately after, results recorded verbatim as the ledger's final section.
If any device line fails, the fix ships as an immediate follow-up and the
ledger records the failure honestly.
