# Dialectic Article Fetch Resilience Design

**Date:** 2026-08-15

**Status:** Approved design; awaiting written-spec review

**Repository:** `/root/DwoodAmo`

**Activation:** Code, tests, and a narrow commit only. Restarting `defuddle.service`
or `dialectic.service` remains a separate production action.

## 1. Problem

All article consumers share `defuddle.service`: `read_article`, claim checking,
Wire, overnight news, prediction evidence, and both stages of saving a reading.
The sidecar currently performs one direct Node `fetch`. Publisher bot defenses
therefore turn into a sidecar 502 carrying `upstream returned HTTP 403` for every
consumer. `save_reading` cannot accept pasted text as a substitute because its
provenance contract requires a fresh source fetch.

The live evidence has two distinct layers:

- Quartz returns a Cloudflare JavaScript challenge and Common Dreams returns a
  Varnish denial to the production host. Direct headers and a Safari user agent
  do not clear either block.
- Wire treats only persisted `reading_items` URLs as seen. An extraction failure
  is never persisted, so a blocked top-of-feed URL can be retried every 15
  minutes and consume one of the two candidate slots indefinitely.

## 2. Decision

Keep direct Defuddle extraction as the primary path. Only when the publisher
returns HTTP 403, make one request through Jina Reader and normalize its Markdown
response into the exact existing article dictionary. Jina's documented public
Reader endpoint is `https://r.jina.ai/<target-url>`; live probes against both
failed production URLs returned the full articles with HTTP 200.

Do not fall back for 401, 404, 451, or arbitrary non-2xx responses. Those statuses
can represent authentication, absence, or an explicit legal restriction rather
than bot mitigation. Do not add a generic retry loop.

Separately, give Wire a bounded in-process cooldown for extraction failures and
thin-content shells, then scan past cooled or unreadable headlines until it has
at most two readable articles to score. This prevents one blocked publisher from
occupying a room's candidate slots while preserving the existing maximum of two
LLM relevance calls per room per run.

## 3. Defuddle data flow

`POST /extract {url}` retains its current request and response interface:

1. Parse and validate the target as public HTTP(S), using the existing private
   host fence.
2. Create one 15-second abort budget shared by the direct and fallback requests.
   The fallback does not extend the Python client's existing 20-second contract.
3. Attempt the current direct fetch and Defuddle HTML extraction unchanged.
4. On direct HTTP 403 only, remove `email` and every case-insensitive `utm_*`
   query parameter before sending the public URL to Jina. Preserve all other
   query parameters because they may identify the article.
5. Require a successful `text/plain` Reader response with a non-empty
   `Markdown Content:` section. Parse `Title`, `Published Time`, and the Markdown
   body. Set `site` from the original target hostname, compute `word_count` from
   the body, and leave unavailable author/description fields null.
6. Return the original caller URL in the existing `url` field. Sanitization is
   for third-party disclosure only and does not silently change caller identity.
7. If Reader fails, return a loud 502 that retains the original upstream 403 and
   names the fallback failure. No empty article or pasted/model-authored content
   may masquerade as a successful fetch.

No API key, new environment variable, database migration, compatibility shim, or
new runtime service is introduced. The unauthenticated Reader limit is currently
20 requests/minute; fallback-only routing and Wire cooldown keep normal traffic
well below that boundary.

## 4. Wire behavior

Wire keeps a module-level map from URL to monotonic retry deadline. This state is
operational suppression, not durable product data, so a process restart may clear
it safely.

- Extraction failures and thin bodies cool that URL for six hours.
- A cooled URL is recorded in job detail as `fetch_cooldown` and is not fetched.
- Each room scans at most six fresh feed entries per run.
- At most two readable articles reach relevance scoring, preserving the current
  LLM-cost ceiling.
- Below-threshold readable articles count against the two-article scoring budget;
  they are not failures and do not enter cooldown.
- Interactive `read_article`, claim-check, and saving paths do not consult Wire's
  cooldown. A human-requested retry always reaches the extractor.

The cooldown is deliberately not configurable. It has one caller and one purpose;
adding an environment policy layer would create indirection without a second use.

## 5. Saving behavior

No reading-library trust rule changes. The model still cannot file pasted text or
its own summary. `save_reading` and the human Accept relay continue to re-fetch
through the sidecar; they succeed for a 403-blocked publisher only when the Reader
fallback returns source text. The unique `(room_id, url)` identity, human Accept
boundary, stored provenance, memory twin, and thin-content policy remain intact.

## 6. Tests

Use Node's built-in test runner with an injected fetch implementation; add no test
dependency. Tests must first fail against the current sidecar, then prove:

- direct 200 still uses Defuddle and never calls Reader;
- direct 403 calls Reader once and returns normalized source content;
- tracking parameters are absent from the Reader request while meaningful query
  parameters and the returned original URL are preserved;
- 404 and 451 never invoke Reader;
- timeout, non-200, wrong content type, and empty Reader content fail loudly;
- private-host URLs never reach either fetch path.

Python Wire tests must first fail against the current loop, then prove:

- a failed extraction enters cooldown;
- a cooled top headline is skipped and a later readable headline can use the
  scoring slot;
- scanning stops after six feed entries;
- no more than two readable articles are scored;
- below-threshold readable articles are not cooled.

Run the focused Node and Python suites, the complete Defuddle test command, the
full Wire test file, and `git diff --check`. A final read-only live probe may call
the changed sidecar in a temporary process on a non-production port; production
services are not restarted during implementation verification.

## 7. Rejected approaches

- **Local Playwright fallback:** adds a browser runtime to a tiny sidecar and can
  still lose to Cloudflare automation detection.
- **Trust pasted article text:** fixes saving only by weakening the source-of-record
  rule; claim-check, Wire, and ordinary reads remain broken.
- **Retry direct fetch with more browser headers:** current Safari headers already
  receive explicit Cloudflare/Varnish denials, so repetition is not a new path.
- **Suppress errors without a fallback:** quiets logs but does not restore reading
  or saving.

## 8. Behavioral changes

- A public article returning direct HTTP 403 may now succeed through one external
  Reader request.
- The sanitized public URL is disclosed to Jina only on that 403 path.
- A failed Wire URL is retried after six hours or a process restart instead of
  every 15 minutes.
- Wire may inspect up to six feed entries to find two readable articles, but still
  performs no more than two relevance-model calls per room per run.

All other response shapes, ordering, nullability, error boundaries, and human
acceptance behavior remain unchanged.
