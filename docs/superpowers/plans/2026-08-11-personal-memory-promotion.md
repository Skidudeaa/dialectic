# Personal Memory Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each authenticated room member independently promote a shared memory into only their own cross-room LLM context.

**Architecture:** Store personal visibility as a `(memory_id, user_id)` grant instead of mutating the shared memory row. Cross-room recall and auto-inject queries join that grant while retaining source-room membership and active-memory fences. Expose the state through narrow authenticated REST endpoints and merge it into the existing PWA memory model.

**Tech Stack:** PostgreSQL/asyncpg, FastAPI/Pydantic, pytest, React 19, TypeScript, Zustand, Vite.

## Global Constraints

- Keep `memories.scope` unchanged; a promotion belongs only to the requesting user.
- Require bearer auth, the source room token, and current source-room membership for every promotion write.
- Keep the existing room-token-only memory-listing endpoint backward compatible.
- Do not mount `api/cross_session_routes.py` or add a WebSocket promotion protocol.
- Do not add a frontend test framework in this tranche; the approved design uses lint, production build, and later browser proof.
- Do not touch tradingDesk files or activate the migration, backend, or frontend in production.

---

### Task 1: Schema and event vocabulary

**Files:**
- Create: `dialectic/migrations/012_user_memory_promotions.sql`
- Modify: `dialectic/schema.sql`
- Modify: `dialectic/models.py`
- Create: `dialectic/tests/test_personal_memory_promotion.py`

**Interfaces:**
- Consumes: existing `memories(id)`, `users(id)`, and string-valued `EventType`.
- Produces: table `user_memory_promotions(memory_id, user_id, promoted_at)` and `EventType.MEMORY_DEMOTED`.

- [ ] **Step 1: Write the failing schema and event contract**

```python
from pathlib import Path

from models import EventType


def test_personal_promotion_schema_and_event_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = (root / "schema.sql").read_text()
    migration = (root / "migrations" / "012_user_memory_promotions.sql").read_text()
    for sql in (schema, migration):
        assert "CREATE TABLE IF NOT EXISTS user_memory_promotions" in sql
        assert "PRIMARY KEY (memory_id, user_id)" in sql
        assert "idx_user_memory_promotions_user" in sql
    assert EventType.MEMORY_DEMOTED.value == "memory_demoted"
```

- [ ] **Step 2: Run the contract and verify RED**

Run: `cd dialectic && python3 -m pytest tests/test_personal_memory_promotion.py::test_personal_promotion_schema_and_event_contract -q`

Expected: FAIL because the migration and enum member do not exist.

- [ ] **Step 3: Add the migration, fresh-schema table, and event member**

```sql
CREATE TABLE IF NOT EXISTS user_memory_promotions (
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    promoted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (memory_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_memory_promotions_user
    ON user_memory_promotions(user_id, memory_id);
```

Add `MEMORY_DEMOTED = "memory_demoted"` beside `MEMORY_PROMOTED`. Update the
existing promotion payload docstring to describe a personal cross-room grant,
not a mutation to global row scope.

- [ ] **Step 4: Run the contract and verify GREEN**

Run: `cd dialectic && python3 -m pytest tests/test_personal_memory_promotion.py::test_personal_promotion_schema_and_event_contract -q`

Expected: PASS.

- [ ] **Step 5: Commit the schema unit**

```bash
git add dialectic/migrations/012_user_memory_promotions.sql dialectic/schema.sql dialectic/models.py dialectic/tests/test_personal_memory_promotion.py
git commit -m "feat: add personal memory grants -- preserve shared scope"
```

### Task 2: Membership-fenced manager writes and personal recall

**Files:**
- Modify: `dialectic/memory/cross_session.py`
- Modify: `dialectic/tests/test_personal_memory_promotion.py`
- Modify: `dialectic/tests/test_collaboration_contracts.py`
- Create: `dialectic/tests/test_cross_session_memory_pg.py`

**Interfaces:**
- Consumes: `user_memory_promotions`, `EventType.MEMORY_PROMOTED`, and `EventType.MEMORY_DEMOTED`.
- Produces: `CrossSessionMemoryManager.get_user_promoted_memory_ids(room_id: UUID, user_id: UUID) -> List[UUID]`; existing promote/demote methods retain their signatures and return `Memory`.

- [ ] **Step 1: Write failing manager contract tests**

```python
@pytest.mark.asyncio
async def test_promote_uses_a_personal_membership_fenced_grant(memory_row) -> None:
    db = SimpleNamespace(fetchrow=AsyncMock(return_value=memory_row))
    manager = CrossSessionMemoryManager(db)
    memory = await manager.promote_memory_to_global(memory_row["id"], USER_A)
    sql = db.fetchrow.await_args.args[0]
    assert memory.id == memory_row["id"]
    assert "INSERT INTO user_memory_promotions" in sql
    assert "JOIN room_memberships" in sql
    assert "m.status = 'active'" in sql
    assert "UPDATE memories" not in sql


@pytest.mark.asyncio
async def test_global_recall_joins_the_requesting_users_grant() -> None:
    db = SimpleNamespace(fetch=AsyncMock(return_value=[]))
    manager = CrossSessionMemoryManager(db)
    manager._embedder = MockEmbeddings()
    await manager.search_user_memories(USER_A, "shared concept", require_global_scope=True)
    sql = db.fetch.await_args.args[0]
    assert "JOIN user_memory_promotions" in sql
    assert "ump.user_id = $1" in sql
    assert "m.scope = 'global'" not in sql
```

Also replace the two old assertions in `test_collaboration_contracts.py` so
automatic recall and collection auto-inject require the personal-grant join.

- [ ] **Step 2: Run the manager contracts and verify RED**

Run: `cd dialectic && python3 -m pytest tests/test_personal_memory_promotion.py tests/test_collaboration_contracts.py -q`

Expected: FAIL because writes still update `memories.scope` and reads still filter `scope = 'global'`.

- [ ] **Step 3: Implement atomic, idempotent personal writes**

Use one SQL statement per write. The promote statement must:

```sql
WITH authorized_memory AS (
    SELECT m.*
    FROM memories m
    JOIN room_memberships rm
      ON rm.room_id = m.room_id AND rm.user_id = $2
    WHERE m.id = $1 AND m.status = 'active'
), inserted_promotion AS (
    INSERT INTO user_memory_promotions (memory_id, user_id)
    SELECT id, $2 FROM authorized_memory
    ON CONFLICT (memory_id, user_id) DO NOTHING
    RETURNING memory_id
), inserted_event AS (
    INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
    SELECT gen_random_uuid(), NOW(), 'memory_promoted', room_id, $2,
           jsonb_build_object(
               'memory_id', id,
               'original_room_id', room_id,
               'promoted_by_user_id', $2
           )
    FROM authorized_memory
    WHERE EXISTS (SELECT 1 FROM inserted_promotion)
)
SELECT * FROM authorized_memory
```

The demote statement uses the same `authorized_memory` CTE, deletes only
`(memory_id, $2)`, and inserts `memory_demoted` only when a row was deleted.
Both methods raise `ValueError("Memory not found or inaccessible")` when the
authorization CTE returns no row. Idempotent repeats return the source `Memory`
without a duplicate lifecycle event.

- [ ] **Step 4: Implement personal read joins**

In `search_user_memories`, replace the row-scope predicate with:

```sql
AND (
    NOT $6::boolean
    OR EXISTS (
        SELECT 1
        FROM user_memory_promotions ump
        WHERE ump.memory_id = m.id AND ump.user_id = $1
    )
)
```

In `get_auto_inject_memories`, join `user_memory_promotions ump` on
`ump.memory_id = m.id AND ump.user_id = $1`, and retain the active-memory
filter. Add `get_user_promoted_memory_ids` with joins to `memories` and
`room_memberships`, filtering the supplied room, user, and active status.

- [ ] **Step 5: Run the manager contracts and verify GREEN**

Run: `cd dialectic && python3 -m pytest tests/test_personal_memory_promotion.py tests/test_collaboration_contracts.py -q`

Expected: PASS.

- [ ] **Step 6: Add the real-Postgres A/B acceptance test**

Create deterministic integration coverage using `DIALECTIC_TEST_DATABASE_URL`,
`MockEmbeddings`, two users, a shared source room, and a second room for user A:

```python
@pytest.mark.asyncio
async def test_personal_promotion_is_visible_only_to_the_promoter(db, rooms) -> None:
    memory = await rooms.memory_manager.add_memory(
        rooms.source_room,
        "shared_concept",
        "The personal promotion acceptance concept",
        created_by_user_id=rooms.user_a,
    )
    await rooms.cross_session_manager.promote_memory_to_global(memory.id, rooms.user_a)

    a_hits = await rooms.cross_session_manager.get_relevant_cross_room_memories(
        rooms.user_a, rooms.user_a_second_room, "personal promotion acceptance concept"
    )
    b_hits = await rooms.cross_session_manager.get_relevant_cross_room_memories(
        rooms.user_b, uuid4(), "personal promotion acceptance concept"
    )

    assert memory.id in {hit.memory_id for hit in a_hits}
    assert memory.id not in {hit.memory_id for hit in b_hits}
    assert await db.fetchval("SELECT scope FROM memories WHERE id = $1", memory.id) == "room"
```

Add cases proving an outsider cannot promote, invalidated memories cannot be
promoted, and repeated promote/demote calls emit exactly one event each.

- [ ] **Step 7: Apply the migration only to the local test database and run integration GREEN**

Run: `cd dialectic && psql postgresql://root@localhost/dialectic_test -v ON_ERROR_STOP=1 -f migrations/012_user_memory_promotions.sql`

Run: `cd dialectic && python3 -m pytest tests/test_cross_session_memory_pg.py -q`

Expected: PASS, or a clean skip only if the documented test database is unavailable.

- [ ] **Step 8: Commit the manager unit**

```bash
git add dialectic/memory/cross_session.py dialectic/tests/test_personal_memory_promotion.py dialectic/tests/test_collaboration_contracts.py dialectic/tests/test_cross_session_memory_pg.py
git commit -m "feat: fence personal memory recall -- isolate collaborators"
```

### Task 3: Authenticated REST state and mutation endpoints

**Files:**
- Modify: `dialectic/api/main.py`
- Create: `dialectic/tests/test_memory_promotion_api.py`

**Interfaces:**
- Consumes: `get_current_user`, `extract_room_token`, `verify_room_token`, `verify_room_member`, and the manager methods from Task 2.
- Produces: `GET /rooms/{room_id}/memory-promotions`, `PUT /memories/{memory_id}/promotion`, and `DELETE /memories/{memory_id}/promotion`.

- [ ] **Step 1: Write failing HTTP contract tests**

Use the repository's `TestClient` dependency-override pattern. Cover:

```python
def test_promote_requires_authenticated_source_room_membership(client) -> None:
    response = client.put(f"/memories/{MEMORY_ID}/promotion")
    assert response.status_code == 200
    assert response.json() == {"memory_id": str(MEMORY_ID), "promoted": True}


def test_personal_promotion_list_returns_only_callers_ids(client) -> None:
    response = client.get(f"/rooms/{ROOM_ID}/memory-promotions")
    assert response.status_code == 200
    assert response.json() == {"memory_ids": [str(MEMORY_ID)]}
```

Separate tests omit the bearer dependency override, supply an invalid room
token, remove the caller from memberships, and make the manager raise
`ValueError`. Assert 401, 401, 403, and 404 respectively.

- [ ] **Step 2: Run the endpoint tests and verify RED**

Run: `cd dialectic && python3 -m pytest tests/test_memory_promotion_api.py -q`

Expected: FAIL with 404 because the route family does not exist.

- [ ] **Step 3: Implement response models and narrow routes in `api/main.py`**

```python
class MemoryPromotionResponse(BaseModel):
    memory_id: UUID
    promoted: bool


class MemoryPromotionListResponse(BaseModel):
    memory_ids: List[UUID]
```

The list route verifies the path room directly. Each mutation first selects the
memory's source `room_id`; a missing row returns 404. Then it verifies the room
token and membership before calling the manager. Map the manager's fail-closed
`ValueError` to 404. Return JSON for both PUT and DELETE so the existing generic
frontend fetch helper does not need a no-content special case.

- [ ] **Step 4: Run endpoint tests and focused backend regression tests**

Run: `cd dialectic && python3 -m pytest tests/test_memory_promotion_api.py tests/test_personal_memory_promotion.py tests/test_collaboration_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the authenticated transport**

```bash
git add dialectic/api/main.py dialectic/tests/test_memory_promotion_api.py
git commit -m "feat: expose personal memory promotion -- require room membership"
```

### Task 4: Minimal PWA Promote/Demote control

**Files:**
- Modify: `dialectic/frontend/app/src/types/index.ts`
- Modify: `dialectic/frontend/app/src/lib/api.ts`
- Modify: `dialectic/frontend/app/src/App.tsx`
- Modify: `dialectic/frontend/app/src/components/sidebar/RightPanel.tsx`
- Modify: `dialectic/frontend/app/src/components/sidebar/MemoryPanel.tsx`
- Modify: `dialectic/frontend/app/src/components/sidebar/MemoryPanel.css`

**Interfaces:**
- Consumes: Task 3's JSON contracts and existing `refreshMemories()`.
- Produces: `Memory.personally_promoted: boolean`, typed API methods, and `onSetMemoryPromotion(memoryId: string, promoted: boolean) => Promise<void>`.

- [ ] **Step 1: Add typed API composition**

The approved design explicitly omits a new frontend test framework. Implement
the smallest typed contract and use the production TypeScript compiler as the
first gate:

```typescript
export interface Memory {
  id: string;
  key: string;
  content: string;
  scope: 'room' | 'user' | 'global' | 'llm';
  version: number;
  status: 'active' | 'invalidated';
  personally_promoted: boolean;
}
```

In `DialecticAPI`, fetch the existing memory list and the personal ID list in
parallel, then map `personally_promoted` onto each memory. Add typed PUT and
DELETE methods for one memory. Both requests use the existing `fetch` helper so
they carry bearer and room-token headers.

- [ ] **Step 2: Wire the async action through App and RightPanel**

```typescript
onSetMemoryPromotion={async (memoryId, promoted) => {
  if (promoted) await api.promoteMemory(memoryId)
  else await api.demoteMemory(memoryId)
  await refreshMemories()
}}
```

Add the exact promise-returning prop to `RightPanelProps` and pass it unchanged
to `MemoryPanel`.

- [ ] **Step 3: Add per-card pending and error behavior**

In `MemoryPanel`, maintain `pendingMemoryId: string | null` and
`promotionError: string | null`. Disable only the selected button, await the
prop, preserve the prior state on failure, and render the thrown error's
message. The button copy is `Promote` or `Demote` from
`memory.personally_promoted`; add a small `Personal` marker beside the existing
source scope when promoted.

- [ ] **Step 4: Add styles using existing tokens**

Add `.memory-meta`, `.memory-promotion`, `.memory-promotion.is-promoted`, and
`.memory-error` rules to `MemoryPanel.css`. Reuse existing amber, ghost, bean,
espresso, bone, and radius variables; introduce no new token or dependency.

- [ ] **Step 5: Run frontend compile and lint**

Run: `cd dialectic/frontend/app && npm run build`

Run: `cd dialectic/frontend/app && npm run lint`

Expected: both PASS with no TypeScript or ESLint errors.

- [ ] **Step 6: Commit the UI unit**

```bash
git add dialectic/frontend/app/src/types/index.ts dialectic/frontend/app/src/lib/api.ts dialectic/frontend/app/src/App.tsx dialectic/frontend/app/src/components/sidebar/RightPanel.tsx dialectic/frontend/app/src/components/sidebar/MemoryPanel.tsx dialectic/frontend/app/src/components/sidebar/MemoryPanel.css
git commit -m "feat: control personal memory recall -- surface promotion state"
```

### Task 5: Current-state docs and full verification

**Files:**
- Modify: `dialectic/TODOS.md`
- Modify: `JOURNAL.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: dated current-state record and a verified, reviewable branch; no production activation.

- [ ] **Step 1: Update current-state records**

Append a dated P2 completion note to `dialectic/TODOS.md` stating that the
personal promotion migration, authenticated REST write path, and PWA controls
are implemented but not activated. Append one `JOURNAL.md` line recording the
behavioral contract and verification boundary.

- [ ] **Step 2: Run all backend tests**

Run: `cd dialectic && python3 -m pytest tests/ -q`

Expected: all non-environment-skipped tests PASS.

- [ ] **Step 3: Re-run frontend and repository checks**

Run: `cd dialectic/frontend/app && npm run lint && npm run build`

Run: `git diff --check`

Expected: all PASS.

- [ ] **Step 4: Review migration and route surface without production mutation**

Run: `rg -n "user_memory_promotions|memory-promotions|/promotion|personally_promoted" dialectic`

Confirm the personal table is the only automatic cross-room visibility gate,
the new routes require both credential types and membership, and the dormant
placeholder-auth router remains unmounted.

- [ ] **Step 5: Commit docs and final verification state**

```bash
git add dialectic/TODOS.md JOURNAL.md
git commit -m "docs: record personal memory promotion -- hold activation"
```

- [ ] **Step 6: Stop at the activation boundary**

Report branch commits, exact tests run, test-database migration status, and the
unverified production migration/backend restart/frontend release/browser flow.
Do not activate production without a separate explicit instruction.
