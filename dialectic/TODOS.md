# Dialectic — TODO List

> Current-state board as of 2026-08-16. This file contains unfinished work
> only. Shipped Release 1–3 history lives in [`../PLAN.md`](../PLAN.md), the
> release ledgers under `docs/superpowers/plans/`, `JOURNAL.md`, and git.

## The quarter (see the plan for full detail + acceptance checks)

- [ ] **P1 residue**: real-device push check on all four devices (Amo + Dan)
- [ ] **P2 (wk 3–4) residue**: persist `context_truncated` to `llm_decisions`
      (it currently only downgrades the FSM tier).
- [ ] **P3 residue**: device-level acceptance — three consecutive mornings,
      one brief per active room, push received by both users
- [ ] **P4 residue**: device-level acceptance of the sweep (question +
      10min silence → exactly one follow-up, and push).
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
operator surfaces. Shipped status stays in the audit amendment and `PLAN.md`;
this section tracks only unresolved cross-cutting work.

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
