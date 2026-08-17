# Push Room and Message Deep Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the canonical room name in every message notification and make warm and cold notification taps land on the exact persisted room, branch, and message.

**Architecture:** The backend adds the server-owned room name to the existing Web Push and Expo payload. The service worker carries the existing room/thread/message IDs into the URL-authoritative `RoomDestination`; `useRoomNavigation` remains the only destination writer, and `ChatLayout` reuses the existing message-context and MessageList flash path.

**Tech Stack:** Python 3.12, FastAPI, pywebpush, exponent-server-sdk, React 19, TypeScript, Workbox service worker, Zustand, Vitest, Playwright

## Global Constraints

- No database migration, new API endpoint, notification landing screen, or alternate navigation writer.
- Title format is `Room Name · Sender Name`; LLM format is `Room Name · ✦ Claude`.
- Body preview and room-based notification tag behavior remain unchanged.
- Warm and cold destinations carry `room_id`, `thread_id`, and `message_id`.
- Old room-only notifications continue working.
- A missing/deleted message falls back to current thread history without a fake placeholder.
- TypeScript route encoding uses `URLSearchParams`; no raw query interpolation.
- Backend deploy precedes the PWA release; production activation requires separate authorization.

---

### Task 1: Canonical room name in notification payloads

**Files:**
- Modify: `dialectic/transport/handlers.py`
- Modify: `dialectic/api/notifications/service.py`
- Test: `dialectic/tests/test_webpush.py`
- Test: `dialectic/tests/test_collaboration_contracts.py`

**Interfaces:**
- Produces: `PushNotificationService.send_message_notification(..., room_name: str, ...) -> dict`.
- Preserves: existing room/thread/message data for Web Push and Expo.

- [ ] **Step 1: Add failing notification-title tests**

Mock `send_web_notifications` and the Expo client. Call the service for a human
and an LLM and assert:

```python
assert web_kwargs["title"] == "Iran/Hormuz Trading Room · Amo"
assert llm_web_kwargs["title"] == "Iran/Hormuz Trading Room · ✦ Claude"
assert web_kwargs["data"]["room_name"] == "Iran/Hormuz Trading Room"
assert expo_message.data == web_kwargs["data"]
```

- [ ] **Step 2: Add failing canonical-name query test**

In the handler contract test, return a membership row containing the canonical
room name and assert `_trigger_push_notifications` passes it to the service.
Assert no client payload field can override it.

- [ ] **Step 3: Run Task 1 tests red**

Run: `cd dialectic && python3 -m pytest tests/test_webpush.py tests/test_collaboration_contracts.py -k 'room_name or notification_title or push' -q`

Expected: failures because the service signature and membership query lack
`room_name`.

- [ ] **Step 4: Implement the backend contract**

Join `rooms` in the existing membership/mute query and select `r.name AS
room_name`. Pass that value through `_trigger_push_notifications` into the
service. Construct the title from canonical room name plus the existing human or
LLM display name. Add `room_name` to both channel data dicts.

- [ ] **Step 5: Run Task 1 tests green**

Run the exact Task 1 command again. Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add dialectic/transport/handlers.py dialectic/api/notifications/service.py dialectic/tests/test_webpush.py dialectic/tests/test_collaboration_contracts.py
git commit -m "feat(dialectic): name the room in message pushes"
```

### Task 2: Full message destination in URLs and service-worker taps

**Files:**
- Modify: `dialectic/frontend/app/src/types/index.ts`
- Modify: `dialectic/frontend/app/src/lib/workspaceRoute.ts`
- Modify: `dialectic/frontend/app/src/lib/workspaceRoute.test.ts`
- Modify: `dialectic/frontend/app/src/sw.ts`
- Create: `dialectic/frontend/app/src/sw.test.ts`

**Interfaces:**
- Produces: `RoomDestination.messageId?: string | null`.
- Produces: `/?room=<id>&thread=<id>&message=<id>` through `URLSearchParams`.
- Produces: service-worker `open-message` events carrying all three IDs.

- [ ] **Step 1: Add failing route tests**

Extend workspace-route tests:

```typescript
expect(destinationFromSearch('?room=r&thread=t&message=m')).toMatchObject({
  roomId: 'r', threadId: 't', messageId: 'm',
})
expect(destinationUrl(room, branch, 'record', null, 'm')).toBe(
  '/?room=r&thread=t&message=m',
)
```

Assert a destination without a message serializes to the exact legacy URL.

- [ ] **Step 2: Add failing service-worker tests**

Install a test `self` with mocked `clients`, `registration`, and listener
capture before dynamically importing `sw.ts`. Prove:

- warm tap focuses the visible client and posts
  `{type: 'open-message', roomId: 'r', threadId: 't', messageId: 'm'}`;
- cold tap calls `openWindow('/?room=r&thread=t&message=m')`;
- reserved characters are encoded by `URLSearchParams`;
- legacy room-only payload still posts/opens a room destination.

- [ ] **Step 3: Run Task 2 tests red**

Run: `cd dialectic/frontend/app && npm test -- --run src/lib/workspaceRoute.test.ts src/sw.test.ts`

Expected: `messageId` is absent and the service worker discards thread/message.

- [ ] **Step 4: Implement route and service-worker behavior**

Add the optional message axis to the type, parser, and serializer. Extend
`destinationUrl` with a final `message: string | null = null` parameter so
existing callers remain source-compatible. In the service worker, build the
cold URL with `URL`/`URLSearchParams`; for warm taps prefer a visible client,
focus it, and post the complete destination. Keep `open-room` handling for
legacy payloads that lack thread/message.

- [ ] **Step 5: Run Task 2 tests green**

Run the exact Task 2 command again. Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add dialectic/frontend/app/src/types/index.ts dialectic/frontend/app/src/lib/workspaceRoute.ts dialectic/frontend/app/src/lib/workspaceRoute.test.ts dialectic/frontend/app/src/sw.ts dialectic/frontend/app/src/sw.test.ts
git commit -m "feat(dialectic): carry push taps to the exact message"
```

### Task 3: Navigation-owned message target and context hydration

**Files:**
- Modify: `dialectic/frontend/app/src/hooks/useRoomNavigation.ts`
- Modify: `dialectic/frontend/app/src/hooks/useRoomNavigation.continuity.test.tsx`
- Modify: `dialectic/frontend/app/src/App.tsx`
- Create: `dialectic/frontend/app/src/App.notification.test.tsx`
- Modify: `dialectic/frontend/app/src/components/chat/MessageList.identity.test.tsx`

**Interfaces:**
- Produces: `RoomNavigation.messageId: string | null`.
- Consumes: Task 2 `RoomDestination.messageId` and existing `api.getMessageContext`.
- Preserves: `MessageList`'s existing `jumpTarget` centered scroll and flash.

- [ ] **Step 1: Add failing navigation tests**

Prove initial URL and service-worker `open-message` events call `navigate` with
all axes. Assert navigation preserves `messageId` only when the requested thread
is the installed thread, includes it in history, and clears it on an ordinary
room/thread navigation.

- [ ] **Step 2: Add failing hydration tests**

Export `ChatLayout` as a named export while retaining the existing default app
export. In `App.notification.test.tsx`, render that real component with the
same store and API spies used by the existing frontend tests, and a
`RoomNavigation` fixture carrying a message target. Assert:

- `api.getMessageContext(threadId, messageId)` is called;
- `api.getMessages` is not called concurrently for that entry;
- the context rows enter the store before `jumpTarget` is emitted;
- missing context falls back to `api.getMessages(threadId, 200)`;
- attachments and reactions still refresh.

Keep the existing MessageList DOM test as the scroll/flash assertion; add the
notification-origin target if its current fixture only covers search.

- [ ] **Step 3: Run Task 3 tests red**

Run: `cd dialectic/frontend/app && npm test -- --run src/hooks/useRoomNavigation.continuity.test.tsx src/App.notification.test.tsx src/components/chat/MessageList.identity.test.tsx`

Expected: navigation understands only `open-room`, and history hydration always
loads the latest window.

- [ ] **Step 4: Implement navigation and hydration**

Store installed `messageId` beside `objectId` in `useRoomNavigation`. Thread it
through `destinationUrl` and the service-worker listener. Rename the event branch
to handle `open-message` without adding direct store/history writes.

In `ChatLayout`'s existing history effect, choose exactly one request: context
when `nav.messageId` exists, otherwise latest history. On context failure, load
latest history. After context rows are installed, set the existing jump target
with a new nonce. Keep one cancellation flag so a slower destination cannot
write into a later room/thread.

- [ ] **Step 5: Run Task 3 tests green**

Run the exact Task 3 command again. Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add dialectic/frontend/app/src/hooks/useRoomNavigation.ts dialectic/frontend/app/src/hooks/useRoomNavigation.continuity.test.tsx dialectic/frontend/app/src/App.tsx dialectic/frontend/app/src/App.notification.test.tsx dialectic/frontend/app/src/components/chat/MessageList.identity.test.tsx
git commit -m "feat(dialectic): hydrate and flash pushed messages"
```

### Task 4: Push navigation verification gate

**Files:**
- Modify: `JOURNAL.md`
- Create: `docs/superpowers/acceptance/2026-08-16-push-room-message-deep-link-acceptance.py`

**Interfaces:**
- Consumes: Tasks 1 through 3.
- Produces: automated warm/cold browser acceptance without creating a production user.

- [ ] **Step 1: Add isolated browser acceptance**

Use the existing seeded acceptance stack. Create two rooms and one persisted
message per room. Stub or dispatch the service-worker notification-click payload
without using a real production subscription. Run 390x844 and 1024x900 browser
contexts. Assert the visible canonical room heading, cold URL, warm room switch,
branch selection, target `data-message-id`, and `msg-flash`. Save one screenshot
per context under `docs/superpowers/acceptance/screenshots-push-deep-link/`.

- [ ] **Step 2: Run focused backend and frontend suites**

```bash
WORKTREE_ROOT=$(git rev-parse --show-toplevel)
cd "$WORKTREE_ROOT/dialectic" && python3 -m pytest \
  tests/test_webpush.py \
  tests/test_collaboration_contracts.py -q
cd frontend/app && npm test -- --run \
  src/lib/workspaceRoute.test.ts \
  src/sw.test.ts \
  src/hooks/useRoomNavigation.continuity.test.tsx \
  src/App.notification.test.tsx \
  src/components/chat/MessageList.identity.test.tsx
```

- [ ] **Step 3: Run full gates**

```bash
WORKTREE_ROOT=$(git rev-parse --show-toplevel)
cd "$WORKTREE_ROOT/dialectic" && python3 -m pytest -q
cd frontend/app && npm test -- --run
npm run lint
npm run build
```

- [ ] **Step 4: Run browser acceptance**

Start the isolated backend from the worktree in one session:

```bash
WORKTREE_ROOT=$(git rev-parse --show-toplevel)
cd "$WORKTREE_ROOT/dialectic"
DATABASE_URL='postgresql://localhost/dialectic_browser' \
JWT_SECRET_KEY='browser-push-secret-32-bytes-minimum' \
ANTHROPIC_API_KEY='browser-fixture-dummy-key' \
SIGNUPS_ENABLED=1 SCHEDULER_ENABLED=0 PORT=8013 python3 run.py
```

Build and start the isolated frontend preview in another session:

```bash
WORKTREE_ROOT=$(git rev-parse --show-toplevel)
cd "$WORKTREE_ROOT/dialectic/frontend/app"
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run build
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run preview -- --port 4173
```

Run the new Python harness from the worktree root:

```bash
python3 docs/superpowers/acceptance/2026-08-16-push-room-message-deep-link-acceptance.py
```

Inspect both screenshots for the room heading, correct room/thread, and centered
flash target. Record exact pass counts, then stop both isolated processes.

- [ ] **Step 5: Mutation-prove routing ownership**

Remove `messageId` from the warm event, replace the cold URL with room-only, and
bypass `navigate` with a direct store write one at a time. Each mutation must
fail its targeted test. Restore and rerun green.

- [ ] **Step 6: Record and commit the gate**

Append one `JOURNAL.md` line with backend, frontend, lint, build, browser, and
mutation results. Commit only the acceptance spec and journal:

```bash
git add docs/superpowers/acceptance/2026-08-16-push-room-message-deep-link-acceptance.py docs/superpowers/acceptance/screenshots-push-deep-link JOURNAL.md
git commit -m "test(dialectic): prove push message landing end to end"
```
