import { beforeEach, describe, expect, it } from 'vitest'
import {
  chooseEntryDestination,
  forgetScene,
  isExplicitDestination,
  rememberScene,
  restoreScene,
} from './sceneContinuity.ts'
import type { RoomDestination, UserRoom } from '../types'

/**
 * Task Group E — device-local continuity (design v2 §15.2–15.5).
 *
 * The precedence is the whole feature, so it lives in a pure function rather
 * than inside the navigation hook: an ordering this consequential has to be
 * provable without mounting anything.
 *
 *     deep link / notification  >  local restoration  >  Home → House
 */

const AMO = 'user-amo'
const DAN = 'user-dan'

function room(over: Partial<UserRoom> = {}): UserRoom {
  return {
    id: 'room-1', name: 'Scheme Room', token: 'tok-1', is_home: false,
    can_manage_home: false, unread_count: 0, last_message_at: null,
    last_message_preview: null, last_read_at: null, joined_at: null,
    ...over,
  } as UserRoom
}

const HOME = room({ id: 'room-home', name: 'Home', is_home: true, token: 'tok-h' })
const ROOMS = [HOME, room()]

const bare: RoomDestination = { roomId: null, threadId: null, scene: null }

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})

describe('what counts as an explicit destination', () => {
  it('treats a bare URL as no request at all', () => {
    expect(isExplicitDestination(bare)).toBe(false)
  })

  it('treats a room, a branch or a scene as an explicit request', () => {
    expect(isExplicitDestination({ ...bare, roomId: 'room-1' })).toBe(true)
    expect(isExplicitDestination({ ...bare, threadId: 'branch-9' })).toBe(true)
    // `/?scene=record` is somebody asking for the Record at Home, and it must
    // outrank a restored House exactly as a room link does.
    expect(isExplicitDestination({ ...bare, scene: 'record' })).toBe(true)
  })
})

describe('startup precedence', () => {
  const restored: RoomDestination = {
    roomId: 'room-1', threadId: 'branch-9', scene: 'record',
  }

  it('gives a deep link the last word over stored local state', () => {
    const chosen = chooseEntryDestination(
      { roomId: 'room-2', threadId: null, scene: null }, restored,
    )
    expect(chosen.roomId).toBe('room-2')
  })

  it('gives a notification entry the last word too', () => {
    // A notification cold-starts as /?room=<id>; it is the same shape as any
    // deep link and must not be quietly redirected to where the user was last.
    const chosen = chooseEntryDestination(
      { roomId: 'room-notified', threadId: null, scene: null }, restored,
    )
    expect(chosen).toEqual({
      roomId: 'room-notified', threadId: null, scene: null,
    })
  })

  it('restores local state on a bare URL', () => {
    expect(chooseEntryDestination(bare, restored)).toEqual(restored)
  })

  it('opens Home → House on a bare URL with nothing stored', () => {
    expect(chooseEntryDestination(bare, null)).toEqual({
      // object: null joined roomId/threadId/scene here when Release 3 (§5.2)
      // extended RoomDestination with the Focus object axis and
      // entryDestination started preserving it the same way it already
      // preserved scene (workspaceRoute.ts) — not a behavior change here.
      roomId: null, threadId: null, scene: null, object: null,
    })
  })

  it('keeps a scene-only URL rather than restoring over it', () => {
    const chosen = chooseEntryDestination(
      { roomId: null, threadId: null, scene: 'record' }, restored,
    )
    expect(chosen).toEqual({ roomId: null, threadId: null, scene: 'record', object: null })
  })
})

describe('remembering and restoring', () => {
  it('restores what was last installed, scene included', () => {
    rememberScene(AMO, { roomId: 'room-1', threadId: 'branch-9', scene: 'record' })
    expect(restoreScene(AMO, ROOMS)).toEqual({
      roomId: 'room-1', threadId: 'branch-9', scene: 'record',
    })
  })

  it('restores a Home scene, which is not the same as no state', () => {
    // Home + Record is a real place the user chose to be; falling back to
    // Home + House would silently undo it on every reload.
    rememberScene(AMO, { roomId: null, threadId: null, scene: 'record' })
    expect(restoreScene(AMO, ROOMS)?.scene).toBe('record')
  })

  it('has nothing to restore before anything is remembered', () => {
    expect(restoreScene(AMO, ROOMS)).toBeNull()
  })
})

describe('a room the user no longer has', () => {
  it('falls back without ever asking for it', () => {
    // §E3: it must not leak the room existence. The candidate is checked
    // against the rooms the caller already holds, so navigation is never asked
    // for a room it would have to refuse — no access error, no "that room is
    // no longer available" for a room the user did not request.
    rememberScene(AMO, { roomId: 'room-gone', threadId: null, scene: 'record' })
    expect(restoreScene(AMO, ROOMS)).toBeNull()
  })

  it('restores nothing at all when the room list is not yet known', () => {
    rememberScene(AMO, { roomId: 'room-1', threadId: null, scene: 'record' })
    expect(restoreScene(AMO, [])).toBeNull()
  })
})

describe('locality', () => {
  it('does not restore one user state for another', () => {
    // A shared browser profile: Dan signing in must not land in Amo room.
    rememberScene(AMO, { roomId: 'room-1', threadId: null, scene: 'record' })
    expect(restoreScene(DAN, ROOMS)).toBeNull()
  })

  it('keeps a window own state ahead of the installation state', () => {
    // Two windows: this one was last in room-1, the installation as a whole
    // moved on to room-2. Reloading THIS window returns it to room-1.
    rememberScene(AMO, { roomId: 'room-1', threadId: null, scene: 'record' })
    window.sessionStorage.setItem(
      'dialectic-scene-window',
      JSON.stringify({ userId: AMO, roomId: 'room-1', threadId: null, scene: 'record' }),
    )
    window.localStorage.setItem(
      'dialectic-scene-install',
      JSON.stringify({ userId: AMO, roomId: 'room-2', threadId: null, scene: 'record' }),
    )
    expect(restoreScene(AMO, [...ROOMS, room({ id: 'room-2', token: 't2' })])?.roomId)
      .toBe('room-1')
  })

  it('falls back to the installation state in a window with no history', () => {
    // §15.4: a NEW window has no stable identity of its own yet, so the
    // installation most recent valid scene is the fallback.
    window.localStorage.setItem(
      'dialectic-scene-install',
      JSON.stringify({ userId: AMO, roomId: 'room-1', threadId: null, scene: 'record' }),
    )
    expect(restoreScene(AMO, ROOMS)?.roomId).toBe('room-1')
  })

  it('survives storage being unavailable or holding junk', () => {
    // Private modes and quota failures throw on write; a corrupt value is a
    // reason to open Home, never to break the boot.
    window.sessionStorage.setItem('dialectic-scene-window', 'not json {')
    window.localStorage.setItem('dialectic-scene-install', 'null')
    expect(() => restoreScene(AMO, ROOMS)).not.toThrow()
    expect(restoreScene(AMO, ROOMS)).toBeNull()
  })
})

describe('forgetting', () => {
  it('leaves nothing behind on sign-out', () => {
    // A shared device: the next person to open the app gets Home, and no
    // evidence of which rooms the last one was in.
    rememberScene(AMO, { roomId: 'room-1', threadId: 'branch-9', scene: 'record' })
    forgetScene()
    expect(restoreScene(AMO, ROOMS)).toBeNull()
    expect(window.localStorage.getItem('dialectic-scene-install')).toBeNull()
    expect(window.sessionStorage.getItem('dialectic-scene-window')).toBeNull()
    expect(JSON.stringify(window.localStorage)).not.toContain('room-1')
  })
})
