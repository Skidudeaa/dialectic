# Handoff — 2026-09-02: the enjoyment experiment, the working-surface mocks, and the delivery protocol

For a fresh session with zero context. Everything below is verified against
the tree, the live database, or the running process at the time of writing.

## 1. What is live in production right now

Commit `27d926b` on master (pushed). Backend `dialectic.service` PID
`1221990`, started 2026-09-02 21:27 CDT, `/health` 200. PWA release
`/var/www/dialectic-releases/20260903T022739Z-your-move-27d926b`, bundle
`index-CkAbCH6U.js`. No migration.

Flags in `dialectic/.env`, confirmed in `/proc/<pid>/environ`:

| flag | value | effect |
|---|---|---|
| `ANNOTATOR_ENABLED` | 0 | annotator posts nothing (`llm/annotator.annotator_enabled`, gate in `transport/handlers.py`) |
| `DIALECTIC_ADDRESSED_ONLY` | 1 | orchestrator skips the interjection engine unless the participant is mentioned (`llm/heuristics.addressed_only`) |
| `ROUND_DAILY` | 1 | every morning is a round morning (`question_round.is_round_day`) |
| `ROUND_ROOMS_PER_DAY` | 1 | one qualifying room per day, rotating by oldest last round (`rotate_rooms`) |
| `QUESTIONS_PER_ROUND` | 1 | one question |
| `PARTICIPATION_SWEEP_ENABLED`, `READING_ECHO_ENABLED`, `WIRE_ENABLED`, `NEWS_DIGEST_ENABLED` | 0 | the chatty jobs |

Untouched and still firing: morning brief 07:00, trading curator, `world_watch`,
`prediction_watch`, `claim_check`, `house_forecast_sweep`, `round_close_watch`,
protocols, forced turns.

New surfaces: `GET /rounds/moves` (`api/rounds.py`, names never numbers, the
house never appears) and `frontend/app/src/components/home/YourMove.tsx`, the
strip above the Home pulse. What Changed entry `your-move` in `lib/releases.ts`.

Amend-beside entry: `dialectic/CLAUDE.md` § "Amendment 2026-09-02".

## 2. Why, in numbers (the baseline the experiment is scored against)

- All time: 629 machine messages to 309 human; the annotator alone 326.
- Iran/Hormuz room, 30 days to 2026-09-02: 277 machine to 113 human, 4 replies,
  13 messages with a tool call recorded, 0 readings linked to the message that
  produced them.
- The Round fired every Sunday since 2026-08-23 and its blind reveal never
  triggered. On ship day: 23 open questions; Dan had forecast 9 of them, Amo 1.
  The adoption gap was the owner's own.

**Score it around 2026-09-16.** Two numbers: human messages per day (all
rooms, `messages.speaker_type='human'` via `threads`), and whether both
humans forecast the daily question (`commitment_confidence` rows with
`actor='human'` per `commitments.category='round'`). If neither moves, the
voice was not the lever and no layout would have been.

**Rollback**: restore the nine env lines, `systemctl restart dialectic`. The
YourMove strip is harmless to leave.

## 3. What is NOT done, on purpose

- "Dialectic speaks when it disagrees" needs a stance signal that does not
  exist. Addressed-only is the strict version.
- Presence-based register (moderator when both present, sparring partner when
  one) is designed, not built. `presence.py` is the one predicate to read.
- Readings linked to the message that pasted them: `reading_items.source_message_id`
  is null for every reading in the Hormuz room. A write-path gap; the four-shapes
  prototype's empty readings column is this.
- The working surface itself. Two mocks exist, both on real data, neither is code
  in the app:
  - Hormuz surface (graph + atlas + conversation anchored to nodes + updates tray,
    verbs on nodes, simulated Dialectic replies from the book's own text):
    https://claude.ai/code/artifact/d54da524-1576-4534-b919-a8a0c1c68ad0
    (source `scratchpad/mock/` of session `018sr8dyQ3ibj2qViTyvCRg9`; the
    generator queries are in that session's transcript, not in the repo).
  - Four conversation shapes over the real 30-day Hormuz corpus (stream+rail,
    tree, lanes, cut-the-volume; a third party's React prototype re-fed with
    `gen_corpus.py`): https://claude.ai/code/artifact/384f4fdd-76f4-475b-8760-47daa0befbd7
    Source zip: `reactSuppliment.zip` at repo root (untracked). Its stack
    (Tailwind, shadcn) does not port; treat as a sketch.
  - Owner's stated direction: conversation is the base unit; a shared,
    manipulable surface tied to theses, atlas, updates; reply/react must be
    visible to the other person; thoughts need visible boundaries; rooms must
    look different; Home must not move in the sidebar; use the width (panes
    side by side, not one scene at a time). Owner's verdict on the mocks so
    far: "it's a start", and all four of my own listed gaps (graph is a
    diagram not a surface; conversation is a rail not on the surface; map is
    decorative; machine volume untouched) were confirmed.

## 4. The delivery protocol (separate repos, local only, no remote)

- `/root/protocol-template` (git, 4 commits): Master Prompt v3.1 split by
  lifetime, then "C with B": `control/protocol.py` runs one
  `claude -p --agent <role>` per role run and writes the manifest, scope
  verdict, evidence chain and hash-chained ledger itself; three roles
  (builder, verifier, critic); judging, RCA, adversarial, traceability and JSON
  schemas suspended (`docs/PROTOCOL.md` v3.2 amendment). Qualified by
  `control/test_protocol.py` (6 rejections before 3 acceptances). Verified on
  Claude Code 2.1.258: settings.json PreToolUse hooks fire inside subagents and
  carry `agent_type`; the fork env var is `CLAUDE_CODE_FORK_MODE`.
- `/root/protocol-runs/dwoodamo-firms`: DwoodAmo frozen at `e29cbf0` (history
  after it pruned), overlay commit `0e697af`, `docs/BRIEF.md` written to rebuild
  the FIRMS fire layer as a §16 process audit. Isolated DB `dialectic_protocol`
  (`DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_protocol`),
  64 world tests and 650 frontend tests pass there. Reference (critic-only):
  `/root/protocol-runs/reference/firms/`. **Never launched**; the owner
  redirected to UX. Launch is `cd /root/protocol-runs/dwoodamo-firms && claude --agent orchestrator`.
- Operator persona: `~/.claude/AGENT_INSTRUCTIONS.md`, imported by
  `~/.claude/CLAUDE.md`.

## 5. Untracked files at repo root, deliberately not committed

`AGENTS.md` (Codex analog, owner's), `IMG_0197.PNG`, `Hormuz Working Surface.png`
(owner's iPad screenshot of mock v2), `reactSuppliment.zip`, and the
`docs/diagrams/gods-eye-integration.visual-check.*` outputs from a prior session.

## 6. Suites at this gate

Backend 2275 passed (one deselected: the known
`test_reading_capture_endpoint::test_capture_rejects_non_postgresql_text_without_database_write`
unicode failure, pre-existing). Frontend 655/655. `tsc -b` and eslint clean.
