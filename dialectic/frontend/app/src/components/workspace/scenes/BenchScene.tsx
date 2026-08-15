import type { ReactNode } from 'react'
import type { WorkspaceObject } from '../../../types/workspace.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'
import { useTradingDesk } from '../../../hooks/useTradingDesk.ts'
import { useAppStore } from '../../../stores/appStore.ts'
import { SceneLoading, SceneUnavailable } from '../SceneEmpty'
import { WorkspaceObjectList } from '../WorkspaceObjectList'
import { ThesisDag } from '../../trading/ThesisDag'
import { MarketStrip } from '../../trading/MarketStrip'
import { PolymarketStrip } from '../../trading/PolymarketStrip'
import { OpenTradesTable } from '../../trading/OpenTradesTable'
import { HourlyDiff } from '../../trading/HourlyDiff'
import { MorningBriefCard } from '../../trading/MorningBriefCard'
import { ThesisNewsList } from '../../trading/ThesisNewsList'
import { AlertEventsList } from '../../trading/AlertEventsList'
import { ScenarioWhatIf } from '../../trading/ScenarioWhatIf'

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
 * THE COCKPIT (2026-08-14): around the lifecycle panel, a bound room now
 * renders everything the LLM's tool loop could always see and the humans
 * could not — the causal DAG with live node states, quotes, Polymarket,
 * alert transitions, the hourly diff, open trades, scenario what-ifs, the
 * morning brief and thesis news. All read-only feeds off useTradingDesk;
 * the one POST (scenario evaluate) is a pure what-if. An unbound room shows
 * none of it: the hook's 409 probe flips `bound` false and the panel's
 * create-thesis surface carries the scene alone, exactly as before.
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

/** Same freshness rule as TradingPanel's StalenessIndicator: under an hour
 * is fresh; beyond that the DAG's live coloring must say it is old. */
function snapshotIsStale(timestamp?: string): boolean {
  if (!timestamp) return true
  const ageMs = Date.now() - new Date(timestamp).getTime()
  return !Number.isFinite(ageMs) || ageMs >= 60 * 60 * 1000
}

export function BenchScene({
  state,
  onOpen,
  tradingPanel,
  roomId,
}: {
  state: WorkspaceObjectsState
  onOpen?: (object: WorkspaceObject) => void
  /** The existing TradingPanel — the thesis lifecycle, moved not rewritten. */
  tradingPanel: ReactNode
  roomId: string | null
}) {
  const desk = useTradingDesk(roomId)
  const tradingConfig = useAppStore((s) => s.tradingConfig)

  if (state.status === 'loading') return <SceneLoading kicker="Bench" />

  const cockpit = desk.bound && roomId ? (
    <>
      {desk.structure.status === 'ready' && desk.structure.data ? (
        <ThesisDag
          structure={desk.structure.data}
          nodeStates={tradingConfig?.nodeStates}
          stale={snapshotIsStale(tradingConfig?.timestamp)}
        />
      ) : desk.structure.status === 'unavailable' ? (
        <section className="cockpit-module">
          <div className="cockpit-header"><span className="cockpit-title">Causal graph</span></div>
          <div className="cockpit-error-line">Unavailable: {desk.structure.error}</div>
        </section>
      ) : null}
      <MarketStrip slice={desk.quotes} onRefresh={desk.refresh} />
      <PolymarketStrip slice={desk.polymarket} />
      <AlertEventsList events={tradingConfig?.alertEvents} />
      <HourlyDiff slice={desk.diff} />
      <OpenTradesTable slice={desk.trades} />
      {desk.structure.status === 'ready' && desk.structure.data && roomId ? (
        <ScenarioWhatIf
          roomId={roomId}
          scenarios={desk.structure.data.scenarios ?? []}
          snapshotImpacts={tradingConfig?.scenarioImpacts}
        />
      ) : null}
      <MorningBriefCard slice={desk.brief} />
      <ThesisNewsList slice={desk.news} />
    </>
  ) : null

  if (state.status === 'unavailable') {
    // The panel and cockpit still render: their state comes from the room's
    // trading config and the relay, not from this projection, so a failed
    // projection must not take the thesis surface down with it.
    return (
      <div className="scene-body">
        <SceneUnavailable
          kicker="Bench"
          what="the bench"
          error={state.error}
          onRetry={state.retry}
        />
        <div className="scene-panel">{tradingPanel}</div>
        {cockpit}
      </div>
    )
  }

  const commitments = state.objects.filter((o) => o.kind === 'commitment')

  return (
    <div className="scene-body">
      <div className="scene-panel">{tradingPanel}</div>
      {cockpit}
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
