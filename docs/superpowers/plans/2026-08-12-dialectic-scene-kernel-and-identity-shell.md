# Dialectic Scene Kernel and Identity Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one typed workspace-scene and product-identity foundation so Home opens as House, conversation is an explicit Record scene, existing room/branch URLs remain stable, and the visible third participant is Dialectic rather than a provider brand.

**Architecture:** Extract current URL helpers from `useRoomNavigation.ts` into a pure tested module, then extend the existing single navigation transaction with workspace-scene resolution. Store the resolved scene transiently in Zustand, render the shipped House and Record scenes through a small scene frame, and centralize participant-facing identity strings while retaining existing backend speaker enums, CSS compatibility names, provider provenance, and `@Claude`/`@llm` compatibility. This tranche adds no domain schema and does not reposition ordinary-room Record yet.

**Tech Stack:** React 19.2, TypeScript 5.9, Zustand 5, Vite 7, Vitest 4.1 and Testing Library using the sibling `trading/frontend` test pattern, FastAPI/Python 3.13, pytest, current WebSocket and PWA infrastructure.

## Global Constraints

- Canonical design: `docs/superpowers/specs/2026-08-12-dialectic-front-end-identity-design-v2.md` at `e3bb6a4`.
- Program sequence: `docs/superpowers/plans/2026-08-12-dialectic-living-workroom-program.md` at `b175fc9`.
- Implementation baseline when this plan was written: repository `master` at `b175fc9`; latest reviewed logic commit `e422f3a`.
- Read `JOURNAL.md`, root `CLAUDE.md`, `dialectic/CLAUDE.md`, the v2 design, and `docs/handoffs/2026-08-12-home-base-session.md` before editing.
- Create an isolated worktree at execution time. Do not implement directly in the production checkout because `dialectic.service` and `tradingdesk.service` run their working trees.
- No database migration, service restart, production frontend release, or Home membership change is authorized by this plan.
- Preserve `useRoomNavigation.ts` as the one destination writer. No component may call `setRoom`, `setThread`, or `leaveRoom` to navigate.
- Preserve current canonical URL behavior:
  - Home root: `/`
  - Ordinary room root: `/?room=<room-id>`
  - Any non-root branch: `/?room=<room-id>&thread=<thread-id>`
- Add `scene` only when the selected scene differs from that destination's default. Existing links must remain canonical and valid.
- Home root defaults to `house`. Ordinary rooms and every non-root branch, including Home branches, default to `record`.
- Only `house` and `record` are implemented in this tranche. The type system may name approved future scenes, but navigation must fall back to the current destination default rather than expose dead UI.
- Preserve Home's all-members intersection, stale snapshot retention, shared human/Dialectic projection, thesis prohibition, and founder-management boundary.
- Preserve per-thread unread semantics and current Home pulse refresh behavior.
- Preserve current mobile drawers, scrim, Escape close, destination close, and exactly-1024 desktop boundary.
- Preserve message editing, deletion, reply, search, attachments, reactions, streaming, Research, proposals, briefing, protocols, commitments, and right-panel functionality.
- Primary visible participant naming becomes Dialectic. Historical persisted message content, provider/model provenance, backend `SpeakerType`, metadata fields, CSS compatibility class names, and database values do not change.
- `@Dialectic` becomes the primary explicit summon. `@Claude` and `@llm` remain accepted compatibility aliases.
- Add frontend test infrastructure by copying the established Vitest/Testing Library pattern from `trading/frontend`; no runtime dependency is added.
- Keep changes conservative. This tranche does not build Bench, Library, Field, Focus, Ledger, Judgment, Atlas, object deep links, or exact device-local restoration.
- Every task ends with a focused test run and a commit. Do not combine tasks into one large commit.

---

## File structure after this tranche

```text
dialectic/frontend/app/
├── package.json
├── package-lock.json
├── vite.config.ts
├── tsconfig.node.json
└── src/
    ├── test/
    │   └── setup.ts
    ├── types/
    │   ├── index.ts
    │   └── workspace.ts
    ├── lib/
    │   ├── productIdentity.ts
    │   ├── productIdentity.test.ts
    │   ├── workspaceRoute.ts
    │   └── workspaceRoute.test.ts
    ├── components/
    │   └── workspace/
    │       ├── SceneSwitcher.tsx
    │       ├── SceneSwitcher.css
    │       ├── WorkspaceSceneFrame.tsx
    │       ├── WorkspaceSceneFrame.css
    │       └── WorkspaceSceneFrame.test.tsx
    ├── hooks/
    │   └── useRoomNavigation.ts
    ├── stores/
    │   ├── appStore.ts
    │   └── appStore.test.ts
    └── App.tsx

dialectic/
├── llm/
│   ├── context.py
│   └── mentions.py
├── transport/
│   └── handlers.py
└── tests/
    └── test_llm_mentions.py
```

No other new directory is required.

---

### Task 1: Add the frontend unit-test harness and lock the current route grammar

**Files:**
- Modify: `dialectic/frontend/app/package.json`
- Modify: `dialectic/frontend/app/package-lock.json`
- Modify: `dialectic/frontend/app/vite.config.ts`
- Modify: `dialectic/frontend/app/tsconfig.node.json`
- Create: `dialectic/frontend/app/src/test/setup.ts`
- Create: `dialectic/frontend/app/src/lib/workspaceRoute.test.ts`
- Create: `dialectic/frontend/app/src/lib/workspaceRoute.ts`
- Modify: `dialectic/frontend/app/src/hooks/useRoomNavigation.ts:1-45`

**Interfaces:**
- Consumes: existing `RoomDestination`, `Thread`, and `UserRoom` types from `src/types/index.ts`.
- Produces:
  - `destinationFromSearch(search: string): RoomDestination`
  - `destinationFromLocation(location: Pick<Location, 'search'>): RoomDestination`
  - `destinationUrl(room, thread): string`
- Later tasks extend these exact functions; do not create a second route module.

- [ ] **Step 1: Install the monorepo's existing frontend-test stack**

Run:

```bash
cd dialectic/frontend/app
npm install --save-dev \
  vitest@^4.1.4 \
  @testing-library/react@^16.3.2 \
  @testing-library/jest-dom@^6.9.1 \
  jsdom@^29.0.2
```

Expected: `package.json` and `package-lock.json` change; no runtime dependency changes.

Add these scripts to `package.json`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

- [ ] **Step 2: Configure Vitest through the existing Vite configuration**

Change the first import in `vite.config.ts` to use Vitest's typed `defineConfig`, while preserving Vite's `ProxyOptions` type:

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import type { ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
```

Add this top-level block beside `plugins`, `server`, and `preview`:

```ts
test: {
  globals: true,
  environment: 'jsdom',
  setupFiles: './src/test/setup.ts',
  restoreMocks: true,
},
```

Update `tsconfig.node.json`:

```json
{
  "include": ["vite.config.ts"]
}
```

No separate `vitest.config.ts` is needed; keeping one Vite configuration avoids proxy drift.

Create `src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 3: Write failing regression tests for the current URL contract**

Create `src/lib/workspaceRoute.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { Thread, UserRoom } from '../types'
import {
  destinationFromLocation,
  destinationFromSearch,
  destinationUrl,
} from './workspaceRoute'

const home = {
  id: 'home-room',
  is_home: true,
} as Pick<UserRoom, 'id' | 'is_home'>

const scheme = {
  id: 'scheme-room',
  is_home: false,
} as Pick<UserRoom, 'id' | 'is_home'>

const root = {
  id: 'main-thread',
  parent_thread_id: null,
} as Pick<Thread, 'id' | 'parent_thread_id'>

const branch = {
  id: 'branch-thread',
  parent_thread_id: 'main-thread',
} as Pick<Thread, 'id' | 'parent_thread_id'>

describe('destinationFromSearch', () => {
  it('treats a bare URL as the canonical Home destination', () => {
    expect(destinationFromSearch('')).toEqual({ roomId: null, threadId: null })
  })

  it('reads room and branch destinations', () => {
    expect(destinationFromSearch('?room=scheme-room')).toEqual({
      roomId: 'scheme-room',
      threadId: null,
    })
    expect(destinationFromSearch('?room=scheme-room&thread=branch-thread')).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
    })
  })

  it('uses only the Location search field', () => {
    expect(destinationFromLocation({
      search: '?room=scheme-room&thread=branch-thread',
    })).toEqual({
      roomId: 'scheme-room',
      threadId: 'branch-thread',
    })
  })
})

describe('destinationUrl', () => {
  it('canonicalizes only the Home root to a bare slash', () => {
    expect(destinationUrl(home, root)).toBe('/')
    expect(destinationUrl(home, branch)).toBe(
      '/?room=home-room&thread=branch-thread',
    )
  })

  it('keeps ordinary roots and branches explicit', () => {
    expect(destinationUrl(scheme, root)).toBe('/?room=scheme-room')
    expect(destinationUrl(scheme, branch)).toBe(
      '/?room=scheme-room&thread=branch-thread',
    )
  })
})
```

- [ ] **Step 4: Run the tests and verify RED**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/lib/workspaceRoute.test.ts
```

Expected: FAIL because `src/lib/workspaceRoute.ts` does not exist.

- [ ] **Step 5: Extract the current pure route functions without changing behavior**

Create `src/lib/workspaceRoute.ts`:

```ts
import type { RoomDestination, Thread, UserRoom } from '../types'

export function destinationFromSearch(search: string): RoomDestination {
  const params = new URLSearchParams(search)
  return {
    roomId: params.get('room'),
    threadId: params.get('thread'),
  }
}

export function destinationFromLocation(
  location: Pick<Location, 'search'>,
): RoomDestination {
  return destinationFromSearch(location.search)
}

export function destinationUrl(
  room: Pick<UserRoom, 'id' | 'is_home'>,
  thread: Pick<Thread, 'id' | 'parent_thread_id'>,
): string {
  const rootHome = room.is_home && thread.parent_thread_id === null
  if (rootHome) return '/'

  const params = new URLSearchParams({ room: room.id })
  if (thread.parent_thread_id !== null) params.set('thread', thread.id)
  return `/?${params.toString()}`
}
```

Remove the local `destinationFromLocation` and `destinationUrl` definitions from `useRoomNavigation.ts` and import them:

```ts
import {
  destinationFromLocation,
  destinationUrl,
} from '../lib/workspaceRoute.ts'
```

Do not change any navigation behavior in this task.

- [ ] **Step 6: Run focused tests, lint, and build**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/lib/workspaceRoute.test.ts
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit**

```bash
git add \
  dialectic/frontend/app/package.json \
  dialectic/frontend/app/package-lock.json \
  dialectic/frontend/app/vite.config.ts \
  dialectic/frontend/app/tsconfig.node.json \
  dialectic/frontend/app/src/test/setup.ts \
  dialectic/frontend/app/src/lib/workspaceRoute.ts \
  dialectic/frontend/app/src/lib/workspaceRoute.test.ts \
  dialectic/frontend/app/src/hooks/useRoomNavigation.ts
git commit -m "test(frontend): pin the room-route contract -- scenes get a safe seam"
```

---

### Task 2: Define the workspace-scene model and canonical scene URLs

**Files:**
- Create: `dialectic/frontend/app/src/types/workspace.ts`
- Modify: `dialectic/frontend/app/src/types/index.ts:1-20`
- Modify: `dialectic/frontend/app/src/lib/workspaceRoute.ts`
- Modify: `dialectic/frontend/app/src/lib/workspaceRoute.test.ts`

**Interfaces:**
- Consumes: Task 1 route helpers.
- Produces:
  - `WorkspaceScene`
  - `ImplementedWorkspaceScene`
  - `WorkspaceLocation`
  - `WORKSPACE_SCENES`
  - `IMPLEMENTED_WORKSPACE_SCENES`
  - `defaultWorkspaceScene(room, thread): ImplementedWorkspaceScene`
  - `resolveWorkspaceScene(room, thread, requested): ImplementedWorkspaceScene`
  - scene-aware `destinationFromSearch`, `destinationFromLocation`, and `destinationUrl`
- Task 3 writes the resolved scene into Zustand.

- [ ] **Step 1: Write failing scene-route tests**

Extend `workspaceRoute.test.ts`:

```ts
import {
  defaultWorkspaceScene,
  destinationFromLocation,
  destinationFromSearch,
  destinationUrl,
  resolveWorkspaceScene,
} from './workspaceRoute'

// Existing fixtures remain unchanged.

describe('workspace scenes', () => {
  it('parses known scene names and drops unknown names', () => {
    expect(destinationFromSearch('?scene=record')).toEqual({
      roomId: null,
      threadId: null,
      scene: 'record',
    })
    expect(destinationFromSearch('?scene=made-up')).toEqual({
      roomId: null,
      threadId: null,
      scene: null,
    })
  })

  it('defaults Home root to House and every other destination to Record', () => {
    expect(defaultWorkspaceScene(home, root)).toBe('house')
    expect(defaultWorkspaceScene(home, branch)).toBe('record')
    expect(defaultWorkspaceScene(scheme, root)).toBe('record')
    expect(defaultWorkspaceScene(scheme, branch)).toBe('record')
  })

  it('rejects an invalid House request outside Home root', () => {
    expect(resolveWorkspaceScene(scheme, root, 'house')).toBe('record')
    expect(resolveWorkspaceScene(home, branch, 'house')).toBe('record')
  })

  it('falls back from approved but not-yet-implemented scenes', () => {
    expect(resolveWorkspaceScene(home, root, 'field')).toBe('house')
    expect(resolveWorkspaceScene(scheme, root, 'library')).toBe('record')
  })

  it('omits the default scene and serializes only a non-default scene', () => {
    expect(destinationUrl(home, root, 'house')).toBe('/')
    expect(destinationUrl(home, root, 'record')).toBe('/?scene=record')
    expect(destinationUrl(scheme, root, 'record')).toBe('/?room=scheme-room')
    expect(destinationUrl(home, branch, 'record')).toBe(
      '/?room=home-room&thread=branch-thread',
    )
  })
})
```

Update the earlier expected objects to include `scene: null`:

```ts
expect(destinationFromSearch('')).toEqual({
  roomId: null,
  threadId: null,
  scene: null,
})
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/lib/workspaceRoute.test.ts
```

Expected: FAIL because workspace scene types and helpers do not exist.

- [ ] **Step 3: Add the approved scene vocabulary without exposing dead scenes**

Create `src/types/workspace.ts`:

```ts
export const WORKSPACE_SCENES = [
  'house',
  'record',
  'bench',
  'library',
  'ledger',
  'field',
  'focus',
  'judgment',
  'atlas',
] as const

export type WorkspaceScene = (typeof WORKSPACE_SCENES)[number]

export const IMPLEMENTED_WORKSPACE_SCENES = ['house', 'record'] as const

export type ImplementedWorkspaceScene =
  (typeof IMPLEMENTED_WORKSPACE_SCENES)[number]

export interface WorkspaceLocation {
  scene: ImplementedWorkspaceScene
}

export function isWorkspaceScene(value: string | null): value is WorkspaceScene {
  return value !== null
    && (WORKSPACE_SCENES as readonly string[]).includes(value)
}

export function isImplementedWorkspaceScene(
  value: WorkspaceScene | null,
): value is ImplementedWorkspaceScene {
  return value !== null
    && (IMPLEMENTED_WORKSPACE_SCENES as readonly string[]).includes(value)
}
```

At the top of `src/types/index.ts`:

```ts
import type { WorkspaceScene } from './workspace.ts'
export * from './workspace.ts'
```

Extend the existing `RoomDestination`:

```ts
export interface RoomDestination {
  roomId: string | null;
  threadId?: string | null;
  scene?: WorkspaceScene | null;
}
```

Do not add object IDs in this tranche.

- [ ] **Step 4: Implement defaulting, validation, and canonical serialization**

Replace `workspaceRoute.ts` with:

```ts
import type {
  ImplementedWorkspaceScene,
  RoomDestination,
  Thread,
  UserRoom,
  WorkspaceScene,
} from '../types'
import {
  isImplementedWorkspaceScene,
  isWorkspaceScene,
} from '../types'

export function destinationFromSearch(search: string): RoomDestination {
  const params = new URLSearchParams(search)
  const requestedScene = params.get('scene')
  return {
    roomId: params.get('room'),
    threadId: params.get('thread'),
    scene: isWorkspaceScene(requestedScene) ? requestedScene : null,
  }
}

export function destinationFromLocation(
  location: Pick<Location, 'search'>,
): RoomDestination {
  return destinationFromSearch(location.search)
}

export function defaultWorkspaceScene(
  room: Pick<UserRoom, 'is_home'>,
  thread: Pick<Thread, 'parent_thread_id'>,
): ImplementedWorkspaceScene {
  return room.is_home && thread.parent_thread_id === null
    ? 'house'
    : 'record'
}

export function resolveWorkspaceScene(
  room: Pick<UserRoom, 'is_home'>,
  thread: Pick<Thread, 'parent_thread_id'>,
  requested: WorkspaceScene | null | undefined,
): ImplementedWorkspaceScene {
  const fallback = defaultWorkspaceScene(room, thread)
  if (!isImplementedWorkspaceScene(requested ?? null)) return fallback
  if (requested === 'house' && fallback !== 'house') return fallback
  return requested
}

export function destinationUrl(
  room: Pick<UserRoom, 'id' | 'is_home'>,
  thread: Pick<Thread, 'id' | 'parent_thread_id'>,
  scene: ImplementedWorkspaceScene = defaultWorkspaceScene(room, thread),
): string {
  const rootHome = room.is_home && thread.parent_thread_id === null
  const defaultScene = defaultWorkspaceScene(room, thread)
  const params = new URLSearchParams()

  if (!rootHome) params.set('room', room.id)
  if (thread.parent_thread_id !== null) params.set('thread', thread.id)
  if (scene !== defaultScene) params.set('scene', scene)

  const query = params.toString()
  return query ? `/?${query}` : '/'
}
```

- [ ] **Step 5: Run focused tests, lint, and build**

```bash
cd dialectic/frontend/app
npm test -- src/lib/workspaceRoute.test.ts
npm run lint
npm run build
```

Expected: all commands exit 0; existing default URLs remain unchanged.

- [ ] **Step 6: Commit**

```bash
git add \
  dialectic/frontend/app/src/types/workspace.ts \
  dialectic/frontend/app/src/types/index.ts \
  dialectic/frontend/app/src/lib/workspaceRoute.ts \
  dialectic/frontend/app/src/lib/workspaceRoute.test.ts
git commit -m "feat(frontend): name the workspace scenes -- keep old links canonical"
```

---

### Task 3: Make the existing navigation transaction own scene installation

**Files:**
- Modify: `dialectic/frontend/app/src/stores/appStore.ts`
- Create: `dialectic/frontend/app/src/stores/appStore.test.ts`
- Modify: `dialectic/frontend/app/src/hooks/useRoomNavigation.ts`
- Modify: `dialectic/frontend/app/src/lib/workspaceRoute.test.ts`

**Interfaces:**
- Consumes: Task 2 `resolveWorkspaceScene` and scene-aware `destinationUrl`.
- Produces:
  - `AppState.workspaceScene: ImplementedWorkspaceScene`
  - `AppState.setWorkspaceScene(scene): void`
  - scene-aware `RoomNavigation.navigate(destination, historyMode)`
- Task 4 renders `workspaceScene`.

- [ ] **Step 1: Write failing Zustand scene-state tests**

Create `src/stores/appStore.test.ts`:

```ts
import { afterEach, describe, expect, it } from 'vitest'
import { useAppStore } from './appStore'

const room = {
  id: 'room-1',
  name: 'Room One',
  token: 'room-token',
  is_home: false,
}

afterEach(() => {
  useAppStore.getState().logout()
})

describe('workspace scene state', () => {
  it('starts on Record before navigation resolves a destination', () => {
    expect(useAppStore.getState().workspaceScene).toBe('record')
  })

  it('stores a scene selected by the navigation transaction', () => {
    useAppStore.getState().setWorkspaceScene('house')
    expect(useAppStore.getState().workspaceScene).toBe('house')
  })

  it('resets to Record when a different room is installed', () => {
    useAppStore.getState().setWorkspaceScene('house')
    useAppStore.getState().setRoom(room, room.token)
    expect(useAppStore.getState().workspaceScene).toBe('record')
  })
})
```

- [ ] **Step 2: Run and verify RED**

```bash
cd dialectic/frontend/app
npm test -- src/stores/appStore.test.ts
```

Expected: FAIL because `workspaceScene` and `setWorkspaceScene` do not exist.

- [ ] **Step 3: Add transient workspace-scene state to the existing store**

Import the type:

```ts
import type {
  // existing imports
  ImplementedWorkspaceScene,
} from '../types/index.ts'
```

Add to `AppState`:

```ts
workspaceScene: ImplementedWorkspaceScene;
setWorkspaceScene: (scene: ImplementedWorkspaceScene) => void;
```

Add to `initialRoomState`:

```ts
workspaceScene: 'record' as ImplementedWorkspaceScene,
```

Add the action:

```ts
setWorkspaceScene: (scene) => set({ workspaceScene: scene }),
```

Inside `setRoom`, explicitly reset:

```ts
workspaceScene: 'record',
```

Do not add `workspaceScene` to Zustand `partialize`. Full device-local restoration belongs to Tranche 9; current scene reload is URL-authoritative in this tranche.

- [ ] **Step 4: Run the store tests and verify GREEN**

```bash
cd dialectic/frontend/app
npm test -- src/stores/appStore.test.ts
```

Expected: PASS.

- [ ] **Step 5: Extend the one navigation transaction**

In `useRoomNavigation.ts`, import:

```ts
import {
  defaultWorkspaceScene,
  destinationFromLocation,
  destinationUrl,
  resolveWorkspaceScene,
} from '../lib/workspaceRoute.ts'
```

Read the store setter:

```ts
const setWorkspaceScene = useAppStore((s) => s.setWorkspaceScene)
```

After resolving `room` and `thread`, before writing history:

```ts
const scene = resolveWorkspaceScene(room, thread, destination.scene)

if (state.currentRoom?.id !== room.id) {
  setRoom(
    { id: room.id, name: room.name, token: room.token, is_home: room.is_home },
    room.token,
  )
}
setThreads(threads)
setThread(thread)
setWorkspaceScene(scene)

const url = destinationUrl(room, thread, scene)
```

Add `setWorkspaceScene` to the callback dependency array.

Keep current behavior for notification entry, search jumps, create/join, denied access, and Home fallback. When those callers omit `scene`, the destination default applies.

- [ ] **Step 6: Add a regression test for canonical fallback**

Extend `workspaceRoute.test.ts`:

```ts
it('canonicalizes a known but unavailable scene back to the destination default', () => {
  const resolved = resolveWorkspaceScene(home, root, 'field')
  expect(resolved).toBe('house')
  expect(destinationUrl(home, root, resolved)).toBe('/')
})
```

- [ ] **Step 7: Run the focused frontend gate**

```bash
cd dialectic/frontend/app
npm test -- \
  src/lib/workspaceRoute.test.ts \
  src/stores/appStore.test.ts
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit**

```bash
git add \
  dialectic/frontend/app/src/stores/appStore.ts \
  dialectic/frontend/app/src/stores/appStore.test.ts \
  dialectic/frontend/app/src/hooks/useRoomNavigation.ts \
  dialectic/frontend/app/src/lib/workspaceRoute.test.ts
git commit -m "feat(frontend): let navigation own the scene -- one destination transaction"
```

---

### Task 4: Render explicit House and Record scenes without regressing the current room

**Files:**
- Create: `dialectic/frontend/app/src/components/workspace/SceneSwitcher.tsx`
- Create: `dialectic/frontend/app/src/components/workspace/SceneSwitcher.css`
- Create: `dialectic/frontend/app/src/components/workspace/WorkspaceSceneFrame.tsx`
- Create: `dialectic/frontend/app/src/components/workspace/WorkspaceSceneFrame.css`
- Create: `dialectic/frontend/app/src/components/workspace/WorkspaceSceneFrame.test.tsx`
- Modify: `dialectic/frontend/app/src/App.tsx:48-620`
- Modify: `dialectic/frontend/app/src/components/layout/AppLayout.tsx`
- Modify: `dialectic/frontend/app/src/components/layout/AppLayout.css`

**Interfaces:**
- Consumes: `workspaceScene` from Task 3 and existing `HomeActivityPulse` plus Record content.
- Produces:
  - `SceneSwitcher`
  - `WorkspaceSceneFrame`
  - explicit Home root House/Record navigation
- Later tranches extend the switcher and frame; do not create another scene shell.

- [ ] **Step 1: Write failing scene-frame component tests**

Create `WorkspaceSceneFrame.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceSceneFrame } from './WorkspaceSceneFrame'

describe('WorkspaceSceneFrame', () => {
  it('renders House and Record choices at Home root', () => {
    render(
      <WorkspaceSceneFrame
        scene="house"
        isHomeRoot
        onSelect={vi.fn()}
        house={<div>House content</div>}
        record={<div>Record content</div>}
      />,
    )

    expect(screen.getByRole('button', { name: 'House' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('button', { name: 'Record' })).toBeInTheDocument()
    expect(screen.getByText('House content')).toBeInTheDocument()
    expect(screen.queryByText('Record content')).not.toBeInTheDocument()
  })

  it('routes a Home scene selection through the supplied callback', () => {
    const onSelect = vi.fn()
    render(
      <WorkspaceSceneFrame
        scene="house"
        isHomeRoot
        onSelect={onSelect}
        house={<div>House content</div>}
        record={<div>Record content</div>}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(onSelect).toHaveBeenCalledWith('record')
  })

  it('forces non-Home destinations to Record and hides a one-item switcher', () => {
    render(
      <WorkspaceSceneFrame
        scene="house"
        isHomeRoot={false}
        onSelect={vi.fn()}
        house={<div>House content</div>}
        record={<div>Record content</div>}
      />,
    )

    expect(screen.queryByRole('navigation', { name: 'Room views' })).not.toBeInTheDocument()
    expect(screen.getByText('Record content')).toBeInTheDocument()
    expect(screen.queryByText('House content')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run and verify RED**

```bash
cd dialectic/frontend/app
npm test -- src/components/workspace/WorkspaceSceneFrame.test.tsx
```

Expected: FAIL because the workspace components do not exist.

- [ ] **Step 3: Implement the scene switcher**

Create `SceneSwitcher.tsx`:

```tsx
import type {
  ImplementedWorkspaceScene,
} from '../../types'
import './SceneSwitcher.css'

const SCENE_LABELS: Record<ImplementedWorkspaceScene, string> = {
  house: 'House',
  record: 'Record',
}

interface SceneSwitcherProps {
  scene: ImplementedWorkspaceScene
  scenes: readonly ImplementedWorkspaceScene[]
  onSelect: (scene: ImplementedWorkspaceScene) => void
}

export function SceneSwitcher({ scene, scenes, onSelect }: SceneSwitcherProps) {
  if (scenes.length < 2) return null

  return (
    <nav className="scene-switcher" aria-label="Room views">
      {scenes.map((candidate) => (
        <button
          key={candidate}
          type="button"
          className={`scene-switcher-action${candidate === scene ? ' is-active' : ''}`}
          aria-current={candidate === scene ? 'page' : undefined}
          onClick={() => onSelect(candidate)}
        >
          {SCENE_LABELS[candidate]}
        </button>
      ))}
    </nav>
  )
}
```

Create `SceneSwitcher.css`:

```css
.scene-switcher {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 18px;
    min-height: 34px;
    padding: 0 18px;
    border-bottom: 1px solid var(--color-bean);
    background: var(--color-void);
}

.scene-switcher-action {
    position: relative;
    height: 34px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--color-secondary);
    font: 10px/1 var(--font-mono);
    letter-spacing: .16em;
    text-transform: uppercase;
    cursor: pointer;
}

.scene-switcher-action::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 1px;
    background: transparent;
}

.scene-switcher-action:hover,
.scene-switcher-action.is-active {
    color: var(--color-bone);
}

.scene-switcher-action.is-active::after {
    background: var(--color-amber);
}
```

- [ ] **Step 4: Implement the scene frame**

Create `WorkspaceSceneFrame.tsx`:

```tsx
import type { ReactNode } from 'react'
import type { ImplementedWorkspaceScene } from '../../types'
import { SceneSwitcher } from './SceneSwitcher'
import './WorkspaceSceneFrame.css'

interface WorkspaceSceneFrameProps {
  scene: ImplementedWorkspaceScene
  isHomeRoot: boolean
  onSelect: (scene: ImplementedWorkspaceScene) => void
  house: ReactNode
  record: ReactNode
}

export function WorkspaceSceneFrame({
  scene,
  isHomeRoot,
  onSelect,
  house,
  record,
}: WorkspaceSceneFrameProps) {
  const scenes: readonly ImplementedWorkspaceScene[] = isHomeRoot
    ? ['house', 'record']
    : ['record']
  const effectiveScene: ImplementedWorkspaceScene = isHomeRoot
    ? scene
    : 'record'

  return (
    <section
      className={`workspace-scene workspace-scene-${effectiveScene}`}
      data-workspace-scene={effectiveScene}
    >
      <SceneSwitcher
        scene={effectiveScene}
        scenes={scenes}
        onSelect={onSelect}
      />
      <div className="workspace-scene-content">
        {effectiveScene === 'house' ? house : record}
      </div>
    </section>
  )
}
```

Create `WorkspaceSceneFrame.css`:

```css
.workspace-scene {
    display: flex;
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    flex-direction: column;
    overflow: hidden;
}

.workspace-scene-content {
    display: flex;
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    flex-direction: column;
    overflow: hidden;
}
```

- [ ] **Step 5: Run the component tests and verify GREEN**

```bash
cd dialectic/frontend/app
npm test -- src/components/workspace/WorkspaceSceneFrame.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Integrate the frame in `App.tsx`**

Read the scene from Zustand near the other room state:

```ts
const workspaceScene = useAppStore((s) => s.workspaceScene)
```

After computing `isHome`, compute:

```ts
const isHomeRoot = isHome && currentThread?.parent_thread_id === null
```

Extract the current content below `HomeActivityPulse` into one `recordSurface` React node. It must contain, in the current order:

```tsx
<>
  <RoomBriefing key={currentRoom.id} roomId={currentRoom.id} />
  {activeProtocol && (
    <ProtocolBanner
      protocol={activeProtocol}
      onAdvance={advanceProtocol}
      onAbort={abortProtocol}
    />
  )}
  <CommitmentSurface />
  <MessageList
    // preserve every existing prop unchanged
  />
  <TypingIndicator
    typingUsers={typingDisplay}
    activityLabel={toolActivityLabel}
  />
  <MessageInput
    // preserve every existing prop unchanged
  />
</>
```

Create the House node by composing the shipped pulse above the same table:

```tsx
const houseSurface = (
  <>
    <HomeActivityPulse
      onNavigate={(destination) => navigate(destination, 'push')}
      refreshVersion={homeRefreshVersion}
      residents={participants}
    />
    {recordSurface}
  </>
)
```

Replace the current inline pulse + Record content with:

```tsx
<WorkspaceSceneFrame
  scene={workspaceScene}
  isHomeRoot={isHomeRoot}
  onSelect={(scene) => {
    void navigate({
      roomId: currentRoom.id,
      threadId: currentThread?.id ?? null,
      scene,
    }, 'push')
  }}
  house={houseSurface}
  record={recordSurface}
/>
```

Rules:

- Home root House shows the current pulse and table.
- Home root Record hides the pulse and shows the full table.
- A Home branch renders Record only.
- An ordinary room renders Record only.
- No existing Record child loses props or changes behavior.

- [ ] **Step 7: Update the layout wrapper without reintroducing direct-child assumptions**

Change `AppLayoutProps`:

```ts
interface AppLayoutProps {
  sidebar: ReactNode
  main: ReactNode
  rightPanel: ReactNode
  isHome?: boolean
  workspaceScene?: 'house' | 'record'
  homeTalking?: boolean
}
```

Add the scene class:

```tsx
<div className={`app-main${isHome ? ' app-main-home' : ''}${workspaceScene ? ` app-main-scene-${workspaceScene}` : ''}${homeTalking ? ' app-main-home-talking' : ''}`}>
  {main}
</div>
```

Pass from `App.tsx`:

```tsx
<AppLayout
  isHome={isHome}
  workspaceScene={workspaceScene}
  homeTalking={isHome && workspaceScene === 'house' && displayMessages.length > 0}
  // existing slots
/>
```

Replace the direct-child selectors in `AppLayout.css`:

```css
.app-main-home .participants-bar {
    border-bottom: none;
}

.app-main-home-talking .workspace-scene-house .home-house {
    flex: 0 1 auto;
    max-height: min(36vh, 20rem);
}

.app-main-home-talking .workspace-scene-house .messages-viewport,
.app-main-home-talking .workspace-scene-house .messages-wrapper {
    flex: 1 1 auto;
    max-height: none;
    min-height: 0;
}
```

Delete obsolete `.app-main-home > ...` direct-child rules. Do not change the drawer breakpoint or rail geometry.

- [ ] **Step 8: Run all frontend tests, lint, and build**

```bash
cd dialectic/frontend/app
npm test
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 9: Commit**

```bash
git add \
  dialectic/frontend/app/src/components/workspace \
  dialectic/frontend/app/src/App.tsx \
  dialectic/frontend/app/src/components/layout/AppLayout.tsx \
  dialectic/frontend/app/src/components/layout/AppLayout.css
git commit -m "feat(frontend): make House and Record explicit -- keep the table intact"
```

---

### Task 5: Make Dialectic the visible participant and preserve summon compatibility

**Files:**
- Create: `dialectic/llm/mentions.py`
- Modify: `dialectic/transport/handlers.py:40-55`
- Modify: `dialectic/llm/context.py:1-95`
- Create: `dialectic/tests/test_llm_mentions.py`
- Create: `dialectic/frontend/app/src/lib/productIdentity.ts`
- Create: `dialectic/frontend/app/src/lib/productIdentity.test.ts`
- Modify: `dialectic/frontend/app/src/App.tsx`
- Modify: `dialectic/frontend/app/src/components/chat/MessageList.tsx`
- Modify: `dialectic/frontend/app/src/components/chat/MessageBubble.tsx`
- Modify: `dialectic/frontend/app/src/components/chat/MessageInput.tsx`
- Modify: `dialectic/frontend/app/src/components/home/HomeActivityPulse.tsx`
- Modify: `dialectic/frontend/app/src/components/sidebar/MemoryPanel.tsx`
- Modify: `dialectic/frontend/app/src/components/layout/HelpDialog.tsx`
- Modify: `dialectic/frontend/app/src/components/layout/RoomSettingsDialog.tsx`

**Interfaces:**
- Produces backend:
  - `LLM_MENTION_RE`
  - `contains_explicit_llm_mention(text: str): bool`
- Produces frontend:
  - `PRODUCT_NAME`
  - `PARTICIPANT_NAME`
  - `ORIGIN_IMPRINT`
  - `PARTICIPANT_SIGNATURE`
  - `participantDisplayName(speakerType, personaName?): string`
- Existing speaker enums, CSS class names, provider fields, persisted content, and API contracts remain unchanged.

- [ ] **Step 1: Write failing backend mention tests**

Create `dialectic/tests/test_llm_mentions.py`:

```python
import pytest

from llm.mentions import contains_explicit_llm_mention


@pytest.mark.parametrize(
    "text",
    [
        "@Dialectic examine this",
        "@dialectic examine this",
        "@Claude examine this",
        "@claude examine this",
        "@llm examine this",
    ],
)
def test_explicit_participant_aliases_are_mentions(text: str) -> None:
    assert contains_explicit_llm_mention(text)


@pytest.mark.parametrize(
    "text",
    [
        "dialectical materialism",
        "claudette said hello",
        "email@dialectic.example",
        "the llm should notice this without a summon",
    ],
)
def test_non_mentions_do_not_trigger(text: str) -> None:
    assert not contains_explicit_llm_mention(text)
```

- [ ] **Step 2: Run and verify RED**

```bash
cd dialectic
python3 -m pytest tests/test_llm_mentions.py -q
```

Expected: FAIL because `llm.mentions` does not exist.

- [ ] **Step 3: Create one backend mention definition and consume it everywhere**

Create `dialectic/llm/mentions.py`:

```python
import re


# Product identity first; provider-era aliases remain accepted compatibility.
LLM_MENTION_RE = re.compile(r"@(dialectic|claude|llm)\b", re.IGNORECASE)


def contains_explicit_llm_mention(text: str) -> bool:
    """Return whether text explicitly summons the Dialectic participant."""
    return bool(LLM_MENTION_RE.search(text))
```

In `transport/handlers.py`:

```python
from llm.mentions import contains_explicit_llm_mention
```

Delete the local `re` import and local `LLM_MENTION_RE` definition if no other code in the file uses `re`. Replace each explicit mention check with:

```python
mentioned = contains_explicit_llm_mention(content)
```

In `llm/context.py`, import the same helper:

```python
from llm.mentions import contains_explicit_llm_mention
```

Replace:

```python
if "@claude" in msg.content.lower() or "@llm" in msg.content.lower():
```

with:

```python
if contains_explicit_llm_mention(msg.content):
```

Update prose comments/docstrings from “@Claude mentions” to “explicit Dialectic mentions” without changing scoring values.

- [ ] **Step 4: Run the focused backend tests**

```bash
cd dialectic
python3 -m pytest \
  tests/test_llm_mentions.py \
  tests/test_context.py \
  tests/test_collaboration_contracts.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Write failing frontend identity tests**

Create `src/lib/productIdentity.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  ORIGIN_IMPRINT,
  PARTICIPANT_NAME,
  PARTICIPANT_SIGNATURE,
  PRODUCT_NAME,
  participantDisplayName,
} from './productIdentity'

describe('product identity', () => {
  it('keeps Dialectic as product and participant', () => {
    expect(PRODUCT_NAME).toBe('Dialectic')
    expect(PARTICIPANT_NAME).toBe('Dialectic')
    expect(PARTICIPANT_SIGNATURE).toBe(')')
    expect(ORIGIN_IMPRINT).toBe('DwoodAmo')
  })

  it('names participant modes without exposing a provider', () => {
    expect(participantDisplayName('llm_primary')).toBe('Dialectic')
    expect(participantDisplayName('llm_provoker')).toBe('Dialectic · Provoker')
    expect(participantDisplayName('llm_annotator')).toBe('Dialectic · Note')
    expect(participantDisplayName('system')).toBe('System')
  })
})
```

- [ ] **Step 6: Run and verify RED**

```bash
cd dialectic/frontend/app
npm test -- src/lib/productIdentity.test.ts
```

Expected: FAIL because `productIdentity.ts` does not exist.

- [ ] **Step 7: Add the identity constants and speaker-label helper**

Create `src/lib/productIdentity.ts`:

```ts
import type { Message } from '../types'

export const PRODUCT_NAME = 'Dialectic'
export const PARTICIPANT_NAME = 'Dialectic'
export const PARTICIPANT_SIGNATURE = ')'
export const ORIGIN_IMPRINT = 'DwoodAmo'

export function participantDisplayName(
  speakerType: Message['speaker_type'],
  personaName?: string | null,
): string {
  switch (speakerType) {
    case 'llm_primary':
      return PARTICIPANT_NAME
    case 'llm_provoker':
      return `${PARTICIPANT_NAME} · Provoker`
    case 'llm_annotator':
      return `${PARTICIPANT_NAME} · Note`
    case 'llm_persona':
      return personaName?.trim() || PARTICIPANT_NAME
    case 'system':
      return 'System'
    default:
      return PARTICIPANT_NAME
  }
}
```

- [ ] **Step 8: Replace primary user-facing provider labels**

Use the constants/helper in these exact places:

`App.tsx`:

```ts
import {
  PARTICIPANT_NAME,
} from './lib/productIdentity.ts'
```

Replace:

```ts
: 'Claude'
```

for LLM reply targets with `PARTICIPANT_NAME`.

Replace typing display:

```ts
if (isLLMThinking && !isLLMStreaming) typingDisplay.push(PARTICIPANT_NAME)
```

Replace the participant row:

```ts
{
  id: 'dialectic',
  name: PARTICIPANT_NAME,
  isOnline: true,
  isClaude: true,
}
```

The `isClaude` prop name remains internal compatibility in this tranche.

Replace Home placeholder:

```tsx
placeholder={isHome ? `Sit down — ${PARTICIPANT_NAME} is already here` : undefined}
```

`MessageList.tsx`:

```ts
import { participantDisplayName } from '../../lib/productIdentity'
```

Replace the LLM branches in `getAuthorName` with:

```ts
if (msg.speaker_type.startsWith('llm_')) {
  return participantDisplayName(msg.speaker_type, msg.persona_name)
}
```

Change empty-state copy to:

```tsx
<p>Type a message to begin. Dialectic will join the conversation.</p>
```

`MessageBubble.tsx`:

```ts
import { PARTICIPANT_SIGNATURE } from '../../lib/productIdentity'
```

Return `PARTICIPANT_SIGNATURE` for `llm_primary`; preserve `!` for provoker and use `)` for annotator rather than inventing a robot glyph.

`MessageInput.tsx`:

```ts
placeholder = 'Think out loud... paste a link and Dialectic reads it'
```

`HomeActivityPulse.tsx`:

- Keep the internal `isClaude` property for compatibility.
- Change title text to `Dialectic lives here`.
- Change `displaySpeaker` mappings to `Dialectic`.

`MemoryPanel.tsx`:

- `Claude’s papers` → `Dialectic’s papers`
- `Claude's identity` → `Dialectic's identity`

`HelpDialog.tsx`:

- Visible participant references become Dialectic.
- Primary summon becomes `@Dialectic`.
- Add one compatibility sentence: `@Claude and @llm still work.`
- Preserve the human-tap trust explanation.

`RoomSettingsDialog.tsx`:

- Replace visible “Claude” labels with “Dialectic”.
- Do not rename backend field names or API payload keys.

Do not rename:

- `SpeakerType` values.
- `llm_*` fields.
- provider/model strings.
- persisted content.
- CSS class names such as `.msg-claude` or `--claude-primary` in this tranche.
- `CLAUDE.md` files.

- [ ] **Step 9: Add a rendered author-label regression test**

Extend `productIdentity.test.ts` only for the pure helper; add a component assertion to `WorkspaceSceneFrame.test.tsx` is not relevant. Instead create `src/components/chat/MessageList.identity.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MessageList } from './MessageList'
import type { Message } from '../../types'

const llmMessage: Message = {
  id: 'm1',
  thread_id: 't1',
  sequence: 1,
  created_at: '2026-08-12T12:00:00Z',
  speaker_type: 'llm_primary',
  user_id: null,
  message_type: 'text',
  content: 'The third participant is here.',
}

describe('MessageList participant identity', () => {
  it('renders Dialectic rather than a provider brand', () => {
    render(
      <MessageList
        messages={[llmMessage]}
        currentUserId="human"
      />,
    )
    expect(screen.getByText('Dialectic')).toBeInTheDocument()
    expect(screen.queryByText('Claude')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 10: Run frontend identity tests, lint, and build**

```bash
cd dialectic/frontend/app
npm test -- \
  src/lib/productIdentity.test.ts \
  src/components/chat/MessageList.identity.test.tsx
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 11: Run the focused backend gate again**

```bash
cd dialectic
python3 -m pytest \
  tests/test_llm_mentions.py \
  tests/test_context.py \
  tests/test_collaboration_contracts.py \
  -q
```

Expected: PASS.

- [ ] **Step 12: Inspect remaining frontend provider labels**

Run:

```bash
rg -n "@Claude|Claude" dialectic/frontend/app/src
```

Expected remaining matches are limited to:

- Internal compatibility identifiers/comments such as `isClaude`.
- CSS compatibility class/token names.
- Explicit compatibility copy saying `@Claude` still works.
- Technical provenance where a provider/model is intentionally named.

Any primary control, byline, placeholder, help heading, activity label, or empty-state copy still using Claude must be changed before commit.

- [ ] **Step 13: Commit**

```bash
git add \
  dialectic/llm/mentions.py \
  dialectic/llm/context.py \
  dialectic/transport/handlers.py \
  dialectic/tests/test_llm_mentions.py \
  dialectic/frontend/app/src/lib/productIdentity.ts \
  dialectic/frontend/app/src/lib/productIdentity.test.ts \
  dialectic/frontend/app/src/App.tsx \
  dialectic/frontend/app/src/components/chat/MessageList.tsx \
  dialectic/frontend/app/src/components/chat/MessageList.identity.test.tsx \
  dialectic/frontend/app/src/components/chat/MessageBubble.tsx \
  dialectic/frontend/app/src/components/chat/MessageInput.tsx \
  dialectic/frontend/app/src/components/home/HomeActivityPulse.tsx \
  dialectic/frontend/app/src/components/sidebar/MemoryPanel.tsx \
  dialectic/frontend/app/src/components/layout/HelpDialog.tsx \
  dialectic/frontend/app/src/components/layout/RoomSettingsDialog.tsx
git commit -m "feat(identity): Dialectic enters the room -- provider names move to provenance"
```

---

### Task 6: Prove navigation, responsive behavior, and existing room capabilities in the browser

**Files:**
- No shipping file required unless a defect is found.
- Modify the exact affected source/test files if acceptance reveals a regression.

**Interfaces:**
- Consumes: all Tasks 1-5.
- Produces: browser evidence for the Tranche 1 exit gate.

- [ ] **Step 1: Run the complete automated gate before browser work**

```bash
cd dialectic
python3 -m pytest tests/ -q

cd frontend/app
npm test
npm run lint
npm run build
```

Expected: zero backend failures, zero frontend test failures, lint exit 0, build exit 0. Record the fresh backend pass count from this run; do not reuse 1,061 from the prior commit message.

- [ ] **Step 2: Start the isolated browser fixture, never production**

Use the existing `dialectic_browser` fixture described in `docs/handoffs/2026-08-12-home-base-session.md`.

Backend terminal:

```bash
cd /root/DwoodAmo/dialectic
export DATABASE_URL='postgresql://localhost/dialectic_browser'
export JWT_SECRET_KEY='browser-scene-kernel-secret-32-bytes-minimum'
export ANTHROPIC_API_KEY='browser-fixture-dummy-key'
export SIGNUPS_ENABLED=1
export SCHEDULER_ENABLED=0
export PORT=8013
python3 run.py
```

Frontend terminal:

```bash
cd /root/DwoodAmo/dialectic/frontend/app
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run build
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run preview -- --port 4173
```

Before opening the new build, unregister any old service worker for `localhost:4173` and clear the site's Cache Storage. The Home handoff records that a stale precache otherwise serves the previous bundle and invalidates the proof.

- [ ] **Step 3: Verify Home root House behavior**

At `http://localhost:4173/` with a founder fixture session:

- URL remains `/`.
- Home room is installed.
- House is selected with `aria-current="page"`.
- Home residents, Needs you, and scheme doors are visible.
- The table remains available beneath House.
- Dialectic, not Claude, is the visible third resident.

Expected: all assertions pass without console error.

- [ ] **Step 4: Verify Home Record navigation and history**

- Click Record.
- Expected URL: `/?scene=record`.
- Home pulse is hidden.
- Record content, composer, proposals, and right panel remain functional.
- Reload and verify Record remains selected.
- Use Back and verify `/` returns to House without duplicate history entries.
- Use Forward and verify `/?scene=record` returns to Record.

- [ ] **Step 5: Verify ordinary room and branch canonical URLs**

- Open an ordinary room root.
- Expected URL remains `/?room=<room-id>` with no `scene=record` noise.
- No House switch appears.
- Record content is visible.
- Open a non-root branch.
- Expected URL remains `/?room=<room-id>&thread=<thread-id>`.
- Reload and verify the exact branch remains selected.
- Open a Home branch and verify it also defaults to Record rather than House.

- [ ] **Step 6: Verify navigation integrations**

- Search to a message in another branch; the drawer closes and the target flashes.
- Trigger the service-worker `open-room` message; destination installs through the same navigation transaction.
- Revoke a persisted room fixture; the app fails closed and falls back without ghost requests.
- Confirm create/join still enters through `RoomAccess` and does not bypass navigation.

- [ ] **Step 7: Verify responsive shell at exact widths**

Run the same core navigation at:

```text
1440 × 1000
1200 × 900
1024 × 768
768 × 1024
390 × 844
```

Expected:

- 1440, 1200, and exactly 1024 use desktop rails.
- 768 and 390 use room and cockpit drawers.
- Scrim and Escape close drawers.
- Scene changes close any open drawer through navigation.
- The software-keyboard viewport does not obscure the composer at phone width.
- No essential action depends on hover.

- [ ] **Step 8: Verify high-risk preserved capabilities**

In one ordinary room:

- Send and reply to a message.
- Start and cancel an LLM stream.
- Start Research and verify the button disarms until completion.
- Open a prediction/thesis/commitment/reading proposal card without accepting production writes.
- Open Memory and personal-promotion controls.
- Open Trading in an unbound room and confirm Create Thesis remains reachable.
- Open Home Trading and confirm thesis creation remains refused/explained.
- Open Protocol, Stakes, Search, and branch genealogy.

Expected: no capability is hidden by the scene wrapper.

- [ ] **Step 9: Fix any acceptance failure with a focused regression test**

For each failure:

1. Add the smallest unit or backend regression test that reproduces it.
2. Run the test and verify RED.
3. Apply the minimal fix.
4. Run the focused test and verify GREEN.
5. Re-run the failed browser case.
6. Commit the fix separately with a message naming the observed behavior.

Do not bundle unrelated visual cleanup into the acceptance fixes.

---

### Task 7: Final verification, journal update, and handoff commit

**Files:**
- Modify: `JOURNAL.md`
- Modify: `dialectic/TODOS.md` only if it currently has a matching living-workroom or identity item; do not create a new task board section merely for this tranche.

**Interfaces:**
- Consumes: verified integrated Tranche 1.
- Produces: recorded baseline for Tranche 2 planning.

- [ ] **Step 1: Re-run the full automated gate from a clean working tree except journal/TODO edits**

```bash
git status --short
cd dialectic
python3 -m pytest tests/ -q
cd frontend/app
npm test
npm run lint
npm run build
```

Expected: only intentional journal/TODO changes appear; all verification commands exit 0.

- [ ] **Step 2: Run static architecture checks**

From repository root:

```bash
rg -n "setRoom\(|setThread\(|leaveRoom\(" \
  dialectic/frontend/app/src \
  -g '!stores/appStore.ts' \
  -g '!hooks/useRoomNavigation.ts'
```

Expected: no destination writes outside the store implementation and navigation hook.

```bash
rg -n "@Dialectic|@Claude|@llm" \
  dialectic/llm \
  dialectic/transport \
  dialectic/frontend/app/src
```

Expected: `@Dialectic` is the primary visible summon; all three aliases feed the one backend helper; compatibility mentions are intentional.

```bash
rg -n "max-width: 1023\.98px" dialectic/frontend/app/src/components/layout/AppLayout.css
```

Expected: one match; the 1024 desktop contract remains intact.

- [ ] **Step 3: Append one decision line to `JOURNAL.md`**

Append the fresh verified facts, using the actual pass count and commit range:

```text
[2026-08-12] Landed the living-workroom scene kernel — Home root is explicit House, conversation is explicit Record, current room/branch URLs remain canonical, and @Dialectic is primary while @Claude/@llm remain compatibility aliases; verified <actual backend count> backend tests, frontend tests, lint, build, and isolated browser acceptance across desktop/tablet/phone widths.
```

Replace `<actual backend count>` with the number from Task 7 Step 1 before committing.

- [ ] **Step 4: Inspect the complete tranche diff**

```bash
git diff --stat HEAD~7..HEAD
git diff --check HEAD~7..HEAD
git log --oneline --decorate -12
```

Expected:

- No whitespace errors.
- No backend schema change.
- No service/deploy file change.
- Commits remain task-scoped.
- No generated screenshots, build output, caches, or local fixture secrets are tracked.

Use the actual first tranche commit rather than `HEAD~7` if acceptance produced additional focused commits.

- [ ] **Step 5: Commit the journal/TODO update**

```bash
git add JOURNAL.md dialectic/TODOS.md
git commit -m "docs: record the scene-kernel gate -- House and Record hold"
```

If `dialectic/TODOS.md` had no matching item and was not modified, omit it from `git add`.

- [ ] **Step 6: Prepare the execution handoff**

Report exactly:

```text
CHANGES: files and behavioral impact
VERIFIED: commands actually run and observed pass counts
UNVERIFIED: real-device macOS/Windows/iOS/Android checks not performed in the implementation environment
NEXT: write the House v2 detailed plan against the integrated head
```

Do not claim production deployment. This plan completes an implementation branch/worktree only.

---

## Plan self-review

### Spec coverage

This tranche covers the v2 design's:

- One navigation spine.
- Home → House default.
- Explicit Record scene.
- Progressive React-PWA recomposition.
- Provider-to-product identity boundary.
- Cross-platform responsive preservation.
- Existing substrate regression requirements.

It intentionally does not implement House v2 semantic movement, WorkspaceObject adapters, evidence scenes, Thesis Bench, Record repositioning, Field, Focus, Atlas, or exact device-local restoration. Those are separate program tranches with explicit dependency gates.

### Placeholder scan

The plan contains no `TBD`, generic “add error handling,” unspecified test request, or undefined interface. The one `<actual backend count>` token is not an implementation placeholder: Task 7 explicitly requires replacing it with fresh observed output before commit.

### Type consistency

- `WorkspaceScene` includes approved future scene names.
- `ImplementedWorkspaceScene` is exactly `house | record` in this tranche.
- `RoomDestination.scene` accepts `WorkspaceScene | null`.
- `resolveWorkspaceScene` returns `ImplementedWorkspaceScene`.
- Zustand stores only `ImplementedWorkspaceScene`.
- `WorkspaceSceneFrame` accepts only `ImplementedWorkspaceScene`.
- `destinationUrl` serializes only a resolved implemented scene.

No later task calls a signature different from the one defined earlier.
