# Handoff — the connection, and the Sunday Round (2026-08-19/20)

Zero-context authority. Everything below is **committed and DEPLOYED** except
where marked. Verify current truth before acting; do not redeploy to "apply"
this document.

## The ask

*"make dan and my connection and tools on this app work and dream up and
impliment capabilities that will make us giggle."*

Mid-session the owner named the capability himself: *"a good judgment style
list of questions (weekly? Sunday)… I remember looking forward to the new round
of good judgment questions"* — and then the fact that reframed everything:
**he and Dan were IARPA/ACE Good Judgment Project superforecasters.** The bar
for the feature is real GJP form, not a quiz.

## What shipped

| Commit | What |
|---|---|
| `269cd54` | The connection — push taps that land, cross-room presence, one presence predicate, the seam timeout law, the cairn fence |
| `49e3129` | The Sunday Round — job, forecast door, scoring rule, card |
| `9084c4e` | Round size dial + shipped dark |
| `15f61ea` | `dialectic/CLAUDE.md` amendment |
| `05e479e` | A round needs two people — the room filter, found while arming |

Release `20260819233503-sunday-round`, symlink flipped, nginx reloaded, backend
restarted (PID moved 3644589 → 1672664, `/health` 200 in 1s, 13 jobs
registered, zero errors in the log since).

## Owner rulings — do not re-litigate without asking

- **Blind until both commit.** Neither forecast is visible until both are in.
- **Time-weighted average Brier**, the ACE rule, not final-answer.
- **Drafted with a veto** — either may bin a badly-formed question; binned is
  never scored.
- The participant may be **sharp and unprompted** about the track record.
  *(This one is RULED but NOT BUILT — see Open below.)*

## The finding that mattered most

The calibration spine shipped 2026-08-18 and by 08-20 held five predictions,
four of them the same duplicated gate-proof row, none resolved. **Nothing was
wrong with the scoring — nothing was ever asked.** All four rows in
`commitments` have `deadline IS NULL`, including both Dan and Amo personally
accepted, because `MessageBubble.tsx`'s Accept tap sent no deadline and no
confidence and `stakes/detector.py`'s extraction prompt never asked for a
deadline. `api/stakes_relay.py` then correctly refused to relay them.

The Round fixes this by construction: a round question is born with its close
date as its deadline.

## Contracts a future session must know

Everything is in `dialectic/CLAUDE.md`'s 2026-08-20 amendment. The four that
bite hardest:

1. **Forecasts are ROWS** (`commitment_confidence`), never JSONB in message
   metadata. `schema.sql:249-259` states the rule and this repo has no
   array-append-into-JSONB idiom. My own first draft got this wrong.
2. **Blindness lives in the READ** (`api/rounds._round_state`), not the UI.
3. **Same-day activity has no lateness gap** — the last forecast of a day
   governs that day. A test of the multi-day rule must backdate `recorded_at`,
   or it asserts something the rule does not claim.
4. **`presence.py` is the single predicate.** If you add a fifth reader of
   `user_presence`, use it. The bug it fixes is invisible: a stranded `'online'`
   row silently disables push/annotator/curator for one member of one room.

## The Round is ARMED (2026-08-20, owner: "un-darken it")

`QUESTION_ROUND_ENABLED=1`, `QUESTIONS_PER_ROUND=5`, backend restarted
(PID 1672664 → 359070, `/health` 200 in 4s, both vars confirmed in
`/proc/<pid>/environ`, zero errors since).

**First fire: Sunday 2026-08-23, 09:00 America/Chicago.** Proven silent in
between — running the job live on a Thursday returns
`{'skipped': 'not_sunday'}` against a pool that raises on any acquire, so the
gate returns before it touches the database rather than merely existing.

**Four rooms qualify, so 20 questions land that morning** — Iran/Hormuz, AI
Capex Unwind, Japan Rate Shock, China Property Cascade. That is 40 forecasts a
week between the two of them. The owner was asked to choose a volume and did
not answer, so it ships at the built default; **the recommendation on the table
was 3/room (12 a week)** on the grounds that a question nobody forecasts scores
nobody. Changing it is one env var and a restart, no code:

```bash
# dialectic/.env
QUESTIONS_PER_ROUND=3        # 1..10, clamped
systemctl restart dialectic  # NEVER with uncommitted edits in the tree
```

`ROUND_SYSTEM` in `llm/question_round.py` is the question quality bar and is
the thing to edit if the questions come out weak. Env backups:
`/root/dialectic-env-backup-20260820.txt` (pre-Round) and
`-prearm.txt` (pre-arming).

### The bug arming exposed

Five rooms qualified, and one was **"Hi Dan!" — one member, and that member the
retired `namosson+retired-test12` account.** Not merely a wasted draft: a
question stays sealed until BOTH forecasters commit, so in a one-member room
`revealed` can never become true. It would have drafted five questions a week,
forever, into a room where none could ever be read. The selection now requires
**≥2 members** and **human** traffic (thirteen jobs post into rooms on their
own, so `messages` alone keeps a dead room looking alive). Mutation-verified.

## Open, in rough order of value

1. **Volume is unruled.** Armed at 5/room = 20 questions every Sunday. The
   recommendation was 3/room; the owner has not chosen. One env var.
2. **The first real round is unobserved.** Nobody has seen a question this
   thing writes. Read the 2026-08-23 output before assuming `ROUND_SYSTEM` is
   good enough — the parser drops malformed blocks silently, so a bad prompt
   shows up as a SHORT round, not an error. Check
   `journalctl -u dialectic --since "2026-08-23 09:00"` for
   `no_valid_questions`.
3. **The sharp-voice ruling is unbuilt.** The participant reading its own and
   their track record aloud — the resolution callback ("Dan called this at 85%
   on Aug 17") — is designed, not written. It needs resolved questions first,
   so it is naturally downstream of arming the Round.
4. **The commitment Accept card still asks for neither deadline nor
   confidence** (`MessageBubble.tsx:322`, `stakes/detector.py:96-99`). The Round
   routes around it; the ordinary path is still unscoreable. The approved plan's
   two-human vote card covers this and was superseded by the Round, not done.
5. **`llm_decisions.tool_calls` is double-encoded** (`self_model.py:257-259`
   pre-dumps into a codec that already dumps), so tool analytics read empty.
   Observability only, but it is what makes "are the tools working" unanswerable
   by query.
6. `save_reading` discards a written summary when the re-fetch 403s. Ten of
   twenty tools have never been called in production. Polymarket is configured
   for none of the live rooms and Iran/Hormuz polls a market that resolved in
   April.

## Honest edges

- **The push fix is not closeable from this machine.** The service worker
  updates on resume, so it lands on Amo's next foreground — and a fresh-profile
  probe is blind to installed-app staleness. Confirm on his device before
  reporting complaint #1 closed.
- **`others_present` was verified positive only in a rolled-back transaction**
  (nobody was online at deploy time). The live projection ran clean across all
  five of Amo's rooms, but every list was empty. First real two-person overlap
  is the actual proof.
- One pre-existing backend failure remains:
  `test_home_activity_pg::test_only_active_commitments_due_within_72h`. It fails
  on a clean tree and this diff never touches `home_activity`.
- The audit proposed keying the GDELT cooldown per-book. **Refused** —
  `trading/web/routes/bridge.py:535` documents that GDELT limits by caller IP,
  so per-book would draw five times the 429s.
