# Release 1 — Workroom Foundation: Consolidated Implementation Plan

**Status:** Executable plan
**Date:** 2026-08-12 (America/Chicago)
**Authority:** `docs/superpowers/plans/2026-08-12-dialectic-living-workroom-program.md` (compressed three-release revision)
**Canonical design:** `docs/superpowers/specs/2026-08-12-dialectic-front-end-identity-design-v2.md`
**Execution target:** GitHub issue #1 — "Codex execution: Release 1 — Workroom Foundation"
**Branch:** `codex/scene-kernel-identity-shell` (one branch, one gate, at most one PR)
**Worktree:** `.worktrees/release-1-workroom-foundation` — the production checkout at `/root/DwoodAmo` is never used for the browser fixture (Amendment 2 §5)

> **This is the single plan for the whole release.** Task groups A–E are committed and
> reviewed separately, but they are not branches, not merge gates, and not PRs. No PR
> opens until the integrated Release 1 gate in Task Group F passes.

---

## Baseline reconnaissance (observed, not assumed)

Everything below was verified against `c796fd4` before this plan was written. It is
recorded because two of these facts change what the exit gate can honestly claim.

| Fact | Observed | Consequence for this plan |
|---|---|---|
| Frontend test harness | **Does not exist.** No `vitest`, no `test` script, 0 `*.test.*` files under `src/` | "Frontend tests pass" in the gate means the harness A1 creates. There is no prior green to regress from. |
| `useRoomNavigation.ts` | 312 lines. `destinationFromLocation(location) → {roomId, threadId}`; `destinationUrl(room, thread)` | Scene is a **third** destination axis added to both functions. These two are the only place URL grammar may be written. |
| Home projection | `api/home.py:169 get_home_activity` | House v2 extends this one function. It already carries the membership intersection; B must not fork a second projection path. |
| Proposal rendering | `MessageBubble.tsx` reads `metadata.claim_check` (205), `metadata.reading_proposal` (235), `metadata.resolution_proposal` (252) | The envelope in D normalizes **over** these keys. The stored metadata contract does not change in Release 1. |
| Backend suite | 1067 passing at `c796fd4` | Historical context only. Every completion claim re-runs it (program §Global constraints). |
| Embedding/model substrate | `voyage-4-large` 1024-dim; Sonnet 5 pins; Haiku retired | Untouched by this release. Do not re-open. |

**Two honesty constraints follow from the table:**

1. The gate may not say "frontend tests still pass" — it says "the frontend suite
   introduced in A1 passes with N tests." There is no baseline.
2. Any claim about Home projection performance must be measured, not inherited. The
   150 ms p95 target was recorded at a seed scale that B changes by adding item kinds.

---

## Inherited constraints (binding, from the program)

These are not restated in full; they are enforced per task and re-checked at the gate.

- `useRoomNavigation.ts` or its deliberate successor is the **one** destination writer.
  No component-local room/branch/scene routing effects.
- Bare `/` remains Home's root. Existing room and branch URLs remain valid.
  Back/Forward, search jumps, and notification entry remain history-correct.
- Exactly **1024 CSS pixels** remains desktop.
- Mobile rails stay reachable through drawers. No feature becomes desktop-only.
- Home Base substrate is untouchable: singleton `is_home`, founder-only nondelegable
  management, generic-join refusal, all-members intersection, Home thesis prohibition.
- Personal memory promotion never becomes shared House state.
- Dialectic proposes; a human makes it real. Acceptance stays explicit, attributable,
  idempotent, failure-visible, duplicate-disarming.
- A reading and its memory twin are **one** object; the UI must never show two.
- Backend speaker enums, stored messages, metadata keys, provider/model provenance,
  and CSS compatibility class names are **unchanged** by the identity shell.
- No service restart, migration, or frontend release without an explicit production
  instruction. Both services run their working trees.

---

## Task group map

```text
A  Scene and identity kernel        (detailed plan already exists — see below)
B  House v2 semantic movement       (extends api/home.py get_home_activity)
C  Workspace-object adapters        (WorkspaceObject projection, spec §8.1)
D  Unified proposal envelope        (ProposalEnvelope, spec §8.3–8.4)
E  Current-scene local continuity   (device-local House/Record restoration)
F  Integrated Release 1 gate        (one gate, then one PR)
```

Dependency: **A → (B ∥ C) → D → E → F.** C and D share the adapter surface, so D lands
after C. E lands last because it persists the scene addresses A and B stabilize.

---

## Task Group A — Scene and identity kernel

**Detail lives in the existing plan; it is not duplicated here.**

- `docs/superpowers/plans/2026-08-12-dialectic-scene-kernel-and-identity-shell.md`
  (Tasks 1–7)
- Amendment 1 — Task 7 pass-count derived from fresh pytest output
- Amendment 2 — jsdom `scrollIntoView` shim, active-scene no-duplicate-history,
  render-node placement after the null guard, mention regex with left boundary,
  isolated-worktree browser commands, external-model boundary, `set -o pipefail`
- Amendment 3 — reclassification to Task Group A

**Executed with these replacements:**

1. Task 7 **does not** open a PR, **does not** claim Release 1 complete, and **does not**
   write the former `NEXT: House v2 detailed plan` handoff (Amendment 3).
2. Task 7's focused verification is recorded in the SDD ledger and task report only.
   The release-level `JOURNAL.md` entry and full backend pass count are written once,
   in F.
3. Execution continues directly into Task Group B on the same branch.

**A's own definition of done:** bare `/` opens Home → House; Home → Record has a
canonical URL surviving reload and Back/Forward; ordinary room/branch URLs unchanged;
`@Dialectic` primary with `@Claude`/`@llm` accepted; `email@dialectic.example` does not
summon; frontend harness green; scene-kernel browser checks pass at desktop/tablet/phone.

---

## Task Group B — House v2 semantic movement

**Extends** `api/home.py::get_home_activity` — the shipped, membership-fenced projection.
It is extended, never forked (spec §5.3: human House and Dialectic's Home context must
derive from the same projection).

### B1 — Movement kind taxonomy (RED → GREEN)

Add the eight kinds from spec §8.5 to the existing projection:

```text
reading_filed          research_completed     claim_warning      wire_interruption
prediction_review      commitment_due         echo_created       thesis_lifecycle
```

Each item carries: origin room, origin branch/object, movement kind, human relevance,
required judgment, current state, **exact destination**.

- **RED:** a test asserting each kind appears for a seeded source row, and that an item
  from a room the user is not a member of is **absent**.
- **GREEN:** minimal SQL/CTE extension of the existing projection.
- **Guard test (mandatory):** the intersection test must fail if the membership fence is
  removed. Mutation-check it — delete the fence, observe RED, restore.

### B2 — Destination correctness

Every movement item's destination must resolve through the A-kernel grammar
(`room`, `thread`, `scene`) and land on the object it names.

- **RED:** for each kind, assert the emitted destination parses via
  `destinationFromLocation` and names the originating room/branch.
- Items whose target no longer exists (deleted branch, retired thesis) resolve to the
  nearest live ancestor, never to a dead URL.

### B3 — Parity and staleness

- **RED:** one test asserting the human House payload and the Dialectic Home prompt
  layer derive from the same projection call — not two queries that happen to agree.
- Stale authorized snapshots remain **visible and marked stale** (spec §10.5). A failed
  refresh must not blank the House.

### B4 — Bound the projection

- Measure p95 at the recorded seed scale **after** the new kinds land. Record the
  observed number. If it exceeds the 150 ms design target, bound the item set (per-kind
  caps, recency window) rather than dropping the fence or the parity.
- **This measurement is mandatory and may not be inherited from the Home Base run.**

---

## Task Group C — Workspace-object adapters

Implements spec §8.1. **Adapter-first: no universal artifact table, no new storage.**

### C1 — `WorkspaceObject` contract

One TypeScript type plus one backend projection shape:

```text
id · kind · room_id · branch_id? · title · summary · status
created_at · updated_at · provenance · relationships
available_actions · review_state · source_entity · source_event
```

### C2 — Per-entity adapters

```text
reading_items                → Reading
messages[source=deep_dive]   → Research Brief   (projection only, spec §8.2 — no table)
trading book + snapshot      → Thesis
commitment / prediction      → Commitment
message metadata proposal    → Proposal         (handed to D)
memory                       → Dossier entry
Home activity item           → House movement   (from B)
message + event history      → Record event
```

### C3 — The twin rule (mandatory guard)

A reading and its `reading:<domain>-<slug>` memory twin **must project to exactly one
object**. This is the single most likely regression in C: the two rows are real and
independent, and naive adapters will emit both.

- **RED:** seed a reading plus its twin; assert the adapter returns **one** object
  carrying both `source_entity` references.
- **Mutation check:** remove the dedup, observe the count go to 2, restore.

Production currently holds 9 readings with 9 twins — a 1:1 pairing that makes this
failure invisible to eyeball checks and visible only to the count assertion.

### C4 — Read-only in Release 1

Adapters project. They do not write, and they do not change any entity's lifecycle.
`available_actions` describes what a surface *may* offer; it does not perform anything.

---

## Task Group D — Unified proposal envelope

Implements spec §8.3–8.4 **over** existing message metadata. The stored contract does
not change in Release 1; relay endpoints are untouched.

### D1 — Envelope contract

```text
id or stable source coordinate · proposal_kind · source_message_id · room_id
branch_id · created_by · created_at · rationale · payload · status
accepted_by · accepted_at · target_object · available_actions
```

Normalized kinds: `prediction_draft`, `thesis_proposal`, `thesis_draft`,
`commitment_proposal`, `reading_draft`, `prediction_resolution`.

### D2 — Status lifecycle

```text
proposed → accepted | rejected/dismissed | superseded | expired | failed
```

- `expired` = target no longer actionable. `failed` = a human-authorized write did not
  complete. **`failed` must be visible** — spec §5.1 and the program both require
  failure-visible acceptance. A swallowed write is the defect this status exists to expose.
- **Accepted proposals remain inspectable.** They do not vanish (spec §8.4).

### D3 — Duplicate disarming

- **RED:** accept twice; the second action is a conflict, not a second write. Assert the
  relay's existing idempotency still holds *through* the envelope.
- The envelope must not become a second write path. It reads state and routes the human's
  action to the existing relay.

### D4 — Migration safety

- **RED:** a message carrying today's raw `metadata.reading_proposal` /
  `resolution_proposal` / `claim_check` still renders correctly through the envelope.
  Old and new shapes coexist; nothing in the DB is rewritten.

---

## Task Group E — Current-scene local continuity

Device-local persistence for the scenes A and B stabilize. **Full object/workbench/
viewport/composer restoration is Release 3** and is explicitly out of scope here.

### E1 — Persist room + branch + scene

Per device and browser profile. Never server-side; never cross-device.

### E2 — Override precedence (mandatory RED tests)

```text
deep link / notification  >  local restoration  >  Home → House fallback
```

- **RED:** a notification-entry URL wins over stored local state.
- **RED:** an explicit `?room=&thread=` URL wins over stored local state.
- **RED:** bare `/` with stored state restores that state; bare `/` with none opens
  Home → House.

### E3 — Fallback chain

`scene → room → Home → House`. A stored scene naming a room the user has since lost
access to falls back cleanly and does **not** leak the room's existence.

---

## Task Group F — Integrated Release 1 gate

Runs once, after A–E. **No PR before this passes.**

### F1 — Fresh verification (no inherited counts)

From the worktree root:

```bash
cd "$WORKTREE_ROOT/dialectic"
set -o pipefail
python3 -m pytest tests/ -q | tee /tmp/dialectic-release1-pytest.txt
cd frontend/app
npm test
npm run lint
npm run build
```

All must exit 0. The backend file must contain exactly one final `N passed` summary and
no `failed`/`error`/interrupted summary.

### F2 — Exit-gate checklist (program §Release 1 exit gate)

- [ ] Bare `/` opens Home → House
- [ ] Home → Record has a canonical URL surviving reload and Back/Forward
- [ ] Ordinary room and branch default URLs unchanged
- [ ] House movement never exceeds the all-members intersection *(mutation-proven)*
- [ ] Human House and Dialectic Home context are projection-identical
- [ ] Proposal types share one authority grammar without breaking existing write paths
- [ ] Reading/memory twins render once *(mutation-proven)*
- [ ] Home pulse/table, messages, Research, proposals, attachments, search, protocols,
      stakes, thesis lifecycle, drawers, and exactly-1024 desktop behavior operational
- [ ] Home projection p95 **measured** at seed scale against the 150 ms target
- [ ] Backend, frontend, lint, build, static architecture, isolated browser acceptance

### F3 — Browser acceptance (isolated, Amendment 2 §5)

Isolated DB `dialectic_browser`, backend port 8013, preview 4173, `SCHEDULER_ENABLED=0`.
Never `/root/DwoodAmo`. No production service restarted. Widths: large desktop, 1200,
exactly 1024, tablet, phone.

### F4 — Journal and handoff

Append one release-level entry with the **observed** backend integer and a date derived
in `America/Chicago` (Amendments 1 + 2 §8). Then the only authorized handoff:

```text
CHANGES: Scene/identity, House movement, workspace adapters/proposals, and current-scene continuity
VERIFIED: Full Release 1 backend/frontend/static/browser gate with observed results
UNVERIFIED: Real-device macOS/Windows/iOS/Android checks not performed
NEXT: Release 2 — Artifact Workroom
```

### F5 — One PR

Opened only after F1–F4. One PR for the whole release.

---

## Process rules (issue #1)

- Fresh implementer per task group; task-scoped spec and code-quality review after each.
- TDD everywhere: **observed** RED, minimal implementation, **observed** GREEN. A test
  that was never seen failing is not evidence.
- Every guard listed as "mutation-proven" above must be shown to go red when the guard is
  removed, and green when restored — reverted by targeted edit, never `git checkout`.
- Task commits allowed. Intermediate branches and PRs are not.
- One broad whole-release review before F5.

## Out of scope for Release 1

Library/Brief/Judgment/Echo surfaces, Thesis Bench, Record repositioning, artifact↔source
navigation (Release 2). Field, Focus, Atlas, exact restoration, final identity/a11y/
performance/device acceptance (Release 3). No framework rewrite, universal artifact
database, CRDT editor, native app, order placement, or freeform graph engine.
