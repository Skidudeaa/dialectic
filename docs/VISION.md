# Dialectic — Vision

*Written down 2026-08-08, from the founding idea and the owner's brief. This is
the durable statement; the quarterly plan (`docs/plans/`) is how it gets built.*

## The idea

Dialectic is an experiment in **collaborative cognition**: two friends and an
LLM co-reasoning in one place, over years, across everything they scheme on
together. It is deliberately not a chat app with an assistant bolted on. The
test of every feature is: *does this make the third mind a better participant?*
— never *does this answer questions faster?*

## The consigliere

The owner's brief, verbatim in spirit:

- **Scope: everything.** Trading and markets, deals and projects, decisions and
  commitments, and the personal — a full second brain for the friendship.
  Every scheme is a room; the room's third member holds its whole history.
- **Agency: works while you sleep.** Between sessions it researches open
  questions, watches scheme state and deadlines, and drafts morning briefs.
  It writes messages and memories — it does not take external actions. Not
  (yet) a standing-permission actor.
- **Cadence: ship monthly, feel it weekly.** Progress that the two humans
  notice in daily use, or it doesn't count.

## Design principles

1. **Participant, not assistant.** The LLM decides when to speak (and, just as
   deliberately, when not to). It carries positions, an evolving identity, and
   a model of each human. Provoker mode exists because comfortable consensus
   is a failure state.
2. **Memory with attribution.** "Remember X" is useless without *who said it
   and when*. Recall runs three lanes (meaning, exact words, speaker); a
   restated fact supersedes its predecessor instead of duplicating it, and the
   old version keeps a closed validity window, not an eraser.
3. **Event sourcing is the truth.** The append-only event log is the source of
   truth; everything else (memory tables, projections, replays) must be
   derivable from it.
4. **An operational self-model.** Ported from the cc-sidecar architecture: the
   participant should know its own state (a finite state machine, not just
   counters), tag every self-belief with a confidence tier
   (observed/reconciled/inferred), downgrade its confidence when its context
   was truncated, and notice — on a timer, with no triggering event — that a
   room went quiet or that it was ignored.
5. **Honest verification.** Every capability claim gets a falsifiable,
   device-level acceptance check. A green test that can't fail is not
   evidence; a benchmark number beats a vibe.
6. **Reach without gatekeepers.** The installed PWA serves all four devices
   today; native apps only when they earn their build-chain cost.

## The long arc

Near term (this quarter): push → cross-room memory + self-awareness → the
Night Shift (scheduler, morning briefs) → silence detection + commitment
proposals → overnight research + generalized scheme state → memory benchmark.

Beyond: supersession as a fully rebuildable event-log projection; the
LongMemEval harness as a standing regression gate; scheme state rich enough
that the consigliere can brief a week's decisions across every open scheme;
and — when the pair wants it — graduated standing permissions for real actions.
