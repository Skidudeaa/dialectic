import type { ReactNode } from 'react'
import type { WorkspaceObject } from '../../../types/workspace.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'
import { SceneLoading, SceneUnavailable } from '../SceneEmpty'
import { WorkspaceObjectList } from '../WorkspaceObjectList'

/**
 * The Bench — the construction surface for what this room is building (§7.2).
 *
 * IT RECOMPOSES, IT DOES NOT REBUILD. `TradingPanel` is 715 lines carrying the
 * whole thesis lifecycle: create, Claude-drafted cascade, human review, accept,
 * immediate first cycle, Builder hand-off, retire, successor. That is moved
 * here whole. §7.2 says the Bench "should recompose existing components rather
 * than rebuilding functional workflows in parallel", and a second create path
 * would be the fastest way to break a lifecycle that works.
 *
 * WHY THERE IS NO EMPTY STATE OF OUR OWN: the trading panel's empty state IS
 * the create-thesis form. Wrapping it in a "nothing here yet" would hide the
 * one thing an empty Bench is for — the same mistake as when the panel was
 * shown only once a snapshot existed, which made the create flow unreachable in
 * exactly the rooms that needed it.
 *
 * Commitments sit alongside the thesis rather than in a Judgment scene of their
 * own: production holds zero of them, and a scene that renders nothing in every
 * room is dead UI the program forbids. When they have a population, they earn
 * their own place.
 */
export function BenchScene({
  state,
  onOpen,
  tradingPanel,
}: {
  state: WorkspaceObjectsState
  onOpen?: (object: WorkspaceObject) => void
  /** The existing TradingPanel — the thesis lifecycle, moved not rewritten. */
  tradingPanel: ReactNode
}) {
  if (state.status === 'loading') return <SceneLoading kicker="Bench" />
  if (state.status === 'unavailable') {
    // The panel still renders: its own state comes from the room's trading
    // config, not from this projection, so a failed projection must not take
    // the thesis surface down with it.
    return (
      <div className="scene-body">
        <SceneUnavailable
          kicker="Bench"
          what="the bench"
          error={state.error}
          onRetry={state.retry}
        />
        <div className="scene-panel">{tradingPanel}</div>
      </div>
    )
  }

  const commitments = state.objects.filter((o) => o.kind === 'commitment')

  return (
    <div className="scene-body">
      <div className="scene-panel">{tradingPanel}</div>
      {commitments.length > 0 && (
        <WorkspaceObjectList
          objects={commitments}
          onOpen={onOpen}
          label="Commitments and predictions"
        />
      )}
    </div>
  )
}
