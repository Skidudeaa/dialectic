# Dialectic Big-Bang Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair every verified trust, data-contract, external-write, pagination, startup, iPad-shell, accessibility, and current-state-authority defect as one integrated release.

**Architecture:** Build the release as small red-green slices on one isolated branch, but ship none separately. Add one focused rate-limit module, one PostgreSQL external-operation ledger, downstream tradingDesk idempotency, bounded ancestry cursors, and explicit responsive-shell state; then pass one integrated gate and squash the temporary task commits into one implementation commit.

**Tech Stack:** Python 3.12, FastAPI, asyncpg/PostgreSQL, pytest/pytest-asyncio, SQLite, React 19, TypeScript, Zustand, Vitest, Vite, Playwright, axe-core, CSS safe-area environment variables, systemd unit files.

## Global Constraints

- Work only in an isolated worktree created from the committed design and plan.
- Preserve existing request and response schemas except for the additive ancestry cursor fields and the explicit 422 on sequence cursors with ancestry.
- Keep `POST /rooms` as a two-step create-then-join lifecycle; authentication must not silently create membership.
- Hard-code the approved rate policies; do not add configuration indirection or a generalized policy engine.
- PostgreSQL migration 018 and tradingDesk SQLite migration 006 are additive. Update fresh-schema sources as well as upgrade migrations.
- No database connection may remain checked out during tradingDesk, Defuddle, quote, or news network waits.
- Keep all seven scenes and the existing visual identity. Do not remove mounted personas, replay, knowledge graph, Atlas, or trading surfaces.
- Controls use at least 12px text, ordinary interface copy at least 14px, independently tappable controls at least 44px, and normal text contrast at least 4.5:1.
- Use strict TDD: write one behavioral test, observe the expected failure, implement the minimum, and observe the pass before the next behavior.
- Type hints are mandatory for new Python functions. Tests assert real behavior; mock only external HTTP boundaries.
- Do not touch production databases, SQLite files, services, systemd state, symlinks, served assets, or live configuration.
- Preserve and do not stage unrelated snapshots, `IMG_0197.PNG`, generated acceptance caches, or concurrent work.
- Append meaningful decisions and dead ends to `JOURNAL.md` using `[2026-08-15] action — why`.
- Temporary task commits are local checkpoints. After the integrated gate, squash them into one implementation commit as required by the approved big-bang design.

## File and Interface Map

### Trust boundary

- Create `dialectic/api/rate_limit.py`: bounded in-process limiter, request/IP keying, account-digest keying, and fixed dependencies.
- Modify `dialectic/api/main.py`: import the fixed dependency; authenticate create, join, and user-model reads.
- Modify `dialectic/api/auth/routes.py`: apply account policies and honest password-recovery behavior.
- Modify `dialectic/frontend/app/src/components/auth/AuthScreen.tsx`: render the backend recovery-unavailable error without success copy.
- Delete `dialectic/api/cross_session_routes.py` after proving it has no references.

### Message and local data correctness

- Modify `dialectic/api/main.py`: reload fields, REST send parity, cursor fields, bounded ancestry query, and fail-fast startup.
- Modify `dialectic/transport/handlers.py`: expose one authoritative `build_message_created_payload` helper used by WebSocket and REST.
- Modify `dialectic/api/notifications/service.py`: null-safe author filtering and lowercase enum filtering.
- Modify `dialectic/api/attachments.py`: dedup only to the current uploader's unbound row.

### Durable external operations

- Create `dialectic/migrations/018_external_operations.sql` and modify `dialectic/schema.sql`.
- Create `dialectic/api/external_operations.py`: typed claim/succeed/fail operations over short pool acquisitions.
- Modify `dialectic/api/prediction_relay.py`, `reading_relay.py`, `thesis_relay.py`, and `trading_relay.py`: pool dependencies and retry-safe external calls.
- Create `trading/web/persistence/sql/006_dialectic_idempotency.sql`.
- Modify `trading/web/models.py`, `trading/web/persistence/repository.py`, `trading/web/routes/predictions.py`, and `trading/web/routes/builder.py`.

### Installed-PWA shell

- Modify `dialectic/frontend/app/src/stores/appStore.ts`: explicit right-panel-open state.
- Modify `AppLayout.tsx/.css`, `RoomHeader.tsx/.css`, `RightPanel.tsx/.css`, `RightPanel.test.tsx`, `SceneSwitcher.tsx/.css`, and scene/layout tests.
- Modify the 38 CSS files identified by the small-type audit only where a rendered control or ordinary copy violates the approved floor.
- Create `docs/superpowers/acceptance/2026-08-15-big-bang-browser-acceptance.py` for full-document axe, geometry, touch, contrast, safe-area, and five-width checks.

### Authority and gate

- Modify `dialectic/README.md`, `dialectic/CLAUDE.md`, `dialectic/TODOS.md`, `PLAN.md`, `dialectic/deploy/dialectic.service`, and the existing human-interaction audit.
- Update `JOURNAL.md`; never stage unrelated entries or artifacts.

---

### Task 1: Establish the isolated baseline

**Files:**
- Read: `CLAUDE.md`
- Read: `dialectic/CLAUDE.md`
- Read: `dialectic/README.md`
- Read: `trading/CLAUDE.md`
- Read: `trading/README.md`
- Read: `JOURNAL.md`

**Interfaces:**
- Consumes: committed design `docs/superpowers/specs/2026-08-15-dialectic-big-bang-stabilization-design.md`.
- Produces: a recorded base SHA, clean feature-worktree scope, and honest baseline test results.

- [ ] **Step 1: Create the worktree through `superpowers:using-git-worktrees`**

Use `.worktrees/dialectic-big-bang-stabilization` and branch `codex/dialectic-big-bang-stabilization-2026-08-15`. Verify the directory is ignored before creation.

```bash
git check-ignore -q .worktrees
git worktree add .worktrees/dialectic-big-bang-stabilization -b codex/dialectic-big-bang-stabilization-2026-08-15
```

- [ ] **Step 2: Re-read repository instructions inside the worktree**

```bash
sed -n '1,260p' CLAUDE.md
sed -n '1,280p' dialectic/CLAUDE.md
sed -n '1,240p' dialectic/README.md
sed -n '1,240p' trading/CLAUDE.md
sed -n '1,180p' trading/README.md
tail -n 20 JOURNAL.md
```

- [ ] **Step 3: Record scope and baseline SHA without modifying production**

```bash
git status --short
git rev-parse HEAD
systemctl is-active dialectic.service tradingdesk.service defuddle.service
```

Expected: feature worktree is clean; services are read only and no command restarts them.

- [ ] **Step 4: Run the targeted baseline suites**

```bash
cd dialectic
python3 -m pytest tests/test_signup_guard.py tests/test_home_membership_api.py tests/test_attachments.py tests/test_prediction_relay_endpoint.py tests/test_prediction_resolve_accept.py tests/test_reading_relay_endpoint.py tests/test_thesis_relay_endpoint.py tests/test_propose_surface_pg.py -q
cd ../trading
python3 -m pytest web/persistence/test_persistence.py web/test_web.py web/routes/test_builder.py -q
cd ../dialectic/frontend/app
npm test -- --run
npm run lint
```

Expected: record exact pass/fail/skip output in `JOURNAL.md`; pre-existing failures stop implementation until classified.

### Task 2: Make authentication and recovery fail closed

**Files:**
- Create: `dialectic/api/rate_limit.py`
- Create: `dialectic/tests/test_auth_security.py`
- Modify: `dialectic/api/main.py`
- Modify: `dialectic/api/auth/routes.py`
- Modify: `dialectic/frontend/app/src/components/auth/AuthScreen.tsx`
- Modify: `dialectic/frontend/app/src/components/auth/AuthScreen.test.tsx`

**Interfaces:**
- Consumes: FastAPI `Request`; route account identifiers already present in Pydantic payloads.
- Produces: `RateLimiter.is_allowed(key: str, limit: int, window_seconds: int) -> bool`, `check_rate_limit(request: Request) -> None`, and `check_account_rate_limit(request: Request, account_identifier: str, *, scope: str, limit: int, window_seconds: int) -> None`.

- [ ] **Step 1: Write failing limiter and OpenAPI tests**

```python
def test_auth_openapi_does_not_expose_rate_policy() -> None:
    operation = main_mod.app.openapi()["paths"]["/auth/login"]["post"]
    names = {parameter["name"] for parameter in operation.get("parameters", [])}
    assert names.isdisjoint({"limit", "window"})


def test_limiter_evicts_expired_keys() -> None:
    now = [100.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert limiter.is_allowed("ip:/auth/login", 1, 60)
    now[0] = 3701.0
    assert limiter.is_allowed("other", 1, 60)
    assert "ip:/auth/login" not in limiter._requests
```

- [ ] **Step 2: Run the tests and observe the expected failures**

```bash
cd dialectic
python3 -m pytest tests/test_auth_security.py::test_auth_openapi_does_not_expose_rate_policy tests/test_auth_security.py::test_limiter_evicts_expired_keys -q
```

Expected: OpenAPI still contains `limit`/`window`; `api.rate_limit` does not exist.

- [ ] **Step 3: Move and bound the limiter**

```python
class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = self._clock()
        stale_cutoff = now - 3600
        for known_key, timestamps in tuple(self._requests.items()):
            if not timestamps or timestamps[-1] <= stale_cutoff:
                del self._requests[known_key]
        cutoff = now - window_seconds
        bucket = [stamp for stamp in self._requests.get(key, []) if stamp > cutoff]
        self._requests[key] = bucket
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True
```

`check_rate_limit` accepts only `request: Request` and enforces 60/60.
`check_account_rate_limit` applies the approved lower limit to both
`{client_ip}:{scope}` and `{account_digest}:{scope}`. Account digests use
`sha256(account_identifier.strip().lower().encode()).hexdigest()` and never store
raw identifiers. Verify-email uses the authenticated user ID as its identifier;
login, forgot, and reset use normalized email.

- [ ] **Step 4: Add failing route-policy and recovery-truth tests**

```python
def test_sixth_login_attempt_for_one_account_is_limited(client: TestClient) -> None:
    for _ in range(5):
        assert client.post("/auth/login", json={"email": "a@example.test", "password": "wrong-password"}).status_code != 429
    assert client.post("/auth/login", json={"email": "a@example.test", "password": "wrong-password"}).status_code == 429


def test_forgot_password_is_unavailable_without_creating_a_code(client, db) -> None:
    response = client.post("/auth/forgot-password", json={"email": "known@example.test"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Password recovery is unavailable because email delivery is not configured"
    assert not any("verification_codes" in call.args[0] for call in db.execute.await_args_list)
```

- [ ] **Step 5: Run the new route tests and verify they fail for behavior**

```bash
python3 -m pytest tests/test_auth_security.py -q
```

Expected: sixth attempt is accepted and forgot-password returns false success or inserts a code.

- [ ] **Step 6: Apply the fixed per-route policies**

Use these exact policies before expensive work: login/verify/reset 5 per 900 seconds by IP and account digest; forgot 3 per 900; signup 5 per 3600 by IP. Unknown account and invalid reset code both return the same 400 detail. Forgot-password returns the approved 503 for every account state and never inserts.

```python
check_account_rate_limit(
    http_request,
    payload.email,
    scope="login",
    limit=5,
    window_seconds=900,
)
```

- [ ] **Step 7: Make frontend recovery copy reflect the 503**

```tsx
expect(await screen.findByRole('alert')).toHaveTextContent(
  'Password recovery is unavailable because email delivery is not configured',
)
expect(screen.queryByText(/code sent/i)).not.toBeInTheDocument()
```

- [ ] **Step 8: Run targeted backend and frontend tests**

```bash
cd dialectic
python3 -m pytest tests/test_auth_security.py tests/test_signup_guard.py -q
cd frontend/app
npm test -- --run src/components/auth/AuthScreen.test.tsx
```

- [ ] **Step 9: Commit the checkpoint**

```bash
git add dialectic/api/rate_limit.py dialectic/api/main.py dialectic/api/auth/routes.py dialectic/tests/test_auth_security.py dialectic/frontend/app/src/components/auth/AuthScreen.tsx dialectic/frontend/app/src/components/auth/AuthScreen.test.tsx JOURNAL.md
git commit -m "fix(dialectic): close authentication bypasses"
```

### Task 3: Fence room identity and remove the placeholder router

**Files:**
- Create: `dialectic/tests/test_room_authorization.py`
- Modify: `dialectic/api/main.py`
- Modify: `dialectic/tests/test_home_membership_api.py`
- Delete: `dialectic/api/cross_session_routes.py`

**Interfaces:**
- Consumes: `AuthenticatedUser` from `api.auth.dependencies` and existing room-token/member verifiers.
- Produces: authenticated create/join/model endpoints with unchanged payload schemas.

- [ ] **Step 1: Write failing authorization tests**

```python
def test_create_room_requires_bearer_auth(client: TestClient) -> None:
    assert client.post("/rooms", json={"name": "No ghost room"}).status_code == 401


def test_join_rejects_a_different_body_user(client: TestClient, caller: UUID, other: UUID) -> None:
    response = client.post(f"/rooms/{ROOM_ID}/join", json={"user_id": str(other)})
    assert response.status_code == 403
    assert response.json()["detail"] == "Cannot join a room as another user"


def test_user_model_rejects_a_different_path_user(client: TestClient, other: UUID) -> None:
    response = client.get(f"/rooms/{ROOM_ID}/user-models/{other}")
    assert response.status_code == 403
```

- [ ] **Step 2: Run the tests and observe unauthorized success or missing dependencies**

```bash
cd dialectic
python3 -m pytest tests/test_room_authorization.py tests/test_home_membership_api.py -q
```

- [ ] **Step 3: Add bearer dependencies and identity equality checks**

```python
async def join_room(
    room_id: UUID,
    request: JoinRoomRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_db),
) -> dict[str, str]:
    if request.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Cannot join a room as another user")
```

Add `current_user` before `db` on create and user-model routes. The user-model route compares IDs before constructing `LLMIdentityManager`.

- [ ] **Step 4: Prove the dormant router has no consumers, then delete it**

```bash
rg -n "cross_session_routes|/cross-session" dialectic --glob '!api/cross_session_routes.py'
```

Expected: no import, mount, client call, or test depends on the file. Delete it with `apply_patch`; do not mount or rehabilitate it.

- [ ] **Step 5: Run authorization and personal-memory tests**

```bash
python3 -m pytest tests/test_room_authorization.py tests/test_home_membership_api.py tests/test_memory_promotion_api.py tests/test_cross_session_memory_pg.py -q
```

- [ ] **Step 6: Commit the checkpoint**

```bash
git add dialectic/api/main.py dialectic/api/cross_session_routes.py dialectic/tests/test_room_authorization.py dialectic/tests/test_home_membership_api.py JOURNAL.md
git commit -m "fix(dialectic): bind room actions to bearer identity"
```

### Task 4: Make REST messages match persisted and live contracts

**Files:**
- Create: `dialectic/tests/test_message_rest_contracts.py`
- Modify: `dialectic/api/main.py`
- Modify: `dialectic/transport/handlers.py`
- Modify: `dialectic/tests/test_collaboration_contracts.py`
- Modify: `dialectic/tests/test_propose_surface_pg.py`

**Interfaces:**
- Consumes: `Message`, `MessageType`, sender display name, and bound attachment rows.
- Produces: `build_message_created_payload(message: Message, *, user_name: str, attachments: list[dict] | None = None) -> dict` used by both transports.

- [ ] **Step 1: Write the failing reload-field test**

```python
def test_history_returns_reply_and_edit_coordinates(client: TestClient) -> None:
    body = client.get(f"/threads/{THREAD_ID}/messages").json()["messages"][0]
    assert body["references_message_id"] == str(PARENT_ID)
    assert body["edited_at"] == EDITED_AT.isoformat().replace("+00:00", "Z")
```

- [ ] **Step 2: Run and observe the two missing response fields**

```bash
cd dialectic
python3 -m pytest tests/test_message_rest_contracts.py::test_history_returns_reply_and_edit_coordinates -q
```

- [ ] **Step 3: Populate the persisted fields**

```python
MessageResponse(
    id=message.id,
    thread_id=message.thread_id,
    sequence=message.sequence,
    created_at=message.created_at,
    speaker_type=message.speaker_type.value,
    user_id=message.user_id,
    message_type=message.message_type.value,
    content=message.content,
    references_message_id=message.references_message_id,
    edited_at=message.edited_at,
    metadata=message.metadata,
)
```

- [ ] **Step 4: Write failing REST parity tests**

```python
async def test_rest_send_rejects_cross_room_reference() -> None:
    response = await call_send_message(references_message_id=OTHER_ROOM_MESSAGE)
    assert response.status_code == 404


async def test_rest_send_retries_one_sequence_collision_and_broadcasts_after_commit() -> None:
    db = CollisionOnceDB()
    response = await call_send_message(db=db)
    assert response.status_code == 200
    assert db.transaction_entries == 2
    assert db.event_inserted_before_last_commit is True
    assert broadcast.payload["references_message_id"] == str(PARENT_ID)


async def test_broadcast_failure_does_not_turn_a_committed_send_into_a_retryable_error() -> None:
    connection_manager.broadcast.side_effect = RuntimeError("socket fanout failed")
    response = await call_send_message()
    assert response.status_code == 200
    assert await persisted_message_count() == 1
```

- [ ] **Step 5: Run and observe the reference, retry, transaction, and broadcast failures**

```bash
python3 -m pytest tests/test_message_rest_contracts.py -q
```

- [ ] **Step 6: Extract the authoritative payload helper**

```python
def build_message_created_payload(
    message: Message,
    *,
    user_name: str,
    attachments: list[dict] | None = None,
) -> dict:
    return {
        "id": str(message.id),
        "thread_id": str(message.thread_id),
        "sequence": message.sequence,
        "created_at": message.created_at.isoformat(),
        "speaker_type": message.speaker_type.value,
        "user_id": str(message.user_id) if message.user_id else None,
        "user_name": user_name,
        "message_type": message.message_type.value,
        "content": message.content,
        "references_message_id": str(message.references_message_id) if message.references_message_id else None,
        "metadata": message.metadata,
        "attachments": attachments or [],
    }
```

Replace the WebSocket inline dict with the helper before using it from REST.

- [ ] **Step 7: Implement three fresh transactions and post-commit broadcast**

Validate the reference room first. Within each attempt, insert message with `RETURNING sequence` and insert its event in one transaction. Catch only `asyncpg.UniqueViolationError`; sleep `0.05 * (attempt + 1)` before attempts two and three. Resolve the user name and broadcast only after the transaction exits.

```python
for attempt in range(3):
    try:
        async with db.transaction():
            row = await db.fetchrow(INSERT_MESSAGE_SQL, message_id, thread_id, now, speaker, user_id, message_type, content, reference_id, metadata)
            await db.execute(INSERT_EVENT_SQL, event_id, now, room_id, thread_id, user_id, event_payload)
        break
    except asyncpg.UniqueViolationError:
        if attempt == 2:
            raise
        await asyncio.sleep(0.05 * (attempt + 1))
```

Catch a post-commit broadcast exception only to log it with `logger.exception` and
return the already-persisted `MessageResponse`. Propagating it would invite the
REST client to retry a message that already exists.

- [ ] **Step 8: Run all message-door tests**

```bash
python3 -m pytest tests/test_message_rest_contracts.py tests/test_collaboration_contracts.py tests/test_propose_surface_pg.py tests/test_propose_surface_ws_door.py -q
```

- [ ] **Step 9: Commit the checkpoint**

```bash
git add dialectic/api/main.py dialectic/transport/handlers.py dialectic/tests/test_message_rest_contracts.py dialectic/tests/test_collaboration_contracts.py dialectic/tests/test_propose_surface_pg.py JOURNAL.md
git commit -m "fix(dialectic): unify persisted message delivery"
```

### Task 5: Correct unread counts, attachment reuse, and startup failure

**Files:**
- Create: `dialectic/tests/test_notification_counts_pg.py`
- Create: `dialectic/tests/test_startup_failure.py`
- Modify: `dialectic/api/notifications/service.py`
- Modify: `dialectic/api/attachments.py`
- Modify: `dialectic/tests/test_attachments.py`
- Modify: `dialectic/api/main.py`

**Interfaces:**
- Consumes: current `message_receipts`, attachments schema, and FastAPI lifespan.
- Produces: correct unread queries, uploader-safe reusable rows, and hard startup failure when PostgreSQL is unavailable.

- [ ] **Step 1: Write real-PostgreSQL unread tests**

```python
async def test_llm_message_counts_but_self_and_system_do_not(db: asyncpg.Connection) -> None:
    assert await calculate_badge_count(db, str(VIEWER)) == 1
    assert await get_room_unread_count(db, str(VIEWER), str(ROOM)) == 1
    assert await get_all_room_unread_counts(db, str(VIEWER)) == {str(ROOM): 1}
```

The fixture inserts one NULL-user `llm_primary`, one viewer-authored human, one other-user human already read, and one lowercase `system` message.

- [ ] **Step 2: Run and observe the LLM omission/system inclusion**

```bash
cd dialectic
python3 -m pytest tests/test_notification_counts_pg.py -q
```

- [ ] **Step 3: Apply the exact predicates to all three queries**

```sql
AND m.user_id IS DISTINCT FROM $1
AND m.speaker_type != 'system'
```

Use the correct positional parameter in the per-room query.

- [ ] **Step 4: Write attachment dedup regression tests**

```python
def test_same_bytes_from_another_uploader_get_a_bindable_row(ctx) -> None:
    first = upload_as(ctx, MEMBER_ID, make_png()).json()
    second = upload_as(ctx, OTHER_MEMBER_ID, make_png()).json()
    assert second["id"] != first["id"]
    assert second["storage_path"] == first["storage_path"]
    assert bind_as(ctx, OTHER_MEMBER_ID, second["id"]).status_code == 200


def test_same_uploader_reupload_after_bind_gets_a_fresh_row(ctx) -> None:
    first = upload(ctx, make_png(), "chart.png", "image/png").json()
    bind_as(ctx, MEMBER_ID, first["id"])
    second = upload(ctx, make_png(), "chart.png", "image/png").json()
    assert second["id"] != first["id"]
    assert second["message_id"] is None
```

- [ ] **Step 5: Run and observe unusable-row reuse**

```bash
python3 -m pytest tests/test_attachments.py -q
```

- [ ] **Step 6: Restrict the dedup query**

```sql
SELECT * FROM attachments
WHERE room_id = $1
  AND sha256 = $2
  AND uploader_user_id = $3
  AND message_id IS NULL
ORDER BY created_at ASC
LIMIT 1
```

If no reusable row exists, keep the shared content-addressed path and insert a new row.

- [ ] **Step 7: Write and run the startup-failure test**

```python
async def test_database_pool_failure_aborts_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncpg, "create_pool", AsyncMock(side_effect=OSError("postgres down")))
    with pytest.raises(OSError, match="postgres down"):
        async with main_mod.lifespan(main_mod.app):
            pass
```

```bash
python3 -m pytest tests/test_startup_failure.py -q
```

- [ ] **Step 8: Replace fake demo mode with log-and-reraise**

```python
except Exception:
    logger.exception("Database connection failed; aborting startup")
    raise
```

- [ ] **Step 9: Run the complete task gate**

```bash
python3 -m pytest tests/test_notification_counts_pg.py tests/test_attachments.py tests/test_startup_failure.py -q
```

- [ ] **Step 10: Commit the checkpoint**

```bash
git add dialectic/api/notifications/service.py dialectic/api/attachments.py dialectic/api/main.py dialectic/tests/test_notification_counts_pg.py dialectic/tests/test_attachments.py dialectic/tests/test_startup_failure.py JOURNAL.md
git commit -m "fix(dialectic): preserve local data truth"
```

### Task 6: Add the durable external-operation ledger

**Files:**
- Create: `dialectic/migrations/018_external_operations.sql`
- Create: `dialectic/api/external_operations.py`
- Create: `dialectic/tests/test_external_operations_pg.py`
- Modify: `dialectic/schema.sql`

**Interfaces:**
- Produces: `ExternalOperation`, `OperationBusy`, `claim_operation`, `succeed_operation`, and `fail_operation`.
- Consumes: `asyncpg.Pool` for claim/failure, `asyncpg.Connection` for caller-owned success transactions, stable operation key, room/kind/user, optional message/slot, and JSON-serializable result.

- [ ] **Step 1: Write schema and claim-state tests before the migration**

```python
async def test_concurrent_claim_has_one_owner(pool: asyncpg.Pool) -> None:
    first, second = await asyncio.gather(
        claim_operation(pool, room_id=ROOM, kind="prediction", operation_key="message:proposal", initiated_by=AMO, source_message_id=MESSAGE, proposal_slot="proposal"),
        claim_operation(pool, room_id=ROOM, kind="prediction", operation_key="message:proposal", initiated_by=DAN, source_message_id=MESSAGE, proposal_slot="proposal"),
        return_exceptions=True,
    )
    assert sum(isinstance(value, ExternalOperation) for value in (first, second)) == 1
    assert sum(isinstance(value, OperationBusy) for value in (first, second)) == 1


async def test_expired_claim_reuses_original_actor_and_key(pool: asyncpg.Pool) -> None:
    reclaimed = await claim_operation(pool, room_id=ROOM, kind="prediction", operation_key="message:proposal", initiated_by=DAN, source_message_id=MESSAGE, proposal_slot="proposal", now=LEASE_EXPIRED_AT)
    assert reclaimed.initiated_by == AMO
    assert reclaimed.operation_key == "message:proposal"
```

- [ ] **Step 2: Run and observe missing table/module failures**

```bash
cd dialectic
python3 -m pytest tests/test_external_operations_pg.py -q
```

- [ ] **Step 3: Add the additive schema**

```sql
CREATE TABLE IF NOT EXISTS external_operations (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    operation_kind TEXT NOT NULL,
    operation_key TEXT NOT NULL UNIQUE,
    initiated_by_user_id UUID NOT NULL REFERENCES users(id),
    source_message_id UUID REFERENCES messages(id) ON DELETE CASCADE,
    proposal_slot TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 1,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    external_result JSONB,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((source_message_id IS NULL) = (proposal_slot IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_operations_message_slot
ON external_operations(source_message_id, proposal_slot)
WHERE source_message_id IS NOT NULL AND proposal_slot IS NOT NULL;
```

Put the same table/index in `schema.sql`.

- [ ] **Step 4: Implement typed claim/succeed/fail operations**

```python
@dataclass(frozen=True)
class ExternalOperation:
    id: UUID
    room_id: UUID
    operation_kind: str
    operation_key: str
    initiated_by: UUID
    status: str
    source_message_id: UUID | None
    proposal_slot: str | None
    external_result: dict | None


async def claim_operation(
    pool: asyncpg.Pool,
    *,
    room_id: UUID,
    kind: str,
    operation_key: str,
    initiated_by: UUID,
    source_message_id: UUID | None = None,
    proposal_slot: str | None = None,
    now: datetime | None = None,
) -> ExternalOperation:
    """Claim, resume, or return one durable external operation."""
```

The claim transaction inserts once, returns succeeded rows immediately, raises `OperationBusy` for unexpired pending rows, and reclaims failed/expired rows without changing `initiated_by_user_id` or `operation_key`. Use a fixed 120-second lease.

`succeed_operation(db: asyncpg.Connection, operation: ExternalOperation, *, result: dict) -> None` does not open or commit a transaction. It stamps proposal metadata when the operation has a message coordinate, skips that stamp for thesis operations, and updates status/result. The endpoint wraps it with its entity-specific local writes in one caller-owned transaction. `fail_operation(pool: asyncpg.Pool, operation: ExternalOperation, *, error: str) -> None` records a bounded 500-character error and status `failed` in a short transaction.

- [ ] **Step 5: Run migration and operation tests**

```bash
psql "${DIALECTIC_TEST_DATABASE_URL:-postgresql://root@localhost/dialectic_test}" -f migrations/018_external_operations.sql
python3 -m pytest tests/test_external_operations_pg.py -q
```

- [ ] **Step 6: Commit the checkpoint**

```bash
git add dialectic/migrations/018_external_operations.sql dialectic/schema.sql dialectic/api/external_operations.py dialectic/tests/test_external_operations_pg.py JOURNAL.md
git commit -m "feat(dialectic): ledger external operations"
```

### Task 7: Make tradingDesk predictions and resolutions idempotent

**Files:**
- Create: `trading/web/persistence/sql/006_dialectic_idempotency.sql`
- Modify: `trading/web/models.py`
- Modify: `trading/web/persistence/repository.py`
- Modify: `trading/web/persistence/test_persistence.py`
- Modify: `trading/web/routes/predictions.py`
- Modify: `trading/web/test_web.py`

**Interfaces:**
- Consumes: optional `source_key` on `PredictionCreate` and required `source_key` on Dialectic resolution requests.
- Produces: `Repository.save_prediction_once(user: str, prediction: dict) -> tuple[dict, bool]` and `Repository.resolve_prediction_once(prediction_id: str, resolution: str, source_key: str | None) -> tuple[dict | None, bool]`.

- [ ] **Step 1: Write migration and repository idempotency tests**

```python
def test_same_prediction_source_returns_one_row(repo: Repository) -> None:
    payload = {"statement": "Brent over 90", "confidence": 0.7, "deadline": "2026-09-30", "source_key": "dialectic:m1:proposal"}
    first, first_created = repo.save_prediction_once("amo", payload)
    second, second_created = repo.save_prediction_once("amo", payload)
    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert len(repo.list_predictions()) == 1
    assert "source_key" not in first
    assert "resolution_source_key" not in first


def test_conflicting_second_resolution_is_rejected(repo: Repository) -> None:
    prediction, _ = repo.save_prediction_once("amo", PREDICTION)
    repo.resolve_prediction_once(prediction["id"], "correct", "dialectic:resolve:p1")
    with pytest.raises(PredictionResolutionConflict):
        repo.resolve_prediction_once(prediction["id"], "incorrect", "dialectic:resolve:p2")
```

- [ ] **Step 2: Run and observe missing migration and methods**

```bash
cd trading
python3 -m pytest web/persistence/test_persistence.py -q
```

- [ ] **Step 3: Add SQLite migration 006**

```sql
ALTER TABLE predictions ADD COLUMN source_key TEXT;
ALTER TABLE predictions ADD COLUMN resolution_source_key TEXT;
CREATE UNIQUE INDEX idx_predictions_source_key ON predictions(source_key) WHERE source_key IS NOT NULL;
CREATE UNIQUE INDEX idx_predictions_resolution_source_key ON predictions(resolution_source_key) WHERE resolution_source_key IS NOT NULL;
```

Update the migration-count assertion from 5 to 6.

- [ ] **Step 4: Add optional model fields and atomic repository methods**

```python
class PredictionCreate(BaseModel):
    statement: str
    confidence: float
    deadline: str
    linked_book_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source_key: Optional[str] = None


class PredictionResolve(BaseModel):
    resolution: Literal["correct", "incorrect"]
    source_key: Optional[str] = None
```

On duplicate `source_key`, fetch and return the existing row with `created=False`. On the same resolution key/verdict return `changed=False`; on any different verdict after resolution raise the domain conflict.

`_prediction_from_row` removes `source_key` and `resolution_source_key` before returning the public dictionary. Add `assert "source_key" not in first` and `assert "resolution_source_key" not in first` to the repository and route tests.

- [ ] **Step 5: Write and run route broadcast tests**

```python
def test_duplicate_prediction_source_broadcasts_once(client, manager) -> None:
    first = client.post("/api/predictions", json=PREDICTION_WITH_SOURCE)
    second = client.post("/api/predictions", json=PREDICTION_WITH_SOURCE)
    assert first.json()["id"] == second.json()["id"]
    assert manager.broadcast_count == 1
```

```bash
python3 -m pytest web/test_web.py web/persistence/test_persistence.py -q
```

- [ ] **Step 6: Commit the checkpoint**

```bash
git add trading/web/persistence/sql/006_dialectic_idempotency.sql trading/web/models.py trading/web/persistence/repository.py trading/web/persistence/test_persistence.py trading/web/routes/predictions.py trading/web/test_web.py JOURNAL.md
git commit -m "fix(trading): make prediction writes idempotent"
```

### Task 8: Make room-bound thesis creation idempotent

**Files:**
- Modify: `trading/web/routes/builder.py`
- Modify: `trading/web/routes/test_builder.py`

**Interfaces:**
- Consumes: `SaveBookRequest.meta.dialecticRoomId`.
- Produces: `find_book_for_dialectic_room(room_id: str) -> dict | None`; duplicate bound creates return the existing book response.

- [ ] **Step 1: Write the failing repeated and concurrent create tests**

```python
def test_repeated_bound_create_returns_the_same_book(client) -> None:
    first = client.post("/api/thesis/builder/books", json=BOUND_BOOK).json()
    second = client.post("/api/thesis/builder/books", json=BOUND_BOOK).json()
    assert second["id"] == first["id"]
    assert len(list(BOOKS_DIR.glob("*-graph.json"))) == 1


def test_concurrent_bound_create_writes_one_book(client) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post("/api/thesis/builder/books", json=BOUND_BOOK), range(2)))
    assert {response.json()["id"] for response in responses} == {responses[0].json()["id"]}
```

- [ ] **Step 2: Run and observe two book IDs/files**

```bash
cd trading
python3 -m pytest web/routes/test_builder.py -q
```

- [ ] **Step 3: Lock scan, decision, and atomic write**

```python
_BOUND_BOOK_CREATE_LOCK = threading.Lock()


def find_book_for_dialectic_room(room_id: str) -> dict | None:
    for path in sorted(BOOKS_DIR.glob("*.json")):
        config = json.loads(path.read_text())
        if config.get("meta", {}).get("dialecticRoomId") == room_id:
            return {"id": path.stem, "filename": path.name}
    return None
```

For a nonempty room ID, enter the lock, return an existing match, otherwise perform the current slug/collision/atomic-write path before releasing it. Unbound book behavior remains unchanged.

- [ ] **Step 4: Run builder and room-link tests**

```bash
python3 -m pytest web/routes/test_builder.py web/test_book_room_link.py -q
```

- [ ] **Step 5: Commit the checkpoint**

```bash
git add trading/web/routes/builder.py trading/web/routes/test_builder.py JOURNAL.md
git commit -m "fix(trading): deduplicate room-bound theses"
```

### Task 9: Route every external move through the ledger without holding a connection

**Files:**
- Modify: `dialectic/api/prediction_relay.py`
- Modify: `dialectic/api/reading_relay.py`
- Modify: `dialectic/api/thesis_relay.py`
- Modify: `dialectic/api/trading_relay.py`
- Modify: `dialectic/tests/test_prediction_relay_endpoint.py`
- Modify: `dialectic/tests/test_prediction_resolve_accept.py`
- Modify: `dialectic/tests/test_reading_relay_endpoint.py`
- Modify: `dialectic/tests/test_thesis_relay_endpoint.py`
- Create: `dialectic/tests/test_relay_connection_lifetime.py`

**Interfaces:**
- Consumes: Task 6 ledger functions and Task 7/8 downstream idempotency contracts.
- Produces: stable keys `prediction:{message_id}:proposal`, `resolution:{message_id}:resolution_proposal`, `reading:{message_id}:reading_proposal`, and `thesis:{room_id}`.

- [ ] **Step 1: Write failing duplicate/crash/lifetime tests**

```python
async def test_duplicate_prediction_accept_posts_once_and_returns_recorded_result() -> None:
    first, second = await asyncio.gather(call_accept(), call_accept())
    assert sorted((first.status_code, second.status_code)) == [200, 409]
    td_post.assert_awaited_once()
    replay = await call_accept()
    successful = first if first.status_code == 200 else second
    assert replay.status_code == 200
    assert replay.json()["id"] == successful.json()["id"]


async def test_network_wait_holds_no_pool_connection() -> None:
    await call_quotes_while_http_blocks()
    assert pool.checked_out_during_http == 0


async def test_retry_after_finalize_crash_preserves_original_actor() -> None:
    await external_write_then_crash_before_finalize(actor=AMO)
    response = await retry_accept(actor=DAN, after_lease_expiry=True)
    assert response.status_code == 200
    assert await accepted_by() == AMO
```

- [ ] **Step 2: Run and observe duplicate posts and held connections**

```bash
cd dialectic
python3 -m pytest tests/test_prediction_relay_endpoint.py tests/test_prediction_resolve_accept.py tests/test_reading_relay_endpoint.py tests/test_thesis_relay_endpoint.py tests/test_relay_connection_lifetime.py -q
```

- [ ] **Step 3: Replace connection-yielding dependencies with pool dependencies**

```python
async def get_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("prediction relay database pool is not initialized")
    return _db_pool
```

Acquire for authorization/validation/claim, release for HTTP, acquire for success/failure finalize. Apply the same lifecycle to all trading-relay network endpoints.

- [ ] **Step 4: Pass stable downstream keys and recorded results**

```python
operation = await claim_operation(
    pool,
    room_id=room_id,
    kind="prediction",
    operation_key=f"prediction:{request.message_id}:proposal",
    initiated_by=current_user.user_id,
    source_message_id=request.message_id,
    proposal_slot="proposal",
)
if operation.status == "succeeded":
    return operation.external_result
created = await td.post("/api/predictions", json_body={**body, "source_key": operation.operation_key})
async with pool.acquire() as db:
    async with db.transaction():
        await succeed_operation(db, operation, result=created)
```

Resolution includes its source key in the body. Reading calls `save_reading` and `succeed_operation` on the same connection and transaction after Defuddle returns. Thesis uses `thesis:{room_id}` and no message coordinate; its room link, event, and operation success share one local transaction.

- [ ] **Step 5: Record failures without swallowing them**

```python
except td.TradingDeskError as exc:
    await fail_operation(pool, operation, error=str(exc))
    raise HTTPException(status_code=502, detail=f"tradingDesk refused the prediction: {exc}")
```

- [ ] **Step 6: Run relay and projection tests**

```bash
python3 -m pytest tests/test_prediction_relay_endpoint.py tests/test_prediction_resolve_accept.py tests/test_reading_relay_endpoint.py tests/test_thesis_relay_endpoint.py tests/test_relay_connection_lifetime.py tests/test_proposal_envelope_pg.py tests/test_workspace_objects_pg.py -q
```

- [ ] **Step 7: Commit the checkpoint**

```bash
git add dialectic/api/prediction_relay.py dialectic/api/reading_relay.py dialectic/api/thesis_relay.py dialectic/api/trading_relay.py dialectic/tests/test_prediction_relay_endpoint.py dialectic/tests/test_prediction_resolve_accept.py dialectic/tests/test_reading_relay_endpoint.py dialectic/tests/test_thesis_relay_endpoint.py dialectic/tests/test_relay_connection_lifetime.py JOURNAL.md
git commit -m "fix(dialectic): make external moves recoverable"
```

### Task 10: Replace invalid ancestry pagination with opaque cursors

**Files:**
- Create: `dialectic/tests/test_message_ancestry_pagination_pg.py`
- Modify: `dialectic/api/main.py`
- Modify: `dialectic/schema.sql` only if EXPLAIN proves an index is required
- Modify: `dialectic/migrations/018_external_operations.sql` only if the same evidence proves an index is required

**Interfaces:**
- Produces: `encode_message_cursor(created_at: datetime, message_id: UUID) -> str` and `decode_message_cursor(cursor: str) -> tuple[datetime, UUID]` plus additive response fields.
- Consumes: URL-safe base64 cursor text and recursive ancestry CTE.

- [ ] **Step 1: Write cursor codec and cross-thread window tests**

```python
def test_cursor_round_trip_is_url_safe() -> None:
    cursor = encode_message_cursor(CREATED_AT, MESSAGE_ID)
    assert "+" not in cursor and "/" not in cursor and "=" not in cursor
    assert decode_message_cursor(cursor) == (CREATED_AT, MESSAGE_ID)


async def test_ancestry_pages_are_stable_with_duplicate_thread_sequences(client) -> None:
    first = client.get(f"/threads/{CHILD}/messages?limit=2").json()
    second = client.get(f"/threads/{CHILD}/messages?limit=2&before_cursor={first['oldest_cursor']}").json()
    assert ids(first) == [M3, M4]
    assert ids(second) == [M1, M2]
    assert set(ids(first)).isdisjoint(ids(second))


def test_sequence_cursor_with_ancestry_is_rejected(client) -> None:
    response = client.get(f"/threads/{CHILD}/messages?before_sequence=3")
    assert response.status_code == 422


def test_ancestry_response_does_not_claim_one_thread_sequence_is_global(client) -> None:
    body = client.get(f"/threads/{CHILD}/messages?limit=2").json()
    assert body["oldest_sequence"] is None
    assert body["newest_sequence"] is None
```

- [ ] **Step 2: Run and observe duplicate/incorrect windows and missing fields**

```bash
cd dialectic
python3 -m pytest tests/test_message_ancestry_pagination_pg.py -q
```

- [ ] **Step 3: Add strict codec and additive API fields**

```python
def encode_message_cursor(created_at: datetime, message_id: UUID) -> str:
    raw = f"{created_at.astimezone(timezone.utc).isoformat()}|{message_id}".encode()
    return urlsafe_b64encode(raw).decode().rstrip("=")


def decode_message_cursor(cursor: str) -> tuple[datetime, UUID]:
    padding = "=" * (-len(cursor) % 4)
    decoded = urlsafe_b64decode(cursor + padding).decode()
    timestamp, message_id = decoded.rsplit("|", 1)
    return datetime.fromisoformat(timestamp), UUID(message_id)
```

Malformed cursors raise HTTP 422 with `Invalid message cursor`.

- [ ] **Step 4: Move cursor, order, and LIMIT + 1 into SQL**

Use `(m.created_at, m.id)` ordering and tuple comparison in the recursive CTE result. Fetch `limit + 1`, remove the sentinel, reverse descending database rows before returning chronological response order, and derive one continuation flag from the sentinel; probe the opposite direction with `EXISTS` using the page edge. Do not construct the full ancestry list in Python. Set the legacy sequence summary fields to `None` for ancestry pages because no one integer orders several threads.

```sql
ORDER BY m.created_at DESC, m.id DESC
LIMIT $4
```

- [ ] **Step 5: Prove or reject additional indexes**

Add `test_ancestry_query_plan_records_current_indexes` to the PostgreSQL test.
It runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` by prefixing the exact query
constant used by the endpoint, prints the JSON plan under `pytest -s`, and asserts
the returned message rows remain bounded by `limit + 1`. Add a partial index only
if the captured plan shows an avoidable scan attributable to a missing index;
otherwise leave migration 018 unchanged.

```bash
python3 -m pytest tests/test_message_ancestry_pagination_pg.py::test_ancestry_query_plan_records_current_indexes -q -s
```

- [ ] **Step 6: Run ancestry, thread-history, and search tests**

```bash
python3 -m pytest tests/test_message_ancestry_pagination_pg.py tests/test_message_rest_contracts.py -q
```

- [ ] **Step 7: Commit the checkpoint**

```bash
git add dialectic/api/main.py dialectic/tests/test_message_ancestry_pagination_pg.py dialectic/schema.sql dialectic/migrations/018_external_operations.sql JOURNAL.md
git commit -m "fix(dialectic): bound ancestry pagination"
```

### Task 11: Make the iPad shell explicit, safe-area aware, and non-duplicative

**Files:**
- Modify: `dialectic/frontend/app/src/stores/appStore.ts`
- Modify: `dialectic/frontend/app/src/stores/appStore.test.ts`
- Modify: `dialectic/frontend/app/src/components/layout/AppLayout.tsx`
- Modify: `dialectic/frontend/app/src/components/layout/AppLayout.css`
- Modify: `dialectic/frontend/app/src/components/layout/RoomHeader.tsx`
- Modify: `dialectic/frontend/app/src/components/layout/RoomHeader.css`
- Modify: `dialectic/frontend/app/src/components/sidebar/RightPanel.tsx`
- Modify: `dialectic/frontend/app/src/components/sidebar/RightPanel.css`
- Modify: `dialectic/frontend/app/src/components/sidebar/RightPanel.test.tsx`

**Interfaces:**
- Produces: `rightPanelOpen: boolean`, `setRightPanelOpen(open: boolean) -> void`; `setRightPanelTab(tab)` also opens the panel.
- Consumes: existing `mobileDrawer` state for overlay drawers.

- [ ] **Step 1: Write failing store and panel tests**

```tsx
it('starts with the desktop context rail closed and opens it when a tab is requested', () => {
  expect(useAppStore.getState().rightPanelOpen).toBe(false)
  useAppStore.getState().setRightPanelTab('threads')
  expect(useAppStore.getState().rightPanelOpen).toBe(true)
})


it('never offers the duplicate Users tab or falls back to it', () => {
  useAppStore.setState({ rightPanelTab: 'memory', rightPanelOpen: true })
  render(<RightPanel {...props} isHome={false} scene="record" />)
  expect(screen.queryByRole('button', { name: 'Users' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Branches' })).toHaveClass('active')
})
```

- [ ] **Step 2: Run and observe default-open grid and Users fallback**

```bash
cd dialectic/frontend/app
npm test -- --run src/stores/appStore.test.ts src/components/sidebar/RightPanel.test.tsx
```

- [ ] **Step 3: Add explicit panel state and remove Users from the rail**

```typescript
rightPanelOpen: false,
setRightPanelOpen: (open) => set({ rightPanelOpen: open }),
setRightPanelTab: (tab) => set({ rightPanelTab: tab, rightPanelOpen: true }),
```

Remove the `UsersPanel` import, its render branch, and the `users` tab. Keep the
`users` prop because Home settings consumes the resident list, and keep
`ParticipantsBar` unchanged. When a stored tab is unavailable, choose the first
actual contextual tab (`threads` in Record), never Users.

- [ ] **Step 4: Write layout class and drawer tests**

```tsx
it('does not reserve a desktop context column while the panel is closed', () => {
  useAppStore.setState({ rightPanelOpen: false })
  const { container } = render(<AppLayout sidebar={<div />} main={<div />} rightPanel={<div />} />)
  expect(container.firstChild).toHaveClass('right-panel-closed')
})
```

- [ ] **Step 5: Apply one-column/tablet and explicit desktop geometry**

```css
.app-layout {
    --safe-top: env(safe-area-inset-top, 0px);
    --safe-right: env(safe-area-inset-right, 0px);
    --safe-bottom: env(safe-area-inset-bottom, 0px);
    --safe-left: env(safe-area-inset-left, 0px);
    grid-template-columns: 260px minmax(0, 1fr) 300px;
    padding: var(--safe-top) var(--safe-right) var(--safe-bottom) var(--safe-left);
}
.app-layout.right-panel-closed { grid-template-columns: 260px minmax(0, 1fr); }
.app-layout.right-panel-closed .app-right-panel { display: none; }

@media (max-width: 1279.98px) {
    .app-layout,
    .app-layout.right-panel-closed { grid-template-columns: minmax(0, 1fr); }
    .app-sidebar,
    .app-right-panel { position: fixed; top: var(--safe-top); bottom: var(--safe-bottom); }
}
```

Drawer scrim uses all safe-area-adjusted edges and toggles are available below 1280. The desktop panel button toggles `rightPanelOpen`; the small-width button toggles `mobileDrawer='panel'`.

- [ ] **Step 6: Add active-tab semantics and styling**

```tsx
<button
  className={`sidebar-tab-btn${activeTab === tab.id ? ' active' : ''}`}
  aria-selected={activeTab === tab.id}
  role="tab"
>
```

```css
.sidebar-tab-btn.active {
    color: var(--color-bone);
    border-bottom-color: var(--color-amber);
}
```

Set `role="tablist"` on `.sidebar-tabs` and `role="tabpanel"` plus an accessible
name on the active panel.

- [ ] **Step 7: Run layout/store/panel tests and build**

```bash
npm test -- --run src/stores/appStore.test.ts src/components/sidebar/RightPanel.test.tsx src/components/layout
npm run lint
npm run build
```

- [ ] **Step 8: Commit the checkpoint**

```bash
git add dialectic/frontend/app/src/stores/appStore.ts dialectic/frontend/app/src/stores/appStore.test.ts dialectic/frontend/app/src/components/layout/AppLayout.tsx dialectic/frontend/app/src/components/layout/AppLayout.css dialectic/frontend/app/src/components/layout/RoomHeader.tsx dialectic/frontend/app/src/components/layout/RoomHeader.css dialectic/frontend/app/src/components/sidebar/RightPanel.tsx dialectic/frontend/app/src/components/sidebar/RightPanel.css dialectic/frontend/app/src/components/sidebar/RightPanel.test.tsx JOURNAL.md
git commit -m "fix(frontend): give the work surface back to iPad"
```

### Task 12: Enforce readable scenes, controls, contrast, and touch targets

**Files:**
- Modify: `dialectic/frontend/app/src/components/workspace/SceneSwitcher.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/SceneSwitcher.css`
- Modify: `dialectic/frontend/app/src/components/workspace/WorkspaceSceneFrame.test.tsx`
- Modify: `dialectic/frontend/app/src/styles/tokens.css`
- Modify rendered-type violations in:
  - `dialectic/frontend/app/src/components/analytics/AnalyticsPanel.css`
  - `dialectic/frontend/app/src/components/analytics/BriefingPanel.css`
  - `dialectic/frontend/app/src/components/analytics/DNAGlyph.css`
  - `dialectic/frontend/app/src/components/analytics/IdentityViewer.css`
  - `dialectic/frontend/app/src/components/auth/AuthScreen.css`
  - `dialectic/frontend/app/src/components/auth/RoomSelector.css`
  - `dialectic/frontend/app/src/components/chat/MessageAttachments.css`
  - `dialectic/frontend/app/src/components/chat/MessageBubble.css`
  - `dialectic/frontend/app/src/components/chat/MessageInput.css`
  - `dialectic/frontend/app/src/components/chat/MessageList.css`
  - `dialectic/frontend/app/src/components/chat/ParticipantsBar.css`
  - `dialectic/frontend/app/src/components/chat/ProposeMenu.css`
  - `dialectic/frontend/app/src/components/chat/SearchOverlay.css`
  - `dialectic/frontend/app/src/components/chat/SignatureMark.css`
  - `dialectic/frontend/app/src/components/chat/TypingIndicator.css`
  - `dialectic/frontend/app/src/components/home/HouseMovement.css`
  - `dialectic/frontend/app/src/components/layout/CapabilityMap.css`
  - `dialectic/frontend/app/src/components/protocols/ProtocolBanner.css`
  - `dialectic/frontend/app/src/components/protocols/ProtocolPicker.css`
  - `dialectic/frontend/app/src/components/replay/ReplayTimeline.css`
  - `dialectic/frontend/app/src/components/sidebar/MemoryPanel.css`
  - `dialectic/frontend/app/src/components/sidebar/RightPanel.css`
  - `dialectic/frontend/app/src/components/sidebar/RoomList.css`
  - `dialectic/frontend/app/src/components/sidebar/SharePanel.css`
  - `dialectic/frontend/app/src/components/sidebar/UsersPanel.css`
  - `dialectic/frontend/app/src/components/stakes/CommitmentCard.css`
  - `dialectic/frontend/app/src/components/stakes/CommitmentDashboard.css`
  - `dialectic/frontend/app/src/components/stakes/CommitmentSurface.css`
  - `dialectic/frontend/app/src/components/trading/ThesisDag.css`
  - `dialectic/frontend/app/src/components/trading/TradingPanel.css`
  - `dialectic/frontend/app/src/components/trading/cockpit.css`
  - `dialectic/frontend/app/src/components/workspace/SceneEmpty.css`
  - `dialectic/frontend/app/src/components/workspace/SceneSwitcher.css`
  - `dialectic/frontend/app/src/components/workspace/WorkspaceObjectList.css`
  - `dialectic/frontend/app/src/components/workspace/focus/Focus.css`
  - `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.css`
  - `dialectic/frontend/app/src/components/workspace/scenes/FieldScene.css`
  - `dialectic/frontend/app/src/styles/global.css`
- Create: `docs/superpowers/acceptance/2026-08-15-big-bang-browser-acceptance.py`

**Interfaces:**
- Produces: primary scene buttons plus an accessible `More views` control below 1280; full-document acceptance results.
- Consumes: current scene order and existing Release 3 browser fixture.

- [ ] **Step 1: Write failing scene-overflow tests**

```tsx
it('keeps all seven scenes reachable through primary actions and More views', async () => {
  render(<SceneSwitcher scene="record" scenes={IMPLEMENTED_WORKSPACE_SCENES} onSelect={onSelect} />)
  await user.click(screen.getByRole('button', { name: 'More views' }))
  for (const name of ['House', 'Record', 'Bench', 'Field', 'Library', 'Ledger', 'Atlas']) {
    expect(screen.getAllByRole(/button|menuitem/).some((node) => node.textContent === name)).toBe(true)
  }
})
```

- [ ] **Step 2: Run and observe the missing overflow control**

```bash
cd dialectic/frontend/app
npm test -- --run src/components/workspace/WorkspaceSceneFrame.test.tsx
```

- [ ] **Step 3: Implement primary plus overflow navigation**

Keep the canonical array unchanged. Give House/Record/Bench/Field the
`scene-switcher-primary` class when present and the remaining buttons
`scene-switcher-secondary`. Below 1280, CSS hides only the secondary buttons and
reveals a native `<details>` overflow containing those same offered destinations.
If the active scene is in overflow, the summary text becomes
`More views · <scene>` and the chosen menu button retains `aria-current`.

```tsx
<details className="scene-switcher-more">
  <summary>
    {overflow.includes(scene) ? `More views · ${SCENE_LABELS[scene]}` : 'More views'}
  </summary>
  <div role="menu">
    {overflow.map((candidate) => (
      <button key={candidate} role="menuitem" aria-current={candidate === scene ? 'page' : undefined} onClick={() => onSelect(candidate)}>
        {SCENE_LABELS[candidate]}
      </button>
    ))}
  </div>
</details>
```

- [ ] **Step 4: Write the acceptance harness before CSS changes**

The new harness copies the current fixture startup and cache-clearing logic but runs axe against `document`, not `.messages-wrapper`. It fails if any visible actionable element has computed font below 12px, bounding width or height below 44px, normal text contrast below 4.5:1, horizontal overflow, status-bar overlap, inaccessible active tab, or an unreachable scene.

Resolve `axe.min.js` from the worktree with
`Path(__file__).resolve().parents[3] / "dialectic/frontend/app/node_modules/axe-core/axe.min.js"`.
Write screenshots to `/tmp/dialectic-big-bang-acceptance`; do not create or stage a
generated screenshot tree in the repository.

```python
def shell_metrics(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('button, a[href], select, input, textarea'))
      .filter(node => node.getClientRects().length > 0)
      .map(node => {
        const rect = node.getBoundingClientRect()
        return {label: node.getAttribute('aria-label') || node.textContent.trim(), width: rect.width, height: rect.height, fontSize: parseFloat(getComputedStyle(node).fontSize)}
      })""")
```

- [ ] **Step 5: Run the harness and capture the expected failures**

Start only the isolated fixture from the implementation worktree. The backend
uses `dialectic_browser` on 8013 with scheduler disabled; Vite preview uses 4173.

```bash
WORKTREE_ROOT=$(git rev-parse --show-toplevel)
cd "$WORKTREE_ROOT/dialectic"
export DATABASE_URL='postgresql://localhost/dialectic_browser'
export JWT_SECRET_KEY='browser-big-bang-secret-32-bytes-minimum'
export ANTHROPIC_API_KEY='browser-fixture-dummy-key'
export SIGNUPS_ENABLED=1
export SCHEDULER_ENABLED=0
export PORT=8013
python3 run.py
```

In a second terminal/session:

```bash
WORKTREE_ROOT=$(git rev-parse --show-toplevel)
cd "$WORKTREE_ROOT/dialectic/frontend/app"
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run build
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run preview -- --port 4173
```

The harness unregisters the service worker and clears Cache Storage before its
first assertion.

```bash
python3 docs/superpowers/acceptance/2026-08-15-big-bang-browser-acceptance.py
```

Expected: failures include current 9–11px controls, low-contrast ghost tabs, undersized targets, and 1024px rail geometry.

- [ ] **Step 6: Raise only rendered controls and ordinary copy**

Use 12px/44px for actionable chrome and 14px for ordinary prose. Decorative signature marks and non-semantic rule labels may remain smaller only when the browser harness excludes them because they are neither controls nor ordinary copy.

```css
.sidebar-tab-btn,
.scene-switcher-action,
.scene-switcher-more summary,
.scene-switcher-more [role="menuitem"] {
    min-height: 44px;
    font-size: 12px;
    color: var(--color-secondary);
}
.sidebar-panel,
.scene-body { font-size: 14px; }
```

Adjust token values or component colors so computed normal-text contrast is at least 4.5:1 on cacao/obsidian. Do not brighten structural hairlines or decorative marks solely to satisfy a text rule that does not apply to them.

- [ ] **Step 7: Run frontend tests, lint, build, and five-width browser gate**

```bash
npm test -- --run
npm run lint
npm run build
cd ../../../..
python3 docs/superpowers/acceptance/2026-08-15-big-bang-browser-acceptance.py
```

Open and inspect every generated phone, iPad portrait, iPad landscape, laptop, and wide-desktop PNG. Record visual observations in `JOURNAL.md`; measurement alone is not render proof.

- [ ] **Step 8: Commit the checkpoint**

```bash
git add dialectic/frontend/app/src docs/superpowers/acceptance/2026-08-15-big-bang-browser-acceptance.py JOURNAL.md
git commit -m "fix(frontend): make every workroom surface readable"
```

### Task 13: Reconcile current-state authority

**Files:**
- Modify: `dialectic/README.md`
- Modify: `dialectic/CLAUDE.md`
- Modify: `dialectic/TODOS.md`
- Modify: `PLAN.md`
- Modify: `dialectic/deploy/dialectic.service`
- Modify: `docs/audits/2026-08-13-dialectic-human-interaction-surface-audit.md`
- Modify: `JOURNAL.md`

**Interfaces:**
- Consumes: observed post-change migration number, tool count, test collection, service structure, and completed task status.
- Produces: one current plan, one active TODO board, durable README commands, and a tracked unit matching the non-secret installed structure.

- [ ] **Step 1: Capture current facts from source and read-only runtime**

```bash
cd dialectic
python3 -m pytest tests/ --collect-only -q | tail -n 2
rg -n 'name="[a-z_]+"' llm/tools.py | wc -l
ls migrations/[0-9][0-9][0-9]_*.sql | sort | tail -1
systemctl cat dialectic.service --no-pager
cd ..
test -f docs/audits/2026-08-13-dialectic-human-interaction-surface-audit.md
```

- [ ] **Step 2: Write a failing authority scan**

```bash
rg -n "913 tests|~1335 tests|migration 017|Release 1 .*awaiting|Release 2 .*awaiting|Release 3 .*awaiting|/opt/dialectic/current" dialectic/README.md dialectic/CLAUDE.md dialectic/TODOS.md PLAN.md dialectic/deploy/dialectic.service
```

Expected before edits: stale volatile counts, shipped-release queue text, and tombstoned `/opt` service paths are found.

- [ ] **Step 3: Make each authority file singular and current**

README retains commands but removes hard-coded totals. CLAUDE records migration 018, the verified tool surface, exact test commands, and the new external-operation contract. TODOS contains only unfinished work and points shipped Release 1–3 history to `PLAN.md`/git. Rewrite the root `PLAN.md` header and status ledger to make this big-bang plan current without deleting Release 3 history. Replace the tracked service unit with the installed non-secret structure:

```ini
[Service]
Type=simple
User=root
WorkingDirectory=/root/DwoodAmo/dialectic
EnvironmentFile=/root/DwoodAmo/dialectic/.env
ExecStart=/usr/bin/python3 run.py
UMask=0077
Restart=always
RestartSec=5
TimeoutStopSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dialectic
```

Do not install or reload the unit.

- [ ] **Step 4: Amend the existing audit status without duplicating it**

Mark each repaired finding as implemented locally, not deployed. Keep browser/device and activation proof explicitly pending.

- [ ] **Step 5: Re-run the authority scan**

```bash
! rg -n "913 tests|~1335 tests|Release 1 .*awaiting|Release 2 .*awaiting|Release 3 .*awaiting|/opt/dialectic/current" dialectic/README.md dialectic/CLAUDE.md dialectic/TODOS.md PLAN.md dialectic/deploy/dialectic.service
systemd-analyze verify dialectic/deploy/dialectic.service
```

- [ ] **Step 6: Commit the checkpoint**

```bash
git add dialectic/README.md dialectic/CLAUDE.md dialectic/TODOS.md PLAN.md dialectic/deploy/dialectic.service docs/audits/2026-08-13-dialectic-human-interaction-surface-audit.md JOURNAL.md
git commit -m "docs(dialectic): restore current-state authority"
```

### Task 14: Run the integrated gate and produce the single implementation commit

**Files:**
- Modify: `JOURNAL.md`
- Review: every path changed since the worktree base.

**Interfaces:**
- Consumes: all task checkpoints.
- Produces: one verified implementation commit and a precise unverified activation ledger.

- [ ] **Step 1: Inspect scope before the expensive gate**

```bash
git status --short
git diff --check
STABILIZATION_BASE_SHA=$(git merge-base HEAD master)
git diff --stat "$STABILIZATION_BASE_SHA"..HEAD
git diff --name-status "$STABILIZATION_BASE_SHA"..HEAD
```

Expected: only planned source, tests, migration, acceptance, authority, and journal paths appear.

- [ ] **Step 2: Run the complete Dialectic gate**

```bash
cd dialectic
python3 -m pytest tests/ -q
```

Record exact passed/failed/skipped counts. A skipped real-PostgreSQL test is not treated as proof; run the named pg tests against `dialectic_test` before completion.

- [ ] **Step 3: Run the complete tradingDesk gate**

```bash
cd ../trading
python3 -m pytest web/ tools/ -q
```

- [ ] **Step 4: Run the complete frontend gate**

```bash
cd ../dialectic/frontend/app
npm test -- --run
npm run lint
npm run build
```

- [ ] **Step 5: Run browser acceptance and inspect every image**

```bash
cd ../../../..
python3 docs/superpowers/acceptance/2026-08-15-big-bang-browser-acceptance.py
```

Record exact assertions, axe findings, widths, screenshots, and human visual observations.

- [ ] **Step 6: Run mutation checks for every repaired boundary**

Temporarily reverse one condition at a time and prove its named test fails: expose the rate arguments, remove caller equality, omit reply field, restore `!=` unread logic, remove uploader filter, disable sequence retry, bypass operation uniqueness, return duplicate trading objects, restore ancestry Python filtering, force desktop rails at 1024, remove safe-top padding, or lower a control to 9px. Revert each temporary mutation with `apply_patch`, rerun the test green, and leave no mutation diff.

```bash
git diff --check
git status --short
```

- [ ] **Step 7: Append the complete verification ledger**

```text
[2026-08-15] completed the local big-bang stabilization gate — record exact backend, tradingDesk, frontend, lint, build, PostgreSQL, browser, axe, screenshot, and mutation results; production migration, restart, deployment, served-asset, and real-device proof remain unauthorized and unverified
```

- [ ] **Step 8: Squash task checkpoints into the approved single implementation commit**

Resolve the exact base first and inspect the checkpoint list. This soft reset changes only branch history and index; it does not discard files.

```bash
STABILIZATION_BASE_SHA=$(git merge-base HEAD master)
git log --oneline "$STABILIZATION_BASE_SHA"..HEAD
git reset --soft "$STABILIZATION_BASE_SHA"
git status --short
git diff --cached --check
git commit -m "fix(dialectic): big-bang production stabilization"
```

- [ ] **Step 9: Verify the final commit and clean scope**

```bash
git show --stat --oneline HEAD
git status --short
git log --oneline --decorate -3
```

Expected: one implementation commit above the plan/design base; no unstaged source changes; no unrelated artifacts staged or committed.

- [ ] **Step 10: Stop at the activation boundary**

Report local checkout, final commit, branch, verification, migrations pending, service/runtime unchanged, served asset unchanged, and real-device proof pending as separate states. Do not merge, push, migrate, restart, install, flip, or deploy without a new explicit instruction.
