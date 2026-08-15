# Dialectic

**Two humans and an AI think together in real time.** Not a chatbot you prompt — a third participant that listens, decides when to speak, remembers who said what, and keeps score of what you both committed to.

Live at **[dialectic.somacura.org](https://dialectic.somacura.org)** — built by and for Amo and Dan.

---

## Dan: jump in (five minutes)

1. **Install it as an app** on each device — same site, no app store:
   - **Android** — open the site in Chrome → ⋮ → *Add to Home screen* → *Install*
   - **Windows** — open in Edge/Chrome → click the *Install* icon in the address bar
2. **Sign in** with the credentials Amo sent you (they're not in this repo, obviously). You only sign in once per device — after that the app opens straight into the room.
3. **Tap the 🔔 "Enable notifications" chip** when you see it. That's what makes your pocket buzz when Amo or Claude writes while the app is closed.
4. **Talk normally.** The room is you, Amo, and Claude. Things worth knowing:
   - `@Claude` summons an immediate streamed reply; otherwise Claude decides for itself when to jump in (question detection, stagnation, novelty, turn count). If you'd rather it only speaks when summoned, that's the **auto-interjection toggle** in room settings — it works.
   - **Claude checks reality mid-argument.** Ask "what's oil at right now" and it goes and looks — live quotes, Polymarket odds, thesis state, what-if scenarios, the latest headlines. You'll see "*Claude is checking live prices…*" while it does, and every answer that used a tool carries a "used N tools" footer you can expand to audit exactly what it fetched and when.
   - **Paste a chart and ask what's wrong with it.** Images, files, and video go straight into the room (attach button, paste, or drag-drop) — and Claude *sees* the images.
   - **Ask Claude a question and walk away** — if nobody answers it for ten minutes, Claude follows up once. It won't nag: three a day per room, and it stays quiet 11pm–7am.
   - **Claude can draft predictions for the desk.** If it proposes one mid-chat, you get an **Accept** card in the message — your tap is what logs it to tradingDesk, never Claude itself.
   - Mark a message as a **Claim**, **Question**, or **Definition** when its role matters — Claude treats them differently.
   - **Fork** any message to explore a branch without derailing the main line. Branches inherit everything above the fork point.
   - **Memory** is the shared brain. Claude recalls by meaning, exact words, or speaker — "what did Dan say about the boat deal" finds it, attributed to whoever said it. Restating a fact *updates* it; the old version keeps its history.
   - **Stakes** turns predictions into tracked commitments with confidence scores — the app keeps calibration stats on how well you both actually forecast.
   - **Protocols** run structured inquiry: Steelman, Socratic, Devil's Advocate, Synthesis — Claude switches from participant to facilitator.
5. **The five trading rooms are all live** — Iran/Hormuz, Trump Tariffs, AI Capex Unwind, China Property Cascade, Japan Rate Shock — each fed by the desk within minutes of anything moving. Since 2026-08-14 the room's **Bench** IS the cockpit: the causal graph with live node states, quotes, Polymarket, open trades, scenario what-ifs, the brief and the news, all native — the one crossing left to [td.somacura.org](https://td.somacura.org) is **Open Builder** for deep DAG editing, no second login. A **critical** node firing buzzes your pocket; lesser noise stays in-room.
6. **Every morning at 7am CT there's a brief waiting** in each active room — yesterday's threads, unanswered questions, commitments due in the next 72 hours, thesis staleness — with a push to both phones.
7. When you've been away, the room shows a "new since you were here" line and Claude leaves catch-up annotations about what happened without you.

Full feature tour: [`dialectic/README.md`](dialectic/README.md).

## What this is

An experiment in collaborative cognition — a **consigliere for shared schemes**. Every scheme (a trade thesis, a deal, a project, a decision) is a room; every room has a third member that never forgets, never sleeps, and knows the difference between what Dan said, what Amo said, and what was decided. By day it argues, synthesizes, and keeps score. The next phases teach it to work at night: research on open questions, watch on deadlines and theses, a morning brief waiting when you wake.

The design stance throughout: **the AI is a participant, not an assistant.** It has heuristics for when to speak and when to shut up, a self-model of its own participation, an evolving identity shaped by the conversations, and a memory it maintains rather than a transcript it's fed.

Vision in full: [`docs/VISION.md`](docs/VISION.md) · Current quarter's roadmap: [`docs/plans/2026-Q3-consigliere.md`](docs/plans/2026-Q3-consigliere.md)

## What's live today

| | |
|---|---|
| **Installable PWA** | All four of our devices (Android, Windows, iPhone, Mac); session and room survive reloads |
| **Push notifications** | Web Push (VAPID) — lock-screen notifications with the app fully closed; tapping one lands in the right room |
| **Attributed memory** | Three-lane recall (semantic + full-text + speaker), write-path dedup, fact supersession with history |
| **LLM participation** | Heuristic interjection, @-mention streaming, provoker mode, offline-user annotations |
| **Thinking protocols** | Steelman / Socratic / Devil's Advocate / Synthesis, multi-phase, facilitated |
| **Stakes** | Commitments, confidence tracking, Brier-score calibration |
| **Claude's tools** *(2026-08-09)* | Eleven checks against the live desk and the room itself — quotes, Polymarket, thesis state, what-if scenarios, headlines, open trades, brief, memory + transcript search, prediction drafts — with visible activity and an auditable per-message tool trace, on the @Claude path AND the unprompted one |
| **Vision + media** *(2026-08-09)* | Images/files/video in the room (attach, paste, drag-drop); Claude sees pasted images. Attachments bind in the send transaction — no ghost delay |
| **Morning Brief** *(2026-08-09)* | 7:00 AM CT, per active room: missed threads, unanswered questions, commitments due ≤72h, thesis staleness — posted in-room + pushed |
| **Silence detection** *(2026-08-09)* | A state machine watches each room (engaged / question-pending / ignored / dormant); an unanswered question gets exactly one follow-up after 10 quiet minutes — capped 3/day, hushed 23:00–07:00 CT, disabled by the room's interjection toggle |
| **Proposal-writes** *(2026-08-09)* | `draft_prediction` — Claude proposes, a human taps Accept, the tap posts to tradingDesk |
| **Trading bloodstream** *(2026-08-09)* | All five thesis books event-driven into their rooms (push on change + hourly heartbeat + reconcile pull); a freshness watchdog tells the room if the feed ever goes quiet; critical alerts buzz pockets |
| **One login** *(2026-08-09)* | The desk trusts Dialectic sessions — the Bench's "Open Builder" deep-links into [td.somacura.org](https://td.somacura.org) with a day-long session; signups are invite-only |
| **One app** *(2026-08-14)* | The Bench renders the whole cockpit natively (DAG, quotes, trades, what-ifs, brief, news); tradingDesk's duplicate social tier is deleted (fusion plan §C4) — it is the engine + the Builder now |
| **Analytics** | Conversation DNA, room briefings, event replay timeline |

## What's next (the quarter)

Phased so something lands every week or two — full detail with acceptance checks in [the plan](docs/plans/2026-Q3-consigliere.md) and [Amendment 1](docs/plans/2026-Q3-consigliere-amendment-1-fusion.md):

1. ✅ **Pockets buzz** — Web Push end-to-end *(shipped; awaiting the real-device check)*
2. ✅ **Phase 2.5: The desk plugs in** *(shipped 2026-08-09 — the fusion above: bloodstream, tools, vision, media, one login)*
3. ✅ **The Night Shift** *(shipped 2026-08-09 — Morning Brief at 7am CT, per room, pushed)*
4. ✅ **Claude notices silence** *(shipped 2026-08-09 — the sidecar state machine ported; one follow-up after 10 quiet minutes. Remaining: spoken commitments auto-proposed for tracking)*
5. **Cross-room memory** — knowledge promoted to global in one room cited in another (the read path is live; the write path and promote-to-global UI are the remaining wiring)
6. **Overnight research + schemes beyond trading** — source-cited answers by morning; every scheme gets always-in-context state like the trading theses have (the pattern is now live and proven)
7. **Prove the memory** — LongMemEval benchmark, tuning, and closing every half-wired subsystem

## How it's built

```
dialectic/           The live product (FastAPI + React PWA, port 8002)
├── api/             REST, WebSocket, auth (JWT + room tokens), push,
│                    trading ingest, media attachments, prediction relay
├── llm/             Orchestrator, tool loop (11 tools), vision, heuristics,
│                    self-model + participation FSM, annotator, night shift
├── memory/          Three-lane RRF recall over pgvector + FTS + trigram, dedup, supersession
├── scheduler.py     The clock: advisory-locked jobs on a double-fire-proof
│                    run ledger — interval buckets + wall-clock daily slots
├── trading_watch.py Reconcile pull + freshness watchdog — stale feeds are structurally loud
├── transport/       WebSocket dispatch, Redis pub/sub
├── stakes/          Commitments and calibration
├── analytics/       Conversation DNA, briefings, knowledge graph
├── frontend/app/    React (Vite + TS) PWA — the only live frontend
├── migrations/      Applied in order (011 current); schema.sql is the fresh-DB baseline
└── tests/           pytest (790) incl. real-Postgres integration tests
trading/             tradingDesk — the market-cognition organ (port 8006):
                     causal-DAG thesis engine, coordinator push, bridge
                     endpoints, five live books. Folded in via git subtree.
cc-sidecar/          Claude Code observability daemon; its reducer/state-machine
                     patterns now power the LLM's participation FSM (P4)
packages/            React Native apps (mobile/macos/windows) — FROZEN, can't reach
                     production yet; the PWA is the reach strategy this quarter
docs/                Vision, quarterly plan + Amendment 1, handoffs, research records
```

Postgres 16 + pgvector + pg_trgm, event-sourced (append-only `events` table is the source of truth). Anthropic primary / OpenAI fallback via a retrying router. Single server, nginx + Cloudflare, no Docker.

## Developing

```bash
# Backend (port 8002; needs DATABASE_URL, ANTHROPIC_API_KEY, JWT_SECRET_KEY in dialectic/.env)
cd dialectic && PORT=8002 python3 run.py

# Frontend
cd dialectic/frontend/app && npm run dev

# Tests
cd dialectic && python3 -m pytest tests/ -q
```

Fuller dev docs and conventions: [`dialectic/CLAUDE.md`](dialectic/CLAUDE.md). Deploy is three independent steps (migration → backend restart → frontend release symlink) — the same file explains why that matters. Current task state: [`dialectic/TODOS.md`](dialectic/TODOS.md).
