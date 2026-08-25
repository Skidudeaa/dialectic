import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.ts'
import type { GeoProjection } from '../types/geo.ts'

/**
 * A room's live geography (World Lens), in the three states a surface must
 * tell apart — useAtlas.ts's idiom verbatim (request-ticket ref, microtask
 * before the first setState). Read by the Bench's "World ↗" affordance,
 * which appears only when the room owns at least one scope.
 */
export type GeoScopesState =
  | { status: 'loading' }
  | { status: 'unavailable'; error: string; retry: () => void }
  | { status: 'ready'; projection: GeoProjection; retry: () => void }

export function useGeoScopes(roomId: string | null): GeoScopesState {
  const [state, setState] = useState<GeoScopesState>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)
  const retry = useCallback(() => setNonce((n) => n + 1), [])
  const requestRef = useRef(0)

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
        setState({ status: 'ready', projection, retry })
      } catch (error: unknown) {
        if (requestRef.current !== ticket) return
        setState({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read the room geography',
          retry,
        })
      }
    })()
  }, [roomId, nonce, retry])

  return state
}
