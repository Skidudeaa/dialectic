# Dialectic Quarter Plan — "The Consigliere Wakes Up"

## Context

Dialectic crossed from prototype to daily tool this week: the LLM has speaker-attributed
three-lane memory (c66b735) and the app is installed and persistent on all four devices
Amo and Dan use (b6bea5c), with both accounts on real emails. But the codebase is
incoherent: flagship capability exists in every state from live to orphaned — the
self-model is dark on the @Claude path, ~800 lines of cross-room memory are unreachable,
the commitment auto-detector is written and never called, the interjection toggle does
nothing, and the Expo mobile app cannot reach production at all.

Owner's brief (2026-08-08): **scope = everything** (trading, deals/projects,
decisions/commitments, personal — a second brain for the friendship);
**agency = works while you sleep** (research, watches, morning briefs — not a
standing-permission actor); **cadence = ship monthly, feel it weekly**.

**The vision:** every scheme is a room; every room has a third member that never
forgets, never sleeps, knows who said what and what was decided. By day it argues and
keeps score; by night it does the homework. It reaches both humans wherever they are,
and holds the pair to their own commitments.

**Backbone dependency logic:** pockets must buzz before nightly work is worth doing
(push first) → the self-model must fire on every LLM path before the state machine has
a decision stream to ride → a scheduler must exist before anything can notice a quiet
room → research and scheme state ride the scheduler → the benchmark and cleanup close
the quarter honestly.

**Standing deploy ritual** (each phase; no hot reload): 1) `psql` apply migrations,
verify `\d`; 2) `systemctl restart dialectic`, verify `/health`; 3) frontend build →
release dir → flip `/var/www/dialectic-current` symlink → `systemctl reload nginx`;
4) acceptance check on a real device, never just curl.

---

## Phase 1 — "Dan's pocket buzzes" (wk 1–2)

**Felt outcome:** PWA closed, phone locked — a message from the other person (or
Claude) raises a lock-screen notification, correctly attributed.

Builds:
- **Web Push (VAPID) backend**: add `pywebpush`; new `api/notifications/webpush.py`
  (sender + 404/410 subscription pruning); refactor `api/notifications/service.py`
  into a channel dispatcher (existing Expo path + new web path); subscribe endpoints
  in `api/notifications/routes.py`. VAPID keys in the systemd env file.
- **Frontend**: switch `vite.config.ts` `generateSW` → `injectManifest`; new
  `src/sw.ts` with `push` + `notificationclick` (deep-link to room), `skipWaiting`/
  `clientsClaim` so installed PWAs self-update; `hooks/usePushSubscription.ts`
  (permission → subscribe → POST); "Enable notifications" affordance;
  `useAwayAlerts.ts` stands down when push is active.
- **Day-1 bug fix**: `transport/handlers.py:1547` uppercase-vs-lowercase speaker
  comparison (always False — LLM pushes never labeled).
- **Docs**: rewrite stale `TODOS.md` to this roadmap; declare `frontend/app` the sole
  live frontend; fix `dialectic/CLAUDE.md` quick start (still points at retired
  `app.html`).

Migration `007_web_push.sql`: `web_push_subscriptions(id, user_id, endpoint UNIQUE,
p256dh, auth, user_agent, created_at, last_success_at)`; `push_tokens` untouched.

**Acceptance:** app fully closed on Dan's locked Android and Amo's locked iPhone —
a message from the other user notifies within 30s, attributed "Amo/Dan"/"Claude".
No buzz with app closed = phase fails.
**Risk (highest of the quarter):** the generateSW→injectManifest SW migration on four
installed PWAs. Test the SW update on one device before flipping the symlink for all.

## Phase 2 — "Claude remembers across rooms, and knows why it spoke" (wk 3–4)

**Felt outcome:** a memory promoted to global in one room gets cited by Claude in
another. @Claude replies gain self-awareness. The interjection toggle becomes real.

Builds:
- **Self-model on all three paths** (`llm/orchestrator.py`): inject
  `render_self_awareness()` + `log_decision()` into `stream_response` (~405–440) and
  `force_response` (~500–540), mirroring the heuristic path; fix the
  `getattr(decision,'_human_turns')` always-NULL bug (line 238); thread
  `self_awareness` through `prompts.py` for those paths.
- **Schema truth**: fold migration 001's `llm_decisions`/`llm_participation_state`
  into `schema.sql`; verify live DB has them.
- **Persist truncation honesty**: `AssembledContext.truncated` (`llm/context.py:136`)
  → `llm_decisions.context_truncated` (migration 008) + one system-prompt line when
  true. (Substrate for Phase 4's confidence downgrade.)
- **Wire cross-session write path**: `include_router(cross_session_routes)` in
  `api/main.py` (~260–278); resolve its 4 auth TODOs with the existing
  `token_utils`/auth patterns; instantiate `transport/cross_session_handlers.py` in
  the dispatch table; "promote to global" action in the memory panel + `lib/api.ts`.
  (Read path already live on all three LLM paths — the global lane fills immediately.)
- **Wire the toggle**: read `rooms.auto_interjection_enabled` in the heuristic entry
  point; short-circuit when false.

**Acceptance:** (a) one @Claude mention → fresh `llm_decisions` row, non-NULL
`human_turn_count`; (b) memory promoted in room A retrieved in room B's prompt;
(c) toggle off → zero unprompted interjections in a provocative 10-minute exchange.

## Phase 3 — "You wake up to a brief" (wk 5–6)

**Felt outcome:** 7am, both phones buzz; each active room has a Morning Brief —
yesterday's threads, open questions, commitments due, thesis drift. First unattended act.

Builds:
- **The scheduler (missing organ)**: `dialectic/scheduler.py`, one asyncio task
  started in `lifespan` (`api/main.py:133`); sleep-loop cron, Postgres advisory lock,
  and a `night_shift_runs` ledger (migration 009) so restart-heavy operation never
  double-fires. The ledger is load-bearing, not polish.
- **Morning brief job**: `llm/night_shift.py`; extract the briefing builder from
  `api/main.py:2228–2350` into `llm/briefing.py` (endpoint + job share one
  implementation). Iterate rooms active in 48h → post brief as an annotator-lane
  message via `llm/annotator.py`'s write path — so Phase 1 push fires for free.
  Content: unanswered questions, commitments due ≤72h (`stakes/manager.py`), thesis
  staleness.
- **Guardrails**: `NIGHT_SHIFT_ENABLED`, hour+timezone config, per-night LLM call
  cap, skip inactive rooms. Hard rule: night shift writes messages/memories only —
  never external actions.
- If graph is kept (owner decision): nightly `REFRESH MATERIALIZED VIEW` — 3 lines.

**Acceptance:** three consecutive mornings, exactly one brief per active room within
10 min of the hour, push received by both users, ledger shows one success per job per
night with zero duplicates across that week's inevitable restarts.

## Phase 4 — "Claude notices the silence" (wk 7–8)

**Felt outcome:** an unanswered question to Claude gets exactly one well-judged
follow-up minutes later. "I'll wire the deposit Monday" becomes a proposed commitment.

Builds:
- **Port the sidecar FSM**: `llm/participation_fsm.py` from
  `cc-sidecar/cc_sidecar/reducer/states.py:25–71` + `machine.py:74–149`, re-keyed to
  conversation states (engaged / awaiting-human / question-pending / ignored /
  dormant); events = Phase 2's complete decision stream + message arrivals; state in
  `llm_participation_state` (+`fsm_state`, `state_entered_at`, `state_source`,
  migration 010).
- **Confidence tiers**: port `StateSource` (observed/reconciled/inferred,
  `models.py:38–43`) + post-truncation downgrade (`machine.py:92–97`) riding Phase 2's
  `context_truncated`; surface tier in `render_self_awareness`.
- **The sweep**: 60s job on the Phase 3 scheduler, thresholds ported from
  `daemon/timers.py:36–149` but re-tuned for chat (cc-sidecar's 60/120/300s is too
  eager — minutes-to-hours; owner taste call at kickoff). Breach in
  question-pending/ignored → `force_response` (now self-aware + logged). Caps in the
  SAME commit: one follow-up per quiet event, daily per-room cap, respects the
  Phase 2 toggle, quiet hours.
- **Wire CommitmentDetector** (`stakes/detector.py`): fire-and-forget from
  `_handle_send_message` post-persist; detections are PROPOSALS (annotator-lane
  suggestion + accept action → existing manual creation path), never auto-created.

**Acceptance:** scripted — direct question + 6min silence → exactly one follow-up
(and push); further silence → zero more. FSM transitions visible in DB at threshold
timestamps. "I'll send it by Friday" → proposal within 1 min; accept → real
commitment. Any follow-up outside an FSM trigger = failure.

## Phase 5 — "It researched while you slept" (wk 9–10)

**Felt outcome:** a question tossed out at 11pm gets a researched, source-cited answer
in the morning brief. Non-trading schemes get the same always-in-context state the
trading thesis enjoys.

Builds:
- **Night research** (`llm/researcher.py`): harvest open questions from the day
  (extraction prompt or explicit tag via annotator); nightly, capped (e.g. 3/night,
  budget owner-set), research via provider web-search tooling (`llm/providers.py`);
  findings → memories (this week's dedup applies) + cited in the brief. Ledgered.
- **Generalize scheme state**: the trading pattern (JSONB on rooms → deterministic-
  slot memory `dedup=False` → prompt injection `prompts.py:158–161`) becomes the
  template. Migration 011: `rooms.scheme_state JSONB` (kind, summary, deadlines,
  next_action, updated_at). `llm/scheme_curator.py` generalizes `trading_curator.py`;
  `_build_trading_context` generalizes to a scheme-state section (trading ingest
  untouched, renders through the general path). Claude proposes state updates
  (Phase 4 etiquette); humans confirm. Deadlines feed briefs + offline push alerts.

**Acceptance:** seed an answerable question after 10pm → morning brief opens with a
researched answer + ≥1 live source URL, research job under budget in the ledger.
Scheme deadline 24h out → reminder push that evening. A brief restating the question
without research = failure.

## Phase 6 — "Prove the memory, close the tabs" (wk 11–12)

**Felt outcome:** the memory system gets a number instead of a vibe; every half-open
drawer is wired shut or removed.

Builds:
- **LongMemEval-S harness** (`tests/benchmarks/longmemeval_harness.py`, per
  `docs/research/agent-memory-2026-07`): three arms — full-context baseline, naive
  RAG same-embedder, full three-lane system. Pass = beat 53.4% by more than the
  49.0–57.8 CI. Run offline; spend the back half acting on results (lane weights,
  RRF k, supersession thresholds).
- **Supersession as rebuildable projection** — explicit stretch; only if the harness
  exposes supersession errors, else first item next quarter.
- **Cleanup execution** per the track below + final `TODOS.md`/`CHANGELOG`/
  `schema.sql` sync.

**Acceptance:** committed results file with all three arms' scores; system clears the
CI bound or a tuning list explains why. Every deleted subsystem greps to nothing;
every "wired" item has a live caller.

---

## Wire-or-delete track (all assigned)

| Item | Verdict | Phase |
|---|---|---|
| `handlers.py:1547` speaker-type bug | Fix | 1 |
| Stale `TODOS.md` + CLAUDE.md quick start | Rewrite | 1 (re-sync 6) |
| Mobile/native packages | Freeze + mark archived in docs; owner decides deletion in 6 | 1 / 6 |
| `auto_interjection_enabled` dead toggle | Wire | 2 |
| `cross_session_routes` + WS handlers (~800 lines unreachable) | Wire | 2 |
| Migration 001 missing from `schema.sql` | Fix | 2 |
| `stakes/detector.py` CommitmentDetector | Wire | 4 |
| Personas (runtime live, no UI) | Defer — keep runtime, no UI this quarter | — |
| Knowledge graph (matview never refreshed, zero callers) | Owner decision; default delete in 6, else nightly refresh in 3 | 3 or 6 |
| Replay `getState` + reconstruction | Strip in 6; keep timeline animation | 6 |

## Decisions the owner holds (asked at the phase where they bite)

1. Mobile packages: archive-and-delete in Phase 6, or keep frozen for a native
   quarter later. (Recommend: archive branch, delete from master. The mobile gap
   report from this session is the workplan if native returns.)
2. Knowledge graph: delete, or keep + refresh (name the query you'd actually run).
3. Brief etiquette: hour, timezones, quiet hours, per-room briefs (recommended) vs
   single digest.
4. Night-research nightly budget + which provider's web-search tool.
5. Phase 4 follow-up thresholds (how long is "ignored" — taste).
6. Whether a below-CI benchmark result blocks next-quarter memory features.

## Verification (plan-level)

Each phase has its falsifiable device-level acceptance check above; each ends with the
standing deploy ritual and a commit. Cross-phase invariants to re-check at every
deploy: the three-part deploy stays in step (process newer than source mtimes;
migration applied; frontend release hash live at origin); `night_shift_runs` never
shows duplicates after restarts (Phases 3+); no LLM speaks without either a human
event or an FSM trigger with caps (Phases 4+).

## Evidence appendix

Full exploration reports (backend wiring audit, cc-sidecar portability, mobile
readiness — file:line for every claim) are in this session's task outputs; the
condensed findings live in this plan's history (git of this file) and the roadmap was
independently re-verified against code by the design agent before sequencing.
