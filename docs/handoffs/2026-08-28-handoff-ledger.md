# Handoff — the ledger of ledgers (2026-08-28)

A consolidation, not a build session. This session ran one fracture review
(CLEAR — the only dirty state was two owner-left untracked files, `AGENTS.md`
and `IMG_0197.PNG`) and then swept every handoff in this directory plus
`PLAN.md` and `docs/superpowers/qualification/2026-08-25-phase-3-world-synapse.md`
to answer one question: **what is done, and what isn't.**

Rule of the sweep: an item is OPEN only if no later document closes it. One
item was corrected against the live DB; it is marked. Everything else is
sourced from the docs and inherits their accuracy.

State at handoff: `master` = `origin/master` = `b212058`, 0 unpushed commits.

## 1. Done (live in production)

| Date | What | Doc |
|---|---|---|
| 08-09 | Event-driven seam (v3 push/heartbeat/reconcile/watchdog), scheduler, tool loop, vision, media, one-login, curator gating, slow feeds | `2026-08-09-fusion-overnight.md` |
| 08-09 | Attachments-in-tx, `get_thesis_news`, Morning Brief, `draft_prediction`, silence FSM, Help dialog | `2026-08-09-gap-closing-evening.md` |
| 08-10 | News/FRED/EIA feeds honest; room tokens moved out of git | `2026-08-10-feed-layer-honesty.md` |
| 08-12 | Home Base (migration 013, founders active); thesis lifecycle + `propose_thesis` | `2026-08-12-home-base-session.md`, `2026-08-12-thesis-lifecycle-session.md` |
| 08-13 | Per-symbol OHLCV window (`f9d125c`) | `2026-08-13-indicator-window-session.md` |
| 08-14 | Release 3 — Field/Focus/Atlas/de-chat (`7535e1c`, migration 017) | `2026-08-14-release-3-shipped-session.md` |
| 08-15 | Dead bridge timer disabled, curator content gate, interjection wiring (speaks 46%→11%) | `2026-08-15-llm-volume-session.md` |
| 08-18 | Calibration spine: claims ledger, scorer, oracle, paper book, `propose_trade` | `2026-08-18-calibration-spine-session.md` |
| 08-19 | Instrument Desk UI (`2c33190`, `19d27e5`, `50025eb`) | `2026-08-19-instrument-desk-session.md` |
| 08-20 | Cross-room presence/push fix (`269cd54`); Sunday Round armed | `2026-08-20-connection-and-the-sunday-round.md` |
| 08-21 | Three-handed Round + Mirror (migration 019); 72h time-bomb fixed | `2026-08-21-the-duel.md` |
| 08-25 | `POST /rooms` joins creator, Proposal Inbox, td username leak fixed | `2026-08-25-coherence-audit-and-the-loops-it-closed.md` |
| 08-25 | World Lens 0–2 (migration 021, Cesium, tool 22, Hormuz seeded) | `2026-08-25-world-lens-phases-0-2.md` |
| 08-25 | Phase 3 Synapse (migration 022, 23 tools, PID 1941516) | `docs/superpowers/qualification/2026-08-25-phase-3-world-synapse.md` |
| 08-26 | Protocol fractures F-001..F-004 (`3b1b4b1`, `59ddae1`) | `2026-08-26-protocol-fractures.md` |
| 08-26 | `world_signals` job 16 (USGS/ADS-B/ISS/Launch Library/FIRMS) + cockpit (`a8fe8ee`, `0ebd535`) | `2026-08-26-world-cockpit-live-signals.md` |

## 2. Not done — open

### Owner decisions pending (nothing can move without a ruling)
- Round volume rule: 5 questions/room vs the recommended 3 — first raised 08-20, "still unanswered" 08-21.
- Stray room `eeffa8f1-…` delete yes/no — 08-14.
- AISStream / OpenSky terms — 08-25, restated 08-26.
- `packages/mobile/.env` tracked in a public repo, no ruling on removal — 08-26.
- `--organize` CLAUDE.md restructure — 08-21 addendum.
- Annotator-vision product call — 08-09.
- World onboarding walkthrough: six open questions, mandatory-policy ruling — `PLAN.md`.
- Standing freezes (deliberate, not forgotten): KG wire-or-delete, replay getState, personas, `packages/*` — 08-10.

### Security / hygiene
- Leaked room tokens were moved to env (`4944009`) but **never rotated** — 08-09/08-10.
- `.planning/*` archive; stale `README` / `INTEGRATION.md` — 08-09.
- `trading/CLAUDE.md` still describes pre-fusion td — 08-12.
- snapshots/outcomes churn: commit vs gitignore undecided — 08-10.

### Never verified on a real device
- Push after the presence fix; cross-device image; oil trace; silence test; "three mornings" of briefs — raised 08-09, repeated through 08-14 and 08-20, never confirmed.
- Home Base iOS/Android acceptance — 08-12.
- Release 3 §7.6 five-platform checklist — 08-14.
- Portfolio / Ledger panels; first real trade proposal — 08-18.
- RoundCard browser proof; same-day settlement bundling — 08-21.
- F-004 protocol alert line visually — 08-26.
- `others_present` live-positive proof — 08-20.
- Owner reaction pass on the five scenes — 08-19.

### Unbuilt
- Cross-room memory write path (routes/WS/promote UI) — 08-09.
- td local-login sunset (P6); `TRADINGDESK_DB_PATH` override — 08-09.
- Memory recall reciting stale facts / LongMemEval benchmark — 08-09, still unbuilt 08-15.
- P5 night research job / `scheme_state` generalization — 08-12.
- F2 typographic voices/motion — 08-14 (needs a contribution-vs-position field).
- fieldViewport / recordScroll capture point — 08-14.
- Audit P0s: real invite, email verify, password recovery, dead-state cleanup, membership separation, td consolidation, A25 token — 08-14 (proposal-inbox piece closed 08-25; rest open).
- InterjectionEngine rungs 1–7 vote-only-YES reshape — 08-15.
- Phase 8 laboratory (shadow books, analytic forecasters, weekly report) — 08-18.
- Outbox / source_key / exit-proposals / rejected-proposal / shorts slices — 08-18.
- Sharp-voice track record — 08-20 (Mirror is adjacent, not the same).
- Live Brent curve spread (front vs 6m) — 08-10.
- Globe mark glyphs; annotationGeoJson / analystEngine / motionModel ports — 08-25.
- `ProtocolDefinition.synthesis_prompt` — defined, unconsumed; do not assume it runs — 08-26.
- Bench alert-LED seen-stamp; `useTradingDesk` slice-keys filter — 08-19.
- Per-scene right-rail accent — 08-19.

### Known defects / debt
- `llm_decisions.tool_calls` double-encoded — 08-20, restated 08-21.
- Commitment Accept card asks neither deadline nor confidence — 08-20, restated 08-21.
- `save_reading` discards the summary on 403 — 08-20.
- GDELT throttle shared across books (one last-request timestamp) — 08-10.
- `_schedule_effectiveness_measurement` fire-and-forget, no retry — 08-15.
- Scheduler runs jobs serially; adsb/firms will crowd it as rooms grow — 08-26.
- `router._hash_prompt` compact projection; context estimate blind to images — 08-09.
- 10 of 20 tools never called in prod; Polymarket unconfigured — 08-20.
- Scott absent from legacy trading rooms → proposal inbox empty there — 08-25.
- Failing tests, all pre-existing: `test_home_activity_pg` (p95 gate, since 08-20), `test_newsletter_ingest.py` ×4 (08-25), `WhatsNewPanel > explains a hard word` (08-25).
- Unrun scripts: `deploy/backfill_trump_tariffs_membership.py`, `cleanup_orphaned_test_rooms.sql` — 08-25.
- Dark flags: `CONGRESS_WATCH_ENABLED` (08-18), `ANNOTATOR_DAILY_CAP` 5→12 (08-15). Trump-signal RSS watchlist entries not added (08-18).

### Closed by a later doc (recorded so nobody re-opens them)
- C4 social-tier cull (08-09) → closed 08-15.
- td WIRE-LIVE rider (08-14) → closed 08-15.
- Spatial Atlas (08-19) → closed 08-25 (World mode).
- "76 commits unpushed" (08-18) → superseded; routine pushes since.
- Original Phase 3 spec (`world_query` / `world_samples` / Bench strip, 08-25) → reshaped into Synapse, then live adapters 08-26.

### Corrected by probe (2026-08-28)
- The docs never confirm the Sunday Round fired. The DB does:
  `commitments WHERE category='round'` = **12 rows, 2026-08-23 14:00 UTC**.
  What remains open, per the 08-24 UX review: 0 of 12 have both humans
  forecasting.

## 3. Contradictions between handoffs

- **Trump Tariffs room, zero members.** 08-12 called it "not a bug." 08-25
  found it was the one casualty of the `POST /rooms` bug (rooms born without
  their creator). The 08-12 framing was wrong; the backfill exists and is unrun.
- **World Phase 3 gate.** 08-25 (phases 0–2) says Phase 3 is gated on "only
  after the wedge feels electric." The same night's qualification doc ships
  Phase 3 to production at 22:20 CDT. The usage gate was not honored.
- **GDELT throttle "heals on its own"** — 08-10 self-corrects within the file:
  drawn from one success; an 18-hour test showed identical 1-of-5 regardless
  of wait. Lesson, not a live defect.

## 4. For the next session

Cheapest high-value moves, in order: run the two unrun scripts (08-25), rotate
the room tokens (08-09), and get the owner's rulings on the seven decisions in
§2. The device-verification column has been open for nineteen days; nothing in
it needs code.
