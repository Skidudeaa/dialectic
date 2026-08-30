import { describe, expect, it } from 'vitest'
import type * as Cesium from 'cesium'
import type { WorldObservation, WorldSignal } from '../../../types/geo.ts'
import { addSignal, isTrackable, observationToSignal } from './worldSignals.ts'

// The recorded layer (World Lens: the consumer, 2026-08-30) — durable
// world_observations rendered as dimmed WorldSignal-shaped glyphs beside
// live signals, never trackable.

const observation: WorldObservation = {
  id: 'world_observation:adsb:contact-9',
  scope_id: 'geo_scope:hormuz',
  scope_label: 'Strait of Hormuz',
  provider: 'adsb',
  signal_id: 'world_signal:adsb:contact-9',
  layer: 'aircraft',
  kind: 'point',
  label: 'UAE201',
  geometry: { type: 'Point', coordinates: [56.3, 26.5] },
  provenance: { provider: 'adsb', acquisition: 'adapter:adsb', source_id: 'contact-9', url: null, credit: 'adsb.lol (ODbL)' },
  details: { track_deg: 90, altitude_ft: 37000 },
  observed_at: '2026-08-30T17:58:00Z',
  retrieved_at: '2026-08-30T17:59:00Z',
  first_seen_at: '2026-08-30T17:30:00Z',
  last_seen_at: '2026-08-30T17:59:00Z',
  seen_count: 4,
}

function collectingViewer() {
  const added: Array<Record<string, unknown>> = []
  const add = (entity: unknown) => {
    added.push(entity as Record<string, unknown>)
    return entity
  }
  return { viewer: { entities: { add } } as unknown as Cesium.Viewer, added }
}

describe('observationToSignal', () => {
  it('stamps freshness recorded and carries the layer glyph forward unchanged', () => {
    const signal = observationToSignal(observation, 'room-h')
    expect(signal.freshness).toBe('recorded')
    expect(signal.layer).toBe('aircraft')
    expect(signal.kind).toBe('point')
    expect(signal.geometry).toEqual(observation.geometry)
    expect(signal.details).toEqual(observation.details)
    expect(signal.room_id).toBe('room-h')
    expect(signal.source_id).toBe(observation.signal_id)
  })
})

describe('isTrackable', () => {
  it('excludes a recorded observation from track-on-click', () => {
    const recorded = observationToSignal(observation)
    expect(isTrackable(recorded)).toBe(false)
  })

  it('leaves a live signal trackable', () => {
    const live: WorldSignal = { ...observationToSignal(observation), freshness: 'current' }
    expect(isTrackable(live)).toBe(true)
  })
})

describe('addSignal dimming', () => {
  it('draws a recorded contact smaller and at reduced alpha than the same live contact', () => {
    const live = collectingViewer()
    addSignal(live.viewer, { ...observationToSignal(observation), freshness: 'current' })
    const recorded = collectingViewer()
    addSignal(recorded.viewer, observationToSignal(observation))

    const liveBillboard = live.added[0].billboard as { width: number } | undefined
    const recordedBillboard = recorded.added[0].billboard as { width: number } | undefined
    expect(liveBillboard).toBeDefined()
    expect(recordedBillboard).toBeDefined()
    expect(recordedBillboard!.width).toBeLessThan(liveBillboard!.width)
  })

  it('sizes a fire by radiative power and rings only a NEW cell', () => {
    const fire = (details: Record<string, unknown>): WorldObservation => ({
      ...observation, layer: 'fires', details,
    })
    const weak = collectingViewer()
    addSignal(weak.viewer, { ...observationToSignal(fire({ frp_mw: 2, novel: false })), freshness: 'current' })
    const strong = collectingViewer()
    addSignal(strong.viewer, { ...observationToSignal(fire({ frp_mw: 60, novel: true })), freshness: 'current' })
    const weakPoint = weak.added[0].point as { pixelSize: number; outlineWidth: number }
    const strongPoint = strong.added[0].point as { pixelSize: number; outlineWidth: number }
    expect(strongPoint.pixelSize).toBeGreaterThan(weakPoint.pixelSize)
    expect(strongPoint.outlineWidth).toBe(2)
    expect(weakPoint.outlineWidth).toBe(1)
    expect((strong.added[0].label as { text: string }).text.startsWith('NEW ')).toBe(true)
    expect((weak.added[0].label as { text: string }).text.startsWith('NEW ')).toBe(false)
  })

  it('sizes a recorded earthquake ring smaller than its live counterpart', () => {
    const quake: WorldObservation = {
      ...observation, layer: 'earthquakes', details: { magnitude: 6 },
    }
    const live = collectingViewer()
    addSignal(live.viewer, { ...observationToSignal(quake), freshness: 'current' })
    const recorded = collectingViewer()
    addSignal(recorded.viewer, observationToSignal(quake))

    const liveEllipse = live.added[0].ellipse as { semiMajorAxis: number }
    const recordedEllipse = recorded.added[0].ellipse as { semiMajorAxis: number }
    expect(recordedEllipse.semiMajorAxis).toBeLessThan(liveEllipse.semiMajorAxis)
  })
})
