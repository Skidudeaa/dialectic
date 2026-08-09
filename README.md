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
   - `@Claude` summons an immediate streamed reply; otherwise Claude decides for itself when to jump in (question detection, stagnation, novelty, turn count).
   - Mark a message as a **Claim**, **Question**, or **Definition** when its role matters — Claude treats them differently.
   - **Fork** any message to explore a branch without derailing the main line. Branches inherit everything above the fork point.
   - **Memory** is the shared brain. Claude recalls by meaning, exact words, or speaker — "what did Dan say about the boat deal" finds it, attributed to whoever said it. Restating a fact *updates* it; the old version keeps its history.
   - **Stakes** turns predictions into tracked commitments with confidence scores — the app keeps calibration stats on how well you both actually forecast.
   - **Protocols** run structured inquiry: Steelman, Socratic, Devil's Advocate, Synthesis — Claude switches from participant to facilitator.
5. When you've been away, the room shows a "new since you were here" line and Claude leaves catch-up annotations about what happened without you.

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
| **Trading integration** | tradingDesk pushes thesis state into the room; Claude reasons with live positions/triggers |
| **Analytics** | Conversation DNA, room briefings, event replay timeline |

## What's next (the quarter)

Phased so something lands every week or two — full detail with acceptance checks in [the plan](docs/plans/2026-Q3-consigliere.md):

1. ✅ **Pockets buzz** — Web Push end-to-end *(shipped; awaiting the real-device check)*
2. **Cross-room memory + real self-awareness** — knowledge promoted in one room cited in another; Claude's self-model wired into every reply path
3. **The Night Shift** — a scheduler and the Morning Brief: yesterday's threads, open questions, commitments due
4. **Claude notices silence** — the sidecar state machine ported; one well-judged follow-up when a question goes unanswered; spoken commitments auto-proposed for tracking
5. **Overnight research + schemes beyond trading** — source-cited answers by morning; every scheme gets always-in-context state like the trading thesis has
6. **Prove the memory** — LongMemEval benchmark, tuning, and closing every half-wired subsystem

## How it's built

```
dialectic/           The live product
├── api/             FastAPI — REST, WebSocket, auth (JWT + room capability tokens), push
├── llm/             Orchestrator, interjection heuristics, prompts, self-model, annotator
├── memory/          Three-lane RRF recall over pgvector + FTS + trigram, dedup, supersession
├── transport/       WebSocket dispatch, Redis pub/sub
├── stakes/          Commitments and calibration
├── analytics/       Conversation DNA, briefings, knowledge graph
├── frontend/app/    React (Vite + TS) PWA — the only live frontend
├── migrations/      Applied in order; schema.sql is the fresh-DB baseline
└── tests/           pytest (299) incl. real-Postgres integration tests
cc-sidecar/          Claude Code observability daemon; its reducer/state-machine
                     patterns are being ported INTO the LLM participant (plan §P4)
packages/            React Native apps (mobile/macos/windows) — FROZEN, can't reach
                     production yet; the PWA is the reach strategy this quarter
docs/                Vision, quarterly plan, research records
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
