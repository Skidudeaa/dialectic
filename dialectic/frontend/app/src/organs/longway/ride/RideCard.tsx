import type { RideData, RideLeg } from '../types'
import { clockTime, gapsAhead, historyLine, lateness, lightAt, nextStops, positionAt, sightEntities, sightsAhead, viewsNow } from './rideCard'

function Sight({ name, meta, leg, current = false }: { name: string; meta: string; leg: RideLeg; current?: boolean }) {
  const entries = sightEntities(name, leg.guide), first = entries[0]
  return <div className="ride-sight">
    {first?.img?.startsWith('https://') && <img src={first.img} alt={first.title} decoding="async" onError={e => { e.currentTarget.hidden = true }} />}
    <div><strong>{name}</strong><p className="ride-meta">{meta}</p>
      {current && first?.what && <p>{first.what}</p>}
      {entries.length > 0 && <details><summary>About this sight</summary>{entries.map((entry, i) => <section key={i}>
        <h4>{entry.title}</h4><p>{entry.what}</p><p>{entry.history}</p>
        {entry.links?.filter(l => l.url.startsWith('https://')).map(l => <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer">{l.label}{l.src ? ` · ${l.src}` : ''}</a>)}
        {entry.img_credit && <small>{entry.img_credit}</small>}
      </section>)}</details>}
    </div>
  </div>
}
export function RideCard({ data, leg, km, now, replay, offline, lastSuccess }: {
  data: RideData; leg: RideLeg | null; km: number | null; now: number; replay: boolean; offline: boolean; lastSuccess: number | null
}) {
  const position = leg && km !== null ? positionAt(leg.sights.km, km) : data.fix ? [data.fix.lon, data.fix.lat] : null
  const light = position ? lightAt(position[1], position[0], now) : null
  const views = leg && km !== null ? viewsNow(leg, data.stops, km) : []
  const ahead = leg ? sightsAhead(leg, data.stops, km, now) : []
  const gaps = leg ? gapsAhead(leg, data.stops, km, now) : [], longGaps = gaps.filter(g => g.minutes >= 5)
  const next = nextStops(data, km, now)
  const previous = data.stops.filter(s => s.dep && Date.parse(s.dep) <= now).at(-1)
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
  return <article className="ride-card" aria-label="Ride instrument">
    {offline && <p role="status" className="ride-offline">No signal since {clockTime(lastSuccess)}, position estimated</p>}
    {replay && <p className="ride-meta">Replay · position interpolated between recorded stops. Historical GPS and forecasts were not recorded.</p>}
    <section><h2>Views now <small>{km === null ? '' : `(model, km ${Math.round(km)})`}</small></h2>
      {light === 'dark' ? <p>Too dark to see the views on either side.</p> : <>
        {light === 'twilight' && <p>Twilight</p>}
        {views.length ? views.map(v => <div key={v.side} className="ride-window">
          <p className="ride-side">{v.side === 'left' ? '◀ Left' : 'Right ▶'} · <strong>{v.label}</strong></p>
          {v.name && leg && <Sight name={v.name} leg={leg} current meta={v.remaining !== null ? `${v.remaining < 1 ? 'Under 1' : Math.round(v.remaining)} km left · ${v.minutes !== null ? `about ${Math.round(v.minutes)} min` : 'duration unknown'}` : v.c < 2 ? 'Small, on the horizon · no mark on the map' : 'Here'} />}
        </div>) : <p>{leg ? 'Waiting for a position on the modelled leg.' : 'View model unavailable for this leg.'}</p>}
      </>}
    </section>
    {leg && <section><h2>Sights ahead <small>(model)</small></h2>
      {ahead.length ? ahead.map(w => <Sight key={`${w.side}:${w.km0}`} name={w.name} leg={leg} meta={`${clockTime(w.at0)}–${clockTime(w.at1)} · ${w.side} · ${w.length_km.toFixed(1)} km${w.size !== undefined ? ` · up to ${w.size}°` : ''}${w.at0 !== null && w.at1 !== null ? ` · ${lightAt(w.lat, w.lon, (w.at0 + w.at1) / 2)}` : ''}${w.sky != null ? ` · ${w.sky}% cloud (model snapshot)` : ''}`} />) : <p>No further timed sights.</p>}
    </section>}
    {leg?.coverage && <section><h2>No usable data ahead <small>(model)</small></h2>
      {gaps.length ? <ul>{longGaps.map(g => <li key={g.km0}>{clockTime(g.at0)}–{clockTime(g.at1)}: {g.minutes} min, {g.near.replace(/ Amtrak( Station)?/g, '')}</li>)}
        {gaps.length > longGaps.length && <li>and {gaps.length - longGaps.length} short drops under 5 min</li>}</ul> : <p>No further modelled gaps.</p>}
    </section>}
    <section><h2>{data.ride.vehicle.name} <small>{data.run && `(run ${data.run})`}</small></h2>
      <p>{data.ride.board} → {data.ride.alight} · {replay ? 'Replay' : data.ride.state}</p>
      {previous && <p><strong>{lateness(previous.late_min)}</strong> leaving {previous.name} at {clockTime(previous.dep)}</p>}
      {replay ? <p>GPS fix, measured speed and heading unavailable in this logbook.</p> : data.fix ? <p>GPS fix {Math.max(0, Math.floor((now - Date.parse(data.fix.at)) / 60000))} min ago · {data.fix.speed_mph === null ? 'speed unknown' : `${data.fix.speed_mph} mph`} · heading {data.fix.heading ?? 'unknown'}</p> : <p>{data.fix_unavailable_reason ?? 'GPS fix unavailable'}</p>}
      <p className="ride-meta">Times in {timeZone}{replay ? ' · future times reconstructed from the logbook' : ''}</p>
      <table><caption>Next stops</caption><thead><tr><th>Stop</th><th>Scheduled</th><th>{replay ? 'Recorded / est.' : 'Estimated'}</th><th>Late</th></tr></thead>
        <tbody>{next.map(({ stop, arrival }) => <tr key={stop.code}><th scope="row">{stop.name}</th><td>{clockTime(stop.sched_arr ?? stop.sched_dep)}</td><td>{clockTime(arrival)}{!stop.arr && !stop.dep ? '*' : ''}</td><td>{lateness(stop.sched_arr || stop.sched_dep ? (arrival - Date.parse((stop.sched_arr ?? stop.sched_dep)!)) / 60000 : null)}</td></tr>)}</tbody></table>
      {!next.length && <p>{data.ride.state === 'arrived' ? 'End of ride.' : 'Next stop unavailable.'}</p>}
      {next.length > 0 && <p>{historyLine(data, next[0].stop.code)}</p>}
      {next.some(e => !e.stop.arr && !e.stop.dep) && <p className="ride-meta">* Schedule plus last known lateness.</p>}
    </section>
    {leg && <p className="ride-meta">{leg.check?.score ? `Model agrees with route guide on ${leg.check.score.agree} of ${leg.check.score.total} landmarks.` : leg.check ? 'Route-guide check written, not yet scored.' : 'Unchecked view model.'}</p>}
  </article>
}
