import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.ts'
import type { AtlasProjection } from '../types/atlas.ts'

/**
 * The caller's own cross-room Atlas, in the three states a surface must be
 * able to tell apart -- copied wholesale from useWorkspaceObjects.ts's idiom
 * (request-ticket ref, microtask before first setState, loading|unavailable|
 * ready). See that file for the full rationale; it applies unchanged here.
 *
 * WHY no room token: Atlas is cross-room by construction (§5.4) -- JWT alone,
 * same as `api.getHomeActivity()`.
 */
type AtlasSnapshot =
  | { status: 'loading' }
  | { status: 'unavailable'; error: string }
  | { status: 'ready'; projection: AtlasProjection }

export type AtlasState = AtlasSnapshot & { retry: () => void }

export function useAtlas(enabled: boolean): AtlasState {
  const [nonce, setNonce] = useState(0)

  // Same purpose as useWorkspaceObjects' requestRef: a stale response from a
  // previous enable/disable toggle must not paint over a newer one.
  const requestRef = useRef(0)
  const retry = useCallback(() => {
    // Invalidate synchronously: a response already in flight must not land
    // between this write-triggered refresh and the next effect pass.
    requestRef.current += 1
    setNonce((n) => n + 1)
  }, [])
  const [state, setState] = useState<AtlasSnapshot>({ status: 'loading' })

  useEffect(() => {
    if (!enabled) return
    const ticket = ++requestRef.current

    void (async () => {
      // React's set-state-in-effect rule refuses a synchronous write inside
      // the effect body; the microtask defers it one tick, same as
      // useRoomNavigation.refreshRooms and useWorkspaceObjects.
      await Promise.resolve()
      if (requestRef.current !== ticket) return
      setState({ status: 'loading' })

      try {
        const projection = await api.getAtlas()
        if (requestRef.current !== ticket) return
        setState({ status: 'ready', projection })
      } catch (error: unknown) {
        if (requestRef.current !== ticket) return
        setState({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read the atlas',
        })
      }
    })()
  }, [enabled, nonce, retry])

  return { ...state, retry } as AtlasState
}
