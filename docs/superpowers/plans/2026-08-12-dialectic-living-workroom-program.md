# Dialectic Living Workroom — Compressed Implementation Program

> **For agentic workers:** Implement this program as three substantial releases. Each release may contain many task-scoped commits and reviews, but it has one branch, one integration gate, and at most one pull request. Do not recreate the former ten-tranche sequence under different names.

**Goal:** Deliver the approved remote-reconciled living-workroom design in three coherent releases without regressing the production Home, navigation, proposal, memory, thesis, evidence, or mobile contracts.

**Architecture:** Preserve the current FastAPI/PostgreSQL and React/TypeScript PWA substrate. First establish the common workroom foundation and house-wide object language. Then move the existing evidence and thesis systems into first-class artifact surfaces while demoting conversation to the Record. Finally add provisional deliberation structure, the Atlas, exact local restoration, and the full identity/accessibility/performance gate.

**Tech Stack:** PostgreSQL 16/asyncpg, FastAPI/Pydantic, pytest/pytest-asyncio, React 19, TypeScript 5.9, Zustand 5, Vite 7, Vitest 4 using the monorepo's existing trading-frontend pattern, WebSocket collaboration, the existing PWA service worker, and the isolated browser-acceptance harness.

## Why this replaces the ten-tranche program

The prior roadmap over-separated foundations that must be designed and integrated together:

- Scene routing, House movement, and workspace adapters all define the same navigation and object contract.
- Evidence surfaces, Thesis Bench, and Record repositioning all define the artifact-centered room.
- Field, Focus, Atlas, restoration, and final identity acceptance all depend on the completed scene and object model.

Splitting those into ten merge gates would create planning churn, integration drift, and repeated browser/device verification without buying meaningful risk isolation.

The new rule is:

> **Three releases. Task-level commits and reviews inside them. No intermediate merge merely because one internal subsystem is green.**

## Global constraints

- Canonical design: `docs/superpowers/specs/2026-08-12-dialectic-front-end-identity-design-v2.md` at commit `e3bb6a4`.
- Home Base is shipped substrate: singleton `is_home`, founder-only nondelegable management, generic-join refusal, all-members room intersection, shared human/Dialectic projection, stale-state retention, and Home thesis prohibition remain intact.
- `useRoomNavigation.ts` or its deliberate successor remains the one destination writer. No component-local room, branch, scene, or object routing effects.
- Bare `/` remains Home's root. Existing room and branch URLs remain valid. Back/Forward, search jumps, and notification entry remain history-correct.
- Exactly 1024 CSS pixels remains desktop until a separately approved responsive-contract change.
- Mobile rails remain reachable through drawers or an equivalently verified replacement. No feature may become desktop-only.
- Personal memory promotion remains a per-user recall grant. It never becomes shared House or Ledger state and never changes the source memory's shared scope.
- Dialectic prepares proposals; a human makes them real. Existing prediction, thesis, commitment, reading, and resolution acceptance remains explicit, attributable, idempotent, and failure-visible.
- Home cannot own or bind a trading thesis. Scheme artifacts remain in their scheme rooms.
- The thesis create, draft, immediate adoption, live state, Builder handoff, retirement, unbinding, and successor lifecycle remains functional throughout recomposition.
- The reading and its memory twin remain one conceptual object; the UI must not duplicate them.
- Automated reading paths continue to share `reading.is_thin()` as the one evidence-quality gate.
- Claim Check remains low-noise: only material warnings interrupt normal flow; unavailable checks never masquerade as support.
- Wire caps, quiet hours, and room interjection settings remain enforced.
- Prediction resolution remains a human judgment.
- Echo remains a visible cross-room citation, never a silent copy or personal promotion.
- Provider/model identifiers remain available in technical provenance. Primary product controls and participant labels use Dialectic.
- No framework rewrite, universal artifact database, CRDT editor, native app, order-placement capability, or freeform graph engine is introduced by this program.
- Both production services run their git working trees. No service restart, migration, or frontend release is part of ordinary implementation without an explicit production instruction.
- Before every release completion claim, run fresh backend, frontend, browser, architecture, accessibility, and applicable device verification. Historical counts are context only.

---

## Dependency graph

```text
RELEASE 1
Workroom Foundation
scene + identity + House movement + workspace objects/proposals
        |
        v
RELEASE 2
Artifact Workroom
Library/Brief/Judgment/Echo + Thesis Bench + Record repositioning
        |
        v
RELEASE 3
Deliberation and Whole-House Intelligence
Field/Focus + Atlas + exact local restoration + final acceptance
```

There are no independent sub-release merge gates. A task can be reviewed and committed without becoming its own branch or pull request.

---

## Release 1 — Workroom Foundation

**One branch, one pull request.**

### Scope

Release 1 combines the former Scene Kernel, House v2, and Workspace Adapter/Proposal work.

It establishes:

1. **Typed scene and destination kernel**
   - Home root defaults to `house`.
   - Conversation is an explicit `record` scene.
   - Existing room and branch URLs remain canonical.
   - Approved future scene names may exist in types but may not expose dead UI.
   - One navigation transaction owns room, branch, scene, and later object destinations.

2. **Product identity shell**
   - Primary visible participant is Dialectic.
   - `@Dialectic` is the primary summon.
   - `@Claude` and `@llm` remain compatibility aliases.
   - Backend speaker enums, stored messages, provider/model provenance, metadata keys, and CSS compatibility names remain unchanged.

3. **House v2 semantic movement**
   - Extend the shipped Home projection beyond unread/questions/commitments.
   - Add bounded movement for readings, research completion, claim warnings, Wire interruptions, prediction review, commitment due, Echo, and thesis lifecycle.
   - Every item carries an exact source destination and remains inside the all-members intersection.
   - Human House and Dialectic's Home prompt context continue to derive from the same projection.
   - Stale authorized snapshots remain visible and marked stale.

4. **Common workspace-object adapters**
   - Normalize existing readings, research turns, theses, commitments, predictions, memories, proposals, and Record events for frontend composition.
   - Do not create a universal artifact database.
   - Deduplicate each reading and its memory twin into one visible object.

5. **Unified proposal envelope**
   - Normalize prediction drafts, thesis proposals and drafts, commitment proposals, reading drafts, and prediction resolutions.
   - Preserve current metadata and relay contracts during migration.
   - Accepted proposals remain inspectable and duplicate actions remain disarmed.

6. **Current-scene local continuity foundation**
   - Persist device-local room, branch, and scene state for the scenes implemented in this release.
   - Deep links and notifications override local restoration.
   - Full object/workbench/viewport/composer restoration is completed in Release 3 after addresses stabilize.

### Existing detailed material

The following remains useful as **Task Group A inside Release 1**, not as an independent release or PR:

- `docs/superpowers/plans/2026-08-12-dialectic-scene-kernel-and-identity-shell.md`
- `docs/superpowers/plans/2026-08-12-dialectic-scene-kernel-and-identity-shell-amendment-1.md`
- `docs/superpowers/plans/2026-08-12-dialectic-scene-kernel-and-identity-shell-amendment-2.md`

Its instruction to stop, hand off, or open a PR after the scene kernel is superseded. Scene-kernel verification remains mandatory, then the same branch continues through House movement and workspace adapters before the Release 1 gate.

### Exit gate

- Bare `/` opens Home → House.
- Home → Record has a canonical URL and survives reload and Back/Forward.
- Ordinary room and branch default URLs remain unchanged.
- House movement never exceeds the all-members intersection.
- The human House and Dialectic Home context remain projection-identical.
- Current proposal types share one visible authority grammar without breaking their existing write paths.
- Reading/memory twins render once.
- Home pulse/table, messages, Research, proposals, attachments, search, protocols, stakes, thesis lifecycle, drawers, and exactly-1024 desktop behavior remain operational.
- Home projection remains within the existing 150 ms p95 design target at the recorded seed scale.
- Full backend tests, frontend tests, lint, production build, static architecture checks, and isolated browser acceptance pass before the single Release 1 PR is opened.

---

## Release 2 — Artifact Workroom

**One branch, one pull request.**

### Scope

Release 2 combines the former Evidence Surfaces, Thesis Bench, and Record Repositioning work.

It delivers:

1. **Library and evidence surfaces**
   - Library backed by `reading_items`.
   - Reading Focus with source, retrieval, thesis impact, use, lineage, and discussion.
   - Claim Check provenance with explicit unavailable state.
   - Echo Focus preserving origin room, target room, relevance, and citation lineage.

2. **Research Brief**
   - Project durable `metadata.source='deep_dive'` messages into reusable Brief objects.
   - Preserve the initiating question, source trace, disagreement, findings, implications, and proposal targets.
   - Do not add a new storage table unless the adapter proves insufficient.

3. **Judgment and commitments**
   - Dedicated prediction/commitment surfaces.
   - Evidence pack and human-only resolution.
   - Preserve correct/incorrect/partial/voided or equivalent existing semantics.

4. **Thesis Bench**
   - Separate authored causal model, live state, evidence, and human judgment.
   - Preserve unbound, drafting, review, live, stale, retirement, and successor states.
   - Keep tradingDesk Builder as the deep DAG surface.
   - Attach relevant readings, research, predictions, commitments, and proposal provenance.

5. **Record repositioning**
   - Record remains exact, searchable, editable where currently permitted, and fully attributable.
   - Artifact scenes become the primary room surfaces when meaningful work exists.
   - Compact source excerpts and bidirectional object ↔ message navigation replace the need to keep the transcript permanently central.
   - Rooms without a meaningful active artifact retain a useful Record fallback.

6. **Release-2 restoration extension**
   - Device-local scene restoration extends to Library, Brief, Judgment, Thesis Bench, selected artifact, and source message.

### Exit gate

- A reading reveals where it matters within two actions.
- Thin or bot-blocked content never appears as filed evidence.
- Research failure never presents a partial synthesis as complete.
- Claim Check silence never implies success.
- Echo never duplicates or silently promotes the source.
- Thesis create/draft/accept/immediate-first-cycle/retire/successor remains functional.
- Home thesis guards remain side-effect-free.
- Search jumps, replies, attachments, reactions, streaming, proposal acceptance, and message history remain correct.
- Ordinary rooms with active artifacts no longer read as conventional chat applications.
- Full backend/frontend/browser verification passes before the single Release 2 PR.

---

## Release 3 — Deliberation and Whole-House Intelligence

**One branch, one pull request.**

### Scope

Release 3 combines Field, Focus, Atlas, exact restoration, and final product acceptance.

It delivers:

1. **Field and Focus**
   - Provisional reasoning objects and relations grounded in actual source events.
   - Origin, review, and deliberative-status dimensions remain distinct.
   - Support/challenge, definition conflict, tension, question, position, and synthesis candidates.
   - Human confirmation, contesting, correction, supersession, split, and merge-of-inference actions.
   - High-consequence state remains proposal-only and human-ratified.
   - Ordinary updates do not reshuffle the whole Field.

2. **Atlas**
   - House-wide navigation across rooms, branches, artifacts, evidence, predictions, Echoes, contradictions, shared sources, and unresolved work.
   - Every edge is backed by real provenance.
   - Semantic list/tree fallback carries the same meaning as spatial views.
   - No force-directed or freeform graph chaos.

3. **Exact device-local restoration**
   - Restore room, branch, scene, selected object, Focus/workbench state, viewport/scroll, open proposal, composer draft, and reply target.
   - Notification and deep-link destinations override restoration.
   - Devices and browser profiles remain independent.
   - Fallback chain: object → scene → room → Home → House.
   - Stale transient state is reconciled rather than replayed blindly.

4. **Final identity, accessibility, and performance pass**
   - Remove chat bubbles and left/right alignment from primary work surfaces.
   - Preserve semantic DOM, selectable text, keyboard navigation, visible focus, contrast, reduced motion, no-color-only meaning, and no hover-only action.
   - Prove the interface at large desktop, 1200, exactly 1024, tablet, and phone widths.
   - Run representative macOS, Windows, iPhone/iPad, and Android acceptance.
   - Bound House, Atlas, Field, and long-lived room projections.

### Exit gate

- Grayscale screens remain recognizable as Dialectic without the wordmark.
- Human-only rooms still look like Dialectic.
- Provisional inference is visibly provisional and fully sourced.
- Confirmation cannot be confused with truth.
- Atlas authorization matches source-room authorization.
- Exact local restoration works across supported platforms without cross-device takeover.
- Primary surfaces no longer resemble generic chat.
- Fresh backend tests, frontend tests, lint, production build, isolated browser acceptance, accessibility checks, performance checks, and real-device checks are recorded before the single Release 3 PR is considered complete.

---

## Planning and execution rule

For each release:

1. Read `JOURNAL.md`, root and subtree `CLAUDE.md`, the v2 design, this program, and the latest handoff.
2. Compare the prior release baseline to current `master`.
3. Write or revise **one detailed implementation plan for the whole release**.
4. Divide that plan into task-scoped TDD commits and fresh implementer/reviewer loops.
5. Do not open intermediate PRs for internal task groups.
6. Run the release-wide integrated gate once all task groups are complete.
7. Open at most one PR for the release.

The three-release boundary is binding. Any proposal to split one release into separate merge tranches requires explicit owner approval.