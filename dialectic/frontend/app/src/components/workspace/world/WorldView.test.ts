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
