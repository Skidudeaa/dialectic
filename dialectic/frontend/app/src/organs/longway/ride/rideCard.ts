import type { GuideEntry, KmRow, RideData, RideLeg, RideStop, SightWindow } from '../types'
const MIN = 60000
const ms = (s: string | null) => s ? Date.parse(s) : NaN
const clamp = (n: number, a: number, b: number) => Math.max(a, Math.min(b, n))

/** The live chart's low-precision solar almanac; the civil-twilight boundary is -6°. */
export function sunEl(lat: number, lon: number, t: number) {
  const dd = (t - Date.UTC(2000, 0, 1, 12)) / 864e5, rad = Math.PI / 180
  const g = ((357.528 + .9856003 * dd) % 360) * rad
  const lam = ((280.460 + .9856474 * dd + 1.915 * Math.sin(g) + .020 * Math.sin(2 * g)) % 360) * rad, eps = (23.439 - .0000004 * dd) * rad
  const ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam)), dec = Math.asin(Math.sin(eps) * Math.sin(lam))
  const ha = ((((18.697374558 + 24.06570982441908 * dd) % 24) * 15 + lon) % 360) * rad - ra, phi = lat * rad
  return Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(ha)) / rad
}
export function lightAt(lat: number, lon: number, t: number) {
  const el = sunEl(lat, lon, t)
  return el < -6 ? 'dark' : el < 0 ? 'twilight' : 'daylight'
}

/** Preserve dwell time. Unknown events inherit the last observed lateness, never a future observation. */
export function stopTimeline(stops: RideStop[]) {
  let late = 0
  return stops.map(stop => {
    const event = (kind: 'arr' | 'dep') => {
      const actual = ms(stop[kind]), scheduled = ms(stop[`sched_${kind}`])
      if (Number.isFinite(actual)) {
        if (Number.isFinite(scheduled)) late = (actual - scheduled) / MIN
        return actual
      }
      return Number.isFinite(scheduled) ? scheduled + late * MIN : NaN
    }
    const arrival = event('arr'), departure = event('dep')
    return { stop, arrival: Number.isFinite(arrival) ? arrival : departure, departure: Number.isFinite(departure) ? departure : arrival }
  })
}
export function replayEvents(stops: RideStop[]) {
  return stopTimeline(stops).flatMap(({ stop, arrival, departure }) => stop.km === null ? [] :
    [{ t: arrival, km: stop.km }, { t: departure, km: stop.km }].filter(e => Number.isFinite(e.t)))
    .sort((a, b) => a.t - b.t)
}
export function replayKm(stops: RideStop[], t: number): number | null {
  const events = replayEvents(stops)
  if (!events.length) return null
  if (t <= events[0].t) return events[0].km
  for (let i = 1; i < events.length; i++) {
    const a = events[i - 1], b = events[i]
    if (t <= b.t) return a.km + (b.km - a.km) * clamp((t - a.t) / Math.max(1, b.t - a.t), 0, 1)
  }
  return events[events.length - 1].km
}
export function positionAt(rows: KmRow[], km: number): [number, number] | null {
  if (!rows.length || km < rows[0][0] || km > rows[rows.length - 1][0]) return null
  const i = rows.findIndex(row => row[0] >= km), b = rows[i], a = rows[Math.max(0, i - 1)]
  const f = (km - a[0]) / (b[0] - a[0] || 1)
  return [a[4] + (b[4] - a[4]) * f, a[3] + (b[3] - a[3]) * f]
}

/** Rebase the leg's old timetable onto this run's ISO schedule. No route, origin-day or timezone constants. */
export function timeAtKm(stops: RideStop[], km: number, scheduled = false): number | null {
  const timeline = stopTimeline(stops).filter(e => e.stop.km !== null && Number.isFinite(e.arrival) && Number.isFinite(e.departure))
  if (!timeline.length) return null
  const arrive = (e: typeof timeline[number]) => scheduled ? ms(e.stop.sched_arr ?? e.stop.sched_dep) : e.arrival
  const depart = (e: typeof timeline[number]) => scheduled ? ms(e.stop.sched_dep ?? e.stop.sched_arr) : e.departure
  for (let i = 1; i < timeline.length; i++) {
    const a = timeline[i - 1], b = timeline[i]
    if (km <= b.stop.km!) {
      const f = clamp((km - a.stop.km!) / (b.stop.km! - a.stop.km! || 1), 0, 1)
      return depart(a) + (arrive(b) - depart(a)) * f
    }
  }
  return arrive(timeline[timeline.length - 1])
}
export function paceAt(stops: RideStop[], km: number) {
  const valid = stops.filter(s => s.km !== null)
  for (let i = 1; i < valid.length; i++) {
    const a = valid[i - 1], b = valid[i]
    if (km >= a.km! && km <= b.km!) {
      const minutes = (ms(b.sched_arr ?? b.sched_dep) - ms(a.sched_dep ?? a.sched_arr)) / MIN
      return minutes > 0 ? minutes / (b.km! - a.km! || 1) : null
    }
  }
  return null
}
/** Advance distance at each stretch's timetable pace, including intermediate station dwells. */
export function estimatedKm(data: RideData, now: number) {
  if (data.km === null || !data.fix) return data.km
  const anchor = timeAtKm(data.stops, data.km, true)
  if (anchor === null) return data.km
  const scheduled = data.stops.map(s => ({ ...s, arr: s.sched_arr, dep: s.sched_dep }))
  return replayKm(scheduled, anchor + Math.max(0, now - ms(data.fix.at))) ?? data.km
}
export function mergeSights(windows: SightWindow[]) {
  const merged: SightWindow[] = []
  for (const side of ['left', 'right'] as const) {
    for (const w of windows.filter(w => w.side === side).sort((a, b) => a.km0 - b.km0)) {
      const last = merged[merged.length - 1]
      if (last && last.side === side && w.km0 <= last.km1 + 2) {
        last.name = [...new Set([last.name, w.name])].join('; ')
        last.km1 = Math.max(last.km1, w.km1); last.t1 = Math.max(last.t1, w.t1)
        last.length_km = last.km1 - last.km0; last.minutes = last.t1 - last.t0
      } else merged.push({ ...w })
    }
  }
  return merged.sort((a, b) => a.km0 - b.km0)
}
const majorWindows = (leg: RideLeg) => mergeSights(leg.sights.sights.filter(w => w.major))
export function viewsNow(leg: RideLeg, stops: RideStop[], km: number) {
  const row = leg.sights.km.reduce<KmRow | null>((best, r) => !best || Math.abs(r[0] - km) < Math.abs(best[0] - km) ? r : best, null)
  if (!row || Math.abs(row[0] - km) > 3) return []
  return (['left', 'right'] as const).map((side, i) => {
    const c = row[i + 1] as number, w = majorWindows(leg).find(w => w.side === side && w.km0 <= km && w.km1 >= km)
    const remaining = w ? Math.max(0, w.km1 - km) : null
    const pace = paceAt(stops, km) ?? (w ? (w.t1 - w.t0) / Math.max(.2, w.km1 - w.km0) : null)
    return { side, c, label: c === 3 ? "Don't miss" : c === 2 ? 'Worth a look' : 'Nothing', name: w?.name ?? row[i + 5] as string ?? '', remaining, minutes: remaining !== null && pace !== null ? remaining * pace : null }
  })
}
/** The kill line of 30 Oct (docs/moonshot-ride.md): a leg's views show only when its operator route-guide check agrees on
 *  at least 80% of landmarks with at most one on the wrong side. The Zephyr scored 7 of 13 and keeps only its track, stops
 *  and signal; a leg with no scored check keeps the same until it is checked. */
export function viewsTrusted(check: RideLeg['check']) {
  const s = check?.score
  return !!s && s.total > 0 && s.agree / s.total >= 0.8 && (s.misses ?? []).filter(m => m.why === 'side miss').length <= 1
}
/** The leg as the map may draw it when its views are withheld: the track stays, the views, names and summits go. */
export function withheldViews(leg: RideLeg): RideLeg {
  return { ...leg, guide: {}, sights: { ...leg.sights, left: [], right: [], sights: [], peaks: [], km: leg.sights.km.map(r => [r[0], 0, 0, r[3], r[4], '', ''] as KmRow) } }
}
/** Where an arrived ride's replay opens: mid-way through its first major sight seen in daylight, not at a dark boarding. */
export function firstLitSight(leg: RideLeg, stops: RideStop[]): number | null {
  for (const w of majorWindows(leg)) {
    const km = (w.km0 + w.km1) / 2, t = timeAtKm(stops, km), at = positionAt(leg.sights.km, km)
    if (t !== null && at && lightAt(at[1], at[0], t) === 'daylight') return t
  }
  return null
}
export function sightsAhead(leg: RideLeg, stops: RideStop[], km: number | null, now: number) {
  return majorWindows(leg).map(w => ({ ...w, at0: timeAtKm(stops, w.km0), at1: timeAtKm(stops, w.km1) }))
    .filter(w => (km === null || w.km0 > km) && w.at1 !== null && w.at1 > now).slice(0, 6)
}
export function gapsAhead(leg: RideLeg, stops: RideStop[], km: number | null, now: number) {
  return (leg.coverage?.gaps ?? []).map(g => ({ ...g, at0: timeAtKm(stops, g.km0), at1: timeAtKm(stops, g.km1) }))
    .filter(g => (km === null || g.km1 > km) && g.at1 !== null && g.at1 > now)
}
export function sightEntities(name: string, guide: RideLeg['guide']): GuideEntry[] {
  let end = -1
  return Object.entries(guide ?? {}).map(([key, entry]) => ({ key, entry, at: name.indexOf(key) }))
    .filter(m => m.key && m.at >= 0).sort((a, b) => a.at - b.at || b.key.length - a.key.length)
    .filter(m => { if (m.at < end) return false; end = m.at + m.key.length; return true })
    .map(m => ({ ...m.entry, title: m.entry.title || m.key }))
}
export function nextStops(data: RideData, km: number | null, now: number) {
  return stopTimeline(data.stops).filter(e => e.departure > now && (km === null || e.stop.km === null || e.stop.km >= km)).slice(0, 5)
}
export function historyLine(data: RideData, code?: string) {
  const h = code && data.history?.at[code]
  return h ? `Past ${h.n} runs: median ${lateness(h.median)}, worst ${lateness(h.worst)} (${data.history!.days} days).` : 'Lateness history unavailable.'
}
export function lateness(min: number | null) {
  if (min === null) return 'Unknown'
  if (min === 0) return 'On time'
  const n = Math.abs(Math.round(min))
  return `${n >= 60 ? `${Math.floor(n / 60)} h ` : ''}${n % 60} min ${min < 0 ? 'early' : 'late'}`
}
export const clockTime = (t: number | string | null) => t === null || (typeof t === 'number' && !Number.isFinite(t)) ? '—' : new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
export function trackHeading(rows: KmRow[], km: number) {
  const a = positionAt(rows, Math.max(rows[0]?.[0] ?? 0, km - .5)), b = positionAt(rows, Math.min(rows.at(-1)?.[0] ?? km, km + .5))
  if (!a || !b) return 0
  return Math.atan2((b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180), b[1] - a[1]) * 180 / Math.PI
}
export function headingDegrees(heading: string | null | undefined, fallback: number) {
  if (!heading) return fallback
  const compass: Record<string, number> = { N: 0, NNE: 22.5, NE: 45, ENE: 67.5, E: 90, ESE: 112.5, SE: 135, SSE: 157.5, S: 180, SSW: 202.5, SW: 225, WSW: 247.5, W: 270, WNW: 292.5, NW: 315, NNW: 337.5 }
  return compass[heading.toUpperCase()] ?? (Number.isFinite(Number(heading)) ? Number(heading) : fallback)
}
