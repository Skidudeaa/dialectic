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

## The quarter (see the plan for full detail + acceptance checks)

- [ ] **P1 residue**: real-device push check on all four devices (Amo + Dan)
- [ ] **P2 (wk 3–4)**: self-model on all three LLM paths; migration 001 folded
      into schema.sql; `context_truncated` persisted + prompted;
      cross-session write path wired (routes + WS handlers + promote-to-global
      UI); `auto_interjection_enabled` toggle made real
- [ ] **P3 (wk 5–6)**: scheduler + `night_shift_runs` ledger; Morning Brief job
      (shared implementation with the briefing endpoint), pushes on delivery
- [ ] **P4 (wk 7–8)**: sidecar FSM port (states + StateSource confidence +
      timer sweep, re-tuned for chat); CommitmentDetector wired as proposals
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
