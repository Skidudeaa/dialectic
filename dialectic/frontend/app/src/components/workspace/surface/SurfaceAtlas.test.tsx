import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SurfaceAtlas } from './SurfaceAtlas'
import { geometryBBox, geometryPath, makeProjector, unionBBox } from './geoProject'
import type { GeoScope, WorldObservation, WorldObservationCount } from '../../../types/geo.ts'

// A small ring around 56E, 26N — the Persian Gulf, roughly.
const GULF_RING: [number, number][] = [
  [55.5, 25.5],
  [56.5, 25.5],
  [56.5, 26.5],
  [55.5, 26.5],
  [55.5, 25.5],
]

function makeScope(overrides: Partial<GeoScope> = {}): GeoScope {
  return {
    id: 'scope-1',
    room_id: 'room-1',
    subject: { entity: 'rooms', id: 'room-1' },
    kind: 'region',
    geometry: { type: 'Polygon', coordinates: [GULF_RING] },
    label: 'Persian Gulf',
    authority: 'human_confirmed',
    provenance: { provider: 'hand-authored', acquisition: 'manual', credit: 'Amo' },
    source_state: 'ok',
    revision_action: 'place',
    review_state: 'accepted',
    freshness: { state: 'current', retrieved_at: '2026-09-01T00:00:00Z' },
    centroid: [56, 26],
    retrieved_at: '2026-09-01T00:00:00Z',
    created_at: '2026-09-01T00:00:00Z',
    ...overrides,
  }
}

function makeObservation(overrides: Partial<WorldObservation> = {}): WorldObservation {
  return {
    id: 'obs-1',
    scope_id: 'scope-1',
    scope_label: 'Persian Gulf',
    provider: 'adsb',
    signal_id: 'sig-1',
    layer: 'aircraft',
    kind: 'point',
    label: 'Contact 1',
    geometry: { type: 'Point', coordinates: [56, 26] },
    provenance: { provider: 'adsb.lol', acquisition: 'poll', credit: 'ODbL' },
    details: {},
    retrieved_at: '2026-09-02T00:00:00Z',
    first_seen_at: '2026-09-02T00:00:00Z',
    last_seen_at: '2026-09-02T00:00:00Z',
    seen_count: 1,
    ...overrides,
  }
}

function makeCount(overrides: Partial<WorldObservationCount> = {}): WorldObservationCount {
  return {
    scope_id: 'scope-1',
    scope_label: 'Persian Gulf',
    layer: 'aircraft',
    count: 1,
    newest_at: '2026-09-02T00:00:00Z',
    ...overrides,
  }
}

describe('geoProject', () => {
  it('geometryBBox walks a polygon ring to its bounding box', () => {
    const bbox = geometryBBox({ type: 'Polygon', coordinates: [[[10, 20], [14, 20], [14, 25], [10, 25], [10, 20]]] })
    expect(bbox).toEqual([10, 20, 14, 25])
  })

  it('geometryBBox ignores geometry types it does not walk', () => {
    expect(geometryBBox({ type: 'GeometryCollection', coordinates: [] })).toBeNull()
    expect(geometryBBox(null)).toBeNull()
  })

  it('unionBBox covers every box and drops nulls', () => {
    const a: [number, number, number, number] = [0, 0, 5, 5]
    const b: [number, number, number, number] = [3, -2, 8, 4]
    expect(unionBBox([a, b, null, undefined])).toEqual([0, -2, 8, 5])
    expect(unionBBox([])).toBeNull()
  })

  it('makeProjector fits bbox corners inside the padded canvas and keeps west-to-east order', () => {
    const bbox: [number, number, number, number] = [10, 20, 14, 25]
    const project = makeProjector(bbox, 720, 300, 28)
    const [xWest] = project(10, 22.5)
    const [xEast] = project(14, 22.5)
    expect(xWest).toBeLessThan(xEast)
    for (const [lon, lat] of [[10, 20], [14, 20], [14, 25], [10, 25]] as const) {
      const [x, y] = project(lon, lat)
      expect(x).toBeGreaterThanOrEqual(28 - 0.01)
      expect(x).toBeLessThanOrEqual(720 - 28 + 0.01)
      expect(y).toBeGreaterThanOrEqual(28 - 0.01)
      expect(y).toBeLessThanOrEqual(300 - 28 + 0.01)
    }
  })

  it('geometryPath begins with M and ends with Z for a polygon, and is empty for a point', () => {
    const project = makeProjector([10, 20, 14, 25], 720, 300, 28)
    const d = geometryPath({ type: 'Polygon', coordinates: [[[10, 20], [14, 20], [14, 25], [10, 20]]] }, project)
    expect(d.startsWith('M')).toBe(true)
    expect(d.trimEnd().endsWith('Z')).toBe(true)
    expect(geometryPath({ type: 'Point', coordinates: [10, 20] }, project)).toBe('')
  })
})

describe('SurfaceAtlas', () => {
  it('shows the empty state and no map when the room owns no geography', () => {
    render(
      <SurfaceAtlas
        scopes={[]}
        observations={[]}
        counts={[]}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.getByText('No geography placed for this room.')).toBeInTheDocument()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('computes the header from counts, not from the raw observation list', () => {
    render(
      <SurfaceAtlas
        scopes={[makeScope(), makeScope({ id: 'scope-2', label: 'Strait of Hormuz' })]}
        observations={[]}
        counts={[
          makeCount({ layer: 'fires', count: 5, novel: 2 }),
          makeCount({ layer: 'aircraft', count: 8 }),
        ]}
        selectedId={null}
        onSelect={vi.fn()}
        hours={48}
      />,
    )
    expect(screen.getByText('Atlas · 2 confirmed areas · 5 fire cells in 48h, 2 new · 8 aircraft')).toBeInTheDocument()
  })

  it('says "no fire cells" and omits aircraft when neither count exists', () => {
    render(
      <SurfaceAtlas
        scopes={[makeScope()]}
        observations={[]}
        counts={[]}
        selectedId={null}
        onSelect={vi.fn()}
        hours={24}
      />,
    )
    expect(screen.getByText('Atlas · 1 confirmed area · no fire cells in 24h')).toBeInTheDocument()
    expect(screen.getByText('no contacts recorded in 24h')).toBeInTheDocument()
  })

  it('renders a novel fire with a NEW aria-label and a plain recurring fire without one', () => {
    const novelFire = makeObservation({
      id: 'fire-new', layer: 'fires', label: 'Cell A',
      details: { frp: 25, confidence: 'nominal', novel: true },
    })
    const recurringFire = makeObservation({
      id: 'fire-old', layer: 'fires', label: 'Cell B',
      details: { frp: 6, confidence: 'low', novel: false, baseline_days: 12 },
    })
    render(
      <SurfaceAtlas
        scopes={[makeScope()]}
        observations={[novelFire, recurringFire]}
        counts={[]}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /NEW vs 30-day baseline/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /recurring 12d/ })).toBeInTheDocument()
  })

  it('calls onSelect with the observation on click, and with null on a second click of the same marker', () => {
    const obs = makeObservation()
    const onSelect = vi.fn()
    const { rerender } = render(
      <SurfaceAtlas
        scopes={[makeScope()]}
        observations={[obs]}
        counts={[]}
        selectedId={null}
        onSelect={onSelect}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Contact 1/ }))
    expect(onSelect).toHaveBeenCalledWith(obs)

    rerender(
      <SurfaceAtlas
        scopes={[makeScope()]}
        observations={[obs]}
        counts={[]}
        selectedId={obs.id}
        onSelect={onSelect}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Contact 1/ }))
    expect(onSelect).toHaveBeenLastCalledWith(null)
  })

  it('skips a non-Point observation rather than drawing it', () => {
    const lineObs = makeObservation({ id: 'not-a-point', geometry: { type: 'LineString', coordinates: [[55.5, 25.5], [56.5, 26.5]] } })
    render(
      <SurfaceAtlas
        scopes={[makeScope()]}
        observations={[lineObs]}
        counts={[]}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button', { name: /Contact 1/ })).toBeNull()
  })

  it('renders a World ↗ button only when onOpenWorld is given, and calls it on click', () => {
    const onOpenWorld = vi.fn()
    render(
      <SurfaceAtlas
        scopes={[makeScope()]}
        observations={[]}
        counts={[]}
        selectedId={null}
        onSelect={vi.fn()}
        onOpenWorld={onOpenWorld}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'World ↗' }))
    expect(onOpenWorld).toHaveBeenCalledTimes(1)
  })

  it('renders no World ↗ button when onOpenWorld is omitted', () => {
    render(
      <SurfaceAtlas
        scopes={[makeScope()]}
        observations={[]}
        counts={[]}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button', { name: 'World ↗' })).toBeNull()
  })
})

describe('SurfaceAtlas contacts status', () => {
  it('never reads a loading or failed contacts read as "no fire cells"', () => {
    const scope = {
      id: 'geo_scope:s1', room_id: 'r', subject: { entity: 'rooms', id: 'r', field: null }, kind: 'polygon',
      geometry: { type: 'Polygon', coordinates: [[[55, 25], [57, 25], [57, 27], [55, 27], [55, 25]]] },
      label: 'Persian Gulf', authority: 'human_confirmed', provenance: {}, source_state: 'ok',
      revision_action: 'create', review_state: 'confirmed', freshness: {}, centroid: [56, 26] as [number, number],
      retrieved_at: '', created_at: '',
    } as unknown as import('../../../types/geo.ts').GeoScope
    const { rerender } = render(
      <SurfaceAtlas scopes={[scope]} observations={[]} counts={[]} selectedId={null} onSelect={() => {}} contactsStatus="loading" />,
    )
    expect(screen.getByText(/reading contacts/)).toBeInTheDocument()
    expect(screen.queryByText(/no fire cells/)).toBeNull()
    rerender(
      <SurfaceAtlas scopes={[scope]} observations={[]} counts={[]} selectedId={null} onSelect={() => {}} contactsStatus="unavailable" />,
    )
    expect(screen.getByText(/contacts unavailable/)).toBeInTheDocument()
    rerender(
      <SurfaceAtlas scopes={[scope]} observations={[]} counts={[]} selectedId={null} onSelect={() => {}} contactsStatus="ready" />,
    )
    expect(screen.getByText(/no fire cells in 48h/)).toBeInTheDocument()
  })
})
