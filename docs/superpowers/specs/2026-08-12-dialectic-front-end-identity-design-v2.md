# Dialectic Front-End Identity and Living Workroom — Remote-Reconciled Design v2

**Status:** Approved direction; canonical design after remote reconciliation; awaiting v2 review  
**Date:** 2026-08-12 (America/Chicago)  
**Repository baseline:** `Skidudeaa/dialectic@4629ec4`  
**Latest logic commit at reconciliation:** `e422f3a`  
**Product:** Dialectic  
**Origin imprint:** DwoodAmo  
**Supersedes:** `2026-08-12-dialectic-front-end-identity-design.md` wherever the two disagree

The original specification remains in the repository as the record of the design conversation. This v2 is the implementation-grounded successor. It preserves the approved identity and product direction while promoting the newly shipped Home Base, personal-memory, thesis-lifecycle, proposal, and evidence systems from future concepts into non-negotiable substrate.

This document is a product and interaction design. It is not an implementation plan.

---

## 1. Executive decision

Dialectic will not be reskinned as a more attractive chat application. It will be recomposed as a **living construction workroom** where two humans and Dialectic build durable work, inspect the reasoning around it, and continuously incorporate relevant evidence from the outside world.

The product has two equal spines:

```text
ARTIFACT SPINE
What the room is building

DELIBERATION SPINE
Why it is being built that way
```

Conversation remains authoritative coordination and history, but it is no longer the product’s only or default organizing metaphor. It becomes **the Record**: exact, searchable, attributable, and always available, without remaining the gravitational center of every screen.

The shipped Library, Night Shift, claim checking, The Wire, Research mode, prediction resolution, and Echo capabilities form one evidence metabolism:

```text
Observe
→ retrieve
→ reject unusable evidence
→ file
→ connect
→ challenge
→ investigate
→ propose
→ judge
→ resolve
→ remember
```

The product sentence is:

> **Dialectic is a workroom where people and agents construct durable artifacts without losing the reasoning, disagreement, provenance, alternatives, and changing evidence that produced them.**

A second sentence now matters just as much:

> **Home is where the whole house becomes visible; scheme work remains in the rooms that own it.**

---

## 2. What the remote changed

The first specification was directionally correct but described several capabilities as future architecture that are now shipped reality.

Since that specification was committed, the remote added or completed:

1. **Home Base** as a live singleton room, a real shared conversation, the bare-launch destination, and the membership-fenced activity view across shared scheme rooms.
2. **Home membership authority** with founder-only management, nondelegable additions, fail-closed access, and a generic-join prohibition.
3. **One URL-authoritative room-navigation transaction** covering initial entry, room and branch selection, search jumps, notifications, Back/Forward, revoked access, and mobile drawer closure.
4. **A shared Home projection** used by both the human interface and Dialectic’s prompt context, under the same membership intersection and an explicit unavailable state.
5. **Personal cross-room memory promotion** as a per-user recall grant that never mutates shared memory scope or another participant’s context.
6. **A complete thesis lifecycle**: proposal, stateless model draft, human review, creation, instant first cycle, deep editing, retirement, unbinding, and successor birth.
7. **Implicit commitment detection** that produces an attributable proposal beneath the human’s own message and writes only after a human tap.
8. **The reading and research stack**: article extraction, library filing, night reading, Wire monitoring, deep research, claim checking, prediction deadline review, and visible cross-room Echo.
9. **A single thin-content policy** shared by digest and Wire paths so bot-blocked shells, cookie walls, and other unusable pages are rejected before scoring or model work.
10. **A 15-tool participant registry**, with proposal-shaped tools and ordinary tool traces already flowing through both explicit and autonomous participation paths.

The result is not merely “more features.” The remote now contains the first real implementation of the artifact spine, the authority model, the house-wide surface, and the proposal grammar.

The design must build on those contracts. It must not replace them with a cleaner but less capable abstraction.

---

## 3. Status language

Every major capability in this specification is marked conceptually as one of three states.

```text
SHIPPED
Exists in the current remote and constrains the redesign.

TARGET
Approved product behavior that still needs implementation.

DEFERRED
Intentionally outside the first implementation of this redesign.
```

The distinction is load-bearing. A design document that calls current behavior future work will recreate solved problems. A design document that calls aspirational behavior live will mislead the implementation.

---

## 4. Current production substrate — SHIPPED

### 4.1 Platform and application stack

Dialectic currently ships as:

- FastAPI and PostgreSQL backend.
- React, TypeScript, Zustand, and Vite PWA.
- Real-time WebSocket collaboration.
- Installed and browser-based use across macOS, Windows, iOS/iPadOS, and Android.
- Event-backed messages, memories, branches, commitments, attachments, LLM decisions, and scheduled work.
- A live tradingDesk integration with room-bound causal thesis books.
- A tool-using primary participant, a participation finite-state machine, silence follow-ups, annotations, and scheduled jobs.

The React PWA is the reach strategy. The frozen React Native package is not part of this redesign. Native mobile or desktop applications are not required.

### 4.2 Verification baseline

The latest logic commit at this reconciliation records **1,061 passing backend tests**. The owner separately reported frontend TypeScript checking and Vite production builds green at the seven-phase completion point. GitHub exposes no CI status checks on the current head, and this documentation-only reconciliation did not independently rerun the suites.

That distinction must remain explicit in future status reporting.

### 4.3 Home Base

Home is already a real room, not a mock dashboard.

Its current contracts are:

- One singleton `is_home` room.
- Bare `/` enters Home’s root branch.
- Explicit room and branch destinations override Home.
- Amo and Dan are the current founder-managers.
- Founder management authority is nondelegable.
- Added Home members may participate but cannot add more members.
- Generic room joining refuses Home.
- Home cannot create, draft, bind, propose, or own a trading thesis.
- Home inherits ordinary conversation, memory, protocols, stakes, Dialectic participation, silence behavior, and local briefing behavior.
- Home adds a read-only, membership-fenced cross-room activity projection.

The activity projection shows only rooms that **every current Home member** belongs to. Adding a member can contract the visible house immediately. This is not a convenience filter; it is the privacy and shared-context boundary.

The same projection feeds:

- The Home human interface.
- Dialectic’s `Shared Home Activity` prompt layer.

Dialectic does not receive a broader hidden house view than the humans. If the projection cannot be built within its time budget, the model receives an explicit unavailable marker rather than fabricated emptiness.

Unread boundaries are per thread so Home and the room rail cannot disagree. The activity read writes no receipts.

### 4.4 Current Home composition

The shipped Home surface already establishes useful identity language:

```text
Residents
Needs you
The house
Scheme doors
The table beneath
```

The `HomeActivityPulse` presents residents, due commitments, unresolved questions, unread work, and doors into shared rooms and changed branches. The transcript beneath it is described in code as **the table, not the place**.

This is the correct transitional geometry. The redesign should expand the house above the table rather than reverting Home to a labeled chat silo or replacing it with a disconnected dashboard.

### 4.5 Navigation

`useRoomNavigation.ts` is the single destination writer.

It currently owns:

- Initial entry.
- Home fallback.
- Room and branch state installation.
- URL history.
- Back/Forward.
- Search jumps.
- Notification entry.
- Revoked-room correction.
- Create and join entry.
- Mobile drawer closure.

Current canonical URLs are room- and branch-aware. Home’s root is bare `/`; ordinary rooms and non-root branches have explicit destinations.

This single-writer rule is a hard boundary. The redesign may extend scene and object addressing, but it may not reintroduce competing effects or component-local destination writes.

### 4.6 Responsive shell

The current application already has usable mobile drawers rather than hiding the rails.

- The room rail and cockpit become slide-over drawers below the desktop boundary.
- Scrim and Escape close them.
- Destination changes close them.
- Branches remain reachable on phones.
- Exactly 1024 CSS pixels is part of the current desktop acceptance contract.

The dynamic-scene redesign must extend this shell or replace it only with equivalent, newly verified behavior. It may not regress phone and tablet access while pursuing a more ambitious desktop composition.

### 4.7 Memory and personal promotion

Room memory is currently presented as a dossier rather than a raw key-value dump.

The shipped panel separates:

- Human-meaningful remembered facts.
- Dialectic’s identity papers.
- Participant models.
- Current thesis-state papers.

Personal promotion is a separate visibility grant:

```text
Shared memory row remains shared
+
User-specific promotion grant
=
Eligible for that user’s cross-room recall
```

Promotion does not:

- Change the memory’s shared scope.
- Move or copy the source memory.
- Grant another collaborator access.
- Make the item a shared House fact.

Recall remains membership-fenced to the source room. Promotion and demotion are idempotent, and the UI exposes the requesting user’s state only.

### 4.8 Proposal grammar

The remote now contains several proposal-shaped workflows sharing one trust pattern:

```text
Dialectic detects, drafts, or recommends
→ proposal is visible and attributable
→ human reviews
→ human tap performs the write
→ accepted state is durable and disarms repeat action
```

Shipped proposal surfaces include:

- Draft prediction.
- Proposed thesis.
- Claude-drafted thesis DAG.
- Detected human commitment.
- Save-reading proposal.
- Prediction-resolution proposal.

Message metadata and the `MESSAGE_METADATA` WebSocket patch are the current transport for several of these proposal objects. That is not the final visual home, but it is a proven interoperability seam and should be reused during migration.

### 4.9 Thesis lifecycle

An ordinary room can now birth one thesis at a time.

The current lifecycle is:

```text
Unbound room
→ title and claim
→ optional Claude DAG draft
→ validation and one correction retry
→ human phase-grouped review
→ Accept & Create
→ book born already bound to the room
→ immediate first evaluation cycle
→ live thesis panel
→ deep link to tradingDesk Builder
→ retire from room
→ book survives on the desk
→ room may birth a successor
```

A mid-conversation `propose_thesis` tool creates a proposal only. The human enters the creation surface and remains responsible for acceptance.

The drafted structure describes causal architecture. Runtime facts, prices, node states, and verification must be earned by the live pipeline rather than copied from model output.

Retirement clears the room binding and current thesis state without deleting the historical book.

### 4.10 Commitment detection

Human language such as “I bet” or “mark my words” can now produce a commitment proposal under the source message.

The detector may create proposal chrome. It does not create the commitment. “Put it on record” is the human write, and the accepted stamp prevents duplicate action after live updates or reload.

This is a direct precedent for future low-friction artifact capture: inference may be immediate, but authority remains human.

### 4.11 Reading Library

`reading_items` is the first native evidence-artifact table.

Current behavior includes:

- Room-scoped article filing.
- Full article body and provenance.
- Full-text search.
- Unique room-and-URL identity so rereading refreshes rather than duplicates.
- Human-Accept save flow.
- Re-fetch at acceptance time so the library stores the page, not the model’s recollection of it.
- A distilled memory twin so existing three-lane recall can find readings without storing full bodies in memory.
- One shared thin-content policy across automated filing paths.

Bot-blocked shells, cookie walls, and other thin pages do not become readings and do not consume downstream scoring or synthesis calls in the protected paths.

The reading and its memory twin are one conceptual evidence object. The UI must not show them as duplicates.

### 4.12 Night Shift and morning brief

The reading stack includes a 05:30 America/Chicago thesis-news digest ahead of the 07:00 brief.

For linked rooms it can:

- Pull new thesis-relevant headlines.
- Extract article bodies.
- Reject unusable content.
- Distill fresh articles against the live thesis.
- File a limited set into the Library.
- Expose them in the morning brief’s “Read overnight” section.

Implementation and activation are separate facts. These jobs are feature-flagged, and the interface must distinguish “nothing relevant arrived” from “the job is disabled, unavailable, or failed.”

### 4.13 The Wire

The Wire watches linked-room news on a shorter cadence.

Current behavior:

- New articles are extracted and checked for usable content.
- Haiku scores relevance against the live thesis.
- Material hits are filed into the Library.
- A real facilitator interjection may be created.
- Room/day caps, quiet hours, and the room’s auto-interjection setting apply.

The relevance decimal is routing machinery. The product should explain why the article matters rather than displaying a pseudo-scientific score as truth confidence.

### 4.14 Research mode

The composer has a deliberate Research action.

Research currently runs a long tool loop:

- Up to 15 iterations.
- Up to 300 seconds.
- Gather, cross-check, and synthesize behavior.
- Ordinary tool-activity and streaming events.
- One active deep dive per room.
- Final result persisted as a normal primary-participant message with source metadata.
- Proposal payloads may be hoisted into the result.

Research is therefore a real artifact generator in behavior, but its result is not yet a first-class Brief entity. The redesign should project the persisted research turn into a reusable Brief object before adding a new storage model.

### 4.15 Claim Check

When a human message contains a URL, the system can compare the message’s representation against the extracted article.

Only `mixed` or `misrepresented` produces a quiet visible warning. Supported and unrelated cases remain visually silent by design.

Failure paths are also silent in the current room UI. The redesign must preserve low-noise behavior without implying that absence of a warning equals successful verification. Full check state belongs in provenance and diagnostics.

### 4.16 Prediction deadline review

The deadline watcher finds due linked predictions, gathers evidence, asks for a verdict, and produces a resolution proposal.

Nothing resolves automatically. A human judgment invokes the relay.

Unlinked predictions are skipped because there is no reliable room mapping. The interface must represent this as an unavailable evidence route rather than pretending the prediction was reviewed.

### 4.17 Echo

Echo makes a reading from one room visibly relevant to another room’s thesis.

Current behavior preserves:

- Origin room.
- Source reading lineage.
- Target room.
- Relevance explanation.
- A visible annotator note.
- A cross-session reference from the origin reading’s memory twin.

Echo is a citation and connection, not a copied article and not a silent injection. The existing automatic cross-session promotion gate remains untouched.

### 4.18 Participant and tool substrate

The primary participant currently has a 15-tool registry. Explicit and autonomous primary paths can use tools; provoker, protocol, and annotator paths do not receive the same tool authority.

Tool activity is transient while work runs and durable in the completed message trace. The redesign must preserve both:

- Human-readable live activity.
- Expandable audit after completion.

Current participant-facing UI still uses provider/persona language such as “Claude.” The target identity uses **Dialectic** for the product participant and keeps provider/model names in provenance. This is an intentional front-end identity migration, not a requirement to rename every backend class or historical record.

---

## 5. Non-negotiable contracts

The following contracts are now stronger than any visual concept in this document.

### 5.1 Human authority

Dialectic may:

- Read.
- Search.
- Infer.
- Draft.
- Propose.
- Attach provisional relationships.
- Produce visible warnings.
- Run scheduled reviews.

Dialectic may not silently:

- Create a commitment.
- Create or retire a thesis.
- Save a human-authoritative reading proposal as accepted.
- Resolve a prediction.
- Declare consensus.
- Modify the shared Ledger.
- Promote one person’s memory for another person.
- Take an external action requiring standing permission.

The human tap remains the write for proposal-shaped actions.

### 5.2 Shared visibility is intersectional

Home shows only rooms and activity shared by every current Home member. The target House scene must use the same fence.

No cross-room surface may obtain a broader view merely because it is visually global.

### 5.3 Human and Dialectic house context must match

The human House surface and Dialectic’s Home prompt layer derive from the same projection and authorization boundary.

A hidden “agent superview” is prohibited.

### 5.4 Personal recall is personal

A personally promoted memory is not a House fact, not a room-wide Ledger item, and not visible in another participant’s personal recall.

### 5.5 Home coordinates; scheme rooms own scheme work

Home is the house-wide coordination room. It may contain house decisions, shared conversation, resident norms, and cross-room movement.

It may not own a trading thesis. Thesis work remains in an ordinary scheme room.

The same principle should guide future artifact types: Home links and coordinates; scheme artifacts remain with the room that owns their context unless explicitly promoted into a house-level artifact by humans.

### 5.6 Evidence must be real enough to file

Unusable page shells do not become evidence. Automated paths share one quality guard. A failed retrieval is not a successful reading with empty content.

### 5.7 Navigation has one owner

All destination changes continue through one navigation transaction. Scene routing and object deep links extend that transaction rather than bypass it.

### 5.8 The Record is never rewritten by interpretation

Messages, proposal decisions, tool traces, and artifact events remain exact history. Later structure may interpret or supersede meaning; it may not rewrite what was said or done.

### 5.9 No feature may become desktop-only

Every essential action must remain usable in browser and installed-PWA contexts on macOS, Windows, iOS/iPadOS, and Android.

---

## 6. Product model

### 6.1 The House and the workrooms

Dialectic has one Home Room and many scheme workrooms.

```text
HOME
The relationship, residents, shared activity, house decisions, and doors

WORKROOMS
The durable schemes, theses, research, evidence, branches, and commitments
```

Home is not a summary page outside the product. It is a room inside the product with the privilege and responsibility of seeing shared house state.

A room is not merely a conversation channel. It is a bounded workspace with:

- A purpose.
- Participants.
- Branches.
- Artifacts.
- Evidence.
- Deliberation.
- Memory.
- Proposals.
- Decisions.
- A Record.

### 6.2 The Artifact spine

The shipped Artifact spine already includes:

- Thesis books and snapshots.
- Readings.
- Predictions and commitments.
- Room memories.
- Personal recall grants.
- Accepted proposal state.
- Attachments.

Target artifact projections add:

- Research Brief.
- Decision dossier.
- House movement item.
- Evidence review.
- Structured synthesis.

Native collaboratively editable documents may arrive later, after the current objects have established the common interaction contract.

### 6.3 The Deliberation spine

The Deliberation spine contains the reasoning around artifacts:

- Questions.
- Claims.
- Evidence.
- Challenges.
- Definitions.
- Counterexamples.
- Tensions.
- Assumptions.
- Alternatives.
- Syntheses.
- Human judgments.

Some deliberation is currently implicit in messages, message types, annotations, thesis links, proposal rationales, and tool traces. Durable reasoning objects remain a target, not a shipped claim.

### 6.4 The Record

The Record contains exact chronological speech and operations:

- Human contributions.
- Dialectic contributions.
- Tool activity.
- Metadata enrichment.
- Proposal creation and decision.
- Branch creation.
- Memory changes.
- Thesis birth and retirement.
- Evidence filing.
- Research completion.
- Prediction judgment.
- Scheduled intervention.

The Record is searchable, auditable, and linkable. It is not deleted merely because a higher-order artifact summarizes it.

### 6.5 The Current

The Current is the flow of outside-world changes that may matter to active work.

It includes:

- Wire hits.
- Night readings.
- Human-provided sources.
- Claim-check warnings.
- Trading-state changes.
- Prediction evidence.
- Echoes.

The Current is not a generic news feed. Every visible item must answer:

```text
Why did this enter the house?
Which room or artifact may it affect?
What happened to it?
What judgment, if any, is required?
```

---

## 7. Canonical surfaces

### 7.1 House — SHIPPED FOUNDATION, TARGET EXPANSION

Home’s default surface is the house-wide view.

The shipped composition already provides:

```text
Residents
Needs you
The house
Scheme doors
Home table
```

The target House scene expands “Needs you” and the scheme doors with semantic movement from the newly shipped evidence and proposal systems.

The House scene answers:

```text
Who is here?
What needs a human?
What changed while we were away?
Which schemes are active?
What did Dialectic do?
What evidence arrived?
What should we resume?
```

Priority order for “Needs you” should be:

1. Human-authority proposals awaiting action.
2. Due predictions and commitments.
3. Unresolved direct questions.
4. Material claim-check warnings.
5. Research results carrying proposals.
6. New Echoes or evidence connections requiring review.
7. Ordinary unread activity.

Representative House composition:

```text
HOME
Amo · Dan · Dialectic

NEEDS YOU
Prediction P-18 — evidence pack ready
Research R-12 — two proposed thesis changes
Claim check — source may misrepresent the exemption
Dan asked — unresolved in AI Capex

WHILE WE WERE AWAY
3 readings filed
1 Wire interruption
1 thesis state changed
1 cross-room Echo

THE HOUSE
Iran / Hormuz
AI Capex
China Property
Japan Rates

AT THE TABLE
The live Home conversation, subordinate to the house above it
```

The table may remain visible beneath the House scene. It does not become the entire place again.

Every House item links to an exact authorized destination. House does not duplicate the source artifact or mark it read merely by projection.

### 7.2 Bench — SHIPPED SEEDS, TARGET UNIFICATION

The Bench is the construction surface for the active artifact.

Existing Bench seeds include:

- Trading panel and thesis creation flow.
- Thesis draft preview.
- Reading proposal cards.
- Commitment and prediction cards.
- Memory dossier.

Target Bench behavior is object-specific:

```text
Thesis       causal model, authored structure, live state, evidence, predictions
Reading      source body, extraction, thesis impact, citations, attached work
Brief        question, findings, disagreement, implications, proposals
Decision     options, evidence, objections, outcome, rationale
Commitment   claim, deadline, confidence history, evidence, judgment, calibration
House item   source room, movement, required action, disposition
```

The Bench should recompose existing components rather than rebuilding functional workflows in parallel.

### 7.3 Field — TARGET

The Field presents the current reasoning structure around the work:

- Positions.
- Claims.
- Challenges.
- Definitions.
- Evidence.
- Tensions.
- Shared premises.
- Branches.
- Syntheses.

It is spatial but not freeform. It behaves like a living editorial proof rather than a force-directed graph.

The Field is not shipped merely because message types and a thesis DAG exist. Those are useful source structures, not the final deliberation model.

### 7.4 Focus — TARGET

Selecting an object transforms the scene around it.

Focus reveals:

- Current state.
- Source events.
- Incoming and outgoing relationships.
- Evidence.
- Open questions.
- Proposal state.
- Branch variants.
- Checks.
- Revision history.
- Available actions.

Focus replaces generic permanent tabs as the primary inspection mechanism, while preserving the mobile drawer as a navigation and utility surface.

### 7.5 Current — TARGET SURFACE OVER SHIPPED DATA

The Current gathers material outside-world movement across the authorized house or active room.

It must distinguish:

- Filed.
- Rejected as unusable.
- Relevant but unreviewed.
- Attached provisionally.
- Discussed.
- Superseded by newer reporting.
- Retrieval unavailable.

No empty automated run should be rendered as evidence that nothing happened.

### 7.6 Library — SHIPPED DATA, TARGET PRIMARY SURFACE

The Library is the durable evidence surface.

A reading should show:

```text
Title and source
Filed time and filing path
Retrieved body provenance
Why it was relevant
Room or thesis impact
Used by
Challenges / supports
Human review state
Newer or superseding reporting
```

Useful groupings include:

- New.
- Attached to work.
- Cited.
- Contested.
- Cross-room.
- Superseded.
- Unread by humans.
- Retrieval failed or unavailable, when the user explicitly inspects attempts.

The reading memory twin remains internal and deduplicated.

### 7.7 Ledger and Dossier — SHIPPED SEEDS, TARGET CLARIFICATION

The **Ledger** holds state the room has authorized:

- Decisions.
- Definitions.
- Accepted premises.
- Disputed premises.
- Constraints.
- Open questions.
- Working room memory.

The **Dossier** is how remembered material is presented and inspected:

- Human-kept facts.
- Dialectic’s identity papers.
- Participant models.
- Thesis-state papers.
- Personal recall promotion state.

A personal promotion is not a Ledger promotion. The UI must keep those meanings distinct.

### 7.8 Record — SHIPPED, TARGET REPOSITIONING

The Record is the exact transcript and operation history.

It retains:

- Search.
- Reply references.
- Attachments.
- Tool traces.
- Proposal cards and decisions.
- Source-message links.
- Branch provenance.

Proposal cards may gain richer object scenes elsewhere, but their originating Record event remains intact.

### 7.9 Atlas — TARGET

The Atlas presents higher-order relationships across the authorized house:

- Rooms.
- Branches.
- Theses.
- Readings.
- Briefs.
- Predictions.
- Commitments.
- Echoes.
- Shared sources.
- Contradictions.
- Stale verification.
- Open questions.

The existing Home scheme doors and BranchTree are early Atlas primitives. Atlas must grow from real relationships rather than become a decorative global graph.

---

## 8. Workspace projection architecture

### 8.1 Adapter-first, not universal-table-first

The first specification correctly rejected a premature generic artifact database. The remote now makes that decision even stronger.

The system already has mature entities with their own lifecycle semantics. The frontend should unify them through projections before moving them into a new shared storage model.

```text
WorkspaceObject

id
kind
room_id
branch_id, when applicable
title
summary
status
created_at
updated_at
provenance
relationships
available_actions
review_state
source_entity
source_event
```

Adapters project current entities:

```text
reading_items                    → Reading
messages[source=deep_dive]       → Research Brief
trading book + snapshot          → Thesis
commitment / prediction          → Commitment
message metadata proposal        → Proposal
memory                           → Dossier entry
personal memory grant            → Personal recall state
Home activity projection item    → House movement
message + event history           → Record event
```

### 8.2 Research Brief projection

Research currently lands as a normal primary-participant message. The first Brief implementation should be a projection over that durable message and metadata.

It should expose:

- Research question.
- Source list and trace.
- Findings.
- Source agreement.
- Material disagreement.
- Implications.
- Proposals.
- Completion and failure state.

A new Brief table is not required until editing, versioning, or independent lifecycle demands it.

### 8.3 Proposal envelope

Current proposal types should normalize into one frontend contract:

```text
ProposalEnvelope

id or stable source coordinate
proposal_kind
source_message_id
room_id
branch_id
created_by
created_at
rationale
payload
status
accepted_by
accepted_at
target_object
available_actions
```

Initial normalized kinds:

- `prediction_draft`
- `thesis_proposal`
- `thesis_draft`
- `commitment_proposal`
- `reading_draft`
- `prediction_resolution`

Future Ledger and artifact-edit proposals should reuse the envelope.

### 8.4 Proposal status

The visible proposal lifecycle is:

```text
proposed
accepted
rejected or dismissed
superseded
expired, when the target is no longer actionable
failed, when a human-authorized write did not complete
```

Accepted proposals remain inspectable. They do not disappear as if no proposal ever existed.

### 8.5 House movement projection

House movement is a projection, not a copied artifact.

A movement item identifies:

- Origin room.
- Origin branch or object.
- Movement kind.
- Human relevance.
- Required judgment.
- Current state.
- Exact destination.

The first extension should cover:

- Reading filed.
- Research completed.
- Claim-check warning.
- Wire interruption.
- Prediction due or reviewed.
- Commitment due.
- Echo created.
- Thesis created, materially changed, or retired.

All items remain subject to Home’s all-members intersection.

---

## 9. Proposal interaction grammar

### 9.1 One trust shape

The product should make the shared rule obvious across every proposal surface:

> **Dialectic can prepare the move. A human makes it real.**

The UI should not teach each proposal type as an unrelated exception.

### 9.2 Context before action

A proposal must show:

- What will change.
- Where it will change.
- Why Dialectic proposed it.
- Which evidence or message produced it.
- Whether the action crosses into tradingDesk or another system.
- What remains reversible.

### 9.3 Human acceptance

Acceptance must:

- Be explicit.
- Be idempotent.
- Disable duplicate actions for all affected viewers when state is shared.
- Preserve the accepting human.
- Surface failure rather than silently pretending success.
- Leave the proposal intact for audit.

### 9.4 Proposal placement

During migration, proposals may continue to render in the Record because that is where their durable metadata currently lives.

The target placement is contextual:

- Thesis proposal opens the Thesis Bench.
- Reading proposal opens Evidence Review.
- Commitment proposal opens the Commitment Bench.
- Prediction resolution opens Judgment.
- Research proposals attach to the Brief and affected artifact.

The Record retains the source card and links to the richer scene.

---

## 10. Home and House trust boundary

### 10.1 Home is a household, not an admin dashboard

The Home Room contains the actual shared relationship and ordinary conversation. The House scene is the organizing layer above that table.

The interface should preserve the current language of place:

```text
Residents
Needs you
The house
Doors
The table
```

It should not replace this with enterprise labels such as Overview, Tasks, Resources, or Workspace Analytics.

### 10.2 Membership authority

The visible Home membership model is narrow:

- Current founder-managers can add an existing credentialed account.
- Added members cannot delegate authority.
- Unauthorized users do not receive existence-leaking detail.
- Generic join is not a Home membership path.
- Emergency removal remains an explicit controlled operation until a reviewed product path exists.

The front-end identity redesign must not soften these boundaries for convenience.

### 10.3 House contraction

When Home membership expands, shared room visibility may contract.

The UI should explain this plainly:

```text
The house shows rooms shared by everyone who lives here.
Adding a resident may hide rooms they do not belong to.
```

The contraction is immediate and expected.

### 10.4 Shared projection parity

If humans can see a House item, Dialectic in Home may reason over that same item. If the item is outside the intersection, neither receives it through Home.

### 10.5 Staleness

A stale House snapshot remains visible with a clear stale marker and retry. It is better to show the last known authorized state than replace it with a blank surface that implies nothing exists.

### 10.6 Home artifact boundary

Home can own:

- House decisions.
- Resident norms.
- Cross-room syntheses explicitly accepted into Home.
- Shared planning.
- Home conversation and memory.

Home cannot own a trading thesis. Scheme-specific artifacts stay in their scheme room and are linked from Home.

---

## 11. Memory, Ledger, and personal context

### 11.1 Shared room memory

A room memory is part of the shared room state. Its content, provenance, speaker attribution, version history, and supersession remain visible to authorized members.

### 11.2 Personal promotion

A personal promotion is a recall grant, not an edit.

The UI language should communicate:

```text
Promote for me
Personal
Remove from my cross-room recall
```

It should not suggest:

```text
Make global
Move to my memory
Hide from the room
```

### 11.3 No leakage into House

Personal promotions do not enter the shared House projection, shared Ledger, or another resident’s context.

A House synthesis may only use such a memory if the relevant human explicitly brings it into the shared room or authorizes a shared artifact.

### 11.4 Dialectic’s papers

Identity papers, participant models, and system-managed thesis-state memory should remain distinct from human-kept facts.

The target participant label is **Dialectic’s papers**. Historical records may continue to say Claude.

### 11.5 Echo is not promotion

Echo creates a visible cross-room citation because a reading may matter elsewhere. It does not personally promote the source memory, copy the reading, or silently change another room’s recall policy.

---

## 12. Thesis as the mature Bench

The thesis lifecycle is the most complete example of the future Artifact spine.

### 12.1 Authored structure versus live state

The Thesis Bench must distinguish:

```text
AUTHORED MODEL
Claim, nodes, edges, mechanisms, lags, scenarios

LIVE STATE
Current values, fired/approaching nodes, phase, confluence, countdowns

EVIDENCE
Readings, market data, claim checks, research, annotations

HUMAN JUDGMENT
Predictions, decisions, retirement, revisions
```

Model-generated drafts may propose authored structure. They may not claim live verification.

### 12.2 One thesis per ordinary room

An ordinary room may have one bound thesis at a time. The interface must make the lifecycle explicit rather than hiding create behind the existence of current state.

The Trading/Thesis door remains reachable even when no thesis exists.

### 12.3 Draft and review

The draft step is stateless and review-first.

The Bench shows:

- Title and root claim.
- Phase-grouped nodes.
- Edges and quantified mechanisms.
- Validation warnings.
- What the model inferred.
- What remains unverified.

The human may accept, revise through the supported surface, discard, or create an empty thesis for manual work.

### 12.4 Immediate adoption

After creation, the first live cycle should remain fast enough that the user does not stare at an unexplained empty artifact. Loading, no-data, and evaluation-failed states must be distinct.

### 12.5 Deep editing

The existing tradingDesk Builder remains the deep graph-editing surface until Dialectic earns an equivalent native editor.

The redesign should make the transition feel like opening a deeper instrument, not leaving for an unrelated product.

### 12.6 Retirement

Retirement:

- Is a human action.
- Removes the room binding.
- Preserves the book on the desk.
- Clears current room state.
- Invalidates current thesis memory.
- Preserves the Record.
- Allows a successor.

The old thesis remains addressable in history and future Atlas views.

### 12.7 Home guard

Home never displays a creation form or accepts a thesis proposal. It explains that theses belong in scheme rooms and offers authorized doors to those rooms.

---

## 13. Evidence metabolism

### 13.1 Reading acquisition

A reading may enter through:

- Human proposal and Accept.
- Night Shift.
- The Wire.
- Research.
- A future explicit import.

Every route converges on the same evidence-quality and filing semantics.

### 13.2 Thin-content policy

There is one shared test for whether extracted content is substantial enough to treat as an article.

The exact word threshold is an implementation parameter. The design contract is:

- One policy.
- Shared by automated filing paths.
- Applied before scoring and synthesis where possible.
- Bot-blocked shells never masquerade as evidence.
- Rejection is diagnosable without cluttering ordinary room activity.

### 13.3 Night Shift scene

Night Shift output should project into a structured overnight artifact:

```text
READ
What was filed

CHANGED
What active work may need revision

UNCHANGED
What was checked and still stands

OPENED
New questions or evidence gaps

PROPOSED
Human-authority actions waiting for review
```

The morning conversational message remains in the Record. House and room scenes consume the structured projection.

### 13.4 Wire movement

A Wire hit should appear as object-centered movement:

```text
THE WIRE
New reporting may alter Reopening Pressure.

Why Dialectic interrupted
Named insurer evidence conflicts with the active 30-day assumption.

Examine evidence · Attach provisionally · Discuss · Dismiss
```

A participant turn may accompany the movement when active conversation makes speech appropriate. The structural item remains the durable navigation target.

### 13.5 Research workbench

Research live state should expose observable operations without revealing private chain-of-thought:

```text
Gathering sources
Cross-checking claims
Tracking source disagreement
Preparing synthesis
```

The finished Brief exposes sources, findings, uncertainty, and proposals.

### 13.6 Claim-check trust language

The normal room surface remains quiet unless the result is material.

The inspector exposes:

```text
not checked
checking
supported
mixed
misrepresented
unrelated
unavailable
```

Absence of a warning must never be labeled “verified.”

### 13.7 Prediction Judgment

A due prediction opens a dedicated Judgment workbench:

```text
Prediction
Deadline
Definition of success
Evidence pack
Dialectic assessment
Human judgment
```

The design should support non-binary outcomes when the downstream contract permits them. Where the current relay only permits correct/incorrect, the UI must not fabricate additional write options.

### 13.8 Echo

Echo appears as a cross-room relationship:

```text
Origin reading
Origin room
Target room and artifact
Why the connection matters
Attach here · Inspect source · Dismiss for this room
```

Dismissal applies to the target relationship, not the source reading.

---

## 14. Deliberation and inference — TARGET

### 14.1 Current foundation

The remote currently has several precursors:

- Explicit message types.
- Reply references.
- Annotations.
- Proposal rationales.
- Claim-check metadata.
- Tool traces.
- Thesis causal structure.
- Branch genealogy.

It does not yet have the full durable reasoning-object model described below.

### 14.2 Epistemic dimensions

Every inferred reasoning object should carry independent dimensions:

```text
ORIGIN
explicit | inferred

REVIEW
provisional | confirmed | contested | superseded

DELIBERATIVE STATUS
active | accepted | rejected | resolved | withdrawn
```

Confirmation means the room accepted the representation. It does not mean the proposition is true.

### 14.3 Low-risk automatic structure

Dialectic may place these into the Field immediately as provisional:

- Contribution type.
- Claim grouping.
- Support or challenge relationship.
- Repeated definition.
- Possible contradiction.
- Emerging position.
- Evidence attachment.
- Branch candidate.
- Unanswered question.
- Candidate synthesis.

### 14.4 Human-ratified authority

These require explicit human judgment:

- Accepted premise.
- Declared consensus.
- Decision.
- Resolved tension.
- Final definition.
- Branch merge.
- Rejection of a position.
- Shared Ledger change.
- Memory invalidation.
- Claim that a participant changed position.

### 14.5 Corrections

Corrections are first-class:

```text
Not support — qualification
These are different definitions
Do not group these claims
This question is already answered
A participant has not conceded
Change source span
Split or merge an inferred object
```

Corrections remain attributable and inform future room-specific inference.

### 14.6 Do not build the compiler first

The Field should not begin with a large new reasoning database and a global model pass.

First implement:

1. Workspace object adapters.
2. Proposal normalization.
3. Source and provenance links.
4. Object-centered scenes.
5. Local, reversible inferred relationships.

Only then should a durable reasoning compiler be introduced for relationships that have proven useful in daily work.

---

## 15. Navigation and device-local restoration

### 15.1 Shipped navigation contract

Current navigation provides:

- Bare `/` to Home root.
- Explicit room and branch URLs.
- Notification entry.
- Search jumps.
- Back/Forward.
- Revoked-access correction.
- One destination writer.

This is the foundation.

### 15.2 Target restoration contract

The approved restoration contract is exact and device-local across macOS, Windows, iOS/iPadOS, and Android.

```text
New installation, browser profile, or independent window
→ Home → House

Explicit deep link or notification
→ Exact referenced destination

Restoration of the same local app/window context
→ Exact previous local scene
```

Current code restores room and branch through URL and persisted authentication state. It does **not** yet restore the complete scene contract below. That is target work.

Exact scene state includes:

- Room.
- Branch.
- Scene.
- Selected workspace object.
- Focus or workbench mode.
- Inspector state.
- Field viewport.
- Record scroll position.
- Open proposal or evidence review.
- Composer draft and reply target.

### 15.3 Precedence

Startup precedence is:

1. Explicit object deep link.
2. Explicit room or branch deep link.
3. Valid local restoration identity.
4. Home → House.

A stale or unauthorized restored object falls back to the nearest valid parent, then the room root, then Home. It does not loop back to an invalid URL.

### 15.4 Device and window locality

Restoration state is not synchronized through the server.

- Mac state does not move Windows.
- Windows does not move Android.
- Android does not move iOS.
- Separate desktop windows remain independent when the browser offers stable window identity.
- If stable window identity is unavailable, the installation’s most recent valid scene is the fallback.

No silent cross-device takeover is allowed.

### 15.5 Reconciliation

Transient state is rebuilt from server truth:

- Typing users.
- Socket state.
- Tool activity.
- Streaming state.
- Proposal status.
- Access rights.
- Current artifact revisions.

A restored composer draft remains local until sent.

---

## 16. Visual and behavioral identity

### 16.1 Governing character

> **An active reasoning instrument with the visual gravity of a private intellectual salon.**

The interface is quiet at rest and expressive when work changes.

It must not resemble:

- A SaaS dashboard with dark mode.
- A social network.
- A debate game.
- A generic AI assistant.
- A prettier chat transcript.
- A Miro-style freeform graph.
- An autonomous system silently rewriting participant intent.

### 16.2 Identity hierarchy

The visible product identity is **Dialectic**.

DwoodAmo is the restrained origin imprint:

```text
A DWOODAMO WORKROOM
```

Provider names remain in provenance, diagnostics, and historical records. Primary product controls should migrate from Claude/provider language to Dialectic.

### 16.3 Product mark

The recommended mark is built from opposition producing movement:

```text
)(
```

Two facing arcs around a narrow interval suggest:

- Tension.
- A doorway.
- A fulcrum.
- Two positions around an unresolved proposition.
- A divided D without a literal monogram.

At larger scale the mark may reflect real room state:

```text
Opening       (   )
Contested     )(
Converging    ( )
Settled       ()
```

It is state-bearing, not a decorative loop.

### 16.4 Color

Canonical dark material palette:

```text
Carbon             #0B0B0A
Graphite            #151513
Iron                #22221F
Warm bone           #E8E1D5
Ash                 #9B978E
Brass               #B89B64
Oxidized copper     #718A80
Dried oxblood       #8C5F5A
Chalk               #F3EEE5
```

Semantic rules:

- Brass: current attention or active transformation.
- Oxidized copper: confirmed or incorporated state.
- Oxblood: real conflict, invalidity, or rejection.
- Broken line and reduced opacity: provisional inference.
- Carbon, bone, and ash carry most of the product.

Color does not encode participants.

### 16.5 Typography

Three voices:

- **Propositional serif** for central questions, major positions, selected propositions, and syntheses.
- **Operational grotesk** for navigation, controls, ordinary contributions, and room state.
- **Provenance mono** for identifiers, timestamps, source chains, branch coordinates, and technical metadata.

The serif appears when language itself is the object of attention. It does not turn the whole application into a book reader.

### 16.6 Current voice worth preserving

The remote has already found several strong labels:

```text
The house
Needs you
Residents
Remember
Keep
Claude’s papers
Put it on record
Accept & Create
```

The redesign should preserve this direct, physical language while migrating provider-facing terms:

```text
Dialectic’s papers
Make a move
Open a branch
Commit to the Ledger
Examine evidence
```

Avoid theatrical jargon.

### 16.7 Spatial grammar

- **Question** orients the Field.
- **Position** forms a territory.
- **Claim** appears as a stable proposition.
- **Evidence** attaches to the claim or artifact it bears on.
- **Counterexample** cuts across its target.
- **Tension** lives between incompatible objects.
- **Definition** stays near the term it governs.
- **Synthesis** gathers sources without erasing residue.
- **Branch** visibly leaves its source.
- **Proposal** sits at the boundary between inferred possibility and human action.

Most objects should not be rounded cards. Typography, spacing, lines, and spatial relationships carry the structure.

### 16.8 Motion

Motion explains causality:

- A reading attaches to an affected claim.
- A proposal travels from source message to target Bench.
- A challenge creates visible pressure.
- A definition splits.
- A synthesis gathers source material.
- A branch unfolds from its origin.
- An accepted proposal settles into durable state.

Disallowed:

- Ambient particles.
- Decorative parallax.
- Glowing AI pulses.
- Floating gradients.
- Constant card movement.
- Fake thinking theater.
- Full-scene reshuffling after ordinary activity.

Reduced-motion mode retains all meaning.

### 16.9 Participant identity

Participants use restrained signatures rather than bright avatar colors.

```text
AMO        A
DAN        D
DIALECTIC  )
```

There are no debate scores, like counts, or winner mechanics.

---

## 17. Responsive and accessible behavior

### 17.1 Platforms

The same product contract applies to:

- macOS browser and installed PWA contexts.
- Windows browser and installed PWA contexts.
- iOS/iPadOS Safari and installed web-app contexts.
- Android Chrome and installed PWA contexts.

### 17.2 Desktop

Desktop supports simultaneous House/room context, dominant active scene, and Focus or utility surface.

Independent windows maintain independent local scenes when possible.

### 17.3 Tablet and phone

The current drawer contract remains the minimum:

- Room and cockpit access remain reachable.
- Scrim and Escape behavior remain coherent.
- Destination changes close drawers.
- No action depends on hover.
- The composer remains usable with the software keyboard.

Target dynamic scenes may become single-surface navigation on narrow screens, with Focus as a sheet or full-screen layer.

### 17.4 Accessibility

Requirements:

- Semantic DOM for readable and actionable objects.
- SVG only for relations and guides, not as the primary reading substrate.
- Selectable text.
- Keyboard navigation.
- Screen-reader summaries of object kind, state, and relationships.
- Visible focus.
- Sufficient contrast.
- No color-only meaning.
- Reduced motion.
- Stable deep links.
- No hover-only controls.

---

## 18. Error, stale-state, and disabled-feature behavior

### 18.1 House unavailable

Keep the last authorized snapshot, mark it stale, and expose Retry. Do not replace it with a blank house.

### 18.2 Restored target unavailable

Fall back through object → scene → room → Home. Explain revoked or missing access without exposing hidden resource detail.

### 18.3 Proposal write fails

The proposal remains proposed or failed. Do not optimistically mark it accepted. The human can retry where safe.

### 18.4 Reading retrieval fails

Do not file a shell. User-initiated inspection may show retrieval failure and retry options.

### 18.5 Claim Check fails

Remain quiet in the normal flow. Provenance inspection shows unavailable rather than supported.

### 18.6 Background job disabled

House and room surfaces distinguish disabled/unavailable from a successful run with no results.

### 18.7 Research fails or is interrupted

Preserve the initiating question and durable progress/error event. Do not publish a partial synthesis as a completed Brief.

### 18.8 Tool activity

Live activity ends when the turn ends. Durable trace remains attached to the final Record event.

---

## 19. Implementation boundary

### 19.1 No framework rewrite

Use the current React, TypeScript, Zustand, Vite, FastAPI, PostgreSQL, WebSocket, scheduler, and tool infrastructure.

### 19.2 No duplicate navigation system

Extend `useRoomNavigation` or its deliberately evolved successor. Do not create scene-routing effects scattered through components.

### 19.3 No duplicate proposal backend

Normalize current metadata proposal types in the frontend first. Add shared backend representation only when lifecycle behavior requires it.

### 19.4 No premature universal artifact database

Use adapters over readings, research messages, theses, commitments, memories, and Home movement. Add native artifact/version/block tables only when collaborative editing creates a concrete requirement.

### 19.5 Progressive recomposition

The current product remains usable throughout migration.

Recommended design tranches:

```text
A. Baseline lock
   Preserve Home, navigation, proposal, memory, thesis, and evidence contracts.

B. Identity shell
   Product tokens, participant naming, scene vocabulary, and responsive scene frame.

C. House v2
   Extend the shipped Home projection and pulse with evidence and proposal movement.

D. Workspace adapters
   Normalize Reading, Brief, Thesis, Commitment, Proposal, Dossier, and Record objects.

E. Evidence scenes
   Library, Research Brief, Claim Check provenance, Judgment, and Echo Focus.

F. Thesis Bench
   Recompose the existing trading lifecycle into the canonical artifact surface.

G. Record repositioning
   Preserve exact history while removing transcript-first layout from ordinary rooms.

H. Field and Focus
   Add local, reversible deliberation structure around proven object relationships.

I. Atlas
   Connect rooms, branches, artifacts, evidence, and Echoes through real provenance.

J. Exact local restoration
   Extend device-local state beyond current room/thread routing and verify all platforms.
```

This ordering is design guidance. A separate implementation plan must inspect current call sites and tests before assigning file-level work.

---

## 20. Verification requirements

### 20.1 Existing contract regressions

Any implementation must preserve tests or equivalent proof for:

- Home singleton behavior.
- Founder-only nondelegable Home management.
- Generic Home join refusal.
- Shared-room membership intersection.
- Shared Home projection parity between humans and Dialectic.
- Explicit unavailable and stale states.
- Home thesis guards.
- Per-thread unread parity.
- Single-writer navigation.
- Room and branch deep links.
- Back/Forward.
- Search and notification entry.
- Mobile drawer reachability.
- Exactly-1024 desktop behavior unless deliberately revised and reaccepted.
- Personal memory isolation and membership fencing.
- Personal promotion and demotion state.
- Thesis draft, create, immediate adoption, retire, and successor flow.
- Proposal acceptance and duplicate prevention.
- Commitment detection detached-task safety.
- Reading acceptance and refetch.
- Shared thin-content rejection.
- Claim-check warning behavior.
- Research event lifecycle.
- Wire caps and quiet-hours behavior.
- Prediction review and human resolution.
- Echo lineage and deduplication.

### 20.2 Browser acceptance

At minimum:

- Large desktop.
- 1200-width desktop.
- Exactly 1024 desktop.
- Tablet width.
- Phone width.
- Installed-PWA shell where available.
- Slow initial room load.
- Revoked persisted destination.
- Stale Home activity.
- Cross-branch deep link.
- Back/Forward.
- Proposal acceptance.
- Composer draft preservation.

### 20.3 Device acceptance

Real-device acceptance must cover representative:

- macOS.
- Windows.
- iPhone/iPad.
- Android.

Cases:

- Deliberate launch to Home → House.
- Exact local restoration.
- Notification deep link.
- Background eviction or process reconstruction.
- Keyboard and software-keyboard behavior.
- Branch and object reachability.
- Offline/stale rendering.
- Independent state across devices.

### 20.4 Performance

The existing Home activity projection measured p95 around 51 ms at the recorded seed scale against a 150 ms design target. New House movement must not destroy that property.

Large, long-lived rooms require:

- Bounded projections.
- Stable cursors.
- No unbounded transcript hydration for object scenes.
- Local scene updates rather than whole-house recomputation.

### 20.5 Evidence before claims

No phase is called complete without fresh proof of the behavior it claims. Historical test counts and owner reports are context, not substitutes for a new verification run.

---

## 21. Non-goals and deferred work

The first implementation of this redesign does not include:

- Branch merging.
- CRDT text editing.
- Generic collaborative code editing.
- A universal artifact database.
- Freeform user-positioned graph layouts.
- Cross-room ontology management.
- Autonomous consensus or resolution.
- Silent standing-permission external action.
- Order placement.
- Multi-agent swarms presented as separate personas.
- Argument scoring or debate winners.
- Public social profiles.
- Plugin marketplace.
- Native mobile or desktop applications.
- Cross-device scene synchronization.
- Replacing tradingDesk’s Builder before Dialectic has earned equivalent depth.

---

## 22. Hard prohibitions

The final interface must not fall back to:

- Chat bubbles as the primary grammar.
- Left-versus-right alignment as the main authorship model.
- Conversation as the only opening surface.
- A separate dashboard outside Home.
- Persistent generic tab sidebars as the main interaction model.
- Rounded-card infestation.
- Purple AI branding.
- Sparkle or robot iconography.
- Bright participant color coding.
- Decorative gradients.
- Freeform graph chaos.
- Hidden automatic structural edits.
- Provider names in primary product controls.
- Personal-memory leakage into shared House state.
- House visibility broader than the all-members intersection.
- Home owning a trading thesis.
- Agent acceptance on behalf of a human.
- Thin or bot-blocked pages presented as filed evidence.
- Cross-device scene takeover.

---

## 23. Acceptance criteria

### 23.1 Identity

- A grayscale screen remains recognizable as Dialectic without the wordmark.
- A human-only room still looks like Dialectic.
- DwoodAmo appears as origin imprint, not competing brand.
- Provider names are available in provenance but absent from primary identity controls.
- No primary ordinary-room screen resembles conventional chat.

### 23.2 Home and House

- Bare launch enters Home.
- Home opens house-wide context rather than a bare transcript.
- Residents, Needs you, scheme doors, and the table form one coherent place.
- House items never exceed the all-members room intersection.
- The human House and Dialectic’s Home context derive from the same projection.
- Adding a Home member visibly contracts shared-room scope when appropriate.
- Home remains a real conversation and never becomes an external dashboard.
- Home cannot create or own a thesis.

### 23.3 Proposal authority

- Every proposal explains its target and consequence.
- Human acceptance is explicit and attributable.
- Shared accepted state disarms duplicate action for every viewer.
- Failed writes remain visible as failed or retryable.
- The originating Record event remains inspectable.

### 23.4 Artifact spine

- A thesis opens a mature Bench without losing its current lifecycle.
- A reading opens as evidence, not merely a chat card.
- A research result opens as a reusable Brief projection.
- A commitment or prediction opens a dedicated judgment surface.
- Every artifact reveals source events and relevant evidence.

### 23.5 Deliberation spine

- Provisional inference is visibly provisional.
- Human corrections are attributable.
- Confirmation is not confused with truth.
- High-consequence state requires human judgment.
- The Record remains exact beneath derived structure.

### 23.6 Memory

- Shared room memory remains shared.
- Personal promotion affects only the promoting user’s cross-room recall.
- Personal state never appears as shared House fact.
- Dialectic’s papers remain distinct from human-kept facts.

### 23.7 Evidence metabolism

- Automated filing paths share one evidence-quality policy.
- Bot-blocked shells do not enter the Library.
- Night Shift work becomes structured movement.
- Wire items identify the affected room or artifact and why they matter.
- Claim Check never implies silent failure passed.
- Echo preserves origin and target lineage.
- Prediction resolution remains a human judgment.

### 23.8 Navigation and restoration

- One transaction owns destination changes.
- Existing room and branch deep links continue to work.
- Object and scene deep links extend the same contract.
- Exact local restoration works across macOS, Windows, iOS/iPadOS, and Android.
- Devices remain independent.
- Invalid restoration falls back safely.

### 23.9 Dynamic interface

- Selection transforms the active scene rather than merely opening a static sidebar.
- Motion explains a real state transition.
- Ordinary updates do not reshuffle the whole room.
- No essential operation depends on hover.
- Phone and tablet users retain full capability.

### 23.10 Accessibility and performance

- Semantic content remains keyboard and screen-reader accessible.
- Reduced-motion mode retains all meaning.
- The layout works from phone width through large desktop windows.
- House and room projections remain bounded and performant in long-lived use.

---

## 24. Supersession map from v1

The following v1 statements are replaced or clarified:

1. **Production baseline:** replaced by the current 15-tool, Home, memory-promotion, thesis-lifecycle, and evidence-stack baseline.
2. **Home Room:** no longer conceptual. It is live and imposes concrete membership, projection, navigation, and thesis-guard contracts.
3. **House scene:** partly shipped as the Home pulse plus table; target work extends it with semantic evidence and proposal movement.
4. **WorkspaceObject:** remains target architecture, now explicitly adapter-first over shipped entities.
5. **Library, Night Shift, Wire, Research, Claim Check, prediction review, and Echo:** implemented substrate, with richer primary scenes still target.
6. **Research Brief:** target projection over a durable deep-dive message, not a new table by default.
7. **Thesis:** promoted from one artifact example to the mature reference lifecycle for the Bench.
8. **Memory:** clarified into shared room dossier, system papers, and private promotion grants.
9. **Exact scene restoration:** still target; current remote provides room/branch URL authority but not the complete local scene contract.
10. **Field, Focus, and Atlas:** remain target and must not be described as shipped.
11. **Frontend migration:** progressive recomposition of the current React PWA, not a rewrite.
12. **Agent authority:** proposal-first trust shape is now a shipped contract across multiple workflows.

---

## 25. Final governing rule

> **Language enters as movement. Evidence must be real enough to file. Structure emerges provisionally. Dialectic may prepare the move; humans give it authority. Artifacts preserve the work. The Record preserves what happened. Personal context remains personal. Home shows only the house its residents truly share.**
