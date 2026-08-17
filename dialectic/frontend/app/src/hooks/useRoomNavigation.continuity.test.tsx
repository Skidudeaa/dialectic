import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRoomNavigation } from './useRoomNavigation.ts'
import { useAppStore } from '../stores/appStore.ts'
import { rememberScene, restoreScene } from '../lib/sceneContinuity.ts'
import { api } from '../lib/api.ts'
import type { Thread, UserRoom } from '../types'

/**
 * Task Group E, wired — not just the rule.
 *
 * The precedence itself is proven on the pure function in
 * lib/sceneContinuity.test.ts. What only a mounted hook can show is that boot
 * actually CONSULTS it, that what gets remembered is what was installed rather
 * than what was requested, and — the one that would be invisible otherwise —
 * that a restored room the user has lost falls back with no access error.
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

const HOME = room({ id: 'room-home', name: 'Home', is_home: true, token: 'tok-h' })
const SCHEME = room()
const OTHER = room({ id: 'room-2', name: 'Other', token: 'tok-2' })
let serviceWorkerMessage: ((event: MessageEvent) => void) | null = null

function threads(roomId: string): Thread[] {
  return [
    { id: `${roomId}-root`, room_id: roomId, parent_thread_id: null,
      title: 'Main', message_count: 2 },
    { id: `${roomId}-branch`, room_id: roomId,
      parent_thread_id: `${roomId}-root`, title: 'Branch', message_count: 1 },
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
  vi.spyOn(api, 'getRooms').mockResolvedValue([HOME, SCHEME])
  vi.spyOn(api, 'getThreads').mockImplementation(
    async (roomId: string) => threads(roomId),
  )
  vi.spyOn(api, 'setRoomToken').mockImplementation(() => undefined)
  serviceWorkerMessage = null
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      addEventListener: vi.fn((type: string, listener: (event: MessageEvent) => void) => {
        if (type === 'message') serviceWorkerMessage = listener
      }),
      removeEventListener: vi.fn(),
    },
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('boot with nothing stored', () => {
  it('opens Home', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(useAppStore.getState().currentRoom?.id).toBe(HOME.id)
  })
})

describe('boot with a stored scene', () => {
  it('restores it on a bare URL', async () => {
    rememberScene(USER_ID, {
      roomId: SCHEME.id, threadId: `${SCHEME.id}-branch`, scene: 'record',
    })
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    const state = useAppStore.getState()
    expect(state.currentRoom?.id).toBe(SCHEME.id)
    expect(state.currentThread?.id).toBe(`${SCHEME.id}-branch`)
  })

  it('rewrites the address bar to the restored destination', async () => {
    // A URL-authoritative app whose address bar reads `/` while a room is on
    // screen has a URL nobody can copy, share, or reload into the same place.
    // Replace, not push: Back must still leave the app rather than walking
    // back through a destination the user never chose.
    rememberScene(USER_ID, {
      roomId: SCHEME.id, threadId: null, scene: 'record',
    })
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(window.location.search).toContain(`room=${SCHEME.id}`)
  })

  it('leaves a deep link URL exactly as it arrived', async () => {
    vi.mocked(api.getRooms).mockResolvedValue([HOME, SCHEME, OTHER])
    enter(`/?room=${OTHER.id}`)
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(window.location.search).toBe(`?room=${OTHER.id}`)
  })

  it('lets an explicit room URL win over it', async () => {
    rememberScene(USER_ID, {
      roomId: SCHEME.id, threadId: null, scene: 'record',
    })
    vi.mocked(api.getRooms).mockResolvedValue([HOME, SCHEME, OTHER])
    enter(`/?room=${OTHER.id}`)
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(useAppStore.getState().currentRoom?.id).toBe(OTHER.id)
  })

  it('lets a notification entry win over it', async () => {
    // A cold-started notification arrives as a complete URL. Landing the user
    // where they were last instead of on the thing they were notified about
    // is the failure this guards.
    rememberScene(USER_ID, { roomId: SCHEME.id, threadId: null, scene: 'record' })
    vi.mocked(api.getRooms).mockResolvedValue([HOME, SCHEME, OTHER])
    enter(`/?room=${OTHER.id}&thread=${OTHER.id}-branch&message=message-cold`)
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(useAppStore.getState().currentRoom?.id).toBe(OTHER.id)
    expect(useAppStore.getState().currentThread?.id).toBe(`${OTHER.id}-branch`)
    expect(result.current.messageId).toBe('message-cold')
    expect(window.location.search).toContain('message=message-cold')
  })
})

describe('warm notification navigation', () => {
  it('installs every axis through navigate and writes exact history', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))

    const acknowledge = vi.fn()
    act(() => {
      serviceWorkerMessage?.({
        data: {
          type: 'open-message',
          roomId: SCHEME.id,
          threadId: `${SCHEME.id}-branch`,
          messageId: 'message-warm',
        },
        ports: [{ postMessage: acknowledge }],
      } as MessageEvent)
    })

    await waitFor(() => expect(result.current.messageId).toBe('message-warm'))
    expect(useAppStore.getState().currentRoom?.id).toBe(SCHEME.id)
    expect(useAppStore.getState().currentThread?.id).toBe(`${SCHEME.id}-branch`)
    expect(window.location.search).toContain('message=message-warm')
    expect(acknowledge).toHaveBeenCalledWith({ type: 'navigation-received' })
  })

  it('drops a message for a missing branch and on ordinary navigation', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))

    await act(async () => {
      await result.current.navigate({
        roomId: SCHEME.id,
        threadId: 'ghost-branch',
        messageId: 'message-ghost',
      })
    })
    expect(result.current.messageId).toBeNull()
    expect(window.location.search).not.toContain('message=')

    await act(async () => {
      await result.current.navigate({
        roomId: SCHEME.id,
        threadId: `${SCHEME.id}-branch`,
        messageId: 'message-real',
      })
    })
    expect(result.current.messageId).toBe('message-real')

    await act(async () => {
      await result.current.navigate({ roomId: SCHEME.id })
    })
    expect(result.current.messageId).toBeNull()
    expect(window.location.search).not.toContain('message=')
  })
})

describe('a stored room the user has lost', () => {
  it('falls back to Home in silence', async () => {
    // §E3: no access error. Telling someone "that room is no longer available
    // to you" about a room they did not ask for announces both that the room
    // exists and that they were removed from it.
    rememberScene(USER_ID, {
      roomId: 'room-revoked', threadId: null, scene: 'record',
    })
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(useAppStore.getState().currentRoom?.id).toBe(HOME.id)
    expect(result.current.accessError).toBeNull()
    expect(api.getThreads).not.toHaveBeenCalledWith('room-revoked')
  })

  it('still refuses an explicitly requested one out loud', async () => {
    // The mirror case: a deep link to a lost room SHOULD say so, because the
    // user asked and deserves an answer.
    enter('/?room=room-revoked')
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.accessError).toBeTruthy())
  })
})

describe('what gets remembered', () => {
  it('is what was installed, not what was asked for', async () => {
    // The branch here does not exist, so navigation lands on the room root.
    // Remembering the REQUEST would store a branch that is not there and
    // restore into a fallback on every reload.
    enter(`/?room=${SCHEME.id}&thread=ghost-branch`)
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(restoreScene(USER_ID, [HOME, SCHEME])).toEqual({
      roomId: SCHEME.id, threadId: null, scene: 'record', object: null,
    })
  })

  it('stores Home root as Home, not as a room id', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(restoreScene(USER_ID, [HOME, SCHEME])).toEqual({
      roomId: null, threadId: null, scene: 'house', object: null,
    })
  })

  it('is dropped on sign-out', async () => {
    const { result } = renderHook(() => useRoomNavigation())
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(restoreScene(USER_ID, [HOME, SCHEME])).not.toBeNull()
    useAppStore.getState().logout()
    expect(restoreScene(USER_ID, [HOME, SCHEME])).toBeNull()
  })
})
