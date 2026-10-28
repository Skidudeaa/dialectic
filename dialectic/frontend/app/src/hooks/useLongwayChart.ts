import { useAppStore } from '../stores/appStore'
import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { ChartProjection, DispatchMetadata } from '../organs/longway/types'

export function useLongwayChart(roomId: string | null) {
  // message_created and llm_done both hydrate this store; metadata patches also
  // update it. Refresh only for a dispatch, not for ordinary conversation.
  const dispatch = useAppStore(s => s.messages.filter(m =>
    (m.metadata as { longway_dispatch?: DispatchMetadata } | null)?.longway_dispatch,
  ).map(m => m.id).join(','))
  return useLongwayResource<ChartProjection>(roomId ? longwayPath(roomId, 'chart') : null, dispatch, 300_000)
}
