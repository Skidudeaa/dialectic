import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.ts'
import type { GeoProjection } from '../types/geo.ts'

/**
 * A room's live geography (World Lens), in the three states a surface must
 * tell apart — useAtlas.ts's idiom verbatim (request-ticket ref, microtask
 * before the first setState). Read by the Bench's "World ↗" affordance,
 * which appears only when the room owns at least one scope.
 */
type GeoScopesSnapshot =
  | { status: 'loading' }
  | { status: 'unavailable'; error: string }
  | { status: 'ready'; projection: GeoProjection }

export type GeoScopesState = GeoScopesSnapshot & { retry: () => void }

export function useGeoScopes(roomId: string | null): GeoScopesState {
  const [nonce, setNonce] = useState(0)
  const requestRef = useRef(0)
  const retry = useCallback(() => {
    // Invalidate synchronously: a response already in flight must not land
    // between this write-triggered refresh and the next effect pass.
    requestRef.current += 1
    setNonce((n) => n + 1)
  }, [])
  const [state, setState] = useState<GeoScopesSnapshot>({ status: 'loading' })

  useEffect(() => {
    if (!roomId) return
    const ticket = ++requestRef.current
    void (async () => {
      await Promise.resolve()
      if (requestRef.current !== ticket) return
      setState({ status: 'loading' })
      try {
        const projection = await api.getGeo(roomId)
        if (requestRef.current !== ticket) return
        setState({ status: 'ready', projection })
      } catch (error: unknown) {
        if (requestRef.current !== ticket) return
        setState({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read the room geography',
        })
      }
    })()
  }, [roomId, nonce, retry])

  return { ...state, retry } as GeoScopesState
}
