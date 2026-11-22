import { useLongwayChart } from './useLongwayChart'
import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { JourneyDetail } from '../organs/longway/types'

export function useLongwayJourney(roomId: string | null) {
  const chart = useLongwayChart(roomId)
  const slug = chart.data?.room.linked_journey
  const journey = useLongwayResource<JourneyDetail>(roomId && slug ? longwayPath(roomId, `journey/${encodeURIComponent(slug)}`) : null)
  const refresh = () => { chart.refresh(); journey.refresh() }
  const hasVoyage = chart.data?.journeys.some(item => item.slug === slug && item.voyage === true) ?? false
  const canEdit = chart.data?.room.can_edit === true
  return { ...journey, hasVoyage, canEdit, refresh, error: chart.error ?? journey.error, loading: chart.loading || journey.loading, unbound: Boolean(chart.data && !slug) }
}
