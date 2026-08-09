# Fusion — tradingDesk × Dialectic → one app, with hands, eyes, and media

> **EXECUTED 2026-08-09 (overnight).** Parts 0, A1–A6, B1–B7, C1/C2, D — live
> in production and verified. Still open: C3/C5 (repo move + doc hygiene,
> weekend), A7 (non-streaming tool paths — deliberately gated on
> streaming-path trust), C4 (the cull), A8 (`draft_prediction`, trust-gated
> ~2026-08-16), and the transactional attachment bind (see task board /
> handoff). Execution record: `docs/handoffs/2026-08-09-fusion-overnight.md`;
> plan deltas discovered during execution are noted there rather than
> silently edited here.

## Context

Amo's ask (2026-08-08): scour /root/tradingDesk + /root/DwoodAmo, fuse into **one app**.
Dan is in and active; more people may follow. Felt problem: *"arguing with one LLM that
doesn't have access to anything but some random data I put in there two months ago."*
Follow-ups: trading is the hot wedge but **not a sandbox** — the scheme abstraction stays;
and this is **not** permission to skimp on QoL/strengthening/connectivity — **tools, and
rich media (images, files, video), are in scope**. Self-hosted droplet, full control.

### Verified diagnosis (explorers, file:line-backed)

- tradingDesk is **alive** (tradingdesk.service, :8006, 4d uptime) fetching Yahoo +
  Polymarket + derived RSI/ATR every 300s across 5 causal-DAG thesis books; 146,713
  snapshots banked (872MB SQLite). All 5 books current **through today**.
- The bridge to Dialectic was manual + validated against a **mock**
  (`tools/validation/mock_dialectic.py`). Last real push: Iran room **2026-06-05**.
  tradingDesk's DB outbox: **58,769 rows, all pending, no drainer**.
- Dialectic suppresses trading data >168h old (`llm/prompts.py:221-252`) → the flagship
  room's prompt literally reads "Market data is suppressed."
- Dialectic's LLM: **zero tool use** (`llm/providers.py` raw text-in/out; would crash on a
  tool_use block). **No scheduler** anywhere (lifespan runs nothing on a timer).
- tradingDesk already shipped an **agent-facing API nobody calls**: `/api/v1/commands`
  (JSON-schema'd), `/api/v1/bootstrap`, machine-readable WS protocol, agent log stamping
  the snapshot revision reasoned against.
- Two live contract bugs in `prompts.py` (scenarios never render — reads a Record as a
  list, :315-332; cascadePhase reads wrong keys, :260-270). Wire truth =
  `export_state()` (thesisgraph.py:845-931); frontend + curator already read it right.
- Only 2 of 5 books have rooms. Dark-but-tested fetchers (GDELT news + Treasury: keyless;
  FRED/EIA: need keys) wired to CLI only.
- Governing docs: `docs/VISION.md` ("writes messages and memories — does not take
  external actions") and committed Q3 plan `docs/plans/2026-Q3-consigliere.md`
  (P1 push ✅ → P2 self-model → P3 scheduler/briefs → P4 FSM → P5 research +
  scheme_state generalization → P6 benchmark). Fusion lands as **amendments beside**
  the plan, never silent edits.
- nginx vhost for dialectic has **no client_max_body_size** → 1MB default blocks uploads
  (must be raised for media). Droplet: 52GB free.

## Decisions locked (Amo, 2026-08-09)

1. **Monorepo move: YES** — git subtree → `/root/DwoodAmo/trading/`, weekend slot.
2. **Push buzz: critical-only** — critical node flips/phase changes buzz pockets;
   warnings in-room; info silent.
3. **Proposal-writes: yes, after a trust week** — read-only tools first, then
   `draft_prediction` with human Accept.
4. Trading is the hot wedge; scheme generalization (P5) inherits a living template.
5. Full platform build-out: media (images/files/video) is a first-class workstream.

---

## Part 0 — Jump-start (hour one, zero code)

1. Append `DIALECTIC_URL=http://127.0.0.1:8002` to `/root/tradingDesk/.env`.
2. `cd /root/tradingDesk && venv/bin/python tools/bridge/run-all.py --dialectic-url
   http://127.0.0.1:8002` — per-book tokens live in book meta; June-vs-today diff
   forces a push for both live rooms. **First-ever real-integration test** (prior
   validation was against the mock): confirm HTTP 200 + memory_id,
   `TRADING_SNAPSHOT_RECEIVED` event, curator alert. Any 400 = contract drift, body
   in stderr.
3. Interim clock: systemd timer `tradingdesk-bridge.{service,timer}` (OnCalendar
   `*:00/30`) running the same command; removed at B-Step 5.
4. Delete the two debris spools in `snapshots/outbox/`.
5. Device check: Iran room chip reads minutes-old; @Claude cites a current Brent price.

## Part A — Hands and eyes (LLM tool use)

New modules `dialectic/llm/tool_loop.py` (agentic loop) + `dialectic/llm/tools.py`
(curated registry) + `dialectic/llm/tradingdesk_client.py` (httpx singleton, service
JWT, loopback :8006). No SDK — raw httpx house style.

- **A1 Providers** (`llm/providers.py` + `tests/test_providers_tools.py`): LLMRequest
  gains `tools`/`tool_choice`; LLMResponse gains `tool_calls`/`raw_content`; pure
  `_parse_anthropic_message` (also fixes latent crash on non-text-first blocks); new
  `stream_events()` with SSE fold handling `content_block_start`/`input_json_delta`;
  OpenAI raises `ToolsUnsupportedError` (tools are Anthropic-only).
- **A2 Router** (`llm/router.py`): chain filters non-Anthropic entries when tools ride;
  `route()`/`stream()` must copy tools into the rebuilt request (today they'd silently
  drop them); `stream_events()` mirroring pre-first-token fallback.
- **A3 Service auth**: `/root/tradingDesk/web/auth.py` gains env-gated `dialectic`
  service user (`DIALECTIC_SERVICE_PASSWORD`); client env `TRADINGDESK_URL/USER/PASSWORD`.
- **A4 Loop** (`tool_loop.py`): max 5 iterations, 60s budget, per-tool 10s timeout;
  every failure becomes `is_error` tool_result — **the room never goes silent**; at
  cap, `tool_choice: none` forces a text landing; Anthropic chain exhausted → strip
  tools, re-route text-only (`degraded=true`).
- **A5 Wire streaming @claude path + UX** (the felt moment): orchestrator
  `stream_response` → `ToolLoop.run_streaming`; new WS type `llm_tool_activity`
  (`transport/websocket.py`, both handler stream sites); frontend TypingIndicator
  shows live labels ("Claude is checking live prices…"); MessageBubble renders a
  collapsed "used N tools" trace (name/args/latency/**snapshot revision** — provenance
  stolen from tradingDesk's agent log). Persist trace in `messages.metadata->'tools'`.
- **Tools (9, read-only)**: get_live_quotes, get_polymarket_odds, get_thesis_state
  (size-capped), diff_thesis_last_hour, evaluate_scenario (what-if vs committed
  revision), get_open_trades, get_morning_brief, **search_memories** (three-lane
  recall as a tool — beats the 20-memory prompt cap), search_transcript. Plus
  get_thesis_news once B ships the news endpoint. Excluded: ui.focus_panel (side
  effect). Registry supports pass-through server tools so P5's web_search is one line.
- **A6 Prompt rework** (`llm/prompts.py`): staleness gate becomes degrade-not-annihilate
  (structure stays, stale *numbers* flagged "do not cite — fetch live via tools");
  render marketSnapshot + tvIndicators (stored today, never rendered); "Your Tools"
  section; bookend: cite only thesis state or received tool results.
- **A7 Non-streaming paths + self-model**: on_message + force_response through the loop
  (provoker/protocol/annotator: **never** — commented why); `log_decision` gains
  tool_calls; migration adds `llm_decisions.tool_calls JSONB`; schema.sql sync.
- **A8 (trust-gated) Proposal-writes**: `draft_prediction` returns a structured
  proposal persisted as message metadata + Accept affordance; on human tap, a small
  Dialectic relay endpoint POSTs to tradingDesk `/api/predictions` under the service
  credential. Claude itself only ever writes messages/memories.
- Kill-switch: `DIALECTIC_TOOLS_ENABLED` env.

## Part B — Bloodstream (data revival + the scheduler organ)

- **B1 Contract fixes** (`llm/prompts.py` :260-270, :315-332): read cascadePhase
  `{number,key,status}` and scenarioImpacts as Record. Regression test uses the REAL
  captured snapshot `/root/tradingDesk/snapshots/iran-hormuz-graph-latest.json` as
  fixture — never invented payloads again.
- **B2 Scheduler** (new `dialectic/scheduler.py` ~150 lines + `dialectic/trading_watch.py`
  + migration `008_scheduler_bloodstream.sql`): asyncio task in lifespan, Postgres
  advisory lock, generalized `scheduled_job_runs` ledger with
  `UNIQUE(job_name, scheduled_for)` insert-or-skip idempotency (supersedes P3's
  planned night_shift_runs — P3 jobs will register on THIS scaffold). Adds
  `rooms.linked_book_id` + backfill for the two live rooms. Jobs: `trading_reconcile`
  (15m pull), `trading_freshness_watchdog` (30m — >3h quiet posts ONE deterministic
  in-room warning, >12h also web-push), `heartbeat` (ledger-only liveness).
- **B3 Ingest extraction + gating** (new `api/trading_ingest.py` from main.py:1245-1332;
  `llm/trading_curator.py`): snapshot v3 carries `alertEvents`; curator fires ONLY on
  warning+ events (today it fires on every receipt — with 300s pushes that's Haiku
  spam); dedup 5m critical / 30m warning; daily cap 8/room (criticals bypass cap, not
  dedup); heartbeat pushes are silent; reconcile-pulled snapshots never fire curator.
  **Critical events → web push** (Phase-1 channel, `tag=trading_{room_id}` collapses
  repeats, <60s target).
- **B4 tradingDesk push side** (new `web/runtime/dialectic_push.py`; `coordinator.py`
  step-11.5 hook): inline push on material change + hourly heartbeat, 10s timeout,
  never raises into the cycle; failure spools to the **file** outbox (kept — it dedups
  to newest-per-room and has replay UI); success drains it. **DB outbox dies**: SQLite
  migration `004_drop_outbox.sql`, five Repository methods deleted, one-time
  stop→drop→VACUUM (reclaims ~200MB). New `GET /api/bridge/snapshot/{thesis_id}` +
  `GET /api/bridge/news/{thesis_id}` (service-token; the news seam A's tool consumes).
  Service token via `TD_SERVICE_TOKEN` constant-time compare in `web/auth.py`.
- **B5 Dark feeds lit** (`coordinator._fetch_slow_feeds` + TTL cache): GDELT (900s) +
  Treasury (3600s) + econ-calendar deadline patching light up keylessly on deploy;
  FRED/EIA light up the moment Amo pastes keys into `trading/.env` (fetchers already
  env-gated). News *signal* flows through existing node mechanism; *articles* stay
  behind the news endpoint for on-demand tool fetch (never into the 800-token prompt
  budget, never as curator spam).
- **B6 Rooms for the 3 orphan books** (runbook, one-time): POST /rooms → join both
  users → `UPDATE rooms SET linked_book_id` → set `dialecticRoomId/Token` in each book
  JSON meta → ONE tradingdesk restart (meta loads at startup). Update the rooms table
  in `dialectic/CLAUDE.md`.
- **B7 SQLite hygiene** (new `web/runtime/maintenance.py`, daily 04:30 UTC): keep last
  2016 revisions/book + first-per-day older (daily downsample); fetch_runs >14d
  deleted; guarded monthly VACUUM. 872MB → ~100-150MB bounded.

## Part C — One app (consolidation)

**Thesis: Dialectic is the app; tradingDesk becomes its market-cognition organ.**
tradingDesk's own last commits built a Dialectic-cosplay "Field Desk" and made it the
default view — the desk was already trying to become Dialectic; we grant the wish
properly. Engine (thesisgraph, data_fetch, outcomes, 5 books) = promoted backend.
Deep UIs (Thesis Builder, DAG canvas, prediction tracker, journal) = linked deep
surface at td.somacura.org (stays public — TradingView HMAC webhooks arrive there).
Duplicated social tier (chat/rooms/LLM proxy/auth) = dies.

- **C1 Auth bridge (Day 2)**: both sides are HS256 — set tradingDesk `JWT_SECRET` =
  Dialectic `JWT_SECRET_KEY`; ~40-line claim shim in `web/auth.py` mapping Dialectic
  `sub` UUIDs → td users via `DIALECTIC_USER_MAP` allowlist. **Same-day rider,
  non-negotiable**: close Dialectic's open signup behind `SIGNUPS_ENABLED=false`
  (`api/auth/routes.py:95`) — once td trusts Dialectic tokens, open signup is a hole.
- **C2 Deep link (Day 2)**: the dead span at `TradingPanel.tsx:255` becomes a real
  per-book link to td.somacura.org; Dan reaches the live DAG canvas with zero extra
  logins.
- **C3 Repo move (weekend)**: `git subtree add --prefix=trading /root/tradingDesk
  master` (107 commits preserved); 872MB DB relocates to `/var/lib/tradingdesk/` +
  symlink (git clean can never eat it; `DEFAULT_DB_PATH` in
  `web/persistence/connection.py:15` is package-relative — add `TRADINGDESK_DB_PATH`
  env override as follow-up); .gitignore extended (trading/venv, web/data, dist,
  *.db); systemd unit repointed (`WorkingDirectory=/root/DwoodAmo/trading`, host
  narrowed 0.0.0.0→127.0.0.1 — nginx is the only legit caller); venv rebuilt; old repo
  tagged `pre-fusion-final` → `/root/tradingDesk-archive` (5-min rollback). Docker
  files deleted (house law). Untracked junk not migrated.
- **C4 The cull (wk 2, after tools ship)**: td chat/rooms/messages routes + chat WS
  lane die (36 rows exported to docs/archive first; machine-readable WS protocol
  survives for agents); Field Desk cockpit: flip default view back FIRST (revert
  0d447fb), archive branch, delete 1,944 lines; `web/state.py` (413 dead lines) and
  `mock_dialectic.py` deleted after a clean week of real delivery. **Kept with stated
  landing places**: `/api/llm/compare` multi-model fan-out (deep-surface power-tool;
  candidate "Panel of Rivals" Dialectic protocol next quarter), Thesis Builder +
  canvas (deep surface indefinitely), prediction/journal UIs (first panel-port
  candidates next quarter). td local login dies at P6 after 30 days of bridge-only.
- **C5 Doc hygiene (weekend)**: `.planning/*` (stale "v2.0 Complete" mobile corpus) →
  `docs/archive/` with tombstone README; root CLAUDE.md rewritten as monorepo map;
  dialectic/README.md fixed (retired app.html, wrong counts); trading/README.md
  refreshed ("zero deps/118 tests" predates the web layer); INTEGRATION.md's false
  "FULLY IMPLEMENTED" corrected as a *recorded* correction (what was true, what
  wasn't, what is now); root README repo-layout gains `trading/`.

## Part D — Media: images, files, video (new workstream, Amo directive)

Dialectic is text-only today. Build attachments end-to-end; Claude gets **vision** on
images (rides A1's content-block rework — same seam, not a bolt-on).

- **D1 Storage + API**: migration `attachments` table (id, room_id, message_id,
  uploader_user_id, kind image|video|file, mime, bytes, sha256, width/height,
  original_name, storage_path, created_at). Files at
  `/var/lib/dialectic/media/<room>/<sha>/…` (never in git, never in /var/www
  releases). `POST /rooms/{id}/attachments` (multipart, room-token + JWT + membership
  — same guards as message writes); `GET /attachments/{id}` streams with membership
  auth. nginx: add `attachments` to the REST proxy regex + set `client_max_body_size`
  on the dialectic vhost (currently ABSENT → 1MB default 413s everything). Caps:
  images/files 25MB, video 300MB; mime allowlist; sha256 dedup.
- **D2 Frontend**: MessageInput gains attach button + clipboard paste + drag-drop +
  upload progress; send_message carries attachment ids; MessageBubble renders images
  inline (CSS-scaled, lazy), video via HTML5 `<video preload=metadata>`, files as
  chip (name/size/download). Push notification body: "Dan sent an image/file/video."
  Service worker: network-first for /attachments.
- **D3 Claude sees images**: when context includes image attachments (or @Claude on
  one), orchestrator builds content-block messages with base64 image blocks (per-image
  ~5MB cap, oversized skipped with an in-prompt note). "@Claude what's wrong with this
  chart?" becomes real. **Video: store/play/share only** — Claude does not watch video
  (honest limit; frame-extraction is a possible later add).
- **D4 Acceptance**: paste a chart screenshot on one phone → renders on the other <5s
  with labeled push; @Claude comments on visible chart content; 100MB video uploads,
  plays on both devices; non-member fetch of an attachment URL → 403.

## Week-one felt sequence (merged)

- **Day 1** — the chip turns green: jump-start push; Iran + Tariffs rooms fresh; Claude
  cites today's Brent. Contract fixes + scheduler deploy (B1/B2).
- **Day 2** — one tap, no second login: deep link + auth bridge + signup guard (C1/C2).
- **Day 3** — Claude reaches for the desk: streaming tools live (A1-A5); "checked just
  now" with a timestamp, mid-argument.
- **Day 4** — the other three books wake up: five rooms, five green chips (B6).
- **Day 5** — the pocket buzz: critical node flip → lock-screen push <60s (B3/B4).
- **Weekend** — invisible work: repo move, doc sweep, amendments committed (C3/C5).
- **Week 2** — media lands (D1-D2), staleness rework + non-streaming tools (A6/A7),
  the cull (C4), vision (D3), hygiene (B7).
- **Week 3** — trust week passed → `draft_prediction` with Accept (A8); soak checks.

## Plan amendments (amend-beside, never edit)

New `docs/plans/2026-Q3-consigliere-amendment-1-fusion.md` (+ one pointer line in the
original): inserts **Phase 2.5 "The desk plugs in"**; scheduler organ pulled forward
built to P3's exact spec (P3 shrinks to brief content/etiquette; freed weeks buffer
P4); migration numbers declared logical-not-literal (008 = scheduler ledger;
`night_shift_runs` superseded by the generalized ledger); VISION's "no external
actions" line interpreted on the record — tools are reads of our own systems +
human-confirmed proposals, order placement categorically out; trading-critical events
extend the P1 push channel; media workstream added under "scope: everything";
monorepo governance declared; scheme abstraction reaffirmed (trading = hot wedge, P5
generalizes a living template). P4 FSM, P6 benchmark, all six owner decisions
untouched.

## Verification (device-level, falsifiable — house style)

1. Iran chip <60m within hour one; any 4xx from the real endpoint = fail.
2. "@Claude what's oil at right now" → live number matching `/api/market/quotes` same
   minute + tool trace in `messages.metadata`; **price cited with empty trace = fail**.
   `systemctl stop tradingdesk` → Claude answers in text naming the failed check.
3. Restart dialectic twice in 10 min → ledger shows zero duplicate
   `(job_name, scheduled_for)` over 24h.
4. Kill test: tradingdesk down 2.5h → exactly one watchdog message per linked room,
   no human action; recovery → fresh chip, no second warning.
5. Buzz test: manual-override a node to `fired` → both locked phones buzz <60s naming
   the node; `approaching` → zero pushes.
6. Fatigue: ≤8 curator messages/room/day; zero from heartbeat pushes.
7. Five rooms fresh <1h at a fixed morning check, 7 consecutive days.
8. Media: cross-device image <5s + push; @Claude reads the chart; 403 for non-members.
9. tradingdesk.db ≤150MB after reclaim, <5MB/week growth over two weekly checks.
10. Scenario regression test renders phase + scenarios from the REAL captured fixture
    (fails against pre-fix code).

## Risks / notes

- Token growth from get_thesis_state → executor-side size caps, not trust.
- @claude latency +1-3s per tool round-trip → the live activity label converts "slow"
  into "alive".
- Migration numbers assigned at implementation (collision guard with in-flight Q3).
- SW/PWA update risk on media SW change — test one device before symlink flip (P1's
  own lesson).
- Streaming text-before-tool-call concatenates across loop iterations into one
  persisted message — accumulated-content handling covered in A5.
- Multi-user readiness (invite gate, token revocation, email delivery, roles) is
  flagged as next quarter's "The third chair" — only the signup flag is in this
  cycle's path.
