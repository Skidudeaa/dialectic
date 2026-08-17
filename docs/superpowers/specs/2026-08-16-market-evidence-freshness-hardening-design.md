# Market Evidence Freshness Hardening

**Date:** 2026-08-16

**Status:** Approved design; awaiting written-spec review

**Repository:** `/root/DwoodAmo`

**Review:** adjudicate run `20260816-212612-b03340`

## 1. Decision

Harden the deployed Polymarket and GDELT verification path so every response
separates what the source said from how current that observation is. A confirmed
empty response, a cached confirmed-empty response, a stale prior observation,
no configured source, and an unavailable source must never collapse into the
same successful empty result.

The repair stays inside the existing tradingDesk producer and Dialectic tool
consumer. It adds no database migration, provider, credential, configuration
layer, or frontend requirement. Existing book files, the Gamma client, the
GDELT client, and tradingDesk's `feedFreshness` clock remain authoritative.

## 2. Proven defects

The first repair is live, but its adversarial review found two release-blocking
defects and eleven additional contract gaps:

- `get_thesis_news` still inherits the tool registry's 10-second timeout while
  its HTTP request permits 60 seconds. A cold focused query is cancelled before
  a healthy GDELT response can arrive.
- One process-wide news lock is held across the network fetch. Unrelated cold
  queries serialize, warm cache hits wait behind them, and blocked `to_thread`
  calls can starve Polymarket work.
- The book-scoped Polymarket route has no cache or single-flight and creates one
  worker per configured market.
- Cached degraded news responses repeat their original `retry_after_seconds`
  instead of reporting the remaining cooldown.
- Polymarket shrinking can remove the status discriminator while retaining a
  count derived from the unshrunk payload.
- Status-less or query-mismatched news payloads can still pass as successful
  emptiness during version skew.
- Mixed Polymarket coverage is called `ok`; the dark configured markets are
  visible only if the model performs a set difference itself.
- `get_polymarket_odds` reads an optional `book_id` which its schema does not
  declare.
- Focused-query length is validated only by the producer, yielding an opaque
  HTTP 422 at the tool boundary.
- Relay-shape failure, parallel strict failure, strict invalid-data retry, and
  caller-supplied GDELT encoding lack regression coverage.
- The legacy desk-wide Polymarket endpoint unintentionally inherited the new
  strict, filtered, five-second behavior.

The owner's added acceptance rule is stronger than those findings: a response
must say whether it is confirmed empty now or merely the last observation, and
must expose when the source was last checked successfully.

## 3. Epistemic contract

### 3.1 Evidence and freshness are orthogonal

Existing `status` fields retain source meaning. A nested `freshness` object
describes observation timing independently:

```json
{
  "status": "no_matches",
  "freshness": {
    "state": "live",
    "attempted_at": "2026-08-17T01:00:00Z",
    "observed_at": "2026-08-17T01:00:00Z",
    "served_at": "2026-08-17T01:00:00Z",
    "age_seconds": 0,
    "ttl_seconds": 900
  }
}
```

Fields mean exactly:

- `state: live` — this request reached the provider and the provider answered
  normally. `ok`, `partial`, `no_data`, and `no_matches` may all be live.
- `state: cached` — no provider request occurred for this response. The status
  describes the observation made at `observed_at`; `age_seconds` is recomputed
  when served.
- `state: stale` — the latest provider attempt failed or an observation has
  exceeded its TTL. Any prior data is historical and cannot be quoted as
  current.
- `state: not_applicable` — no provider is configured, so no fetch timestamp or
  evidentiary claim exists.
- `attempted_at` — time of the most recent provider attempt, successful or not.
- `observed_at` — time the provider last answered normally for this exact
  source scope and query.
- `served_at` — time this response was constructed.
- `age_seconds` — whole seconds from `observed_at` to `served_at`, or null when
  no successful observation exists.
- `ttl_seconds` — the existing source freshness policy, not a new configurable
  value.

Timestamps are UTC ISO-8601. Cached objects preserve `observed_at`; they never
restamp old evidence as current.

### 3.2 Confirmed empty

`status: no_matches` for GDELT and `status: no_data` for Polymarket mean the
provider answered normally and yielded no current matching records. With
`freshness.state: live`, that is confirmed empty at `observed_at`. With
`freshness.state: cached`, it means confirmed empty at the older timestamp and
no new poll occurred.

Neither status proves the underlying event did not happen. The tool descriptions
must keep that warning.

### 3.3 Stale prior observation

Each scoped cache retains the last successful observation after its serving TTL
expires. When a new poll fails, the bridge returns current failure state plus an
optional `last_observation`:

```json
{
  "status": "unavailable",
  "freshness": {
    "state": "stale",
    "attempted_at": "2026-08-17T01:10:00Z",
    "observed_at": "2026-08-17T00:45:00Z",
    "served_at": "2026-08-17T01:10:00Z",
    "age_seconds": 1500,
    "ttl_seconds": 900
  },
  "markets": [],
  "last_observation": {
    "status": "ok",
    "observed_at": "2026-08-17T00:45:00Z",
    "markets": [{"slug": "market-id", "probability": 0.42}]
  }
}
```

The current `markets` or `articles` list stays empty on failure. Historical data
lives only under `last_observation`, so list-only browser consumers cannot
mistake it for current data.

Dialectic treats `rate_limited`, `unavailable`, and stale current checks as
failed tool calls (`ok: false`). The tool error names `observed_at`, age, and the
last observation when one exists. The model may say “last observed at X,” but
must also say the current check failed. No prior observation means only the
failure reason is returned.

The cache is process-local like the current source cache. After a restart,
tradingDesk may use the latest snapshot's existing `feedFreshness` and persisted
book values as a last observation only when their source, timestamp, and market
identity can all be proven. It must not synthesize a timestamp for an unstamped
book default.

## 4. Polymarket contract

### 4.1 Scoped statuses

`GET /api/bridge/polymarket/{thesis_id}` returns:

- `ok` — every configured market has a current numeric probability.
- `partial` — at least one configured market has a current probability and at
  least one does not.
- `no_data` — the provider answered normally but no configured market has a
  current probability.
- `not_configured` — the book declares no Polymarket market.
- `unavailable` — the provider request failed.

The payload keeps `configured_markets` and current numeric `markets`, and adds
`missing_markets` in authored order. `partial` and `no_data` therefore name dark
markets directly. Probabilities must be real numbers, not booleans, within
`0.0..1.0`; slugs must be configured and unique.

### 4.2 Cache and concurrency

Use a bounded book-scoped TTL cache with one in-flight producer per book. A
Bench read and an LLM read for the same book share the same poll. Cache reads do
not enter a worker thread. Failures are not stored as successful current data;
the last successful observation is retained only for stale reporting.

Parallel Gamma work is capped at eight workers regardless of book size. Today's
four-market corpus stays fully parallel. The cap prevents an edited book from
turning one request into an unbounded public-API fan-out.

### 4.3 Payload shrinking

Dialectic protects `status`, `freshness`, `configured_markets`, and
`missing_markets` when shrinking. `count` is derived from the `markets` list
that remains in the final payload. If current market rows must be truncated,
the response names the truncation rather than retaining an inconsistent count.

### 4.4 Tool schema

`get_polymarket_odds` continues accepting an optional explicit `book_id`,
matching the established cross-book behavior of other trading tools. Its input
schema must declare that property, and its description must say that it defaults
to the active room's book rather than claiming strict room-only scope.

### 4.5 Legacy browser compatibility

The legacy desk-wide `GET /api/market/polymarket` keeps its previous best-effort
membership contract: configured markets remain present with `probability: null`
when no current value exists, and its previous 15-second request budget remains.
Strict failure semantics, scoped statuses, partial coverage, and stale history
belong to the service-authenticated book route.

The Dialectic Bench remains list-shaped. It returns only current rows from
`markets`; it never unwraps `last_observation` into the list.

## 5. GDELT contract

### 5.1 Bounded interactive latency

The bridge's interactive fetch performs one bounded 20-second provider attempt.
The existing source-wide cooldown replaces sleeping and retrying inside a human
turn. A first 429 is classified immediately as `rate_limited`; it is not slept
through and retried inside the request.

The seam budget is ordered:

1. GDELT provider attempt: at most 20 seconds.
2. Dialectic HTTP request: 25 seconds.
3. `get_thesis_news` tool execution: 29 seconds.
4. Whole tool loop: 60 seconds.

Every outer budget exceeds its inner producer while the tool stays under half
the whole-turn budget. Standing jobs can retry on their next scheduled run; an
interactive request never occupies the entire turn with internal retries.

### 5.2 Cache and single-flight

Cache lookup occurs before thread dispatch. Same-query misses share one
in-flight task. Different queries may overlap through a dedicated two-worker
news executor; they do not queue behind a single network-held mutex and do not
consume the default executor used by Polymarket.

A short state lock protects only cache, cooldown, and in-flight-map mutations.
No lock is held during network I/O. A successful provider response resets the
source rate-limit streak only through that protected state transition.

Cache identity is the exact normalized query plus its source scope. Returned
payloads echo the exact query. Cached `retry_after_seconds` is derived from the
remaining absolute deadline each time it is served, never copied from the
original response.

### 5.3 Strict consumer validation

Dialectic accepts only the five documented news statuses, `source: gdelt`, a
list-valued `articles` field, a valid freshness object, and the exact focused
query it requested. Missing status, unknown status, status/shape inconsistency,
or a query mismatch raises `TradingDeskError` and fails the tool trace.

The tool validates its trimmed focused query locally at 5–500 characters before
network I/O. GDELT operator syntax remains permitted and auditable. The existing
`urlencode` parameter builder remains authoritative; regression tests prove
`&`, `=`, `#`, spaces, and operators remain one encoded `query` parameter.

## 6. Relay and failure behavior

The room-scoped Bench relay rejects a legacy bare list or a status object without
`markets` as an upstream shape error and maps it to 502. It does not fall back to
the desk-wide endpoint, because that would reintroduce unscoped evidence.

Polymarket transport/API failures are caught only at the scoped bridge boundary
where they become explicit `unavailable` state. No catch-all returns an empty
success. Unexpected programming errors continue to fail the HTTP request.

GDELT provider exceptions remain structured for scheduled and Bench consumers;
the LLM executor converts actual provider degradation into a failed tool result.

## 7. Test-first implementation gate

Before production changes, add failing tests for:

1. news HTTP and tool timeout ordering;
2. warm news cache hits bypassing a blocked cold fetch;
3. independent cold news queries overlapping within the bounded executor;
4. same-key news and same-book Polymarket single-flight;
5. bounded Polymarket worker count;
6. live, cached, stale, and not-applicable freshness timestamps and ages;
7. current failure carrying a separate stale prior observation;
8. cached cooldown remaining time decreasing;
9. Polymarket `partial`, `missing_markets`, numeric bounds, and authored order;
10. shrink protection and post-shrink count consistency;
11. missing/unknown news status and focused-query mismatch failing loudly;
12. locally rejected out-of-bounds focused queries with no HTTP call;
13. the declared optional Polymarket `book_id` schema;
14. relay 502 behavior for legacy and malformed bridge shapes;
15. parallel plus strict Polymarket exception propagation;
16. strict invalid-data retry count and terminal error;
17. special-character and operator-preserving GDELT URL encoding;
18. legacy global Polymarket null membership and 15-second behavior;
19. the Bench never presenting stale historical rows as current.

Prove red then green for each new behavior. Run the focused bridge, adapter,
tool-registry, tool-loop, relay, and fetcher suites, then both full backend
suites. Production restart remains a separate activation step after a clean
commit and fresh runtime checks.

## 8. Deliberate exclusions

Do not implement the review's rejected expansions:

- no sanitization rewrite of filesystem exception details in this pass;
- no per-room GDELT quota system;
- no multi-worker distributed cache or lock;
- no desk-wide fallback during producer/consumer version skew;
- no expired-market substitution;
- no persistent observation database or migration;
- no frontend presentation change.

## 9. Acceptance

The work is accepted when Amo or Dan can audit one tool result and say precisely:
what source scope was checked, what it returned, whether that result was live or
cached, when it was observed, how old it is, what configured markets are missing,
and—after a failed current poll—what the last observation was without mistaking
it for current evidence.
