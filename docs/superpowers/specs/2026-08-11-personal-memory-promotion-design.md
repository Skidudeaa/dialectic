# Personal Cross-Room Memory Promotion

**Date:** 2026-08-11
**Status:** Approved — the user selected personal promotion.

## Goal

Let a room member promote a shared memory into their own cross-room LLM context
without changing what any other member's LLM can recall.

Acceptance case:

1. User A and user B share room A.
2. User A promotes a memory from room A.
3. User A can receive that memory in automatic LLM context in another room.
4. User B cannot receive it outside room A unless user B promotes it separately.

## Data model

Add `user_memory_promotions`:

- `memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE`
- `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `promoted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- primary key `(memory_id, user_id)`
- index `(user_id, memory_id)` for recall queries

Update both the numbered migration sequence and `dialectic/schema.sql` so fresh
databases and upgraded databases have the same shape.

The source `memories` row remains shared and keeps its existing `scope`. A
personal promotion is a user-specific visibility grant; it must not set
`memories.scope = 'global'`, `owner_user_id`, or `promoted_by_user_id`.

## Authorization and lifecycle

Promotion requires all three existing credentials:

- a valid bearer-authenticated user;
- a valid token for the memory's source room;
- current membership in that source room.

The manager write itself also joins through `room_memberships`, so callers
cannot bypass the membership fence. Missing, inactive, and inaccessible
memories have the same not-found result to avoid disclosing their existence.

Promotion is idempotent. Demotion deletes only the requesting user's grant and
is also idempotent after authorization. Deleting a memory or user cascades its
grants. If a user loses source-room membership, recall stops because reads
continue to require membership even if the grant row remains.

## Read path

Automatic cross-room recall joins `user_memory_promotions` on both the memory
and the requesting user. Existing active-memory, source-room membership, room
exclusion, similarity, and limit rules remain in force.

The dormant row-level `scope = 'global'` mechanism is not used for automatic
cross-room injection. There are currently no global rows to migrate.

## HTTP transport

Use the established REST authentication path rather than mounting
`api/cross_session_routes.py`, whose placeholder user identity is unsafe.

Add a narrow endpoint family:

- list the current user's promoted memory IDs for a room;
- promote one memory for the current user;
- demote one memory for the current user.

Each endpoint uses `get_current_user`, `X-Room-Token`, and the existing room
membership verifier. Responses expose only the requesting user's promotion
state. Existing room-memory listing remains compatible with room-token-only
callers.

## Frontend

The current room memory panel loads the user's promotion IDs alongside the
existing memory list. Each active memory card shows exactly one action:

- **Promote** when the current user has no grant;
- **Demote** when the current user has a grant.

Only the clicked memory is disabled while its request is pending. A failed
request leaves the prior state intact and displays the error; there is no
optimistic silent fallback. The existing scope label remains the source
memory's scope because personal promotion does not mutate that row.

## Events

Successful first promotion and actual demotion append the corresponding memory
lifecycle event with memory ID, user ID, and source room ID. Idempotent repeats
do not emit duplicate events.

## Verification

Backend tests must prove:

- user A promotion is invisible to user B;
- automatic cross-room recall includes only user A's promoted memories;
- source-room membership is required on writes and reads;
- missing, inactive, and inaccessible memories fail closed;
- promote and demote are idempotent;
- HTTP bearer auth, room token, and membership are enforced.

Frontend verification must include lint and production build. The repository
has no frontend unit-test runner, so browser interaction remains an explicit
activation check rather than adding a new test framework in this tranche.

## Non-goals

- No collection-management UI.
- No global search UI.
- No WebSocket promotion protocol.
- No migration or interpretation of hypothetical legacy global rows.
- No tradingDesk changes.
- No production migration, restart, or frontend flip during implementation.
