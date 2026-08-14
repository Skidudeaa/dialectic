# Dialectic — TODO List

> Rewritten 2026-08-08 against the approved quarter plan ("The Consigliere
> Wakes Up", `/root/.claude/plans/we-need-a-more-streamed-starfish.md`).
> The previous version of this file listed ~10 already-implemented "vision
> features" as unbuilt and Redis pub/sub as open — trust this one.

## Shipped recently (Aug 2026)

- [x] Three-lane RRF memory recall (dense + FTS + entity/speaker), write-path
      dedup + supersession, speaker attribution in prompts (c66b735)
- [x] Installable PWA on all four devices; room persists across reloads (b6bea5c)
- [x] Web Push (VAPID): backend channel + migration 007, hand-written service
      worker with push/notificationclick, subscription hook + enable chip,
      push-tap deep-links into the room. LLM-push attribution bug fixed.
- [x] Redis pub/sub (shipped earlier; the old TODO listing it as open was stale)

### Shipped 2026-08-09 (gap-closing session, six workstreams)

- [x] Transactional attachment bind (fusion handoff #12): `send_message` takes
      `attachment_ids`, insert + binds in one transaction, broadcast carries
      media; REST bind endpoint, client correlation + 2s debounce deleted (6d4fe3e)
- [x] `get_thesis_news` tool over the service-token bridge (4ed40d9)
- [x] **A7**: tools on the non-streaming `on_message` path; `force_response`
      joins the self-model (reason param, log_decision, self-awareness);
      migration 010 (`llm_decisions.tool_calls`); schema.sql finally knows the
      self-model tables (a915059)
- [x] **P3 Morning Brief**: briefing builder extracted to `llm/briefing.py`
      (+commitments ≤72h, thesis staleness, unanswered questions); scheduler
      learns wall-clock daily slots; `morning_brief` job posts + pushes per
      room 07:00 America/Chicago, `NIGHT_SHIFT_ENABLED` gate (9052502)
- [x] **A8 `draft_prediction`** (trust gate lifted by owner 2026-08-09):
      proposal-only tool, human Accept → relay POSTs to tradingDesk;
      REST message projection stops dropping `metadata` (bbeebc5)
- [x] **P4 FSM**: `llm/participation_fsm.py` (states + StateSource tiers +
      truncation downgrade) + 60s `participation_sweep` — one follow-up after
      10 quiet minutes, cap 3/day/room, quiet hours 23:00–07:00 CT;
      `auto_interjection_enabled` toggle FINALLY gates the heuristic path;
      migration 011 (b448c70)

### Shipped 2026-08-11

- [x] **Create Thesis GUI**: trading panel's empty state grows a create form;
      `POST /rooms/{id}/trading/thesis` registers the room token on td's
      bridge (runtime file tier, no restart), mints the book born bound
      (`meta.dialecticRoomId`, `*-graph` naming), links `linked_book_id`,
      logs `THESIS_CREATED`; coordinator adopts builder-saved books at
      runtime; success state deep-links into the desk's Builder
- [x] **Claude drafts the DAG**: `llm/thesis_drafter.py` — the room's
      primary model proposes the causal cascade (builder-format nodes/edges,
      validated: acyclic, typed, capped; one correction retry); stateless
      `POST .../trading/thesis/draft`, panel preview, human Accept carries
      the draft through create — draft_prediction trust shape
- [x] **Thesis lifecycle, whole loop**: `propose_thesis` (12th tool) — the
      LLM proposes a thesis mid-argument, chat card seeds the create form;
      retire (`DELETE .../trading/thesis` + td `room-unbind` — book
      survives, binding + push token die, `thesis_state_current` memory
      invalidated, `THESIS_RETIRED`); desk runs an adopted book's first
      cycle immediately (panel fills in seconds); Trading tab always
      visible (create surface was unreachable in unbound rooms);
      bound-but-undrawn panel state with Builder link

## In flight — the Living Workroom program (three releases)

Not on master. One branch (`codex/scene-kernel-identity-shell`), one worktree
(`.worktrees/release-1-workroom-foundation`), **one PR per release, opened only
at that release's integrated gate**. The canonical record of what has landed is
`docs/superpowers/plans/2026-08-12-dialectic-release-1-sdd-ledger.md` — this
list is a pointer, not a second copy of it.

Release 1 (Workroom Foundation) is COMPLETE and gated, awaiting its single PR.
It ran as six task groups, `A → (B ∥ C) → D → E → F`:

- [x] **A** Scene and identity kernel — scene as the third destination axis
- [x] **B** House v2 semantic movement — eight kinds, one fenced projection
- [x] **C** Workspace-object adapters — one shape, no new table, twins folded
- [x] **D** Unified proposal envelope — five kinds, one contract, no new writes
- [x] **E** Current-scene local continuity — window-local, deep links win
- [x] **F** Integrated Release 1 gate — 1138 backend, 77 frontend, 16/16 browser

Releases 2 (Artifact Workroom) and 3 (Deliberation and Whole-House
Intelligence) are scoped in `2026-08-12-dialectic-living-workroom-program.md`.

## The quarter (see the plan for full detail + acceptance checks)

- [ ] **P1 residue**: real-device push check on all four devices (Amo + Dan)
- [ ] **P2 (wk 3–4) residue**: persist `context_truncated` to `llm_decisions`
      (it currently only downgrades the FSM tier). Activated 2026-08-11:
      personal cross-room memory grants, membership-fenced REST promote/demote
      transport, and PWA controls. The approved REST design
      leaves the placeholder-auth router and dormant WS handlers unmounted.
      Done 2026-08-09: self-model on all three LLM paths, schema.sql sync,
      `auto_interjection_enabled` toggle
- [ ] **P3 residue**: device-level acceptance — three consecutive mornings,
      one brief per active room, push received by both users
- [ ] **P4 residue**: device-level acceptance of the sweep (question +
      10min silence → exactly one follow-up, and push). Done 2026-08-11:
      CommitmentDetector wired as proposals — fire-and-forget on human
      messages, hits land as metadata.commitment_proposals + live
      MESSAGE_METADATA push, "Put it on record" card sends an ordinary
      create_commitment with proposal_index and the server stamps
      accepted (COMMITMENT_DETECTION_ENABLED gates it)
- [ ] **P5 (wk 9–10)**: night research job; scheme state generalized beyond
      trading (rooms.scheme_state + scheme_curator)
- [ ] **P6 (wk 11–12)**: LongMemEval-S three-arm benchmark; cleanup execution;
      supersession-as-projection (stretch)

## Wire-or-delete track

- [ ] Knowledge graph: owner decision — delete, or keep + nightly refresh (P3/P6)
- [ ] Replay `getState` + reconstruction: strip in P6, keep timeline animation
- [ ] Personas: deferred — runtime + REST stay, no UI this quarter
- [ ] Mobile/native packages (`packages/*`): **frozen** — cannot reach
      production (WS handshake, room tokens, auth contract all wrong; see the
      2026-08-08 mobile readiness report). Owner decides archive-vs-delete in
      P6. PWA is the reach strategy.

## Standing invariants

- Deploys are three independent steps: migration → backend restart → frontend
  release symlink. Verify all three (see CLAUDE.md).
- Night-shift jobs (P3+) must be ledgered — restarts are frequent.
- No LLM speech without a human event or a capped FSM trigger (P4+).

## Human-interaction audit follow-through (2026-08-13)

Authority: [`docs/audits/2026-08-13-dialectic-human-interaction-surface-audit.md`](../docs/audits/2026-08-13-dialectic-human-interaction-surface-audit.md)
maps 209 current, in-progress, backend-only, target, external, duplicate, and
operator surfaces. This list tracks the cross-cutting work; Release 3's Field,
Focus, Atlas, restoration, proposal, and accessibility implementation remains
owned by `PLAN.md`.

### P0 — trust and product coherence

- [ ] Remove tradingDesk's randomized “WIRE LIVE” latency and its inert New
      Case control; no visible telemetry or action may be cosmetic.
- [ ] Make the PWA the sole Dialectic home and reduce tradingDesk to a
      specialist thesis instrument; cull its duplicate rooms/chat/Field Desk
      social tier without losing evidence capture, node cross-highlighting,
      lifecycle operations, or return context.
- [ ] Complete the human-authority loop beyond Release 3's Make a Move, Field,
      and Focus: proposal inbox/object/history, stable artifact deep links, and
      explicit accepted/contested/corrected/superseded receipts.
- [ ] Build a real invitation, email-verification, and password-recovery flow
      with actual delivery before the API or UI says a code was sent.
- [ ] Replace dead, silent, or false states: branchless workspace-object taps,
      analytics failure rendered as empty, ephemeral backend-command results,
      and action failures that lose human input or offer no safe retry.

### P1 — complete the human journeys

- [ ] Separate durable membership, presence, roles, invitations, and access;
      add room leave/remove/rename/archive, invite rotation, and stewardship.
- [ ] Split settings into Personal, Notifications, Room, Dialectic behavior,
      Home, and role-gated Operator diagnostics.
- [ ] Surface per-room mute, notification classes, preview privacy, permission
      recovery, and object/proposal notification deep links.
- [ ] Turn Deep Research into a durable, source-reviewable Brief with persisted
      question, progress/cancel, partial/failure states, provenance, and filing.
- [ ] Make House “Needs you” the cross-room human-action inbox for proposals,
      contested marks, expiring judgments, failed jobs, and unresolved work.
- [ ] Prove keyboard, screen-reader, focus, grayscale, reduced-motion, touch,
      and real-device behavior across the PWA and retained tradingDesk surfaces.

### P2 — wire coherently or retire

- [ ] Route global memory search, references, collections, and auto-injection
      through Atlas/Echo/Focus, or retire the raw CRUD surfaces.
- [ ] Let Field/Focus/Atlas supersede the old concept-map endpoints; do not ship
      a third graph metaphor.
- [ ] Keep persona CRUD deferred unless a concrete human-managed identity use
      case is approved.
- [ ] Decide whether generated thesis HTML is a supported export or an operator
      artifact, and give it explicit version/freshness/authority labeling.
- [ ] Give backend commands durable typed results and receipts, or make the
      palette explicitly developer-only.
