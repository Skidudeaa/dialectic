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

Release 1 (Workroom Foundation) runs as six task groups, `A → (B ∥ C) → D → E → F`:

- [x] **A** Scene and identity kernel — scene as the third destination axis
- [x] **B** House v2 semantic movement — eight kinds, one fenced projection
- [x] **C** Workspace-object adapters — one shape, no new table, twins folded
- [ ] **D** Unified proposal envelope — over today's message metadata
- [ ] **E** Current-scene local continuity — device-local, deep links win
- [ ] **F** Integrated Release 1 gate — fresh counts, browser acceptance, the PR

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
