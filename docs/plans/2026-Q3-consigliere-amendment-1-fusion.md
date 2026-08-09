# Amendment 1 to "The Consigliere Wakes Up" — The Desk Plugs In

*Recorded 2026-08-09, beside the original per house rules (amend-beside, never
silently edit). Owner's brief, verbatim in spirit: "we are gouging them all and
turning them into one goddamn mass of an app… we're just arguing with one LLM
that doesn't have access to anything but some random data I put in there two
months ago… jump start this shit." Follow-ups the same night: trading is the
hot wedge but NOT a sandbox — the scheme abstraction stays; and full platform
build-out is in scope: "tools tools tools. like images files video we need it
all."*

Full working plan: `docs/plans/2026-08-09-fusion-master-plan.md`. This
amendment records what changes about the COMMITTED quarter plan.

> **Execution status (stamped 2026-08-09, end of the overnight session):**
> Phase 2.5 items 1–6 are **live in production** — bloodstream (all five
> rooms on v3 event-driven push, watchdog armed), tools (streaming @Claude
> path, nine read-only tools, traces persisted), one login + deep link +
> signup lock + 72h token exchange, five living theses, severity-gated
> curator + critical web push, media end-to-end with vision on images.
> 18 commits, 679 dialectic + 701 tradingDesk tests green, each capability
> verified against the running system (live Brent fetch with trace; byte-
> identical media round trip). **Remaining tail:** the monorepo move + doc
> hygiene (weekend), non-streaming tool paths (gated on streaming-path
> trust), the tradingDesk social-tier cull, transactional attachment bind,
> and `draft_prediction` after the trust week (~2026-08-16). Handoff:
> `docs/handoffs/2026-08-09-fusion-overnight.md`.

> **Execution stamp (2026-08-09, evening — same day, second session).** The
> tail closed early: transactional attachment bind (#12), `get_thesis_news`,
> **A7** non-streaming tool paths, the **P3 Morning Brief** (07:00 CT,
> per-room, push), **A8 `draft_prediction`** (trust gate lifted by owner
> ruling this day, ahead of ~08-16), and the **P4 silence FSM** + sweep
> (10-min follow-up, cap 3/day, quiet 23:00–07:00 CT) are all committed
> (6d4fe3e, 4ed40d9, a915059, 9052502, bbeebc5, b448c70), 788 dialectic
> tests green. Migrations 010/011 committed, NOT yet applied; deploys and
> device-level acceptance remain. Still open from this amendment: the C4
> social-tier cull, td local-login sunset, annotator-vision product call,
> `TRADINGDESK_DB_PATH` override, INTEGRATION.md correction.

## What this inserts: Phase 2.5 — "The desk plugs in" (immediate)

The diagnosis, verified file:line in the working plan: tradingDesk was alive
the whole time (fetching every 300s, 146k snapshots banked) while Dialectic
starved — the bridge was manual (last push June 5), tradingDesk's DB outbox
held 58,769 undelivered pushes with no drainer, the >7-day staleness gate
suppressed the whole trading block, and the LLM had no tools and no scheduler.
The fix is a fusion, not a feature: Dialectic is the app; tradingDesk becomes
its market-cognition organ.

Phase 2.5 ships:
1. **The bloodstream**: coordinator pushes snapshots on material change +
   hourly heartbeat (v3 contract carries `alertEvents`); Dialectic scheduler
   reconciles by pull; freshness watchdog tells the room when the feed is
   quiet. The DB outbox corpse is dropped; the file outbox stays as the
   failure spool.
2. **Hands and eyes**: an Anthropic tool loop in the LLM layer with nine
   read-only tools (live quotes, thesis state, what-if scenarios, Polymarket,
   open trades, brief, three-lane memory search, transcript search) backed by
   tradingDesk's live API under a dedicated `dialectic` service principal.
   Tool activity is visible in the room; every tool call is traced into
   message metadata with provenance.
3. **One login**: tradingDesk trusts Dialectic JWTs (shared HS256 secret +
   claim shim); Dialectic's open signup closes behind `SIGNUPS_ENABLED`
   (the moment td trusts our tokens, open signup is a privilege door);
   the TradingPanel's dead "Open Full Dashboard" span becomes a real link.
4. **Five living theses**: rooms provisioned and meta-bound for all five
   books (ai-capex-unwind, china-property-cascade, japan-rate-shock join
   Iran/Hormuz and Trump Tariffs). ✅ shipped 2026-08-09
5. **Critical events reach pockets**: severity-gated curator + web push
   (critical only — owner ruling 2026-08-09), dedup windows and a daily cap
   so a buzz is always worth a look.
6. **Media**: images/files/video attachments end-to-end, with Claude vision
   on images (video is store/play/share; Claude does not watch video).

## What moves forward from Phase 3

The scheduler organ (`dialectic/scheduler.py`, advisory lock, run ledger) is
built NOW, to P3's exact spec. ✅ shipped 2026-08-09 (`5efff93`), first jobs:
trading_reconcile, trading_freshness_watchdog, scheduler_heartbeat.

**P3 consequently shrinks** to brief content, night-shift guardrails, and
etiquette (owner decisions #3 unchanged) — its jobs `register()` onto the
existing scheduler. The freed weeks buffer P4.

**Ledger supersession**: the generalized `scheduled_job_runs` table
(migration 008, `UNIQUE (job_name, scheduled_for)`) replaces P3's planned
`night_shift_runs` (migration 009). Migration numbers in the committed plan
are logical, not literal — each lands on the next free number.

## What this reinterprets (on the record, for Dan)

VISION.md: *"It writes messages and memories — it does not take external
actions."* Ruling recorded: **reading our own systems is not acting.** Every
tool in Phase 2.5 is a GET or a pure what-if against services we run. The one
write-shaped capability — `draft_prediction` — produces a PROPOSAL a human
must tap to accept (identical etiquette to P4's commitment proposals), ships
only after a trust week of read-only tools (owner ruling 2026-08-09), and the
human's tap performs the external write, not Claude. Order placement remains
categorically out. Kill-switch: `DIALECTIC_TOOLS_ENABLED`.

## Governance

- **Monorepo**: tradingDesk moves into this repo as `trading/` via git
  subtree (owner ruling 2026-08-09); one CLAUDE.md, one plan governs. The
  872MB SQLite DB relocates to `/var/lib/tradingdesk/` (never enters git).
- **What dies**: tradingDesk's duplicated social tier (chat rooms/messages,
  LLM chat proxy, Field Desk cockpit) sunsets after tools ship; its local
  login dies at P6 after 30 days of bridge-only auth. Kept with landing
  places: Thesis Builder + DAG canvas (deep surface), /api/llm/compare
  (deep-surface power tool; "Panel of Rivals" protocol candidate next
  quarter), prediction tracker + journal UIs (panel-port candidates next
  quarter).
- **Scheme abstraction reaffirmed**: trading is the hot room, so the organ is
  built against trading first; P5 generalizes a LIVING template into
  `rooms.scheme_state` exactly as written.

## Untouched

P1 (shipped), P2 scope, P4 FSM, P6 benchmark + cleanup, and all six owner
decisions in the original plan. The wire-or-delete track gains rows (working
plan §C4) but loses none.
