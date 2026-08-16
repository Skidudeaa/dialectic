# LLM Market Verification Contract Repair

**Date:** 2026-08-16

**Status:** Approved design; awaiting written-spec review

**Repository:** `/root/DwoodAmo`

**Release shape:** One backward-compatible tradingDesk/Dialectic contract repair,
verified locally and committed separately from any production activation

## 1. Decision

Repair the data contracts that caused Claude to report two unrelated conditions as
“the news feed and Polymarket are both empty.” The repair makes authored
Polymarket feeds reachable, scopes prediction-market evidence to the active book,
and preserves the reason a news lookup produced no articles. It also lets Claude
issue one focused GDELT query when the room asks it to verify a claim outside the
book's standing watch query.

No new provider, credential, schema migration, frontend response shape, or config
layer is introduced. Existing GDELT and Polymarket clients remain authoritative.
Production restart is a separate authorization boundary.

## 2. Proven defects

- Book files and the thesis engine use `feeds[].market` for Polymarket market IDs,
  while `web.adapters.market._collect_symbols_from_books` reads only
  `feeds[].slug`. The HTTP adapter therefore discovers zero markets and returns
  `[]` without contacting Polymarket.
- `get_polymarket_odds` calls the global market endpoint, even in a book-bound
  room. The China book has no Polymarket feed, while other books do; a global
  empty list cannot describe the active room's coverage.
- The market adapter catches every Polymarket exception and returns `[]`, making
  upstream failure indistinguishable from no configured markets or no current
  data.
- The China book's standing GDELT query covers property defaults and
  restructurings. It does not cover new-loan contraction or offshore-trust tax
  claims, so a successful empty response cannot verify or refute those claims.
- The bridge represents no configuration, no matches, rate limiting, and other
  upstream failures as `articles: []`, sometimes with only a prose `note`.
- The tool loop marks every non-exception executor return `ok: true`; therefore a
  failure-shaped HTTP 200 is recorded as a healthy tool call. Its `degraded` flag
  describes LLM-provider fallback, not data-source health.

## 3. Polymarket contract

### 3.1 Canonical market identity

Inside `trading/web/adapters/market.py`, one local helper resolves a Polymarket
feed ID as `market` first, then legacy `slug`. Empty values are ignored. Both the
global collector and the book-scoped read use that helper. `market` wins if a
malformed feed supplies conflicting values because it is the field authored by
current books and consumed by the thesis engine.

The existing `GET /api/market/polymarket` response remains a list. Once fixed, it
contains results for every configured market rather than the current permanent
empty result. The adapter no longer catches an arbitrary exception and converts
it to `[]`; a real fetch failure reaches FastAPI as an error.

### 3.2 Book-scoped service read

Add service-authenticated `GET /api/bridge/polymarket/{thesis_id}`. It resolves
only that book's configured market IDs and returns:

```json
{
  "status": "ok | not_configured | no_data",
  "configured_markets": ["market-id"],
  "markets": [{"slug": "market-id", "probability": 0.42}]
}
```

`not_configured` means the book declares no Polymarket feed. `no_data` means at
least one market is configured but the existing Polymarket client returned no
probability. An upstream exception is not encoded as either state; it is a failed
HTTP request and therefore a failed Dialectic tool call.

Dialectic's `get_polymarket_odds` resolves the room's book and uses this bridge
read. The Bench relay uses the same scoped read but continues returning only its
`markets` list, preserving the browser contract. The old global endpoint remains
available to existing tradingDesk consumers.

## 4. News contract

### 4.1 Structured source state

`GET /api/bridge/news/{thesis_id}` keeps `articles` and the existing headline
shape, and adds these fields:

```json
{
  "status": "ok | no_matches | not_configured | rate_limited | unavailable",
  "source": "gdelt",
  "query": "the exact query sent to GDELT",
  "articles": [],
  "fetched_at": "UTC ISO-8601",
  "cache_hit": false,
  "retry_after_seconds": 120,
  "note": "human-readable detail when useful"
}
```

`ok` requires at least one article. `no_matches` means GDELT answered normally
with zero matches. `not_configured` means no standing query exists. A
`GdeltRateLimitError` becomes `rate_limited`; any other provider exception becomes
`unavailable`. `retry_after_seconds` appears only for the latter two states.
Cached responses retain their original `fetched_at`; the returned copy sets
`cache_hit: true`. `query` is `null` only for `not_configured`.

Rate limits remain graceful HTTP 200 bridge responses so scheduled jobs and the
Bench can render source state instead of a generic 502. Dialectic's LLM executor,
however, raises a named tool error for `rate_limited` or `unavailable`, making the
tool trace `ok: false`. `no_matches` and `not_configured` remain successful,
structured coverage results.

### 4.2 Focused verification query

The service-only news route accepts an optional `query` parameter, trimmed and
bounded to 5–500 characters. When absent, it uses the book's standing query.
When present, it is sent to the existing GDELT article client unchanged and is
reported verbatim in the response, even if the book has no standing query. This
is targeted news retrieval, not a claim that GDELT is a general web index.

The news cache key includes the normalized query. Expired entries are pruned and
the cache is capped at 64 entries by evicting the entry nearest expiry; no
unbounded model-generated key set is kept. A GDELT 429 establishes one
process-wide GDELT cooldown using the existing exponential schedule. Every query
returns `rate_limited` without contacting GDELT until that cooldown expires, so
changing query text or books cannot hammer through it. The next successful GDELT
fetch clears the source-wide streak.

`get_thesis_news` gains optional `query` input and passes it as a request
parameter. Its description tells Claude to use the standing query for a thesis
update and one focused query when asked to verify a specific external claim. A
`no_matches` result explicitly says it is not evidence that the event did not
happen.

## 5. Compatibility and behavior changes

- Existing news consumers still receive `articles` and optional `note`; all new
  fields are additive.
- Existing browser Polymarket consumers still receive a list.
- The global Polymarket endpoint remains a list and begins returning the markets
  already authored in book files.
- A genuine Polymarket exception now fails loudly instead of masquerading as an
  empty success.
- The LLM's Polymarket evidence becomes room/book scoped.
- GDELT rate limiting and provider failures become failed LLM tool calls; a valid
  zero-match lookup remains a successful call with explicit coverage.
- The generic tool-loop `degraded` flag is unchanged because it correctly means
  provider-chain degradation, not data-source degradation.

## 6. Test-first implementation gate

Before production code changes, add focused failing tests proving:

1. current `market` feeds and legacy `slug` feeds are both discovered, with
   `market` canonical on conflict;
2. the current checked-in books yield four configured global markets;
3. the book-scoped endpoint distinguishes `not_configured`, `no_data`, populated
   data, unknown books, and upstream failure;
4. the global endpoint preserves its list response;
5. news distinguishes all five statuses and reports its exact query;
6. a focused query has a distinct bounded cache entry and cannot bypass a source
   cooldown;
7. cached news preserves `fetched_at` and reports `cache_hit: true`;
8. Dialectic sends the focused query, scopes Polymarket to the room's book, and
   raises tool errors only for true upstream degradation;
9. the Bench relay remains list-shaped for Polymarket.

After each expected red failure, implement only enough code to turn it green.
Then run the focused tradingDesk bridge/market suites, Dialectic tool and relay
suites, both full backend suites if the focused gates pass, and read-only live
requests only if production has not been restarted. No service restart, frontend
flip, migration, or live-data mutation is part of this implementation gate.

## 7. Acceptance

The repair is accepted when a China-room lookup can say exactly that the book has
no configured Polymarket market, a focused GDELT query can be audited by its exact
query and source status, configured markets are actually fetched, and no
rate-limit or provider failure is recorded as a healthy empty tool call.
