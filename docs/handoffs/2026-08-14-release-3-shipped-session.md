# Handoff — Release 3 shipped and live (2026-08-14, overnight session)

**State: Release 3 — Deliberation and Whole-House Intelligence — is MERGED,
PUSHED, and LIVE in production.** Master `7535e1c`, pushed to origin. This was
the program's final release. The next session picks up owner follow-through,
not build work.

## What is live, verified by probe (not inherited)

- Backend PID **3510008** on :8002, health 200, db connected, scheduler fresh,
  zero error lines in journalctl since restart (~02:03 CDT).
- Migration **017_field_marks** applied to the production DB (`\d field_marks`
  verified). `field_marks` currently holds 0 rows — correct: the first
  `field_inference` cycle ran at 07:02:47 UTC, success, all three active rooms
  skipped on `no_new_content` (the cheap gate spending nothing on idle rooms).
  Marks appear when conversation resumes.
- Frontend release `/var/www/dialectic-releases/20260814T070541Z-release-3-deliberation`
  behind `/var/www/dialectic-current`; **both origin AND the public Cloudflare
  edge serve `index-PC6LZzqQ.js`** (probed separately). Installed PWAs may need
  one kill-and-reopen for the service worker to swap bundles.

## The canonical records

- **Gate ledger:** `docs/superpowers/plans/2026-08-14-dialectic-release-3-deliberation-gate.md`
  — every observed number, the full mutation-guard table (~20 re-proofs), the
  25/25 + 30/30 harness runs, the perf analysis, and the honest-limits list.
- **JOURNAL.md** — the release entry (2026-08-14).
- **PLAN.md `## AMENDMENTS`** — three dated entries: stray-room clearance,
  audit disposition, and the forced deploy-before-device-checklist ordering.

## OWNER ITEMS OUTSTANDING (the reason this handoff exists)

1. **§7.6 device checklist** — macOS Safari/Chrome, Windows Chrome/Edge,
   iPhone, iPad, Android, ~10 min each against https://dialectic.somacura.org:
   open PWA → sign in → room → Field → tap object into Focus → kill app →
   reopen (lands on the exact object) → pasted room URL overrides restoration →
   type draft, reload (present, unsent) → rotate/resize (no horizontal
   overflow, nothing hover-only) → grayscale squint (still reads Dialectic).
   **Record results VERBATIM in gate ledger §9** (checkbox list already there).
   Any device FAIL ships as an immediate follow-up fix, recorded honestly.
2. **Stray room deletion** — `probe-do-not-create`
   (`eeffa8f1-9d5a-4d31-981d-b5cf0a0627e8`, 1 thread, 2 events, 0 members,
   0 messages). The owner cleared the *question* mid-build (amendment recorded)
   but the wording was ambiguous between "proceed" and "delete"; the
   production DELETE still awaits one unambiguous yes. Delete order when given:
   events → threads → room (FKs), or a single
   `DELETE FROM rooms WHERE id='eeffa8f1-...'` if cascades cover it — CHECK
   cascades first; do not improvise on production.

## Deferred with reasons (do not re-litigate; sources linked in the ledger)

- **F2** (three typographic voices + causality motion): needs a
  contribution-vs-position classification that does not exist in the message
  model. Post-gate work per Ruling R3.
- **fieldViewport / recordScroll**: stored axes with NO capture point — the
  scene frame is overflow:hidden, Record's scroll belongs to MessageList's
  follow-the-tail logic. A restore fighting that logic is design work.
- **Atlas N+1** (per-eligible-room FieldMarkService loop, 27.3% of build at
  seed scale): fine at current scale, first suspect if atlas p95 regresses.
- **Merge non-primary sources reopenable** by a later confirm (only the primary
  is lineage-anchored) — same deliberate family as reopenable bare supersede.
- **tradingDesk rider** (`e234212`: fake WIRE-LIVE latency + inert new-case
  `+` removed): merged to master but goes live only at tradingDesk's NEXT
  deploy — `tradingdesk.service` was not restarted this session.
- **Cross-cutting audit follow-through** (invitations/recovery delivery,
  membership separation, td consolidation, A25 URL-fragment token): parked on
  `dialectic/TODOS.md` P0/P1/P2, per the audit's own boundary.

## Environment / cleanup notes for the next session

- Fixture processes (:8013 backend, :4173 preview) were stopped by task
  handle; production verified untouched throughout.
- `dialectic_browser` carries gate-session residue: 2 field marks (1
  confirmed), the extra users `gate2@fixture.example.com` /
  `gate2-fixture-pw-123` (member of Scheme Room) — harmless fixture state.
- A dedicated **`dialectic_seed`** DB exists (TG-G's, ~50 rooms seeded) —
  reusable for perf reruns via `docs/superpowers/acceptance/perf_release3.py`
  (self-manages its :8014 backend). Run it on a QUIET box: the gate rerun
  missed targets purely under ambient load 35–45 (ollama + Codex processes,
  not ours); the load-13 reference met all four.
- `docs/superpowers/acceptance/__pycache__/` sits untracked; ignore or clean.
- The box had 35 logged-in users and load spikes to 73 this night — test
  timeouts under load are flakes; rerun files alone before believing them.

## Traps this session confirmed (already in the harness files' comments)

- Geometry must wait for `document.getAnimations()` to drain — `claudeEnter`
  scales rows from 0.97 and a mid-animation width reads 3% narrow.
- `rememberScene` axes-preservation must PICK fields, never spread the whole
  prior record (prior.scene clobbered destination.scene — the gate's
  kill-and-reopen scenario caught what 232 green unit tests missed; fence now
  exists in sceneContinuity.test.ts).
- Postgres `ON CONFLICT` against a partial unique index must repeat the
  index's WHERE predicate.
- `MockEmbeddings.DIMENSIONS` must match the live pgvector width (1024 since
  migration 016) — stale 1536 broke 14 tests the moment dialectic_test was
  rebuilt fresh.
