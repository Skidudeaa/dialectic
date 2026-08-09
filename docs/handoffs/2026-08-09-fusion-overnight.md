# Handoff — The Fusion Overnight (2026-08-09, ~04:00–06:45 UTC)

**What happened:** the approved fusion plan
(`docs/plans/2026-08-09-fusion-master-plan.md`, Amendment 1 beside the Q3
plan) was executed in one overnight session: Fable orchestrating, eight
builder subagents writing code under disjoint file fences, every diff
proofread, every capability verified against the running system before
being called done. 18 commits (13 DwoodAmo + 5 tradingDesk at time of
writing), 679 + 701 tests green.

## What is LIVE in production

| Capability | Proof it works |
|---|---|
| Event-driven bloodstream: coordinator pushes v3 (with `alertEvents`) on change + hourly heartbeat; 15-min reconcile pull; freshness watchdog (3h in-room warning, 12h pocket push) | All five rooms flipped to v3 at 06:15–06:16 via the coordinator itself; watchdog + heartbeat green in `scheduled_job_runs` |
| The scheduler organ (`dialectic/scheduler.py` + `trading_watch.py`, migration 008) — advisory lock, double-fire-proof ledger | Ledger shows exactly one success per job per bucket across three restarts |
| LLM tool loop: 9 read-only tools, streaming @Claude path, visible activity, trace in `messages.metadata` | Live probe: "@Claude what is Brent at" → `get_live_quotes` → "$83.55 per the live feed — notably below the $99.78 snapshot…" with full trace persisted |
| Vision on image attachments (4 images / 12MB budget, image-before-caption) | 51 tests; wire-body verified; OpenAI fallback honestly says it can't see |
| Media end-to-end: upload (sha-deduped, magic-sniffed, streamed) / render / bind / list | Live byte-identical round trip in a scratch room, 401 unauthed, cleaned up incl. disk blob |
| One login: shared HS256 + claim shim; signups CLOSED (`SIGNUPS_ENABLED`); deep link; 72h token exchange (`/api/auth/exchange`, `/api/auth/me`) | Signup 403s with invite message; exchange mutation-tested; bridged sessions show real names |
| Curator severity gating: critical→always+push (cap-exempt), warning→offline-only, info/heartbeat→silent; 8/day cap; 5m/30m dedup | Mutation-tested; v1/v2 legacy behavior preserved |
| Slow feeds: Treasury + GDELT + econ-calendar live on TTLs; FRED/EIA light when keys land in `trading/.env` | First light in journal: 10Y 4.47→4.65% (curve 2026-08-07) on the first pull |
| SQLite retention: 04:30 UTC daily (keep 2016 revs/thesis + first-per-day), fetch_runs 14d, guarded VACUUM | Task armed, next run logged; outbox corpse dropped (914→659MB) |
| Quotes endpoint fixed (had NEVER returned a quote) + 240s cache | 49 real quotes, cold 18.5s → warm 10ms |
| Five thesis rooms bound and fed | All five fresh; `dialectic/CLAUDE.md` table updated |

## What is NOT done (task board is authoritative)

1. **#8 Repo move + doc hygiene (weekend):** `git subtree add --prefix=trading /root/tradingDesk master`; 872MB SQLite → `/var/lib/tradingdesk/` + symlink BEFORE the move (`DEFAULT_DB_PATH` in `web/persistence/connection.py:15` is package-relative); systemd repoint + host → 127.0.0.1; venv rebuild; archive old repo (`pre-fusion-final` tag exists? NO — tag at move time); delete Docker files; `.planning/*` → archive; fix stale READMEs + INTEGRATION.md's false "FULLY IMPLEMENTED" (record the correction, don't silently edit). **Note: `books/*.json` carry room tokens and are pushed to GitHub (private repo, pre-existing practice) — revisit at move time.**
2. **#9 Leftovers:** A7 (on_message/force_response through ToolLoop.run + `log_decision` tool_calls + migration 010) — gated on days of streaming-path trust; `router._hash_prompt` compact projection (16MB transient with images; forward hash break accepted); context token estimate blind to images; C4 cull (export td's 36 chat rows first, flip Field Desk default BEFORE deleting, then routes/ws chat lane, `web/state.py`, `mock_dialectic.py` after a clean week); annotator-vision product call — **Amo decides** whether the annotator should see images.
3. **#10 `draft_prediction`** (proposal + human Accept) — trust week ends ~2026-08-16.
4. **#12 Transactional bind:** `send_message` accepts `attachment_ids`, binds via the committed helper (`api/attachments.py:546`, raises `AttachmentBindError`, never commits) in the message transaction; broadcast carries attachments; then DELETE the client's bind call + (thread,content) correlation + 2s debounce. Also enables empty-caption-with-attachments (`handlers.py:203`). Single owner; handlers.py is free.
5. **Device-level checks only Amo/Dan can run:** phone → Iran room → "@Claude what's oil at right now" (watch the activity label + trace footer); "Open Full Dashboard" tap; paste a chart, ask about it; the buzz test (force a critical flip via td manual override).

## Gotchas that will bite the unwary

- **Both systemd units run their git WORKING TREES.** Every restart deploys whatever is on disk. Never restart while any agent/editor holds uncommitted edits. Deploy = review → commit → restart → poll a real 200 → verify the specific behavior.
- **Deploy order for auth-touching work:** td secret/shim changes → restart td → THEN dialectic frontend flip (else deep-link clicks log people out of td).
- `journalctl --since` parses LOCAL (CDT) time; app logs stamp UTC. An empty window may be your timezone, not absence.
- nginx: `sites-enabled/dialectic` is now a real **symlink** to sites-available (drift class eliminated). The dialectic vhost carries `attachments` in the proxy regex + `client_max_body_size 310m` + `proxy_request_buffering off` — all three required for media.
- tradingDesk's SPA catch-all answers unknown GET paths **200 + text/html**. Never trust a status code from td without checking content-type.
- The td quotes cold path is 18.5s (per-book Yahoo refetch with sleeps); the tool timeout for it is 20s and the 240s cache makes repeats 10ms. The real fix (serve from coordinator data) is future work.
- Interim bridge timer (`tradingdesk-bridge.timer`, 30min) is STILL ENABLED as a belt — disable after a clean week of coordinator pushes: `systemctl disable --now tradingdesk-bridge.timer`.
- Env now load-bearing (names only): dialectic — `TRADINGDESK_URL/USER/PASSWORD`, `TD_SERVICE_TOKEN`, `SIGNUPS_ENABLED`, `SCHEDULER_ENABLED`, `DIALECTIC_TOOLS_ENABLED`, `DIALECTIC_VISION_ENABLED`, `MEDIA_ROOT`; td — `DIALECTIC_URL`, `DIALECTIC_SERVICE_PASSWORD`, `TD_SERVICE_TOKEN`, `DIALECTIC_USER_MAP`, `JWT_SECRET` (= dialectic's `JWT_SECRET_KEY`).
- Known accepted trades: 72h exchanged tokens outlive `DIALECTIC_USER_MAP` removal (third-chair scope); receiver-side media race covered by a 2s debounce until #12; the (thread,content) correlation's only real hole is a sub-round-trip double-send with identical content + asymmetric attachments.

## Where the deeper records live

- Owner rulings + scope interpretation: `docs/plans/2026-Q3-consigliere-amendment-1-fusion.md`
- Vision status: `docs/VISION.md` §Status update 2026-08-09
- Cross-session memory: `~/.claude/projects/-root-DwoodAmo/memory/fusion-2026-08-09-state.md`
- The agents' full reports (mutation-test evidence, deviations, escalations) are in this session's transcript; every accepted deviation is restated in the relevant commit message.
