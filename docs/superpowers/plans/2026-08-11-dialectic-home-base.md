# Dialectic Home Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a real Home room the default meeting place for Amo, Dan, and Claude, with membership-safe cross-room activity, visible branch genealogy, and one URL-authoritative navigation path.

**Architecture:** Migration `013` creates the unique Home room and nondelegable Home-management capability; a separately reviewed activation transaction adds only Amo and Dan. One `HomeActivityService` performs the database-enforced membership intersection and produces both the authenticated HTTP projection and Claude's compact Home context. The React PWA keeps the existing room-scoped store and shipped mobile drawers, but routes every destination through one hook that owns room/thread loading, URL history, notification entry, revoked-access fallback, and drawer close.

**Tech Stack:** PostgreSQL 16/asyncpg, FastAPI/Pydantic, pytest/pytest-asyncio, React 19, TypeScript 5.9, Zustand 5, Vite 7, existing PWA service worker.

## Selected Implementation Mode

Implement on local `master` in the production checkout. After Task 1 is
committed and verified, apply additive migration `013` to production while the
existing backend still runs, verify the schema bootstrap, and only then land
later `is_home`-dependent backend commits. This early authorization covers the
schema and Home/Main bootstrap only; it does not authorize founder activation,
a service restart, or a frontend release.

## Global Constraints

- The approved behavior is defined in `docs/superpowers/specs/2026-08-11-dialectic-home-base-design.md` at commit `f77ff3a`.
- Migration `013` is additive and idempotent; do not reuse migration `012`.
- Home starts with Amo and Dan only. Both can add existing credentialed users; added users cannot add anyone else.
- Founder activation accepts reviewed email parameters and never infers founders from display names or all credentialed accounts.
- The Home activity source set is the database-enforced intersection of rooms accessible to every current Home member.
- Activity responses and Claude context never contain room tokens or any field from a room outside that intersection.
- Every message-derived activity field excludes `messages.is_deleted = TRUE`.
- `GET /users/me/home/activity` requires a valid access JWT and current Home membership; missing Home and authenticated nonmembership both return `404 Home unavailable`.
- Home remains a normal conversation room for messages, memories, protocols, autonomous interjection, tools, the participation FSM, silence follow-ups, briefs, commitments, replay, and push.
- Home can never acquire `rooms.linked_book_id`: thesis create/draft return `409`, and `propose_thesis` declines with `Propose it in the scheme's room.`
- Trading remains an unconditional right-rail tab. Do not restore the former binding-dependent tab gate.
- Preserve the mobile drawers, scrim, Escape close, and room-change close shipped in `273a42b`; extend them instead of creating another mobile shell.
- Valid popstate re-entry is history-neutral: no `pushState` and no `replaceState`.
- Do not add an activity table, notification-center workflow, frontend unit-test framework, feature flag, native-app work, or tradingDesk change.
- Apply the production migration only at Task 1's explicit early-migration gate. Do not run founder activation, restart services, or flip the frontend release symlink during implementation without a separate explicit production instruction.

---

### Task 1: Unique Home schema and reviewed founder activation

**Files:**
- Create: `dialectic/migrations/013_home_base.sql`
- Create: `dialectic/deploy/activate_home_founders.sql`
- Modify: `dialectic/schema.sql:25-70`
- Modify: `dialectic/models.py:112-168`
- Create: `dialectic/tests/test_home_schema_pg.py`

**Interfaces:**
- Consumes: existing `rooms`, `threads`, `room_memberships`, `events`, `user_credentials`, and existing event strings `room_created`, `thread_created`, and `user_joined`.
- Produces: `rooms.is_home: bool`, `room_memberships.can_manage_home: bool`, one unique Home row, one Home root thread titled `Main`, and a parameterized founder-activation transaction.

- [x] **Step 1: Write the failing schema contract**

```python
from pathlib import Path

from models import EventType, Room, RoomMembership


def test_home_schema_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = (root / "schema.sql").read_text()
    migration = (root / "migrations" / "013_home_base.sql").read_text()
    activation = (root / "deploy" / "activate_home_founders.sql").read_text()

    for sql in (schema, migration):
        assert "is_home BOOLEAN NOT NULL DEFAULT FALSE" in sql
        assert "can_manage_home BOOLEAN NOT NULL DEFAULT FALSE" in sql
        assert "WHERE is_home" in sql

    assert f"'{EventType.ROOM_CREATED.value}'" in migration
    assert f"'{EventType.THREAD_CREATED.value}'" in migration
    assert f"'{EventType.USER_JOINED_ROOM.value}'" in activation

    assert ":'amo_email'" in activation
    assert ":'dan_email'" in activation
    assert "display_name" not in activation
    assert "can_manage_home = TRUE" in activation
    assert Room.model_fields["is_home"].default is False
    assert RoomMembership.model_fields["can_manage_home"].default is False
```

- [x] **Step 2: Run the contract and verify RED**

Run: `cd dialectic && python3 -m pytest tests/test_home_schema_pg.py::test_home_schema_contract -q`

Expected: FAIL because migration `013`, the activation script, and model fields do not exist.

- [x] **Step 3: Add the additive columns, unique index, and idempotent Home bootstrap**

Use this DDL in `013_home_base.sql`, and mirror only the resulting DDL shape in
`schema.sql`. `schema.sql` remains data-free: a database created from it alone
contains zero Home rows. Every environment, including a fresh database, runs
idempotent migration `013` to create Home, its `Main` thread, and their events.

```sql
ALTER TABLE rooms
    ADD COLUMN IF NOT EXISTS is_home BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_single_home
    ON rooms (is_home)
    WHERE is_home;

ALTER TABLE room_memberships
    ADD COLUMN IF NOT EXISTS can_manage_home BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
DECLARE
    home_id UUID;
    main_id UUID;
    created_home BOOLEAN := FALSE;
    created_main BOOLEAN := FALSE;
BEGIN
    SELECT id INTO home_id FROM rooms WHERE is_home;
    IF home_id IS NULL THEN
        home_id := gen_random_uuid();
        INSERT INTO rooms (id, created_at, token, name, is_home)
        VALUES (
            home_id,
            NOW(),
            replace(gen_random_uuid()::text, '-', ''),
            'Home',
            TRUE
        );
        created_home := TRUE;
    END IF;

    SELECT id INTO main_id
    FROM threads
    WHERE room_id = home_id AND parent_thread_id IS NULL
    ORDER BY created_at, id
    LIMIT 1;

    IF main_id IS NULL THEN
        main_id := gen_random_uuid();
        INSERT INTO threads (id, room_id, created_at, title)
        VALUES (main_id, home_id, NOW(), 'Main');
        created_main := TRUE;
    END IF;

    IF created_home THEN
        INSERT INTO events (id, timestamp, event_type, room_id, payload)
        VALUES (gen_random_uuid(), NOW(), 'room_created', home_id,
                jsonb_build_object('name', 'Home'));
    END IF;

    IF created_main THEN
        INSERT INTO events
            (id, timestamp, event_type, room_id, thread_id, payload)
        VALUES (gen_random_uuid(), NOW(), 'thread_created', home_id, main_id,
                jsonb_build_object('title', 'Main'));
    END IF;
END $$;
```

Add `is_home: bool = False` to `Room` and
`can_manage_home: bool = False` to `RoomMembership`. Do not add a room-kind
enum.

- [x] **Step 4: Add the founder activation transaction**

`activate_home_founders.sql` must require two psql variables and abort unless
each normalized email resolves to exactly one distinct credential identity:

```sql
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE home_founder_activation (
    email TEXT PRIMARY KEY,
    user_id UUID
) ON COMMIT DROP;

INSERT INTO home_founder_activation (email, user_id)
SELECT requested.email, uc.user_id
FROM (
    VALUES (lower(trim(:'amo_email'))), (lower(trim(:'dan_email')))
) AS requested(email)
JOIN user_credentials uc ON lower(uc.email) = requested.email;

DO $$
BEGIN
    IF (SELECT count(*) FROM home_founder_activation) <> 2
       OR (SELECT count(DISTINCT user_id) FROM home_founder_activation) <> 2 THEN
        RAISE EXCEPTION 'Founder activation requires exactly two distinct credential identities';
    END IF;
    IF (SELECT count(*) FROM rooms WHERE is_home) <> 1 THEN
        RAISE EXCEPTION 'Founder activation requires exactly one Home room';
    END IF;
END $$;

WITH home AS (
    SELECT id FROM rooms WHERE is_home
), added AS (
    INSERT INTO room_memberships
        (room_id, user_id, joined_at, can_manage_home)
    SELECT home.id, founder.user_id, NOW(), TRUE
    FROM home CROSS JOIN home_founder_activation founder
    ON CONFLICT (room_id, user_id) DO UPDATE
        SET can_manage_home = TRUE
    WHERE NOT room_memberships.can_manage_home
    RETURNING room_id, user_id
)
INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
SELECT gen_random_uuid(), NOW(), 'user_joined', room_id, user_id,
       jsonb_build_object('activation', 'home_founder')
FROM added
WHERE NOT EXISTS (
    SELECT 1 FROM events e
    WHERE e.event_type = 'user_joined'
      AND e.room_id = added.room_id
      AND e.user_id = added.user_id
);

COMMIT;
```

Before implementation accepts this SQL, verify PostgreSQL's `ON CONFLICT ...
WHERE` grammar against the local server with `psql`; if it rejects the shown
form, split existing-founder elevation and missing-membership insertion into
two explicit statements while preserving one event only for newly inserted
memberships. Do not weaken the exact-two-identity guard.

- [x] **Step 5: Add real-Postgres idempotency coverage**

Use `DIALECTIC_TEST_DATABASE_URL` and the existing clean-skip convention. Start
an explicit transaction, execute the migration twice, assert exactly one Home,
one root thread, and no duplicate create events, then roll the transaction back:

```python
@pytest.mark.asyncio
async def test_migration_013_is_idempotent(db) -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "013_home_base.sql"
    ).read_text()
    tx = db.transaction()
    await tx.start()
    try:
        await db.execute(migration)
        await db.execute(migration)
        home_id = await db.fetchval(
            "SELECT id FROM rooms WHERE is_home"
        )
        assert home_id is not None
        assert await db.fetchval(
            "SELECT count(*) FROM rooms WHERE is_home"
        ) == 1
        assert await db.fetchval(
            """SELECT count(*) FROM threads
               WHERE room_id = $1 AND parent_thread_id IS NULL""",
            home_id,
        ) == 1
        assert await db.fetchval(
            """SELECT count(*) FROM events
               WHERE room_id = $1 AND event_type = $2""",
            home_id, EventType.ROOM_CREATED.value,
        ) == 1
    finally:
        await tx.rollback()
```

- [x] **Step 6: Run schema and migration GREEN**

Run: `cd dialectic && python3 -m pytest tests/test_home_schema_pg.py -q`

Expected: PASS, or the real-Postgres case cleanly skips only when the documented test database is unavailable.

- [x] **Step 7: Persist migration 013 in the local test database**

Run: `cd dialectic && psql postgresql://root@localhost/dialectic_test -v ON_ERROR_STOP=1 -f migrations/013_home_base.sql`

Then run: `cd dialectic && psql postgresql://root@localhost/dialectic_test -Atc "SELECT count(*) FROM rooms WHERE is_home"`

Expected: migration succeeds and the count is exactly `1`. Every subsequent
real-Postgres fixture selects that committed Home row and adds its test
memberships/data inside a rollback transaction; no fixture inserts a second
`is_home = TRUE` row.

- [x] **Step 8: Commit the foundation**

```bash
git add dialectic/migrations/013_home_base.sql dialectic/deploy/activate_home_founders.sql dialectic/schema.sql dialectic/models.py dialectic/tests/test_home_schema_pg.py
git commit -m "feat: establish Dialectic Home -- keep founder activation explicit"
```

- [x] **Step 9: Cross the schema-only production migration gate**

This step is authorized immediately after Step 8 passes and the foundation
commit is verified. Before applying anything, confirm the deployed backend is
still the pre-Home build and capture its current service and `/health` state.
Apply committed `migrations/013_home_base.sql` to the production database with
`ON_ERROR_STOP`, without restarting `dialectic.service`.

Verify all of the following directly in PostgreSQL:

- `rooms.is_home` and `room_memberships.can_manage_home` exist with
  `NOT NULL DEFAULT FALSE`;
- `idx_rooms_single_home` exists as a partial unique index;
- exactly one Home room and one root `Main` thread exist;
- the Home room has zero memberships;
- the expected `room_created` and `thread_created` bootstrap events exist once;
- the existing backend remains healthy after the additive migration.

Stop on any mismatch. Do not run `activate_home_founders.sql`, restart the
service, place later backend commits in service, or release frontend assets at
this gate. Record the migration and verification evidence in `JOURNAL.md`
before beginning Task 2.

### Task 2: Home membership administration and ordinary-join denial

**Files:**
- Create: `dialectic/api/home.py`
- Create: `dialectic/deploy/remove_home_member.sql`
- Modify: `dialectic/api/main.py:26-39,160-200,299-326,600-636,2129-2214`
- Modify: `dialectic/models.py:35-65`
- Create: `dialectic/tests/test_home_membership_api.py`
- Modify: `dialectic/tests/test_home_schema_pg.py`
- Modify: `dialectic/tests/test_user_rooms_read_state.py`

**Interfaces:**
- Consumes: Task 1's `is_home` and `can_manage_home`, `get_current_user`, `extract_room_token`, and `EventType.USER_JOINED_ROOM`.
- Produces: `POST /users/me/home/member-candidate`,
  `POST /users/me/home/members`, a reviewed emergency removal script,
  `EventType.HOME_MEMBER_REMOVED`, plus `UserRoomResponse.is_home` and
  `UserRoomResponse.can_manage_home` for the caller's own membership.

- [x] **Step 1: Write failing endpoint contracts**

Use FastAPI dependency overrides and an `AsyncMock` database, following
`tests/test_memory_promotion_api.py`. Cover:

```python
def test_founder_adds_existing_user(client, db) -> None:
    candidate = client.post(
        "/users/me/home/member-candidate",
        headers={"X-Room-Token": "home-token"},
        json={"email": " New.Member@Example.com "},
    )
    assert candidate.status_code == 200
    response = client.post(
        "/users/me/home/members",
        headers={"X-Room-Token": "home-token"},
        json={
            "email": " New.Member@Example.com ",
            "confirmed_user_id": candidate.json()["user_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "added"
    query = db.fetchrow.await_args_list[-1].args[0]
    assert "ON CONFLICT (room_id, user_id) DO NOTHING" in query
    assert "INSERT INTO events" in query
    assert f"'{EventType.USER_JOINED_ROOM.value}'" in query


def test_added_member_cannot_add_another(client_without_capability) -> None:
    response = client_without_capability.post(
        "/users/me/home/members",
        headers={"X-Room-Token": "home-token"},
        json={"email": "target@example.com"},
    )
    assert response.status_code == 403
```

Also assert: missing bearer is 401; bad Home token is 401; current Home
nonmember is 403; unknown email is 404; repeated add returns
`already_member` with no second event; generic `POST /rooms/{home_id}/join`
returns 403 for a nonmember; an existing Home member replaying the generic
join retains the existing `200 {"status": "already_member"}` result; ordinary
room joining still returns its existing result. Candidate lookup requires the
same Home token, membership, and capability as add, returns 404 for an unknown
email, and does not write.

- [x] **Step 2: Run endpoint contracts and verify RED**

Run: `cd dialectic && python3 -m pytest tests/test_home_membership_api.py tests/test_user_rooms_read_state.py -q`

Expected: FAIL because the router, response fields, and Home join denial do not exist.

- [x] **Step 3: Implement the focused Home router**

Create a router with the same pool-injection pattern as `api/thesis_relay.py`:

```python
router = APIRouter(tags=["home"])
_db_pool = None


def set_home_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_db() -> AsyncIterator[asyncpg.Connection]:
    async with _db_pool.acquire() as conn:
        yield conn


class AddHomeMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    confirmed_user_id: UUID


class HomeMemberCandidateResponse(BaseModel):
    user_id: UUID
    display_name: str


class AddHomeMemberResponse(BaseModel):
    user_id: UUID
    display_name: str
    status: Literal["added", "already_member"]
```

The route first selects Home by `is_home` plus token and returns 401 when that
credential does not resolve. It then selects the caller's Home membership and
returns 403 for nonmembership or missing capability before querying the target
email. This two-query order preserves the existing token-versus-membership
error contract. Normalize the target with
`str(request.email).strip().lower()`.

Both routes reuse one `_require_home_manager(token, caller_id, db)` helper.
Candidate lookup returns the one credentialed user's ID and display name but
writes nothing. The add route repeats the normalized-email lookup and requires
its user ID to equal `confirmed_user_id`, preventing an email/account change
between preview and confirmation.

Use one target/add/event statement so idempotency cannot duplicate the event:

```sql
WITH target AS (
    SELECT uc.user_id, u.display_name
    FROM user_credentials uc
    JOIN users u ON u.id = uc.user_id
    WHERE lower(uc.email) = $2 AND uc.user_id = $4
), added AS (
    INSERT INTO room_memberships
        (room_id, user_id, joined_at, can_manage_home)
    SELECT $1, user_id, NOW(), FALSE FROM target
    ON CONFLICT (room_id, user_id) DO NOTHING
    RETURNING user_id
), event_write AS (
    INSERT INTO events
        (id, timestamp, event_type, room_id, user_id, payload)
    SELECT gen_random_uuid(), NOW(), 'user_joined', $1, added.user_id,
           jsonb_build_object('added_by_user_id', $3::text)
    FROM added
)
SELECT target.user_id, target.display_name,
       EXISTS (SELECT 1 FROM added) AS added
FROM target
```

No result means 404. Return `added` or `already_member` from the boolean.

- [x] **Step 4: Mount the router and reject generic Home joins**

Import `router as home_router, set_home_db_pool` in `api/main.py`, inject the
pool during lifespan, and include the router beside the other focused routers.

Change `join_room`'s room lookup to select `is_home`; after token validation,
perform its existing-membership check first. Return its existing
`already_member` response when that row exists. Only a new membership attempt
against Home returns
`HTTPException(403, "Home membership requires a Home administrator")`. Do not
change ordinary room invite semantics.

Extend `UserRoomResponse` and its query:

```python
class UserRoomResponse(BaseModel):
    # existing fields unchanged
    is_home: bool = False
    can_manage_home: bool = False
```

Select `r.is_home` and `rm.can_manage_home`, and project both. Also add
`AND NOT m.is_deleted` to the existing unread, latest-timestamp, and preview
subqueries so the room rail follows the same soft-delete truth as Home.

- [x] **Step 5: Add the reviewed emergency removal path**

Add `HOME_MEMBER_REMOVED = "home_member_removed"` to `EventType`. The psql
script accepts `member_email` and `removed_by_email`, resolves exactly one Home,
requires the remover to be a current `can_manage_home` member, requires the
target to be a current member, and refuses to remove the final Home manager.
Inside one transaction it deletes the target membership and appends
`home_member_removed` with the removed user as `events.user_id` and the remover
ID in payload. It never deletes the user, Home, messages, memories, or events.

Extend `test_home_schema_pg.py` to assert the script contains
`EventType.HOME_MEMBER_REMOVED.value`, the manager guard, and the final-manager
guard. Rehearse it only on `dialectic_test`: create unique test credentials,
add the target to the committed Home, run the script with explicit `-v`
arguments, assert the target's Home membership is gone and its activity request
would resolve to `HomeUnavailable`, assert a source room that was excluded only
because the target lacked membership becomes eligible again for the remaining
members, then remove the test users and their non-Home fixture data.

- [x] **Step 6: Run focused GREEN**

Run: `cd dialectic && python3 -m pytest tests/test_home_membership_api.py tests/test_user_rooms_read_state.py tests/test_signup_guard.py -q`

Expected: PASS.

- [x] **Step 7: Commit membership administration**

```bash
git add dialectic/api/home.py dialectic/deploy/remove_home_member.sql dialectic/api/main.py dialectic/models.py dialectic/tests/test_home_membership_api.py dialectic/tests/test_home_schema_pg.py dialectic/tests/test_user_rooms_read_state.py
git commit -m "feat: administer Home membership -- keep authority nondelegable"
```

### Task 3: Prevent Home from entering the thesis lifecycle

**Files:**
- Modify: `dialectic/api/thesis_relay.py:70-190`
- Modify: `dialectic/llm/tools.py:690-728`
- Modify: `dialectic/tests/test_thesis_relay_endpoint.py`
- Modify: `dialectic/tests/test_tools_registry.py:885-941`

**Interfaces:**
- Consumes: `Room.is_home` from Task 1.
- Produces: identical `409` guards on thesis create/draft and a failed `propose_thesis` tool trace in Home.

- [ ] **Step 1: Write failing create, draft, and tool tests**

Extend the thesis-relay fake room row with `is_home`. Add:

```python
def test_home_create_is_409_before_any_side_effect(monkeypatch) -> None:
    fake_db = _make_db(is_home=True)
    service_post, post = AsyncMock(), AsyncMock()
    response = _create(
        fake_db, monkeypatch, service_post=service_post, post=post
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Propose it in the scheme's room."
    service_post.assert_not_awaited()
    post.assert_not_awaited()
    fake_db.execute.assert_not_awaited()


def test_home_draft_is_409_before_drafter(monkeypatch) -> None:
    fake_db = _make_db(is_home=True)
    drafter = AsyncMock()
    response = _draft(fake_db, monkeypatch, drafter=drafter)
    assert response.status_code == 409
    assert response.json()["detail"] == "Propose it in the scheme's room."
    drafter.assert_not_awaited()
```

In `TestProposeThesis`, make `_tool` accept `is_home` and assert Home raises
`ValueError` matching `Propose it in the scheme's room.` Ordinary unbound room
proposal tests must remain unchanged.

- [ ] **Step 2: Run the guards and verify RED**

Run: `cd dialectic && python3 -m pytest tests/test_thesis_relay_endpoint.py tests/test_tools_registry.py -q`

Expected: the new Home cases FAIL.

- [ ] **Step 3: Implement the guards at the first authorized boundary**

Both relay queries must select `is_home`. Preserve existing token and
membership checks, then run this before the linked-book and title checks:

```python
if row["is_home"]:
    raise HTTPException(
        status_code=409,
        detail="Propose it in the scheme's room.",
    )
```

At the top of the `propose_thesis` executor, before linked-book and input
validation:

```python
if getattr(room, "is_home", False):
    raise ValueError("Propose it in the scheme's room.")
```

- [ ] **Step 4: Run focused GREEN**

Run: `cd dialectic && python3 -m pytest tests/test_thesis_relay_endpoint.py tests/test_tools_registry.py tests/test_orchestrator_tools.py -q`

Expected: PASS, including the existing ordinary-room create/draft/proposal contracts.

- [ ] **Step 5: Commit the lifecycle boundary**

```bash
git add dialectic/api/thesis_relay.py dialectic/llm/tools.py dialectic/tests/test_thesis_relay_endpoint.py dialectic/tests/test_tools_registry.py
git commit -m "fix: keep Home outside thesis lifecycle -- preserve room creation flow"
```

### Task 4: Membership-intersection activity projection

**Files:**
- Create: `dialectic/home_activity.py`
- Modify: `dialectic/llm/briefing.py:57-82,208`
- Create: `dialectic/tests/test_home_activity_pg.py`

**Interfaces:**
- Consumes: Home schema, `messages`, `threads`, `message_receipts`, `room_memberships`, `users`, and `commitments`.
- Produces: `HomeActivityService.build(viewer_user_id: UUID) -> HomeActivityProjection`, `HomeActivityProjection.to_prompt_section(max_chars: int = 12000) -> str`, and `HomeUnavailable`.

- [ ] **Step 1: Define response models and failing real-Postgres cases**

Define these Pydantic models in `home_activity.py` so the service, FastAPI, and
prompt formatter share one contract:

```python
class HomeActivityBranch(BaseModel):
    id: UUID
    parent_thread_id: Optional[UUID]
    title: Optional[str]
    depth: int
    message_count: int
    unread_count: int
    last_message_at: Optional[datetime]


class HomeActivityQuestion(BaseModel):
    thread_id: UUID
    speaker: str
    content_preview: str
    timestamp: datetime


class HomeActivityCommitment(BaseModel):
    id: UUID
    claim: str
    deadline: datetime
    category: str


class HomeActivityRoom(BaseModel):
    id: UUID
    name: Optional[str]
    last_message_at: Optional[datetime]
    last_speaker: Optional[str]
    last_message_preview: Optional[str]
    unread_count: int
    branches: list[HomeActivityBranch]
    unresolved_questions: list[HomeActivityQuestion]
    commitments_due: list[HomeActivityCommitment]


class HomeActivityProjection(BaseModel):
    generated_at: datetime
    rooms: list[HomeActivityRoom]
```

In `test_home_activity_pg.py`, use a transaction-scoped fixture and
deterministic UUIDs. Select the one Home committed to `dialectic_test` by Task
1, add Amo and Dan test memberships inside the fixture transaction, then create
one shared room, one Amo-only room, branches, read receipts, active
commitments, questions, and a soft-deleted newest message. Write failing tests
proving:

1. only the shared room appears;
2. adding a third Home member immediately removes it;
3. no serialized projection contains `token`;
4. unread counts and boundaries differ by viewer;
5. unresolved questions legitimately differ when the viewer boundary differs;
6. the deleted newest message affects no preview, timestamp, count, unread, or unresolved-question result;
7. only active commitments due within 72 hours appear;
8. branch parent/depth metadata survives ordering;
9. the prompt rendering is capped and names its viewer-derived lineage.

- [ ] **Step 2: Run the projection tests and verify RED**

Run: `cd dialectic && python3 -m pytest tests/test_home_activity_pg.py -q`

Expected: FAIL because `home_activity.py` does not exist.

- [ ] **Step 3: Reuse the existing unresolved-question heuristic**

Rename `llm.briefing._unanswered_questions` to
`unanswered_questions` and update its existing caller. Keep its current
different-speaker/later-message semantics. Import that function from
`home_activity.py`; do not fork a second question-resolution definition.

- [ ] **Step 4: Implement the authorization and source-set CTE**

`HomeActivityService.__init__(db)` stores the current asyncpg connection.
`build` owns its snapshot:

```python
async with self.db.transaction(
    isolation="repeatable_read",
    readonly=True,
):
    # authorize, compute eligible IDs, and run only ID-fenced reads here
```

Both current consumers pass a standalone acquired connection rather than an
outer transaction, so the isolation level is explicit instead of degrading to
a nested savepoint. Inside that snapshot, first verify Home membership without
exposing Home metadata:

```sql
SELECT r.id
FROM rooms r
JOIN room_memberships rm
  ON rm.room_id = r.id AND rm.user_id = $1
WHERE r.is_home
```

No row raises `HomeUnavailable`. Run projection assembly inside one read-only
`REPEATABLE READ` transaction. The exact membership-intersection query produces
the eligible room ID set:

```sql
WITH home_members AS (
    SELECT rm.user_id
    FROM room_memberships rm
    WHERE rm.room_id = $2
), eligible_rooms AS (
    SELECT r.id, r.name, viewer_rm.joined_at
    FROM rooms r
    JOIN room_memberships viewer_rm
      ON viewer_rm.room_id = r.id AND viewer_rm.user_id = $1
    WHERE NOT r.is_home
      AND NOT EXISTS (
          SELECT 1
          FROM home_members hm
          WHERE NOT EXISTS (
              SELECT 1
              FROM room_memberships source_rm
              WHERE source_rm.room_id = r.id
                AND source_rm.user_id = hm.user_id
          )
      )
)
SELECT id, name, joined_at FROM eligible_rooms
```

Every subsequent content read in that same snapshot is parameterized by the
returned UUID array (`WHERE room_id = ANY($n::uuid[])` or an equivalent join to
`unnest($n::uuid[])`). No later query may rediscover rooms by broader viewer
membership. A single set-based statement is allowed when it meets the measured
target, but is not required; the privacy invariant is the exact intersection
plus eligible-ID fencing on every read.

- [ ] **Step 5: Implement exact receipt, deletion, and ordering semantics**

For every room, derive the viewer boundary as the latest room-scoped `read`
receipt, falling back to `eligible_rooms.joined_at`. All message subqueries use
`AND NOT m.is_deleted`. Unread predicates also use:

```sql
m.created_at > boundary.read_at
AND (m.user_id IS NULL OR m.user_id <> $1)
```

Cap activity-window rows before restoring chronological order:

```sql
SELECT * FROM (
    SELECT m.id, m.thread_id, m.created_at, m.message_type, m.content,
           m.user_id, m.speaker_type,
           COALESCE(u.display_name, m.speaker_type) AS sender_name
    FROM messages m
    JOIN threads t ON t.id = m.thread_id
    LEFT JOIN users u ON u.id = m.user_id
    WHERE t.room_id = er.id
      AND NOT m.is_deleted
      AND m.created_at > boundary.read_at
    ORDER BY m.created_at DESC
    LIMIT 100
) windowed
ORDER BY created_at
```

Use `unanswered_questions` on these chronological rows. Sort rooms with unread
first and then by latest activity descending; sort branches by latest activity
while retaining `parent_thread_id` and `depth`. Do not include raw window
messages in `HomeActivityProjection`.

- [ ] **Step 6: Add the compact prompt formatter**

`to_prompt_section` renders a nonce-delimited data section containing
`generated_at`, room names, unread counts, latest previews, changed branches,
unresolved questions, and due commitments. It appends whole room blocks until
the next block would exceed `max_chars`, then appends
`[Home activity truncated at 12000 characters]`. Treat the projection as data,
not instructions, matching `_build_trading_context`'s injection-defense stance.

- [ ] **Step 7: Run real-Postgres GREEN**

Run: `cd dialectic && python3 -m pytest tests/test_home_activity_pg.py tests/test_night_shift.py -q`

Expected: PASS. A skip is acceptable only when the test database is unavailable;
do not report SQL semantics verified from a skipped run.

- [ ] **Step 8: Measure and tune before adding consumers**

Inside the Postgres test suite, seed a deterministic production-scale fixture
with seed `20260811`: the committed Home, two Home members, 25 eligible source
rooms, 100 branches, 100 nondeleted window messages per room, receipts, and due
commitments. Print the seed. Capture
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for each service query, then time 20
warm `HomeActivityService.build` calls and assert p95 <= 150 ms.

Add an index only when the plan identifies its scan. If indexing alone does not
meet the target, split correlated work into bounded set-based reads within the
same eligible-ID-fenced transaction. A final sanctioned fallback is a <=5
second in-process cache keyed by `(viewer_user_id,
ordered_current_home_member_ids)` after a fresh Home-membership query; a
membership change therefore changes the key before any cached content can be
returned. Do not add an activity table.

- [ ] **Step 9: Prove repeatability on the persistent test schema**

Run: `cd dialectic && python3 -m pytest tests/test_home_activity_pg.py -q && python3 -m pytest tests/test_home_activity_pg.py -q`

Then run: `cd dialectic && psql postgresql://root@localhost/dialectic_test -Atc "SELECT count(*) FROM rooms WHERE is_home"`

Expected: both runs PASS without cleanup and the Home count remains exactly
`1`.

- [ ] **Step 10: Commit the projection**

```bash
git add dialectic/home_activity.py dialectic/llm/briefing.py dialectic/tests/test_home_activity_pg.py
git commit -m "feat: project shared Home activity -- intersect every membership"
```

### Task 5: Authenticated activity endpoint and Claude Home context

**Files:**
- Modify: `dialectic/api/home.py`
- Modify: `dialectic/llm/orchestrator.py:113-161,345-385,595-629,740-765`
- Modify: `dialectic/llm/prompts.py:87-230`
- Create: `dialectic/tests/test_home_activity_api.py`
- Create: `dialectic/tests/test_home_prompt.py`

**Interfaces:**
- Consumes: `HomeActivityService` from Task 4.
- Produces: `GET /users/me/home/activity`, `HOME_ACTIVITY_UNAVAILABLE`, and a Home-only `home_activity_context` prompt layer.

- [ ] **Step 1: Write failing HTTP authorization tests**

Follow the dependency-override pattern used by other focused routers. Assert:

```python
def test_activity_requires_bearer_auth(client_without_auth) -> None:
    assert client_without_auth.get("/users/me/home/activity").status_code == 401


def test_activity_returns_projection_without_tokens(
    client, monkeypatch
) -> None:
    fake_service = SimpleNamespace(
        build=AsyncMock(return_value=PROJECTION)
    )
    monkeypatch.setattr(
        home_mod,
        "HomeActivityService",
        lambda _db: fake_service,
    )
    response = client.get("/users/me/home/activity")
    assert response.status_code == 200
    assert "token" not in response.text.lower()
    fake_service.build.assert_awaited_once_with(CALLER_ID)


def test_nonmember_and_missing_home_are_indistinguishable(
    nonmember_client, missing_home_client
) -> None:
    nonmember = nonmember_client.get("/users/me/home/activity")
    missing = missing_home_client.get("/users/me/home/activity")
    assert (nonmember.status_code, nonmember.json()) == (
        404, {"detail": "Home unavailable"}
    )
    assert (missing.status_code, missing.json()) == (
        nonmember.status_code, nonmember.json()
)
```

The test module imports `api.home as home_mod` and monkeypatches the constructor
there, matching the endpoint's deliberate inline service construction. Do not
invent a FastAPI service dependency used only by tests.

- [ ] **Step 2: Add the endpoint and verify HTTP GREEN**

Implement:

```python
@router.get(
    "/users/me/home/activity",
    response_model=HomeActivityProjection,
)
async def get_home_activity(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
) -> HomeActivityProjection:
    try:
        return await HomeActivityService(db).build(current_user.user_id)
    except HomeUnavailable:
        raise HTTPException(status_code=404, detail="Home unavailable")
```

Run: `cd dialectic && python3 -m pytest tests/test_home_activity_api.py -q`

Expected: PASS.

- [ ] **Step 3: Write failing prompt-path tests**

Test `PromptBuilder.build` directly and the orchestrator helper with mocked
service output. Prove:

- Home primary and forced-response prompts contain `## Shared Home Activity`;
- Home streaming primary prompts contain the same section;
- normal rooms contain no Home section;
- Home provoker and protocol prompts contain no Home section;
- a projection error produces the exact `HOME_ACTIVITY_UNAVAILABLE` marker;
- a projection call that exceeds two seconds produces the same marker and does
  not cancel the Home conversation turn;
- the marker says Claude must not claim the digest is current;
- the most recent human message's `user_id` is passed as the viewer.

- [ ] **Step 4: Add one explicit orchestrator helper**

In `orchestrator.py`:

```python
HOME_ACTIVITY_UNAVAILABLE = (
    "[HOME ACTIVITY UNAVAILABLE — do not claim this digest is current]"
)


async def _get_home_activity_context(
    self,
    room: Room,
    messages: list[Message],
    *,
    include: bool,
) -> Optional[str]:
    if not room.is_home or not include:
        return None
    viewer_id = next(
        (
            message.user_id
            for message in reversed(messages)
            if message.speaker_type == SpeakerType.HUMAN and message.user_id
        ),
        None,
    )
    if viewer_id is None:
        return HOME_ACTIVITY_UNAVAILABLE
    try:
        projection = await asyncio.wait_for(
            HomeActivityService(self.db).build(viewer_id),
            timeout=2.0,
        )
        return projection.to_prompt_section()
    except Exception:
        logger.exception("Home activity context unavailable")
        return HOME_ACTIVITY_UNAVAILABLE
```

Call it before prompt assembly in all three orchestrator paths. Pass
`include=not decision.use_provoker and protocol is None` in `on_message`,
`include=not use_provoker and protocol is None` in `force_response`, and
`include=not use_provoker` in `stream_response`.

- [ ] **Step 5: Add the prompt layer without disturbing existing layers**

Extend `PromptBuilder.build` with
`home_activity_context: Optional[str] = None`. After this-room shared memory and
before personal cross-session memory, append:

```python
if home_activity_context:
    system_parts.append(
        f"\n\n## Shared Home Activity\n{home_activity_context}"
    )
```

Pass the helper result at the three existing `prompt_builder.build` call sites.
Do not add an `is_home` condition anywhere else in participation, protocol,
tool, FSM, briefing, or sweep logic.

- [ ] **Step 6: Run all Home/LLM focused tests**

Run: `cd dialectic && python3 -m pytest tests/test_home_activity_api.py tests/test_home_prompt.py tests/test_prompts.py tests/test_orchestrator_tools.py tests/test_participation_fsm.py tests/test_night_shift.py tests/test_scheduler.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the two-consumer contract**

```bash
git add dialectic/api/home.py dialectic/llm/orchestrator.py dialectic/llm/prompts.py dialectic/tests/test_home_activity_api.py dialectic/tests/test_home_prompt.py
git commit -m "feat: share Home pulse with Claude -- mark unavailable context"
```

### Task 6: One URL-authoritative room and branch navigation hook

**Files:**
- Create: `dialectic/frontend/app/src/hooks/useRoomNavigation.ts`
- Create: `dialectic/frontend/app/src/components/auth/RoomAccess.tsx`
- Create: `dialectic/frontend/app/src/components/auth/RoomAccess.css`
- Modify: `dialectic/frontend/app/src/types/index.ts:1-165`
- Modify: `dialectic/frontend/app/src/lib/api.ts:75-110`
- Modify: `dialectic/frontend/app/src/components/auth/RoomSelector.tsx`
- Modify: `dialectic/frontend/app/src/App.tsx:48-612`
- Modify: `dialectic/frontend/app/src/hooks/useDialecticSocket.ts:350-385`
- Modify: `dialectic/frontend/app/src/components/layout/AppLayout.tsx:18-35`

**Interfaces:**
- Consumes: `GET /users/me/rooms`, existing room tokens, `GET /rooms/{id}/threads`, Zustand room actions, and the shipped `mobileDrawer` state.
- Produces: `navigate(destination: RoomDestination, historyMode?: HistoryMode) -> Promise<boolean>` and one shared Create/Join surface.

- [ ] **Step 1: Add exact frontend navigation types and API calls**

```typescript
export interface UserRoom {
  // existing fields unchanged
  is_home: boolean;
  can_manage_home: boolean;
}

export interface Room {
  // existing fields unchanged
  is_home: boolean;
}

export type HistoryMode = 'push' | 'replace' | 'none';

export interface RoomDestination {
  roomId: string | null;
  threadId?: string | null;
}
```

Type `api.getRooms(): Promise<UserRoom[]>` and
`api.getThreads(roomId): Promise<Thread[]>`. Keep room tokens confined to the
saved-room result and request header path.

- [ ] **Step 2: Implement URL parsing and formatting as pure functions**

In `useRoomNavigation.ts`:

```typescript
export function destinationFromLocation(location: Location): {
  roomId: string | null;
  threadId: string | null;
} {
  const params = new URLSearchParams(location.search);
  return {
    roomId: params.get('room'),
    threadId: params.get('thread'),
  };
}

function destinationUrl(room: UserRoom, thread: Thread): string {
  const rootHome = room.is_home && thread.parent_thread_id === null;
  if (rootHome) return '/';
  const params = new URLSearchParams({ room: room.id });
  if (thread.parent_thread_id !== null) params.set('thread', thread.id);
  return `/?${params.toString()}`;
}
```

An ordinary room root uses `/?room=<id>`. A Home branch includes both Home's
room ID and its thread ID; only Home's root canonicalizes to `/`.

A null `roomId` is not an error: it is the canonical Home-root destination and
resolves to the one `is_home` descriptor after saved rooms have loaded. A
non-null unknown room is not classified as denied until that load has completed.

- [ ] **Step 3: Implement the single navigation transaction**

The hook owns `rooms`, `loading`, `error`, `refreshRooms`, and `navigate`. Use a
monotonic attempt ref so a slower earlier fetch cannot overwrite a later tap.
Keep the current rooms-load promise in a ref; `navigate` awaits it when loading
is in progress, so early popstate and notification events queue behind room
resolution rather than taking an error fallback.
Within `navigate`:

1. resolve null `roomId` to the one Home descriptor; otherwise resolve the room
   only from `rooms` and require its token;
2. set the API room token;
3. reuse current `threads` only for the same room, otherwise fetch them;
4. validate `threadId` belongs to the destination room, otherwise use the
   oldest root thread;
5. call `setRoom` only when the room changes, then `setThreads` and `setThread`;
6. apply `pushState`, `replaceState`, or no history mutation from
   `historyMode`;
7. close `mobileDrawer` only after successful state installation;
8. on 401/403/404, remove the invalid destination, replace to Home, show the
   access error, and use the full selector only if Home is also unavailable.

The public signature is:

```typescript
async function navigate(
  destination: RoomDestination,
  historyMode: HistoryMode = 'push',
): Promise<boolean>
```

When installing a room in Zustand, copy `is_home` from the saved-room
descriptor into `Room`; do not re-derive Home from its name or URL.

The hook also exposes:

```typescript
async function enterGrantedRoom(
  granted: Pick<UserRoom, 'id' | 'name' | 'token'>,
): Promise<boolean>
```

For JWT-backed create/join, this refreshes `GET /users/me/rooms` and then calls
`navigate`. For the existing access-token-empty guest path, it inserts a local
descriptor with `is_home: false`, `can_manage_home: false`, zero unread state,
and the granted token, then calls the same `navigate` transaction. This
preserves guest invite/create without giving the navigation hook an alternate
state-installation path.

- [ ] **Step 4: Centralize initial, notification, and popstate entry**

After the saved-room list loads:

- an explicit `room`/`thread` URL calls `navigate(destination, 'none')`;
- a bare URL calls Home's root with `'none'`, regardless of persisted room;
- invalid explicit state shows the error then calls Home with `'replace'`;
- the `popstate` listener queues behind any in-flight rooms load, then calls
  `navigate(parsedDestination, 'none')` and never writes history;
- a live service-worker `open-room` message calls `navigate({roomId}, 'push')`;
- a cold notification URL enters through the initial `'none'` path.

Delete `switchRoomRef` and the one-shot effect that erases `?room=` from
`App.tsx`.

Add `AuthenticatedWorkspace` above `ChatLayout` in `App.tsx`. It owns
`useRoomNavigation`, does not mount `ChatLayout` until the hook has installed a
definitive `currentRoom`, `roomToken`, and `currentThread`, and renders an
explicit loading shell during saved-room resolution. Therefore
`useDialecticSocket` and every room-scoped hydration effect remain inside a
non-null `ChatLayout` and cannot open a socket or issue room reads for the
persisted room while a bare URL is resolving to Home.

If the caller has no Home membership and no usable persisted or explicit room,
`AuthenticatedWorkspace` renders the full-screen `RoomAccess`. Preserve the
existing access-token-empty guest path: it goes directly to that invite surface
and never calls the Home activity endpoint. `App` renders
`AuthenticatedWorkspace` for every authenticated identity instead of branching
on `currentRoom` itself.

Convert every existing competing state writer as part of this step:

- cross-branch search jumps call
  `navigate({roomId: currentRoom.id, threadId: result.thread_id}, 'push')`;
- delete the `threads[0]` fallback effect because successful navigation always
  installs a root or validated requested thread;
- remove the hydration effect's `leaveRoom()` ejection and its duplicate
  `getThreads`; revocation and thread loading belong only to `navigate`;
- ignore the persisted room during boot until `AuthenticatedWorkspace` marks
  navigation ready;
- change `useDialecticSocket`'s `thread_forked` handling to add the returned
  thread without selecting it directly, then invoke a callback supplied by
  `ChatLayout` that navigates to the new branch with push history;
- route header-select, right-panel, rail, Home-pulse, and branch-tree selection
  through `navigate`; no component calls `setRoom`, `setThread`, or `leaveRoom`
  to express a destination.

- [ ] **Step 5: Extract one Create/Join surface**

Move the existing create and invite-code join forms into `RoomAccess.tsx` with:

```typescript
interface RoomAccessProps {
  mode: 'screen' | 'dialog';
  rooms: UserRoom[];
  onRoomSelect: (destination: RoomDestination) => Promise<boolean>;
  onRoomGranted: (
    room: Pick<UserRoom, 'id' | 'name' | 'token'>,
  ) => Promise<boolean>;
  onClose?: () => void;
}
```

Saved-room selection calls `onRoomSelect`. After create or join succeeds, pass
the returned or parsed room ID/token/name to `onRoomGranted`; the hook performs
the JWT refresh or guest descriptor insertion and navigation. Do not write
Zustand room/thread state inside the form.
`RoomSelector` becomes the terminal `mode="screen"` wrapper. `ChatLayout`
opens `mode="dialog"` from the rail `+` action without calling `leaveRoom()`.
Retain the existing full-screen selector for no-Home/no-room recovery.

- [ ] **Step 6: Fold drawer close into navigation**

Remove only the `currentRoomId` close effect from `AppLayout.tsx`. Keep its
Escape listener and scrim unchanged. The hook's successful destination path is
now the sole destination-driven drawer close, including branch changes within
the same room.

- [ ] **Step 7: Run compile and lint**

Run: `cd dialectic/frontend/app && npm run build`

Run: `cd dialectic/frontend/app && npm run lint`

Expected: both PASS. Browser behavior is verified in Task 9; do not claim
history correctness from compilation.

Run:

```bash
rg -n "setRoom\(|setThread\(|leaveRoom\(" \
  dialectic/frontend/app/src/App.tsx \
  dialectic/frontend/app/src/components \
  dialectic/frontend/app/src/hooks/useDialecticSocket.ts
```

Review every match. Destination changes may remain only in
`useRoomNavigation`; socket state hydration may add thread records but may not
select a destination. Store action definitions are not call sites.

- [ ] **Step 8: Commit navigation consolidation**

```bash
git add dialectic/frontend/app/src/hooks/useRoomNavigation.ts dialectic/frontend/app/src/components/auth/RoomAccess.tsx dialectic/frontend/app/src/components/auth/RoomAccess.css dialectic/frontend/app/src/types/index.ts dialectic/frontend/app/src/lib/api.ts dialectic/frontend/app/src/components/auth/RoomSelector.tsx dialectic/frontend/app/src/App.tsx dialectic/frontend/app/src/hooks/useDialecticSocket.ts dialectic/frontend/app/src/components/layout/AppLayout.tsx
git commit -m "feat: make room navigation singular -- preserve URL destinations"
```

### Task 7: Shared branch tree, pinned Home, and responsive header

**Files:**
- Modify: `dialectic/api/main.py:639-735`
- Modify: `dialectic/tests/test_home_activity_pg.py`
- Create: `dialectic/frontend/app/src/components/sidebar/BranchTree.tsx`
- Create: `dialectic/frontend/app/src/components/sidebar/BranchTree.css`
- Modify: `dialectic/frontend/app/src/types/index.ts`
- Modify: `dialectic/frontend/app/src/lib/api.ts`
- Modify: `dialectic/frontend/app/src/App.tsx:411-514`
- Modify: `dialectic/frontend/app/src/components/sidebar/RoomList.tsx`
- Modify: `dialectic/frontend/app/src/components/sidebar/RoomList.css`
- Modify: `dialectic/frontend/app/src/components/sidebar/ThreadPanel.tsx`
- Modify: `dialectic/frontend/app/src/components/layout/RoomHeader.tsx`
- Modify: `dialectic/frontend/app/src/components/layout/RoomHeader.css`

**Interfaces:**
- Consumes: existing `GET /rooms/{room_id}/genealogy`, Task 6's `navigate`, and current `ThreadNodeResponse` JSON.
- Produces: one recursive `BranchTree` used in both the room rail/drawer and Branches panel.

- [ ] **Step 1: Align thread counts with soft-delete truth**

Add `AND NOT m.is_deleted` to the `message_count` subqueries in both
`list_threads` and `get_thread_genealogy`. Extend the Postgres fixture to
soft-delete one message in a fork, call the genealogy endpoint and
`HomeActivityService.build`, and assert both surfaces return the same branch
count.

- [ ] **Step 2: Add the genealogy contract**

```typescript
export interface ThreadNode {
  id: string;
  parent_thread_id: string | null;
  fork_point_message_id: string | null;
  title: string | null;
  message_count: number;
  created_at: string;
  depth: number;
  children: ThreadNode[];
}
```

Add:

```typescript
async getGenealogy(roomId: string): Promise<ThreadNode[]> {
  return this.fetch(`/rooms/${roomId}/genealogy`);
}
```

Fetch genealogy when the current room changes and after `threads` gains a new
fork. Preserve the active transcript and expose a retry state if the genealogy
read fails.

- [ ] **Step 3: Build one recursive tree component**

```typescript
interface BranchTreeProps {
  nodes: ThreadNode[];
  activeThreadId: string | null;
  onSelect: (threadId: string) => void;
  compact?: boolean;
}
```

Render a semantic nested list. Each row shows title, fork marker for nonroots,
and message count. Use `node.depth` for a bounded indentation custom property;
do not flatten `children`. A row click calls the supplied navigation callback.

- [ ] **Step 4: Pin Home and expand only the active room**

`RoomList` receives `genealogy` and `onThreadSelect`. Partition rooms into the
single `is_home` row and ordinary rooms; render Home under a `Home` label, then
ordinary rooms under `Rooms`. Render `BranchTree compact` only beneath the
active room. Keep unread badges and previews on room rows.

Because the same `RoomList` is already the content of the shipped mobile
navigation drawer, this change extends that drawer automatically; do not add a
second drawer.

- [ ] **Step 5: Replace flat Branches rendering**

Change `ThreadPanel` to accept `ThreadNode[]` and render the same `BranchTree`
above its existing “Fork from last message” action. Keep the active branch and
fork action behavior.

- [ ] **Step 6: Make the header a real breadcrumb and collapse labeled icons**

Render `Room / Branch` using the selected thread title, while retaining the
select as the keyboard-friendly fallback. Route select changes through Task
6's navigation callback.

At widths below 600px, hide the visible text for Protocol and Help but keep
their icons, `title`, and explicit `aria-label`; keep the room and context
drawer toggles. Ensure the room and branch labels truncate independently
instead of pushing the drawer toggles offscreen.

Add `onHomeClick` to `RoomHeader`. When the current room is not Home, render a
compact labeled Home action before the room/branch breadcrumb; at narrow widths
its house icon remains with `aria-label="Go Home"`. It calls Task 6's navigator
with Home's root destination and default push history. Hide the action while
already on Home.

- [ ] **Step 7: Run backend and frontend gates**

Run: `cd dialectic && python3 -m pytest tests/test_home_activity_pg.py -q`

Run: `cd dialectic/frontend/app && npm run lint && npm run build`

Expected: PASS.

- [ ] **Step 8: Commit genealogy and responsive navigation**

```bash
git add dialectic/api/main.py dialectic/tests/test_home_activity_pg.py dialectic/frontend/app/src/components/sidebar/BranchTree.tsx dialectic/frontend/app/src/components/sidebar/BranchTree.css dialectic/frontend/app/src/types/index.ts dialectic/frontend/app/src/lib/api.ts dialectic/frontend/app/src/App.tsx dialectic/frontend/app/src/components/sidebar/RoomList.tsx dialectic/frontend/app/src/components/sidebar/RoomList.css dialectic/frontend/app/src/components/sidebar/ThreadPanel.tsx dialectic/frontend/app/src/components/layout/RoomHeader.tsx dialectic/frontend/app/src/components/layout/RoomHeader.css
git commit -m "feat: expose room genealogy -- extend the shipped drawers"
```

### Task 8: Home pulse, Home settings, and unconditional Trading behavior

**Files:**
- Create: `dialectic/frontend/app/src/components/home/HomeActivityPulse.tsx`
- Create: `dialectic/frontend/app/src/components/home/HomeActivityPulse.css`
- Create: `dialectic/frontend/app/src/components/home/HomeSettingsPanel.tsx`
- Create: `dialectic/frontend/app/src/components/home/HomeSettingsPanel.css`
- Modify: `dialectic/frontend/app/src/types/index.ts`
- Modify: `dialectic/frontend/app/src/lib/api.ts`
- Modify: `dialectic/frontend/app/src/App.tsx:411-537`
- Modify: `dialectic/frontend/app/src/components/sidebar/RightPanel.tsx`
- Modify: `dialectic/frontend/app/src/components/trading/TradingPanel.tsx:504-544`
- Modify: `dialectic/frontend/app/src/components/trading/TradingPanel.css`

**Interfaces:**
- Consumes: Task 5's activity endpoint, Task 2's membership endpoint, Task 6's `navigate`, and `UserRoom.is_home/can_manage_home`.
- Produces: a read-only Home pulse, Home member-add settings, and an explanatory Home Trading empty state.

- [ ] **Step 1: Add exact frontend activity types and API methods**

Mirror Task 4's JSON models as `HomeActivityProjection`,
`HomeActivityRoom`, `HomeActivityBranch`, `HomeActivityQuestion`, and
`HomeActivityCommitment`. Add:

```typescript
async getHomeActivity(): Promise<HomeActivityProjection> {
  return this.fetch('/users/me/home/activity');
}

async resolveHomeMember(email: string): Promise<{
  user_id: string;
  display_name: string;
}> {
  return this.fetch('/users/me/home/member-candidate', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

async addHomeMember(
  email: string,
  confirmedUserId: string,
): Promise<{
  user_id: string;
  display_name: string;
  status: 'added' | 'already_member';
}> {
  return this.fetch('/users/me/home/members', {
    method: 'POST',
    body: JSON.stringify({
      email,
      confirmed_user_id: confirmedUserId,
    }),
  });
}
```

The existing auth helper carries the current Home room token for member-add;
the activity call ignores room token server-side and authorizes from JWT plus
Home membership.

- [ ] **Step 2: Implement the pulse's refresh state machine**

`HomeActivityPulse` receives:

```typescript
interface HomeActivityPulseProps {
  onNavigate: (destination: RoomDestination) => Promise<boolean>;
  refreshVersion: number;
}
```

Maintain `snapshot`, `error`, `loading`, `collapsed`, and one in-flight promise
ref. Refresh on mount/Home entry, `visibilitychange` to visible, manual Retry,
and every 60 seconds while visible. If a refresh fails after success, retain
the snapshot and show `Stale — <error>` plus Retry. If the first refresh fails,
show the error without covering transcript or composer.

Also refresh when `refreshVersion` changes. `ChatLayout` increments that value
after `HomeSettingsPanel` successfully adds an existing user, so the displayed
intersection contracts immediately instead of waiting for the next interval.

Render capped room cards ordered as received. A room-card tap navigates to its
root; a changed-branch tap navigates to `{roomId, threadId}`. Do not mark source
messages read and do not add dismiss/archive/mute controls.

- [ ] **Step 3: Render the pulse only in Home**

In `ChatLayout`, derive `currentRoomMeta` from the saved-room list. Insert
`HomeActivityPulse` above `RoomBriefing` only when
`currentRoomMeta.is_home`. Ordinary room center columns remain unchanged.

- [ ] **Step 4: Replace Home Share with nondelegable settings**

`HomeSettingsPanel` accepts `canManageHome` and
`onMembershipChanged: () => void`. When true, render one normalized email field
and resolve it through `api.resolveHomeMember`. Show the returned display name
and email in a confirmation state; only the explicit Confirm action calls
`api.addHomeMember(email, candidate.user_id)`. Show `Added <name>` or `<name> is
already in Home` from the server response. Call `onMembershipChanged` only for
`status === 'added'`. When false, explain that only Amo and Dan can add members.
Do not render a Home invite code or a member-removal UI; emergency removal is
the reviewed operator script from Task 2.

In `RightPanel`, keep Trading unconditionally appended. For Home only, replace
the Share tab with a Home tab that renders `HomeSettingsPanel`; ordinary rooms
retain Share unchanged.

- [ ] **Step 5: Make Trading's Home empty state explanatory, not actionable**

Before the generic unbound-room `CreateThesisForm`, add:

```tsx
if (currentRoom?.is_home && !tradingConfig) {
  return (
    <div className="trading-panel-empty trading-panel-home">
      <strong>Home connects the schemes.</strong>
      <p>Propose and create a thesis in the scheme's own room.</p>
    </div>
  );
}
```

Keep the Trading tab present in Home and every ordinary room. The backend and
tool guards from Task 3 remain authoritative.

- [ ] **Step 6: Run frontend gates**

Run: `cd dialectic/frontend/app && npm run lint && npm run build`

Expected: PASS.

- [ ] **Step 7: Commit Home surfaces**

```bash
git add dialectic/frontend/app/src/components/home/HomeActivityPulse.tsx dialectic/frontend/app/src/components/home/HomeActivityPulse.css dialectic/frontend/app/src/components/home/HomeSettingsPanel.tsx dialectic/frontend/app/src/components/home/HomeSettingsPanel.css dialectic/frontend/app/src/types/index.ts dialectic/frontend/app/src/lib/api.ts dialectic/frontend/app/src/App.tsx dialectic/frontend/app/src/components/sidebar/RightPanel.tsx dialectic/frontend/app/src/components/trading/TradingPanel.tsx dialectic/frontend/app/src/components/trading/TradingPanel.css
git commit -m "feat: make Home the shared cockpit -- keep schemes in rooms"
```

### Task 9: Full verification, browser proof, and current-state records

**Files:**
- Modify: `README.md`
- Modify: `dialectic/README.md`
- Modify: `CLAUDE.md`
- Modify: `dialectic/CLAUDE.md`
- Modify: `dialectic/TODOS.md`
- Modify: `JOURNAL.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a reviewable local implementation with current docs and explicit separation between code, migration, runtime, and device proof.

- [ ] **Step 1: Run focused backend contracts together**

Run:

```bash
cd dialectic && python3 -m pytest \
  tests/test_home_schema_pg.py \
  tests/test_home_membership_api.py \
  tests/test_home_activity_pg.py \
  tests/test_home_activity_api.py \
  tests/test_home_prompt.py \
  tests/test_thesis_relay_endpoint.py \
  tests/test_tools_registry.py \
  tests/test_user_rooms_read_state.py -q
```

Expected: PASS, with real-Postgres projection tests explicitly reported as run
or skipped.

- [ ] **Step 2: Confirm the Task 4 performance gate after integration**

Re-run Task 4's deterministic seed `20260811`, `EXPLAIN (ANALYZE, BUFFERS,
FORMAT JSON)`, and 20 warm service calls against the integrated code. Record
planning time, execution time, shared-hit blocks, shared-read blocks, and p95
in `JOURNAL.md`. The acceptance target remains p95 <= 150 ms. A failure returns
work to Task 4 query/index design before browser verification; do not add a
late cache or index after both consumers have been accepted.

- [ ] **Step 3: Run the full backend suite**

Run: `cd dialectic && python3 -m pytest tests/ -q`

Expected: all non-environment-skipped tests PASS.

- [ ] **Step 4: Run frontend static gates**

Run: `cd dialectic/frontend/app && npm run lint && npm run build`

Expected: both PASS.

- [ ] **Step 5: Prepare an isolated browser-acceptance database**

Point both the backend and every psql command explicitly at
`DIALECTIC_TEST_DATABASE_URL`; do not source the production `.env`. Apply
migration `013` idempotently. Through the real signup/auth and room APIs, create
three uniquely named local test credential accounts, activate the first two as
Home founders with `activate_home_founders.sql`, create one room shared by both
founders, one room belonging only to the first, and one fork in the shared
room. The third account remains outside Home.

Before opening the PWA, assert the first founder's authenticated
`GET /users/me/home/activity` is 200 and the third account receives the exact
`404 {"detail":"Home unavailable"}` response. This fixture is test data in the
isolated database only; never use production emails, tokens, or room IDs.

- [ ] **Step 6: Run repeatable desktop and mobile browser acceptance**

Against the local backend and Vite production preview, use the installed
headless browser tooling to exercise, not merely screenshot:

1. bare `/` launch enters Home;
2. explicit room and branch URLs survive refresh;
3. Home root → Home branch → Back → Forward restores both destinations without
   increasing `history.length` or calling replaceState during popstate;
4. live `open-room` service-worker messages switch rooms;
5. Home pulse room and branch taps land at the exact destination;
6. Create/Join opens as an overlay and cancel preserves the active transcript;
7. an artificially slow room-list boot shows the loading shell, opens no
   WebSocket and performs no room-scoped request before Home is installed;
8. a revoked persisted room plus bare `/` falls back to Home exactly once with
   an error and performs no hydration fetch for the persisted room;
9. a cross-branch search jump updates the URL, closes the drawer, and survives
   refresh in that branch;
10. Home activity error retains a stale successful snapshot;
11. 1440, 1200, and 1024 widths preserve desktop navigation;
12. 768 and 390 widths preserve the shipped scrim and Escape close, reach every
    room and active branch, close on branch selection, and keep the composer
    visible with the software-keyboard viewport emulation;
13. Home Trading remains visible but exposes no create form;
14. ordinary unbound rooms still expose Create Thesis.

Save screenshots only for failures or final device evidence; the pass/fail
record must come from asserted destinations, visible labels, drawer state, and
history length.

- [ ] **Step 7: Update current-state documentation**

Update the two READMEs so bare launch, Home, branch navigation, and Home member
administration match the shipped UI. Update both `CLAUDE.md` files to name
migration `013`, the Home projection, and the default launch contract. Record
the completed task and remaining production activation/device gate in
`dialectic/TODOS.md`. Append one `JOURNAL.md` line for each meaningful measured
or behavioral decision; do not paste test noise.

- [ ] **Step 8: Run repository hygiene checks**

Run: `git diff --check`

Run: `git status --short`

Run: `git diff --name-only $(git merge-base HEAD master)..HEAD`

Confirm no trading snapshots, credentials, generated releases, browser
profiles, or unrelated dirty files are staged.

- [ ] **Step 9: Commit current-state records**

```bash
git add README.md dialectic/README.md CLAUDE.md dialectic/CLAUDE.md dialectic/TODOS.md JOURNAL.md
git commit -m "docs: record Home Base implementation -- hold activation"
```

## Production activation gate

Do not cross this gate as part of implementation. After separate explicit
approval:

1. verify the reviewed implementation commit and capture current service/health;
2. verify the Task 1 migration evidence and re-check the two columns, partial
   unique index, one Home, one root `Main` thread, and zero Home memberships;
3. place the reviewed backend commit in the deployed checkout, restart
   `dialectic.service`, and verify `/health` plus scheduler heartbeat before any
   account can see Home;
4. verify both founders still receive no Home row before activation;
5. run `activate_home_founders.sql` with the reviewed Amo and Dan credential
   emails, then verify exactly two Home memberships, both management flags, and
   no other credentialed Home member;
6. verify Home auth, member preview/add, activity intersection, soft-delete,
   thesis denial, Claude timeout/unavailable markers, and the reviewed emergency
   removal script against a disposable nonfounder account;
7. build an immutable frontend release, verify its asset digest, flip
   `/var/www/dialectic-current`, and reload nginx;
8. complete the actual iPhone and Android acceptance list from the approved
   spec, including cold/open notification entry, background eviction, keyboard,
   drawer branch reachability, and offline-stale rendering;
9. report commit, migration, backend PID/health, served asset digest, browser
   proof, and device proof as separate states.

Rollback remains additive: flip the frontend symlink back first; the prior
backend ignores the new columns; a backend rollback runs against the additive
schema. Do not delete Home, its messages, memberships, events, or token during
rollback.
