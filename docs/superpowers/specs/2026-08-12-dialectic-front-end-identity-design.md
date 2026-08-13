# Dialectic Front-End Identity and Product Surface Design

**Status:** Approved design, awaiting written-spec review  
**Date:** 2026-08-12  
**Repository:** `Skidudeaa/dialectic`  
**Product:** Dialectic  
**Origin imprint:** DwoodAmo

## 1. Executive decision

Dialectic will not be reskinned as a more attractive chat application. It will be reoriented as a **living construction workroom** where two humans and Dialectic build durable work, inspect the reasoning around it, and continuously incorporate relevant evidence from the outside world.

The product has two equal spines:

```text
ARTIFACT SPINE
What the room is building

DELIBERATION SPINE
Why it is being built that way
```

Conversation remains authoritative history and coordination, but it is demoted from the default product surface to **the Record**.

The shipped Library, Night Shift, claim checking, The Wire, Research mode, prediction resolution, and Echo capabilities form one evidence metabolism:

```text
Observe
→ file
→ connect
→ challenge
→ investigate
→ decide
→ resolve
→ remember
```

The product sentence is:

> **Dialectic is a workroom where people and agents construct durable artifacts without losing the reasoning, disagreement, provenance, alternatives, and changing evidence that produced them.**

## 2. Identity hierarchy

The visible product identity is **Dialectic**.

DwoodAmo is the discreet workshop or origin imprint. It appears only in restrained locations such as the arrival screen, colophon, repository materials, exported records, and system metadata:

```text
A DWOODAMO WORKROOM
```

DwoodAmo never competes with Dialectic as a second masthead.

Model-provider names are technical provenance, not primary product identity. Ordinary interface controls refer to the participant as **Dialectic**, not Claude, GPT, or another provider. Provider and model information remains available in technical inspection and audit history.

## 3. Product character

The governing character is:

> **An active reasoning instrument with the visual gravity of a private intellectual salon.**

Dialectic is precise, kinetic, quiet at rest, and expressive when the state of the work changes. It must not resemble:

- A SaaS dashboard with dark mode.
- A social network.
- A debate game.
- A generic AI assistant.
- A Miro-style freeform graph.
- A prettier transcript.
- An autonomous system that silently decides what participants meant.

The interface becomes more organized as the room grows. Work should accumulate structure and consequence rather than merely length.

## 4. Current production baseline

This design is grounded in the current `Skidudeaa/dialectic` monorepo, not the obsolete January `DanWoodAMO` prototype.

The existing production baseline already includes:

- FastAPI and PostgreSQL backend.
- Componentized React and TypeScript PWA built with Vite.
- Installed and browser-based use across macOS, Windows, iOS/iPadOS, and Android.
- Real-time rooms, branches, messages, replies, presence, search, media, memories, and commitments.
- Tool-using LLM orchestration.
- Participation finite-state machine and silence handling.
- Scheduler and Night Shift jobs.
- TradingDesk thesis integration.
- Library and reading objects.
- Research mode.
- Claim checking.
- The Wire.
- Prediction resolution.
- Cross-room Echo.

Owner-reported verification at the design cutoff is 1,058 passing backend tests, with frontend TypeScript and Vite production builds green.

The implementation will recompose the current React PWA. It will not restart from a single-file frontend, replace the stack without cause, or rebuild working orchestration infrastructure from scratch.

## 5. The product model

### 5.1 The two spines

The Artifact spine contains durable work such as:

- Thesis models.
- Readings and source references.
- Research briefs.
- Predictions and commitments.
- Decisions.
- Working documents introduced later.
- Accepted room state.

The Deliberation spine contains inspectable reasoning around that work:

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

An artifact may be surrounded by deliberation without being rewritten by it. Deliberation may remain provisional or contested. Durable authority remains explicit.

### 5.2 The Record

The Record is the exact chronological history of what happened:

- Human contributions.
- Dialectic contributions.
- Tool activity.
- Structural inference.
- Corrections.
- Proposal creation.
- Proposal acceptance or rejection.
- Branch creation.
- Artifact changes.
- Ledger changes.
- Research completion.
- Evidence filing.

The Record remains searchable, auditable, and linkable. It is not the normal default scene.

### 5.3 The evidence metabolism

The outside world enters through one coherent cycle rather than seven disconnected features.

```text
THE WORLD
    │
    ├── The Wire
    ├── Night Shift
    ├── Research
    └── Human-provided sources
    │
THE CURRENT
    │
THE LIBRARY
    │
ARTIFACTS ↔ DELIBERATION
    │
HUMAN JUDGMENT
    │
THE LEDGER
```

The Current is not a feed of headlines. It is the stream of changes that may matter to the house’s active work.

## 6. Canonical vocabulary

The interface uses a controlled vocabulary:

```text
Home Room
House
Workroom
Bench
Field
Focus
Current
Library
Ledger
Record
Atlas
Move
Artifact
Position
Claim
Question
Tension
Definition
Evidence
Branch
Synthesis
Proposal
Provisional
Confirmed
Contested
Superseded
Judgment
```

Language must remain plain enough to use without studying a glossary. Product vocabulary may be distinctive, but it must not become theatrical jargon.

## 7. Navigation and lifecycle contract

### 7.1 Home Room is the front door

Home Room is the canonical top-level entry. There is no separate app-level dashboard competing with the workrooms.

The previously proposed global Table is absorbed into Home Room as the **House** scene.

A deliberate top-level launch with no explicit target opens:

```text
Home Room → House
```

The House scene shows cross-room movement, pending judgment, overnight work, and current activity across the relationship.

### 7.2 Exact local restoration

Session restoration is exact and device-local across macOS, Windows, iOS/iPadOS, and Android.

The contract is:

```text
New installation, browser profile, or independent window
→ Home Room → House

OS, process, browser, or installed-PWA restoration
→ Exact previous local scene

Reload of an existing window
→ Exact previous local scene

Notification or deep link
→ Exact referenced object
```

Exact scene restoration includes:

- Room.
- Branch.
- Active scene.
- Selected artifact or reasoning object.
- Inspector, focus, or workbench state.
- Field viewport.
- Scroll position.
- Open proposal or evidence review.
- Composer draft and reply target.

Transient state is reconciled rather than blindly restored. Typing indicators, socket state, expired model activity, and stale pending operations are rebuilt from current server truth.

Restoration state is not synchronized across devices. Each device and browser profile retains its own continuity. Independent macOS or Windows windows retain independent scenes when stable window identity is available; otherwise the installation’s most recent scene is used.

There is no silent cross-device takeover.

## 8. Home Room and the House scene

Home Room is a real shared workroom with its own conversation, artifacts, deliberation, Library, Ledger, and Record. It also has the privilege of seeing the state of the entire house.

The default House scene answers:

```text
What changed?
What matters?
What requires judgment?
What did Dialectic do?
What should we resume?
```

A representative composition is:

```text
HOME ROOM
Amo · Dan · Dialectic

WHILE WE WERE AWAY
3 readings filed
1 thesis challenged
2 research proposals ready
1 prediction awaiting judgment

ACTIVE ACROSS THE HOUSE
Iran / Hormuz
AI Capex
Japan Rates

NEEDS JUDGMENT
Claim check — source may misrepresent the exemption
Prediction P-18 — evidence pack ready
Research Brief R-12 — two proposed thesis changes
Echo — possible cross-room liquidity connection

CONTINUE IN HOME
Latest shared plans, ordinary discussion, and house decisions
```

This is not a notification center. Every item represents a semantic change and links directly to the affected room and object.

The House scene may group movement by:

- While we were away.
- Needs judgment.
- Active across the house.
- Overnight work.
- New evidence.
- Cross-room connections.
- Stale or unresolved work.
- Continue where we left off.

The conversation Record remains one gesture away but is never the opening center of gravity.

## 9. Room composition

A room has one dominant working surface that changes with the selected object and task.

The interface does not preserve a permanent chat center with an accumulating set of cards and drawers around it.

A room contains these scenes:

### 9.1 Bench

The Bench is the construction surface for the active artifact.

Its form depends on artifact kind:

```text
Thesis       causal model, nodes, predictions, evidence, checks
Reading      source, extraction, impact, citations, attached work
Brief        question, findings, disagreement, implications, proposals
Decision     options, evidence, objections, outcome, rationale
Commitment   claim, deadline, evidence, judgment, calibration
Document     block-level working surface when native documents arrive
```

### 9.2 Field

The Field shows the current reasoning structure around the work:

- Positions.
- Claims.
- Challenges.
- Definitions.
- Evidence.
- Tensions.
- Shared premises.
- Branches.
- Syntheses.

The Field is spatial but not freeform. It behaves like a living editorial proof rather than a node graph.

### 9.3 Focus

Selecting an object transforms the scene around it.

The Focus surface reveals:

- Current state.
- Source contributions.
- Incoming and outgoing relations.
- Questions.
- Evidence.
- Proposed changes.
- Branch variants.
- Checks.
- Revision history.
- Available actions.

The surrounding scene recedes while relevant objects move forward. Focus replaces generic persistent inspector tabs.

### 9.4 Library

The Library contains evidence retained by the house:

- Readings.
- Sources.
- Attachments.
- Research inputs.
- Cross-room evidence.
- Superseded reporting.

A Library object is not merely a bookmark. It shows where it matters and what it changed.

### 9.5 Ledger

The Ledger holds state participants have explicitly authorized the room to carry forward:

- Definitions.
- Accepted premises.
- Disputed premises.
- Decisions.
- Constraints.
- Open questions.
- Working memory.

Dialectic may propose Ledger changes. It may not silently ratify them.

### 9.6 Record

The Record is chronological speech and operation history. It preserves provenance and supports audit, search, replay, and source inspection.

### 9.7 Atlas

The Atlas presents higher-order relationships across the house:

- Rooms.
- Artifacts.
- Dependencies.
- Contradictions.
- Branches.
- Echoes.
- Open questions.
- Stale verification.
- Shared sources.

Atlas is not a decorative graph. It is a navigable projection of real relationships.

## 10. Dynamic workbenches

When the room needs a specific operation, the active scene becomes a temporary workbench rather than opening a generic modal.

Examples include:

### Contradiction workbench

```text
CLAIM C12
Reasons must be understood to constrain behavior.

CONFLICTS WITH

CLAIM C07
Accountability depends on participation in a consequence system.

Possible relation
Contradiction · Different scope · Definition conflict · No conflict
```

### Definition workbench

```text
TERM
Comprehension

Candidate meanings
Ability to represent a reason
Subjective awareness of a reason
Behavioral sensitivity to a reason

Used inconsistently in C04, C12, and C18
```

### Research workbench

```text
RESEARCHING
Gathering sources
Cross-checking claims
Tracking source disagreement
Preparing synthesis
```

### Judgment workbench

```text
PREDICTION P-18
Claim
Deadline
Evidence pack
Dialectic assessment
Human judgment
```

The user retains spatial context throughout the operation.

## 11. Workspace object projection

The existing system already contains real durable object types. The first implementation should not force them into a premature generic artifact database.

A common frontend projection will unify them:

```text
WorkspaceObject

id
kind
room_id
title
summary
status
created_at
updated_at
provenance
relationships
available_actions
source_entity
```

Adapters project existing entities into this contract:

```text
Reading           → Reference object
Research result   → Brief object
Thesis book       → Structured model object
Prediction        → Commitment object
Accepted proposal → Decision or state transition
Memory            → Ledger entry
Message           → Record event
```

This creates one coherent object language without migrating working systems into an abstract universal schema before native collaborative editing requires it.

A native artifact/version/block model should be introduced only when collaboratively editable working documents or diagrams create a concrete need for concurrency, lineage, and merge semantics.

## 12. Deliberation and inference model

Dialectic continuously derives useful structure but does not pretend inference is fact.

Every inferred object has three independent dimensions:

```text
ORIGIN
explicit | inferred

REVIEW
provisional | confirmed | contested | superseded

DELIBERATIVE STATUS
active | accepted | rejected | resolved | withdrawn
```

This distinction prevents “confirmed claim” from being interpreted as “true claim.” Confirmation means the room accepted the representation, not the proposition’s truth.

### 12.1 Low-risk automatic structure

Dialectic may place these into the Field immediately as provisional:

- Contribution type.
- Claim grouping.
- Support or challenge relation.
- Repeated definition.
- Possible contradiction.
- Emerging position.
- Evidence attachment.
- Branch candidate.
- Unanswered question.
- Candidate synthesis.

### 12.2 Human-ratified authority

These require explicit human judgment:

- Accepted premise.
- Declared consensus.
- Decision.
- Resolved tension.
- Final definition.
- Branch merge.
- Rejection of a position.
- Ledger change.
- Memory invalidation.
- Claim that a participant changed position.

### 12.3 Corrections

Corrections are first-class actions:

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

## 13. Dialectic’s visible role

Dialectic is a participant with visible agency, not a typing animation and not a purple assistant bubble.

It can:

- Speak.
- Ask.
- Challenge.
- Synthesize.
- Propose a branch.
- Propose a Ledger change.
- Attach evidence provisionally.
- Create an open question.
- Propose an artifact change.
- Remain silent.

Its activity is expressed through the workspace channel that best fits the work.

A Builder action becomes a proposed artifact change. A Critic action becomes a question, contradiction, or failed check. An Archivist action becomes a missing-decision or missing-rationale proposal. An Integrator action becomes a cross-artifact or branch relationship. A Provoker action becomes a targeted challenge attached to the relevant object.

These are working modes of Dialectic, not multiple chat personas.

Agent-created actions do not recursively trigger uncontrolled agent activity. New autonomous work requires a human-originated operation, explicit request, or scheduled review boundary.

## 14. Integration of the seven shipped phases

### 14.1 Library

`reading_items` is treated as the first native evidence artifact surface.

A reading shows:

- Source and filing time.
- Retrieval provenance.
- Distillation against the live thesis or room purpose.
- Thesis impact.
- Supporting and challenging relationships.
- Use by briefs, claims, predictions, and decisions.
- Human reading or discussion state.

The `reading:<domain>-<slug>` memory twin remains an internal compatibility bridge. The interface deduplicates the reading and its memory twin into one visible object.

### 14.2 Night Shift

The 05:30 digest and 07:00 brief produce structured overnight movement in Home Room and relevant source rooms.

A Night Shift result separates:

- Read.
- Changed.
- Unchanged.
- Opened.
- Proposed.

The persisted conversational turn remains in the Record, but the reusable result is a Morning or Research Brief object.

### 14.3 Claim Check

Only material warnings interrupt the normal scene.

The internal state remains inspectable:

```text
not_checked
checking
supported
mixed
misrepresented
unavailable
```

Silence never implies successful verification. Failure may remain quiet in the room but must remain visible in diagnostics and provenance.

### 14.4 The Wire

The Wire is room movement, not headline chatter.

A Wire intervention states:

- What arrived.
- Which artifact or assumption it affects.
- Why Dialectic interrupted.
- Which actions are available.

Relevance scores remain routing machinery. The user sees the reason the evidence matters, not an unexplained decimal.

### 14.5 Research mode

Research mode is rendered as a live Research workbench.

Observable stages may show gathering, cross-checking, disagreement tracking, and synthesis preparation. The interface does not expose hidden chain-of-thought.

The result becomes a first-class Research Brief with:

- Question.
- Findings.
- Source agreement.
- Material disagreement.
- Implications.
- Proposed changes.
- Provenance.

The streaming message remains the Record announcement, not the only durable output.

### 14.6 Prediction resolution

Predictions become first-class Commitment objects.

The resolution surface contains:

- Claim.
- Deadline.
- Evidence pack.
- Ambiguities.
- Dialectic assessment.
- Human judgment.

Human judgment remains authoritative. Supported resolution states include correct, incorrect, partial, and voided or indeterminate when binary resolution would corrupt calibration.

### 14.7 Echo

Echo creates a visible cross-room relationship.

It shows:

- Source room.
- Target room or artifact.
- Shared concept or assumption.
- Why the connection matters.
- Attach, inspect, or dismiss actions.

Echo remains visible and attributable. It never becomes a silent cross-room memory injection.

## 15. Visual identity

### 15.1 Product mark

The recommended mark is formed from two opposing arcs:

```text
)(
```

It suggests opposition, a doorway, a fulcrum, parentheses around an unresolved proposition, and two positions producing movement.

At larger sizes it may subtly express state:

```text
Opening     (   )
Contested   )(
Converging  ( )
Integrated  ()
```

The mark remains restrained and state-bearing. It is not a looping logo animation.

### 15.2 Color system

The canonical palette is material rather than neon:

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
- Oxidized copper: incorporated or confirmed structure.
- Oxblood: genuine conflict, rejection, or invalid state.
- Broken lines and reduced opacity: provisional structure.
- Carbon, bone, and ash: ordinary working state.

Color does not assign cartoon identities to participants.

### 15.3 Typography

Dialectic uses three typographic voices:

- Propositional serif for central questions, major positions, synthesis statements, and selected propositions.
- Operational grotesk for controls, names, navigation, actions, room state, and ordinary contributions.
- Provenance mono for identifiers, timestamps, source chains, branch coordinates, and technical metadata.

The serif appears where language itself becomes the object of attention. It is not used as a decorative skin over every screen.

### 15.4 Spatial grammar

Objects communicate meaning through placement:

- Questions orient the field.
- Positions form stable territories.
- Claims nest within positions.
- Evidence attaches to claims.
- Counterexamples cut across affected propositions.
- Tensions occupy the seam between conflicting objects.
- Definitions sit near the terms they govern.
- Branches unfold from their exact source.
- Syntheses temporarily gather their source objects.

Most objects are not enclosed in rounded cards. Typography, spacing, rules, relation paths, and focus create structure.

## 16. Motion language

Motion explains causality.

Allowed motion:

- A provisional claim emerges from its source move.
- A support relation draws toward its target.
- A challenge applies pressure to a proposition.
- A definition splits when incompatible meanings appear.
- Related objects gather into a position.
- A correction detaches and reattaches an inference.
- A synthesis gathers its sources.
- A confirmed premise settles into the Ledger.
- A branch unfolds from its originating object.

Disallowed motion:

- Ambient particles.
- Floating gradients.
- Decorative parallax.
- Glowing AI pulses.
- Constant card hover movement.
- Fake thinking theatrics.
- Full-field rearrangement after every message.

Animations are brief, interruptible, and driven by real state changes. Reduced-motion mode preserves all meaning through static transitions and annotation.

## 17. Platform behavior

Dialectic is one responsive PWA product across macOS, Windows, iOS/iPadOS, and Android.

### 17.1 Desktop and large tablet landscape

The dominant scene receives most of the viewport. Workroom navigation is narrow and collapsible. Context appears through Focus or a contextual edge panel rather than permanent generic tabs.

Multiple desktop windows may hold different local scenes.

### 17.2 Tablet portrait

The active scene remains primary. House navigation, Atlas, Library, and Focus open as persistent side sheets or transformed scene layers.

### 17.3 Phone

One major surface is visible at a time. Selection opens Focus as a bottom sheet or full scene. The composer remains usable. No essential operation depends on hover.

### 17.4 Input parity

The product supports:

- Pointer and keyboard.
- Touch.
- Trackpad.
- Installed PWA and browser use.
- Desktop window resizing.
- OS process eviction and restoration.

Representative shortcuts:

```text
Enter          submit
Shift+Enter    newline
Cmd/Ctrl+K     search or command palette
Cmd/Ctrl+/     focus composer
Escape         exit focus or close operation layer
```

Shortcuts supplement rather than replace discoverable controls.

## 18. Accessibility

The primary scene uses semantic DOM elements. SVG is limited to relation paths, tension seams, branch paths, and transition guides.

The product does not use canvas as the primary reading or editing substrate.

Requirements include:

- Selectable and addressable text.
- Keyboard navigation.
- Screen-reader-readable object type, state, and relation summaries.
- Visible focus states.
- Sufficient contrast.
- Reduced-motion support.
- No color-only meaning.
- No hover-only operation.
- Stable deep links to objects and source events.

## 19. Frontend implementation boundary

The implementation recomposes the existing React and TypeScript PWA.

It should introduce:

- Scene routing and restoration state.
- House scene inside Home Room.
- WorkspaceObject adapters.
- Context-driven Focus.
- Artifact and evidence scenes.
- Field layout primitives.
- Semantic relation rendering with SVG.
- Revision-aware deep links.
- Local device and window restoration keys.

It should preserve working backend behavior and current capabilities unless a product requirement makes a targeted backend extension necessary.

The design does not require a framework rewrite, a native application, a freeform graph engine, or a universal artifact database in its first implementation.

## 20. Hard prohibitions

The final interface must not fall back to:

- Chat bubbles.
- Left-versus-right message alignment as the primary grammar.
- Conversation as the default opening surface.
- Persistent generic tab sidebars.
- Rounded-card infestation.
- Purple AI branding.
- Sparkle or robot iconography.
- Bright participant color coding.
- Decorative gradients.
- Freeform graph chaos.
- Hidden automatic structural edits.
- Provider names in primary product controls.
- A separate dashboard front door outside Home Room.
- Cross-device scene synchronization without explicit user action.

## 21. Non-goals for the first implementation

The first implementation does not include:

- Branch merging.
- Freeform user-positioned graph layouts.
- Cross-room ontologies.
- Autonomous consensus or resolution.
- External action without human proposal approval.
- Citation verification beyond the shipped claim-check behavior.
- Multi-agent swarms presented as separate personas.
- Argument scoring or debate winners.
- Public social profiles.
- Plugin marketplace.
- Native mobile or desktop applications.
- Generic collaborative code editing.
- CRDT-based text editing.

## 22. Acceptance criteria

The design is successful only when all of the following are true.

### Identity

- A grayscale screenshot remains recognizable as Dialectic without the wordmark.
- A room with only human-authored work still looks like Dialectic.
- No primary screen resembles a conventional chat application.
- DwoodAmo appears as an origin imprint, not a competing brand.

### Home and lifecycle

- A new installation opens Home Room’s House scene.
- Restoration returns to the exact local scene on macOS, Windows, iOS/iPadOS, and Android.
- Different devices maintain independent restoration state.
- A deep link opens the exact referenced object.
- A process-restored scene reconciles stale transient state.

### Evidence metabolism

- Night Shift work appears as structured house or room movement.
- A reading reveals its thesis or room impact within two actions.
- A claim-check warning opens complete provenance without implying silent failures passed.
- A Wire item identifies the affected object and why it matters.
- Research produces a reusable Brief object rather than only a long message.
- A prediction opens a dedicated Judgment surface.
- An Echo preserves source-room lineage and target-room relevance.

### Dual spine

- Every durable artifact can reveal the reasoning and evidence around it.
- Every deliberative object can reveal its source contributions.
- Conversation remains available in the Record without being the default center.
- Dialectic’s inferred structure is visibly provisional until confirmed.
- High-consequence state requires explicit human judgment.

### Dynamic interface

- Selection transforms the active scene rather than merely opening a static sidebar.
- Motion explains a real state transition.
- The room remains spatially stable during ordinary activity.
- No essential operation depends on hover.

### Accessibility and performance

- Semantic content remains keyboard and screen-reader accessible.
- Reduced-motion mode retains all meaning.
- The layout works from phone width through large desktop windows.
- Evidence, Record, and Focus views remain usable with long-lived rooms.

## 23. Final governing rule

> **Language enters as movement. Evidence acquires consequence. Structure emerges provisionally. Humans give durable state its authority. Artifacts preserve the work. The Record preserves what happened. Home Room shows the state of the whole house.**
