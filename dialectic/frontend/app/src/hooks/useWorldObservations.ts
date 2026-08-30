import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.ts'
import type { WorldObservationsProjection } from '../types/geo.ts'

/** How often the recorded layer refetches on its own, while a room owning it
 *  stays mounted — a contact loitering in a bound scope should not need a
 *  manual reload to be seen. Matches the plan's world_watch cadence order of
 *  magnitude without coupling to it. */
const REFETCH_MS = 300_000

/**
 * A room's durable world observations — the "recorded" layer beside World's
 * live signals, and the counts WorldStrip reads. Same three-state shape and
 * request-ticket idiom as useGeoScopes.ts (a microtask before the first
 * setState, a ticket that discards a stale response), plus a self-driven
 * poll: unlike geography, observations change on their own clock even while
 * nobody touches this room.
 */
type WorldObservationsSnapshot =
  | { status: 'loading' }
  | { status: 'unavailable'; error: string }
  | { status: 'ready'; projection: WorldObservationsProjection }

export type WorldObservationsState = WorldObservationsSnapshot & { retry: () => void }

export function useWorldObservations(roomId: string | null, hours = 24): WorldObservationsState {
  const [nonce, setNonce] = useState(0)
  const requestRef = useRef(0)
  const retry = useCallback(() => {
    // Invalidate synchronously: a response already in flight must not land
    // between this write-triggered refresh and the next effect pass.
    requestRef.current += 1
    setNonce((n) => n + 1)
  }, [])
  const [state, setState] = useState<WorldObservationsSnapshot>({ status: 'loading' })

  useEffect(() => {
    if (!roomId) return
    const ticket = ++requestRef.current
    void (async () => {
      await Promise.resolve()
      if (requestRef.current !== ticket) return
      setState({ status: 'loading' })
      try {
        const projection = await api.getWorldObservations(roomId, hours)
        if (requestRef.current !== ticket) return
        setState({ status: 'ready', projection })
      } catch (error: unknown) {
        if (requestRef.current !== ticket) return
        setState({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read this room’s world observations',
        })
      }
    })()
  }, [roomId, hours, nonce])

  // The clock: a plain interval calling the same invalidate-and-refetch path
  // as a manual retry, so a stale in-flight request from the previous tick
  // can never land over a newer one.
  useEffect(() => {
    if (!roomId) return
    const id = window.setInterval(retry, REFETCH_MS)
    return () => window.clearInterval(id)
  }, [roomId, retry])

  return { ...state, retry } as WorldObservationsState
}
