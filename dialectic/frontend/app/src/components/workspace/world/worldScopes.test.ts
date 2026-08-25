import { describe, expect, it } from 'vitest'
import type { GeoScope } from '../../../types/geo.ts'
import { isProvisional, scopeDestination, scopesBounds } from './worldScopes'

function scope(partial: Partial<GeoScope>): GeoScope {
  return {
    id: 'geo_scope:1', room_id: 'room-1',
    subject: { entity: 'rooms', id: 'room-1' },
    kind: 'polygon',
    geometry: { type: 'Polygon', coordinates: [[[55, 26], [57, 26], [57, 27], [55, 27], [55, 26]]] },
    label: 'Strait', authority: 'human_confirmed',
    provenance: { provider: 'human', acquisition: 'human', credit: '' },
    source_state: 'ok', centroid: [56, 26.5],
    retrieved_at: '2026-08-25T00:00:00Z', created_at: '2026-08-25T00:00:00Z',
    ...partial,
  }
}

describe('scopeDestination', () => {
  it('lands on the subject, reusing workspace-object ids', () => {
    expect(scopeDestination(scope({}))).toEqual({ roomId: 'room-1' })
    expect(scopeDestination(scope({ subject: { entity: 'reading_items', id: 'r9' } })))
      .toEqual({ roomId: 'room-1', object: 'reading:r9' })
    expect(scopeDestination(scope({ subject: { entity: 'field_marks', id: 'm3' } })))
      .toEqual({ roomId: 'room-1', object: 'field_mark:m3' })
    expect(scopeDestination(scope({ subject: { entity: 'messages', id: 'msg' } })))
      .toEqual({ roomId: 'room-1', messageId: 'msg' })
    expect(scopeDestination(scope({ subject: { entity: 'memories', id: 'x' } })))
      .toEqual({ roomId: 'room-1' })
  })
})

describe('scopesBounds', () => {
  it('frames every geometry kind and returns null for nothing', () => {
    expect(scopesBounds([])).toBeNull()
    const bounds = scopesBounds([
      scope({}),
      scope({ kind: 'point', geometry: { type: 'Point', coordinates: [60, 20] } }),
      scope({ kind: 'route', geometry: { type: 'LineString', coordinates: [[50, 30], [52, 31]] } }),
    ])
    expect(bounds).toEqual([50, 20, 60, 31])
  })
})

describe('authority', () => {
  it('is what makes a scope provisional — never the label or the state', () => {
    expect(isProvisional(scope({ authority: 'machine_proposed' }))).toBe(true)
    expect(isProvisional(scope({ authority: 'human_confirmed', source_state: 'stale' }))).toBe(false)
    expect(isProvisional(scope({ authority: 'source_reported' }))).toBe(false)
  })
})
