# Handoff — The night the feed layer stopped lying (2026-08-10, ~04:00–06:00 UTC)

**What happened:** started as "fix the newsfeed", became a sweep of the whole
feed layer. Six commits. Every defect found had the same shape: *something
that looked live and wasn't*, with a warning nobody could act on sitting
right next to it.

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
| Docs match reality | test count 1325 → 1359; README documents the watch-only contract and the 5-char rule |
| FRED writes percent into percent-calibrated nodes | `0e2d997` — `units=pc1` on the three index series; `retail-prices` 332.568 → 3.287, `input-costs` 286.827 → 10.110 |
| The news bridge backs off a 429 instead of feeding it | `c5a1884` — consecutive rate limits double the hold, 120 → 900s cap, cleared by one good fetch |

Suite 1323 → 1364 passed, 2 skipped. Desk on `c5a1884`, healthy.

**Final verification (00:39, after a deliberate 20-minute window with zero
probes):** coordinator GDELT requests = **0**. `trump-tariffs` returned 15
live headlines, `japan-rate-shock` 4 earlier. `iran`, `ai-capex` and
`china` were still rate-limited — GDELT's per-IP penalty on this host
outlasts 20 minutes, and hours of the old every-tick behaviour plus my own
verification probing are what earned it. Nothing in the desk is feeding it
now, so it heals on its own; the remaining 429s are residue, not a defect.
Treat any single news probe as a request that itself extends the hold.

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

1. **Room tokens are now PUBLIC — rotate them, and get them out of git.**

   > **Superseded 2026-08-10 ~12:05 CDT: the push happened, on the owner's
   > explicit second instruction.** `origin/master` is at `4bc859a`; the
   > `trading/` tree (308 files) is live on the public repo and the five
   > `meta.dialecticRoomToken` values went with it. This is no longer a
   > risk to weigh — it is an exposure to close. The paragraphs below record
   > the pre-push state for the record.

   Pre-push pre-flight was otherwise clean: no `.env` with secrets in the
   142 commits (`packages/mobile/.env` holds only `EXPO_PUBLIC_API_URL`,
   which Expo bundles client-side by design), no committed key VALUES, no
   blob over 50 MB.

   **The rotation and the migration are ONE job, not two.** `rooms.token` is
   plaintext in Postgres and compared directly (`stakes/routes.py:32`), so
   rotating is a per-room `UPDATE` — but a new token written back into
   `trading/books/*.json` lands in the same tracked file that is now public,
   which recreates the exposure on the next commit. Rotate and move to env
   in the same pass, in this order: new tokens into env + `rooms.token` →
   books scrubbed → commit → restart the desk (its WorkingDirectory IS the
   git tree) → verify one push round-trip per room.

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

   **`git rm --cached` will not undo this.** The blobs are in pushed
   history and public commits get cached and scraped, so scrubbing history
   is a separate exercise from rotating — and rotation is what actually
   closes the hole. What remains open:

   ```bash
   # 1. rotate — per room, tokens live plaintext in rooms.token
   psql -c "UPDATE rooms SET token = '<new>' WHERE id = '<room-uuid>';"

   # 2. get them out of git in the SAME pass, or step 1 is undone by the
   #    next commit. One DIALECTIC_ROOM_TOKEN cannot hold five values, so
   #    this needs a per-room mapping in env (see bridge.py:184).

   # 3. commit scrubbed books -> restart the desk (WorkingDirectory IS the
   #    git tree) -> verify one push round-trip per room.

   # optional, separate: purge the blobs from history
   #   git bundle create ../backup.bundle --all   # FIRST
   #   git filter-repo --path trading/books --invert-paths   # then re-add clean
   ```

   Also still true: `tradingdesk-bridge.timer` fires every 30 minutes on
   the old push path, so a rotation that misses it will surface as a
   half-hourly auth failure rather than immediately.
2. **A live curve spread has no implementation.** `curve` wanted front-vs-6m
   Brent as a percent; no fetcher computes a spread, and its `symbols` list
   was never read by anything. Marked `manual` and pointed at the live
   contracts (`BZ=F` over `BZJ27.NYM`) — the original `BZK26.NYM` leg had
   expired months ago. Building real spread support would make it live.
3. **CommitmentDetector as proposals** — still imported, never called
   (`stakes/detector.py`). Bigger than wiring: `draft_prediction`'s Accept
   card rides on an *LLM* message's `metadata.proposal`, but a detected
   commitment comes from a *human's own* message, so where the card lives is
   a design decision. Also needs a per-room cap — it fires a Haiku call per
   triggered message.
4. **Cross-room memory write path** — routes + WS handlers + promote-to-global
   UI. Read path is live. The remaining P2 item.
5. **Owner rulings, unchanged:** knowledge graph wire-or-delete, replay
   `getState`, personas, frozen `packages/*`.
6. **Ops:** `tradingdesk-bridge.timer` still enabled (disable after a clean
   week); `trading/snapshots/*-latest.json` + `outcomes/trades/*.jsonl` churn
   dirty in the worktree on every restart — commit-vs-gitignore still pending.

## Tooling note

Live-resolving all 57 declared Yahoo symbols is what caught `^PMI` (not a
ticker) and `BZK26.NYM` (expired contract). Neither is findable by reading
the books, and futures contracts will expire again — a periodic re-run of
that resolution sweep is the cheapest guard against the next one.
