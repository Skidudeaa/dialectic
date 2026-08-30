import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorldStrip } from './WorldStrip.tsx'
import { api } from '../../../lib/api.ts'
import type { GeoProjection, GeoScope, WorldObservationsProjection } from '../../../types/geo.ts'

vi.mock('../../../lib/api.ts', () => ({
  api: { getGeo: vi.fn(), getWorldObservations: vi.fn() },
}))

function geo(scopes: GeoScope[] = []): GeoProjection {
  return { generated_at: 'now', room_id: 'room-h', scopes }
}

function scope(overrides: Partial<GeoScope> = {}): GeoScope {
  return {
    id: 'geo_scope:hormuz',
    room_id: 'room-h',
    subject: { entity: 'rooms', id: 'room-h' },
    kind: 'polygon',
    geometry: { type: 'Polygon', coordinates: [] },
    label: 'Strait of Hormuz',
    authority: 'human_confirmed',
    provenance: { provider: 'human', acquisition: 'human', credit: 'fixture' },
    source_state: 'ok',
    revision_action: 'place',
    review_state: 'accepted',
    freshness: { state: 'current', retrieved_at: 'now' },
    centroid: [56.3, 26.5],
    retrieved_at: 'now',
    created_at: 'now',
    ...overrides,
  }
}

function observations(counts: WorldObservationsProjection['counts'] = []): WorldObservationsProjection {
  return { observations: [], counts }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('WorldStrip', () => {
  it('offers the seed-it door, built from the current search params, when the room owns no geography', async () => {
    vi.mocked(api.getGeo).mockResolvedValue(geo([]))
    vi.mocked(api.getWorldObservations).mockResolvedValue(observations())
    window.history.replaceState(null, '', '/?room=room-h&scene=bench')

    render(<WorldStrip roomId="room-h" />)
    const link = await screen.findByRole('link', { name: /seed it/i })
    expect(link.getAttribute('href')).toBe('?room=room-h&scene=atlas')
  })

  it('counts contacts across scopes today and shows the newest age, plus the door', async () => {
    vi.mocked(api.getGeo).mockResolvedValue(geo([scope()]))
    vi.mocked(api.getWorldObservations).mockResolvedValue(observations([
      {
        scope_id: 's1', scope_label: 'Strait of Hormuz', layer: 'aircraft',
        count: 3, newest_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      },
      {
        scope_id: 's2', scope_label: 'Persian Gulf', layer: 'earthquakes',
        count: 1, newest_at: new Date(Date.now() - 60 * 60_000).toISOString(),
      },
    ]))

    render(<WorldStrip roomId="room-h" worldLink={<button type="button">World ↗</button>} />)
    const strip = await screen.findByTestId('world-strip')
    expect(strip.textContent).toMatch(/World · 4 contacts in 2 scopes today/)
    expect(strip.textContent).toMatch(/last \d+m ago/)
    expect(screen.getByRole('button', { name: 'World ↗' })).toBeInTheDocument()
  })

  it('counts NEW fires from the rows, never the recurring flare field', async () => {
    vi.mocked(api.getGeo).mockResolvedValue(geo([scope()]))
    const fire = (id: string, novel: boolean) => ({
      id, scope_id: 's1', scope_label: 'Persian Gulf', provider: 'firms',
      signal_id: `world_signal:firms:${id}`, layer: 'fires', kind: 'point' as const,
      label: 'Fire · 30 MW · high conf', geometry: { type: 'Point', coordinates: [50.6, 30.4] },
      provenance: { provider: 'firms', acquisition: 'adapter:firms', source_id: id, url: null, credit: 'NASA FIRMS' },
      details: { frp_mw: 30, novel }, retrieved_at: 'now', first_seen_at: 'now', last_seen_at: 'now', seen_count: 1,
    })
    vi.mocked(api.getWorldObservations).mockResolvedValue({
      observations: [fire('a', true), fire('b', false), fire('c', false)],
      counts: [{ scope_id: 's1', scope_label: 'Persian Gulf', layer: 'fires', count: 3, newest_at: new Date().toISOString() }],
    })

    render(<WorldStrip roomId="room-h" />)
    const strip = await screen.findByTestId('world-strip')
    expect(strip.textContent).toMatch(/3 contacts in 1 scope today/)
    expect(strip.textContent).toMatch(/· 1 new fire$/)
  })

  it('shows the count line with no age clause when this room has zero contacts yet', async () => {
    vi.mocked(api.getGeo).mockResolvedValue(geo([scope()]))
    vi.mocked(api.getWorldObservations).mockResolvedValue(observations([]))

    render(<WorldStrip roomId="room-h" />)
    const strip = await screen.findByTestId('world-strip')
    expect(strip.textContent).toMatch(/World · 0 contacts in 0 scopes today/)
    expect(strip.textContent).not.toMatch(/last/)
  })

  it('renders nothing while geography is still loading, and nothing on a failed read', async () => {
    vi.mocked(api.getGeo).mockReturnValue(new Promise(() => {}))
    vi.mocked(api.getWorldObservations).mockResolvedValue(observations())
    render(<WorldStrip roomId="room-h" />)
    expect(screen.queryByTestId('world-strip')).not.toBeInTheDocument()
  })

  it('stays silent (not the seed-it door) when the geography read itself fails', async () => {
    vi.mocked(api.getGeo).mockRejectedValue(new Error('nope'))
    vi.mocked(api.getWorldObservations).mockResolvedValue(observations())
    render(<WorldStrip roomId="room-h" />)
    await waitFor(() => expect(api.getGeo).toHaveBeenCalled())
    expect(screen.queryByTestId('world-strip')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /seed it/i })).not.toBeInTheDocument()
  })
})
