import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.ts'
import type { FieldMark } from '../types/workspace.ts'

/**
 * The room's Field marks, in the three states a surface must be able to
 * tell apart. Copied wholesale from useWorkspaceObjects.ts -- same fetch
 * idiom, same reasons, so a new hook does not quietly diverge from the one
 * every other scene already trusts.
 *
 * ARCHITECTURE: one fetch of the whole projection per room. The server
 * builds every mark in a single pass (field_marks.FieldMarkService.build),
 * so there is nothing to filter server-side the way getWorkspaceObjects
 * filters by kind -- the Field's sectioning happens client-side, in
 * FieldScene, over one projection.
 *
 * WHY three states and not `marks: []` plus an error flag: same reasoning as
 * useWorkspaceObjects (design v2 §7.5) -- an empty array must never mean
 * both "this room has no marks yet" and "the projection failed". A room with
 * zero marks and a teaching empty state is the Field's normal early life
 * (§6.6: the inference job is the population plan, not wishful metadata);
 * collapsing that into the same shape as a failed fetch would make the
 * empty-state-that-teaches rule impossible to honour downstream.
 *
 * WHY `enabled`: same guest-boundary reasoning as useWorkspaceObjects -- the
 * projection sits behind get_current_user, so firing it for a guest identity
 * (no JWT) would paint "unavailable" across the Field and read as an outage
 * rather than as the boundary it is.
 */
export type FieldMarksState =
  | { status: 'loading' }
  | { status: 'unavailable'; error: string; retry: () => void }
  | { status: 'ready'; marks: FieldMark[]; generatedAt: string; refresh: () => void }

export function useFieldMarks(
  roomId: string | null,
  enabled: boolean,
): FieldMarksState {
  const [state, setState] = useState<FieldMarksState>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)
  // One bump function serves both names a caller reaches for: `retry` after
  // a failed fetch, `refresh` after a review POST lands. Same effect either
  // way -- re-run the request this hook already owns.
  const bump = useCallback(() => setNonce((n) => n + 1), [])

  // Identifies the request this component still cares about. A room switch
  // while a fetch is in flight must not paint the previous room's marks into
  // the new one -- the response arrives with no indication it is stale.
  const requestRef = useRef(0)

  useEffect(() => {
    if (!roomId || !enabled) return
    const ticket = ++requestRef.current

    void (async () => {
      // WHY the microtask: React's set-state-in-effect rule (rightly)
      // refuses state writes in an effect's synchronous frame, because they
      // cascade a second render. Same idiom as useWorkspaceObjects and
      // useRoomNavigation.refreshRooms, which solved this exact problem
      // first.
      await Promise.resolve()
      if (requestRef.current !== ticket) return
      setState({ status: 'loading' })

      try {
        const projection = await api.getFieldMarks(roomId)
        if (requestRef.current !== ticket) return
        setState({
          status: 'ready',
          marks: projection.marks,
          generatedAt: projection.generated_at,
          refresh: bump,
        })
      } catch (error: unknown) {
        if (requestRef.current !== ticket) return
        setState({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read the Field',
          retry: bump,
        })
      }
    })()
  }, [roomId, enabled, nonce, bump])

  return state
}
