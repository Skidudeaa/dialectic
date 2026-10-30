import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fixtureLeg as leg, fixtureRide as ride } from './fixtures'
import { RideCard } from './RideCard'
import { RidingNow } from './RidingNow'
import { useRide } from './useRide'
import RideBench from './RideBench'
vi.mock('./RideMap', () => ({ default: ({ position }: { position: number[] | null }) => <div data-testid="ride-map">{JSON.stringify(position)}</div> }))
const at = Date.parse('2026-10-23T09:53:00-07:00')
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })
it('renders the named current view, upcoming sight, stop table and darkness in the actual card', () => {
  const view = render(<RideCard data={ride} leg={leg} km={635} now={at} replay offline={false} lastSuccess={null} />)
  expect(screen.getByText("Don't miss")).toBeInTheDocument()
  expect(screen.getByText('Nothing')).toBeInTheDocument()
  expect(screen.getByText(/Upper Klamath Lake alongside/)).toBeInTheDocument()
  expect(screen.getByText('Mount Scott and Mount Thielsen')).toBeInTheDocument()
  expect(screen.getByRole('table')).toHaveTextContent('Chemult')
  view.rerender(<RideCard data={ride} leg={leg} km={635} now={Date.parse('2026-10-23T03:00:00-07:00')} replay offline={false} lastSuccess={null} />)
  expect(screen.getByText('Too dark to see the views on either side.')).toBeInTheDocument()
  expect(screen.queryByText(/Upper Klamath Lake alongside/)).not.toBeInTheDocument()
})
it('scrubs an arrived ride through the connected API and moves the map and card together', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/ride/leg') ? leg : ride))))
  render(<RideBench roomId="room" record={<p>Room record</p>} />)
  const slider = await screen.findByRole('slider', { name: 'Replay time' })
  await screen.findByTestId('ride-map')
  fireEvent.change(slider, { target: { value: at } })
  expect(screen.getByText('(model, km 646)')).toBeInTheDocument()
  expect(screen.getByTestId('ride-map')).not.toHaveTextContent('null')
  expect(screen.getByText('Room record')).toBeInTheDocument()
  const exact = screen.getByRole('textbox', { name: 'Exact time (with timezone)' })
  fireEvent.change(exact, { target: { value: '2026-10-23T09:53:00-07:00' } }); fireEvent.blur(exact)
  expect(slider).toHaveValue(String(at))
})
it('hides an empty House strip and navigates the member’s listed ride', async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ rides: [] }))); vi.stubGlobal('fetch', fetcher)
  const navigate = vi.fn(), view = render(<RidingNow roomId="house" onNavigate={navigate} />)
  await waitFor(() => expect(fetcher).toHaveBeenCalled())
  expect(screen.queryByRole('heading', { name: 'Riding now' })).not.toBeInTheDocument()
  view.unmount()
  fetcher.mockImplementation(async () => new Response(JSON.stringify({ rides: [{ room_id: 'coast', room_name: 'Aboard', trip: 'coast', ride: ride.ride, fix: null, next_stop: { code: 'CMO', name: 'Chemult', est: '2026-10-23T17:41:00Z' }, late_min: 102 }] })))
  render(<RidingNow roomId="house" onNavigate={navigate} />)
  fireEvent.click(await screen.findByRole('button', { name: /Coast Starlight 14/ }))
  expect(navigate).toHaveBeenCalledWith('coast')
})

describe('live polling and offline retention', () => {
  it('polls every 60 seconds, loads the leg once, and never treats a cached response as fresh', async () => {
    vi.useFakeTimers(); vi.setSystemTime(at)
    const live = { ...ride, ride: { ...ride.ride, state: 'riding' }, fetched_at: new Date(at).toISOString(), km: 635 }
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/ride/leg') ? leg : live)))
    vi.stubGlobal('fetch', fetcher)
    function Probe() { const state = useRide('room'); return <p>{state.data?.ride.id} {state.offline ? 'offline' : 'online'} {state.leg?.id}</p> }
    render(<Probe />)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(screen.getByText(/14-22 online amtrak/)).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
    expect(fetcher.mock.calls.filter(c => !c[0].includes('/leg'))).toHaveLength(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(120000) })
    expect(screen.getByText(/14-22 offline/)).toBeInTheDocument()
    expect(fetcher.mock.calls.filter(c => c[0].includes('/leg'))).toHaveLength(1)
    fetcher.mockRejectedValue(new Error('no signal'))
    await act(async () => { await vi.advanceTimersByTimeAsync(20 * 60000) })
    expect(screen.getByText(/14-22 offline amtrak/)).toBeInTheDocument()
  })
})
