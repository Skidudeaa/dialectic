# TradingView Integration — Webapp-First Architecture

**Date:** 2026-04-10
**Replaces:** `.planning/tv-plan/plan-alpha-v2.md` (CLI-centric, pre-webapp)
**Origin decision:** "needs to be built into this application as an integrated part of the 'webview/webapp'. this isn't 2 different or 3 different projects. these are all a part of the same set of tools." — operator, 2026-04-10

## 1. Why this plan replaces Alpha v2

Alpha v2 was written on 2026-04-05, two days before the FastAPI + React webapp shipped (v0.2.0, 2026-04-07). Alpha assumes a CLI world: `tv-webhook.py` is a standalone `BaseHTTPRequestHandler` running on port 8787 under systemd, managed separately from `run-all.py` and the thesis-graph tool. That architecture made sense *before* the web layer existed.

Now that `web/` is the primary interaction surface — JWT auth, WebSocket chat, LLM routing, trade journal, prediction tracker, morning brief, cross-book panel — spinning up a *second* HTTP server on a different port for Pine alerts would fracture the system. Two process lifecycles, two TLS stories, two monitoring stories, two deployment stories. No.

This plan keeps Alpha's **engine contract** intact (the hard-won epistemic discipline of `overlay: true`, the four pre-declared mutation ops, the HMAC/nonce/timestamp webhook security posture, the closesObserved counter integration) and re-homes the operator-facing machinery into the existing FastAPI app.

## 2. What stays, what moves

| Component | Alpha v2 home | This plan's home | Why |
|---|---|---|---|
| Pure RSI/ATR/SMA math | `tools/data-fetch/derived_indicators.py` | **SAME** | Stdlib, zero deps, shared between CLI `--fetch` path and web adapters. No reason to move. |
| OHLCV stash + `compute_derived_indicators()` | `tools/thesis-graph/thesisgraph.py` | **SAME** | Engine-level concern; runs during `thesisgraph.py --fetch`, invoked by both `run-all.py` and `web/adapters/thesis.py`. |
| `tvIndicators` snapshot field (v:2 schema) | `export_state()` in `thesisgraph.py` | **SAME** | Snapshot is the single source of truth for both CLI push-to-dialectic and web `/api/thesis/{id}/state`. |
| `tvIndicatorShifts` diff category | `tools/bridge/diff-snapshots.py` | **SAME** | Consumed by `run-all.py` and by `web/adapters/thesis.py` (cache invalidation hook). |
| `tvAlertBindings` node schema | Book JSON files | **SAME** | Config-as-data, read by the webhook handler regardless of where the handler lives. |
| **HMAC verify / timestamp window / nonce store** | `tools/bridge/tv-webhook.py` (BaseHTTPRequestHandler) | **`web/tv_webhook.py`** (pure functions, stdlib only) | Move the verification logic into a testable pure-function module the FastAPI route imports. |
| **Pine alert HTTP endpoint** | `tools/bridge/tv-webhook.py` (port 8787) | **`web/routes/tradingview.py`** (FastAPI route `POST /api/tradingview/webhook`) | Single process, single port, same TLS termination as the rest of the API. |
| **Atomic book mutation** | `tv-webhook.py` inline | **`web/adapters/tradingview.py`** | Thin adapter; uses `asyncio.to_thread` for the blocking write; invalidates `web/adapters/thesis.py` cache; broadcasts via `web/ws.py`. |
| **Bindings management** | Manual JSON editing | **`GET/POST/DELETE /api/thesis/{book_id}/tv-bindings`** + frontend UI | Operators edit bindings from the dashboard, not by hand-editing book JSON. |
| **Indicator visualization** | Static HTML (generated) | **`ThesisViewer.tsx` + new `TradingViewPanel.tsx`** | Live, reactive, updates on WebSocket push. |
| **Alert stream** | Log file only | **WebSocket broadcast to all connected clients in the book's room** | Two-analyst team sees alerts in real time. |

## 3. Architecture diagram

```
Pine Script alert on TradingView
        │  POST /api/tradingview/webhook
        │  X-TV-Signature, X-TV-Timestamp, X-TV-Nonce
        ▼
  FastAPI route (web/routes/tradingview.py)
        │  - Rate limit (per-IP token bucket)
        │  - HMAC verify via web/tv_webhook.py (stdlib pure funcs)
        │  - Timestamp window / nonce replay check
        │  - Pydantic validate body → TVWebhookAlert
        ▼
  Adapter (web/adapters/tradingview.py)
        │  - Load book via existing path-validated helper
        │  - Resolve bindingId → (node, binding)
        │  - Enforce op/type contract (four ops only)
        │  - asyncio.to_thread → atomic tmp+replace book write
        │  - Invalidate thesis_adapter cache for this book_id
        │  - Append event to web/data/tradingview-events.jsonl
        ▼
  WebSocket broadcast (web/ws.py)
        │  {type: "tv-alert", bookId, nodeId, op, newValue, ...}
        ▼
  Connected clients in the book's room
        │  ThesisViewer auto-refreshes via apiFetch(/api/thesis/{id}/state)
        │  TradingViewPanel prepends the alert to its feed
        │  Chat room gets a system message: "TV ALERT: brent closesObserved 2 → 3"
        ▼
  Next scheduled run-all.py / next manual /api/thesis/.../fetch-prices
        │  compute_derived_indicators populates tvIndicators
        │  diff-snapshots reports tvIndicatorShifts
        │  push-to-dialectic propagates the new state
```

Every arrow above already exists in the codebase except for the three bolded boxes: the FastAPI route, the adapter, and the frontend panel. The rest is reuse.

## 4. New / modified files

### NEW

| Path | Est. lines | Purpose |
|---|---|---|
| `tools/data-fetch/derived_indicators.py` | 180 | Pure stdlib RSI(14)/ATR(14)/SMA(N) + closes-above-threshold counter. From Alpha v2, unchanged. |
| `tools/data-fetch/test_derived_indicators.py` | 260 | 48 tests — Wilder 1978 reference sequence, edge cases. From Alpha v2. |
| `web/tv_webhook.py` | 120 | Pure HMAC verify, timestamp window check, nonce store (in-process dict + TTL). Stdlib only. Importable by the route AND directly unit-testable. |
| `web/adapters/tradingview.py` | 200 | Adapter: load book, resolve binding, enforce op/type contract, atomic write, cache invalidation, event log append, broadcast trigger. |
| `web/routes/tradingview.py` | 180 | FastAPI routes: POST webhook (unauthenticated, HMAC-gated), GET/POST/DELETE bindings (JWT-gated), GET recent alerts, GET webhook status. |
| `web/test_tradingview.py` | 400 | 60+ tests across three classes: TestTVWebhookAuth (HMAC/nonce/timestamp), TestTVWebhookApply (all four ops, op/type mismatches, atomic write, concurrency), TestTVBindingsAPI (CRUD + auth guards + path validation). |
| `frontend/src/components/TradingViewPanel.tsx` | 220 | Right-panel tab: binding list per book, recent alert feed (last 20), webhook URL with copy-to-clipboard, HMAC secret status, "create binding" modal. |
| `frontend/src/components/TVIndicatorBadge.tsx` | 60 | Small inline RSI/ATR badge for ThesisViewer node rows. Colors: RSI>70 red, RSI<30 green, else gray; ATR shown as numeric. |

### MODIFIED

| Path | Lines Δ | Change |
|---|---|---|
| `tools/thesis-graph/thesisgraph.py` | +55 | `fetch_prices()` stashes OHLCV into `cfg["_ohlcv"]`. New `compute_derived_indicators(cfg)` (~35 lines). Wired into `main()` after `fetch_polymarket`. `export_state()` bumps to `"v": 2` with top-level `tvIndicators`. |
| `tools/thesis-graph/test_export.py` | +40 | 7 new tests: v:2 shape, backward-compat (nodes without `derivedIndicators`), tvIndicators flow, closesObserved auto-increment. |
| `tools/bridge/diff-snapshots.py` | +45 | New `tvIndicatorShifts` category (RSI deltas > 8 points, ATR deltas > 15%). v:1↔v:2 tolerant — falls back to empty set when field absent. |
| `tools/bridge/test_diff.py` | +24 | 7 new tests for tvIndicatorShifts. |
| `web/models.py` | +60 | New Pydantic models: `TVBinding`, `TVWebhookAlert`, `TVIndicatorReading`, `TVBindingCreateRequest`, `TVWebhookAck`, `TVAlertEvent`. |
| `web/main.py` | +2 | Register `tradingview` router. |
| `web/adapters/thesis.py` | +8 | Public `invalidate(book_id)` method (or expose via module function); called by the tradingview adapter after a mutation. |
| `web/ws.py` | +15 | New `broadcast_to_book_rooms(book_id, event_dict)` helper — finds rooms linked to this book via `meta.thesisBookId` and fans out. |
| `web/state.py` | +20 | New namespace: `tradingview_events` → JSONL append log at `web/data/tradingview-events.jsonl` with timestamp, bookId, nodeId, op, newValue, applied-by (webhook vs operator). |
| `frontend/src/components/ThesisViewer.tsx` | +35 | Inline `<TVIndicatorBadge>` beside each node that has `tvIndicators`. New "last TV alert" row under the cascade phase header. |
| `frontend/src/components/Dashboard.tsx` | +10 | Mount new `TradingViewPanel` as a right-panel tab alongside PredictionTracker / TradeJournal. |
| `frontend/src/lib/api.ts` | +45 | New functions: `listTVBindings(bookId)`, `createTVBinding(bookId, binding)`, `deleteTVBinding(bookId, bindingId)`, `getTVAlertEvents(bookId, limit)`, `getWebhookStatus()`. |
| `frontend/src/lib/types.ts` | +30 | TypeScript interfaces mirroring the new Pydantic models. |
| `books/iran-hormuz-graph.json` | +18 | `derivedIndicators` on brent/diesel/em-currency/food-spike. `tvAlertBindings` seeded with the three from Alpha v2's First Three Trades. |
| `books/trump-tariffs-graph.json` | +22 | `derivedIndicators` on input-costs/usd-cny/auto-sector. `tvAlertBindings` for the SPY-short trade's Pine alert. |
| `.env.example` | +3 | `TV_WEBHOOK_SECRET=` (required, no default), `TV_WEBHOOK_RATE_LIMIT_PER_MIN=60`, `TV_WEBHOOK_NONCE_TTL_SECONDS=600`. |
| `CLAUDE.md` | +50 | New architecture section; update test count to ~460 total. |
| `CHANGELOG.md` | +40 | Feature entry. |

**Total estimate:** ~1,300 new lines + ~380 modified = ~1,680 LoC. ~130 new tests (48 derived_indicators + 60 web_tradingview + 7 export + 7 diff + 8 e2e). Target test total: **~460** (was 333 post-consolidation).

## 5. The four mutation ops (unchanged from Alpha v2)

Webhook payloads carry only `bindingId` + optional numeric `value`. Everything else is looked up from the pre-declared binding in book JSON. No free-form field writes.

| `op` | Mutates | Valid node types | Constraint |
|---|---|---|---|
| `incrementClosesObserved` | `node.closesObserved` (int, +=1) | `price`, `reversal` | Drives the existing `closesRequired` gate at `thesisgraph.py:201` |
| `setNodeState` | `node.state` (string) | `event` | Target state must be one of `active/resolved/partial/monitoring/fired` |
| `setProbability` | `node.probability` (float) | `event` | Value must be in `[0.0, 1.0]` |
| `setCurrent` | `node.current` (float) | `price`, `reversal`, `constraint` | Numeric only |

The route handler enforces every row.

## 6. Webhook request contract (unchanged from Alpha v2)

```
POST /api/tradingview/webhook
Content-Type: application/json
X-TV-Signature: sha256=<hex hmac of raw body with TV_WEBHOOK_SECRET>
X-TV-Timestamp: 1712347890
X-TV-Nonce: a8f3d2e9c1b47f29

Body (≤ 8 KiB, JSON):
{
  "book": "iran-hormuz-graph",
  "bindingId": "brent-persistence-close-above-115",
  "value": 115.42,
  "pineAlertName": "brent_persistence_close_115",
  "chartSymbol": "TVC:UKOIL"
}
```

Response codes:
- `200` → `{"status": "ok", "nodeId": "brent", "op": "incrementClosesObserved", "newValue": 3}`
- `400` → malformed body / bad book id / missing nonce / oversized body
- `401` → HMAC mismatch
- `404` → unknown book or bindingId
- `409` → nonce replay
- `410` → timestamp outside ±300s window
- `422` → op/type mismatch or value out of range
- `429` → rate limit exceeded (new in this plan — stdlib token bucket, per-IP)
- `500` → `TV_WEBHOOK_SECRET` not configured

## 7. Snapshot v:2 additions (unchanged from Alpha v2)

`export_state()` emits `"v": 2` with an optional top-level `tvIndicators` dict keyed by nodeId. Existing snapshot consumers (mock_dialectic, diff-snapshots, push-to-dialectic) tolerate unknown keys; no consumer changes needed. The `v` bump is informational.

```json
{
  "v": 2,
  "tvIndicators": {
    "brent": {
      "rsi14": 64.3,
      "atr14": 3.21,
      "source": "derived_from_yahoo",
      "computedAt": "2026-04-10T07:58:32Z"
    }
  },
  ...existing keys unchanged...
}
```

## 8. WebSocket broadcast schema

New message type on the existing room WebSocket:

```json
{
  "type": "tv-alert",
  "timestamp": "2026-04-10T14:23:07Z",
  "bookId": "iran-hormuz-graph",
  "nodeId": "brent",
  "op": "incrementClosesObserved",
  "newValue": 3,
  "bindingId": "brent-persistence-close-above-115",
  "pineAlertName": "brent_persistence_close_115",
  "thesisStateChanged": true
}
```

`thesisStateChanged` is true when the mutation caused a node state transition (computed by running `propagate()` before vs. after). Frontend uses this to decide whether to force-refresh the ThesisViewer vs. just update the TradingViewPanel feed.

Also triggers a matching system-message in the room chat:

```
[SYSTEM · 14:23:07] TradingView alert `brent_persistence_close_115` (TVC:UKOIL @ 115.42)
  → incremented brent.closesObserved to 3
  → brent node promoted: approaching → fired
```

## 9. Frontend design

### `TradingViewPanel.tsx` (new right-panel tab)

```
┌─ TRADINGVIEW ────────────────────────────┐
│ Webhook: https://.../api/tradingview/... │
│ Secret: ✓ configured      Status: READY  │
│ Rate: 60/min   Nonce TTL: 600s           │
├──────────────────────────────────────────┤
│ BINDINGS (4 active)            [+ NEW]   │
│                                          │
│ ◉ brent-persistence-close-above-115      │
│   node: brent (price)                    │
│   op: incrementClosesObserved            │
│   threshold: 115                         │
│   pine: brent_persistence_close_115      │
│   last fire: 14:23 · 3 total     [×]     │
│                                          │
│ ◉ hormuz-reopen-announced                │
│   node: hormuz (event)                   │
│   op: setNodeState → resolved            │
│   last fire: never               [×]     │
│                                          │
│   ...                                    │
├──────────────────────────────────────────┤
│ RECENT ALERTS (last 20)                  │
│                                          │
│ 14:23:07 brent closesObserved 2→3        │
│ 11:44:22 em-currency setCurrent 1.132    │
│ 09:12:01 hormuz-tension setProbability.. │
│ ...                                      │
└──────────────────────────────────────────┘
```

### `TVIndicatorBadge.tsx` (inline in ThesisViewer)

```
brent [approaching] score: 1.45   RSI14:64.3  ATR14:3.21
```

RSI badge colors (display-only, not gates): `>70` amber/red, `<30` teal/green, else muted gray. ATR shown as plain numeric.

### `ThesisViewer.tsx` modification

Add a small "Last TV alert" row under the cascade phase header showing the most recent alert from `tradingview-events.jsonl` for the active book, with a click-to-jump to the TradingView panel.

### Binding editor modal (inside `TradingViewPanel`)

Form fields:
- `bindingId` (string, kebab-case, unique per book)
- `nodeId` (dropdown of nodes in current book)
- `op` (dropdown of 4 ops)
- For `incrementClosesObserved`: `thresholdLevel` (numeric)
- For `setNodeState`: `targetState` (dropdown of 5 states)
- `expectedPineAlertName` (string, for documentation)
- `description` (textarea)

Validation mirrors the server-side enforcement — the form disables invalid op/type combos.

## 10. Phased build sequence

### Phase 1 — Engine enrichment (3 days, ~400 LoC)

**Goal:** `tvIndicators` populated in snapshot from local RSI/ATR; `closesObserved` auto-increments; tests green.

- [x] CREATE `tools/data-fetch/derived_indicators.py` (Alpha v2 verbatim)
- [x] CREATE `tools/data-fetch/test_derived_indicators.py` (48 tests)
- [x] MODIFY `thesisgraph.py` (fetch_prices stash, compute_derived_indicators, export_state v:2)
- [x] MODIFY `test_export.py` (+7 tests)
- [x] MODIFY `diff-snapshots.py` (+tvIndicatorShifts)
- [x] MODIFY `test_diff.py` (+7 tests)
- [x] MODIFY both book JSONs with `derivedIndicators` specs

**Exit:** `python3 tools/thesis-graph/thesisgraph.py books/iran-hormuz-graph.json --fetch --export-state -` produces v:2 snapshot with non-empty `tvIndicators.brent.rsi14`. Full 333 existing tests still green; 62 new tests added. Total: 395.

### Phase 2 — Webapp integration (5 days, ~900 LoC)

**Goal:** The webhook endpoint, the adapter, the bindings CRUD API, the event log, the WebSocket broadcast, and all frontend surfaces. This is the majority of the work.

- [x] CREATE `web/tv_webhook.py` (HMAC/timestamp/nonce pure functions)
- [x] CREATE `web/adapters/tradingview.py`
- [x] CREATE `web/routes/tradingview.py` and register in `web/main.py`
- [x] MODIFY `web/models.py` (+TV Pydantic models)
- [x] MODIFY `web/adapters/thesis.py` (expose `invalidate(book_id)`)
- [x] MODIFY `web/ws.py` (+broadcast_to_book_rooms)
- [x] MODIFY `web/state.py` (+tradingview_events namespace)
- [x] CREATE `web/test_tradingview.py` (60+ tests)
- [x] CREATE `frontend/src/components/TradingViewPanel.tsx`
- [x] CREATE `frontend/src/components/TVIndicatorBadge.tsx`
- [x] MODIFY `frontend/src/components/ThesisViewer.tsx` (inline badges + last-alert row)
- [x] MODIFY `frontend/src/components/Dashboard.tsx` (mount TradingViewPanel tab)
- [x] MODIFY `frontend/src/lib/api.ts` + `types.ts`

**Exit:**
- Signed POST to `/api/tradingview/webhook` → 200, book JSON mutated, WebSocket broadcast arrives at connected client, ThesisViewer auto-refreshes.
- All adversarial probes tested: bad sig → 401, expired timestamp → 410, nonce replay → 409, path traversal → 400, oversized body → 400, wrong op/type → 422, out-of-range value → 422, unknown bindingId → 404, rate limit → 429.
- Concurrent POSTs to the same book serialize without corruption (asyncio lock per book_id).
- Bindings CRUD endpoints work from frontend UI; JWT-protected; path-validated.
- Total test count: ~460 (333 existing + 62 engine + ~65 webapp).

### Phase 3 — Seed the First Three Trades (1 day, no new code)

**Goal:** Populate the bindings that make Alpha v2's First Three Trades executable via the webapp.

- Add `brent-persistence-close-above-115` binding to iran-hormuz-graph
- Add `fert-close-above-700` binding to iran-hormuz-graph
- Add `spy-below-200dma-first-touch` binding to trump-tariffs-graph
- Add `hormuz-reopen-announced` manual binding (operator fires from Pine when news hits)
- Document the corresponding Pine Script alert bodies in a new `docs/runbooks/tradingview-pine-setup.md`
- Seed an initial `tradingview-events.jsonl` entry noting "bindings provisioned 2026-04-XX"

**Exit:** An operator can copy Pine Script alert config from the runbook, paste the webhook URL from the TradingView panel, fire a test alert, and see it land in the chat room within 2 seconds.

### Out of scope (deferred)

- Bravo's multi-timeframe divergence (needs 4h fetch loop — Phase 3.5 follow-up)
- Bravo's velocity7d / forecastAtDeadline (pure functions, ~30 LoC, Phase 3.5)
- Bravo's cross-book confluence — ALREADY BUILT in `tools/outcomes/cross_book.py`. No work needed; just surface it in the TradingViewPanel alongside binding alerts.
- Bravo's morning-brief markdown renderer — out of scope per judge verdict
- Bravo's chart screenshot pipeline — out of scope per judge verdict
- Bravo's Node.js MCP subprocess — explicitly rejected

## 11. Security posture

- **HMAC**: `hmac.compare_digest` on SHA-256 of raw body with `TV_WEBHOOK_SECRET`. Constant-time comparison.
- **Timestamp window**: ±300s via `X-TV-Timestamp` header.
- **Nonce replay**: in-process dict with 10-min TTL; single process per uvicorn worker, so nonce check is worker-local — acceptable because uvicorn in this deployment runs one worker (see `docker-compose.yml`). Future multi-worker would need Redis.
- **Path validation**: `book` param must match `^[a-z0-9-]+$`; resolved path must start with `books/` absolute.
- **Body cap**: 8 KiB (FastAPI `max_length` on the request body).
- **Rate limit**: stdlib token-bucket, per-IP, 60 req/min default (env configurable). Returns 429 on overflow. Prevents DoS.
- **Op/type enforcement**: mirrors the table in §5. Each op has a dedicated branch in the adapter.
- **Secret isolation**: `TV_WEBHOOK_SECRET` is a separate env var from `DIALECTIC_ROOM_TOKEN` and `JWT_SECRET`. No op can mutate `meta.*` fields, so tokens are unreachable via webhook.
- **TLS**: in production, nginx (via `docker-compose.yml`) terminates TLS. The webhook URL in the TradingViewPanel displays the nginx-facing URL, not the uvicorn internal URL.
- **JWT-protected management**: binding CRUD endpoints require a valid JWT (amo or dan). Only the `POST /webhook` route is unauthenticated at the JWT layer (HMAC-gated instead).
- **Audit log**: every webhook event (success, auth failure, validation failure) appended to `web/data/tradingview-events.jsonl` with full context. Log is viewable from the TradingViewPanel.

## 12. Operational notes

- **Startup**: uvicorn warns if `TV_WEBHOOK_SECRET` is unset (similar to the existing `JWT_SECRET` warning in `web/auth.py`).
- **Health endpoint**: `/api/health` gains a `tradingview` block — secret configured? recent 500s? pending bindings?
- **Tests in CI**: no network calls, no extra ports; `web/test_tradingview.py` uses FastAPI TestClient.
- **Docker**: no new services; the webhook lives inside the existing backend container. `docker compose up` and you're done.
- **Rollback**: feature can be disabled by clearing `TV_WEBHOOK_SECRET` — the route returns 500 until re-configured. No code rollback needed.

## 13. Open questions

Answered before starting the build:

1. **One WebSocket room per book, or global broadcast?** → Per-book rooms via existing `meta.thesisBookId` linkage. Global fallback to "all rooms" if no linkage exists.
2. **Where does the Pine Script setup runbook live?** → `docs/runbooks/tradingview-pine-setup.md` (new dir if needed), linked from the TradingViewPanel UI via a "Pine setup guide" button.
3. **Should `compute_derived_indicators` also run from the web adapter's `fetch_prices_for_book`?** → Yes. Both CLI `thesisgraph.py --fetch` AND web `POST /api/thesis/{id}/fetch-prices` must trigger derivation. Single import point.
4. **Cache invalidation on webhook mutation?** → Yes, explicit `thesis_adapter.invalidate(book_id)` call after atomic write. The next `GET /api/thesis/{id}/state` reloads from disk.
5. **Nonce store persistence across restarts?** → No. In-memory only. A restart = empty nonce store. Combined with the 300s timestamp window, an attacker would need to replay within 300s of a restart; deemed acceptable. Future hardening could use a small JSONL at `web/data/nonces.jsonl` if needed.

## 14. Success metrics

- Phase 1 exit: 395 tests green, v:2 snapshots validated end-to-end.
- Phase 2 exit: ~460 tests green, webhook round-trip <200ms p95, frontend alert visible <2s after Pine fire.
- Phase 3 exit: all three canonical trades show bindings in the UI; Pine test-fire successful.
- 30 days post-merge:
  - Zero auth bypasses (0 successful POSTs without valid HMAC).
  - Zero atomic-write corruption incidents.
  - ≥2 cases of closesObserved reaching closesRequired via Pine before the next MWF cron batch (shortens time-to-fire).
  - RSI overlay drift vs. TradingView chart's own RSI: <1.5 points average.

## 15. What this plan replaces in `.planning/tv-plan/`

After this plan is approved and Phase 1 starts, the following files should be left in place as historical design record (the competition was real; the verdict is still instructive):

- `plan-alpha-v1.md` / `plan-alpha-v2.md` — historical
- `plan-bravo-v1.md` / `plan-bravo-v2.md` — historical, some ideas deferred
- `judge-verdict.md` — historical, philosophy still valid
- `red-team-alpha.md` / `red-team-bravo.md` — historical
- `codebase-map.md` — stale (predates webapp), should get a one-line "see docs/plans/2026-04-10-..." pointer at the top
- `research-context.md` — historical

No deletion. The `.planning/tv-plan/` directory is the competition-era design record; this plan in `docs/plans/` is the build spec.
