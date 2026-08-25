# The UX shortcomings we haven't rectified — 2026-08-24

**Method:** re-verified the 2026-08-13 human-interaction-surface-audit
(`docs/audits/2026-08-13-dialectic-human-interaction-surface-audit.md`, 209
surfaces, amended 08-16) and `TODOS.md`'s P0/P1/P2 follow-through against
**today's actual code, the live DB, and a real browser session** — not against
memory, not against the audit's own 08-16 claims. Three parallel passes: static
code verification of the P0 findings, a live signed-out browser walkthrough
plus P1 code verification, and a P2 sweep plus a live-DB check of the Round's
first fire. Every verdict below is grounded in a file:line, a query result, or
an observed screen — not a guess. Where something couldn't be verified, that's
stated rather than papered over.

**Headline:** eleven days and ~55 commits of real feature work (Release 3,
One App/C4-cull, Instrument Desk, Calibration Spine, Connection repairs,
Legibility, The Duel, write_document) closed a genuine chunk of the audit —
the outright *lying* UI is mostly gone. But the pattern across almost every
remaining item is the same: **the deception got fixed: the capability gap
behind it didn't.** Forgot-password no longer claims an email was sent — it's
honestly disabled, and still unusable. The dead workspace-object click is
fixed — but there's still no proposal inbox to click into. And one thing
nobody was watching for: the Sunday Round shipped and fired **perfectly**
(zero errors) and its actual payoff has fired **zero times**, because the
two humans it's built for haven't both shown up to a single question yet.

---

## 1. What's genuinely fixed since 08-13 — credit where due

| Audit finding | Status | Evidence |
|---|---|---|
| T02/T04 — fake `Math.random()` "WIRE LIVE" latency, inert "New Case +" | **Gone.** Whole Field Desk cockpit deleted in the C4 cull. | `trading/CLAUDE.md` 08-14 amendment; zero grep hits for `WIRE LIVE` in `trading/frontend/src/` |
| W15 — workspace objects without `branch_id` look clickable, do nothing | **Fixed.** Renders a plain non-interactive `<li>` now, with a comment explaining why. | `WorkspaceObjectList.tsx:59,84-86` |
| A06/A07 — forgot/reset password lies that an email was sent | **The lie is fixed.** Now returns an honest `503` / a `disabled` button instead of a fake success. | `dialectic/api/auth/routes.py:129,~447`; live DOM check, `forgotBtn.disabled === true` |
| X05/N01 — notifications only deep-link to a room | **Substantially fixed**, further than the audit anticipated. `notificationclick` now carries `room_id` + `thread_id` + `message_id`. | `dialectic/frontend/app/src/sw.ts` |
| P08 — one prediction, one identity, across systems | **Data model unified.** Stakes mirrors into td's one claims ledger via idempotent `stake:{id}:*` keys (Calibration Spine, 08-18). UI is still fragmented — see §3. | — |
| D12 — humans can only react, never author proposals | **Fixed.** A working "Make a move" composer exists. | `dialectic/frontend/app/src/components/chat/ProposeMenu.tsx` |
| The Round mirrors every forecast into td's ledger labelled "LLM" | **Fixed 08-22**, one day before first fire. *(Standing project memory called this open — it's not; corrected 08-24.)* | `docs/reviews/2026-08-21_round-forecast-attribution.md`; commit `2597460` |

---

## 2. Still open — P0 (trust and product coherence)

**1. tradingDesk is still a live, public, second product identity — with real usernames in the DOM.**
`td.somacura.org` is enabled in nginx and Cloudflare-fronted (`ufw` only
restricts the *origin* to Cloudflare's edge ranges — the site itself is public
like any other CF-proxied domain). Its standalone `Login.tsx:136` literally
reads *"Two-analyst workspace. Dev users: amo, ..."* — disclosing real
usernames on a page anyone who finds the subdomain can load. This was flagged
as a UX/coherence problem in the audit; it's actually a live, public
information-disclosure surface today, not dead code.

**2. The primary PWA's own browser tab still says "Field Desk."**
`dialectic/frontend/app/index.html:15` — `<title>Dialectic — Field
Desk</title>`. The specialist product's name is literally branded onto the
canonical product's own tab, the one surface One App/C4-cull was built to make
coherent. One-line fix, never made.

**3. There is still no proposal inbox.** "Make a move" (D12) works. Reviewing
what's pending, contested, or expired (D13) does not exist anywhere —
`HouseMovement.tsx` (the "Needs you" surface) has zero mentions of
proposal/contested/pending. The only place a proposal is visible is as a card
inside whatever room's chat history it was posted in. A human's only tool for
"what needs my judgment right now, across rooms" is to remember and scroll.

**4. Access recovery is still a dead end.** No email integration exists
anywhere in the codebase (grep for smtp/sendgrid/ses/postmark/resend/mailgun
across all of `dialectic/`: zero hits). Zero UI screens exist for
verify/reset. A locked-out user's only path is operator SQL. The dishonesty is
gone; the capability was never built.

**5. Failure receipts are still ephemeral.** `trading/frontend/src/components/CommandPalette.tsx:144`
still stuffs command results into `window.__lastCommandResult` with nothing
durable a human can come back to.

---

## 3. Still open — P1 (complete the core human journeys)

- **Room lifecycle doesn't exist at the backend, at all.** Grepped every
  `@router.patch("/rooms` and `@router.delete("/rooms` across
  `dialectic/api/*.py`: zero matches. No rename, archive, delete, leave,
  remove-member, or rotate-invite route exists. This isn't a missing UI over a
  working API — the API isn't there either.
- **Membership is still presence.** A real `GET /rooms/{id}/members` route
  now exists (`api/main.py:913`) — but it was built "so the @-picker works,"
  and nothing renders it as a standalone roster. The Users panel is still
  online-presence-only.
- **Research questions still aren't durable objects.** No `research_brief`
  table exists. A research question is still asked, waited on, and returned
  as one chat message — no persisted question, sources, or progress state.
- **Predictions have one identity in the database and none in the UI.** The
  backend consolidation (§1) has no corresponding human-facing view — no
  Judgment scene exists in the current scene set (`record/bench/field/library/ledger`).
  A human still has to know which of three places to look.
- **Accessibility work remains almost entirely unverified.** The 08-16 audit
  amendment claimed "safe areas, 44px targets, 12px control type, and contrast
  pass at five widths" — and five days later the 44px rule itself broke every
  inline Explain marker in the app, caught only by a screenshot no automated
  check would have taken (see the Legibility memory). Live re-testing this
  session confirmed the touch-target floor holds on the **signed-out**
  sign-in screen (all 5 controls ≥44×44px) but could not reach an
  authenticated room to re-check the exact surface that broke before, or test
  keyboard/screen-reader behavior past sign-in — auth minting was correctly
  blocked by the permission classifier as impersonation, and no other login
  path was available without guessing real credentials. **Nobody has ever run
  an axe pass or manual screen-reader test on this product.** That's not a
  regression to fix — it's work that has never happened.

---

## 4. Still open — P2 (simplify or retire)

- **The knowledge-graph decision is still undecided**, 8+ months after the
  wire-or-delete track named it. `KnowledgeGraphEngine` still builds a
  materialized view at every startup (`dialectic/api/main.py:37,188-193,316`)
  for a feature nobody has ruled to keep or cut.
- **Generated thesis HTML dashboards are stale and unlabeled** — worse than
  the audit knew. All 6 files in `trading/output/` are dated **Aug 9, 03:05**
  — generated before Release 1 shipped and never regenerated since. Nothing
  on the page tells a viewer that. Anyone who still has one of these open or
  bookmarked is looking at a 2-week-stale snapshot with no warning.
- **Persona CRUD** — confirmed still deferred exactly as designed. Not a
  problem, just noting it was checked.

---

## 5. New findings the 08-13 audit never saw

The audit mapped UI surfaces; it didn't trace data flows or read the newest
handoffs. This pass did both and found five things worth the owner's
attention that aren't in the original 209:

1. **Ordinary predictions still can't be scored.** Outside the Round, the
   Accept-card flow never asks for a deadline or confidence
   (`MessageBubble.tsx:322`, `stakes/detector.py:96-99`) — flagged open in
   both the 08-20 and 08-21 handoffs, never closed. The Round works around
   this by asking directly; every other prediction in the app still can't be.
2. **The flagship trading room is watching a dead market.** Iran/Hormuz polls
   a Polymarket market that resolved in April. Polymarket isn't configured
   for any other live room. 10 of the 20 registered LLM tools have never been
   called in production.
3. **`save_reading` silently drops a written summary** when its own re-fetch
   403s — real data loss on a permission edge, noted in the 08-20 handoff,
   not yet addressed.
4. **`llm_decisions.tool_calls` is double-encoded** (`self_model.py:257-259`)
   — tool-call analytics silently read back empty. Nothing errors; the data
   just isn't there.
5. **Time-bomb test fixtures: 15 unaudited candidates, refreshed count.** The
   Legibility session found "~10" files pairing a live clock against a
   hardcoded date (the same bug class that caused a real false-red test on
   08-21). A corrected grep run this session (the earlier one missed calls
   like `datetime.now(timezone.utc)`) finds **15** genuine candidates, listed
   in `[[legibility-2026-08-21]]`. None have been individually read yet.

---

## 6. The Round: built right, sitting unused

This is the most interesting finding in this review, and it isn't a bug.

The Sunday Round fired exactly on schedule — **2026-08-23 14:00:23 UTC / 09:00
CT**, `question_round` job status `success`, zero errors, **12 commitments
created** (3 per room × 4 qualifying rooms), matching the 08-22 volume ruling
precisely. `round_close_watch` has run hourly since with a clean empty result
every time, correctly, since every deadline is weeks out. The `house` actor
forecast all 12 on schedule. Every piece of engineering behind this feature
worked.

**One day in: 9 of 12 questions have exactly one human forecast. 3 have zero.
Not one has both Amo and Dan.** The entire payoff this feature exists for —
the blind reveal, the "how you misread them" second slider, the credit line,
the Mirror — requires both humans on the same question, and it has not fired
a single time. This isn't a code problem to fix; it's the first real adoption
signal for a feature that was, until yesterday, untested by real use. Worth
watching directly rather than assuming the engineering being correct means
the feature is working.

---

## 7. Standing memory corrected by this review

`[[legibility-2026-08-21]]` described the Round's "labelled LLM" bug as open
with "the one-line fix does not work" as its last word. **It was fixed
2026-08-22**, verified again live today via DB query. That memory file has
been corrected in place; if you've seen that line quoted elsewhere, it's
stale.

---

## 8. If you only do three things

1. **Fix the two embarrassments that cost nothing to fix**: the PWA's own
   `<title>` tag still says "Field Desk" (`index.html:15`), and
   `td.somacura.org`'s login page names real usernames on the open internet.
   Both are one-line changes.
2. **Build the proposal inbox.** Field, Focus, and "Make a move" all shipped.
   Nothing surfaces the queue they create. This is the single highest-leverage
   gap — everything upstream of it is already built.
3. **Don't mistake the Round's clean launch for adoption.** Check in with Dan
   directly about the Sunday Round rather than waiting for the log to show a
   second forecaster — the code has nothing left to tell you here.
