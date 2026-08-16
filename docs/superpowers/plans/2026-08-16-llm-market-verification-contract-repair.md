# LLM Market Verification Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Claude's market-verification tools return reachable, book-scoped evidence with explicit source state instead of healthy-looking empty arrays.

**Architecture:** tradingDesk remains the sole market-data producer. Its market adapter canonicalizes authored Polymarket IDs, while service-authenticated bridge routes expose book-scoped Polymarket evidence and status-rich GDELT results. Dialectic preserves browser list shapes, but its LLM executors consume the structured bridge contracts and turn actual provider degradation into failed tool calls.

**Tech Stack:** Python 3.12, FastAPI, httpx, pytest, existing GDELT Doc 2.0 client, existing Polymarket Gamma client

## Global Constraints

- No new provider, credential, database migration, config layer, or frontend response shape.
- `feeds[].market` is canonical; legacy `feeds[].slug` remains readable.
- Existing `GET /api/market/polymarket` remains list-shaped.
- Existing news `articles` and optional `note` fields remain available; new status fields are additive.
- Focused GDELT query length is 5–500 trimmed characters.
- News cache holds at most 64 query-specific entries and one process-wide GDELT cooldown.
- No service restart, frontend flip, migration, or live-data mutation during implementation.
- Use type hints on every new or changed Python function.
- Preserve unrelated `JOURNAL.md`, snapshot, image, and cache-file changes in the primary checkout.

---

### Task 1: Canonical Polymarket market IDs

**Files:**
- Modify: `trading/web/adapters/market.py`
- Test: `trading/web/test_market_quotes.py`

**Interfaces:**
- Consumes and retains concurrent work: `_polymarket_feed_id(feed: dict) -> str`
- Produces: `polymarket_markets_from_book(cfg: dict[str, Any]) -> list[str]`
- Produces: `fetch_polymarket_probs(market_ids: Optional[list[str]] = None) -> list[dict[str, Any]]`
- Preserves: `_collect_symbols_from_books() -> tuple[set[str], list[str]]`

- [ ] **Step 1: Write failing canonical-ID tests**

Add tests that prove `market` wins, `slug` remains supported, duplicates are
removed in authored order, and the checked-in books expose four markets:

```python
class TestPolymarketCollection:
    def test_market_is_canonical_and_slug_is_legacy(self):
        cfg = {"nodes": [{"feeds": [
            {"source": "polymarket", "market": "canonical", "slug": "legacy"},
            {"source": "polymarket", "slug": "legacy-only"},
            {"source": "polymarket", "market": "canonical"},
        ]}]}
        assert market.polymarket_markets_from_book(cfg) == [
            "canonical", "legacy-only",
        ]

    def test_checked_in_books_expose_four_markets(self):
        _symbols, market_ids = market._collect_symbols_from_books()
        assert market_ids == [
            "us-iran-april-30",
            "us-tariff-rate-china-march-31",
            "trump-visit-china-by-june-30",
            "us-recession-by-end-of-2026",
        ]
```

Add a fetch test where `fetch_markets` returns one float and one `None`; only the
float result may be emitted. Add a test proving a raised `RuntimeError` propagates
rather than becoming `[]`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd trading
venv/bin/python -m pytest web/test_market_quotes.py -q
```

Expected: new tests fail because `polymarket_markets_from_book` does not exist
and `None` results are retained. The concurrent primary-checkout repair already
makes checked-in IDs visible and propagates exceptions; preserve those changes.

- [ ] **Step 3: Implement canonical collection and loud failure**

In `web/adapters/market.py`, retain the concurrent `_polymarket_feed_id` repair
already present in the primary checkout and add the reusable book collector:

```python
def polymarket_markets_from_book(cfg: dict[str, Any]) -> list[str]:
    market_ids: list[str] = []
    for node in cfg.get("nodes", []) or []:
        for feed in node.get("feeds", []) or []:
            if not isinstance(feed, dict):
                continue
            market_id = _polymarket_feed_id(feed)
            if market_id and market_id not in market_ids:
                market_ids.append(market_id)
    return market_ids
```

Use this helper from the global collector and watchlist alongside the existing
feed-ID helper. Change `fetch_polymarket_probs` to accept optional explicit IDs,
call the existing fetcher without a catch-all, and emit only numeric
probabilities:

```python
def fetch_polymarket_probs(
    market_ids: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    if market_ids is None:
        _, market_ids = _collect_symbols_from_books()
    if not market_ids:
        return []
    probabilities = polymarket_mod.fetch_markets(market_ids)
    return [
        {"slug": market_id, "probability": probability}
        for market_id, probability in probabilities.items()
        if isinstance(probability, (int, float))
    ]
```

Import `Optional` from `typing`. Do not change quote behavior.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Task 1 command again. Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add trading/web/adapters/market.py trading/web/test_market_quotes.py
git commit -m "fix(trading): read the Polymarket IDs books actually author"
```

---

### Task 2: Book-scoped Polymarket bridge and Bench relay

**Files:**
- Modify: `trading/web/routes/bridge.py`
- Test: `trading/web/test_bridge_endpoints.py`
- Modify: `dialectic/api/trading_relay.py`
- Test: `dialectic/tests/test_trading_relay_endpoint.py`

**Interfaces:**
- Consumes: `polymarket_markets_from_book(cfg) -> list[str]`
- Consumes: `fetch_polymarket_probs(market_ids) -> list[dict[str, Any]]`
- Produces: `GET /api/bridge/polymarket/{thesis_id}` structured response
- Preserves: `GET /rooms/{room_id}/trading/polymarket` list response

- [ ] **Step 1: Write failing bridge tests**

In `trading/web/test_bridge_endpoints.py`, add tests for:

```python
def test_polymarket_not_configured(client):
    response = client.get(
        "/api/bridge/polymarket/china-property-cascade-graph",
        headers=svc_headers(),
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "not_configured",
        "configured_markets": [],
        "markets": [],
    }
```

Use `monkeypatch` for `fetch_polymarket_probs` to prove a configured book returns
`no_data` for `[]`, `ok` for a probability, 404 for an unknown book, and 500 for
an actual adapter exception. Assert service-token auth is required.

- [ ] **Step 2: Verify tradingDesk bridge tests RED**

```bash
cd trading
venv/bin/python -m pytest web/test_bridge_endpoints.py -q
```

Expected: new `/api/bridge/polymarket/{thesis_id}` tests fail with 404 or the SPA
HTML fallback.

- [ ] **Step 3: Implement the book-scoped route**

Add a route beside the news bridge. Resolve `_book_path`, parse the same JSON with
the same 404/500 behavior, collect IDs, and call the adapter in `asyncio.to_thread`:

```python
@router.get("/polymarket/{thesis_id}")
async def get_thesis_polymarket(
    thesis_id: str,
    _svc: None = Depends(require_service_token),
) -> JSONResponse:
    path = _book_path(thesis_id)
    if path is None:
        raise HTTPException(404, detail=f"No book for thesis {thesis_id!r}")
    try:
        book = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, detail=f"Book {thesis_id!r} is unreadable: {exc}")
    from web.adapters import market as market_adapter
    market_ids = market_adapter.polymarket_markets_from_book(book)
    if not market_ids:
        payload = {"status": "not_configured", "configured_markets": [], "markets": []}
    else:
        markets = await asyncio.to_thread(
            market_adapter.fetch_polymarket_probs, market_ids,
        )
        payload = {
            "status": "ok" if markets else "no_data",
            "configured_markets": market_ids,
            "markets": markets,
        }
    return JSONResponse(content=payload, media_type="application/json")
```

- [ ] **Step 4: Verify tradingDesk bridge tests GREEN**

Run the Task 2 tradingDesk command again. Expected: all pass.

- [ ] **Step 5: Write the failing Dialectic relay test**

Replace `test_polymarket_proxies` so `service_get` returns a structured body,
the response remains its `markets` list, and the resolved book is in the path:

```python
def test_polymarket_is_book_scoped_but_remains_list_shaped(monkeypatch):
    service_get = AsyncMock(return_value={
        "status": "ok",
        "configured_markets": ["m"],
        "markets": [{"slug": "m", "probability": 0.4}],
    })
    response = _call(
        _make_db(), monkeypatch, "polymarket",
        td_mocks={"service_get": service_get},
    )
    assert response.json() == [{"slug": "m", "probability": 0.4}]
    service_get.assert_awaited_once_with(
        f"/api/bridge/polymarket/{BOOK_ID}",
    )
```

- [ ] **Step 6: Verify the relay test RED**

```bash
cd dialectic
/usr/bin/python3 -m pytest tests/test_trading_relay_endpoint.py -q
```

Expected: the old relay calls the JWT/global endpoint and returns the structured
dict rather than the list.

- [ ] **Step 7: Implement the scoped relay and verify GREEN**

Capture `book_id = await _resolve_room_book(...)`, call
`td.service_get(f"/api/bridge/polymarket/{book_id}")`, require a dict with a list
`markets`, and return that list. Raise the existing `_bad_gateway` for a malformed
shape or `TradingDeskError`. Run the Task 2 Dialectic command again.

- [ ] **Step 8: Commit Task 2**

```bash
git add trading/web/routes/bridge.py trading/web/test_bridge_endpoints.py \
  dialectic/api/trading_relay.py dialectic/tests/test_trading_relay_endpoint.py
git commit -m "fix(dialectic): scope Polymarket evidence to the active book"
```

---

### Task 3: Structured and targeted GDELT news state

**Files:**
- Modify: `trading/web/routes/bridge.py`
- Test: `trading/web/test_bridge_endpoints.py`

**Interfaces:**
- Produces: `_fetch_news_sync(thesis_id: str, book: dict[str, Any], query_override: Optional[str] = None) -> tuple[dict[str, Any], float]`
- Produces: query-specific `_news_cache[(thesis_id, query)]`
- Produces: process-wide `_news_rate_limit_streak: int` and `_news_rate_limit_until: float`
- Extends: `GET /api/bridge/news/{thesis_id}?query=...`

- [ ] **Step 1: Replace ambiguous news tests with failing status tests**

Update the fixture to clear the cache and reset the integer cooldown globals.
Update existing assertions and add tests for:

```python
assert populated["status"] == "ok"
assert empty["status"] == "no_matches"
assert unconfigured["status"] == "not_configured"
assert rate_limited["status"] == "rate_limited"
assert unavailable["status"] == "unavailable"
```

Every body must contain `source == "gdelt"`, `query`, `articles`, `fetched_at`,
and `cache_hit`. `query` is `None` only for `not_configured`.

Add a test issuing `?query=China%20new%20yuan%20loans`; assert the exact string
reaches `gdelt.fetch_articles` and is returned. Add validation tests for trimmed
lengths below 5 and above 500 (422). Add cache tests proving default and targeted
queries are distinct, cached timestamps are stable, `cache_hit` flips true, and
inserting 65 query keys leaves 64.

Add a global cooldown test: after one query raises `GdeltRateLimitError`, a
different book/query returns `rate_limited` without calling the fetcher. Simulate
expiry by setting `_news_rate_limit_until = 0.0`, return a successful empty fetch,
and assert `_news_rate_limit_streak == 0`.

- [ ] **Step 2: Run bridge tests and verify RED**

Run the Task 2 tradingDesk bridge command. Expected failures: missing status and
provenance fields, no query parameter, old cache key, and per-book cooldown.

- [ ] **Step 3: Implement structured payloads and cache helpers**

Use `datetime.now(timezone.utc).isoformat()` for `fetched_at`. Add local helpers:

```python
def _news_payload(
    status: str,
    query: Optional[str],
    *,
    articles: Optional[list[dict[str, Any]]] = None,
    note: Optional[str] = None,
    retry_after_seconds: Optional[int] = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "source": "gdelt",
        "query": query,
        "articles": articles or [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "cache_hit": False,
    }
    if note is not None:
        payload["note"] = note
    if retry_after_seconds is not None:
        payload["retry_after_seconds"] = retry_after_seconds
    return payload
```

Change `_fetch_news_sync` to use the override when supplied, return the five
statuses, set the process-wide exponential cooldown on 429, and reset it after a
successful GDELT response.

Store cache entries by `(thesis_id, query or "")`. Before insertion, remove
expired entries; if 64 remain and the new key is absent, evict
`min(_news_cache, key=lambda key: _news_cache[key][0])`. Return a shallow payload
copy with `cache_hit = True` on hits. During a live cooldown, return a fresh
`rate_limited` payload with the remaining seconds without calling GDELT.

Declare the route query as:

```python
query: Optional[str] = Query(default=None, min_length=5, max_length=500)
```

Trim it before use and import `Query`, `datetime`, and `timezone`.

- [ ] **Step 4: Run bridge tests and verify GREEN**

Run the Task 2 tradingDesk bridge command again. Expected: all pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add trading/web/routes/bridge.py trading/web/test_bridge_endpoints.py
git commit -m "fix(trading): preserve why a news lookup has no articles"
```

---

### Task 4: Dialectic tool health and focused verification queries

**Files:**
- Modify: `dialectic/llm/tradingdesk_client.py`
- Modify: `dialectic/llm/tools.py`
- Test: `dialectic/tests/test_tools_registry.py`

**Interfaces:**
- Extends: `service_get(path: str, *, params: Optional[dict] = None, timeout: Optional[float] = None) -> Any`
- Changes: `get_polymarket_odds` consumes book-scoped structured bridge data
- Changes: `get_thesis_news` accepts optional `query` and raises on `rate_limited` or `unavailable`

- [ ] **Step 1: Write failing client and tool tests**

Add a service-client test that calls `service_get(..., params={"query": "new yuan loans"})`
and asserts the request URL contains the query parameter without losing the
service token.

Replace the Polymarket tool test coverage with:

```python
assert request.url.path == "/api/bridge/polymarket/iran-hormuz-graph"
return json_response({
    "status": "ok",
    "configured_markets": ["m"],
    "markets": [{"slug": "m", "probability": 0.42}],
})
```

Assert `not_configured` remains a successful structured result. Assert an HTTP
500 still raises `TradingDeskError`.

For news, assert optional `query` is forwarded, `no_matches` remains structured,
and both `rate_limited` and `unavailable` raise `TradingDeskError` containing the
status, exact query, and retry value when present. Update the old
`test_note_only_degradation_is_not_an_error`; degradation is now deliberately an
error so the trace cannot say `ok: true`.

- [ ] **Step 2: Run tool tests and verify RED**

```bash
cd dialectic
/usr/bin/python3 -m pytest tests/test_tools_registry.py -q
```

Expected: query params are unsupported, Polymarket still uses the global JWT
endpoint, and news degradation returns normally.

- [ ] **Step 3: Extend the service client**

Add `params: Optional[dict] = None` and pass `params=params` to `client.get`.
Keep all existing authentication, timeout, JSON, and error behavior.

- [ ] **Step 4: Implement book-scoped Polymarket tool behavior**

Resolve `book_id`, call the service bridge, require a dict with list `markets`,
and return the structured result plus `book_id` and `count`. Do not replace
`not_configured` or `no_data` with the old ambiguous note.

- [ ] **Step 5: Implement focused news and failure semantics**

Read `query = str(args.get("query") or "").strip() or None`, pass it through
`service_get(params={"query": query} if query else None, timeout=...)`, and raise:

```python
if news.get("status") in {"rate_limited", "unavailable"}:
    retry = news.get("retry_after_seconds")
    suffix = f"; retry after {retry}s" if retry is not None else ""
    raise td.TradingDeskError(
        f"GDELT {news['status']} for query {news.get('query')!r}{suffix}"
    )
```

Add `query` to the tool input schema and update its description with the exact
`no_matches` rule. Keep the existing result shrinking, `book_id`, and `count`.

- [ ] **Step 6: Run tool tests and verify GREEN**

Run the Task 4 tool command again. Expected: all pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add dialectic/llm/tradingdesk_client.py dialectic/llm/tools.py \
  dialectic/tests/test_tools_registry.py
git commit -m "fix(dialectic): make empty evidence explain itself"
```

---

### Task 5: Integrated verification and handoff

**Files:**
- Modify: `JOURNAL.md`
- Verify only: all implementation files from Tasks 1–4

**Interfaces:**
- Consumes: all repaired contracts
- Produces: verified implementation branch and exact activation boundary

- [ ] **Step 1: Run focused tradingDesk verification**

```bash
cd trading
venv/bin/python -m pytest web/test_market_quotes.py web/test_bridge_endpoints.py -q
```

Expected: all pass.

- [ ] **Step 2: Run focused Dialectic verification**

```bash
cd dialectic
/usr/bin/python3 -m pytest tests/test_tools_registry.py \
  tests/test_trading_relay_endpoint.py -q
```

Expected: all pass.

- [ ] **Step 3: Run both full backend suites**

```bash
cd trading && venv/bin/python -m pytest -q
cd dialectic && /usr/bin/python3 -m pytest -q
```

If a known load-sensitive test times out, rerun that exact test once with system
load recorded; never report a clean full-suite number unless the full command is
clean.

- [ ] **Step 4: Run static and diff checks**

```bash
git diff --check
cd trading && venv/bin/python -m compileall -q web
cd dialectic && /usr/bin/python3 -m compileall -q llm api
```

Expected: no output and zero exit status.

- [ ] **Step 5: Run read-only contract probes without activating code**

Import the worktree modules directly to prove the checked-in books yield four
market IDs. Do not curl the live service expecting the new endpoints because
systemd still runs the primary checkout and has not been restarted.

- [ ] **Step 6: Update the journal and commit verification evidence**

Append one line to `JOURNAL.md` recording the repaired contracts and exact suite
counts. Commit only the journal and any implementation changes still intentionally
uncommitted:

```bash
git add JOURNAL.md
git commit -m "docs(dialectic): record honest market verification gate"
```

- [ ] **Step 7: Stop at the activation boundary**

Report branch, commits, focused/full test evidence, unchanged production PIDs,
and the exact remaining activation action: merge/cherry-pick into `master`, then
separately authorize tradingDesk restart followed by Dialectic restart. No
frontend flip or migration is required.
