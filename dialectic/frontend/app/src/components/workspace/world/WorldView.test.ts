import { describe, expect, it, vi } from 'vitest'
import type * as Cesium from 'cesium'
import type { GeoScope, WorldSignal } from '../../../types/geo.ts'
import { addSignal } from './worldSignals.ts'
import { addScope } from './worldScopeEntities.ts'

const contact: WorldSignal = {
  id: 'world_signal:ais:contact-1',
  provider: 'ais',
  source_id: 'contact-1',
  room_id: 'room-h',
  layer: 'vessels',
  kind: 'point',
  geometry: { type: 'Point', coordinates: [56.3, 26.5] },
  provenance: {
    provider: 'ais', acquisition: 'adapter:ais', source_id: 'contact-1',
    url: null, credit: 'AIS provider credit',
  },
  source_state: 'partial',
  freshness: 'current',
  coverage: 'receiver footprint',
  observed_at: '2026-08-25T17:58:00Z',
  retrieved_at: '2026-08-25T17:59:00Z',
  expires_at: '2026-08-25T18:10:00Z',
  label: 'Vessel contact 1',
  details: {},
}

const selectedScope: GeoScope = {
  id: 'geo_scope:selected',
  room_id: 'room-h',
  subject: { entity: 'rooms', id: 'room-h' },
  kind: 'point',
  geometry: { type: 'Point', coordinates: [56.3, 26.5] },
  label: 'Selected evidence',
  authority: 'human_confirmed',
  provenance: { provider: 'human', acquisition: 'human', credit: 'fixture' },
  source_state: 'ok',
  revision_action: 'place',
  review_state: 'accepted',
  freshness: { state: 'not_applicable', retrieved_at: '2026-08-25T17:59:00Z' },
  centroid: [56.3, 26.5],
  retrieved_at: '2026-08-25T17:59:00Z',
  created_at: '2026-08-25T17:59:00Z',
}

describe('WorldView signal layer', () => {
  it('adds a signal as its own distinct, non-scope globe entity', () => {
    const add = vi.fn()
    const viewer = { entities: { add } } as unknown as Cesium.Viewer

    addSignal(viewer, contact)

    expect(add).toHaveBeenCalledOnce()
    expect(add.mock.calls[0][0]).toMatchObject({
      id: contact.id,
      name: contact.label,
      properties: { worldSignal: true },
      point: { pixelSize: 12 },
    })
  })
})

describe('WorldView durable scope layer', () => {
  it('marks the real selected geometry without minting a second entity', () => {
    const add = vi.fn()
    const viewer = { entities: { add } } as unknown as Cesium.Viewer

    addScope(viewer, selectedScope, true)

    expect(add).toHaveBeenCalledOnce()
    expect(add.mock.calls[0][0]).toMatchObject({
      id: selectedScope.id,
      name: selectedScope.label,
      properties: { worldScope: true, selected: true },
      point: { pixelSize: 14, outlineWidth: 3 },
    })
  })
})

// ── layer glyphs (God's Eye View parity, 2026-08-26) ──────────────────────

function signal(overrides: Partial<WorldSignal>): WorldSignal {
  return { ...contact, ...overrides }
}

/** The entity options `addSignal` builds, kept loose on purpose: this test
 *  asserts what the glyph code chose, not Cesium's own option types. */
type AddedEntity = Record<string, never> & {
  billboard?: { rotation: number }
  ellipse?: { semiMajorAxis: number }
  point?: unknown
  polyline?: unknown
  properties: { worldSignal: boolean; layer: string }
}

function collectingViewer() {
  const added: AddedEntity[] = []
  const add = (entity: unknown) => {
    added.push(entity as AddedEntity)
    return entity
  }
  return {
    viewer: { entities: { add } } as unknown as Cesium.Viewer,
    added,
  }
}

describe('contact glyphs', () => {
  it('draws an aircraft as an arrow rotated onto its own track', () => {
    const { viewer, added } = collectingViewer()
    addSignal(viewer, signal({
      id: 'world_signal:adsb:a1', provider: 'adsb', source_id: 'a1',
      layer: 'aircraft', label: 'UAE201',
      details: { track_deg: 90, altitude_ft: 37000 },
    }))
    expect(added).toHaveLength(1)
    expect(added[0].billboard).toBeDefined()
    // -90° in radians: Cesium rotates counter-clockwise, compass track is
    // clockwise, so the sign flip IS the correctness here.
    expect(added[0].billboard?.rotation).toBeCloseTo(-Math.PI / 2, 6)
    // An airborne contact gets a leader line down to the ground it is over.
    expect(added[0].polyline).toBeDefined()
  })

  it('leaves an aircraft with no reported track as a plain contact', () => {
    const { viewer, added } = collectingViewer()
    addSignal(viewer, signal({ layer: 'aircraft', details: { altitude_ft: 1000 } }))
    // No heading was reported, so none is drawn. An arrow pointing north by
    // default would be the map inventing telemetry.
    expect(added[0].billboard).toBeUndefined()
    expect(added[0].point).toBeDefined()
  })

  it('sizes an earthquake ring by magnitude', () => {
    const { viewer, added } = collectingViewer()
    addSignal(viewer, signal({ layer: 'earthquakes', details: { magnitude: 6 } }))
    const six = added[0].ellipse?.semiMajorAxis ?? 0

    const second = collectingViewer()
    addSignal(second.viewer, signal({ layer: 'earthquakes', details: { magnitude: 4 } }))
    expect(six).toBeGreaterThan(second.added[0].ellipse?.semiMajorAxis ?? 0)
  })

  it('marks every signal entity so the pick handler can tell it from a scope', () => {
    const { viewer, added } = collectingViewer()
    addSignal(viewer, signal({ layer: 'satellites', details: { altitude_km: 420 } }))
    expect(added[0].properties.worldSignal).toBe(true)
    expect(added[0].properties.layer).toBe('satellites')
  })
})

describe('signalHeight', () => {
  it('reads feet and kilometres, and nothing else', async () => {
    const { signalHeight } = await import('./worldSignals.ts')
    expect(signalHeight(signal({ details: { altitude_ft: 1000 } }))).toBeCloseTo(304.8, 3)
    expect(signalHeight(signal({ details: { altitude_km: 420 } }))).toBe(420_000)
    // A string from a CSV feed is still a number.
    expect(signalHeight(signal({ details: { altitude_ft: '1000' } }))).toBeCloseTo(304.8, 3)
    // Ground contacts clamp to terrain rather than floating at zero.
    expect(signalHeight(signal({ details: {} }))).toBeNull()
    expect(signalHeight(signal({ details: { altitude_ft: 'unknown' } }))).toBeNull()
  })
})
