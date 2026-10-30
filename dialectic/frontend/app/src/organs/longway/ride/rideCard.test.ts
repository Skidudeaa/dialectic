import { describe, expect, it } from 'vitest'
import { estimatedKm, firstLitSight, gapsAhead, historyLine, lightAt, mergeSights, positionAt, replayKm, sightEntities, sightsAhead, stopTimeline, sunEl, viewsNow } from './rideCard'
import { fixtureLeg as leg, fixtureRide as ride } from './fixtures'
import { rideStyle } from './rideLayers'
const at = Date.parse('2026-10-23T09:53:00-07:00')

describe('ride instrument against the original leg and logbook', () => {
  it('keeps the solar darkness rule and names civil twilight', () => {
    expect(lightAt(42.49, -121.88, at)).toBe('daylight')
    expect(lightAt(42.49, -121.88, Date.parse('2026-10-23T03:00:00-07:00'))).toBe('dark')
    const twilight = Array.from({ length: 120 }, (_, i) => Date.parse('2026-10-23T06:00:00-07:00') + i * 60000).find(t => sunEl(42.49, -121.88, t) >= -6 && sunEl(42.49, -121.88, t) < 0)!
    expect(lightAt(42.49, -121.88, twilight)).toBe('twilight')
  })
  it('shows the screenshot classes at km 635 with the later model’s lake name and countdown', () => {
    const [left, right] = viewsNow(leg, ride.stops, 635)
    expect(left).toMatchObject({ label: "Don't miss", side: 'left' })
    expect(left.name).toContain('Upper Klamath Lake')
    expect(left.remaining).toBeCloseTo(3.8)
    expect(left.minutes).toBeCloseTo(3.8 * 76 / 118.2)
    expect(right).toMatchObject({ label: 'Nothing', name: '' })
    expect(sightsAhead(leg, ride.stops, 635, at).some(w => w.name.includes('Mount Scott'))).toBe(true)
  })
  it('uses per-km names and their photos when no major window covers the spot', () => {
    const model = { ...leg, sights: { ...leg.sights, sights: [] } }
    const left = viewsNow(model, ride.stops, 635)[0]
    expect(left.name).toBe('Pelican Butte')
    expect(sightEntities(left.name, leg.guide)[0].img).toMatch(/^https:/)
  })
  it('merges windows on the same side within 2 km without mutating source data', () => {
    const w = leg.sights.sights.find(w => w.major)!
    const windows = [{ ...w, name: 'A', km0: 1, km1: 5 }, { ...w, name: 'B', km0: 7, km1: 9 }, { ...w, name: 'C', side: 'left' as const, km0: 10, km1: 15 }]
    const result = mergeSights(windows)
    expect(result[0]).toMatchObject({ name: 'A; B', km0: 1, km1: 9 })
    expect(windows[0].name).toBe('A')
    expect(result).toHaveLength(2)
  })
  it('re-times views and gaps from this run’s schedule and estimates, never the file’s old t0', () => {
    const a = sightsAhead(leg, ride.stops, 635, at)[0]
    const shifted = ride.stops.map(s => ({ ...s, arr: s.arr && new Date(Date.parse(s.arr) + 30 * 60000).toISOString(), dep: s.dep && new Date(Date.parse(s.dep) + 30 * 60000).toISOString() }))
    const b = sightsAhead(leg, shifted, 635, at)[0]
    expect(b.at0! - a.at0!).toBeCloseTo(30 * 60000)
    const model = { ...leg, coverage: { ...leg.coverage!, gaps: [{ km0: 680, km1: 690, length_km: 10, minutes: 6, near: 'Klamath Falls to Chemult', from_code: 'KFS', t0: 1, t1: 2 }] } }
    const gap = gapsAhead(model, ride.stops, 635, at)[0]
    expect(gap.at0).toBeGreaterThan(at)
    expect(gapsAhead(model, ride.stops, 700, at)).toEqual([])
  })
  it('interpolates the actual stops honestly: 09:53 is km 646, not the screenshot GPS km 635', () => {
    expect(replayKm(ride.stops, at)).toBeCloseTo(601.6 + 118.2 * 29 / 77)
    expect(replayKm(ride.stops, Date.parse('2026-10-23T16:15:00Z'))).toBe(601.6)
    const p = positionAt(leg.sights.km, 635)!
    expect(p).toEqual([-121.8795, 42.4946])
  })
  it('falls back to schedule plus the last known lateness at the unrecorded Seattle arrival', () => {
    const end = stopTimeline(ride.stops).at(-1)!
    expect(end.arrival).toBe(Date.parse('2026-10-24T03:53:00Z'))
  })
  it('counts distance down during a 20 minute outage at timetable pace', () => {
    const data = { ...ride, km: 635, fix: { lat: 42.4946, lon: -121.8795, at: new Date(at).toISOString(), age_min: 0, speed_mph: 70, heading: 'N', source: 'amtrak' as const } }
    expect(estimatedKm(data, at + 20 * 60000)).toBeCloseTo(635 + 20 * 118.2 / 76)
  })
  it('reports next-stop history and does not invent history when absent', () => {
    expect(historyLine({ ...ride, history: { days: 30, at: { CMO: { n: 20, median: 18, worst: 142 } } } }, 'CMO')).toContain('median 18 min late, worst 2 h 22 min late')
    expect(historyLine(ride, 'CMO')).toBe('Lateness history unavailable.')
  })
  it('keeps 7/14 px magenta teeth on the correct sides and signal off by default', () => {
    const style = rideStyle(leg)
    const tooth = style.layers.find(l => l.id === 'teeth-left-3')!
    expect(tooth.paint).toMatchObject({ 'line-width': 14, 'line-offset': -12, 'line-color': '#ff2fd6' })
    expect(style.layers.find(l => l.id === 'teeth-right-2')!.paint).toMatchObject({ 'line-width': 7, 'line-offset': 8.5 })
    expect(style.layers.find(l => l.id === 'signal')!.layout).toMatchObject({ visibility: 'none' })
  })
  it('opens an arrived replay on the first major sight in daylight, never at a dark boarding', () => {
    const t = firstLitSight(leg, ride.stops)!
    const km = replayKm(ride.stops, t)!, at = positionAt(leg.sights.km, km)!
    expect(lightAt(at[1], at[0], t)).toBe('daylight')
    expect(viewsNow(leg, ride.stops, km).some(v => v.c === 3)).toBe(true)
    expect(firstLitSight({ ...leg, sights: { ...leg.sights, sights: [] } }, ride.stops)).toBeNull()
  })
})
