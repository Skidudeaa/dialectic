import { useAppStore } from '../stores/appStore'
import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { ChartProjection, DispatchMetadata, ScoutRunMetadata } from '../organs/longway/types'

export function useLongwayChart(roomId: string | null) {
  // message_created and llm_done both hydrate this store; metadata patches also
  // update it. Refresh for a dispatch or Scout receipt, not ordinary conversation.
  const dispatch = useAppStore(s => s.messages.filter(m =>
    (m.metadata as { longway_dispatch?: DispatchMetadata; longway_scout_run?: ScoutRunMetadata } | null)?.longway_dispatch ||
    (m.metadata as { longway_scout_run?: ScoutRunMetadata } | null)?.longway_scout_run,
  ).map(m => m.id).join(','))
  return useLongwayResource<ChartProjection>(roomId ? longwayPath(roomId, 'chart') : null, dispatch, 300_000)
}
