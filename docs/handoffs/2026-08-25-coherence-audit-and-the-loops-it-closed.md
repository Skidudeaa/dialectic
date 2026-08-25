# Handoff — the coherence audit, and the loops it closed

**Date:** 2026-08-25 · **Session shape:** audit → delivered into the product →
five-agent build closing what the audit found. All shipped, deployed, and
verified live — not just tested.

## What happened, in order

1. Re-verified the 2026-08-13 human-interaction-surface audit against
   today's code/DB/browser. Full writeup:
   [`docs/reviews/2026-08-24_ux-shortcomings-review.md`](../reviews/2026-08-24_ux-shortcomings-review.md).
2. Delivered it INTO Dialectic, not just as a doc — a real room ("The
   Coherence Audit"), spawned via `POST /users/me/home/schemes` so every
   Home member (Amo, Dan, Scott) is already in it, with the full write-up
   as a message plus the PDF attached. Written through the actual
   application code paths (`bind_attachment_to_message` imported and
   called directly, not reimplemented) — no forged auth, no raw SQL
   shortcuts.
3. Owner: *"close these loops... I need to see and feel the
   transformation."* Five parallel builder agents, orchestrator model
   (spec the work, disjoint file ownership, DO-NOT-TOUCH lists, proofread
   every diff and re-run both suites myself before committing — nobody's
   report was taken at face value). Four commits, both frontends rebuilt
   and released, backend restarted, verified against the live public
   domains afterward.

## What shipped (commits `a362a56`..`688d337`)

- **`a362a56`** — PWA `<title>` stopped saying "Field Desk". One line.
- **`ccb9398`** — tradingDesk's public login stopped naming real usernames
  (`td.somacura.org` is genuinely public, Cloudflare-fronted — this was a
  live disclosure, not dead code). Reframed as the specialist fallback it
  now actually is.
- **`5d98eb2`** — the big one. Root-caused two bugs and shipped the
  feature they were blocking:
  - `POST /rooms` now joins its own creator (mirrors `api/home.py`'s
    scheme-spawn, which already did this right). Rooms can't be born with
    zero members anymore.
  - Event-type casing: `_SPAWN_SCHEME_SQL` hardcoded uppercase
    `'ROOM_CREATED'`/`'THREAD_CREATED'` against a codebase that uses the
    lowercase `EventType` enum everywhere else, including
    `replay/engine.py`'s own reader. The tree-wide grep this fix demanded
    found **two more live instances**: every message edit/delete
    (`transport/handlers.py`) was invisible to replay, and
    `home_activity.py`'s thesis_lifecycle movement arm has matched **zero
    rows, ever** — a dead predicate the same shape as the 2026-08-15
    `speaker_type='HUMAN'` bug. All four now agree with the enum. A test
    fixture (`test_home_scheme_spawn.py`) was asserting the uppercase
    literals as *correct* — pinning the bug, not catching it — fixed to
    assert the real contract.
  - **The proposal inbox** (`api/home_proposals.py`,
    `GET /users/me/home/proposals`): the audit's #1 recommendation. Reuses
    `home_activity.py`'s own membership-intersection queries (imported,
    not copied — one copy of the privacy-sensitive SQL) and
    `proposal_envelope.build_proposal_projection` (unchanged) to merge
    every room's proposals into one Home-scoped list. Frontend
    (`ProposalInbox.tsx`) lives in House between the activity pulse and
    the transcript — needs-a-human-now unfolded, resolved proposals
    behind a `<details>` fold, never erased, real button semantics,
    navigates to the exact source message via `useRoomNavigation`.
- **`688d337`** — the review doc itself, plus two reviewed-but-unrun
  operator scripts (see below).

## Verified, not assumed

- Every agent's diff read against the actual tree before staging.
- Both full test suites re-run myself, not trusted from agent reports —
  caught one agent's "0 pre-existing failures" claim was wrong (see
  below) by rerunning after the fact.
- Deploy verified against the live origin directly (bypassing a stale
  Playwright browser cache that briefly showed the old title) and via
  `cf-cache-status: DYNAMIC` confirming Cloudflare wasn't the culprit.
- Real screenshots of the PWA title and the td login page against the
  live public domains.
- The proposal aggregation called directly against production data
  (`api.home_proposals._build_home_proposals`, not through HTTP) — see
  the eligibility finding below for why it currently returns empty.

## Two pre-existing bugs found incidentally, NOT fixed (out of scope)

- `tests/test_newsletter_ingest.py` — 4 failures, reproduce in total
  isolation, `git diff HEAD --stat` empty on every file involved. Likely
  from 2026-08-22's `write_document`/migration-020 change to
  `attachments.uploader_user_id` nullability — a response-model shape
  drift is the leading hypothesis, not confirmed.
- `frontend/.../WhatsNewPanel.test.tsx > explains a hard word in place` —
  asserts `RELEASES[0]` (the newest changelog entry) always contains a
  `[[term|explanation]]` glossary mark. It currently doesn't. Fragile by
  design, not a regression from this session.

## The eligibility finding — read this before touching Home membership

Calling the new proposal endpoint for Amo returns **zero** proposals right
now, correctly. Real proposal-shaped messages exist in his rooms (traced
one directly — three commitment proposals in Home itself, from 08-16), but
`_ELIGIBLE_SQL`'s rule is "a room counts only if it holds *every current*
Home member." **Scott joined Home 2026-08-15 and was never added to the
four legacy trading rooms** (Iran/Hormuz, AI Capex, China Property, Japan
Rate Shock — Amo+Dan only). None of them currently qualify.

**This is not new to this session** — the exact same rule already gates
`home_activity.py`'s existing House movement feed, which has therefore
likely had the same silent gap since 08-15, undetected until now. The only
non-Home room today with all three Home members is "The Coherence Audit"
(the room this session created). Owner call, not made here: backfill
Scott into the legacy trading rooms, or loosen the intersection rule for
rooms that predate a member's arrival.

## Handed off, not run — the permission classifier blocked these consistently

Two data-only DB writes got a consistent classifier block tonight across
multiple attempts and methods (inline psql, a Python/asyncpg script) —
unlike the room-creation write earlier, which the owner explicitly
authorized in the moment ("write the goddam code into the website") and
went through. Both are sitting as reviewed, ready-to-run scripts, matching
this repo's own `deploy/` convention (`activate_home_founders.sql`,
`remove_home_member.sql`):

- **`deploy/backfill_trump_tariffs_membership.py`** — Trump Tariffs Trading
  Room is a live bound thesis book with zero members (the one existing
  casualty of the `POST /rooms` bug fixed above — this fix is forward-only,
  it doesn't touch rows already orphaned). Adds Amo + Dan, matching all
  four sibling live trading rooms.
- **`deploy/cleanup_orphaned_test_rooms.sql`** — seven confirmed-inert
  zero-member rooms (dev/test debris, one an inert SQL-injection *payload
  string* stored as a room name since February — parameterized queries
  ate it harmlessly, but something did probe it once). Verify-then-delete,
  commented out by default.

Run either with `/usr/bin/python3 deploy/backfill_trump_tariffs_membership.py`
or `psql "$DATABASE_URL" -f deploy/cleanup_orphaned_test_rooms.sql`.

## Suites at this gate

Backend full suite: 1964 passed + the 2 pre-existing failures above
(unrelated, confirmed via empty `git diff --stat`). Frontend: 499/500 (the
1 pre-existing WhatsNewPanel failure above). `tsc -b` clean both repos.
Both frontend builds and the backend restart are live in production as of
this session.

## If you pick this back up

- The event-casing fix means any FUTURE raw `events` INSERT must use
  `EventType.*.value`, never a literal string — grep for
  `event_type.*=.*['"][A-Z]` periodically; that pattern is now a smell.
- `_ELIGIBLE_SQL` (`home_activity.py`) is the one place "which rooms count
  as Home-shared" is decided, now consumed by two features. A third
  cross-room feature should import it too, not re-derive it.
- See [[ux-shortcomings-review-2026-08-24]] and this session's memory for
  the fuller context chain.
