import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import raw from '../__fixtures__/chart.json'
import type { ChartProjection } from '../types'
import { LongwayBench } from '../LongwayBench'
const state = vi.hoisted(() => ({ data: null as ChartProjection | null, error: null as string | null }))
vi.mock('../../../hooks/useLongwayChart', () => ({ useLongwayChart: () => ({ data: state.data, error: state.error, refresh: vi.fn() }) }))
vi.mock('../chartSlot', () => ({ default: () => <p>Globe scene</p> }))
vi.mock('./RideBench', () => ({ default: () => <p>Ride scene</p> }))
afterEach(cleanup)
function choose(kind: 'trip' | 'candidate', rides: number, bound = true) {
  state.error = null
  const data = raw as unknown as ChartProjection
  state.data = { ...data, room: { id: 'room', is_home: false, linked_journey: bound ? data.journeys[0].slug : null }, rooms: [], fixes_state: { stale: false, why: null, written: null }, journeys: [{ ...data.journeys[0], kind, rides }], vehicles: [] }
}
it('chooses the ride only for the bound trip with rides', async () => {
  choose('trip', 1); render(<LongwayBench roomId="room" />)
  expect(await screen.findByText('Ride scene')).toBeInTheDocument()
})
it.each([['candidate', 1, true], ['trip', 0, true], ['trip', 1, false]] as const)('keeps the globe for %s with %i rides, bound=%s', (kind, rides, bound) => {
  choose(kind, rides, bound); render(<LongwayBench roomId="room" />)
  expect(screen.getByText('Globe scene')).toBeInTheDocument()
})

it('keeps the ride mounted when the parent chart refresh fails offline', async () => {
  choose('trip', 1); const view = render(<LongwayBench roomId="room" />)
  const scene = await screen.findByText('Ride scene')
  state.error = 'No signal'
  view.rerender(<LongwayBench roomId="room" />)
  expect(screen.getByText('Ride scene')).toBe(scene)
  expect(screen.queryByText('Retry chart')).not.toBeInTheDocument()
})
