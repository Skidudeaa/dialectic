import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useLongwayJourney } from '../../hooks/useLongwayJourney'

export function LongwayLibrary({ roomId }: { roomId: string }) {
  const { data, error, loading, unbound, refresh } = useLongwayJourney(roomId)
  if (error) return <p role="alert">{error} <button onClick={refresh}>Retry journey</button></p>
  if (unbound) return <p>This room is not yet linked to a journey.</p>
  if (loading || !data) return <p role="status">Loading journey…</p>
  return <div className="longway-library scene-body">
    {!/^#\s/.test(data.dossier.trimStart()) && <h2>{data.title}</h2>}
    <section aria-label="Dossier" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(data.dossier, { async: false })) }} />
    <section aria-label="Evidence ledger"><h2>Evidence ledger</h2>{data.evidence.map(row => <article key={row.id} className={`longway-card${row.faded ? ' is-faded' : ''}`}>
      <h3>{row.id} · {row.claim}</h3><p>{row.status}{row.checked_at ? ` · checked ${new Date(`${row.checked_at}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })}` : ''}</p>
      {row.faded && <p>past its recheck rule</p>}<p>{row.scope}</p>
      {row.url ? <a href={row.url} target="_blank" rel="noopener noreferrer">{row.publisher ?? row.url}</a> : <p>{row.publisher}</p>}
    </article>)}</section>
    <section aria-label="Vehicles"><h2>Vehicles</h2>{data.vehicles.map(vehicle => <article key={vehicle.name} className="longway-card"><h3>{vehicle.name}</h3>
      <p>{vehicle.fix ? `heard ${Math.floor(vehicle.fix.age_min)} min ago · ${vehicle.fix.lat}, ${vehicle.fix.lon}${vehicle.fix.place ? ` · ${vehicle.fix.place}` : ''}` : 'never heard'}</p>
      <p>{vehicle.note}</p>{vehicle.timetable && <a href={vehicle.timetable} target="_blank" rel="noopener noreferrer">Published timetable</a>}
    </article>)}</section>
    <h2>Room readings</h2>
  </div>
}
