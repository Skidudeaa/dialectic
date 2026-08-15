# Dialectic — Feature Tour & Manual

Two humans and an AI think together in real time. The AI is a **participant**:
it decides when to speak, remembers who said what, checks live market data
mid-argument, and keeps score of what you both committed to.

Live at **https://dialectic.somacura.org** — built by and for Amo and Dan.
New here? Start with the five-minute jump-in at the [root README](../README.md).
This file is the complete tour.

## Getting in

1. Open https://dialectic.somacura.org and sign in (invite-only; Amo has credentials).
2. Install it as an app: Android Chrome → ⋮ → *Add to Home screen*; iPhone Safari →
   Share → *Add to Home Screen*; desktop Chrome/Edge → install icon in the address bar.
3. Tap the 🔔 **Enable notifications** chip once per device. This is what makes
   your pocket buzz with the app closed. Tapping a notification lands in the right room.
4. The green **Connected** dot means real-time sync is live. If it drops, reload
   before writing — unsent text stays in the composer.

## Home

Opening the app on a bare URL lands in **Home** — one real room shared by the
founders, where the three of you actually live. Home is a normal conversation
(memory, protocols, stakes, Claude participation all work), plus a **shared
activity pulse**: every scheme room that ALL current Home members belong to
shows its unread count, latest line, changed branches, open questions, and
commitments coming due. Tap a room or branch card to land exactly there.
Claude sees the same digest (and only the same digest) when it speaks in Home.

Membership is deliberately narrow: only Amo and Dan can add someone (Home
tab in the right rail), added members cannot add anyone else, and a room
appears in the pulse only while *every* Home member belongs to it — adding a
person immediately contracts what Home shows. Home can never hold a thesis;
its Trading tab explains where theses live instead of offering the form.

*(Live since 2026-08-12: Amo and Dan are the founding members. A room shows
in the pulse only when every Home member belongs to it — a room nobody has
joined, or that's missing one member, stays out until the membership catches
up.)*

## The room, and its places

A room is you, Dan, and Claude. One room per durable scheme or thinking stream.

A room is a **workroom**, not a chat window. The tabs under the room title are
its places (the active one shows a one-line hint of what lives there):

| Place | What it is |
|---|---|
| **Record** | The exact transcript — searchable, attributable, never paraphrased |
| **Bench** | The thesis under construction — causal graph, live market, open trades, what-ifs |
| **Field** | Provisional reasoning — support, tension, and synthesis candidates awaiting your review |
| **Library** | What the room has actually read — filed evidence, one entry per source |
| **Ledger** | What the room holds itself to — commitments, dossier entries, memories |

Home has its own places: **House** (movement across every shared scheme),
**Atlas** (the whole house mapped — rooms, artifacts, echoes, crossings), and
its Record.

| You want… | Do this |
|---|---|
| Claude to answer right now | `@Claude <message>` — streamed reply, watches it work |
| Claude to join on its own judgment | Just talk. It speaks on questions, stagnation, topic shifts, turn imbalance |
| Claude to only speak when summoned | Room settings → **auto-interjection** off |
| A message's role to matter | Mark it **Claim**, **Question**, or **Definition** before sending |
| A side branch | **Fork** any message — inherits everything above the fork point |
| Something remembered | **Memory** panel — or just restate it; restating *updates* the fact and keeps the old version's history |
| A structured argument | **Protocol**: Steelman, Socratic, Devil's Advocate, or Synthesis — Claude facilitates phases and writes conclusions to memory |
| A prediction tracked | **Stakes** — confidence updates, deadlines, Brier calibration. Claude can draft one for you (below) |
| To catch up | The "new since you were here" line + Claude's annotations about what happened without you |

## Claude's hands and eyes

- **Live data mid-argument.** "What's oil at?" "Any news on the Hormuz thesis?"
  "What if Hormuz closes — run the scenario." Claude checks the desk: live quotes,
  Polymarket odds, thesis state, what-if scenarios, headlines, open trades — plus
  the room's own memory and transcript. You see "*Claude is checking live prices…*"
  while it works, and a "used N tools" footer on the answer you can expand to audit
  every fetch. This works on `@Claude` AND when Claude jumps in unprompted.
- **It sees images.** Attach, paste, or drag-drop a chart → "@Claude what's wrong
  with this?" Files and video upload too (video is store/play/share — Claude
  doesn't watch video).
- **It follows up on silence.** Ask Claude something and walk away: after ten
  quiet minutes it follows up — once. Hard limits: 3 per room per day, silent
  11pm–7am CT, off entirely if the room's interjection toggle is off.
- **It drafts, you dispose.** Claude proposes; only your tap creates. Three
  surfaces, one trust shape:
  - a proposed **prediction** carries an Accept card — your tap posts it to
    tradingDesk;
  - a proposed **thesis** ("we should book this") carries a card that opens the
    Create Thesis panel pre-filled, where Claude drafts the causal cascade for
    your review and Accept & Create mints the book, born bound to the room;
  - a heard **commitment** ("I bet…", "mark my words") gets a card under your
    own message — "Put it on record" logs it to the room's stakes, and the card
    disarms for both of you.
  Claude never writes to the desk itself. Order placement is not a thing and
  won't be.
- **Rooms birth their theses.** The Bench's empty state IS the create
  surface: title + claim in, Claude-drafted DAG for review, first snapshot in
  the panel within seconds. Retire from the panel footer when a thesis
  resolves — the book survives on the desk, and the room can birth its
  successor.
- **The whole cockpit works on your phone.** Below 1024px the room list and the
  right-rail cockpit are slide-over drawers (☰ and ▦ in the header) — memory,
  trading, stakes, everything, with the same behavior as desktop.

## The five trading rooms

Iran/Hormuz · Trump Tariffs · AI Capex Unwind · China Property Cascade · Japan
Rate Shock — each bound to a live thesis book on the desk:

- **The Bench is the cockpit** (since 2026-08-14). A bound room's Bench renders,
  natively: the **causal graph** (phase columns, live node states colored onto
  the authored structure, click any node for its thresholds and gates), the
  **market strip** (live quotes), **Polymarket odds**, **alert events**, the
  **hourly diff**, **open trades** with their resting predicates, **scenario
  what-ifs** (Evaluate runs a hypothetical against the live snapshot — nothing
  is ever placed), the **morning brief**, and **thesis news**. Everything
  Claude's tools can see, you can see.
- Thesis state (cascade phase, fired/approaching nodes, confluence, countdowns)
  is in Claude's context for every reply — within minutes of anything moving.
- A **critical** node flip buzzes both pockets. Warnings stay in-room; heartbeats
  are silent. If the feed ever goes quiet 3+ hours, a watchdog says so in the room.
- The one remaining crossing to td.somacura.org is **Open Builder** — the deep
  DAG-*editing* instrument (restructure nodes/edges), reached from the Bench
  with no second login (72h bridged session). The old "Open Full Dashboard"
  link is gone because the dashboard now lives in the Bench.

## The daily rhythm

- **7:00 AM CT — Morning Brief** in every room that had activity: yesterday's
  threads, unanswered questions, commitments due within 72h, thesis staleness.
  Posted in-room, pushed to both phones. Quiet rooms are skipped.
- Coming back hours later: catch-up annotation ("Connected to / Tension detected /
  For when Dan returns") waiting on your messages.

## Honest limits

- Claude's memory recall can surface **stale facts as if current** (old prices,
  old uptime numbers). If a number matters, make it fetch live — that's what the
  tools are for. Benchmark-driven memory tuning is this quarter's P6.
- The OpenAI fallback can't see images and can't use tools — on fallback Claude
  says so rather than pretending.
- Claude does not take external actions. Ever. The one write-shaped capability
  (prediction drafts) executes only on a human tap.

## Local development

```bash
cd dialectic && pip install -e .
createdb dialectic && psql dialectic < schema.sql
cp .env.example .env   # DATABASE_URL, ANTHROPIC_API_KEY, JWT_SECRET_KEY required
PORT=8002 python3 run.py                      # backend on :8002
cd frontend/app && npm install && npm run dev # frontend on :3000
python3 -m pytest tests/ -q                   # ~1335 tests
```

`frontend/app` (React/Vite/TS) is the only live frontend; the legacy
`frontend/app.html` is retired.

## Feature flags (all in `dialectic/.env`, all default ON)

| Flag | Gates |
|---|---|
| `SCHEDULER_ENABLED` | The whole job scheduler |
| `NIGHT_SHIFT_ENABLED` | The 7am morning brief |
| `PARTICIPATION_SWEEP_ENABLED` | The 60s silence-follow-up sweep |
| `DIALECTIC_TOOLS_ENABLED` | All LLM tool use |
| `DIALECTIC_VISION_ENABLED` | Image blocks to Claude |
| `COMMITMENT_DETECTION_ENABLED` | "I bet…" → put-it-on-record cards |
| `CAIRN_TOOLS_ENABLED` | The cairn dev-memory tool group |
| `SIGNUPS_ENABLED` | Open signup (keep `0` — invite-only) |

## How it's built (one paragraph + map)

FastAPI + asyncpg over Postgres 16 (pgvector + pg_trgm), event-sourced — the
append-only `events` table is the truth; Anthropic primary / OpenAI fallback via
a retrying router; React PWA over WebSocket; systemd units run the git working
trees (deploy = migration → `systemctl restart dialectic` → frontend release
symlink flip). Full conventions: [`CLAUDE.md`](CLAUDE.md).

```
api/         REST + WS + auth + push + attachments + prediction relay
llm/         orchestrator · tool_loop + tools (19) · vision · heuristics ·
             prompts · self_model · participation_fsm · annotator ·
             briefing · night_shift · silence_sweep · trading_curator
memory/      three-lane RRF recall (dense + FTS + speaker) · dedup · supersession
scheduler.py advisory-locked jobs on a double-fire-proof run ledger
transport/   WebSocket dispatch, Redis pub/sub
stakes/      commitments + Brier calibration
analytics/   conversation DNA, briefings, knowledge graph
replay/      event replay + state materialization
frontend/app React PWA
migrations/  017 current; schema.sql = fresh-DB baseline (014's reading_items
             is migration-only — a fresh DB needs the migrations too)
tests/       pytest (~1335) incl. real-Postgres integration tests
```

Task board: [`TODOS.md`](TODOS.md) · Quarter plan + Amendment 1: `../docs/plans/`
