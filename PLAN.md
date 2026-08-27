# Dialectic guided learning — zero-context handoff

Current **2026-08-26 America/Chicago**. The owner wants a complete, human-useful
walkthrough/how-to built into the live Dialectic PWA so Dan, Nick, Scott, and
future collaborators cannot stumble through God's Eye / World Synapse without
learning what it is, how to use it, and where human authority begins and ends.

This is a planning checkpoint, not an approved design or implementation. The
next session must resume with the owner ruling in `OPEN QUESTIONS — ASK BEFORE
DECIDING`; it must not infer that answer from the recommended direction.

At handoff, `/root/DwoodAmo` is `master` at
`1f8dc4f8102d2446d504f9f832555a1c63681182`, equal to `origin/master`. The
tracked tree was clean before this handoff; preserve unrelated untracked
`AGENTS.md`, `IMG_0197.PNG`, and
`docs/superpowers/acceptance/__pycache__/`. Live World Synapse application code
is `85fed38`; the current production/runtime and rollback ledger remains in
`docs/superpowers/qualification/2026-08-25-phase-3-world-synapse.md` and Git
history at `1f8dc4f^:PLAN.md`.

> **Amended 2026-08-26 (evening) — these runtime coordinates are stale; prefer
> what follows.** A parallel session shipped the World cockpit and its live
> signal adapters after this checkpoint was written. `master` is now `0ebd535`
> (`a8fe8ee` + three reviewed fixes), pushed; live application code is
> `0ebd535`, not `85fed38`; the backend is PID `2832622` and the selected PWA
> release is `20260827T003007Z-world-cockpit-0ebd535`. No migration
> accompanied either commit. The tracked tree is no longer clean at `1f8dc4f`.
> Everything else in this plan — the guided-learning contract and its
> OPEN QUESTIONS — is untouched and still awaits the owner's ruling. Full
> record: `docs/handoffs/2026-08-26-world-cockpit-live-signals.md`.
>
> One consequence for THIS plan: World now has live layers, sensor optics, a
> HUD and click-to-track, so anything the guided walkthrough teaches about
> World must cover them — including the line the product draws between
> tracking a contact (presentation, writes nothing) and placing one
> (authority, a human act).

## LATEST INTENDED CONTRACT

- The education is **inside Dialectic**, reachable from the app while using the
  real product. An external README, video, slide deck, or docs-only page is not
  the requested outcome.
- It must be complete enough that a new collaborator understands the essential
  Dialectic model, then can safely traverse House -> World -> Focus -> Field ->
  thesis meaning without losing object identity or mistaking imagery for
  authority.
- It must be human-useful: concise language, visible examples, doing rather
  than reading alone, explicit provenance and failure states, keyboard/touch/
  mobile/reduced-motion support, and an evergreen replay door.
- “Cannot stumble without learning” means passive Help alone is insufficient.
  The product must bring the learning path to the user and retain progress. The
  exact mandatory/skip/account-persistence policy is unresolved below.
- The core walkthrough must be safe and read-only. It may navigate and inspect
  real authorized objects, but it must not create fake production evidence,
  Field judgments, scope reviews, or thesis edits merely to demonstrate them.
- The participant, World, and Help must tell one consistent story: provider
  observations/proposals are not authority; human placement creates durable
  GeoScope lineage; explicit Field binding gives causal meaning; human review
  adjudicates it; Builder remains the sole thesis writer.

## FEATURE DOSSIER — CURRENT LEARNING SURFACES

### Current surface

- `RoomHeader.tsx` exposes one labeled Help button at every width.
- `HelpDialog.tsx` is the one explanation door with two ARIA tabs:
  `This room` and `What changed`.
- `CapabilityMap.tsx` reads live room/scheduler capability state and tells only
  durable rules. It currently explains the participant, thesis binding,
  background jobs, Record/Bench/Library/Field/Ledger, glossary, and limits.
- `WhatsNewPanel.tsx` renders authored append-only release history while reading
  current job state from the live capabilities endpoint.
- `lib/releases.ts` stores changelog history and a device-local last-seen release
  ID at `dialectic-releases-seen`; this is unread-badge state, not onboarding
  progress.
- `App.tsx` owns `helpTab` as transient local state and mounts `HelpDialog` only
  when the user taps Help. There is no automatic first-run/open behavior.
- World Synapse is live, but the current Help map does not teach World, scope
  lineage, provenance, Focus continuity, causal bindings, or failed-WebGL
  behavior. The newest changelog entry is 2026-08-22; no World/Synapse release
  entry exists.

### Pivotal lineage

- `0c2b462` — introduced the in-room Help dialog as the whole product tour.
- `fcf1936` — made Help a visible labeled button and Escape-dismissable.
- `3b36ac2` — replaced hardcoded deployment claims with the live capability
  projection; established the law “facts about this deployment are read, rules
  about the product are told.”
- `3f36c37` — added the shared glossary, scene primers, and the self-checking
  “What changed” shelf; browser screenshots caught visual breakage tests missed.
- `0be95ae..85fed38` — added and activated World Lens/Synapse without extending
  the learning surface.
- `42f9315` in `trading/frontend` — older tradingDesk first-login tour and
  `/welcome` guide. It proves a replayable first-run pattern was useful, but it
  describes the retired parallel trading interface and is not the live
  Dialectic PWA architecture.

### Last alignment and present drift

The current repair baseline is the live Dialectic Help architecture at
`3f36c37` forward-ported through current `master`: one obvious Help door, live
capability facts, authored durable rules, accessible explanations, and visual
browser review. Do not restore the old tradingDesk tour wholesale.

The drift is educational, not a broken renderer: World/Synapse acquired a deep
object/authority workflow after the Help surface's last substantive expansion.
Current code works, but a collaborator can open World without ever learning
why House remains authoritative, how selection survives across surfaces, how
provenance and lineage work, or why a causal binding is a human Field judgment.

## DECISIONS WITH RATIONALE

1. **Extend the existing Dialectic Help system.** Strongest rejected alternative:
   a separate `/welcome` microsite. It lost because the user asked for education
   built into the product, and a second door can remain undiscovered.
2. **Use the old tradingDesk onboarding only as a historical pattern.**
   Strongest rejected alternative: port its components. It lost because those
   steps teach the retired parallel interface and its component/router state is
   not Dialectic's PWA architecture.
3. **Teach through safe navigation and inspection, not production writes.**
   Strongest rejected alternative: require users to create a scope and causal
   mark. It lost because forced training must not manufacture authoritative
   evidence or thesis meaning.
4. **Retain one evergreen replay door in Help.** Strongest rejected alternative:
   a one-shot modal only. It lost because a collaborator must be able to relearn
   after time away or when a feature becomes relevant.
5. **Preserve the live-facts/written-rules split.** Strongest rejected
   alternative: hardcode an all-capabilities tour. It lost because the previous
   Help prose materially drifted from production and overstated/understated what
   was active.
6. **Teach World as Dialectic, not as a globe product.** Strongest rejected
   alternative: a cinematic Cesium tour. It lost because the core lesson is
   causal object continuity and human authority, not camera spectacle.
7. **Keep the required core approximately five minutes and move depth into
   optional missions.** Strongest rejected alternative: one encyclopedic
   walkthrough. It lost because mandatory walls of text teach dismissal, not
   competence.
8. **Do not load Cesium merely to explain Cesium.** Strongest rejected
   alternative: embed a live globe inside Help. It lost because House users must
   retain the zero-World-byte shell contract and failed-WebGL users need complete
   learning too.
9. **Use versioned progress rather than a permanent boolean.** Strongest
   rejected alternative: `onboarded=true`. It lost because major new learning
   contracts must be able to re-open without erasing a person's prior history.
10. **Target all eligible collaborators, not hardcoded display names.** Strongest
    rejected alternative: special-case Dan/Nick/Scott. It lost because names are
    mutable, authorization is account-based, and future members need the same
    safety. Whether existing accounts are forced through the first version is
    the explicit owner question below.

## RECOMMENDED EXPERIENCE — NOT YET OWNER-APPROVED

Add a first Help shelf named `Start here`, backed by a versioned progress owner.
Auto-open it for accounts that have not completed the current required guide.
Allow temporary closing and exact resume, but—if the owner approves mandatory
completion—keep the Help action visibly marked and reopen at the next natural
entry until the core is complete. Completion removes pressure; Help always
retains `Start here` for replay.

The core should teach six short chapters:

1. **One living room:** Dialectic is the participant; Record, Bench, Library,
   Field, Ledger, Atlas, Focus, and World are projections of the same room-owned
   objects, not separate apps.
2. **Human authority:** the participant can read, propose, and navigate; human
   actions establish geographic and causal authority; Builder alone edits a
   thesis.
3. **House and World:** House is the complete accessible list; World is a lazy
   spatial embodiment. Switching views preserves the selected object. A room
   change clears the prior object/camera fence.
4. **Inspect evidence:** select an authorized real scope when one exists, open
   Focus, inspect provider/acquisition/source ID/URL/credit, freshness, and
   append-only lineage. If no room scope exists, use a code-native illustration
   and say why no live example is available; never fabricate one.
5. **Give geography meaning:** show the exact semantic sequence `scope ->
   supports/challenges/context -> thesis node -> review state`; explain that it
   is DOM truth, not a measured geographic ray. If no real binding exists, say
   so and show the grammar without pretending production contains one.
6. **Recover and continue:** return World -> House with the same selection,
   show failed-WebGL/list fallback, show where Help/What changed live, and state
   the next optional practice mission.

Optional missions may guide real user-chosen work—place a genuine observation,
ratify/redraw, bind a genuine causal relation, confirm/contest/correct—but only
after the user chooses an actual room object and the ordinary product confirms
the write. A dedicated training room or synthetic evidence system is out of
scope unless separately approved.

## APPROACHES CONSIDERED

### A. Account-owned required core + contextual practice — recommended

Server stores guide version, current/completed step, and timestamps per user.
The PWA auto-opens/resumes the core and Help replays it. Contextual prompts
connect steps to the real current room when safe. This alone reliably reaches
existing users across devices, but requires an authenticated API/storage change
and production migration.

### B. Device-local guided Help

Reuse `localStorage` like release-seen state. Cheapest and no migration, but a
user can complete it on one device and be interrupted forever on another, clear
site data to reset, or never see it on an already-open device. This does not
fully satisfy “cannot stumble without learning.”

### C. Contextual coach marks only

Teach each surface the first time it opens. Feels lightweight, but users can
miss steps, never build the mental model in order, and cannot prove completion.
Useful as optional reinforcement after the core, not as the sole design.

## DO-NOT-RELITIGATE LIST

- Help remains the one explanation door. This is settled by the existing
  product contract and avoids another undiscoverable guide surface.
- Do not hardcode current room counts, active providers, scheduler flags, or
  production causal-binding existence. The prior Help drift established that
  runtime facts must be read.
- Do not copy `trading/frontend/src/components/onboarding` into Dialectic. That
  is legacy product architecture, not an implementation shortcut.
- Do not invent a second navigation writer. Every guided destination must use
  `useRoomNavigation.navigate`; no direct room/scene/view/object mutation.
- Do not create fake scopes, Field marks, reviews, or thesis changes to complete
  mandatory learning. GeoScope/Field/Builder authority is a production law.
- Do not imply unavailable/unconfigured/empty/zero are the same source state.
- Do not eager-import `WorldView`/Cesium from Help, guide data, illustrations,
  tests, or a barrel export. The production build's lazy-Cesium gate is settled.
- Do not make hover/title attributes the only explanation. Keyboard, touch,
  screen-reader, and failed-WebGL users get the complete contract.
- Do not use color as the only state. Existing Help/World accessibility rules
  require words plus visual treatment.
- Do not reduce the 44 px action target or 12 px small-text floors, and honor
  `prefers-reduced-motion`.
- Do not claim deployment from source tests. Migration, backend PID, selected
  release, public bytes, activation, public browser, and human completion are
  separate truth surfaces.

## OPEN QUESTIONS — ASK BEFORE DECIDING

1. **Mandatory policy — first and blocking:** should the core be mandatory once
   per account for all existing and future users, with temporary Close but no
   permanent Skip until completion? The prior recommendation was exactly this;
   the owner did not answer and instead requested this handoff. Stop and ask.
2. If mandatory is approved, should an account be allowed to use the rest of
   Dialectic while the incomplete guide is temporarily closed, or should core
   completion gate normal interaction? Recommendation: allow normal use, keep a
   persistent named reminder, and resume at the next login/Help open; a hard
   interaction lock is hostile and risky.
3. Does “complete” mean God's Eye/World Synapse plus the minimum Dialectic mental
   model needed to use it, or a comprehensive tour of every current Dialectic
   capability? Recommendation: World/Synapse core plus optional broader modules;
   an all-product mandatory tour will be too long.
4. Is server-side per-account persistence approved, including a small migration,
   or must the first version remain client-only? Do not invent a table or mutate
   `users` before this decision.
5. May guided navigation offer the real Hormuz room as an example to every user
   who is already authorized there, or must the guide remain entirely in the
   current room? Never widen membership for training.
6. Is production activation part of the resumed implementation session? A
   migration, service restart, immutable frontend release, public acceptance,
   and account-level UAT require explicit current authorization even though the
   droplet is production.

## REPO / ENVIRONMENT ORIENTATION

### Canonical learning surfaces

- `dialectic/frontend/app/src/components/layout/HelpDialog.tsx` — one Help door,
  tab state, modal/Escape/outside-click behavior.
- `dialectic/frontend/app/src/components/layout/HelpDialog.test.tsx` — current
  accessible tab and dismissal contracts.
- `dialectic/frontend/app/src/components/layout/CapabilityMap.tsx` — live facts
  plus durable rules; keep guide copy consistent with it.
- `dialectic/frontend/app/src/components/layout/CapabilityMap.test.tsx` — live
  state, unknown-state, and reader-facing copy tests.
- `dialectic/frontend/app/src/components/layout/WhatsNewPanel.tsx` and
  `lib/releases.ts` — current-state-aware history and device-local unread state;
  add the shipped World/guide entries here only after implementation lands.
- `dialectic/frontend/app/src/components/layout/RoomHeader.tsx` — visible Help
  action and unread mark.
- `dialectic/frontend/app/src/App.tsx` — current `helpTab` owner and all Atlas /
  World / Focus / Field navigation callbacks. Do not grow guide business logic
  indiscriminately inside this already-large file.
- `dialectic/frontend/app/src/hooks/useRoomNavigation.ts` — sole destination
  writer.
- `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.tsx` —
  House/World projection, textual scope list, causal overlay, WebGL fallback.
- `dialectic/frontend/app/src/components/focus/FocusWorld.tsx` — provenance,
  lineage, review, placement, Field binding doors.
- `dialectic/frontend/app/src/components/workspace/scenes/FieldScene.tsx` —
  causal relation/review and Builder handoff.
- `dialectic/frontend/app/scripts/verify-lazy-cesium.mjs` — emitted-build guard.

### Backend if account persistence is approved

- `dialectic/api/main.py` — router registration/lifespan; do not put progress
  SQL inline here if an existing focused API module pattern fits.
- `dialectic/api/capabilities.py` — current live Help facts; guide progress is a
  different concern and should not contaminate deployment capability truth.
- `dialectic/schema.sql` and numbered `dialectic/migrations/` — migration 022 is
  current. Any guide-progress storage must update both migration and fresh-DB
  baseline in the same change.
- `dialectic/models.py`, authentication dependencies, and existing user-scoped
  API modules — trace actual caller/fence patterns before naming the contract.
- `users` currently contains identity/style fields only; there is no existing
  onboarding/tutorial progress column or table. Do not guess a storage shape.

### Legacy / misleading paths

- `trading/frontend/src/components/onboarding/`,
  `trading/frontend/src/components/welcome/`, and
  `trading/frontend/src/pages/Welcome.tsx` teach the old tradingDesk frontend.
  Read for interaction lessons only; tradingDesk's duplicate social/UI product
  was culled and Dialectic is the human interface.
- React Native packages are frozen and cannot satisfy production reach.
- Legacy static Dialectic frontends are retired. Only
  `dialectic/frontend/app` builds the live PWA.
- `dialectic/deploy/dialectic.service` targets nonexistent
  `/opt/dialectic/current`; the installed production unit runs
  `/root/DwoodAmo/dialectic` directly.

### Environment and production boundaries

- Backend: `/etc/systemd/system/dialectic.service`, loopback port 8002.
- Public origin: `https://dialectic.somacura.org`.
- Frontend: immutable directories under `/var/www/dialectic-releases`, selected
  by `/var/www/dialectic-current`.
- Production environment: `dialectic/.env`; never commit or print it.
- Current World migration: 022. Current app source: `85fed38`; later commits
  through `1f8dc4f` are documentation only.
- Start production work read-only. Preserve unrelated dirty/untracked files.
  Migration/restart/release/push require their own evidence and authorization.

## IMPLEMENTATION SHAPE AFTER OWNER APPROVAL

Do not write code directly from this section. After the blocking owner ruling,
finish the design, save it under
`docs/superpowers/specs/2026-08-26-dialectic-guided-learning-design.md`, obtain
owner review, then write a TDD implementation plan under
`docs/superpowers/plans/2026-08-26-dialectic-guided-learning.md`.

Likely units, subject to that approved design:

1. A pure typed guide curriculum: stable guide/version/step IDs, durable copy,
   optional contextual destination/action metadata, no Cesium imports.
2. A focused progress owner: load, resume, advance, complete, and version
   semantics; authenticated server API only if approved.
3. A `Start here` Help shelf/stepper with semantic progress, Back/Next, Close,
   replay, keyboard focus management, reduced motion, and responsive layout.
4. A small coordinator outside `App.tsx` that decides whether to auto-open and
   asks `useRoomNavigation` to perform safe guided destinations.
5. Context adapters that truthfully say “not available in this room” and show a
   code-native explanatory example rather than fabricating live state.
6. A World/guide release entry and current Help copy update after the behavior
   exists and has passed browser qualification.

## VERIFICATION

### Before editing

```bash
cd /root/DwoodAmo
git status --short
git rev-parse HEAD
git rev-parse origin/master
git diff --check
```

Pass: only the known handoff/JOURNAL edits plus preserved unrelated untracked
paths exist. Never stage the unrelated artifacts.

### TDD predicates

Write each test before implementation and observe the expected failure:

- incomplete current guide auto-opens under the owner-approved policy;
- completed current guide stays quiet but replays from Help;
- an older completed version follows the approved re-learning policy;
- Close preserves exact resume progress and differs from Complete;
- progress is fenced to the authenticated user and cannot read/write another;
- unavailable progress says unknown/retry rather than silently “complete”;
- every step has a stable ID, meaningful heading, and named user action;
- guided destinations pass through `useRoomNavigation` and clear room-fenced
  object/camera state correctly;
- a room with no scopes/provider/bindings tells that truth without fabricated
  examples;
- keyboard order, focus return, Escape/Close policy, 44 px controls, 12 px text,
  reduced motion, and 390 px width remain usable;
- importing/rendering Help loads no World/Cesium bytes;
- failed WebGL keeps the complete instructional path.

Targeted commands will depend on final filenames. Full existing gates are:

```bash
cd /root/DwoodAmo/dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/ -q

cd frontend/app
npm test -- --run
npm run lint
npm run build

cd /root/DwoodAmo
git diff --check
```

The build must end with `Lazy Cesium contract passed`. Do not accept the known
jsdom canvas informational message as browser proof.

### Browser acceptance

Retain machine results and visually inspect screenshots at desktop and 390 px:

1. Existing account with no current completion is brought into the core under
   the approved policy.
2. Close/reload resumes the exact step; completion/reload stays quiet.
3. Help -> Start here replays from the beginning without erasing completion.
4. Navigate House -> World -> Focus -> Field explanation -> House through
   visible guide controls and canonical URLs.
5. Repeat in a room with no geography and no causal binding; wording is honest.
6. Force WebGL failure; complete the same curriculum from the text list.
7. Run keyboard-only, reduced-motion, and mobile viewport sequences; inspect
   focus, overflow, type size, and target geometry.
8. Verify House/Help cold launch transfers zero World/Cesium bytes.
9. If server progress exists, use two authenticated users and prove isolation.
10. Observe no page errors, HTTP 500s, leaked tokens, or production evidence
    writes from the mandatory core.

### Production qualification if separately authorized

Report independently: migration and backup; backend clean checkout/restart/PID;
health and logs; immutable PWA release/symlink/nginx; served asset hashes;
public authenticated browser; activation policy; Dan/Nick/Scott account
eligibility; actual human completion. A green automated browser is not proof
that any named person learned it.

### Definition of done

- Every eligible collaborator is brought to the current core under the owner's
  approved policy and can resume/replay it.
- The core teaches the six chapters above without hardcoded deployment lies,
  fake authority, eager Cesium, inaccessible interactions, or production writes.
- Help remains accurate, obvious, and evergreen; “What changed” records the
  shipped feature only after it exists.
- Source, backend, frontend, build, accessibility, browser, public delivery,
  activation, and human completion are reported separately.
- Dan, Nick, and Scott have each actually completed the production guide or are
  truthfully listed as pending; account records alone are not learning proof.

## CONFLICT RULE

If implementation reality contradicts this plan, the builder flags the contradiction and stops — no silent improvisation, no quiet re-planning.

## AMENDMENTS
