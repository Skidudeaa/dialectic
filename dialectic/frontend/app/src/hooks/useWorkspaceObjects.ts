import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.ts'
import type { WorkspaceObject } from '../types/workspace.ts'

/**
 * The room's workspace objects, in the three states a surface must be able to
 * tell apart.
 *
 * ARCHITECTURE: one fetch of the whole projection per room, filtered per scene
 * in the component. The server builds every kind in a single pass anyway (its
 * own `kind` query parameter filters AFTER the build), so asking four times —
 * once per scene — would be four full projections to render one room.
 *
 * WHY three states and not `objects: []` plus an error flag: design v2 §7.5
 * forbids rendering an empty automated run as evidence that nothing happened.
 * A hook that returns an empty array for BOTH "this room holds nothing" and
 * "the projection failed" makes that rule unenforceable downstream — the
 * surface cannot tell an honest silence from a broken one, and it will pick the
 * reassuring reading every time. The distinction has to exist here, in the
 * type, or it does not exist at all.
 *
 * WHY `enabled`: the projection sits behind `get_current_user`, so a guest
 * identity (no JWT — see AuthScreen) gets 401 on every call. Firing a request
 * we know will fail would paint "unavailable" across every scene and read as
 * an outage rather than as the guest boundary it is.
 */
export type WorkspaceObjectsState =
  | { status: 'loading' }
  | { status: 'unavailable'; error: string; retry: () => void }
  | { status: 'ready'; objects: WorkspaceObject[]; generatedAt: string; retry: () => void }

export function useWorkspaceObjects(
  roomId: string | null,
  enabled: boolean,
): WorkspaceObjectsState {
  const [state, setState] = useState<WorkspaceObjectsState>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)
  const retry = useCallback(() => setNonce((n) => n + 1), [])

  // Identifies the request this component still cares about. A room switch
  // while a fetch is in flight must not paint the previous room's objects into
  // the new one — the response arrives with no indication it is stale.
  const requestRef = useRef(0)

  useEffect(() => {
    if (!roomId || !enabled) return
    const ticket = ++requestRef.current

    void (async () => {
      // WHY the microtask: React's set-state-in-effect rule (rightly) refuses
      // state writes in an effect's synchronous frame, because they cascade a
      // second render. Same idiom as useRoomNavigation.refreshRooms, which
      // solved this exact problem first.
      await Promise.resolve()
      if (requestRef.current !== ticket) return
      setState({ status: 'loading' })

      try {
        const projection = await api.getWorkspaceObjects(roomId)
        if (requestRef.current !== ticket) return
        setState({
          status: 'ready',
          objects: projection.objects,
          generatedAt: projection.generated_at,
          retry,
        })
      } catch (error: unknown) {
        if (requestRef.current !== ticket) return
        setState({
          status: 'unavailable',
          error: error instanceof Error ? error.message : 'Could not read this room',
          retry,
        })
      }
    })()
  }, [roomId, enabled, nonce, retry])

  return state
}
