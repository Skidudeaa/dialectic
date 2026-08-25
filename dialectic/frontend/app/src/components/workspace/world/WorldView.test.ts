import { describe, expect, it, vi } from 'vitest'
import type * as Cesium from 'cesium'
import type { WorldSignal } from '../../../types/geo.ts'
import { addSignal } from './worldSignals.ts'

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
