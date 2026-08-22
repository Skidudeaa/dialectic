# Finding — the Sunday Round's forecasts reach the desk ledger labelled "LLM"

**Date:** 2026-08-21 · **Found during:** the legibility build (explain-everywhere UI)
**Severity:** high, and time-boxed — the Round's first fire is **Sunday 2026-08-23 09:00 CT**

## Status: FIXED 2026-08-22, before first fire

Owner's ruling: *"should be labeled both human and who proposes (can be 1 or
more humans)."* Shipped as **one desk row per (commitment, forecaster)**:

- `source_key` carries the forecaster — `stake:{id}:{user_id}:created` and the
  same for `:confidence:{seq}` and `:resolved`. It had to go in the KEY, not
  just the label, for the replay reason set out below.
- `source_label` is the **forecaster's** display name, alone, because td's own
  model calls it "the leaderboard grouping key" — folding the proposer in would
  split one person across as many rows as there are proposers.
- The proposer rides a **`proposed_by:<name>` tag**: recorded, queryable, and
  grouping-neutral.
- **Resolution fans out**, once per human who forecast, each with that person's
  own last confidence. A single resolve would have left every other
  forecaster's claim open forever, which scores as "never answered" rather than
  as right or wrong.

Two things the change surfaced that were not in the original finding:

- The house had to be excluded from the resolve fan-out **by `actor`, never by
  `user_id IS NOT NULL`** — that column is nullable for legitimate
  un-attributed LLM claims too, which would then be created on the desk and
  never resolved. This is exactly the confusion `stakes/house.py` exists to
  end, and the first draft of the fix walked straight into it.
- `trading/tools/outcomes/import_dialectic_stakes.py` still builds
  per-commitment keys, so a run would now add duplicate rows attributed to the
  wrong actor. It **refuses to run** until ported.

Zero migration cost, confirmed before the change: `SELECT count(*) FROM
predictions WHERE source_key LIKE 'stake:%'` was **0**, because no dialectic
commitment has ever had both a deadline and a confidence. Sunday's Round will
be the first rows this ledger has ever held.

Backend suite 1943 passed. The key fence is mutation-proven: reverting
`source_key` to the per-commitment shape turns
`test_two_humans_on_one_question_get_two_distinct_rows` red.

The original finding follows, unedited.

## What happens

When Amo or Dan moves a slider on a Sunday Round question, that forecast mirrors
into tradingDesk's claims ledger attributed to **`LLM`** — not to the person who
made it. Both humans land on the same row, blended with each other.

## The chain, verified link by link

1. `api/rounds.py:134` — the human forecast door calls
   `CommitmentManager.record_confidence(...)`.
2. `stakes/manager.py:191` — that relays with
   `source_label=await self._relay_source_label(commitment.get("created_by_user_id"))`.
   Note what it reads: the commitment's **creator**, never the `user_id` of the
   forecaster it was just handed.
3. `stakes/manager.py:113-125` — `_relay_source_label(None)` returns the literal
   `"LLM"`.
4. `llm/question_round.py:394` — every Round question is created
   `created_by_user_id=None,   # drafted, not claimed by either human`.

For an ordinary commitment ("I bet X by Friday") the creator *is* the forecaster,
so this has always looked correct. The Round is the first thing that separates the
two, and it separates them for every question it will ever write.

## Why the one-line fix does not work

The tempting change is to pass the forecaster's `user_id` at step 2. It is not
enough. `api/stakes_relay.py:113-129` — `_ensure_ledger_row` POSTs
`/api/predictions` with the label in the **create** body, and its own docstring
says *"td replays the existing row when the source_key is already claimed."* The
row is created once under `stake:{commitment_id}:created` and every later
confidence event POSTs to `/api/predictions/{that same id}/confidence`.

So the label is fixed at creation, creates replay rather than update, and both
humans post confidence against one prediction row. Correcting the label at step 2
would change nothing, because by then the row already exists and says `LLM`.

A real fix needs one of:

- **a desk prediction row per forecaster** for round questions (source key
  becomes `stake:{commitment_id}:{user_id}:created`), or
- **the desk's confidence events carrying their own actor**, with the leaderboard
  grouping on that rather than on the prediction's `source_label`.

Both cross the service boundary into the scoring spine. That is why this is
written down rather than patched at 23:00 two days before first fire.

## What is NOT affected — scope, so this is not over-read

**The Round's own head-to-head scoring is correct and unaffected.**
`commitment_confidence` carries both `user_id` and `actor` (migration 019), and
`stakes/timeweighted.py` scores per actor off those rows. The seal, the peer
delta, the house's separation from the humans — all of that reads dialectic's own
table and is right.

What collapses is only the **mirror into tradingDesk's claims ledger**, which is
what `TrackRecordPanel` (the Ledger's scored track record) renders.

## The consequence worth weighing

`self_model.fetch_track_record` feeds the desk's scored record back into the
participant's own prompt under *"## Your Track Record (scored, not
self-reported)"*. If both humans' Round forecasts accumulate under `LLM`, the
participant reads a track record containing other people's forecasts as its own.
That is a feedback loop into its self-model, not merely a display bug.

*(Traced through `fetch_track_record`'s use of the desk leaderboard; I did not
run the loop end-to-end, so treat this paragraph as a well-grounded expectation
rather than an observed event.)*

## Recommendation

Decide before Sunday. Rows relayed from the first fire onward carry the wrong
label permanently — a later fix does not retroactively re-attribute them, so the
cost of waiting is a polluted ledger rather than a delayed feature.

If there is no time to choose, the cheapest honest stopgap is to **stop relaying
round-category commitments to the desk** until attribution is designed. The
Round's own scoring does not depend on the relay, so nothing the duel promises is
lost by holding it back.

## How this surfaced

The copy on `TrackRecordPanel` said "one row per forecaster". An adversarial
verifier checked that sentence against the implementation instead of accepting
it, and the sentence was not merely overstated — it was inverted. The copy has
been corrected (`one row per source`, and the panel no longer claims to be
room-scoped either, since `api/trading_relay.py` discards the room's book and the
desk answers from an unfiltered `SELECT * FROM predictions`). A rendered-text
regression test now fences both claims.
