# Handoff — "the dam llm won't shut up in the rooms" (2026-08-15, evening)

**State: shipped, deployed, verified.** Master `5e36d43`. Backend restarted
17:39:26 CDT, health 200 (db connected, scheduler fresh, redis connected).
Backend suite **1376 passing**. No migration, no frontend change.

This session had two halves: a survey of what remains in the project's plans
(§5 below, unchanged by the work), and a measured fix for LLM volume in the
rooms. The volume work is complete; the observation window is not.

---

## 1. What was making the noise, and what shipped

Three findings, measured against the live DB and the journals — none guessed.

### The loudest source was not a heuristic

`tradingdesk-bridge.timer` (`OnCalendar=*:00/30`) was still running
`tools/bridge/run-all.py`. **Its own unit description reads "interim; removed
when coordinator push deploys."** The coordinator's inline push shipped weeks
ago; the timer never left.

Its payloads stamp **`v: 2`**, and `api/trading_ingest.curator_plan()` gives
v1/v2 the legacy *alert on every receipt* branch. The whole point of the v3
contract is that `alertEvents: []` means *nothing happened, stay quiet* — so
tradingDesk's own hourly v3 heartbeats were correctly silent while a redundant
duplicate of them chattered every 30 minutes.

    snapshot_v | curator_alerts        -- all curator messages ever
    -----------+---------------
             2 |            32
             3 |             3

**Timer stopped and disabled** (`systemctl stop/disable tradingdesk-bridge.timer`,
verified inactive + disabled after a `daemon-reload`). The coordinator pushes
all five books — 9 heartbeats each on the day of the fix.

### The curator had no content gate at all

Every guard it had was a clock: `is_duplicate` is a 5/30-minute window,
`CURATOR_DAILY_CAP` an 8/day ceiling. A snapshot repushed every 30 minutes
clears a clock by waiting. **Japan Rate Shock took 21 alerts in three days off
ONE unchanged snapshot**, each opening `ALERT (19th confirmation — STALE, do
not action)` — the model knew, and had no way to decline.

`llm/trading_curator.py` now carries `snapshot_fingerprint()` +
`is_unchanged()`, comparing the CAUSAL content against the room's last curator
alert:

- **In:** `nodeStates`, `cascadePhase`, `countdowns`, `alertEvents`.
- **Out, deliberately:** `timestamp` / `revision` / `generatedAt` (they move on
  every push by construction — hashing the payload would fingerprint the
  clock) and `marketSnapshot` (a fourth decimal on usdJpy is not a reason to
  wake anyone, and including it would hand the always-different behaviour back
  through a different field).
- Compared against the **last** alert only, so a state that reverts and returns
  is news again.
- A pre-fingerprint row reads SQL NULL → **"this is news"**. The opposite
  failure is a permanently muted trading room, which is worse than the noise.

### `heuristics.decide` gained rung 0 — the first rung that can decline

A message that OPENS by addressing people who do not include us is not our
turn. It **outranks the explicit mention**, because a message can name the
participant while talking to someone else. The originating case, Home, this
evening:

> `@amo feature idea can you make it highlight the name if it is one of us and
> make the @llm a different color`

That contains `@llm`, so mention detection fired rung 1 and the participant
answered a request addressed to a human — opening, accurately, "This one's not
for me to weigh in on." *Being right about that in the reply is not the same as
staying out of it.*

`llm/mentions.addresses_someone_else()` reads the **address block** — the
leading run of `@handles` — and leaves everything else alone, so a mid-sentence
"hey @dialectic what do you think" still summons. Measured over the week:
**10 of 45** `@`-opening human messages would be silenced.

---

## 2. Gotchas worth carrying (each cost time here)

- **If `tradingdesk-bridge.timer` ever comes back, so does the noise.** Its
  v2 payloads still take `curator_plan`'s legacy branch; only the new content
  gate stands between it and a repeat. `systemctl daemon-reload` also warned
  the unit file had "changed on disk" at some earlier point — the units in
  `/etc/systemd/system/` are not in git, so nothing records who edited them.
  A manual `python3 tools/bridge/run-all.py` remains a legitimate operator
  action and is now content-gated rather than silenced.
- **The curator calls `claude-sonnet-5`**, not the Haiku its module docstring
  claims ("TRADEOFF: Extra LLM call per snapshot (Haiku = cheap)"). Those 21
  repeated paragraphs were Sonnet calls. Docstring left alone; noted here.
- **`tests/test_trading_curator.py`'s `make_mock_db()` returns ONE dict for
  every `fetchrow`.** Adding any new `fetchrow` to `generate_alert` breaks
  unrelated tests with a `KeyError` on the column you added — that is a
  harness artifact, not a product bug. The mock now carries
  `{"sequence": 1, "fingerprint": None}`.
- **Those mocked tests assert the shape of a query that never ran.** That is
  why `tests/test_trading_curator_pg.py` exists (6 real-Postgres contracts,
  skips cleanly without `dialectic_test`). Do not trust a green mocked curator
  test as evidence that SQL binds.
- **`messages` has no `room_id`** — reach it through `threads`. (Already in
  `dialectic/CLAUDE.md`; it bit again here.)
- **A probe lesson:** the first live verification flipped `boj-decision` to
  `fired` to prove a moved state changes the fingerprint. It read "no change" —
  because that node was *already* `fired`. The probe was wrong, not the code.
  Confirm the input you varied actually varied before reading anything into a
  failing probe.
- **`journalctl --since` parses LOCAL time; app logs stamp UTC.** The alert
  cadence only became legible after converting: every Japan alert lands 50–140s
  after a `:00/:30` tick, which is what pinned the timer.

---

## 3. What was checked and found HEALTHY — do not "fix" these

- **The wire's two Iran/Hormuz repeats today are correct behaviour.** The
  model wrote "a repeat of the shared-memory entry already logged for this
  exact URL", which reads like a dedup bug; `reading_items` shows two
  *different* URLs (dw.com and econotimes) on the same story, 2 against a cap
  of 4. That is editorial judgment, not a defect. `seen_urls()` works.
- **`trading_reconcile` correctly suppresses the curator** via
  `?source=reconcile` → `fire_curator=False`. It was the prime suspect from
  the cadence and it is innocent.
- **`reading_echo`** posted 19 messages on 08-13/14 and nothing since — not a
  live source tonight.

---

## 4. Next steps

1. **Observe the window (the reason this handoff exists).** The address rung
   is proven by unit tests, a mutation kill, and corpus replay — **not** by a
   live message in a real room. And the curator gate has not yet had a chance
   to suppress anything in production, because the timer that fed it is gone.
   Tomorrow, confirm:

       -- expect: only entries whose thesis state actually moved
       SELECT m.created_at, r.name, m.metadata->>'snapshot_v' AS v,
              m.metadata->>'snapshot_fingerprint' AS fp
       FROM messages m JOIN threads t ON t.id=m.thread_id JOIN rooms r ON r.id=t.room_id
       WHERE m.metadata->>'source'='trading_curator'
         AND m.created_at > '2026-08-15 22:39:00+00' ORDER BY 1;

   Baseline for comparison — machine vs human messages per day:

       08-13:  5 human / 37 machine      08-14:  4 human / 34 machine
       08-15:  7 human / 19 machine (fix deployed 22:39 UTC)

2. **Relax `ANNOTATOR_DAILY_CAP`.** It is `5` in `.env` as a stopgap from
   before the worth gate landed (see `dialectic/CLAUDE.md`, amendment
   "the annotator worth gate"). Both are live now and they stack, so 5 is
   doing the cutting the gate was meant to do and the gate's real effect stays
   invisible. Move toward 12 after a few days of observation.
3. **The real fix is still not done:** `InterjectionEngine.decide`'s rungs 1–7
   vote only YES and return on first match, so silence is reachable only by
   falling through all seven, and `confidence` is recorded after the decision
   rather than used to make it. Rung 0 is the one case where the room had
   already said whose turn it was — it is not the re-shaping.
4. **`_schedule_effectiveness_measurement`** remains a fire-and-forget
   `asyncio.sleep(30)` task with no retry; a restart inside the window loses
   the row. `human_responded` is a pure function of `messages` and would be
   better derived at read time than snapshotted on a timer. (Carried from the
   morning's amendment, untouched.)

---

## 5. The project queue, as surveyed at the top of this session

Unchanged by tonight's work; recorded so the next session does not re-derive it.

- **The Living Workroom program is COMPLETE** — R1 (08-13), R2 (08-13), R3
  (08-14) all gated and live. The C4 cull and Bench cockpit (08-14) also closed
  the human-interaction audit's first two P0s: verified in the tree —
  `trading/frontend/src/components/dialectic/` no longer exists, and
  tradingdesk restarted 08-14 23:28, after `e234212`.
- **Two owner decisions still open** — gate ledger
  `docs/superpowers/plans/2026-08-14-dialectic-release-3-deliberation-gate.md`
  §9: the five-device checklist, and one unambiguous yes on deleting stray room
  `eeffa8f1-9d5a-4d31-981d-b5cf0a0627e8`.
- **Audit follow-through** in `dialectic/TODOS.md`: 3 P0s remain (proposal
  inbox/deep-links/receipts; a real invite + email-verification + password
  recovery with actual delivery; replacing dead/silent/false states), 6 P1
  journeys, 5 P2 wire-or-retire calls. *Not re-verified against code this
  session — the list is as the audit left it.*
- **The only substantial unbuilt FEATURES left** are quarter-plan P5 (night
  research `llm/researcher.py`; generalizing scheme state beyond trading) and
  P6 (LongMemEval-S three-arm benchmark, cleanup execution).
- Known deferred: F2 typographic voices (needs a contribution-vs-position
  field); `fieldViewport`/`recordScroll` stored with no capture point; Atlas's
  per-room `FieldMarkService` N+1 (27.3% of build time at seed scale).

---

## 6. Housekeeping

- **`JOURNAL.md` is left UNCOMMITTED on purpose.** It carries two lines from a
  parallel session plus one appended here; staging the file would sweep a
  peer's claims into someone else's commit. Whoever commits it next takes all
  three.
- The working tree also holds `trading/snapshots/*.json` (tradingDesk's own
  runtime churn) and an untracked `IMG_0197.PNG` — neither is this session's.
