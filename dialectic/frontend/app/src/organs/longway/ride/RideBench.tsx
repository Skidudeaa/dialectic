import { useState } from 'react'
import type { ReactNode } from 'react'
import { useRide } from './useRide'
import { estimatedKm, firstLitSight, headingDegrees, positionAt, replayEvents, replayKm, trackHeading } from './rideCard'
import { RideCard } from './RideCard'
import RideMap from './RideMap'
import type { RideLeg } from '../types'
import './ride.css'

// A route nobody has modelled yet still gets the map: imagery, the vehicle at its fix and the stored track.
const BARE: RideLeg = { id: '', leg: null, sights: { built: '', classes: [], km: [], left: [], right: [], sights: [], stations: [], peaks: [] }, coverage: null, guide: {}, check: null }

export default function RideBench({ roomId, record }: { roomId: string; record?: ReactNode }) {
  const [selected, setSelected] = useState<string>()
  const [scrub, setScrub] = useState<number | null>(null)
  const { data, leg, error, legError, now, offline, lastSuccess, refresh } = useRide(roomId, selected)
  if (!data) return <div className="longway-bench longway-ride"><p role={error ? 'alert' : 'status'}>{error || 'Loading ride…'} {error && <button onClick={refresh}>Retry ride</button>}</p>{record && <div className="longway-bench-record">{record}</div>}</div>
  const replay = data.ride.state === 'arrived', events = replayEvents(data.stops)
  const start = events[0]?.t, end = events.at(-1)?.t
  const opening = replay && leg ? firstLitSight(leg, data.stops) : null
  const time = replay && start !== undefined && end !== undefined ? Math.max(start, Math.min(end, scrub ?? opening ?? start)) : now
  const km = replay ? replayKm(data.stops, time) : offline ? estimatedKm(data, now) : data.km
  const fixAt: [number, number] | null = data.fix ? [data.fix.lon, data.fix.lat] : null
  const modelled = leg && km !== null ? positionAt(leg.sights.km, km) : null
  const position: [number, number] | null = !replay && !offline && fixAt ? fixAt : modelled ?? (replay ? null : fixAt)
  const heading = headingDegrees(replay || offline ? null : data.fix?.heading, leg && km !== null ? trackHeading(leg.sights.km, km) : 0)
  return <div className="longway-bench longway-ride">
    {data.rides.length > 1 && <label className="ride-selector">Ride <select value={data.ride.id} onChange={e => { setSelected(e.target.value); setScrub(null) }}>{data.rides.map(r => <option value={r.id} key={r.id}>{r.date} · {r.id} · {r.state}</option>)}</select></label>}
    {(leg || position) && <RideMap leg={leg ?? BARE} position={position} heading={heading} data={data} time={time} />}
    {!leg && <p role="status" className="ride-meta">{legError || (data.ride.leg_ready ? 'Loading the views along this route…' : 'No view model for this route yet: the train, its stops and its lateness.')}{legError && <button onClick={refresh}>Retry leg</button>}</p>}
    <div className="longway-chart-notes ride-notes">
      {replay && start !== undefined && end !== undefined && <section className="ride-replay" aria-label="Ride replay">
        <label htmlFor="ride-time">Replay time</label><output htmlFor="ride-time">{new Date(time).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })} · {Intl.DateTimeFormat().resolvedOptions().timeZone}</output>
        <input id="ride-time" type="range" min={start} max={end} step={60000} value={time} onChange={e => setScrub(Number(e.target.value))} />
        <label>Exact time (with timezone)<input type="text" key={data.ride.id} placeholder="2026-10-23T09:53:00-07:00" onBlur={e => { const n = Date.parse(e.target.value); if (Number.isFinite(n)) setScrub(n) }} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} /></label>
        <p className="ride-meta">{new Date(start).toLocaleString()} — {new Date(end).toLocaleString()}</p>
      </section>}
      {replay && !events.length && <p>Replay unavailable: this logbook has no timed stops.</p>}
      {error && <p role="status">Refresh unavailable: {error} <button onClick={refresh}>Retry ride</button></p>}
      <RideCard data={data} leg={leg} km={km} now={time} replay={replay} offline={!!offline} lastSuccess={lastSuccess} />
    </div>
    {record && <div className="longway-bench-record">{record}</div>}
  </div>
}
