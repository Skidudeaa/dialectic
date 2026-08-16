# Dialectic human-interaction surface audit

**Date:** 2026-08-13
**Scope:** every place where a human currently interacts with Dialectic, where
the current system exposes a capability without a human surface, and where the
approved product direction requires a new surface.
**Evidence:** current checkout, the Draw.io architecture source, frontend call
sites, backend routes, realtime events, current product specification, current
Release 3 plan, and operator runbooks. This is a code-grounded audit, not a
production browser certification.

## 2026-08-16 local stabilization amendment

The big-bang stabilization branch repairs the findings below **locally**. None
of these status changes is a deployment claim: production migrations, service
restarts, frontend activation, served-asset checks, and real-device proof remain
pending a separately authorized activation.

| Audit surface / contract | Local status | What changed | Still pending |
|---|---|---|---|
| A06–A07 recovery truth | IMPLEMENTED LOCALLY | Forgot-password creates no unreachable credential and returns the same honest unavailable response for known and unknown accounts; reset failures no longer disclose account state. | Real email delivery and a complete recovery UI. |
| A13–A15 room authority | IMPLEMENTED LOCALLY | Room creation requires bearer auth; generic join retains its compatible body but binds it to the bearer; user-model reads are self-only. | Production activation and the broader invitation/membership lifecycle. |
| R04, R07, R11, R19 message truth | IMPLEMENTED LOCALLY | Reload retains reply/edit fields; REST send now shares room fencing, transaction, bounded sequence retry, persisted payload, and post-commit fanout semantics with WebSocket delivery; unread counts include null-authored Dialectic rows and exclude stored lowercase system rows. | Production and multi-device observation. |
| R21–R22 attachment reuse | IMPLEMENTED LOCALLY | Content-addressed files stay deduplicated, but an attachment row is reused only for the same uploader while unbound. | Product-level file trust/scan metadata remains open. |
| D10 durable acceptance | IMPLEMENTED LOCALLY | Prediction, resolution, reading, and thesis relays use leased operation keys, release PostgreSQL during external waits, replay success, preserve the initiating human, and finalize local acceptance atomically. tradingDesk prediction writes and room-bound theses are independently idempotent. | Production migrations 018/006 and activation proof. |
| N05–N06, N08–N10, P01, X08–X09 shell/accessibility | IMPLEMENTED LOCALLY | Below 1280px both rails are independent overlays; desktop context is explicit; duplicate Users is removed; tabs expose active semantics; all seven scenes remain reachable through primary/overflow navigation; safe areas, 44px targets, 12px control type, and contrast pass at five widths. | Hardware iPad/phone, keyboard, and screen-reader proof. |
| R04 ancestry history | IMPLEMENTED LOCALLY | Cross-thread ancestry uses strict opaque time-plus-ID cursors and a bounded recursive SQL window; incompatible sequence cursors fail instead of returning a false page. | Production query observation at real history volume. |
| O04 startup truth | IMPLEMENTED LOCALLY | PostgreSQL pool creation failure aborts startup; the supported Redis in-memory fallback remains separate. | Runtime restart/health proof after authorization. |
| O07 tracked service authority | IMPLEMENTED LOCALLY | The tracked unit now matches the installed non-secret working-tree structure. | No unit was installed or reloaded. |

## Executive finding

Dialectic does not have one UI. It currently has four human-interaction
environments:

1. The primary React PWA at `dialectic/frontend/app/`.
2. The separate tradingDesk SPA at `trading/frontend/`, which itself has a
   Field Desk, a classic desk, a thesis builder, and a welcome/onboarding site.
3. Browser and operating-system surfaces: installation, notification
   permission, push notifications, deep links, file pickers, clipboard,
   downloads, media playback, URL/history, and responsive layouts.
4. Operator-only surfaces: SQL scripts, environment flags, service control,
   logs, migrations, password rotation, alert configuration, and generated HTML
   dashboards.

The largest UI problem is therefore not a shortage of components. It is the
absence of one authoritative product topology. The primary PWA is moving toward
a living workroom, while tradingDesk still presents a second product identity
and a second chat/room system. Several important capabilities exist only as API
routes, several visible controls are incomplete, and the path from conversation
to durable human judgment is only half surfaced.

The strongest existing product grammar is already in the approved design:

> Dialectic can prepare the move. A human makes it real.

The world-class UI should make that contract visible everywhere: machine
inference is provisional, human acceptance is explicit, evidence remains
inspectable, destructive acts are deliberate, and every durable artifact has a
stable place and provenance.

## Status legend

| Status | Meaning |
|---|---|
| **CURRENT** | Reachable and wired in the frontend at current HEAD. It is not a claim that this audit browser-tested production. |
| **IN PROGRESS** | Present only in the dirty worktree or only partly wired; not a complete human surface. |
| **BACKEND ONLY** | API, persistence, or event support exists, but no reachable first-party UI completes the human workflow. |
| **TARGET** | Approved in the current identity specification or Release 3 plan, but not implemented at HEAD. |
| **EXTERNAL** | The human interacts through the browser, OS, TradingView, or another product-owned boundary outside the React DOM. |
| **OPERATOR** | Requires shell, SQL, environment, log, or deployment access. It is not an end-user UI. |
| **DUPLICATE** | A second implementation overlaps a canonical Dialectic interaction. |
| **RETIRED / NON-PRODUCT** | Historical, frozen, unconnected, generated, or deliberately excluded from the active UI. |

## System boundary from the Draw.io architecture

The architecture artifact is
`docs/diagrams/dialectic-architecture.drawio`; its PNG/SVG exports are views,
not the source of truth.

```text
Human
├── Dialectic PWA — dialectic.somacura.org
│   ├── access and rooms
│   ├── Home / House
│   ├── room workspaces and Record
│   ├── collaboration, AI, evidence, judgment
│   └── browser / PWA / notification surfaces
├── tradingDesk SPA — td.somacura.org
│   ├── bridged or standalone access
│   ├── Field Desk dossier
│   ├── classic multi-panel desk
│   ├── thesis builder
│   └── welcome, onboarding, shortcuts, command surfaces
├── External human surfaces
│   ├── OS/browser notification and install UI
│   ├── email — required, not implemented
│   ├── TradingView alert editor and Pine setup
│   └── file system, clipboard, media viewer, downloads
└── Operator surfaces
    ├── systemd, nginx, logs, health, feature flags
    ├── Postgres migrations and reviewed membership SQL
    ├── account/password bootstrap
    ├── scheduler and bridge operations
    └── generated thesis HTML dashboards
```

Machine-only boxes in the diagram—FastAPI routers, Postgres, scheduler,
workspace projection, memory, LLM participant, Defuddle, Anthropic, market
providers, and the bridge—are not human surfaces. They need human-readable
status, provenance, errors, and controls in the surfaces above. `cc-sidecar` is
unconnected lineage, and `packages/` is frozen rather than production UI.

## Human actors

| Actor | Current authority and needs |
|---|---|
| Visitor | Understand the product, sign in, learn why signup/guest access is unavailable, recover access. |
| Invited account holder | Authenticate, enter Home or a room, understand invitation state, complete setup. |
| Room member | Converse, branch, search, attach evidence, invoke protocols/research, make and accept proposals, inspect artifacts. |
| Home member | See house-wide movement and pending work, enter shared rooms, distinguish residents from people merely online. |
| Home founder/manager | Add a confirmed existing account and understand the effect on the membership-intersection House. |
| Offline/returning member | Receive a trustworthy alert, deep-link to the exact object, recover context, and control notification behavior. |
| Trading analyst | Inspect and edit thesis structures, operate predictions/trades/webhooks, understand data freshness, and return to the originating Dialectic room. |
| Owner/operator | Provision and recover people, remove Home members, deploy safely, inspect health/logs/jobs, and repair queues without mutating production accidentally. |
| Assistive-technology and keyboard user | Reach every action, perceive every state without color/hover/motion, retain focus and context across overlays and responsive modes. |

AI participants, schedulers, and providers are not human actors. Their output
creates human interaction obligations: attribution, progress, provenance,
failure, cancellation, review, and authority boundaries.

## Surface register: access, identity, and membership

### A. Primary PWA access

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| A01 | Product front door | Reads the Dialectic premise and chooses an access path. | CURRENT | Keep one unmistakable product identity and add an invitation/recovery explanation rather than exposing internal capability switches. |
| A02 | Sign in | Email/password, validation, loading, API error, successful session creation. | CURRENT | Preserve autofill/password-manager semantics; add recovery and account-state help. |
| A03 | Create Account tab | Form is available only when `/auth/capabilities` says signup is open; otherwise explains invite-only status. | CURRENT, gated off | This is not an invitation flow. A world-class closed product needs an invite acceptance or owner-provisioned setup journey. |
| A04 | Guest / Invite tab | Guest identity and invite entry only appear when guest capability is enabled. | CURRENT code, capability off | Keep hidden while disabled. Do not imply guest access when workroom projections require JWT. |
| A05 | Email verification | Backend accepts a six-digit verification code. | BACKEND ONLY | No verification UI and no email delivery. Define entry, resend, expiry, wrong-code, already-used, and change-email states before enforcing verification. |
| A06 | Forgot password | Backend creates a reset code and returns a success-shaped response. | BACKEND ONLY | No UI and no email delivery; the API currently says a code was sent when delivery is explicitly absent. This is a broken human contract. |
| A07 | Reset password | Backend accepts email, code, and new password, revokes sessions, then auto-signs in. | BACKEND ONLY | Needs code entry, password rules, expiry, retry, revoked-session explanation, and delivery infrastructure. |
| A08 | Session refresh | Silent access-token refresh and current-user bootstrap. | CURRENT | Surface only terminal failures; avoid disorienting full-screen resets during transient refresh. |
| A09 | Session-ended reason | Sign-in screen can explain password-reset or session-eviction logout. | CURRENT | Expand to expired, revoked, insufficient access, and offline distinctions without leaking security detail. |
| A10 | Sign out | Revokes refresh token when possible, clears local state, returns to auth. | CURRENT | Confirm exactly which device-local drafts, scene continuity, room secrets, and notification subscriptions are forgotten. |
| A11 | No-room recovery | Full-screen room selector when no Home or usable room is available. | CURRENT | Explain whether the cause is no membership, revoked access, unavailable server, or stale local room data. |
| A12 | Saved room selection | Opens a known room from the recovery screen or rail. | CURRENT | Show membership/access state separately from presence and retain actionable errors. |
| A13 | Create room | Names a room, creates it, joins it, installs navigation state. | CURRENT | Add ownership/lifecycle expectations; creation API authorization is a separate security concern and must not be inferred from the UI. |
| A14 | Join by invite code | Pastes `dialectic-v1:room-id:token`. | CURRENT | A link/QR form would reduce secret handling and parsing error; invitation should preview destination without leaking unauthorized content. |
| A15 | Manual join | Pastes room ID and secret token separately. | CURRENT | Keep as an advanced recovery path, not the primary invitation UX. |
| A16 | Room share | Copies combined invite code or separate room ID/token. | CURRENT | Mark the token as a secret, show who can use it, provide revocation/rotation, and avoid accidental exposure in screen sharing. |
| A17 | Room list `+` | Opens the same create/join surface as no-room recovery. | CURRENT | Reuse is correct; retain one acquisition flow. |
| A18 | Home member candidate lookup | Founder enters email, receives matched display name, confirms addition. | CURRENT | Good two-step pattern; explain how adding a member changes House visibility through the all-members intersection. |
| A19 | Home member removal | Reviewed SQL script removes membership. | OPERATOR | Needs a deliberate founder/admin UI if this becomes routine; include consequences, confirmation, audit trail, and recovery. |
| A20 | Home resident roster | Home settings and House derive “residents” from online presence. | CURRENT but semantically incomplete | Offline members can disappear from a membership concept. Separate **members** from **currently here**. |
| A21 | Room roster and roles | Users panel shows presence. | CURRENT but incomplete | Needs durable membership, invitation status, roles, who can share/manage, and offline members. Presence is not authorization. |
| A22 | Room lifecycle | Rename, archive/delete, leave, remove member, rotate invite, transfer stewardship. | NEEDS SURFACE | These actions are absent from the primary PWA even though room creation/sharing establishes a lifecycle. |
| A23 | Profile/account settings | Display name, email state, password, sessions/devices, accessibility preferences. | NEEDS SURFACE | Current room settings are AI-participant settings, not personal/account settings. |
| A24 | Role and permission explanation | Founder, member, guest, room member, Home manager, trading analyst. | NEEDS SURFACE | Controls should be hidden or disabled with a precise reason; do not make users discover roles through 403 responses. |

### B. tradingDesk access

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| A25 | Dialectic-to-desk bridge | “Open Full Dashboard” passes a short-lived access token in the URL fragment plus room context; desk exchanges it. | CURRENT | Preserve one-tap access, remove the fragment immediately, show originating room/book, provide a return path, and explain failed/expired exchange. |
| A26 | Standalone tradingDesk login | Username/password, password reveal, loading, invalid-credentials error. | CURRENT | It advertises hardcoded two-analyst dev accounts and has no recovery. It should be an operator fallback, not a competing normal login. |
| A27 | tradingDesk logout | Clears its local auth and returns to root. | CURRENT | A bridged user needs a clear distinction between leaving the desk and signing out of Dialectic everywhere. |
| A28 | tradingDesk password rotation | Edit server environment and restart service. | OPERATOR | No human self-service or session/device view. Consolidate identity under Dialectic before expanding access. |

## Surface register: global shell, navigation, and continuity

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| N01 | URL/deep-link destination | Room, branch, and scene are query-string axes; Home root canonicalizes to `/`. | CURRENT | Object selection is not yet an axis. Every notification/search/artifact link needs one canonical destination writer. |
| N02 | Browser Back/Forward | `pushState`, `replaceState`, and `popstate` navigate without separate route ownership. | CURRENT | Extend rather than duplicate for object/Focus state; preserve history-neutral restoration. |
| N03 | Device-local restoration | Restores last room, branch, scene, and some rail state per window/device. | CURRENT foundation | TARGET v2 includes selected object, Focus/workbench, inspector tab, Field viewport, Record scroll, proposal/evidence review, composer draft, and reply. |
| N04 | Room rail | Lists Home and rooms, selects destination, opens room acquisition. | CURRENT | Add unread/pending semantics without turning it into a dashboard; distinguish membership/access errors from empty rooms. |
| N05 | Mobile room drawer | Opens the left rail at narrow widths. | CURRENT | Needs focus trapping, accessible close/return focus, gesture-safe scrolling, and state retention. |
| N06 | Room header | Room/Home identity, branch select, protocol, search, settings, help, connection, responsive drawers. | CURRENT | Reduce control crowding through task hierarchy; current header has already exhibited width starvation. |
| N07 | Branch selector | Changes the active thread inside a room. | CURRENT | Show ancestry/context, not only a title, and make current branch unambiguous on mobile. |
| N08 | Scene switcher | Home root: House/Record. Ordinary room: Record/Bench/Library/Ledger. Home branch: Record only. | CURRENT | Field and Atlas will change the set. Focus must remain selected-object state, not a permanent tab. |
| N09 | Right-panel navigation | Scene-dependent tabs expose supporting tools. | CURRENT | It is a second navigation system. Each tool needs a declared home: scene body, Focus inspector, global utility, or settings. |
| N10 | Mobile cockpit drawer | Opens the right panel at narrow widths. | CURRENT | Same overlay/accessibility obligations as the room drawer; selected tool must remain legible. |
| N11 | Global search shortcut | Cmd/Ctrl+K opens current-room message search. | CURRENT | Label its scope. Backend cross-session memory search is a different, unsurfaced capability. |
| N12 | Connection status | Header and Record show connected/offline/reconnecting consequences. | CURRENT | Standardize online, stale, reconnecting, offline-readable, offline-write-queued, and failed states. |
| N13 | Access/navigation errors | Full-screen or inline errors appear during room resolution. | CURRENT | Errors must survive corrective navigation long enough to be understood and acted on. |

## Surface register: Home and House

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| H01 | Home default landing | Bare `/` opens or restores Home when membership exists. | CURRENT | Keep Home as canonical entry; do not add another app-level dashboard. |
| H02 | House resident line | Shows Dialectic plus present humans and status. | CURRENT | Rename/present as presence; add a separate actual membership roster. |
| H03 | Needs you | Due commitments, unresolved questions, and unread work link into rooms/branches. | CURRENT | Become the product’s human-action inbox; add proposal reviews, contested Field marks, research decisions, failed jobs, and expiring judgments. |
| H04 | House movement | Cross-room activity with source room, actor, time, and navigation. | CURRENT | Preserve membership-intersection privacy and explicit stale/unavailable states. |
| H05 | Scheme doors | Lists shared rooms and enters them. | CURRENT | Explain why some of a person’s rooms are not household-shared rather than silently omitting context. |
| H06 | Stale House snapshot | Retains last good data and offers Retry when refresh fails. | CURRENT | This is the correct stale-data model; reuse it across projections. |
| H07 | Home Record | House pulse followed by the normal conversation Record. | CURRENT | Keep House as the default mental model; avoid visually demoting it beneath chat. |
| H08 | Home settings | Household presence, held facts, and founder membership add flow. | CURRENT | Split membership, presence, shared-memory policy, and personal settings into named domains. |
| H09 | Atlas | Cross-room rooms, branches, artifacts, Echoes, shared sources, unresolved work. | TARGET | Personal authorization per viewer; list/tree must be complete before optional spatial rendering. Every node must use canonical navigation/Focus. |
| H10 | House-wide current/night work | Overnight jobs, Wire/reading movement, and pending review are partly summarized by House/help. | PARTIAL / TARGET | Present completed, running, disabled, stale, failed, and human-decision-required states without exposing scheduler jargon. |

## Surface register: Record and direct collaboration

### Composition and conversation

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| R01 | Room briefing | Reads current room context before messages. | CURRENT | Explain provenance/time and unavailable state; do not silently substitute old context. |
| R02 | Protocol banner | Sees active deliberation mode and phase. | CURRENT | Keep protocol state distinct from normal conversation and from AI “thinking.” |
| R03 | Commitment surfaced in Record | Sees a current commitment callout. | CURRENT when data exists | Link to the canonical judgment/commitment object and show owner/deadline/status. |
| R04 | Message list | Reads paginated human, Dialectic, system, proposal, annotation, and research contributions. | CURRENT | Target design removes chat bubbles/left-right alignment in favor of full-width contribution rows and restrained signatures. |
| R05 | Message types | Human chooses text, claim, question, or definition; Home hides types. | CURRENT | Preserve semantics in accessible labels and downstream structure; clarify why Home differs. |
| R06 | Composer | Drafts, sends with Enter, inserts newline with Shift+Enter, reports delivery error. | CURRENT | Add persistent draft/reply restoration and proposal composition without crowding the primary act of writing. |
| R07 | Reply | Selects a parent, sees quoted context, cancels, sends linked reply. | CURRENT | Restore drafts/replies locally and validate the parent still exists after reload. |
| R08 | Fork from message | Names a branch through a prompt and creates it from a contribution. | CURRENT | Replace browser prompt with a context-rich lightweight surface; explain branch inheritance and resulting destination. |
| R09 | Branch genealogy | Opens branch list/tree, moves between branch lineage, retries loading. | CURRENT | Merge duplicate branch selectors/panels around one ancestry model. |
| R10 | Search | Filters room history, shows branch, opens exact message context, supports keyboard shortcut. | CURRENT | Search result should explain scope and preserve return position. |
| R11 | Unread boundary | Sees first unread divider and jumps to latest. | CURRENT | Keep read truth tied to visibility/following tail; add “return to where I was” when jumping. |
| R12 | Reactions | Adds/removes a quick-set reaction. | CURRENT | If reactions become judgment signals, distinguish lightweight acknowledgment from durable acceptance. |
| R13 | Edit own message | Enters edit mode and saves/cancels. | CURRENT | Show edit history or edited state where intellectual provenance matters. |
| R14 | Delete own message | Confirms deletion. | CURRENT | Explain whether replies, artifacts, citations, or accepted proposals remain and how tombstones appear. |
| R15 | Markdown and links | Reads formatted content and follows safe links. | CURRENT | Maintain sanitized rendering, external-link affordance, keyboard access, and readable provenance. |
| R16 | Long-content folding | Expands/collapses long messages and annotations. | CURRENT | Preserve search/deep-link target visibility and screen-reader announcement. |
| R17 | Participant bar/presence | Sees who is present and human/agent typing. | CURRENT | Presence is ephemeral; never reuse it as membership or authority. |
| R18 | Typing indicator | Sees human or Dialectic activity. | CURRENT | Avoid ambient “thinking theater”; report only meaningful causal progress. |
| R19 | Delivery/stream errors | Inline composer error, message failure, or websocket error. | PARTIAL | Several paths still log or disappear. Every failed human action needs retained input, cause, retry, and non-duplication semantics. |

### Attachments and evidence entry

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| R20 | File picker | Selects image, video, or file. | CURRENT + EXTERNAL | State size/type limits before selection; preserve privacy and cancellation. |
| R21 | Paste/drop upload | Pastes or drags evidence into the composer. | CURRENT | Show drop target, upload ownership, security constraints, and duplicate handling. |
| R22 | Upload queue | Sees progress, failure, Retry, and Remove; can send attachment-only messages. | CURRENT | Prevent send while required uploads are unresolved and distinguish retryable from rejected. |
| R23 | Authenticated image | Lazy-loads protected media, retries, opens image. | CURRENT | Provide alt/description workflow and explicit access-expired state. |
| R24 | Protected video | Tap-to-load playback with retry. | CURRENT + EXTERNAL media controls | Include captions/transcript path and do not autoplay sensitive material. |
| R25 | File download | Opens/downloads protected attachment and surfaces failure. | CURRENT + EXTERNAL | Show file identity, size, type, source, scan/trust state, and expiry before download. |
| R26 | Reading/evidence promotion | Machine or proposal flow can create a durable reading from a normal message. | CURRENT acceptance path, incomplete creation UX | Human needs a first-class “file as evidence/reading” move with source metadata, preview, duplicates, and acceptance. |

## Surface register: Dialectic participation, protocols, and trust

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| D01 | Dialectic identity in Record | Reads a unified participant name rather than provider branding. | CURRENT | Extend de-provider identity to all primary controls; retain model/provider only in provenance and diagnostics. |
| D02 | Room behavior settings | Toggles auto-participation, turn threshold, and topic-shift sensitivity. | CURRENT | Explain effect, scope, owner, current server value, and whether the setting is disabled by capability. |
| D03 | Active inference stream | Sees meaningful response streaming and completion. | CURRENT | Preserve cancel/failure boundaries and never confuse partial text with durable artifact state. |
| D04 | Tool activity | Sees transient activity and expands completed calls, latency, provenance, and errors. | CURRENT | Keep durable trace available from the resulting contribution/object; avoid exposing raw implementation noise by default. |
| D05 | Protocol picker | Chooses Steelman, Socratic, Devil’s Advocate, or Synthesis; enters claim. | CURRENT | Explain expected phases, participant authority, exit, and impact before invoking. |
| D06 | Protocol operation | Advances phase, concludes, dismisses, or aborts. | CURRENT | Use consistent destructive/terminal-state language and retain a protocol record. |
| D07 | Deep Research | Sends a text question, watches a single long-running job, receives result as a message. | CURRENT | The research question is not durably persisted at HEAD; create a dedicated Brief object/surface with sources, progress, cancellation, timeout, partial results, and retry. |
| D08 | Claim check | Sees mixed/misrepresented verdict badge when present. | CURRENT but narrow | Needs a full evidence/provenance review, unavailable state, scope, and explanation of what was checked. |
| D09 | Proposal cards | Reads prediction, thesis, reading, commitment, and resolution proposals embedded in messages. | CURRENT for machine-authored proposals | Standardize one proposal envelope and show proposer, payload, evidence, consequences, status, expiry, and accepting human. |
| D10 | Accept proposal | Accepts a prediction/reading/commitment or thesis cascade into durable state. | CURRENT | Every accept must be idempotent, attributable, reviewable, and linked to the resulting object. |
| D11 | Resolve prediction proposal | Marks correct/incorrect through the proposal flow. | CURRENT | Separate factual resolution, scoring, disagreement, and correction; avoid irreversible one-tap ambiguity. |
| D12 | Human proposal composition | “Make a move” for prediction, thesis, reading, or commitment. | TARGET | This is the missing half of human authority. It should create a normal message with validated proposal metadata and work at phone width. |
| D13 | Proposal inbox/review | Finds pending, contested, failed, expired, dismissed, and accepted proposals across context. | NEEDS SURFACE | Proposal cards inside a transcript are insufficient once proposals become a product-wide human queue. |
| D14 | Annotation | Receives machine annotations/claim checks on contributions. | CURRENT | Provide explicit relationship to source message and a path to contest/correct. |
| D15 | Persona management | Create/edit/delete room personas. | BACKEND ONLY, deliberately deferred | Keep out unless the product chooses human-managed multiple AI identities; otherwise retire endpoints rather than accidentally exposing provider configuration. |

## Surface register: durable workroom scenes and objects

### Current scenes

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| W01 | Record | Conversation, reasoning trace, protocols, and current work. | CURRENT | Treat as one spine of the workroom, not the whole product. |
| W02 | Bench | Full thesis lifecycle panel: create/draft/review, bind, inspect snapshot, open specialist desk, retire. | CURRENT | The current 700+ line panel is functional but dense; split creation, current thesis, and specialist handoff into clear modes without breaking lifecycle behavior. |
| W03 | Thesis draft review | Reviews generated title/claim/budget, DAG nodes/edges/rationale; accepts or discards. | CURRENT | Show source/proposal, validation, what will be created, and whether dismissal is durable. |
| W04 | Thesis creation result | Sees success and opens Builder. | CURRENT | Link back to room and resulting object; retain failed draft and input for retry. |
| W05 | Current thesis summary | Staleness, phase, active nodes, countdowns, confluence, scenarios, portfolio. | CURRENT | Make source freshness and server time first-class; never imply live data from decoration. |
| W06 | Unbound thesis | Explains bound-but-undrawn state and points to Builder. | CURRENT | Clarify whether the user is leaving Dialectic and preserve return context. |
| W07 | Thesis retirement | Double-confirms retirement and preserves book. | CURRENT | State irreversible consequences precisely; surface audit/history and a recovery story if binding was mistaken. |
| W08 | Library | Lists reading and research-brief workspace objects or teaches the empty state. | CURRENT, read-only | Needs rich preview, source/evidence inspector, proposal status, deduplication, filing, citation, correction, and object navigation through Focus. |
| W09 | Ledger | Lists dossier objects and embeds Memory. | CURRENT | Separate shared record, personal memory policy, object history, and provenance; current blend is conceptually dense. |
| W10 | Memory add | Creates a room memory. | CURRENT | Show who/what scope owns it, source message, durability, and downstream injection. |
| W11 | Memory search | Local filtering/search when list grows. | CURRENT | Label room scope; backend global search is distinct. |
| W12 | Memory expand | Reads full memory content. | CURRENT | Include created/updated times, speaker/source, supersession, and reference use. |
| W13 | Promote/demote memory | Adds/removes personal cross-session reuse. | CURRENT | Explain personal versus shared visibility and where the memory may be injected. |
| W14 | Memory edit/delete | Backend supports update/delete. | BACKEND ONLY | Needs provenance-aware editing, deletion consequences, supersession/history, confirmation, and permission rules. |
| W15 | Workspace object list | Selects reading, brief, thesis, commitment, proposal, dossier, House movement, or Record event. | CURRENT projection | Current selection only navigates objects with a `branch_id`; objects without one appear interactive but do nothing. This is a broken affordance until Focus exists. |

### Target workroom grammar

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| W16 | Field | Reads room reasoning as positions, claims, tensions, questions, definitions, evidence, syntheses, and branch candidates. | TARGET; backend files IN PROGRESS in dirty worktree | Provisional/confirmed/contested/superseded must be textual and structural, not color-only. Review actions make human authority explicit. |
| W17 | Field review | Confirm, contest, correct, split, merge, and inspect lineage/provenance. | TARGET | Use stable ordering so review changes meaning without making the map jump; preserve history. |
| W18 | Focus | Selects any object into a detailed inspection/workbench state. | TARGET | It is not a tab. It needs state, sources, relationships, open questions, proposal state, evidence, branch variants, history, checks, and actions. |
| W19 | Focus deep link | URL carries an object ID; unknown/inaccessible object degrades to an unavailable state. | TARGET | Use the one navigation writer; mobile becomes full-surface with Back clearing object selection. |
| W20 | Focus actions | Confirm/contest quickly; correct/split/merge through a minimal editor; open source/branch. | TARGET | Gate on membership and show effect before mutation. Retain notes and human stamp. |
| W21 | Atlas | Navigates cross-room rooms, branches, artifacts, Echoes, sources, and unresolved work. | TARGET | It is personal navigation, not a shared House projection; authorization must match each source room. |
| W22 | Current | Sees changing external/internal conditions and overnight movement. | APPROVED DESIGN, not current scene vocabulary | Define exact data contract and human actions before adding navigation; avoid a generic feed/dashboard. |
| W23 | Judgment | Reviews predictions, commitments, resolutions, calibration, and pending decisions. | APPROVED NAME / TARGET, no Release 3 build | Consolidate Stakes and proposal resolution when real population/action density justifies a scene. |
| W24 | Research Brief | Reads a durable research result with question, sources, claims, caveats, proposal links, and revision state. | TARGET concept; current result is a message | The result needs identity beyond “long chat answer,” especially for citation and reuse. |
| W25 | Proposal object | Opens proposal as a durable object rather than only an embedded card. | TARGET implication | Required for inbox, history, expired/dismissed/failed states, and deep links. |
| W26 | Evidence review | Opens source content, extraction, claim check, relationship, and acceptance decision. | NEEDS SURFACE | This is the bridge between Record, Library, Field, and Focus. |
| W27 | Artifact history | Sees revisions, supersession, proposal/acceptance, and provenance. | PARTIAL / TARGET | Use one history grammar across memory, Field marks, readings, theses, commitments, and proposals. |

## Surface register: current supporting panels

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| P01 | Users | Reads current presence list. | CURRENT | Rename to Presence or add real membership. Do not label online users as the complete roster. |
| P02 | Branches | Reads/selects branch genealogy. | CURRENT | Unify with header branch selector and in-Record fork context. |
| P03 | Share | Copies invite credentials. | CURRENT ordinary rooms | Add secret handling, revocation/rotation, and membership state. |
| P04 | Insights | Reads conversation DNA, volume, argument density, question resolution, memory/forks/provoker, and turn balance. | CURRENT | Fetch failure currently collapses into “No analytics data.” Separate empty, unavailable, stale, and partial. Explain metrics and avoid turning reasoning into vanity scores. |
| P05 | History | Replays room event timeline, play/pause, and speed. | CURRENT | State reconstruction is not fully wired. Either reconstruct trustworthy historical state or present an event log without implying replay fidelity. |
| P06 | Dialectic identity | Directly edits the room’s shared LLM identity. | CURRENT | Save failure is weakly surfaced and “LLM Identity” contradicts product identity. Treat as privileged room policy with version/audit. |
| P07 | Memory | Reads/adds/searches/promotes memory. | CURRENT in Ledger and some Home context | Complete provenance/edit/delete/history before expanding reuse. |
| P08 | Stakes | Creates and manages predictions, commitments, bets, deadlines, confidence, resolution, filters, and calibration. | CURRENT | Browser prompts for resolution are insufficient for nuanced judgment. Consolidate object history, evidence, partial/voided reasons, and conflict. |
| P09 | Capability map/help | Reads live auth/room capabilities, active scheduler jobs, scene explanation, and honest limits. | CURRENT | Excellent source-of-truth direction; translate internal jobs into user consequences and actions. |
| P10 | Room settings | Controls Dialectic participation heuristics. | CURRENT | Move out of generic “settings” ambiguity; add separate Personal, Room, Notifications, Membership, and Dialectic behavior domains. |
| P11 | Knowledge graph / concept map | Backend analytics exposes concept/provenance/connections/refresh capabilities. | BACKEND ONLY | Field/Atlas may supersede it. Wire to the approved projection or retire; do not create a third graph metaphor. |
| P12 | Cross-session search | Backend searches memories across sessions. | BACKEND ONLY | Belongs in Atlas/global retrieval with source-room authorization and clear scope, not current-room Cmd/Ctrl+K. |
| P13 | Collections/references | Create memory collections, attach/retrieve references, inspect reverse references, auto-inject. | BACKEND ONLY | Needs a coherent Echo/source-management surface or deliberate removal. Raw collection CRUD is not a product. |

## Surface register: browser, OS, and device boundaries

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| X01 | Notification permission prompt | Browser asks to allow notifications. App currently requests on room entry when permission is `default`. | CURRENT + EXTERNAL | Prompting before value/explanation is a trust and conversion risk. Ask only after an explicit human action with a clear benefit. |
| X02 | Enable push chip | Human explicitly subscribes through service worker/PushManager. | CURRENT | Consolidate with X01 so there is one comprehensible opt-in path and a visible result. |
| X03 | Denied/unsupported push | Hook distinguishes unsupported, denied, prompt, subscribed, and error states. | CURRENT logic | Surface recovery instructions and do not repeatedly nag when OS/browser policy blocks permission. |
| X04 | OS push notification | Title/body appears outside the app. | CURRENT + EXTERNAL | Include human-readable room/context while minimizing sensitive content; support privacy preview settings. |
| X05 | Notification tap | Service worker opens/focuses app and deep-links to room. | CURRENT | Extend to branch/object/proposal and reconcile revoked access, deleted object, and changed status. |
| X06 | Away local notification | Page-generated Notification when hidden and push is not already subscribed. | CURRENT | Prevent duplicate OS alerts; apply the same privacy/mute policy as push. |
| X07 | Document-title unread badge | Hidden tab title gains an unread count and resets on return. | CURRENT | Keep counts consistent with server badge/read receipts and avoid implying every event needs attention. |
| X08 | Room mute/settings | Backend supports per-room mute, room notification settings, and badge counts. | BACKEND ONLY | Needs Personal Notifications UI: per-room mute, event classes, preview privacy, quiet hours/device status, and test notification. |
| X09 | Native device tokens | Backend registers/removes native notification tokens. | BACKEND ONLY | No native client is in the active architecture; label as reserved or remove until a client exists. |
| X10 | PWA installation | Browser/OS “Install” or “Add to Home Screen” uses manifest/icons. | CURRENT + EXTERNAL | Add an in-product, platform-aware explanation only when install materially improves the workflow; include update/offline expectations. |
| X11 | Service-worker update | Browser may keep an older asset until lifecycle/cache advances. | CURRENT infrastructure | Needs a safe “Update available” pattern if behavior/contracts change; never silently strand a stale frontend against a closed backend door. |
| X12 | Responsive layouts | Desktop rails, tablet compression, mobile drawers, mobile full-surface targets. | CURRENT + TARGET | Test real interaction at 390/phone, tablet, laptop, wide desktop; not merely overflow bounds. |
| X13 | Keyboard | Enter/Shift+Enter, Cmd/Ctrl+K, escape/overlay interactions, tab/focus. | PARTIAL | Publish a coherent shortcut map for the PWA, prevent conflicts, and prove every pointer action has a keyboard path. |
| X14 | Screen reader/semantic DOM | Native controls and ARIA exist unevenly. | PARTIAL | Axe plus manual landmark, naming, live-region, focus-order, table/graph, and modal testing is required. |
| X15 | Reduced motion | Streaming, typing, pulses, transitions, replay, tool state. | NEEDS SYSTEMATIC SURFACE | Motion may explain causality only; preserve meaning and progress when reduced. |
| X16 | Color/contrast/grayscale | State colors, participant identity, predictions, Field status, market state. | PARTIAL | Every distinction needs text/shape/pattern; test key screens in grayscale and high contrast. |
| X17 | Clipboard | Copies invites, IDs/tokens, brief text, webhook URL, messages, exports. | CURRENT + EXTERNAL | Confirm success, distinguish secrets, handle denied clipboard, and avoid copying hidden/stale values. |
| X18 | Download/export | Downloads attachments, chat Markdown, thesis JSON, generated outputs. | CURRENT across both apps | State format, scope, sensitivity, generation time, and whether the export is a snapshot. |
| X19 | Offline/reconnect | PWA socket reconnects and some stale content remains visible. | PARTIAL | Define read availability, draft safety, write queue/no-queue, duplicate prevention, and conflict resolution. Do not use one “offline” label for all. |

## Surface register: tradingDesk specialist UI

The Draw.io artifact establishes tradingDesk as a separate live SPA behind its
own service. It is part of the human surface map even when reached from the
Dialectic Bench.

### Field Desk root (`/`)

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| T01 | Field Desk masthead | Sees “DIALECTIC FIELD DESK,” current case, “EYES ONLY,” analyst cities/distance, agents, clock, and classic-desk link. | CURRENT, DUPLICATE identity | It competes with the primary Dialectic workroom and hardcodes two named analysts/providers. Specialist context should inherit the originating room and shared identity. |
| T02 | “WIRE LIVE” telemetry | Sees a green live label plus a changing millisecond value. | CURRENT but deceptive | The displayed latency is generated by `Math.random()`. Remove it immediately; no cosmetic number may masquerade as observed system truth. |
| T03 | Open cases rail | Selects thesis book/case and sees phase, presence, confluence. | CURRENT | Align “case/book/thesis” vocabulary and preserve room binding. |
| T04 | New case `+` | Button is visible with “Open a new case” title. | CURRENT but inert | It has no click handler. Remove until real or connect to Builder with a defined creation flow. |
| T05 | Standing bets | Reads up to six predictions and their state/confidence. | CURRENT | Link to full prediction object/evidence/history and standardize confidence storage/format. |
| T06 | Dossier room | Reads/sends a second real-time room transcript with people and multiple named providers. | CURRENT, DUPLICATE collaboration | The trading README schedules this social tier for removal. Preserve specialist evidence/actions, not a second room/chat universe. |
| T07 | Dossier message composer | Uses mentions, slash commands, auto-complete, Enter, and “FILE” send. | CURRENT, DUPLICATE | Consolidate commands/proposals with the primary Record or explicitly scope this as a specialist console. |
| T08 | File clipping | Enters source, headline, optional take; files a structured clipping. | CURRENT | This useful evidence capture should become a canonical reading/evidence move, with URL, timestamp, source preview, duplicates, and provenance. |
| T09 | Code exhibit | Enters filename, language, and code; files an exhibit. | CURRENT | Canonicalize as an attachment/evidence type rather than a surface unique to the duplicate chat. |
| T10 | Dispatch interactions | Reads typed dispatches, agent/model output, TV alerts, commitments; flashes referenced nodes. | CURRENT | Preserve cross-highlighting as a Focus/Bench interaction after duplicate chat removal. |
| T11 | Situation cockpit | Filters phase nodes, sees state, confluence, price, countdowns, scenarios, and feed freshness. | CURRENT | Strong specialist surface; make freshness measured, timestamped, source-specific, and accessible without color. |
| T12 | Trade termination | Opens modal, types `KILL`, provides reason, requests short-lived token, confirms irreversible ledger write. | CURRENT | Strong deliberate-action pattern. Add focus trapping, expiry countdown, evidence/state snapshot, and post-action receipt. |

### Classic desk (`/desk/*`)

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| T13 | Classic desk shell | Room/book switching, connection/outbox/presence, panel layout, Builder/Field Desk/welcome links, logout. | CURRENT | Establish this as a named specialist cockpit rather than an alternative primary product. |
| T14 | Room management | Creates/selects trading rooms and binds an optional book. Backend also supports rename/delete. | CURRENT create/select; partial lifecycle | Decide whether these rooms survive the social-tier cull. Do not build more management UI for a layer scheduled for removal. |
| T15 | Book tab bar | Switches thesis books and displays state dots. | CURRENT | Explain worst-state aggregation, freshness, and origin room. |
| T16 | Market ticker/watchlist | Reads live watchlist associated with room/thesis. | CURRENT | Show source, observation time, stale/error/closed-market state. |
| T17 | Classic chat | Real-time humans/providers, mentions, compare, slash commands, search, pins, copy, retry, export, presence, pending sends. | CURRENT, DUPLICATE | This is a second duplicate chat in the same SPA. Extract unique specialist commands before culling. |
| T18 | Thesis viewer | Refreshes/selects book; reads freshness, cascade, node filters/states, confluence, countdowns, scenarios. | CURRENT | Consolidate shared view logic with Bench/Field Desk or define one authoritative detailed view. |
| T19 | Morning brief | Generates/regenerates and copies a structured brief. | CURRENT | Link sources and generated-at data; preserve prior brief while regeneration fails; define whether this becomes a Dialectic Research Brief. |
| T20 | Cross-book scan | Runs scan, expands findings, sees severity/type/freshness. | CURRENT | Explain algorithm/evidence and distinguish no finding from unavailable scan. |
| T21 | Cross-book matrix | Compares books, states, signals, trades, and refresh. | CURRENT | A justified specialist matrix; maintain keyboard/table semantics and source freshness. |
| T22 | Prediction tracker | Creates, filters, resolves correct/partial/incorrect, sees accuracy/calibration. | CURRENT | Reconcile with Dialectic Stakes/Judgment so one prediction has one identity/history. |
| T23 | Trade journal | Logs direction, ticker, entry/exit, thesis node, notes; reads open/closed and P&L. | CURRENT | Add edit/close/correction/audit semantics deliberately; do not treat optional exit as complete lifecycle truth. |
| T24 | TradingView panel | Copies webhook URL, inspects security/rate/skew/nonce state, filters/creates/deletes bindings, sees recent results. | CURRENT | Keep secret/security wording operator-grade, provide setup test/receipt, and link each alert to the mutation/evidence it caused. |
| T25 | Trade lifecycle | Re-evaluates predicates, expands trades/ledger/errors, performs tokenized kill flow. | CURRENT | Reuse one termination grammar and make evaluation time/source visible. |
| T26 | Agent in room | Inspects runtime status, model/tool set, logs/calls, prompt preview, snapshot revision, and refresh. | CURRENT | Keep operational diagnostics out of primary reasoning UI; label privacy/sensitivity and access role. |
| T27 | Outbox badge/detail | Sees queued bridge snapshots, age/room detail, and manually drains/replays. | CURRENT | Excellent operator recovery surface; add per-item result, deduplication guarantee, and explicit production-impact wording. |
| T28 | UI command palette | Cmd/Ctrl+K searches rooms, panels, and actions; stores recents. | CURRENT | Align shortcuts with primary PWA and preserve visible scope. |
| T29 | Backend command palette | Cmd/Ctrl+Shift+K introspects commands, builds parameter inputs, executes. | CURRENT but incomplete result UX | Results are only toasted and stored on `window.__lastCommandResult`. Add a durable typed result/receipt or keep this as an explicitly developer-only console. |
| T30 | Keyboard shortcut overlay | `?` opens the shortcut list. | CURRENT | Good discoverability; add full focus trap/return and current-platform labels. |
| T31 | Responsive panel controls | Collapses rails, overlays right panel, drag-resizes desktop panel. | CURRENT | Prove touch targets, keyboard resizing, saved width, overlay focus, and dense-data readability. |

### Builder and education

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| T32 | Builder library (`/builder`) | Lists books, opens, duplicates, deletes with confirmation, imports JSON, creates blank. | CURRENT | Clarify active/in-use books before deletion and provide provenance/version/audit. |
| T33 | Thesis graph canvas | Adds/selects/moves nodes and edges, pans/zooms, sees causal graph. | CURRENT | Keyboard and screen-reader alternative is mandatory; provide list/table editing equivalent. |
| T34 | Thesis metadata editor | Edits title, claim, budget, as-of metadata. | CURRENT | Validate meaning and units inline; show how changes affect bound rooms. |
| T35 | Node editor | Edits identity, label, phase, rationale, thresholds, data sources, instruments, countdowns, signals. | CURRENT | High cognitive load needs progressive disclosure, examples, validation, and change impact. |
| T36 | Edge editor | Edits causal rationale and lag; deletes edge. | CURRENT | Show source/target context and prevent invalid/cyclic or orphaning mutations with explainable validation. |
| T37 | Instrument/rules/scenario editors | Manages instruments, portfolio rules, scenario probabilities/impacts. | CURRENT | Strong domain surfaces; use stable terminology and validation with consequence previews. |
| T38 | Builder history | Undo/redo, dirty state, before-unload/in-app discard confirmation. | CURRENT | Good local safety; add version history, conflict detection, save receipt, and server-side revision identity. |
| T39 | Import/export JSON | Uses local file picker/download and conversion. | CURRENT + EXTERNAL | Show schema/version, validation preview, collision policy, and whether import creates or overwrites. |
| T40 | Save/delete | Blocks on validation, shows errors/warnings, saves, confirms delete. | CURRENT | Link validation issues to exact graph fields; communicate server failure without losing local history. |
| T41 | Welcome site (`/welcome`) | Reads architecture, features, recipes/cookbook, workspace diagrams, and product negatives. | CURRENT | Reconcile terminology/identity with the primary PWA and current system; stale education is worse than no education. |
| T42 | Onboarding tour | Modal sequence covers welcome, chat, thesis viewer, TradingView, integrations, Builder, done. | CURRENT | If duplicate chat is removed, rebuild around the canonical end-to-end human journey and permit skip/replay. |
| T43 | Empty states/toasts | Teaches first room and reports errors/success. | CURRENT | Toasts cannot be the sole home of actionable failures or command results. Persistent work needs persistent receipts. |

## Surface register: external and operator workflows

| ID | Surface | Human interaction | State | Required work / risk |
|---|---|---|---|---|
| O01 | Email delivery | Receives verification, invite, password-reset, security, and possibly notification mail. | NEEDS EXTERNAL SURFACE | Not implemented. Define sender identity, expiry, phishing-resistant links/codes, resend, bounce, and support path. |
| O02 | TradingView alert editor | Human installs Pine logic and webhook payloads in TradingView. | EXTERNAL + documented | Provide copyable payload, test endpoint, binding health, last accepted/rejected receipt, clock-skew help, and no secret in screenshots. |
| O03 | Generated thesis HTML | Opens self-contained graph dashboards in `trading/output/`. | OPERATOR / exported analyst surface | Mark snapshot generation time, book version, data freshness, and whether it is authoritative or archival. |
| O04 | Health endpoints | Operator checks service/database/scheduler/readiness. | OPERATOR | A human-safe status dashboard is optional; do not expose sensitive internals publicly. Read-only health must never mutate. |
| O05 | Logs | Reads `journalctl` and structured service events. | OPERATOR | Preserve correlation IDs and human-action receipts; redact secrets/tokens/content appropriately. |
| O06 | Feature flags/capabilities | Edits environment for signup, guests, jobs, providers, behavior. | OPERATOR | Current Help reads runtime capability truth. Any future control deck must show code default, persisted/env override, active value, restart requirement, and blast radius. |
| O07 | Service deployment | Migration, service restart, frontend release/flip, nginx reload, health/asset verification. | OPERATOR | Sequence depends on whether a change opens or closes a door; UI/backend compatibility must be explicit. |
| O08 | Database migration | Applies and verifies schema changes. | OPERATOR | Never represent a frontend as available until migration/runtime contract is active. |
| O09 | Home founder activation | Reviewed SQL creates/marks founders. | OPERATOR | Keep rare bootstrap separate from everyday membership UI and record audit evidence. |
| O10 | Home member removal | Reviewed SQL removes a member. | OPERATOR | Move to UI only with explicit authorization, consequence preview, confirmation, and audit/recovery. |
| O11 | Account provisioning/recovery | Creates credentials or rotates server password outside product. | OPERATOR | Replace routine use with invite/recovery flows; retain emergency break-glass procedure. |
| O12 | Scheduler/job control | Enables/disables/restarts Wire, digest, prediction, reading, research work. | OPERATOR with CURRENT read-only Help | Product UI should show effects and human decisions, not generic toggles for implementation jobs. |
| O13 | Bridge/outbox recovery | Inspects queued snapshots and replays. | CURRENT tradingDesk operator UI + OPERATOR service context | Keep replay idempotent and show exact destinations/results. |
| O14 | Market/provider credentials | Configures Anthropic/OpenRouter/market sources and observes failures. | OPERATOR | Primary UI should report capability/provenance/unavailability without naming providers as product participants. |
| O15 | Production support | Investigates revoked access, missing data, failed research, stale snapshots, or notification delivery. | NEEDS COHERENT WORKFLOW | Build audit/event lookup around a person, room, object, and action—not raw service topology. |

## Backend-only capabilities and the surfaces they imply

| Capability already present | Current human access | Needed canonical home |
|---|---|---|
| Verify email, forgot/reset password | None | Access/account recovery (A05–A07) plus email (O01). |
| Per-room mute, notification settings, badge, native token registration | Web subscription only | Personal Notifications (X01–X09). |
| Full memory update/delete | Add/search/promote/demote only | Ledger/Focus history and provenance (W09–W14). |
| Global memory search, references, collections, auto-injection | None | Atlas/Echo/source management (P12–P13, W21). |
| Persona CRUD | None by design | Either privileged Dialectic behavior settings or retirement (D15). |
| Concept map/provenance/connections | No UI | Field/Focus/Atlas projection or retirement (P11). |
| Field projection/review | Dirty-worktree backend only | Field scene and Focus review (W16–W20). |
| Workspace objects | Read-only lists; branch-only opening | Focus object state/deep links (W15, W18–W20). |
| Proposal envelope and accept relays | Machine proposal cards only | Human Make a Move plus proposal inbox/object (D12–D13, W25). |
| Research event/result | Long-running button and message | Research Brief/workbench (D07, W24). |
| Room event history | Replay timeline with incomplete reconstruction | Trustworthy history/event record (P05, W27). |
| trading room patch/delete | Create/select only | Decide during social-tier cull; do not expand a retiring layer. |
| Backend command registry/results | Ephemeral toast/window variable | Typed operator command console/receipt or developer-only removal (T29). |

## End-to-end human journeys

These journeys expose gaps that component-by-component reviews miss.

### J1. First arrival to useful work

```text
Premise → sign in / invitation → account state → Home → Needs you or a room
→ understand House/Record/scenes → make first contribution → see delivery truth
```

Breaks today:

- There is no real invite acceptance/account setup flow.
- Signup can be closed honestly, but recovery is absent.
- Email verification/reset APIs claim delivery that does not exist.
- No-room, no-membership, revoked-access, and unavailable-server states need
  clearer separation.

### J2. Invite another human

```text
Choose room → Share → understand secret and role → send link/code
→ recipient authenticates → previews destination → joins → appears as member
→ controls notifications → can later leave or be removed
```

Breaks today:

- Invitation is secret copying, not a complete lifecycle.
- Presence substitutes for membership in several surfaces.
- No routine leave/remove/rotate/revoke UI exists.
- Home membership uses a stronger candidate-confirm pattern than ordinary rooms;
  the product should converge on that trust level.

### J3. Conversation becomes durable work

```text
Write/reply/attach evidence → Dialectic may infer or propose
→ human inspects sources/consequences → accepts/contests/corrects
→ durable object appears in Field/Bench/Library/Ledger/Judgment
→ object opens in Focus → history/provenance remain inspectable
```

Breaks today:

- Humans cannot yet author structured proposals.
- Proposal review is buried in message chronology.
- Workspace objects without branches appear selectable but do not open.
- Field and Focus are not implemented at HEAD.
- Evidence review and artifact history lack one shared grammar.

### J4. Research question to reusable brief

```text
Question → scope/cost/time expectation → progress/cancel → source retrieval
→ partial/failure/success → inspect sources/claims/caveats → accept/file/cite
→ durable Brief in Library/Focus → later Echo/reference
```

Breaks today:

- The question is not durably persisted at HEAD.
- Result is a normal message, not a Brief.
- No partial-result/citation-review workspace exists.
- Cross-session references/collections exist behind APIs only.

### J5. Notification back to exact work

```text
Human opts in → chooses privacy/mute policy → event occurs while away
→ one OS alert → tap → authenticate/refresh → exact room/branch/object/proposal
→ changed/revoked/deleted fallback → action → read/badge reconciliation
```

Breaks today:

- App can ask permission automatically on room entry before value is explained.
- Per-room notification controls are backend-only.
- Deep links stop at room/branch/scene, not object/proposal.
- Device acceptance remains unproved in this audit.

### J6. Dialectic room to specialist trading work and back

```text
Bench thesis → Open specialist desk → token exchange → same room/book context
→ inspect/edit/operate → durable result/receipt → return to originating Focus/Bench
```

Breaks today:

- The desk opens into a competing “Dialectic Field Desk” identity and duplicate
  room/chat model.
- Vocabulary fragments across scheme, room, case, book, thesis, desk, and Field.
- Some specialist results stay in toasts or a browser global.
- Return navigation and shared object identity are weak.

### J7. High-consequence judgment

```text
Prediction/commitment/trade/proposal → inspect evidence/current state
→ understand effect → confirm with reason → attributable mutation
→ receipt/history → correction or dispute path
```

Strong pattern already present:

- Trade kill requires intent (`KILL`), a reason, a short-lived token, and a
  second confirmation.

Weak patterns:

- Some prediction resolutions use icon buttons or browser prompts.
- Proposal acceptance lacks a product-wide review center.
- Artifact correction/dispute/history is inconsistent.

### J8. Failure and support

```text
Action fails → input/state retained → human sees scope/cause/retry safety
→ retry or support receipt → operator can trace person/room/object/action
→ human sees resolution without duplicate mutation
```

Breaks today:

- Some frontend failures only log, disappear, or masquerade as empty data.
- tradingDesk command results are ephemeral.
- Primary support remains service/log oriented rather than action oriented.

## Required state coverage

Every interactive surface should explicitly decide which of these states it
supports. “Nothing rendered” is never an acceptable implicit state.

| State family | Required visible states |
|---|---|
| Acquisition | unavailable, loading, ready, empty, stale-with-last-good, partial, retrying, failed. |
| Access | signed out, invited, authenticated, unverified, unauthorized, revoked, expired, missing membership, role insufficient. |
| Connectivity | live, stale, reconnecting, offline-readable, offline-draft-safe, write not queued, write queued, sync conflict. |
| Human mutation | pristine, editing, validating, submitting, succeeded with receipt, failed with retained input, retry-safe, duplicate prevented. |
| Proposal/judgment | proposed, under review, accepted, dismissed, contested, corrected, superseded, expired, failed, unavailable. |
| Artifact | absent, draft, provisional, confirmed, contested, superseded, retired, deleted/tombstoned, inaccessible. |
| Long-running work | queued, running, progress, cancel requested, partial, completed, failed, timed out, disabled, stale result. |
| Permission/device | unsupported, prompt available, requesting, granted, denied, OS-blocked, subscribed, muted, unsubscribed, subscription error. |
| Destructive action | consequence preview, intent confirmation, authorization/token, in progress, receipt, irreversible result, correction/recovery path. |
| Responsive overlay | trigger, open landmark/title, trapped focus, close/back, returned focus, preserved selection/scroll. |

## Highest-priority findings

### P0 — trust and product coherence

1. **Remove false telemetry.** tradingDesk displays a randomized latency next
   to “WIRE LIVE.” No world-class reasoning tool can fabricate operational
   truth, even cosmetically.
2. **Choose one primary Dialectic topology.** The PWA living workroom should be
   canonical. tradingDesk should be a specialist instrument reached from a
   thesis, not a second Dialectic home with two more chat systems.
3. **Finish the human authority loop.** Ship human “Make a move,” Field review,
   Focus, proposal inbox/history, and stable artifact deep links so people can
   do more than react to machine-authored cards.
4. **Repair access/recovery truth.** Build invitation, verification, and
   password recovery with actual delivery before any UI/API says mail was sent.
5. **Eliminate dead and lying affordances.** The Field Desk new-case `+` is
   inert; workspace objects without branches do nothing; analytics failures can
   look empty. Every visible action/state must be real and attributable.
6. **Standardize failure receipts.** Human input must survive failure; errors
   must distinguish empty/unavailable/stale; high-consequence actions need a
   durable receipt and trace.

### P1 — complete core human journeys

1. Separate membership, presence, roles, invitations, and access state.
2. Add room lifecycle and personal/account/notification settings.
3. Make Focus the universal object interaction and source/history inspector.
4. Turn Research output into a durable, source-reviewable Brief.
5. Make House “Needs you” the cross-room human-action inbox.
6. Implement exact local restoration and object-level notification deep links.
7. Consolidate predictions/commitments across Stakes, proposal cards,
   Judgment, and tradingDesk so one object has one history.
8. Complete keyboard, screen-reader, focus, grayscale, reduced-motion, and real
   device-width acceptance across both SPAs.

### P2 — simplify or retire

1. Route global memory search/references/collections through Atlas/Echo or
   retire raw CRUD.
2. Let Field/Focus/Atlas supersede the old concept-map endpoint rather than
   adding another graph.
3. Keep persona CRUD deferred unless a real human-managed identity use case is
   chosen.
4. Decide whether generated HTML thesis dashboards are exports or a supported
   surface; label and test accordingly.
5. Convert backend command execution into a real operator console with results,
   or remove it from normal UI.
6. Remove frozen `packages/`, unconnected `cc-sidecar`, archived prototypes, and
   stale screenshots from product-surface discussions; retain them only as
   lineage.

## Canonical world-class surface model

### 1. One product, two scopes

```text
Dialectic
├── Home scope
│   ├── House — shared movement and Needs you
│   ├── Atlas — personal cross-room navigation
│   └── Record — Home conversation
└── Room scope
    ├── Record — deliberation and provenance
    ├── Field — live reasoning structure
    ├── Bench — thesis/specialist work
    ├── Library — evidence and briefs
    └── Ledger — durable record and memory

Selected object → Focus (state, not tab)
Pending human act → Make a move / Review
Specialist thesis operation → tradingDesk instrument, with return context
```

Do not create another dashboard, generic canvas, activity feed, permanent Focus
tab, or provider selector as a primary surface.

### 2. One object grammar

Every reading, brief, thesis, commitment, proposal, prediction, Field mark,
memory, event, and movement should answer the same questions:

- What is it?
- What state is it in, in words as well as visual form?
- Who or what proposed/created it?
- What sources and room/branch context support it?
- What changed, when, and why?
- What requires a human now?
- What will each available action do?
- What object/state resulted from the action?
- How can it be contested, corrected, superseded, or revisited?

Focus is the shared answer; scenes provide domain context, not competing detail
implementations.

### 3. One trust grammar

Use these distinctions everywhere:

| Meaning | UI obligation |
|---|---|
| Machine inferred | Literal **provisional** label, softer/dashed structure, provenance, no durable authority. |
| Human proposed | Named proposer, payload, evidence, consequence, review state. |
| Human accepted | Named accepting human, timestamp, resulting object, idempotent receipt. |
| Contested | Literal **contested** label, reason, actor, next available correction/review. |
| Superseded | Collapsed but available lineage; never silently erased. |
| External/live data | Source, observation time, retrieval time, stale threshold, failure state. No cosmetic telemetry. |
| Destructive/irreversible | Consequence preview, deliberate intent, reason where meaningful, authorization, final receipt. |

### 4. One navigation authority

- Keep `useRoomNavigation` as the only destination writer.
- Extend destination with object/Focus rather than inventing another router.
- Deep links and notifications override restoration; restoration never overrides
  current server authorization/state.
- Unknown or inaccessible object → Focus unavailable → nearest valid parent,
  not a generic 404 or blank surface.
- Back closes mobile Focus/overlay before leaving the human’s place.

### 5. One settings model

Settings need named domains:

1. **Personal:** profile, password, sessions/devices, accessibility, appearance.
2. **Notifications:** permission/subscription, previews, room mute, event types,
   quiet behavior.
3. **Room:** name/lifecycle, members/roles/invites, room policy.
4. **Dialectic behavior:** auto-participation and deliberation heuristics.
5. **Home:** membership and shared-home policy.
6. **Operator diagnostics:** capabilities, jobs, provider/runtime health—role
   gated and visually separate.

### 6. One responsive/accessibility contract

The same work must remain possible at phone, tablet, laptop, and wide desktop:

- No hover-only action.
- Every icon-only action has a name and a visible discoverability path.
- Every modal/drawer traps and returns focus.
- Dense graphs have list/table editing and reading equivalents.
- Every state remains intelligible in grayscale and with reduced motion.
- Touch targets and scrolling work inside nested rails/inspectors.
- Draft, selected object, reply, review, and scroll survive non-destructive
  layout changes.
- Loading, empty, unavailable, stale, and access-denied are different states.

## Evidence index

### Architecture and product intent

- `docs/diagrams/dialectic-architecture.drawio`
- `docs/diagrams/README.md`
- `docs/superpowers/specs/2026-08-12-dialectic-front-end-identity-design-v2.md`
- `PLAN.md` — Release 3 handoff; dirty user-owned file, read but not changed by
  this audit.
- `JOURNAL.md`

### Primary PWA

- `dialectic/frontend/app/src/App.tsx`
- `dialectic/frontend/app/src/components/`
- `dialectic/frontend/app/src/hooks/useRoomNavigation.ts`
- `dialectic/frontend/app/src/hooks/usePushSubscription.ts`
- `dialectic/frontend/app/src/hooks/useAwayAlerts.ts`
- `dialectic/frontend/app/src/lib/workspaceRoute.ts`
- `dialectic/frontend/app/src/types/workspace.ts`
- `dialectic/frontend/app/src/sw.ts`

### Primary backend capabilities

- `dialectic/api/main.py`
- `dialectic/api/auth/routes.py`
- `dialectic/api/home.py`
- `dialectic/api/notifications/routes.py`
- `dialectic/api/cross_session_routes.py`
- `dialectic/api/personas.py`
- `dialectic/api/workspace.py`
- `dialectic/api/field.py` — untracked, in-progress backend file at audit time.
- `dialectic/deploy/`

### tradingDesk

- `trading/frontend/src/App.tsx`
- `trading/frontend/src/pages/Dashboard.tsx`
- `trading/frontend/src/components/dialectic/`
- `trading/frontend/src/components/builder/`
- `trading/frontend/src/components/`
- `trading/web/routes/`
- `trading/docs/USER-MANUAL.md`
- `trading/docs/runbooks/`
- `trading/deploy/README.md`

## Explicit exclusions

- This audit does not claim current production activation or browser behavior;
  it maps current checkout wiring and planned/in-progress states.
- It does not treat database tables, service-to-service APIs, schedulers, LLMs,
  or providers as human surfaces. It maps their required human status/control
  consequences.
- It does not treat the frozen React Native `packages/` code as current UI.
- It does not treat `cc-sidecar` as connected product UI.
- It does not treat stale screenshots as evidence of the current interface.
- It does not prescribe a visual style system. It defines the interaction and
  information architecture that a visual system must serve.

## Audit conclusion

The shortest path to a world-class Dialectic UI is not a broad reskin. It is to
make the existing product model coherent:

1. The PWA becomes the only Dialectic home.
2. House exposes movement and human obligations.
3. Record preserves the deliberation.
4. Field exposes provisional structure.
5. Focus makes every durable thing inspectable and actionable.
6. Human proposals and reviews complete the authority loop.
7. Bench opens tradingDesk as a specialist instrument, not a competing product.
8. Every external, failure, permission, and destructive state tells the truth.

That sequence produces a UI whose sophistication comes from continuity,
inspectability, and human authority—not from surface count or visual density.
