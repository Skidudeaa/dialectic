import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRoomNavigation } from './useRoomNavigation.ts'
import { useAppStore } from '../stores/appStore.ts'
import { api } from '../lib/api.ts'
import type { Thread, UserRoom } from '../types'

/**
 * The `object` axis (§1.18, §5.2) — Focus's selection, threaded through the
 * ONE destination writer. The pure round-trip (destinationFromSearch /
 * destinationUrl / entryDestination) is proven in workspaceRoute.test.ts;
 * this is the part only a mounted hook can show — that `navigate` actually
 * installs the axis as hook state and into the URL, and resets it exactly
 * like every other axis a destination omits.
 */

const USER_ID = 'user-amo'

function room(over: Partial<UserRoom> = {}): UserRoom {
  return {
    id: 'room-1', name: 'Scheme Room', token: 'tok-1', is_home: false,
    can_manage_home: false, unread_count: 0, last_message_at: null,
    last_message_preview: null, last_read_at: null, joined_at: null,
    ...over,
  } as UserRoom
}

const SCHEME = room()

function threads(roomId: string): Thread[] {
  return [
    { id: `${roomId}-root`, room_id: roomId, parent_thread_id: null,
      title: 'Main', message_count: 2 },
  ]
}

function enter(url: string) {
  window.history.replaceState(null, '', url)
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  enter('/')
  useAppStore.setState({
    user: { id: USER_ID, display_name: 'Amo' } as never,
    accessToken: 'jwt',
    isAuthenticated: true,
    currentRoom: null,
    threads: [],
  } as never)
  vi.spyOn(api, 'getRooms').mockResolvedValue([SCHEME])
  vi.spyOn(api, 'getThreads').mockImplementation(async (roomId: string) => threads(roomId))
  vi.spyOn(api, 'setRoomToken').mockImplementation(() => undefined)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('the object axis', () => {
  it('starts null', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(result.current.objectId).toBeNull()
  })

  it('installs an object id navigate is given, and carries it into the URL', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))

    await act(async () => {
      await result.current.navigate({ roomId: SCHEME.id, object: 'field_mark:abc' }, 'push')
    })

    expect(result.current.objectId).toBe('field_mark:abc')
    expect(window.location.search).toContain('object=field_mark%3Aabc')
  })

  it('carries a geo-scope root id through the same object axis unchanged', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))

    await act(async () => {
      await result.current.navigate({ roomId: SCHEME.id, object: 'geo_scope:root-1' }, 'push')
    })

    expect(result.current.objectId).toBe('geo_scope:root-1')
    expect(window.location.search).toContain('object=geo_scope%3Aroot-1')
  })

  it('resets to null on a destination that does not carry it — same as scene', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))

    await act(async () => {
      await result.current.navigate({ roomId: SCHEME.id, object: 'field_mark:abc' }, 'push')
    })
    expect(result.current.objectId).toBe('field_mark:abc')

    // An ordinary destination change (no `object` key at all) closes Focus —
    // this is how a plain rail tap or thread switch closes it without any
    // call site needing to remember to pass `object: null` itself.
    await act(async () => {
      await result.current.navigate({ roomId: SCHEME.id }, 'push')
    })
    expect(result.current.objectId).toBeNull()
    expect(window.location.search).not.toContain('object=')
  })

  it('closes on an explicit object: null', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))

    await act(async () => {
      await result.current.navigate({ roomId: SCHEME.id, object: 'field_mark:abc' }, 'push')
    })
    await act(async () => {
      await result.current.navigate({ roomId: SCHEME.id, object: null }, 'push')
    })
    expect(result.current.objectId).toBeNull()
  })
})
