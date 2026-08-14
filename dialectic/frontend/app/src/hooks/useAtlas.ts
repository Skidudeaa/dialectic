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
export type AtlasState =
  | { status: 'loading' }
  | { status: 'unavailable'; error: string; retry: () => void }
  | { status: 'ready'; projection: AtlasProjection; retry: () => void }

export function useAtlas(enabled: boolean): AtlasState {
  const [state, setState] = useState<AtlasState>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)
  const retry = useCallback(() => setNonce((n) => n + 1), [])

  // Same purpose as useWorkspaceObjects' requestRef: a stale response from a
  // previous enable/disable toggle must not paint over a newer one.
  const requestRef = useRef(0)

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
        setState({ status: 'ready', projection, retry })
      } catch (error: unknown) {
        if (requestRef.current !== ticket) return
        setState({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read the atlas',
          retry,
        })
      }
    })()
  }, [enabled, nonce, retry])

  return state
}
