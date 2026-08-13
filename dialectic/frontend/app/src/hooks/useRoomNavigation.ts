import { useCallback, useEffect, useRef, useState } from 'react'
import { useAppStore } from '../stores/appStore.ts'
import { api, ApiError } from '../lib/api.ts'
import type { HistoryMode, RoomDestination, Thread, UserRoom } from '../types/index.ts'

/**
 * The ONE URL-authoritative navigation transaction.
 *
 * Every destination change — initial load, rail tap, branch select, search
 * jump, notification entry, popstate, create/join — flows through
 * `navigate`, which owns destination validation, room/thread state
 * installation, URL history, revoked-room correction, and mobile drawer
 * close. No component writes setRoom/setThread/leaveRoom to express a
 * destination; the competing effects this replaces caused stale-closure
 * and history-order regressions.
 */

// The route grammar moved to lib/workspaceRoute so it can be unit-tested without
// mounting this hook. Imported for internal use AND re-exported, because existing
// call sites import these names from here; this hook remains the one destination
// WRITER. (A bare `export ... from` would re-export without binding them locally,
// leaving the uses below undefined.)
import {
  destinationFromLocation,
  destinationUrl,
  entryDestination,
  resolveWorkspaceScene,
} from '../lib/workspaceRoute.ts'

export { destinationFromLocation, destinationUrl }

/** Local descriptor for the guest invite path — no JWT saved-room list. */
function guestDescriptor(room: Pick<UserRoom, 'id' | 'name' | 'token'>): UserRoom {
  return {
    id: room.id,
    name: room.name,
    token: room.token,
    is_home: false,
    can_manage_home: false,
    unread_count: 0,
    last_message_at: null,
    last_message_preview: null,
    last_read_at: null,
    joined_at: null,
  }
}

export interface RoomNavigation {
  rooms: UserRoom[]
  loading: boolean
  /** True once the initial destination is definitively installed or refused. */
  ready: boolean
  /** Room-list load failure, if any. */
  error: string | null
  /** Why the last requested destination was refused, if it was. */
  accessError: string | null
  clearAccessError: () => void
  refreshRooms: () => Promise<UserRoom[]>
  navigate: (
    destination: RoomDestination,
    historyMode?: HistoryMode,
  ) => Promise<boolean>
  enterGrantedRoom: (
    granted: Pick<UserRoom, 'id' | 'name' | 'token'>,
  ) => Promise<boolean>
}

export function useRoomNavigation(): RoomNavigation {
  const setRoom = useAppStore((s) => s.setRoom)
  const setThread = useAppStore((s) => s.setThread)
  const setThreads = useAppStore((s) => s.setThreads)
  const setMobileDrawer = useAppStore((s) => s.setMobileDrawer)
  const setWorkspaceScene = useAppStore((s) => s.setWorkspaceScene)

  const [rooms, setRooms] = useState<UserRoom[]>([])
  const [loading, setLoading] = useState(true)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [accessError, setAccessError] = useState<string | null>(null)

  const roomsRef = useRef<UserRoom[]>([])
  const loadRef = useRef<Promise<UserRoom[]> | null>(null)
  // Monotonic attempt counter: a slower earlier fetch can never overwrite
  // a later tap.
  const attemptRef = useRef(0)
  const navigateRef = useRef<RoomNavigation['navigate']>(async () => false)

  const refreshRooms = useCallback((): Promise<UserRoom[]> => {
    const load = (async () => {
      // WHY the microtask: the boot effect calls this synchronously, and
      // React's set-state-in-effect rule (rightly) refuses state writes in
      // an effect's synchronous frame. Everything below runs after it.
      await Promise.resolve()
      setLoading(true)
      const persisted = useAppStore.getState()
      if (!persisted.accessToken) {
        // Guest identities have no JWT-backed saved-room list; their one
        // room arrives via enterGrantedRoom or rides in from persistence.
        const list = persisted.currentRoom && persisted.roomToken
          ? [guestDescriptor({
              id: persisted.currentRoom.id,
              name: persisted.currentRoom.name,
              token: persisted.roomToken,
            })]
          : []
        roomsRef.current = list
        setRooms(list)
        setError(null)
        return list
      }
      try {
        const list = await api.getRooms()
        roomsRef.current = list
        setRooms(list)
        setError(null)
        return list
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load rooms')
        return roomsRef.current
      }
    })()
    loadRef.current = load
    void load.finally(() => {
      if (loadRef.current === load) loadRef.current = null
      setLoading(false)
    })
    return load
  }, [])

  const navigate = useCallback(async (
    destination: RoomDestination,
    historyMode: HistoryMode = 'push',
  ): Promise<boolean> => {
    const attempt = ++attemptRef.current

    // Early popstate and notification entries queue behind the in-flight
    // rooms load instead of taking an error fallback.
    if (loadRef.current) await loadRef.current.catch(() => undefined)
    if (attempt !== attemptRef.current) return false

    // A denied explicit destination is corrected to Home with replace
    // history, so Back never returns to a room the user cannot open.
    const denied = async (message: string): Promise<false> => {
      setAccessError(message)
      await refreshRooms()
      let homeInstalled = false
      if (destination.roomId !== null) {
        homeInstalled = await navigateRef.current({ roomId: null }, 'replace')
      }
      if (!homeInstalled) {
        const state = useAppStore.getState()
        if (state.currentRoom && state.currentRoom.id === destination.roomId) {
          // The refused room is also the installed one — clear it so the
          // full selector renders rather than a dead chat.
          state.leaveRoom()
        }
      }
      setReady(true)
      return false
    }

    const list = roomsRef.current
    const room = destination.roomId === null
      ? list.find((candidate) => candidate.is_home)
      : list.find((candidate) => candidate.id === destination.roomId)

    if (!room?.token) {
      if (destination.roomId === null) return false
      return denied('That room is no longer available to you.')
    }

    api.setRoomToken(room.token)

    const state = useAppStore.getState()
    let threads: Thread[]
    if (state.currentRoom?.id === room.id && state.threads.length > 0) {
      threads = state.threads
    } else {
      try {
        threads = await api.getThreads(room.id)
      } catch (err) {
        if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
          return denied('Your access to that room was revoked.')
        }
        // A network blip must NOT eject the user — stay put.
        setAccessError('Could not reach the server — try again.')
        return false
      }
    }
    if (attempt !== attemptRef.current) return false

    const requested = destination.threadId
      ? threads.find((thread) => thread.id === destination.threadId)
      : undefined
    const thread = requested
      ?? threads.find((candidate) => candidate.parent_thread_id === null)
      ?? threads[0]
    if (!thread) return denied('That room has no branches yet.')

    // Scene resolves against the destination that was actually reached, not the
    // one requested: an unavailable or ill-fitting scene lands on the default
    // rather than erroring, and the URL below serializes what we installed.
    const scene = resolveWorkspaceScene(room, thread, destination.scene)

    if (state.currentRoom?.id !== room.id) {
      setRoom(
        { id: room.id, name: room.name, token: room.token, is_home: room.is_home },
        room.token,
      )
    }
    setThreads(threads)
    setThread(thread)
    // AFTER setRoom, which resets the scene to 'record' on a room change.
    setWorkspaceScene(scene)

    const url = destinationUrl(room, thread, scene)
    if (historyMode === 'push') window.history.pushState(null, '', url)
    else if (historyMode === 'replace') window.history.replaceState(null, '', url)
    // 'none' (popstate, initial entry) mutates no history.

    // Successful state installation is the one destination-driven drawer
    // close — including branch changes within the same room.
    setMobileDrawer(null)
    setAccessError(null)
    setReady(true)
    // Badge parity: entering a room used to refetch the saved-room list.
    void refreshRooms()
    return true
  }, [refreshRooms, setMobileDrawer, setRoom, setThread, setThreads, setWorkspaceScene])

  useEffect(() => {
    navigateRef.current = navigate
  }, [navigate])

  const enterGrantedRoom = useCallback(async (
    granted: Pick<UserRoom, 'id' | 'name' | 'token'>,
  ): Promise<boolean> => {
    if (useAppStore.getState().accessToken) {
      await refreshRooms()
    } else {
      // Guest path: one local descriptor, then the SAME navigation
      // transaction — no alternate state-installation path.
      const list = [
        ...roomsRef.current.filter((room) => room.id !== granted.id),
        guestDescriptor(granted),
      ]
      roomsRef.current = list
      setRooms(list)
    }
    return navigateRef.current({ roomId: granted.id }, 'push')
  }, [refreshRooms])

  // Initial entry: an explicit room/thread URL wins; a bare URL enters
  // Home's root regardless of any persisted room. Both use 'none' history.
  const bootedRef = useRef(false)
  useEffect(() => {
    if (bootedRef.current) return
    bootedRef.current = true
    void refreshRooms()
    const parsed = destinationFromLocation(window.location)
    void (async () => {
      const installed = await navigateRef.current(
        entryDestination(parsed),
        'none',
      )
      if (!installed) setReady(true)
    })()
  }, [refreshRooms])

  // Back/Forward re-entry is history-neutral: never a push, never a replace.
  useEffect(() => {
    const onPopState = () => {
      const parsed = destinationFromLocation(window.location)
      void navigateRef.current(
        entryDestination(parsed),
        'none',
      )
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  // A tapped push notification: the service worker posts open-room into a
  // live window (cold starts arrive as /?room=<id> through initial entry).
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; roomId?: string } | null
      if (data?.type === 'open-room' && data.roomId) {
        void navigateRef.current({ roomId: data.roomId }, 'push')
      }
    }
    navigator.serviceWorker.addEventListener('message', onMessage)
    return () => navigator.serviceWorker.removeEventListener('message', onMessage)
  }, [])

  const clearAccessError = useCallback(() => setAccessError(null), [])

  return {
    rooms,
    loading,
    ready,
    error,
    accessError,
    clearAccessError,
    refreshRooms,
    navigate,
    enterGrantedRoom,
  }
}
