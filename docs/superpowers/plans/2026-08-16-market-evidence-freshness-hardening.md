# Market Evidence Freshness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Polymarket and GDELT tool result distinguish live, cached, confirmed-empty, stale, unavailable, and not-configured evidence with auditable timestamps.

**Architecture:** tradingDesk remains the producer. `web.routes.bridge` owns bounded caches, single-flight, provider state, and freshness payloads; Dialectic strictly validates those payloads and converts current provider degradation into failed tool traces while preserving timestamped prior observations. The legacy browser surfaces keep their existing list contracts.

**Tech Stack:** Python 3.12, FastAPI, asyncio, `concurrent.futures.ThreadPoolExecutor`, httpx, pytest, existing Gamma and GDELT clients

## Global Constraints

- No database migration, new provider, credential, environment variable, or config layer.
- Preserve `GET /api/market/polymarket` as a best-effort list with null membership and its 15-second budget.
- Preserve the Dialectic Bench Polymarket response as a current-only list; never unwrap stale history into it.
- Timestamps are UTC ISO-8601; ages use monotonic elapsed time and are recomputed when served.
- GDELT attempt 20s < Dialectic HTTP 25s < tool 29s < half the 60s loop budget.
- Cap Gamma parallelism at eight workers.
- Do not implement adjudicate findings SYN-015 through SYN-018 or replace expired market IDs.
- Type hints are mandatory for all new Python functions and state containers.

---

### Task 1: Freshness and cached-observation contract

**Files:**
- Modify: `trading/web/routes/bridge.py`
- Test: `trading/web/test_bridge_endpoints.py`

**Interfaces:**
- Produces: `_freshness_payload(*, state: str, attempted_at: Optional[str], observed_at: Optional[str], served_at: str, age_seconds: Optional[int], ttl_seconds: int) -> dict[str, Any]`
- Produces: cache entries retaining `expires_at`, `observed_monotonic`, `payload`, and the last successful observation.
- Consumes: existing `_news_payload`, `_news_cache`, `NEWS_TTL_SECONDS`, and `NEWS_ERROR_TTL_SECONDS`.

- [ ] **Step 1: Add failing freshness tests**

Add tests that freeze wall and monotonic clocks and assert:

```python
assert live["freshness"] == {
    "state": "live",
    "attempted_at": "2026-08-17T01:00:00+00:00",
    "observed_at": "2026-08-17T01:00:00+00:00",
    "served_at": "2026-08-17T01:00:00+00:00",
    "age_seconds": 0,
    "ttl_seconds": 900,
}
assert cached["freshness"]["state"] == "cached"
assert cached["freshness"]["observed_at"] == live["freshness"]["observed_at"]
assert cached["freshness"]["age_seconds"] == 37
```

Also assert `not_configured` uses `state == "not_applicable"` with null attempt,
observation, and age.

- [ ] **Step 2: Run the focused tests red**

Run: `cd trading && python3 -m pytest web/test_bridge_endpoints.py -k 'freshness or not_configured' -q`

Expected: failures because the nested freshness contract does not exist.

- [ ] **Step 3: Implement the shared payload helper in `bridge.py`**

Keep the helper local to the existing bridge module. Stamp wall time only at an
actual attempt or serve boundary; compute cache age from stored monotonic time.
Extend `_news_payload` to require the freshness object rather than constructing
an ambiguous `fetched_at` stamp for every state. Retain top-level `fetched_at`
and `cache_hit` during this release as compatibility aliases derived from
`freshness.observed_at` and `freshness.state == "cached"`.

- [ ] **Step 4: Run the focused tests green**

Run: `cd trading && python3 -m pytest web/test_bridge_endpoints.py -k 'freshness or not_configured' -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add trading/web/routes/bridge.py trading/web/test_bridge_endpoints.py
git commit -m "fix(trading): make evidence freshness explicit"
```

### Task 2: Bounded GDELT latency and per-query single-flight

**Files:**
- Modify: `trading/tools/data_fetch/gdelt.py`
- Modify: `trading/web/routes/bridge.py`
- Test: `trading/tools/data_fetch/test_gdelt.py`
- Test: `trading/web/test_bridge_endpoints.py`

**Interfaces:**
- Produces: first-429 classification when `retries=0`.
- Produces: `_news_inflight: dict[tuple[str, str], asyncio.Task[dict[str, Any]]]`.
- Produces: dedicated two-worker `_NEWS_EXECUTOR`.
- Consumes: Task 1 freshness/cache entry shape.

- [ ] **Step 1: Add failing provider-budget and encoding tests**

Pin `fetch_articles(..., retries=0)` to one request, immediate
`GdeltRateLimitError` on the first 429, and one encoded `query` parameter for a
value containing `&`, `=`, `#`, spaces, and `sourcelang:eng`.

```python
assert parsed_qs(urlsplit(captured_url).query)["query"] == [raw_query]
assert request_count == 1
```

- [ ] **Step 2: Add failing concurrency tests**

Use `threading.Event` gates in `test_bridge_endpoints.py`:

- block cold query A, prepopulate warm query B, and assert B returns before A;
- start two different cold queries and assert both provider functions enter
  before either gate is released;
- start two identical cold queries and assert the producer counter is one.

- [ ] **Step 3: Run Task 2 tests red**

Run: `cd trading && python3 -m pytest tools/data_fetch/test_gdelt.py web/test_bridge_endpoints.py -k 'encoding or first_rate_limit or single_flight or warm_cache or independent_queries' -q`

Expected: current global lock serializes the tests and the first 429 with zero
retries is not classified correctly.

- [ ] **Step 4: Implement bounded fetch and async single-flight**

In `gdelt.py`, make a first 429 terminal when no retry remains. In `bridge.py`:

- call `gdelt.fetch_articles(..., retries=0)`;
- check cache before executor dispatch;
- use a briefly held state lock only around cache/cooldown/in-flight mutation;
- create one asyncio task per cache key and await it with `asyncio.shield`;
- execute provider calls through a module-level two-worker executor;
- remove the in-flight entry only when the owning task completes;
- allow different keys to overlap;
- derive cached `retry_after_seconds` from the absolute expiry at serve time.

No lock may be held during the network call.

- [ ] **Step 5: Run Task 2 tests green**

Run the exact Task 2 command again. Expected: all selected tests pass without
timing sleeps longer than the event-gated critical section.

- [ ] **Step 6: Commit Task 2**

```bash
git add trading/tools/data_fetch/gdelt.py trading/tools/data_fetch/test_gdelt.py trading/web/routes/bridge.py trading/web/test_bridge_endpoints.py
git commit -m "fix(trading): bound and coalesce focused news checks"
```

### Task 3: Scoped Polymarket observations, partial coverage, and bounded fan-out

**Files:**
- Modify: `trading/tools/data_fetch/polymarket.py`
- Modify: `trading/web/adapters/market.py`
- Modify: `trading/web/routes/bridge.py`
- Test: `trading/tools/data_fetch/test_polymarket.py`
- Test: `trading/web/test_market_quotes.py`
- Test: `trading/web/test_bridge_endpoints.py`

**Interfaces:**
- Produces: maximum eight workers in `fetch_markets(..., parallel=True)`.
- Produces: book-scoped payload statuses `ok|partial|no_data|not_configured|unavailable`.
- Produces: `missing_markets: list[str]` and optional `last_observation`.
- Consumes: Task 1 freshness shape and existing authored-order market resolver.

- [ ] **Step 1: Add failing strict/fan-out tests**

Add tests proving:

```python
with pytest.raises(APIError):
    fetch_markets(["a", "b"], parallel=True, raise_on_error=True)
assert recorded_max_workers == 8  # with 50 inputs
```

Pin malformed response retry behavior to consume the configured attempts and
raise `APIError` containing `invalid data` only after exhaustion.

- [ ] **Step 2: Add failing bridge-state tests**

Cover:

- two concurrent requests for one book call the producer once;
- two configured IDs with one numeric row return `status: partial` and the
  other ID in `missing_markets`;
- zero numeric rows after a normal provider response return live `no_data`;
- invalid booleans, out-of-range values, duplicate slugs, and unconfigured slugs
  fail the bridge contract;
- a provider failure returns `unavailable`, current `markets: []`, stale
  freshness, and a separate prior observation when one exists;
- no prior observation means no `last_observation` key.

- [ ] **Step 3: Run Task 3 tests red**

Run: `cd trading && python3 -m pytest tools/data_fetch/test_polymarket.py web/test_market_quotes.py web/test_bridge_endpoints.py -k 'parallel or partial or missing_markets or last_observation or single_flight or invalid_probability' -q`

Expected: failures for unbounded workers, no single-flight, and absent partial/
stale contracts.

- [ ] **Step 4: Implement bounded workers and observation state**

Use `min(len(slugs), 8)` workers. Retry unexpected invalid data consistently
with transport retries before strict failure. Add a bounded per-book cache and
in-flight map in `bridge.py`; do not cache failures as current data. Preserve
authored order in both `configured_markets` and `missing_markets`.

Catch only the Polymarket provider exceptions at the scoped route boundary.
Programming errors still propagate as HTTP failures.

- [ ] **Step 5: Run Task 3 tests green**

Run the exact Task 3 command again. Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add trading/tools/data_fetch/polymarket.py trading/tools/data_fetch/test_polymarket.py trading/web/adapters/market.py trading/web/test_market_quotes.py trading/web/routes/bridge.py trading/web/test_bridge_endpoints.py
git commit -m "fix(trading): expose partial and stale market coverage"
```

### Task 4: Strict Dialectic consumers and ordered tool budgets

**Files:**
- Modify: `dialectic/llm/tradingdesk_client.py`
- Modify: `dialectic/llm/tools.py`
- Test: `dialectic/tests/test_tools_registry.py`

**Interfaces:**
- Produces: `NEWS_TOOL_HTTP_TIMEOUT_S = 25.0` and `NEWS_TOOL_TIMEOUT_S = 29.0`.
- Consumes: Task 2 news contract and Task 3 Polymarket contract.

- [ ] **Step 1: Add failing news timeout and validation tests**

Capture the timeout passed to `td.service_get`, then assert:

```python
assert timeout == 25.0
assert tool.timeout_s == 29.0
assert timeout < tool.timeout_s < DEFAULT_LOOP_BUDGET_S / 2
```

Add tests rejecting missing/unknown status, non-list articles, invalid freshness,
and focused-query echo mismatch. Add a local 4-character query rejection test
that asserts no HTTP request occurred.

- [ ] **Step 2: Add failing Polymarket shape and shrink tests**

Reject unknown status, malformed freshness, nonnumeric/out-of-range rows, and
status/count inconsistencies. Feed a payload above `THESIS_CHAR_CAP`; assert
`status`, `freshness`, `configured_markets`, and `missing_markets` survive and
`count` equals the visible post-shrink list.

Assert the tool schema declares optional `book_id`.

- [ ] **Step 3: Run Task 4 tests red**

Run: `cd dialectic && python3 -m pytest tests/test_tools_registry.py -k 'news_timeout or query_echo or query_bounds or polymarket_shape or polymarket_shrink or book_id_schema' -q`

Expected: failures for the 10-second default, permissive shapes, and absent
schema property.

- [ ] **Step 4: Implement strict consumer behavior**

Use exact status allowlists and explicit field checks in the two existing tool
executors. Raise `TradingDeskError` for producer contract failures. Raise
`ValueError("query must be between 5 and 500 characters after trimming")`
before I/O for invalid focused queries.

For `rate_limited`, `unavailable`, or stale current checks, include the prior
observation timestamp/age in the exception message while still producing a
failed trace. Protect the epistemic fields during `_shrink`; derive count only
from the final visible `markets` list.

- [ ] **Step 5: Run Task 4 tests green**

Run the exact Task 4 command again. Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add dialectic/llm/tradingdesk_client.py dialectic/llm/tools.py dialectic/tests/test_tools_registry.py
git commit -m "fix(dialectic): preserve evidence age through the tool trace"
```

### Task 5: Relay and legacy compatibility

**Files:**
- Modify: `dialectic/api/trading_relay.py`
- Modify: `trading/web/adapters/market.py`
- Test: `dialectic/tests/test_trading_relay_endpoint.py`
- Test: `trading/web/test_market_quotes.py`

**Interfaces:**
- Consumes: Task 3 scoped structured response.
- Preserves: current-only list output from the Bench and best-effort global desk output.

- [ ] **Step 1: Add failing relay-shape tests**

Mock a legacy list and a dict without `markets`; assert both become HTTP 502 with
`unexpected shape`. Mock `unavailable` with a historical observation; assert the
Bench returns an empty list rather than stale rows.

- [ ] **Step 2: Add failing legacy global tests**

Pin all configured global IDs to remain present, including
`{"slug": id, "probability": None}`, and assert the legacy adapter passes its
15-second budget without strict failure mode.

- [ ] **Step 3: Run Task 5 tests red**

Run: `cd dialectic && python3 -m pytest tests/test_trading_relay_endpoint.py -k polymarket -q`

Run: `cd trading && python3 -m pytest web/test_market_quotes.py -k polymarket -q`

Expected: malformed relay coverage and legacy null membership fail.

- [ ] **Step 4: Implement the compatibility fences**

Keep strict/scoped behavior on the service bridge. Route the global browser read
through the existing best-effort client defaults and emit null rows for missing
probabilities. In the Bench relay, unwrap `markets` only for `ok`, `partial`, and
live/cached `no_data`; return no rows for unavailable/stale current state.

- [ ] **Step 5: Run Task 5 tests green**

Run both Task 5 commands again. Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add dialectic/api/trading_relay.py dialectic/tests/test_trading_relay_endpoint.py trading/web/adapters/market.py trading/web/test_market_quotes.py
git commit -m "fix(dialectic): fence stale evidence from browser lists"
```

### Task 6: Market verification gate

**Files:**
- Modify: `JOURNAL.md`

**Interfaces:**
- Consumes: Tasks 1 through 5.
- Produces: one clean, reviewable market-hardening commit series.

- [ ] **Step 1: Run focused suites**

```bash
cd trading && python3 -m pytest \
  tools/data_fetch/test_gdelt.py \
  tools/data_fetch/test_polymarket.py \
  web/test_bridge_endpoints.py \
  web/test_market_quotes.py \
  web/test_market_polymarket_id.py -q
cd ../dialectic && python3 -m pytest \
  tests/test_tools_registry.py \
  tests/test_tool_loop.py \
  tests/test_trading_relay_endpoint.py -q
```

- [ ] **Step 2: Run both full backend suites**

```bash
WORKTREE_ROOT=$(git rev-parse --show-toplevel)
cd "$WORKTREE_ROOT/trading" && python3 -m pytest -q
cd "$WORKTREE_ROOT/dialectic" && python3 -m pytest -q
```

- [ ] **Step 3: Inspect mutations and diff**

Prove at least these mutations fail their targeted tests: remove query echo
validation, relabel `partial` as `ok`, restamp cached `observed_at`, remove the
worker cap, and unwrap `last_observation` into the Bench list. Restore each
mutation and rerun its test. Run `git diff --check` and inspect `git status`.

- [ ] **Step 4: Record the gate**

Append one `JOURNAL.md` line with exact focused/full counts and any unavailable
live provider proof. Do not edit runtime snapshots.

- [ ] **Step 5: Commit the gate record**

```bash
git add JOURNAL.md
git commit -m "docs(dialectic): record evidence freshness hardening gate"
```
