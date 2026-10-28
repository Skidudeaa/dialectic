import type { ChartProjection, Journey, Vehicle } from '../../types'
import fixture from './chart.json'

// Captured stdout is untouched. These are only the server-owned additions from
// LONGWAY_ORGAN.md §5. No live position is claimed by this offline fixture.
export const projection: ChartProjection = {
  ...fixture,
  journeys: fixture.journeys as Journey[],
  sources: fixture.sources as ChartProjection['sources'],
  vehicles: fixture.vehicles.map(v => ({ ...v, fix: null, heard: false })) as Vehicle[],
  fetched_at: '2026-10-28T12:00:00Z',
  room: { id: 'fixture-house', linked_journey: null, is_home: true }, rooms: [],
  fixes_state: { written: null, stale: false, why: null },
}
