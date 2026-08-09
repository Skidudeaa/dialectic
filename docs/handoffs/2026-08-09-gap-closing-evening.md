# Handoff — The Gap-Closing Evening (2026-08-09, ~21:00–22:15 UTC)

**What happened:** the morning's fusion left a named tail; the owner ordered all
of it plus the two trust-gated items shipped the same day. Six workstreams
(W1–W6) executed by subagents under disjoint file fences against an approved
plan, then a live-found bugfix, a full docs overhaul, and an in-app help
surface. 12 commits, dialectic suite 679 → **790 green**, all three deploy
layers stepped forward and verified.

## What is LIVE in production

| Capability | Proof |
|---|---|
| Attachments bind in the send transaction; REST bind + 2s debounce gone | `6d4fe3e`; broadcast carries media; empty-caption sends work |
| `get_thesis_news` tool (11 tools total) | `4ed40d9`; X-Service-Token client path; 10→11 registry contract |
| Tools on the non-streaming path; `force_response` self-aware + logged | `a915059`; migration **010 applied** (`llm_decisions.tool_calls`) |
| Morning Brief 07:00 CT, per room, pushed | `9052502`; catch-up fired 21:02 UTC — briefs posted to 4 rooms (Iran had 88 missed), 2 pushes each, quiet room skipped |
| `draft_prediction` + human Accept → relay to tradingDesk | `bbeebc5`; REST message projection carries `metadata` (traces survive reload) |
| Silence FSM + 60s sweep (10min → one follow-up; 3/day; quiet 23–07 CT) | `b448c70`; migration **011 applied**; ledger shows `participation_sweep` success every 60s since 21:02 |
| **`auto_interjection_enabled` toggle finally gates the heuristic path** | same commit; room settings toggle is real |
| Book-scoped tools resolve in bound rooms | `c0191e8` — `Room` model gained `linked_book_id` (BaseModel had silently dropped migration 008's column); resolver reads v3 `thesisId`. Found live: "tool needs explicit book ID" in the bound Iran room |
| Docs tell the truth | `6155ae1` (front doors), `11100e5` (trading README rewrite + INTEGRATION.md superseded stamp), `ac73898` (plan stamps) |
| In-app help: `Help ⌄` button in the room header; Escape dismisses both dialogs | `0c2b462`, `fcf1936`; live at origin (bundle hash verified) |

Deploy state: DB at migration 011 · backend process on `c0191e8` (restarted
16:21 CDT) · nginx serving `20260809T213832Z-help-escape` + the Escape/button
release (`fcf1936`). All five scheduler jobs registered and ledgering.

## What is NOT done

1. **Device checks only the humans can run**: real-device push on all four
   devices; cross-device image send; "@Claude what's oil at" + trace; the
   silence test (question + 10 quiet minutes → exactly one follow-up);
   three consecutive mornings of the brief.
2. **CommitmentDetector as proposals** — `stakes/detector.py` imported, still
   never called. W5's Accept-card pattern is now the template.
3. **Cross-room memory write path** — routes + WS handlers + promote-to-global
   UI (read path already live). The remaining P2 item.
4. Fusion tail: C4 social-tier cull, td local-login sunset (P6),
   annotator-vision product call (owner), `TRADINGDESK_DB_PATH` override,
   `.planning/` archive, **`books/*.json` carry room tokens to GitHub —
   unrevisited**.
5. Ops: `tradingdesk-bridge.timer` still enabled — disable after a clean week;
   `trading/snapshots/*-latest.json` churn sits dirty in the worktree from
   service activity (commit-vs-gitignore decision pending); td quotes cold
   path still 18.5s (240s cache papers over it).
6. Known rough edge: memory recall can recite stale facts as current
   (annotator quoted "Brent ~99.7", "4 days uptime" from months-old memories
   this evening). P6 benchmark work; until then, the tools are the
   countermeasure — make Claude fetch live.

## Gotchas new this session

- **The brief catches up.** `morning_brief` fires once on recovery if the
  service was down through its 07:00 CT slot (today it posted at ~16:02 CT
  for the missed morning). Ledger `UNIQUE(job_name, scheduled_for)` keeps it
  to once per day — but expect a brief after any deploy that spans the slot.
- **New jobs default ON.** `NIGHT_SHIFT_ENABLED`, `PARTICIPATION_SWEEP_ENABLED`
  unset = live. Kill switches are env `=0`.
- **Relay credentials must line up**: dialectic `TRADINGDESK_USER` must be
  literally `dialectic`, `TRADINGDESK_PASSWORD` = td's `DIALECTIC_SERVICE_PASSWORD`.
- **FSM caps live in code**: `llm/silence_sweep.py` — `FSM_FOLLOWUP_DELAY_MIN=10`,
  `FSM_QUIET_START/END=23:00/07:00` (America/Chicago), cap 3/day,
  `FSM_DORMANT_HOURS=24`; all env-tunable.
- ChunkHound runs via `~/.local/bin/chunkhound-trial` (external config at
  `~/.config/chunkhound-trial/`, yarn exclude merged there; repo-local
  `.chunkhound.json` must NOT exist — the wrapper refuses it).

## Where the deeper records live

- Task board: `dialectic/TODOS.md` (stamped this session)
- Plan stamps: `docs/plans/2026-Q3-consigliere.md` §P3/P4,
  `docs/plans/2026-Q3-consigliere-amendment-1-fusion.md` (evening stamp)
- Morning session: `docs/handoffs/2026-08-09-fusion-overnight.md`
- In-app tour: room header `Help ⌄` — same content as `dialectic/README.md`
