# Handoff — the Calibration Spine + the Paper Book (2026-08-18)

One session took "make our own personal PLTR" from vision to production:
the claims ledger, the scorer, the deterministic oracle, the paper book,
propose_trade, the unconventional sources, and the bias controls — 11
commits (`295a28c…86aca51`), deployed and live-verified, plus the Iran
book seeded. This file is the state, the gotchas, and the next moves for
a session with zero context.

## Where the truth lives

- **The plan + the review adjudication**:
  `/root/.claude/plans/think-outside-the-box-elegant-acorn.md` — the
  amalgamated plan (this session's + the parallel "Calibration Spine"
  plan), the owner's four rulings, and the point-by-point adjudication of
  an external model review that arrived MID-BUILD (five of its corrections
  shipped; the deferrals carry recorded revisit triggers). Read it before
  amending anything the spine froze.
- **Doc amendments**: `trading/CLAUDE.md` + `dialectic/CLAUDE.md`, both
  "Amendment 2026-08-18" — the scoring laws, the new modules, the counts
  (12 jobs, 20 tools, td migrations to 008).
- **Memory**: `calibration-spine-2026-08-18.md` (the release),
  `prediction-loop-never-closed-2026-08-15.md` (now marked CLOSED),
  `builder-reports-can-be-stale.md` (session lesson, staged for global
  promotion at the next reviewed /reflect).

## Deployed state (all verified live, not assumed)

- Both services restarted on this tree; td auto-applied migrations
  **007 + 008** (75.0 confidence poison repaired — 0 rows > 1.0, history
  seeded 5/5; pre-migration backup at
  `/var/lib/tradingdesk/tradingdesk.db.pre007-20260818`). Frontend release
  `20260818005442-calibration-spine` is what the edge serves (bundle hash
  matched).
- Live probes passed: calibration (honest nulls), leaderboard
  (coverage-only groups — 5 open test-artifact claims, 0 scored),
  portfolio, and the door 422s confidence 75.0.
- **The Iran book is funded**: $100,000 deposit 2026-08-18T12:10Z
  (`source_key seed:iran-hormuz-graph:2026-08-18` — re-runs can't
  double-fund). 1 fill, 0 equity marks — the FIRST mark lands at the next
  04:30 UTC maintenance run and starts the SPY benchmark clock (the seed
  postdates the prior night's run; zero marks right now is correct, not a
  bug).
- Stakes backfill importer dry-ran: all 4 historical commitments refused
  ("no deadline") — the refuse-to-invent rule working; nothing to import.
  New deadline-carrying commitments relay live via stakes_relay.

## ⚠ 76 commits unpushed

`origin/master` (github.com:Skidudeaa/dialectic) is 76 commits behind —
more than this session's 12; earlier sessions' work is also local-only.
Pushing is the owner's call (house rule: push only when asked). Before any
push, remember the history-scan rule in global CLAUDE.md (secrets/blob
sizes in HISTORY, not the working tree).

## Gotchas a fresh session will hit

- **`CONGRESS_WATCH_ENABLED=0` — ships dark.** The Senate/House Stock
  Watcher S3 dataset URLs are CODED ASSUMPTIONS (flagged in
  `llm/congress_watch.py`); verify them live before arming. Scheduler
  nuance: unset env reads as ON at the Job level, so the OFF default is
  enforced INSIDE the job body (documented in-module).
- **The RSS wire is live but unconfigured** — no room has watchlist
  entries yet. Trump-signal feeds activate by adding
  `{type:"rss", value:"<feed url>", tag:"social"}` rows to
  `rooms.watchlist` (the `social` tag lowers the thin floor to 25 words).
  There is no UI for watchlist editing yet — SQL or a future settings
  surface.
- **Commit `b339bfa`'s message has one stale line** ("past-deadline claims
  resolve incorrect without needing a quote") — the shipped contract
  requires bar evidence at expiry. Corrected in trading/CLAUDE.md's
  amendment; don't re-learn the wrong contract from the message.
- **td `PredictionConfidenceCreate` silently drops the stakes relay's
  confidence `source_key`** — benign today (no retry loop exists), becomes
  real the moment an outbox or retry ships. Recorded in the plan
  amendment.
- **Orphan-claim edge at trade accept**: a forecast-carrying accept whose
  fill 422s (unquoted symbol) has already minted the prediction
  (prediction-first ordering is deliberate). Retry is idempotent; an
  unfixable symbol leaves a claim with no fill.
- **Two unverified-by-eyeball surfaces**: Bench PortfolioPanel + Ledger
  TrackRecordPanel passed every render test and tsc, but no human has
  looked at them live. Same for the "## Your Track Record" prompt section
  — unit-pinned, not yet observed in a real LLM turn (any room message or
  the 07:00 brief will exercise it).
- **Frontend batch test runs under load show timeout flakes** on untouched
  files (6-12s userEvent timeouts); all green in isolation. Don't chase
  them; don't trust a loaded batch run as a regression signal either.
- **Peer-session artifacts in the tree**: JOURNAL.md + PLAN.md
  modifications and IMG_0197.PNG are another session's — leave them.

## Next moves, in rough order

1. **Watch the first cycle close**: 04:30 UTC mark → benchmark starts;
   07:00 CT brief should carry the dissent line ("no credible
   contradicting coverage…") and, once readings exist, COUNTER labels.
2. **Eyeball the two new panels** on a real device; screenshot per house
   rule if anything looks off.
3. **First real trade**: ask the LLM in the Iran room to propose one —
   card renders → Accept → fill + paired prediction land; a
   price_cross-spec'd forecast then auto-resolves with zero further taps.
4. **Arm congress**: verify the two S3 URLs return the assumed shapes,
   then `CONGRESS_WATCH_ENABLED=1` + restart.
5. **Add the Trump-signal RSS entries** to the tariffs room's watchlist.
6. **Drop the first Capex Insider PDF** (room attachment → ingest) and
   watch it become citable.
7. **Phase 8 — the laboratory** (the one unbuilt phase): shadow books
   (`shadow:antithesis:<book>`, `shadow:consensus:<book>` — schema needs
   nothing new), the analytic base-rate/consensus forecasters (free from
   `base_rate` columns), and the weekly "How We Are Wrong" report. Its
   design gate is FROZEN POLICY VERSIONS first — the review's experiment
   registry point was adopted; don't launch a shadow arm before pinning
   model/prompt/policy versions.
8. Later slices with recorded triggers: durable outbox for stakes relay,
   confidence source_key at td's door, exit-proposals-on-resolution,
   rejected-proposal projection (selection-vs-skill), shorts semantics.
