# Handoff — The night the feed layer stopped lying (2026-08-09 → 08-11)

**What happened:** started as "fix the newsfeed", became a sweep of the whole
feed layer, then a public-repo push and a credential migration. **14 commits**
across two days, all pushed (`8d07672`).

Almost every defect had the same shape: *something that looked live and
wasn't*, with a warning nobody could act on sitting right next to it. A dark
GDELT query, a validator reading a key no file writes, a lag parser silently
defaulting a quarter of the graph, an index level in a percent node, a retry
loop feeding the throttle it was retrying against. None of them raised.

The second theme is about me rather than the code, and it is the one worth
carrying forward: **three times this session a conclusion ran ahead of the
evidence** — a "0 requests" reading from an empty log window, a mutation test
that errored instead of failing, and a "the throttle has lifted" drawn from
the first book in a probe run. Each was caught by finishing the check rather
than by a new idea. The traps section below is mostly that.

## What is LIVE and verified

| Capability | Proof |
|---|---|
| News feed on all five books | `22789a3` — each book declares a watch-only GDELT rhetoric node; `/api/bridge/news/{book}` serves headlines instead of `"no gdelt config"` |
| Three GDELT catalog queries that had **never worked** | `10d5305`, `6cd02a3`, `cf97ddb` — BOJ/JGB, LGFV, TSMC all rejected upstream since authoring |
| FRED + EIA live for the first time | keys in `trading/.env`; first ticks corrected `dxy-stress` 28.07 → 119.70 and `diesel` 5.38 → 5.348 $/GAL |
| Coordinator spends **zero** GDELT requests | `6433640` — measured 0 fetches across a full tick window after deploy |
| A failing slow source backs off | `6433640` — cooldown doubles from 600s, capped at the source's TTL |
| The feed validator validates feeds | `13d1a2a` — it had read the singular `feed` key while all 71 nodes use plural `feeds` |
| 18 edges propagate on their declared lag | `13d1a2a` — quarters and `immediate to N` no longer collapse to 30d |
| Docs match reality | test count 1325 → 1379; README documents the watch-only contract and the 5-char rule; `.env.example` + deploy runbook carry `DIALECTIC_ROOM_TOKENS` |
| Room tokens out of the books, into env | `4944009` — same secrets, new home; all five rooms 200 on a read-only auth check, 401 negative control |
| FRED writes percent into percent-calibrated nodes | `0e2d997` — `units=pc1` on the three index series; `retail-prices` 332.568 → 3.287, `input-costs` 286.827 → 10.110 |
| The news bridge backs off a 429 instead of feeding it | `c5a1884` — consecutive rate limits double the hold, 120 → 900s cap, cleared by one good fetch |

Suite 1323 → 1379 passed, 3 skipped. Desk on `8d07672`, healthy.

### What GDELT is actually doing — read this before diagnosing the feed

Two spaced runs, ~18 hours apart, produced the SAME shape:

| | 00:39, after 20 min quiet | 18:48, after ~18 h quiet |
|---|---|---|
| 1st book probed | **15 articles** | **15 articles** |
| every book after, ~40s apart | 429 | 429 (all four) |

**One request per quiet window. The length of the preceding silence buys
nothing.** Twenty minutes and eighteen hours performed identically, which
kills the theory the 00:39 line in this file used to assert — that we had
earned a lingering penalty through the old every-tick behaviour and it
would "heal on its own". It does not heal, because there is nothing to
heal: the constraint is spacing between requests, not accumulated debt.

> That earlier claim was written from the 00:39 run and stood in this file
> for a day. It was drawn from one success plus three failures and read
> the failures as decay. Corrected 2026-08-11 once the 18-hour run showed
> an identical 1-of-5. Recorded rather than deleted because the wrong
> version is the more instructive one: a single success at the head of a
> probe run is not evidence that a throttle lifted.

Consequences for whoever is next:

- **Coordinator GDELT requests are 0** and stay 0 — that fix holds.
- The desk is CORRECT but serves **one book at a time**. Ask Claude about
  two theses in one conversation and the second reliably eats a 429.
- **A single news probe is itself a request.** Any check you run is
  competing with the feature. Prefer reading `journalctl` over probing.
- Do not conclude anything from one book. Probe the set or nothing.

## Traps worth remembering

- **GDELT rejects quoted terms under 5 characters** with `The specified
  phrase is too short.` — and returns it as a **non-JSON 200 body**, so it
  surfaces as `GdeltAPIError`, not as a validation error. `IEEPA` (5) passes,
  `LGFV` (4) does not. Three of five catalog queries were dead this way and
  nobody noticed, because no book referenced them until the wiring landed.
- **A fetcher that discards its result still pays for it.** Every engine
  fetcher refuses to write into a node with no `current` key, but only
  `fetch_gdelt` was *planning* around that. Five books × one watch-only node
  = five real HTTP calls per tick, all thrown away, all against the only
  unauthenticated per-IP-throttled source on the desk. The log read
  `updated 0 node(s) from 1/1 queries`, which looks like a quiet news day.
- **Failure inverted the polling pressure — in two places.** `slow_feeds`
  re-attempted a failing source every 300s tick while leaving a healthy one
  alone until its TTL, so failing made the desk poll 3×–72× *harder* than
  succeeding. The news bridge had the same shape one layer up: its flat 120s
  error TTL treated a 429 like any other failure, so five books re-attempted
  roughly every 24s between them and kept the throttle warm for hours. A
  rate limit is not a guess about recovery — it is the upstream saying in
  words that we ask too often, and it is the only error that should back off
  on its own count.
- **A cooldown of exactly one tick is a no-op.** The retry is due at
  `now >= retry_at`, so the very next tick lands on the boundary and fetches
  anyway. Base is two ticks (600s) for that reason.
- **A validator can read a key no file uses.** The feed-schema block read
  `n.get("feed")`; every book writes `feeds`. Zero matches across five books
  since it was written. It found three dead feeds in iran-hormuz the moment
  it read the right key — and no book hard-errored, which is what made it
  safe to turn on.
- **One false warning discredits eighteen real ones.** The lag check flagged
  `1-4 weeks (tit-for-tat)`, which the parser reads fine as 17d. Sitting
  beside 18 genuine findings, it is exactly how an operator learns to skim
  past the whole channel.
- **A mutation that kills nothing means the guard is untested.** The first
  overflow test looped 40 failures; the float overflow needs ~1015
  doublings, and the TTL cap answers correctly either way. It had to seed
  the streak to reach the guard it named.

## Still open

1. **Room tokens: moved out of git 2026-08-10 ~17:55 CDT. NOT rotated —
   they remain valid and remain in pushed history.**

   > **Update 2026-08-10 ~17:55 CDT (`4944009`).** The owner's call was
   > move, not rotate. `DIALECTIC_ROOM_TOKENS` in `trading/.env` (gitignored,
   > mode 600) now carries `<room-uuid>:<token>` for all five rooms, the
   > books are scrubbed, and every reader goes through one resolver,
   > `tools/bridge/room_tokens.py`. Verified against the live dialectic
   > service: all five rooms return **200** on a read-only token-gated
   > endpoint, with a wrong token and a missing token both returning 401 as
   > the negative control. Zero deprecation warnings and zero auth failures
   > on the running desk.
   >
   > **What this does and does not buy.** It stops the NEXT commit from
   > leaking, and it means a fresh clone of the public repo carries no
   > credential. It does NOT un-publish yesterday's push: the five values
   > are in pushed history and are still live. Anyone who pulled or scraped
   > between ~12:05 and now holds working room tokens. Rotation is still
   > the only thing that closes that, and it is now a one-line change per
   > room (`UPDATE rooms SET token = ...` plus the env value) precisely
   > because the books no longer have an opinion.

   > **Superseded 2026-08-10 ~12:05 CDT: the push happened, on the owner's
   > explicit second instruction.** `origin/master` is at `4bc859a`; the
   > `trading/` tree (308 files) is live on the public repo and the five
   > `meta.dialecticRoomToken` values went with it. The paragraphs below
   > record the pre-push state.

   Pre-push pre-flight was otherwise clean: no `.env` with secrets in the
   142 commits (`packages/mobile/.env` holds only `EXPO_PUBLIC_API_URL`,
   which Expo bundles client-side by design), no committed key VALUES, no
   blob over 50 MB.

   **The migration half is done; rotation is what remains.** `rooms.token`
   is plaintext in Postgres and compared directly (`stakes/routes.py:32`),
   so rotating is now genuinely a per-room two-liner — the books no longer
   carry a value that could undo it:

   ```bash
   # per room: new secret in both places, then restart
   psql -c "UPDATE rooms SET token = '<new>' WHERE id = '<room-uuid>';"
   #   ...and edit the matching pair in DIALECTIC_ROOM_TOKENS in trading/.env
   sudo systemctl restart tradingdesk
   ```

   Do all five in one pass, then re-run the auth check that verified this
   migration (all five rooms 200 on `GET /stakes/rooms/{id}/commitments`
   with a wrong-token 401 as the control). `tradingdesk-bridge.timer` reads
   the same `.env`, so it needs no separate change — but it only pushes when
   a snapshot CHANGED, so a green run showing `pushed=-` proves nothing
   about auth. Use the read-only check, not the timer.

   `Skidudeaa/dialectic` is **PUBLIC**. `master` was 142 commits ahead of
   `origin/master` and 0 behind, so the push fast-forwarded cleanly — and
   added the **entire `trading/` tree**, which the public remote did not
   carry at all. Inside it, five live `meta.dialecticRoomToken`
   values in `trading/books/*.json`.

   They are **load-bearing, not vestigial**: `web/routes/bridge.py:184` maps
   `dialecticRoomId → dialecticRoomToken` at runtime, the coordinator push
   reads them, and `tradingdesk-bridge.timer` is still enabled and firing
   every 30 minutes. Removing them from the books without an env-backed
   replacement breaks the push path — and a single `DIALECTIC_ROOM_TOKEN`
   cannot hold five distinct per-room values, so the migration needs a real
   per-room mapping, not a one-line swap.

   Two decisions were on the table; the owner took path C (publish as-is)
   after being shown the consequence twice. A ruling was requested at
   ~01:00 CDT and went unanswered overnight, so the push was staged and
   left unfired; the instruction came at ~12:05 CDT.

   **`git rm --cached` will not undo this**, and neither did the migration.
   The blobs are in pushed history and public commits get cached and
   scraped. Only two things are left, and they are independent:

   ```bash
   # ROTATION — the one that actually closes the hole. Per room:
   psql -c "UPDATE rooms SET token = '<new>' WHERE id = '<room-uuid>';"
   #   ...and the matching pair in DIALECTIC_ROOM_TOKENS in trading/.env
   sudo systemctl restart tradingdesk

   # HISTORY PURGE — optional, separate, and does NOT substitute for above
   #   git bundle create ../backup.bundle --all      # FIRST
   #   git filter-repo --path trading/books --invert-paths
   ```

   `tradingdesk-bridge.timer` reads the same `.env`, so it needs no
   separate change — but it only pushes when a snapshot CHANGED, so a green
   run showing `pushed=-` proves nothing about auth. Verify with the
   read-only per-room check instead.
2. **Nothing serialises GDELT across books — the last gap in the news feed.**
   Each book's `/api/bridge/news/{id}` fetches independently, so with one
   request allowed per quiet window (see the table above), asking Claude
   about two theses in one conversation reliably 429s the second. The
   per-book backoff shipped in `c5a1884` handles the refusal gracefully; it
   does not stop five books racing each other into it.

   Shape of the fix: a module-level last-request timestamp in `bridge.py`
   shared by ALL books, and when a call arrives inside the floor, serve the
   cached miss rather than spend a doomed request. **Derive the interval
   from passive `journalctl` observation over a day, not from probing** —
   every probe spends exactly the request the feature needs, which is what
   made every reading in this session partly self-inflicted. 60–90s is the
   guess; it should not ship as a guess.

3. **A live curve spread has no implementation.** `curve` wanted front-vs-6m
   Brent as a percent; no fetcher computes a spread, and its `symbols` list
   was never read by anything. Marked `manual` and pointed at the live
   contracts (`BZ=F` over `BZJ27.NYM`) — the original `BZK26.NYM` leg had
   expired months ago. Building real spread support would make it live.
4. **CommitmentDetector as proposals** — still imported, never called
   (`stakes/detector.py`). Bigger than wiring: `draft_prediction`'s Accept
   card rides on an *LLM* message's `metadata.proposal`, but a detected
   commitment comes from a *human's own* message, so where the card lives is
   a design decision. Also needs a per-room cap — it fires a Haiku call per
   triggered message.
5. **Cross-room memory write path** — routes + WS handlers + promote-to-global
   UI. Read path is live. The remaining P2 item.
6. **Owner rulings, unchanged:** knowledge graph wire-or-delete, replay
   `getState`, personas, frozen `packages/*`.
7. **Ops:** `tradingdesk-bridge.timer` still enabled (disable after a clean
   week); `trading/snapshots/*-latest.json` + `outcomes/trades/*.jsonl` churn
   dirty in the worktree on every restart — commit-vs-gitignore still pending.

## Tooling note

Live-resolving all 57 declared Yahoo symbols is what caught `^PMI` (not a
ticker) and `BZK26.NYM` (expired contract). Neither is findable by reading
the books, and futures contracts will expire again — a periodic re-run of
that resolution sweep is the cheapest guard against the next one.
