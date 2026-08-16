# Dialectic Article Fetch Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore reading and saving for public article URLs blocked by publisher HTTP 403 defenses, while stopping Wire from retrying unreadable headlines every 15 minutes.

**Architecture:** Keep direct Defuddle extraction primary. Move extraction into a testable Node module that performs one tracking-sanitized Jina Reader fallback only after direct HTTP 403, then preserve the existing sidecar JSON contract. Add a Wire-only in-memory cooldown and bounded feed scan without changing interactive retries or the two-call LLM scoring ceiling.

**Tech Stack:** Node 22 ESM, Node built-in test runner, Defuddle 0.19, linkedom, Python 3.12, pytest, FastAPI/asyncpg application contracts.

## Global Constraints

- Direct publisher extraction remains the primary path.
- Reader fallback runs only after direct HTTP 403; never after 401, 404, 451, or arbitrary non-2xx responses.
- Strip `email` and case-insensitive `utm_*` query parameters before disclosing the public target URL to Jina; preserve all other query parameters.
- Direct and fallback requests share the existing 15-second total abort budget.
- Preserve the existing `{title, author, description, site, published, word_count, url, content}` response shape and return the caller's original URL.
- Do not accept pasted or model-authored article text as library provenance.
- Wire cooldown is six hours in process memory, scans at most six fresh headlines, and scores at most two readable articles per room per run.
- No migration, API key, environment variable, compatibility shim, logging framework, or runtime service is added.
- Do not restart `defuddle.service` or `dialectic.service` during implementation; production activation remains separate.
- Stage and commit only the exact task files; preserve the existing dirty journal, trading snapshots, image, and acceptance cache.

---

## File map

- Create `dialectic/defuddle_service/extractor.mjs`: public-URL validation, direct Defuddle extraction, 403-only Reader fallback, tracking sanitization, Reader parsing, and `HttpError`.
- Create `dialectic/defuddle_service/extractor.test.mjs`: deterministic Node tests with an injected fetch function.
- Modify `dialectic/defuddle_service/server.mjs`: retain only the loopback HTTP adapter and delegate extraction to `extractor.mjs`.
- Modify `dialectic/defuddle_service/package.json`: add the Node built-in test command.
- Modify `dialectic/llm/wire.py`: add the bounded cooldown and readable-article budget.
- Modify `dialectic/tests/test_wire.py`: mutation-sensitive cooldown, scan, and score-budget contracts.
- Modify `dialectic/CLAUDE.md`: amend beside with the new direct/fallback and Wire retry contract.
- Modify `JOURNAL.md`: append the implemented decision and verification result without staging unrelated existing journal changes.

### Task 1: Direct-first extractor with a 403-only Reader fallback

**Files:**
- Create: `dialectic/defuddle_service/extractor.test.mjs`
- Create: `dialectic/defuddle_service/extractor.mjs`
- Modify: `dialectic/defuddle_service/server.mjs:14-136`
- Modify: `dialectic/defuddle_service/package.json:8-13`

**Interfaces:**
- Produces: `export class HttpError extends Error`, carrying integer `.status`.
- Produces: `export async function extract(url, fetchImpl = fetch)`, returning the existing article object or throwing `HttpError`.
- Consumes: global `fetch`, `AbortSignal.timeout`, `URL`, `Defuddle`, and `parseHTML`.
- Preserves: `POST /extract {url}` and all Python `defuddle_client.extract_article()` behavior.

- [ ] **Step 1: Add the failing Node contract tests**

Create `extractor.test.mjs` using `node:test`, `node:assert/strict`, and an injected sequence fetch:

```js
import test from 'node:test';
import assert from 'node:assert/strict';

import { extract, HttpError } from './extractor.mjs';

function sequenceFetch(...responses) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url: String(url), options });
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { calls, fetchImpl };
}

function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

function readerResponse(body, status = 200, contentType = 'text/plain; charset=utf-8') {
  return new Response(body, {
    status,
    headers: { 'content-type': contentType },
  });
}

const READER_ARTICLE = `Title: Source title
URL Source: https://publisher.example/story
Published Time: 2026-08-15T12:00:00Z

Markdown Content:
# Source title

This is the source article body with enough words to prove normalization.`;
```

Add tests with these exact behavioral assertions:

```js
test('direct success never calls Reader', async () => {
  const fetch = sequenceFetch(htmlResponse(
    '<html><head><title>Direct title</title></head><body><main><p>Direct source body.</p></main></body></html>'
  ));
  const article = await extract('https://publisher.example/direct', fetch.fetchImpl);
  assert.equal(fetch.calls.length, 1);
  assert.equal(article.url, 'https://publisher.example/direct');
  assert.match(article.content, /Direct source body/);
});

test('direct 403 uses Reader with sanitized tracking and preserves caller URL', async () => {
  const original = 'https://publisher.example/story?email=secret&utm_source=mail&UTM_medium=email&article=kept';
  const fetch = sequenceFetch(htmlResponse('blocked', 403), readerResponse(READER_ARTICLE));
  const article = await extract(original, fetch.fetchImpl);
  assert.equal(fetch.calls.length, 2);
  assert.equal(fetch.calls[1].url, 'https://r.jina.ai/https://publisher.example/story?article=kept');
  assert.equal(fetch.calls[0].options.signal, fetch.calls[1].options.signal);
  assert.equal(article.url, original);
  assert.equal(article.title, 'Source title');
  assert.equal(article.published, '2026-08-15T12:00:00Z');
  assert.equal(article.site, 'publisher.example');
  assert.match(article.content, /source article body/);
  assert.ok(article.word_count > 0);
});

for (const status of [404, 451]) {
  test(`direct ${status} never invokes Reader`, async () => {
    const fetch = sequenceFetch(htmlResponse('denied', status));
    await assert.rejects(
      extract('https://publisher.example/story', fetch.fetchImpl),
      (error) => error instanceof HttpError && error.status === 502
        && error.message === `upstream returned HTTP ${status}`,
    );
    assert.equal(fetch.calls.length, 1);
  });
}

test('Reader failure retains the original upstream 403', async () => {
  const fetch = sequenceFetch(htmlResponse('blocked', 403), readerResponse('limited', 429));
  await assert.rejects(
    extract('https://publisher.example/story', fetch.fetchImpl),
    /upstream returned HTTP 403; reader fallback failed: reader returned HTTP 429/,
  );
});

test('Reader timeout retains the original upstream 403', async () => {
  const timeout = new DOMException('timed out', 'TimeoutError');
  const fetch = sequenceFetch(htmlResponse('blocked', 403), timeout);
  await assert.rejects(
    extract('https://publisher.example/story', fetch.fetchImpl),
    /upstream returned HTTP 403; reader fallback failed: reader fetch timed out/,
  );
});

test('Reader rejects wrong content type and an empty Markdown body', async (t) => {
  await t.test('wrong content type', async () => {
    const fetch = sequenceFetch(htmlResponse('blocked', 403), readerResponse('{}', 200, 'application/json'));
    await assert.rejects(extract('https://publisher.example/story', fetch.fetchImpl), /reader returned application\/json/);
  });
  await t.test('empty body', async () => {
    const fetch = sequenceFetch(htmlResponse('blocked', 403), readerResponse('Title: Empty\n\nMarkdown Content:\n   '));
    await assert.rejects(extract('https://publisher.example/story', fetch.fetchImpl), /reader returned no article content/);
  });
});

test('private targets reach neither direct fetch nor Reader', async () => {
  const fetch = sequenceFetch();
  await assert.rejects(
    extract('http://127.0.0.1/private', fetch.fetchImpl),
    (error) => error instanceof HttpError && error.status === 400,
  );
  assert.equal(fetch.calls.length, 0);
});
```

Add `"test": "node --test extractor.test.mjs"` to `package.json`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd dialectic/defuddle_service && npm test
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `extractor.mjs`. This proves the test is red because the production extraction module does not exist.

- [ ] **Step 3: Implement the minimal extractor module**

Move `HttpError`, `isPrivateHost`, the Safari user agent, the 15-second timeout, direct fetch, redirect validation, `parseHTML`, and Defuddle normalization from `server.mjs` into `extractor.mjs`.

Use one signal for both fetches and inject only the fetch function:

```js
const READER_BASE_URL = 'https://r.jina.ai/';
const FETCH_TIMEOUT_MS = 15000;

function sanitizeForReader(parsed) {
  const target = new URL(parsed.href);
  for (const key of [...target.searchParams.keys()]) {
    const normalized = key.toLowerCase();
    if (normalized === 'email' || normalized.startsWith('utm_')) {
      target.searchParams.delete(key);
    }
  }
  return target.href;
}

function parseReaderArticle(text, originalUrl, parsed) {
  const match = text.match(/(?:^|\r?\n)Markdown Content:\s*\r?\n([\s\S]*)$/);
  const content = match?.[1]?.trim() || '';
  if (!content) throw new Error('reader returned no article content');
  const header = text.slice(0, match.index);
  const field = (name) => header.match(new RegExp(`^${name}:\\s*(.+)$`, 'mi'))?.[1]?.trim() || null;
  return {
    title: field('Title'),
    author: null,
    description: null,
    site: parsed.hostname,
    published: field('Published Time'),
    word_count: content.split(/\s+/u).filter(Boolean).length,
    url: originalUrl,
    content,
  };
}
```

When direct response status is 403, call `${READER_BASE_URL}${sanitizeForReader(parsed)}` with `accept: text/plain`, the same signal, and no credentials. Require `response.ok` and `content-type` beginning with `text/plain`. Wrap every fallback error as:

```js
throw new HttpError(
  502,
  `upstream returned HTTP 403; reader fallback failed: ${detail}`,
);
```

For direct statuses other than 403, keep the existing `upstream returned HTTP <status>` error exactly.

Reduce `server.mjs` to import `{ extract, HttpError }` from `./extractor.mjs`; retain request-body limits, `/health`, `/extract`, JSON serialization, error-to-status mapping, and loopback listener unchanged.

- [ ] **Step 4: Run the Node tests and verify GREEN**

Run:

```bash
cd dialectic/defuddle_service && npm test
```

Expected: all extractor tests PASS with zero warnings.

- [ ] **Step 5: Run the existing Python consumer contracts**

Run:

```bash
cd dialectic && python3 -m pytest tests/test_tools_registry.py tests/test_reading_relay_endpoint.py tests/test_claim_check.py -q
```

Expected: PASS. The Python client and tool/save response contracts remain unchanged.

- [ ] **Step 6: Commit only the extractor slice**

```bash
git add dialectic/defuddle_service/extractor.mjs \
  dialectic/defuddle_service/extractor.test.mjs \
  dialectic/defuddle_service/server.mjs \
  dialectic/defuddle_service/package.json
git diff --cached --check
git commit -m "fix(dialectic): readers get through publisher walls -- direct first, source intact"
```

### Task 2: Wire cooldown and bounded scan-past behavior

**Files:**
- Modify: `dialectic/tests/test_wire.py:63-132,268-320`
- Modify: `dialectic/llm/wire.py:43-72,283-305`

**Interfaces:**
- Produces: module state `_fetch_cooldowns: dict[str, float]` keyed by exact feed URL.
- Produces: `_in_fetch_cooldown(url: str) -> bool` and `_cool_fetch(url: str) -> None`.
- Preserves: `wire_watch(ctx) -> dict`, scheduler registration, daily interjection cap, quiet hours, room toggle, and at most two relevance calls.

- [ ] **Step 1: Add failing Wire tests**

Add an autouse fixture that clears cooldown state when the new map exists, without changing current production behavior during the RED run:

```python
@pytest.fixture(autouse=True)
def clear_fetch_cooldowns():
    cooldowns = getattr(wire, "_fetch_cooldowns", None)
    if cooldowns is not None:
        cooldowns.clear()
    yield
    if cooldowns is not None:
        cooldowns.clear()
```

Replace the current one-item extraction-failure expectation and add these contracts:

```python
async def test_extract_failure_cools_url_and_scans_past_it(
    self, mocks, monkeypatch, interjection_calls,
):
    from llm.defuddle_client import DefuddleError

    failed = "https://reuters.com/s1"
    mocks.extract_errors[failed] = DefuddleError("upstream 403")
    db = make_wire_db(rooms=[make_room_row()])
    ctx = _ctx(db)[0]
    clock = {"now": 100.0}
    monkeypatch.setattr(wire.time, "monotonic", lambda: clock["now"])

    first = await wire.wire_watch(ctx)
    assert mocks.extract_calls == [
        "https://reuters.com/s1",
        "https://reuters.com/s2",
        "https://reuters.com/s3",
    ]
    assert [item["url"] for item in mocks.saved] == [
        "https://reuters.com/s2",
        "https://reuters.com/s3",
    ]
    assert {item["reason"] for item in first[str(ROOM_ID)]["skipped"]} == {"extract_failed"}

    mocks.extract_calls.clear()
    mocks.saved.clear()
    second = await wire.wire_watch(ctx)
    assert mocks.extract_calls == [
        "https://reuters.com/s2",
        "https://reuters.com/s3",
    ]
    assert {item["reason"] for item in second[str(ROOM_ID)]["skipped"]} == {"fetch_cooldown"}

    mocks.extract_errors.clear()
    mocks.extract_calls.clear()
    clock["now"] += 6 * 60 * 60 + 1
    third = await wire.wire_watch(ctx)
    assert mocks.extract_calls == [
        "https://reuters.com/s1",
        "https://reuters.com/s2",
    ]
    assert all(
        item["reason"] != "fetch_cooldown"
        for item in third[str(ROOM_ID)]["skipped"]
    )

async def test_scan_stops_after_six_unreadable_entries(self, mocks, interjection_calls):
    from llm.defuddle_client import DefuddleError

    mocks.articles = make_articles(8)
    mocks.extract_errors = {
        article["url"]: DefuddleError("blocked") for article in mocks.articles
    }
    db = make_wire_db(rooms=[make_room_row()])
    await wire.wire_watch(_ctx(db)[0])
    assert mocks.extract_calls == [article["url"] for article in mocks.articles[:6]]
    assert mocks.score_calls == []
    assert mocks.saved == []

async def test_below_threshold_articles_are_not_cooled(self, mocks, interjection_calls):
    mocks.score = {"score": wire.WIRE_THRESHOLD - 0.1, "why": "peripheral"}
    db = make_wire_db(rooms=[make_room_row()])
    ctx = _ctx(db)[0]
    await wire.wire_watch(ctx)
    assert wire._fetch_cooldowns == {}
    mocks.extract_calls.clear()
    second = await wire.wire_watch(ctx)
    assert mocks.extract_calls == ["https://reuters.com/s1", "https://reuters.com/s2"]
    assert all(
        item["reason"] == "below_threshold"
        for item in second[str(ROOM_ID)]["skipped"]
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd dialectic && python3 -m pytest \
  tests/test_wire.py::TestWireWatch::test_extract_failure_cools_url_and_scans_past_it \
  tests/test_wire.py::TestWireWatch::test_scan_stops_after_six_unreadable_entries \
  tests/test_wire.py::TestWireWatch::test_below_threshold_articles_are_not_cooled -q
```

Expected: FAIL because current Wire slices the first two headlines, has no cooldown map, and does not scan past extraction failures.

- [ ] **Step 3: Implement cooldown and readable-article budgeting**

Import `time` and add:

```python
WIRE_FEED_SCAN_CAP = 6
WIRE_FETCH_COOLDOWN_SECONDS = 6 * 60 * 60
_fetch_cooldowns: dict[str, float] = {}


def _in_fetch_cooldown(url: str) -> bool:
    deadline = _fetch_cooldowns.get(url)
    if deadline is None:
        return False
    if deadline <= time.monotonic():
        del _fetch_cooldowns[url]
        return False
    return True


def _cool_fetch(url: str) -> None:
    _fetch_cooldowns[url] = time.monotonic() + WIRE_FETCH_COOLDOWN_SECONDS
```

Replace `for headline in fresh[:WIRE_PER_ROOM_CAP]` with a scan over `fresh[:WIRE_FEED_SCAN_CAP]` and a `readable_count` checked at the top of the loop. For each URL:

1. Append `{"url": url, "reason": "fetch_cooldown"}` and continue when cooled.
2. On `DefuddleError`, call `_cool_fetch(url)`, append `extract_failed`, and continue.
3. On `is_thin(article)`, call `_cool_fetch(url)`, append `thin_content`, and continue.
4. Increment `readable_count` immediately before `_score`.
5. Stop before processing another headline once `readable_count == WIRE_PER_ROOM_CAP`.

Update the module docstring guardrail: `WIRE_PER_ROOM_CAP` caps readable/scored articles; the feed scan cap bounds extraction work; extraction failures cool for six hours.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the same three-node command from Step 2.

Expected: 3 passed.

- [ ] **Step 5: Run the complete Wire suite**

```bash
cd dialectic && python3 -m pytest tests/test_wire.py -q
```

Expected: all Wire tests PASS. Update only assertions whose old first-two-headlines behavior is deliberately replaced by the approved scan-past contract.

- [ ] **Step 6: Commit only the Wire slice**

```bash
git add dialectic/llm/wire.py dialectic/tests/test_wire.py
git diff --cached --check
git commit -m "fix(dialectic): the wire stops hammering blocked sources -- scan past, cool down"
```

### Task 3: Current-state amendment and full verification

**Files:**
- Modify: `dialectic/CLAUDE.md`
- Modify: `JOURNAL.md` (leave unstaged if unrelated pre-existing lines cannot be isolated safely)

**Interfaces:**
- Documents: direct fetch -> 403-only tracking-sanitized Reader -> loud failure.
- Documents: six-hour Wire cooldown, six-headline scan, two-readable scoring cap.
- Changes no runtime interface.

- [ ] **Step 1: Amend current-state documentation beside existing history**

Append a dated amendment to `dialectic/CLAUDE.md`; do not rewrite older historical descriptions:

```markdown
## Amendment 2026-08-15 — article walls and the Wire retry clock

- `defuddle.service` remains direct-first. A publisher HTTP 403 alone triggers
  one tracking-sanitized Jina Reader request inside the same 15-second budget;
  all consumers keep the existing article JSON contract. Pasted/model text is
  still not filing provenance.
- Wire cools extraction failures and thin shells for six hours in process
  memory, scans at most six fresh feed entries, and sends at most two readable
  articles to relevance scoring per room/run. Interactive retries ignore this
  cooldown.
```

Append one Journal line recording the verified behavior and why. Do not stage unrelated pre-existing journal changes.

- [ ] **Step 2: Run all article-consumer and scheduled-reader tests**

```bash
cd dialectic && python3 -m pytest \
  tests/test_tools_registry.py \
  tests/test_reading_relay_endpoint.py \
  tests/test_claim_check.py \
  tests/test_wire.py \
  tests/test_news_night.py \
  tests/test_prediction_watch.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the full backend suite**

```bash
cd dialectic && python3 -m pytest tests/ -q
```

Expected: PASS. If the documented load-sensitive `test_home_activity_pg` p95 gate alone flakes, preserve the full output, rerun that exact test once, and report both results; do not weaken its threshold.

- [ ] **Step 4: Prove both blocked publishers through a temporary sidecar**

Start `server.mjs` from `dialectic/defuddle_service` with `DEFUDDLE_PORT=18110` in a foreground execution session. Do not touch `defuddle.service`.

From a second command, run:

```bash
curl -fsS http://127.0.0.1:18110/health | jq -e '.ok == true'
curl -fsS --max-time 20 http://127.0.0.1:18110/extract \
  --json '{"url":"https://qz.com/anthropic-ipo-2-trillion-valuation-october-081326"}' \
  | jq -e '(.title | contains("Anthropic")) and (.content | length > 1000) and (.word_count > 100)'
curl -fsS --max-time 20 http://127.0.0.1:18110/extract \
  --json '{"url":"https://www.commondreams.org/news/world-liberty-financial-bank-charter"}' \
  | jq -e '(.title | contains("Trump")) and (.content | length > 1000) and (.word_count > 100)'
```

Expected: all three `jq -e` commands exit 0 without printing article bodies. Stop the temporary foreground process with Ctrl-C.

- [ ] **Step 5: Verify no production activation occurred**

```bash
systemctl show defuddle.service -p MainPID -p ExecMainStartTimestamp -p ActiveEnterTimestamp
systemctl show dialectic.service -p MainPID -p ExecMainStartTimestamp -p ActiveEnterTimestamp
curl -fsS http://127.0.0.1:8010/health
curl -fsS http://127.0.0.1:8002/health
```

Compare the PIDs/start timestamps with the pre-implementation values. Expected: unchanged services and healthy endpoints.

- [ ] **Step 6: Run final scope and whitespace verification**

```bash
git diff --check
git status --short --branch
git log --oneline -5
```

Inspect every requested diff. Confirm no trading snapshot, image, cache directory, or unrelated Journal content entered either implementation commit.

- [ ] **Step 7: Commit the current-state amendment only**

```bash
git add dialectic/CLAUDE.md
git diff --cached --check
git commit -m "docs(dialectic): amend beside -- readers cross 403 walls, Wire waits"
```

Leave `JOURNAL.md` unstaged if its requested new lines cannot be isolated from pre-existing dirty work. Report that boundary explicitly.

## Production activation boundary

Implementation completion does not activate the fix. After the code and tests are committed, production requires explicit authorization for:

1. `systemctl restart defuddle.service` and verification of `/health` plus both exact publisher URLs through port 8010.
2. `systemctl restart dialectic.service` only for the Wire cooldown; verify `/health`, scheduler freshness, and the next `wire_watch` ledger detail.
3. A real Home `read_article` and reading-Accept retry to prove clinician-equivalent human/browser behavior at the actual tool boundary.

Do not combine those restarts with implementation verification or infer authorization from approval of this plan.
