// Test/preview adapter: preserve the original logbook's observations.
import rawLeg from '../__fixtures__/ride-leg.json'
import book from '../__fixtures__/ride-logbook.json'
import type { RideData, RideLeg } from '../types'
// The Coast Starlight's own route-guide score (legs/amtrak-313-14/check.json, 30 Oct): its views pass the line.
export const fixtureLeg: RideLeg = { ...(rawLeg as unknown as RideLeg), check: { score: { agree: 6, total: 7, misses: [{ name: 'Mount Scott', why: 'missing' }] } } }
export const fixtureRide: RideData = {
  trip: { slug: book.trip, title: 'Coast Starlight 2026' },
  rides: [{ id: book.ride, date: book.date, state: 'arrived' }],
  ride: { id: book.ride, date: book.date, board: book.board, alight: book.alight, riders: ['Amo'], leg: book.leg, leg_ready: true, logbook: true, vehicle: { name: book.vehicle, kind: 'train', amtrak: book.train }, state: 'arrived' },
  run: book.ride, fix: null, fix_unavailable_reason: 'No GPS track was stored', km: null,
  stops: book.stops.map(s => ({ code: s.code, name: fixtureLeg.sights.stations.find(p => p.code === s.code)?.name ?? s.code, km: s.km, sched_arr: s.sched_arr, sched_dep: s.sched_dep, arr: s.arr, dep: s.dep, estimated: false, status: null, late_min: s.late_dep ?? s.late_arr })),
  history: null, track: [], fetched_at: '2026-10-29T12:00:00Z',
}
