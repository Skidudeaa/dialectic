# Dialectic Living Workroom Program Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each tranche plan task-by-task. Detailed tranche plans use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved remote-reconciled Dialectic living-workroom design as a sequence of independently shippable changes without regressing the production Home, navigation, proposal, memory, thesis, evidence, or mobile contracts.

**Architecture:** Preserve the current FastAPI/PostgreSQL and React/TypeScript PWA substrate. Introduce one typed workspace-scene kernel, then progressively project the shipped entities—Home movement, readings, research turns, theses, commitments, predictions, proposals, memories, and Record events—into richer House, Bench, Focus, Field, Library, Ledger, Judgment, and Atlas surfaces. Each tranche is planned against the freshly integrated previous tranche so later file-level instructions do not become stale before execution.

**Tech Stack:** PostgreSQL 16/asyncpg, FastAPI/Pydantic, pytest/pytest-asyncio, React 19, TypeScript 5.9, Zustand 5, Vite 7, Vitest 4 using the monorepo's existing trading-frontend pattern, WebSocket collaboration, existing PWA service worker, existing isolated browser-acceptance harness.

## Global Constraints

- Canonical design: `docs/superpowers/specs/2026-08-12-dialectic-front-end-identity-design-v2.md` at commit `e3bb6a4`.
- Planning baseline: repository `master` at `b71fda3`; latest reviewed logic commit `e422f3a`.
- Home Base is shipped substrate: singleton `is_home`, founder-only nondelegable management, generic-join refusal, all-members room intersection, shared human/Dialectic projection, stale-state retention, and Home thesis prohibition remain intact.
- `useRoomNavigation.ts` or its deliberate successor remains the one destination writer. No component-local room, branch, scene, or object routing effects.
- Bare `/` remains Home's root; current room and branch URLs remain valid; Back/Forward and notification entry remain history-correct.
- Exactly 1024 CSS pixels remains desktop until a separately approved responsive-contract change.
- Mobile rails remain reachable through drawers; no feature may become desktop-only.
- Personal memory promotion remains a per-user recall grant. It never becomes shared House or Ledger state and never changes the source memory's shared scope.
- Dialectic prepares proposals; a human makes them real. Existing prediction, thesis, commitment, reading, and resolution proposal acceptance remains explicit, attributable, idempotent, and failure-visible.
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
- Before every completion claim, run fresh verification appropriate to that tranche. Historical test counts are context only.

---

## Program dependency graph

```text
1. Scene Kernel + Identity Shell
        |
        v
2. House v2 Movement
        |
        v
3. Workspace Adapters + Proposal Envelope
        |--------------------|
        v                    v
4. Evidence Surfaces     5. Thesis Bench
        |                    |
        |---------|----------|
                  v
6. Record Repositioning
        |
        v
7. Field + Focus
        |
        v
8. Atlas
        |
        v
9. Exact Local Restoration
        |
        v
10. Final Identity / Accessibility / Performance Gate
```

Tranches 4 and 5 may proceed in parallel only after Tranche 3 lands because both consume the same normalized workspace-object and proposal interfaces. All other tranches are sequential.

---

## Tranche 1: Scene Kernel and Identity Shell

**Detailed plan:** `docs/superpowers/plans/2026-08-12-dialectic-scene-kernel-and-identity-shell.md`

**Purpose:** Create typed scene addressing, preserve current URL semantics, make Home → House and ordinary room → Record explicit, and migrate primary participant-facing labels from Claude to Dialectic without changing provider provenance or backend identifiers.

**Produces:**

- Frontend unit-test harness reusing the monorepo's Vitest pattern.
- Pure route/scene helpers.
- Transient workspace-scene state owned by the existing navigation transaction.
- Explicit House and Record scene frame.
- Stable extension point for later object scenes.
- Central product-identity constants.

**Exit gate:**

- Bare `/` opens Home → House.
- Home → Record has a canonical URL and survives reload/Back/Forward.
- Ordinary room and branch URLs remain unchanged for default Record.
- Existing Home pulse, table, proposal cards, mobile drawers, and room functions remain operational.
- Primary visible participant naming is Dialectic; provider provenance remains intact.
- Frontend unit tests, lint, build, and isolated browser acceptance pass.

---

## Tranche 2: House v2 Movement

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-house-v2.md` against the integrated Tranche 1 head before implementation.

**Purpose:** Extend the shipped membership-fenced Home projection from unread/questions/commitments into semantic house movement without creating a separate dashboard or broader hidden model context.

**Inputs:**

- Scene kernel and House scene.
- Current `HomeActivityService` intersection and 2-second prompt-context boundary.
- Existing Home stale-state behavior.
- Existing scheduler, reading, research, Wire, claim-check, prediction, thesis, and Echo events/metadata.

**Produces:**

- Bounded `HouseMovementItem` projection.
- Movement kinds for reading filed, research completed, claim warning, Wire interruption, prediction review, commitment due, Echo, and thesis lifecycle.
- Exact room/branch/message/object destinations through the same navigation transaction.
- House sections that preserve the shipped place vocabulary: Residents, Needs you, The house, Doors, The table.
- Shared projection parity between Home UI and Dialectic's Home prompt context.

**Exit gate:**

- No House item exceeds the all-members intersection.
- Adding a Home resident contracts the same human and model view immediately.
- Stale snapshot remains visible and marked stale.
- Home projection p95 remains below the existing 150 ms design target at the recorded seed scale.
- Home remains a real conversation and cannot own a thesis.

---

## Tranche 3: Workspace Adapters and Proposal Envelope

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-workspace-adapters.md` against the integrated Tranche 2 head.

**Purpose:** Normalize shipped entities for frontend composition without migrating them into a speculative universal artifact database.

**Produces:**

```ts
interface WorkspaceObject {
  id: string
  kind: 'reading' | 'research_brief' | 'thesis' | 'commitment' | 'prediction' | 'proposal' | 'memory' | 'record_event'
  roomId: string
  threadId: string | null
  title: string
  summary: string
  status: string
  createdAt: string
  updatedAt: string | null
  provenance: WorkspaceProvenance
  relationships: WorkspaceRelationship[]
  availableActions: WorkspaceAction[]
  source: WorkspaceSourceRef
}
```

```ts
interface WorkspaceProposal {
  id: string
  kind: 'prediction_draft' | 'thesis_proposal' | 'thesis_draft' | 'commitment_proposal' | 'reading_draft' | 'prediction_resolution'
  sourceMessageId: string
  status: 'proposed' | 'accepted' | 'dismissed' | 'superseded' | 'expired' | 'failed'
  target: WorkspaceTargetRef
  rationale: string | null
  acceptedByUserId: string | null
  payload: Record<string, unknown>
}
```

Adapters consume current tables and message metadata; they do not create a new artifact schema.

**Exit gate:**

- Every current proposal type renders through one shared lifecycle grammar.
- Accepted proposals remain inspectable and duplicate action stays disarmed.
- Reading/memory twins deduplicate into one visible object.
- Existing REST and WebSocket contracts remain backward compatible.

---

## Tranche 4: Evidence Surfaces

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-evidence-surfaces.md` after Tranche 3.

**Purpose:** Promote the reading/research stack out of Record-only cards into reusable Library, Brief, Evidence Review, Claim Check, Judgment, and Echo scenes.

**Produces:**

- Library scene backed by `reading_items`.
- Reading Focus showing source, retrieval, thesis impact, use, lineage, and discussion state.
- Research Brief projection over durable `metadata.source='deep_dive'` messages.
- Claim Check provenance scene with explicit unavailable state.
- Prediction Judgment scene preserving human-only resolution.
- Echo Focus showing origin room, target room, relevance explanation, and citation lineage.

**Exit gate:**

- A filed reading reveals where it matters within two actions.
- Thin/bot-blocked content never appears as evidence.
- Research failure never presents a partial synthesis as complete.
- Claim Check silence never implies success.
- Echo never duplicates or silently promotes the source.

---

## Tranche 5: Thesis Bench

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-thesis-bench.md` after Tranche 3.

**Purpose:** Recompose the current Trading panel lifecycle into the mature reference Bench while preserving the deep tradingDesk Builder.

**Produces:**

- Clear separation of authored model, live state, evidence, and human judgment.
- Empty/unbound, drafting, review, live, stale, retirement, and successor states in one lifecycle surface.
- Attached readings, research, predictions, commitments, and proposal provenance.
- Existing Builder handoff retained for deep DAG editing.

**Exit gate:**

- Create/draft/accept/immediate-first-cycle/retire/successor flow still passes.
- Home thesis guards still return 409 with no side effects.
- Model draft never presents runtime facts as verified.
- Trading door remains reachable in an unbound ordinary room.

---

## Tranche 6: Record Repositioning

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-record-repositioning.md` after Tranches 4 and 5 integrate.

**Purpose:** Preserve exact chronological history while removing transcript-first layout from ordinary rooms.

**Produces:**

- Record as an explicit scene.
- Compact source-event excerpts inside Bench, Focus, Library, and Judgment scenes.
- Bidirectional object ↔ source-message navigation.
- Current message editing, deletion, reply, search, attachments, reactions, streaming, and proposal metadata retained.

**Exit gate:**

- No history or provenance is lost.
- Search jumps still land on exact messages and branches.
- Streaming and follow-the-tail behavior remains correct.
- Ordinary-room default scene is no longer a conventional chat feed once a meaningful active artifact exists; rooms without one retain a useful Record fallback.

---

## Tranche 7: Field and Focus

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-field-focus.md` after Record repositioning.

**Purpose:** Add visible, provisional deliberation structure around proven workspace objects without letting inference silently create authority.

**Produces:**

- Typed reasoning objects and relations only where current sources support them.
- Origin, review, and deliberative-status dimensions.
- Provisional grouping, challenge/support, definition conflict, tension, question, and synthesis candidates.
- Human confirmation, contesting, correction, supersession, split, and merge-of-inference actions.
- Focus transformation around selected objects.

**Exit gate:**

- Every inferred object links to source events.
- Confirmation cannot be confused with truth.
- High-consequence state remains proposal-only and human-ratified.
- Ordinary updates do not reshuffle the full Field.

---

## Tranche 8: Atlas

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-atlas.md` after Field/Focus.

**Purpose:** Connect rooms, branches, artifacts, evidence, predictions, Echoes, and unresolved work through real provenance rather than a decorative graph.

**Produces:**

- House-wide navigable relationships.
- Stable object and branch identity.
- Bounded views for dependencies, contradictions, shared sources, stale checks, and cross-room citations.
- Accessibility-first semantic list/tree fallback for every spatial view.

**Exit gate:**

- Atlas edges are backed by real source relationships.
- Membership fencing remains identical to source-room authorization.
- No freeform user-positioned graph or force-directed chaos.
- Phone users retain equivalent navigation and meaning.

---

## Tranche 9: Exact Device-Local Restoration

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-exact-local-restoration.md` after all target scenes have stable addresses.

**Purpose:** Restore exact local continuity across macOS, Windows, iOS/iPadOS, and Android without cross-device takeover.

**Produces:**

- Per-installation and, where stable identity exists, per-window restoration key.
- Room, branch, scene, selected object, Focus/workbench state, viewport/scroll, open proposal, composer draft, and reply-target restoration.
- Explicit reconciliation of stale transient state.
- Safe fallback chain: object → scene → room → Home → House.

**Exit gate:**

- Deliberate bare launch enters Home → House.
- OS/browser/PWA process reconstruction restores the exact prior local scene.
- Notification/deep link overrides restoration.
- Devices remain independent.
- Revoked or deleted targets fail closed and explain the fallback.

---

## Tranche 10: Final Identity, Accessibility, and Performance Gate

**Detailed-plan generation gate:** Write `docs/superpowers/plans/2026-08-12-dialectic-final-acceptance.md` after Tranche 9.

**Purpose:** Prove the product is recognizably Dialectic, fully reachable, and operationally honest across every supported platform.

**Exit gate:**

- Grayscale screens remain recognizable without the wordmark.
- Human-only rooms still look like Dialectic.
- Primary surfaces no longer use chat bubbles, left/right alignment, purple AI branding, decorative gradients, or provider names as product identity.
- Semantic DOM, keyboard navigation, visible focus, contrast, reduced motion, and no-color-only meaning pass.
- macOS, Windows, iPhone/iPad, and Android device acceptance passes for launch, restoration, notification entry, keyboard behavior, branch/object navigation, and offline/stale rendering.
- Home and long-lived room projections remain bounded and performant.
- Fresh backend tests, frontend tests, lint, production build, browser acceptance, and device checks are recorded before completion.

---

## Planning rule for subsequent tranches

After each tranche integrates:

1. Read `JOURNAL.md`, root and subtree `CLAUDE.md`, the v2 design, the prior tranche plan, and the latest handoff.
2. Compare the prior plan baseline to current `master`.
3. Trace actual call sites and tests for the next subsystem.
4. Write the next detailed plan using exact current paths, signatures, test code, commands, and commit boundaries.
5. Self-review for spec coverage, placeholders, and type consistency.
6. Execute only after the next plan is reviewed.

This rule is deliberate. Writing all late-tranche file-level instructions against today's component tree would manufacture stale certainty and cause the implementation to fight its own earlier work.
