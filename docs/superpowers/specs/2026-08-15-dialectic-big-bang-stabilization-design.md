# Dialectic Big-Bang Stabilization Design

**Date:** 2026-08-15

**Status:** Approved design; awaiting written-spec review

**Repository:** `/root/DwoodAmo`

**Release shape:** One isolated stabilization branch, one integrated verification gate, one implementation commit, and one separately authorized production activation boundary

## 1. Decision

Repair the verified security, data-contract, concurrency, performance, iPad-shell,
accessibility, and current-state-authority defects as one release. The work may be
developed and tested in ordered internal slices, but no slice ships independently.
The release is accepted, committed, and later activated only when the entire gate
is green.

This is deliberately a big bang. It trades a larger review and rollback surface
for one coherent contract across Dialectic, tradingDesk, PostgreSQL, SQLite, and
the PWA. The migrations therefore remain additive, public response changes remain
additive wherever possible, and activation remains a separate user decision.

## 2. Current evidence

The design responds only to defects verified against current source or the live
read-only surface:

- room creation is unauthenticated;
- generic room join trusts a body-supplied user ID after validating only the room
  token;
- user-model reads prove the target is a member but do not prove the caller is the
  target;
- FastAPI exposes the rate-limit dependency's `limit` and `window` arguments as
  attacker-controlled query parameters;
- password recovery distinguishes account states and claims email delivery that
  does not exist;
- the unmounted cross-session router contains a hard-coded user UUID and commented
  authentication;
- message reload omits reply and edit fields;
- unread SQL excludes NULL-authored LLM messages and compares a lowercase enum
  column with uppercase `SYSTEM`;
- attachment dedup can return a row another user cannot bind, or a row already
  bound to an earlier message;
- REST message creation lacks the WebSocket path's reference fence, sequence retry,
  transaction, and live broadcast;
- ancestry pagination applies thread-local sequence cursors to messages from
  multiple threads and derives continuation flags from an already-filtered list;
- proposal relays check acceptance before an external write and stamp it after,
  permitting concurrent duplicate writes and crash gaps;
- relay dependencies hold PostgreSQL connections while network calls can wait for
  tens of seconds;
- startup catches database-pool failure and advertises a demo mode whose routes
  then fail through a missing pool;
- the installed-PWA shell lacks top and side safe-area treatment, pins both rails
  at iPad-landscape width, opens a duplicate participant surface, and contains
  undersized and low-contrast chrome;
- current-state documentation retains shipped TODOs, stale counts, and a tracked
  service unit that differs from the actual service shape.

Healthy services and green broad suites do not negate these contract-level
failures. Every repair below receives a mutation-sensitive regression test.

## 3. Trust boundary

### 3.1 Room and user-model authorization

`POST /rooms` keeps its request and response schema but requires
`get_current_user`. It still creates no membership; the existing client follows
creation with the generic join call, and preserving that two-step lifecycle avoids
silently changing room events or membership timing.

`POST /rooms/{room_id}/join` requires a bearer user in addition to the room token.
The body `user_id` remains for compatibility but must equal the bearer user's ID.
Home's existing nondelegable membership rule remains unchanged.

`GET /rooms/{room_id}/user-models/{user_id}` requires a bearer user, requires the
path user to equal that bearer user, then applies the existing room-token and
membership fences. A user can inspect only their own model.

### 3.2 Rate limits

The router dependency becomes `check_rate_limit(request)` with no injectable
policy arguments. OpenAPI must expose neither `limit` nor `window`.

The existing in-process limiter remains because production is a single application
process. It gains bounded cleanup: empty expired buckets are deleted rather than
retained forever. The fixed global auth policy remains 60 requests per 60 seconds
per IP and endpoint.

Credential-guessing routes add a second key derived from the normalized account
identifier's SHA-256 digest, never a raw email or user ID:

- login, verify-email, and reset-password: five attempts per 15 minutes per IP and
  five per account digest;
- forgot-password: three attempts per 15 minutes per IP and three per account
  digest;
- signup: five attempts per hour per IP.

A failed limit returns 429 before password hashing, code lookup, or session writes.
This release does not add Redis-only behavior or a configurable policy layer.

### 3.3 Password-recovery truth

Email delivery is absent, so `/auth/forgot-password` must not create an unreachable
credential or claim one was sent. It returns the same 503 response for known and
unknown addresses and performs no verification-code insert.

`/auth/reset-password` retains support for a valid, already provisioned reset code,
but an unknown account and an invalid or expired code produce the same response.
The frontend displays the unavailable-recovery message verbatim rather than
promising an email.

### 3.4 Dormant unsafe router

Delete `dialectic/api/cross_session_routes.py` after a reference scan proves it is
not imported or mounted. Its supported personal-memory behavior already lives in
authenticated endpoints in `api/main.py`; retaining a second placeholder door is
strictly a future security hazard, not dormant functionality.

## 4. Message and notification correctness

### 4.1 Reload contract

Every `MessageResponse` produced by thread history includes the persisted
`references_message_id` and `edited_at` values. Metadata behavior remains
unchanged.

### 4.2 REST send parity

The REST fallback validates that a referenced message exists in the same room.
Message insert and event insert share one transaction. Sequence collision handling
matches the WebSocket path: at most three fresh transactions with the existing
short bounded backoff.

Only after commit, the path resolves the sender's display name and emits the same
`message_created` payload contract through the configured connection manager.
Database failure emits no event and no broadcast; broadcast failure does not roll
back a committed message.

Extract the shared persisted-message payload construction into the existing
transport module and use it from both REST and WebSocket. This is the single seam
needed to prevent their live contracts from diverging; it does not introduce a new
service layer.

### 4.3 Unread counts

All three unread queries use PostgreSQL's null-safe
`m.user_id IS DISTINCT FROM $user` predicate and compare `speaker_type` with the
stored lowercase `system` value. Human messages by another user and LLM messages
with NULL `user_id` count; the current user's messages and system messages do not.

### 4.4 Attachment ownership

Content-addressed blobs remain room-deduplicated on disk, while attachment rows
remain per usable upload. A dedup hit may return an existing row only when it:

- belongs to the current uploader; and
- is still unbound.

A different uploader or an already-bound row creates a new attachment row pointing
at the same content-addressed path. Bind authorization remains unchanged. No schema
migration is required.

## 5. Durable external operations

### 5.1 PostgreSQL operation ledger

Migration 018 adds `external_operations` with:

- UUID primary key;
- room ID, operation kind, and unique operation key;
- nullable source message ID and proposal slot for message-backed operations;
- initiating user ID;
- status constrained to `pending`, `succeeded`, or `failed`;
- attempt count, lease expiry, last error, and JSONB external result;
- created and updated timestamps;
- a partial unique `(source_message_id, proposal_slot)` constraint when both
  coordinates are present.

An endpoint first authenticates and validates the stored proposal, then claims or
reclaims its operation in a short transaction. It releases the connection before
calling tradingDesk or Defuddle. A second live request receives the recorded
success, a bounded in-progress conflict, or safely reclaims a failed/expired lease.

Success persists the external result and the proposal acceptance stamp in one
transaction. The stamp uses the operation's initiating user, so a crash and later
retry cannot rewrite who made the original move. Failure records the error and
leaves the proposal retryable. A process death after the external write is safe
because every external destination below accepts the same stable operation key.

### 5.2 Prediction creation and resolution

tradingDesk SQLite migration 006 adds an optional unique prediction source key and
an optional resolution source key. Dialectic derives stable keys from the proposal
coordinate, not timestamps or request IDs.

Repeated prediction creation with the same source key returns the original
prediction without inserting or broadcasting twice. Repeating a resolution with
the same source key and verdict returns the existing result. A different verdict
for an already resolved prediction returns 409.

### 5.3 Reading acceptance

Defuddle extraction is a read, not the durable side effect. After extraction,
`reading_items` and its memory twin are written together with operation success and
the proposal stamp in the PostgreSQL transaction boundary supported by their
existing helpers. The unique `(room_id, url)` rule remains the durable article
identity.

### 5.4 Thesis creation

A room-bound tradingDesk thesis is idempotent on `meta.dialecticRoomId`. Add one
module-level lock around the bound-room scan, create decision, and atomic file
write. A retry returns the existing book. Dialectic keys its operation by room ID,
with no source-message coordinate, and can repair a missing local
`linked_book_id` without creating an orphaned second thesis.

### 5.5 Connection lifetime

Proposal and trading-relay endpoints receive the pool, not a connection held for
the request lifetime. They acquire only for local authorization, claim, or finalize
transactions. No PostgreSQL connection remains checked out during tradingDesk,
Defuddle, quote, news, or other bounded network waits.

## 6. Pagination and bounded queries

Thread-local sequence cursors remain supported for `include_ancestry=false`.
Ancestry pagination gains additive `before_cursor` and `after_cursor` query fields
and `oldest_cursor` and `newest_cursor` response fields. The opaque URL-safe cursor
encodes the stable `(created_at, message_id)` coordinate.

The recursive ancestry CTE continues to cap depth at 50, but applies the cursor,
ordering, and `LIMIT + 1` in SQL. The extra row determines continuation without a
full-history Python scan. Ordering is deterministic on `(created_at, id)`.

Supplying `before_sequence` or `after_sequence` with ancestry enabled returns 422
because a thread-local integer cannot identify a cross-thread position. Current
frontend code supplies neither and remains compatible. This is the one deliberate
legacy behavior break; silently returning an incorrect window is worse.

Before finalizing migration 018, run `EXPLAIN` for the rewritten ancestry and
unread queries against the current schema. Add an index only when that evidence
shows an avoidable scan on the bounded query, and record the plan before and after
in the verification ledger. Otherwise migration 018 contains no speculative
message or receipt index.

## 7. Startup and failure behavior

Database-pool creation failure logs the exception and aborts application startup.
There is no demo mode because the mounted product has no database-free route set.
The optional Redis path keeps its existing explicit in-memory fallback because that
fallback is real and supported.

Required pool dependencies fail loudly if called before initialization. External
operation errors preserve their current 502 boundary, record retry state, and never
silently substitute mock data or a successful-looking empty response.

## 8. iPad and installed-PWA shell

### 8.1 Safe areas and viewport

The application shell defines top, right, bottom, and left inset variables from
`env(safe-area-inset-*)` and applies them at the outer layout boundary. Fixed
headers, drawers, and composer placement consume those variables rather than
adding independent ad hoc padding. Installed `black-translucent` mode remains, and
the browser gate fails if any status-bar collision survives.

### 8.2 Responsive rails

At viewport widths below 1280 CSS pixels, both side rails become explicit overlay
drawers and default closed. The conversation/work surface receives the full width.
At 1280 and above, the left navigation remains persistent; the right context rail
renders only after an explicit user action.

The RightPanel never falls back from an unavailable Memory tab to Users. Users are
already represented by the participant surface, so the duplicate Users tab is
removed. Existing Memory, Branches, Insights, Stakes, History, AI, and Share
capabilities remain reachable when they apply.

All seven scenes remain canonical. Narrow widths show the primary scene choices
and place the remainder in one accessible overflow control; no scene or URL is
deleted.

### 8.3 Legibility and interaction

Shell controls use at least 12px text, ordinary interface copy at least 14px, and
44px minimum touch targets where controls are independently tappable. Normal text
meets 4.5:1 contrast against its actual background. Keyboard focus is visible, tab
state is visually and semantically exposed, and active/inactive state does not rely
on color alone.

The existing visual identity—sheet, ink, cacao, rules, and instrument cards—stays.
This is a hierarchy and usability correction, not another aesthetic rewrite.

## 9. Current-state authority

Documentation changes ship in the same release:

- README keeps durable architecture and verification commands but drops volatile
  hard-coded test totals;
- `dialectic/CLAUDE.md` remains the operator contract and states the actual current
  migration/tool surface once verified;
- `dialectic/TODOS.md` contains only unfinished work; shipped Releases 1–3 move out
  of the active queue without rewriting their history;
- the current master plan links the stabilization release and its verification
  ledger;
- the tracked service unit is reconciled with the non-secret structure of the
  installed unit;
- the existing human-interaction audit is amended only where this release changes
  status; no duplicate audit document is created.

`JOURNAL.md` records meaningful design, dead ends, migration decisions, verification,
and activation facts. Generated snapshots and unrelated working-tree artifacts are
never staged.

## 10. Testing and acceptance

Every behavioral repair follows red-green-refactor. Before each test body, the
production mutation it catches is named. Tests exercise real route, SQL, repository,
or component behavior; external network calls are mocked only at the HTTP boundary.

The integrated local gate includes:

- targeted Dialectic route, SQL, transport, relay, and migration tests;
- PostgreSQL integration tests for operation claiming, stale-lease recovery,
  acceptance actor stability, and ancestry windows;
- tradingDesk repository, migration, builder, prediction, and resolution tests;
- full Dialectic backend and tradingDesk suites;
- frontend unit tests, lint, and production build;
- full-app axe checks rather than message-wrapper-only checks;
- browser screenshots at phone portrait, iPad portrait, iPad landscape, laptop,
  and wide desktop widths;
- installed-PWA safe-area and 44px touch-target assertions;
- an explicit mutation check for every repaired boundary.

The big-bang implementation is complete only when the whole gate passes. A green
subset is progress, not a shippable release.

## 11. Activation and rollback boundary

Implementation does not authorize production writes, migrations, restarts, unit
installation, frontend flips, or deployment.

If separately authorized after the integrated gate:

1. record database, SQLite, service, and served-asset baselines;
2. back up PostgreSQL and the tradingDesk SQLite database;
3. apply additive PostgreSQL migration 018 and tradingDesk migration 006;
4. flip the frontend before closing backend doors, preventing an old UI from
   advertising behavior the new backend refuses;
5. restart tradingDesk and Dialectic in the dependency order specified by the
   implementation plan;
6. verify exact auth, message, operation, health, served-asset, and browser
   contracts;
7. run the real-device checklist.

Rollback may restore the previous binaries and frontend because both migrations are
additive. New columns and the operation table remain in place until a separately
reviewed cleanup; rollback never drops data under pressure.

## 12. Explicit non-goals

- No replacement of FastAPI, PostgreSQL, React, Vite, SQLite, or the existing
  WebSocket protocol.
- No enterprise policy engine, generalized outbox framework, or configuration
  indirection for one release.
- No removal of mounted personas, replay, knowledge-graph, Atlas, or specialist
  trading surfaces.
- No broad decomposition of `api/main.py`, `transport/handlers.py`, `App.tsx`, or
  the orchestrator beyond seams demanded by these fixes.
- No email provider implementation; recovery fails honestly until one exists.
- No production activation inside the implementation session.
